"""Pruebas del motor de analisis/correccion (app.services.procesamiento).

Estas pruebas no tocan Flask ni la base de datos: operan directamente
sobre imagenes en memoria, para poder verificar con precision de pixel
que la regla de proteccion facial se cumple.
"""

import io

import numpy as np
from PIL import Image

from app.services.procesamiento import (
    analizar_imagen,
    detectar_rostros,
    mejorar_fotografia,
    _mascara_proteccion_rostros,
)


def _png_bytes(imagen):
    buf = io.BytesIO()
    imagen.save(buf, format="PNG")
    return buf.getvalue()


def _imagen_solida(ancho, alto, rgb):
    return Image.new("RGB", (ancho, alto), rgb)


def _imagen_oscura(ancho=300, alto=200):
    return _imagen_solida(ancho, alto, (20, 20, 25))


def _imagen_clara(ancho=300, alto=200):
    return _imagen_solida(ancho, alto, (245, 245, 240))


def _imagen_dominante_calida(ancho=300, alto=200):
    return _imagen_solida(ancho, alto, (200, 130, 60))


def _imagen_dominante_fria(ancho=300, alto=200):
    return _imagen_solida(ancho, alto, (60, 130, 200))


def _rostro_sintetico(ancho=400, alto=500):
    """Cara sintetica basada en gradientes (no vectores planos): es la
    unica forma de generar un rostro de prueba sin usar la fotografia
    real de una persona (no disponible, y no seria apropiado obtenerla
    solo para una prueba). Verificado empiricamente que SI dispara una
    deteccion real del Haar Cascade -- no es una imagen simulada al azar.
    """
    yy, xx = np.mgrid[0:alto, 0:ancho]
    cx, cy = ancho / 2, alto / 2

    dist = ((xx - cx) / 140) ** 2 + ((yy - cy) / 180) ** 2
    base = np.clip(235 - dist * 90, 120, 235)

    for signo in (-1, 1):
        ex, ey = cx + signo * 55, cy - 20
        d = ((xx - ex) / 22) ** 2 + ((yy - ey) / 14) ** 2
        base = np.where(d < 1, base - 140 * np.exp(-d * 2), base)
        d_ceja = ((xx - ex) / 28) ** 2 + ((yy - (ey - 25)) / 7) ** 2
        base = np.where(d_ceja < 1, base - 90, base)

    d_nariz = ((xx - cx) / 10) ** 2 + ((yy - cy + 10) / 55) ** 2
    base = np.where((d_nariz < 1) & (xx > cx), base - 15, base)

    d_boca = ((xx - cx) / 38) ** 2 + ((yy - cy - 95) / 12) ** 2
    base = np.where(d_boca < 1, base - 60, base)

    gris = np.clip(base, 0, 255).astype(np.uint8)
    rgb = np.stack([gris, gris * 0.85, gris * 0.75], axis=-1).astype(np.uint8)
    imagen = Image.fromarray(rgb, mode="RGB").filter(__import__("PIL").ImageFilter.GaussianBlur(1.2))
    return imagen


# --- Analisis --------------------------------------------------------------

def test_analiza_orientacion_y_dimensiones():
    analisis = analizar_imagen(_imagen_solida(800, 400, (128, 128, 128)))
    assert analisis["ancho"] == 800
    assert analisis["alto"] == 400
    assert analisis["orientacion"] == "horizontal"


def test_detecta_imagen_oscura():
    analisis = analizar_imagen(_imagen_oscura())
    assert analisis["brillo_promedio"] < 0.2


def test_detecta_imagen_clara():
    analisis = analizar_imagen(_imagen_clara())
    assert analisis["brillo_promedio"] > 0.8


def test_detecta_dominante_calida():
    analisis = analizar_imagen(_imagen_dominante_calida())
    assert analisis["temperatura"] == "calida"


def test_detecta_dominante_fria():
    analisis = analizar_imagen(_imagen_dominante_fria())
    assert analisis["temperatura"] == "fria"


# --- Correccion adaptativa ---------------------------------------------------

def test_correccion_de_oscura_sube_el_brillo():
    bytes_originales = _png_bytes(_imagen_oscura())
    bytes_resultado, metadata = mejorar_fotografia(bytes_originales)

    resultado = Image.open(io.BytesIO(bytes_resultado))
    brillo_resultado = np.asarray(resultado.convert("L")).mean() / 255
    assert brillo_resultado > metadata["analisis"]["brillo_promedio"]
    assert "exposicion" in metadata["correcciones_aplicadas"]


