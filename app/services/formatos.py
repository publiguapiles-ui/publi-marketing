"""Motor de composicion de formatos para redes sociales (Paso 8).

Regla absoluta (igual que en app/services/procesamiento.py): este
modulo nunca recibe una ruta de Storage ni escribe sobre el original.
Opera enteramente en memoria sobre los bytes que se le entregan y
devuelve bytes nuevos.

Flujo: ORIGINAL (o su version MEJORADA) -> recorte inteligente al
formato objetivo -> logo/marca de agua opcional -> archivo nuevo. El
recorte usa la deteccion de rostros de app/services/procesamiento.py
unicamente para evitar cortar una cabeza/rostro -- nunca para
retocar, embellecer o identificar a nadie (misma regla del Paso 7).
"""

import io
import time

from PIL import Image

FORMATOS_FIJOS = {
    "formato_cuadrado": (1080, 1080),
    "formato_vertical": (1080, 1350),
    "formato_historia": (1080, 1920),
}
# El horizontal no tiene un tamano unico obligatorio (ver Paso 8, punto
# 14): conserva la proporcion original de la fotografia, solo se limita
# el lado mayor para no subir archivos innecesariamente grandes. Un
# formato horizontal especifico (ej. 1920x1080) queda para el Paso 9.
_LADO_MAXIMO_HORIZONTAL = 1920

TIPOS_FORMATO = list(FORMATOS_FIJOS.keys()) + ["formato_horizontal"]

# El logo ocupa un porcentaje del ancho del lienzo (nunca un tamano fijo
# en pixeles) para que se vea proporcional sin importar el formato.
_LOGO_ANCHO_PORCENTAJE = 0.12
_LOGO_ALTO_MAXIMO_PORCENTAJE = 0.30  # evita logos "gigantes" en fotos muy verticales
_MARGEN_PORCENTAJE = 0.04  # proporcional al lienzo, nunca pegado al borde
_OPACIDAD_MINIMA = 0.15  # nunca invisible, aunque el usuario pida menos
_OPACIDAD_MAXIMA = 1.0

MENSAJE_SIN_ENCUADRE_SEGURO = "No se encontró un encuadre seguro para este formato."


def cargar_imagen_preservando_alpha(bytes_originales):
    """Como procesamiento.cargar_imagen, pero SIN forzar RGB: si el
    archivo (tipicamente un logo) tiene transparencia, se conserva.
    """
    imagen = Image.open(io.BytesIO(bytes_originales))
    imagen.load()
    return imagen


def tiene_transparencia(imagen):
    if imagen.mode in ("RGBA", "LA", "PA"):
        canal_alfa = imagen.convert("RGBA").getchannel("A")
        return canal_alfa.getextrema()[0] < 255
    if imagen.mode == "P" and "transparency" in imagen.info:
        return True
    return False


def advertencia_resolucion_logo(logo_ancho, logo_alto, ancho_lienzo_objetivo):
    """Si el logo se tendria que ampliar (upscale) para verse al tamano
    proporcional esperado, la calidad se resiente -- se avisa en vez de
    "inventar" resolucion que el archivo original no tiene.
    """
    ancho_render = ancho_lienzo_objetivo * _LOGO_ANCHO_PORCENTAJE
    if logo_ancho < ancho_render * 0.9:
        return "El logo seleccionado tiene una resolución baja y podría perder calidad al aplicarlo."
    return None


def _tamano_objetivo(tipo_formato, ancho_base, alto_base):
    if tipo_formato in FORMATOS_FIJOS:
        return FORMATOS_FIJOS[tipo_formato]

    # formato_horizontal: conserva la proporcion original.
    lado_mayor = max(ancho_base, alto_base)
    if lado_mayor <= _LADO_MAXIMO_HORIZONTAL:
        return ancho_base, alto_base
    escala = _LADO_MAXIMO_HORIZONTAL / lado_mayor
    return max(1, round(ancho_base * escala)), max(1, round(alto_base * escala))


