"""Pruebas del motor de formatos/logo (app.services.formatos).

Igual que tests/test_procesamiento.py: no tocan Flask ni la base de
datos, operan directamente sobre imagenes en memoria.
"""

import io

import numpy as np
from PIL import Image

from app.services.formatos import (
    FORMATOS_FIJOS,
    MENSAJE_SIN_ENCUADRE_SEGURO,
    advertencia_resolucion_logo,
    aplicar_logo,
    generar_formato,
    recorte_inteligente,
    tiene_transparencia,
)
from app.services.procesamiento import detectar_rostros


def _png_bytes(imagen):
    buf = io.BytesIO()
    imagen.save(buf, format="PNG")
    return buf.getvalue()


def _imagen_solida(ancho, alto, rgb):
    return Image.new("RGB", (ancho, alto), rgb)


def _rostro_sintetico(ancho=400, alto=500):
    """Identico al helper de test_procesamiento.py: gradientes, no
    vectores planos -- es lo unico que dispara una deteccion real del
    Haar Cascade sin usar la foto de una persona real.
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
    from PIL import ImageFilter

    return Image.fromarray(rgb, mode="RGB").filter(ImageFilter.GaussianBlur(1.2))


def _logo_rgba(ancho, alto, rgb_opaco, con_zona_transparente=False):
    logo = Image.new("RGBA", (ancho, alto), (*rgb_opaco, 255))
    if con_zona_transparente:
        transparente = Image.new("RGBA", (ancho // 2, alto), (0, 0, 0, 0))
        logo.paste(transparente, (0, 0))
    return logo


def _png_bytes_rgba(imagen):
    buf = io.BytesIO()
    imagen.save(buf, format="PNG")
    return buf.getvalue()


# --- Dimensiones exactas de los formatos fijos --------------------------------

def test_formato_cuadrado_dimensiones_exactas():
    base = _png_bytes(_imagen_solida(1600, 900, (80, 100, 120)))
    bytes_resultado, metadata = generar_formato(base, "formato_cuadrado", rostros=[])
    resultado = Image.open(io.BytesIO(bytes_resultado))
    assert resultado.size == (1080, 1080) == FORMATOS_FIJOS["formato_cuadrado"]
    assert metadata["ancho_px"] == 1080 and metadata["alto_px"] == 1080


def test_formato_vertical_dimensiones_exactas():
    base = _png_bytes(_imagen_solida(900, 1600, (80, 100, 120)))
    bytes_resultado, metadata = generar_formato(base, "formato_vertical", rostros=[])
    resultado = Image.open(io.BytesIO(bytes_resultado))
    assert resultado.size == (1080, 1350) == FORMATOS_FIJOS["formato_vertical"]


def test_formato_historia_dimensiones_exactas():
    base = _png_bytes(_imagen_solida(1200, 800, (80, 100, 120)))
    bytes_resultado, metadata = generar_formato(base, "formato_historia", rostros=[])
    resultado = Image.open(io.BytesIO(bytes_resultado))
    assert resultado.size == (1080, 1920) == FORMATOS_FIJOS["formato_historia"]


def test_formato_horizontal_preserva_proporcion_original():
    base = _png_bytes(_imagen_solida(1600, 900, (80, 100, 120)))  # 16:9
    bytes_resultado, metadata = generar_formato(base, "formato_horizontal", rostros=[])
    resultado = Image.open(io.BytesIO(bytes_resultado))
    proporcion_original = 1600 / 900
    proporcion_resultado = resultado.width / resultado.height
    assert abs(proporcion_original - proporcion_resultado) < 0.01
    assert max(resultado.size) <= 1920


# --- Recorte inteligente: nunca deforma ---------------------------------------

def test_recorte_nunca_deforma_produce_tamano_exacto():
    imagen = _imagen_solida(2000, 500, (10, 20, 30))
    recorte, advertencia = recorte_inteligente(imagen, 1080, 1080, rostros=[])
    assert advertencia is None
    assert recorte.size == (1080, 1080)


# --- Recorte inteligente + rostros: la prueba mas importante de este paso -----

def test_recorte_evita_cortar_rostro_cuando_es_posible():
    """Si existe un encuadre seguro, el rostro debe seguir siendo
    detectable en el resultado recortado -- se usa el propio detector
    real (no una suposicion) como verificacion.
    """
    imagen = _rostro_sintetico(800, 600)
    rostros = detectar_rostros(imagen)
    assert len(rostros) >= 1, "El detector no encontro el rostro sintetico."

    recorte, advertencia = recorte_inteligente(imagen, 1080, 1350, rostros)
    assert advertencia is None
    assert recorte is not None

    rostros_en_recorte = detectar_rostros(recorte)
    assert len(rostros_en_recorte) >= 1, "El rostro desaparecio del recorte: la proteccion de encuadre fallo."


def test_recorte_advierte_cuando_no_hay_encuadre_seguro():
    """Dos rostros separados por casi todo el ancho de una imagen muy
    ancha: ningun recorte cuadrado de 1080px puede incluir a ambos.
    """
    imagen = _imagen_solida(3000, 400, (50, 50, 50))
    rostros = [(0, 150, 100, 100), (2900, 150, 100, 100)]

    recorte, advertencia = recorte_inteligente(imagen, 1080, 1080, rostros)
    assert recorte is None
    assert advertencia == MENSAJE_SIN_ENCUADRE_SEGURO


def test_generar_formato_no_produce_archivo_sin_encuadre_seguro():
    base = _png_bytes(_imagen_solida(3000, 400, (50, 50, 50)))
    rostros = [(0, 150, 100, 100), (2900, 150, 100, 100)]
    bytes_resultado, metadata = generar_formato(base, "formato_cuadrado", rostros=rostros)
    assert bytes_resultado is None
    assert metadata["advertencia"] == MENSAJE_SIN_ENCUADRE_SEGURO


# --- Logo: transparencia, proporcion, posicion ---------------------------------

def test_tiene_transparencia_detecta_alpha_real():
    opaco = Image.new("RGBA", (10, 10), (255, 0, 0, 255))
    transparente = Image.new("RGBA", (10, 10), (255, 0, 0, 0))
    assert tiene_transparencia(opaco) is False
    assert tiene_transparencia(transparente) is True


def test_logo_transparente_no_agrega_fondo_blanco():
    """Donde el logo es 100% transparente, el pixel de fondo original
    debe quedar intacto -- nunca se rellena con blanco ni se aplana la
    transparencia antes de componer.
    """
    color_fondo = (30, 60, 90)
    base = _imagen_solida(1080, 1080, color_fondo)

    logo_ancho, logo_alto = 400, 200
    logo = Image.new("RGBA", (logo_ancho, logo_alto), (0, 0, 0, 0))  # 100% transparente
    logo_bytes = _png_bytes_rgba(logo)

    resultado = aplicar_logo(base, logo_bytes, posicion="centro", opacidad=1.0)
    arr = np.asarray(resultado)
    cx, cy = 1080 // 2, 1080 // 2
    assert tuple(arr[cy, cx]) == color_fondo


def test_logo_no_se_deforma_mantiene_proporcion():
    """El logo es rectangular (3:1). El area que realmente cambia en el
    lienzo (fuera de la zona transparente) debe conservar esa
    proporcion aproximada, no la proporcion del lienzo cuadrado.
    """
    color_fondo = (0, 0, 0)
    base = _imagen_solida(1000, 1000, color_fondo)
    logo = _logo_rgba(300, 100, (255, 255, 255))  # 3:1, totalmente opaco
    logo_bytes = _png_bytes_rgba(logo)

    resultado = aplicar_logo(base, logo_bytes, posicion="centro", opacidad=1.0)
    arr = np.asarray(resultado)
    distinto = np.any(arr != np.array(color_fondo), axis=-1)
    filas = np.where(distinto.any(axis=1))[0]
    columnas = np.where(distinto.any(axis=0))[0]
    ancho_pintado = columnas.max() - columnas.min() + 1
    alto_pintado = filas.max() - filas.min() + 1
    proporcion = ancho_pintado / alto_pintado
    assert abs(proporcion - 3.0) < 0.15, f"El logo se deformo: proporcion resultante {proporcion}"


def test_advertencia_resolucion_logo_baja():
    assert advertencia_resolucion_logo(logo_ancho=20, logo_alto=10, ancho_lienzo_objetivo=1080) is not None
    assert advertencia_resolucion_logo(logo_ancho=600, logo_alto=300, ancho_lienzo_objetivo=1080) is None


def test_posicion_inferior_derecha_no_toca_esquina_opuesta():
    color_fondo = (10, 10, 10)
    base = _imagen_solida(1080, 1080, color_fondo)
    logo = _logo_rgba(200, 200, (255, 255, 255))
    logo_bytes = _png_bytes_rgba(logo)

    resultado = aplicar_logo(base, logo_bytes, posicion="inferior_derecha", opacidad=1.0)
    arr = np.asarray(resultado)
    assert tuple(arr[10, 10]) == color_fondo  # esquina superior izquierda intacta


def test_generar_formato_con_logo_aplica_composicion():
    base = _png_bytes(_imagen_solida(1600, 900, (20, 40, 60)))
    logo_bytes = _png_bytes_rgba(_logo_rgba(300, 150, (255, 200, 0)))

    bytes_resultado, metadata = generar_formato(
        base, "formato_cuadrado", rostros=[], logo_bytes=logo_bytes, aplicacion="logo", posicion="inferior_derecha", opacidad=0.9
    )
    assert bytes_resultado is not None
    resultado = Image.open(io.BytesIO(bytes_resultado))
    assert resultado.size == (1080, 1080)
    arr = np.asarray(resultado)
    # Tolerancia de compresion JPEG (guardado con calidad 95, no sin
    # perdida como la mejora automatica): la esquina opuesta al logo no
    # deberia cambiar de forma perceptible, aunque JPEG no garantiza
    # pixeles identicos en ningun punto de la imagen.
    assert np.abs(arr[5, 5].astype(int) - np.array([20, 40, 60])).max() <= 3