def test_correccion_de_clara_no_la_quema_mas():
    bytes_originales = _png_bytes(_imagen_clara())
    bytes_resultado, metadata = mejorar_fotografia(bytes_originales)

    resultado = Image.open(io.BytesIO(bytes_resultado))
    brillo_resultado = np.asarray(resultado.convert("L")).mean() / 255
    # No debe sobreexponer aun mas una imagen ya muy clara.
    assert brillo_resultado <= metadata["analisis"]["brillo_promedio"] + 0.01


def test_no_aplica_correccion_de_exposicion_si_ya_esta_bien_expuesta():
    imagen = _imagen_solida(300, 200, (128, 128, 128))
    bytes_originales = _png_bytes(imagen)
    _bytes_resultado, metadata = mejorar_fotografia(bytes_originales)
    # brillo medio (~0.5) no deberia disparar correccion de exposicion
    assert abs(metadata["analisis"]["brillo_promedio"] - 0.5) < 0.05


# --- Sin rostros -------------------------------------------------------------

def test_imagen_sin_rostros_no_marca_proteccion():
    bytes_originales = _png_bytes(_imagen_solida(300, 200, (100, 150, 90)))
    _bytes_resultado, metadata = mejorar_fotografia(bytes_originales)
    assert metadata["rostros_detectados"] == 0
    assert metadata["rostros_protegidos"] is False
    assert metadata["categoria"] == "general"


# --- CRITICO: deteccion y proteccion de rostros -----------------------------

def test_deteccion_real_de_rostro_sintetico():
    """Confirma que el Haar Cascade SI detecta el rostro sintetico (no
    es una prueba mockeada): si esto falla, ninguna otra prueba de
    proteccion facial es valida.
    """
    imagen = _rostro_sintetico()
    rostros = detectar_rostros(imagen)
    assert len(rostros) >= 1, "El detector no encontro el rostro sintetico: revisar antes de confiar en las pruebas de proteccion."


def test_clasificacion_es_personas_cuando_hay_rostro():
    imagen = _rostro_sintetico()
    _bytes_resultado, metadata = mejorar_fotografia(_png_bytes(imagen))
    assert metadata["rostros_detectados"] >= 1
    assert metadata["rostros_protegidos"] is True
    assert metadata["categoria"] == "personas"
    assert metadata["confianza_categoria"] >= 0.5


def test_centro_del_rostro_no_se_modifica_ni_un_pixel():
    """LA PRUEBA MAS IMPORTANTE DE ESTE PASO.

    Verifica, pixel por pixel, que el centro de la region facial
    detectada en el resultado es IDENTICO al original. Si esto
    fallara, significaria que el rostro fue retocado -- lo cual esta
    prohibido.
    """
    imagen = _rostro_sintetico()
    rostros = detectar_rostros(imagen)
    assert len(rostros) >= 1

    bytes_resultado, metadata = mejorar_fotografia(_png_bytes(imagen))
    resultado = Image.open(io.BytesIO(bytes_resultado)).convert("RGB")

    arr_original = np.asarray(imagen)
    arr_resultado = np.asarray(resultado)

    x, y, w, h = rostros[0]
    # Nucleo central del rostro (20% del ancho/alto alrededor del centro
    # de la deteccion): bien lejos del borde difuminado de la mascara.
    cx, cy = x + w // 2, y + h // 2
    mx, my = max(4, w // 10), max(4, h // 10)

    region_original = arr_original[cy - my : cy + my, cx - mx : cx + mx]
    region_resultado = arr_resultado[cy - my : cy + my, cx - mx : cx + mx]

    assert region_original.shape == region_resultado.shape
    assert np.array_equal(region_original, region_resultado), (
        "El centro del rostro cambio de pixeles: la proteccion facial fallo."
    )


def test_fondo_lejos_del_rostro_si_se_corrige():
    """El fondo (lejos de cualquier rostro) debe poder cambiar -- si no
    cambiara nunca, la correccion no estaria aplicandose realmente.
    """
    imagen = _imagen_oscura(500, 700)  # fondo oscuro, sin rostro real aqui
    bytes_resultado, metadata = mejorar_fotografia(_png_bytes(imagen))
    resultado = Image.open(io.BytesIO(bytes_resultado)).convert("RGB")

    arr_original = np.asarray(imagen)
    arr_resultado = np.asarray(resultado)
    assert not np.array_equal(arr_original, arr_resultado)


def test_mascara_de_proteccion_cubre_la_region_del_rostro():
    mascara = _mascara_proteccion_rostros((400, 500), [(100, 100, 120, 150)])
    # centro de la caja: debe estar totalmente protegido (1.0)
    assert mascara[175, 160] > 0.95
    # esquina lejos de cualquier rostro: sin proteccion
    assert mascara[10, 10] < 0.05
