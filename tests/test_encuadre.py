"""Pruebas del recorte inteligente por puntuacion de candidatos (Paso 9):
sujeto principal sin rostros, varias personas, punto de enfoque manual
y zoom. No tocan Flask ni la base de datos -- igual que
tests/test_formatos.py y tests/test_procesamiento.py.
"""

import io

import numpy as np
from PIL import Image, ImageFilter

from app.services.formatos import (
    MENSAJE_ENCUADRE_IMPERFECTO,
    calcular_saliencia,
    calcular_ventana_formato,
    generar_formato,
    puntaje_ventana,
)
from app.services.procesamiento import detectar_rostros


def _png_bytes(imagen):
    buf = io.BytesIO()
    imagen.save(buf, format="PNG")
    return buf.getvalue()


def _imagen_solida(ancho, alto, rgb):
    return Image.new("RGB", (ancho, alto), rgb)


def _parche_rostro(ancho=300, alto=400):
    """Parche cuadrado/rectangular con un rostro sintetico centrado --
    identica tecnica (gradientes, no vectores planos) y proporciones
    verificadas empiricamente en tests/test_procesamiento.py, solo
    parametrizada para poder pegarse en cualquier posicion de un
    lienzo mas grande via Image.paste().
    """
    yy, xx = np.mgrid[0:alto, 0:ancho]
    cx, cy = ancho / 2, alto / 2
    escala = ancho / 400

    dist = ((xx - cx) / (140 * escala)) ** 2 + ((yy - cy) / (180 * escala)) ** 2
    base = np.clip(235 - dist * 90, 120, 235)

    for signo in (-1, 1):
        ex, ey = cx + signo * 55 * escala, cy - 20 * escala
        d = ((xx - ex) / (22 * escala)) ** 2 + ((yy - ey) / (14 * escala)) ** 2
        base = np.where(d < 1, base - 140 * np.exp(-d * 2), base)
        d_ceja = ((xx - ex) / (28 * escala)) ** 2 + ((yy - (ey - 25 * escala)) / (7 * escala)) ** 2
        base = np.where(d_ceja < 1, base - 90, base)

    d_nariz = ((xx - cx) / (10 * escala)) ** 2 + ((yy - cy + 10 * escala) / (55 * escala)) ** 2
    base = np.where((d_nariz < 1) & (xx > cx), base - 15, base)

    d_boca = ((xx - cx) / (38 * escala)) ** 2 + ((yy - cy - 95 * escala) / (12 * escala)) ** 2
    base = np.where(d_boca < 1, base - 60, base)

    gris = np.clip(base, 0, 255).astype(np.uint8)
    rgb = np.stack([gris, gris * 0.85, gris * 0.75], axis=-1).astype(np.uint8)
    return Image.fromarray(rgb, mode="RGB").filter(ImageFilter.GaussianBlur(1.2))


def _lienzo_con_rostros(ancho, alto, centros, fondo=(80, 90, 70), tamano_parche=(300, 400)):
    """Imagen RGB con un rostro sintetico PEGADO (no mezclado por
    formula) en cada posicion de `centros` -- pegar copias identicas
    del mismo parche probado es lo que garantiza que el detector real
    los siga reconociendo a todos, sin importar cuantos haya.
    """
    imagen = Image.new("RGB", (ancho, alto), fondo)
    parche = _parche_rostro(*tamano_parche)
    pw, ph = tamano_parche
    for cx, cy in centros:
        imagen.paste(parche, (int(cx - pw / 2), int(cy - ph / 2)))
    return imagen


# --- Sin personas: sujeto principal por saliencia, nunca "solo el centro" -----

def test_sin_rostros_horizontal_no_deforma_y_usa_saliencia():
    ancho, alto = 1600, 900
    imagen = _imagen_solida(ancho, alto, (30, 30, 30))
    arr = np.asarray(imagen).copy()
    arr[300:700, 1100:1500] = (240, 200, 60)  # bloque de alto contraste a la derecha
    imagen_con_sujeto = Image.fromarray(arr)

    cx, _cy = calcular_saliencia(imagen_con_sujeto)
    assert cx > 0.6, "La saliencia deberia inclinarse hacia el bloque de alto contraste (derecha)."

    bytes_resultado, metadata = generar_formato(_png_bytes(imagen_con_sujeto), "formato_cuadrado", rostros=[])
    resultado = Image.open(io.BytesIO(bytes_resultado))
    assert resultado.size == (1080, 1080)
    assert metadata["algoritmo_recorte"] == "saliencia"
    # El recorte debe haberse desplazado hacia la derecha (no el centro geometrico).
    assert metadata["crop_x"] > (ancho - metadata["crop_width"]) / 2


def test_sin_rostros_vertical_dimensiones_exactas():
    base = _png_bytes(_imagen_solida(900, 1600, (50, 60, 70)))
    bytes_resultado, metadata = generar_formato(base, "formato_vertical", rostros=[])
    resultado = Image.open(io.BytesIO(bytes_resultado))
    assert resultado.size == (1080, 1350)


def test_sin_rostros_cuadrada_dimensiones_exactas():
    base = _png_bytes(_imagen_solida(1000, 1000, (50, 60, 70)))
    bytes_resultado, metadata = generar_formato(base, "formato_historia", rostros=[])
    resultado = Image.open(io.BytesIO(bytes_resultado))
    assert resultado.size == (1080, 1920)


# --- Una persona: el rostro se conserva -----------------------------------------