def _union_rostros(rostros):
    if not rostros:
        return None
    x0 = min(x for (x, y, w, h) in rostros)
    y0 = min(y for (x, y, w, h) in rostros)
    x1 = max(x + w for (x, y, w, h) in rostros)
    y1 = max(y + h for (x, y, w, h) in rostros)
    return x0, y0, x1, y1


def recorte_inteligente(imagen, ancho_objetivo, alto_objetivo, rostros=None):
    """Recorta (nunca deforma) `imagen` a la proporcion ancho_objetivo x
    alto_objetivo usando un recorte tipo "cover": se escala la imagen
    para cubrir por completo el lienzo objetivo y se recorta el
    sobrante de un solo eje.

    Si hay rostros detectados, el recorte se centra en la union de
    todos ellos (aproximacion automatica de "punto de enfoque" -- ver
    Paso 8 punto 16; un control manual queda para el Paso 9). Si ningun
    recorte puede incluir a todos los rostros, no se produce una imagen
    defectuosa: se devuelve (None, advertencia).

    Devuelve (imagen_recortada_o_None, advertencia_o_None).
    """
    ancho_src, alto_src = imagen.size
    if ancho_src <= 0 or alto_src <= 0 or ancho_objetivo <= 0 or alto_objetivo <= 0:
        return None, MENSAJE_SIN_ENCUADRE_SEGURO

    escala = max(ancho_objetivo / ancho_src, alto_objetivo / alto_src)
    nuevo_ancho = max(ancho_objetivo, round(ancho_src * escala))
    nuevo_alto = max(alto_objetivo, round(alto_src * escala))
    imagen_escalada = imagen.resize((nuevo_ancho, nuevo_alto), Image.LANCZOS)

    union = _union_rostros(rostros)
    if union is not None:
        fx0, fy0, fx1, fy1 = (v * escala for v in union)
    else:
        fx0 = fy0 = fx1 = fy1 = None

    sobrante_x = nuevo_ancho - ancho_objetivo
    sobrante_y = nuevo_alto - alto_objetivo

    if sobrante_x > 0:
        if fx0 is not None:
            if (fx1 - fx0) > ancho_objetivo:
                return None, MENSAJE_SIN_ENCUADRE_SEGURO
            rango_min = max(0, fx1 - ancho_objetivo)
            rango_max = min(sobrante_x, fx0)
            centro_ideal = (fx0 + fx1) / 2 - ancho_objetivo / 2
            crop_x0 = min(max(centro_ideal, rango_min), rango_max)
        else:
            crop_x0 = sobrante_x / 2
    else:
        crop_x0 = 0

    if sobrante_y > 0:
        if fy0 is not None:
            if (fy1 - fy0) > alto_objetivo:
                return None, MENSAJE_SIN_ENCUADRE_SEGURO
            rango_min = max(0, fy1 - alto_objetivo)
            rango_max = min(sobrante_y, fy0)
            centro_ideal = (fy0 + fy1) / 2 - alto_objetivo / 2
            crop_y0 = min(max(centro_ideal, rango_min), rango_max)
        else:
            crop_y0 = sobrante_y / 2
    else:
        crop_y0 = 0

    crop_x0 = int(round(crop_x0))
    crop_y0 = int(round(crop_y0))
    recorte = imagen_escalada.crop((crop_x0, crop_y0, crop_x0 + ancho_objetivo, crop_y0 + alto_objetivo))
    return recorte, None


