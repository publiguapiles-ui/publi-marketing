"""Pruebas del motor de formatos/logo (app.services.formatos).

Igual que tests/test_procesamiento.py: no tocan Flask ni la base de
datos, operan directamente sobre imagenes en memoria.
"""

import io

import numpy as np
from PIL import Image

from app.services.formatos import (
    FORMATOS_FIJOS,
    MENSAJE_ENCUADRE_IMPERFECTO,
    advertencia_resolucion_logo,
    aplicar_logo,
    aplicar_recorte,
    calcular_ventana_formato,
    generar_formato,
    tiene_transparencia,
)


def _png_bytes(imagen):
    buf = io.BytesIO()
    imagen.save(buf, format="PNG")
    return buf.getvalue()


def _imagen_solida(ancho, alto, rgb):
    return Image.new("RGB", (ancho, alto), rgb)


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


# --- Recorte: nunca deforma -----------------------------------------------------
# El motor de recorte por puntuacion de candidatos (Paso 9) se prueba a
# fondo en tests/test_encuadre.py; aqui solo se verifica que la
# composicion (formatos + logo) siga funcionando sobre el nuevo motor.

def test_recorte_nunca_deforma_produce_tamano_exacto():
    calculo = calcular_ventana_formato(2000, 500, "formato_cuadrado", rostros=[])
    imagen = _imagen_solida(2000, 500, (10, 20, 30))
    recorte, _caja = aplicar_recorte(imagen, calculo["ventana"], calculo["ancho_objetivo"], calculo["alto_objetivo"])
    assert calculo["advertencia"] is None
    assert recorte.size == (1080, 1080)


def test_generar_formato_siempre_produce_un_archivo():
    """Paso 9: ya no se rechaza silenciosamente. Un rostro que cubre casi
    todo el ancho de una imagen muy ancha hace que CUALQUIER posicion de
    la ventana de recorte lo toque sin poder contenerlo completo -- no
    hay forma de evitarlo, asi que se genera igual el archivo (el mejor
    encuadre posible) con la advertencia explicita en vez de fallar.
    """
    base = _png_bytes(_imagen_solida(3000, 400, (50, 50, 50)))
    rostros = [(200, 50, 2600, 300)]  # cubre casi todo el ancho: ninguna posicion evita tocarlo
    bytes_resultado, metadata = generar_formato(base, "formato_cuadrado", rostros=rostros)
    assert bytes_resultado is not None
    resultado = Image.open(io.BytesIO(bytes_resultado))
    assert resultado.size == (1080, 1080)
    assert metadata["advertencia"] == MENSAJE_ENCUADRE_IMPERFECTO


def test_generar_formato_prefiere_excluir_por_completo_a_cortar_a_medias():
    """Decision de diseno deliberada: entre un candidato que corta a un
    rostro por la mitad y uno que simplemente lo deja fuera del
    encuadre, se prefiere dejarlo fuera -- un rostro cortado se ve como
    un error obvio; uno ausente se ve como un encuadre distinto, no
    roto. Aqui el rostro es mas ancho que la ventana pero esta acotado
    (no cubre casi toda la imagen), asi que SI existe una posicion que
    lo evita del todo.
    """
    base = _png_bytes(_imagen_solida(3000, 400, (50, 50, 50)))
    rostros = [(1100, 50, 800, 300)]
    bytes_resultado, metadata = generar_formato(base, "formato_cuadrado", rostros=rostros)
    assert bytes_resultado is not None
    assert metadata["advertencia"] is None


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