def test_una_persona_rostro_conservado_en_el_resultado():
    imagen = _lienzo_con_rostros(800, 600, [(400, 300)])
    rostros = detectar_rostros(imagen)
    assert len(rostros) >= 1, "El detector no encontro el rostro sintetico."

    bytes_resultado, metadata = generar_formato(_png_bytes(imagen), "formato_vertical", rostros=rostros)
    resultado = Image.open(io.BytesIO(bytes_resultado)).convert("RGB")
    assert metadata["algoritmo_recorte"] == "rostros"
    assert metadata["advertencia"] is None

    rostros_en_resultado = detectar_rostros(resultado)
    assert len(rostros_en_resultado) >= 1, "El rostro desaparecio del resultado."


# --- Varias personas: se conserva el maximo razonable ---------------------------

def test_varias_personas_conserva_la_mayoria_cuando_es_posible():
    """Tres rostros razonablemente cercanos entre si en una imagen
    ancha: el mejor candidato deberia poder conservarlos a todos (o
    casi todos) en vez de arbitrariamente solo al primero.
    """
    imagen = _lienzo_con_rostros(1400, 700, [(400, 350), (700, 350), (1000, 350)])
    rostros = detectar_rostros(imagen)
    assert len(rostros) >= 2, "El detector deberia encontrar al menos 2 de los 3 rostros sinteticos."

    # formato_cuadrado (no historia): en este lienzo da una ventana mas
    # ancha, suficiente para conservar a la mayoria de las 3 personas.
    calculo = calcular_ventana_formato(1400, 700, "formato_cuadrado", rostros)
    ventana = calculo["ventana"]
    rostros_norm = [(x / 1400, y / 700, (x + w) / 1400, (y + h) / 700) for (x, y, w, h) in rostros]

    conservados = sum(
        1
        for caja in rostros_norm
        if caja[0] >= ventana[0] - 1e-6 and caja[1] >= ventana[1] - 1e-6 and caja[2] <= ventana[2] + 1e-6 and caja[3] <= ventana[3] + 1e-6
    )
    assert conservados >= len(rostros) - 1, "Se perdieron demasiados rostros pudiendo conservar mas."


def test_puntaje_ventana_premia_mas_rostros_conservados():
    """El sistema de puntuacion (Paso 9, punto 20) es determinista y
    testeable de forma aislada: una ventana que conserva 2 rostros debe
    puntuar mas que una que solo conserva 1.
    """
    rostros_norm = [(0.1, 0.1, 0.2, 0.2), (0.5, 0.1, 0.6, 0.2)]
    ventana_ambos = (0.0, 0.0, 0.7, 0.3)
    ventana_uno = (0.0, 0.0, 0.3, 0.3)
    assert puntaje_ventana(ventana_ambos, rostros_norm) > puntaje_ventana(ventana_uno, rostros_norm)


# --- Focus point manual: siempre respetado --------------------------------------

def test_focus_point_manual_es_respetado():
    calculo = calcular_ventana_formato(2000, 800, "formato_cuadrado", rostros=[], modo="manual", focus_x=0.85, focus_y=0.5)
    x0, y0, x1, y1 = calculo["ventana"]
    assert x0 <= 0.85 <= x1
    assert y0 <= 0.5 <= y1
    assert calculo["algoritmo"] == "manual"
    assert calculo["focus_x"] == 0.85


def test_manual_tiene_prioridad_sobre_automatico_aunque_haya_rostros():
    """La seleccion manual del usuario siempre gana (Paso 9, punto 12),
    incluso si hay rostros detectados que el modo automatico usaria.
    """
    rostros = [(50, 50, 100, 100)]  # rostro cerca de la esquina superior izquierda
    calculo = calcular_ventana_formato(2000, 800, "formato_cuadrado", rostros, modo="manual", focus_x=0.9, focus_y=0.5)
    assert calculo["algoritmo"] == "manual"
    x0, y0, x1, y1 = calculo["ventana"]
    assert x0 > 0.5, "El encuadre manual deberia estar del lado derecho, ignorando el rostro de la izquierda."


def test_zoom_reduce_el_area_del_encuadre():
    sin_zoom = calcular_ventana_formato(2000, 2000, "formato_cuadrado", rostros=[], modo="manual", focus_x=0.5, focus_y=0.5, zoom=1.0)
    con_zoom = calcular_ventana_formato(2000, 2000, "formato_cuadrado", rostros=[], modo="manual", focus_x=0.5, focus_y=0.5, zoom=2.0)
    ancho_sin_zoom = sin_zoom["ventana"][2] - sin_zoom["ventana"][0]
    ancho_con_zoom = con_zoom["ventana"][2] - con_zoom["ventana"][0]
    assert ancho_con_zoom < ancho_sin_zoom


# --- Encuadre imposible: nunca se rechaza silenciosamente -----------------------

def test_advertencia_explicita_cuando_no_se_puede_evitar_cortar():
    base = _png_bytes(_imagen_solida(3000, 400, (50, 50, 50)))
    rostros = [(200, 50, 2600, 300)]
    bytes_resultado, metadata = generar_formato(base, "formato_cuadrado", rostros=rostros)
    assert bytes_resultado is not None
    assert metadata["advertencia"] == MENSAJE_ENCUADRE_IMPERFECTO


# --- Logo: permanece dentro del resultado ----------------------------------------

def test_logo_permanece_dentro_de_los_limites_del_resultado():
    from app.services.formatos import aplicar_logo

    base = _imagen_solida(1080, 1080, (10, 10, 10))
    logo = Image.new("RGBA", (2000, 2000), (255, 0, 0, 255))  # logo mas grande que el lienzo
    buf = io.BytesIO()
    logo.save(buf, format="PNG")

    resultado = aplicar_logo(base, buf.getvalue(), posicion="inferior_derecha", opacidad=1.0)
    assert resultado.size == (1080, 1080), "El logo no debe hacer crecer el lienzo final."