def _posicion_xy(canvas_w, canvas_h, logo_w, logo_h, posicion, margen_px):
    posiciones = {
        "superior_izquierda": (margen_px, margen_px),
        "superior_derecha": (canvas_w - logo_w - margen_px, margen_px),
        "inferior_izquierda": (margen_px, canvas_h - logo_h - margen_px),
        "inferior_derecha": (canvas_w - logo_w - margen_px, canvas_h - logo_h - margen_px),
        "centro": ((canvas_w - logo_w) // 2, (canvas_h - logo_h) // 2),
    }
    x, y = posiciones.get(posicion, posiciones["inferior_derecha"])
    return max(0, int(x)), max(0, int(y))


def aplicar_logo(imagen_base_rgb, logo_bytes, posicion, opacidad):
    """Compone `logo_bytes` sobre una copia de `imagen_base_rgb` (RGB).

    El logo NUNCA se deforma (se escala manteniendo ancho/alto
    original) y su transparencia, si la tiene, se respeta tal cual --
    nunca se le agrega un fondo blanco ni se aplana su canal alfa antes
    de tiempo. La opacidad pedida se aplica multiplicando el canal
    alfa existente, nunca reemplazandolo, para no destruir la
    transparencia propia del archivo.
    """
    opacidad = max(_OPACIDAD_MINIMA, min(_OPACIDAD_MAXIMA, opacidad))

    logo = cargar_imagen_preservando_alpha(logo_bytes).convert("RGBA")
    canvas_w, canvas_h = imagen_base_rgb.size

    logo_ancho_objetivo = max(1, round(canvas_w * _LOGO_ANCHO_PORCENTAJE))
    proporcion = logo.height / logo.width
    logo_alto_objetivo = round(logo_ancho_objetivo * proporcion)

    alto_maximo = canvas_h * _LOGO_ALTO_MAXIMO_PORCENTAJE
    if logo_alto_objetivo > alto_maximo:
        logo_alto_objetivo = max(1, round(alto_maximo))
        logo_ancho_objetivo = round(logo_alto_objetivo / proporcion)

    logo_redimensionado = logo.resize((logo_ancho_objetivo, logo_alto_objetivo), Image.LANCZOS)

    canal_r, canal_g, canal_b, canal_a = logo_redimensionado.split()
    canal_a = canal_a.point(lambda v: int(v * opacidad))
    logo_final = Image.merge("RGBA", (canal_r, canal_g, canal_b, canal_a))

    margen_px = round(canvas_w * _MARGEN_PORCENTAJE)
    x, y = _posicion_xy(canvas_w, canvas_h, logo_ancho_objetivo, logo_alto_objetivo, posicion, margen_px)

    resultado = imagen_base_rgb.convert("RGBA")
    resultado.alpha_composite(logo_final, dest=(x, y))
    return resultado.convert("RGB")


def generar_formato(bytes_base, tipo_formato, rostros, logo_bytes=None, aplicacion="sin_logo", posicion="inferior_derecha", opacidad=0.8):
    """Genera un formato (cuadrado/vertical/historia/horizontal) a partir
    de los bytes de una fotografia (original o ya mejorada).

    `rostros` se recibe ya calculado por el llamador (evita detectar
    dos veces si ya se corrio la deteccion antes). Devuelve
    (bytes_resultado_o_None, metadata) -- si no hay un encuadre seguro,
    bytes_resultado es None y metadata trae la advertencia explicando
    por que no se genero el archivo.
    """
    inicio = time.time()

    imagen = Image.open(io.BytesIO(bytes_base))
    imagen.load()
    imagen = imagen.convert("RGB")
    ancho_base, alto_base = imagen.size

    ancho_objetivo, alto_objetivo = _tamano_objetivo(tipo_formato, ancho_base, alto_base)
    recorte, advertencia_recorte = recorte_inteligente(imagen, ancho_objetivo, alto_objetivo, rostros)

    if recorte is None:
        return None, {
            "advertencia": advertencia_recorte,
            "ancho_px": None,
            "alto_px": None,
            "duracion_segundos": round(time.time() - inicio, 3),
        }

    resultado = recorte
    advertencia_logo = None
    if aplicacion != "sin_logo" and logo_bytes:
        logo_probe = cargar_imagen_preservando_alpha(logo_bytes)
        advertencia_logo = advertencia_resolucion_logo(logo_probe.width, logo_probe.height, ancho_objetivo)
        resultado = aplicar_logo(resultado, logo_bytes, posicion, opacidad)

    buffer = io.BytesIO()
    resultado.save(buffer, format="JPEG", quality=95)
    bytes_resultado = buffer.getvalue()

    metadata = {
        "advertencia": advertencia_logo,
        "ancho_px": ancho_objetivo,
        "alto_px": alto_objetivo,
        "duracion_segundos": round(time.time() - inicio, 3),
    }
    return bytes_resultado, metadata
