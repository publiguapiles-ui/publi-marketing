"""Motor de composicion de formatos para redes sociales (Paso 8) con
recorte inteligente por puntuacion de candidatos (Paso 9).

Regla absoluta (igual que en app/services/procesamiento.py): este
modulo nunca recibe una ruta de Storage ni escribe sobre el original.
Opera enteramente en memoria sobre los bytes que se le entregan y
devuelve bytes nuevos.

Flujo: ORIGINAL (o su version MEJORADA) -> RECORTE inteligente al
formato objetivo -> LOGO/marca de agua opcional -> archivo nuevo. El
recorte SIEMPRE se hace antes de componer el logo (Paso 9, punto 23):
si el logo se colocara antes, un recorte posterior podria cortarlo.

El recorte usa la deteccion de rostros de app/services/procesamiento.py
unicamente para evitar cortar una cabeza/rostro -- nunca para
retocar, embellecer o identificar a nadie (misma regla del Paso 7).
Cuando no hay rostros, se usa una senal de "sujeto principal"
completamente local y determinista (energia de bordes / Sobel, sin
ningun modelo de IA externo) en vez de recortar siempre desde el
centro sin analizar la imagen.

Rendimiento: el calculo del encuadre (deteccion de rostros, energia de
bordes, puntuacion de candidatos) trabaja siempre en coordenadas
NORMALIZADAS (0-1) sobre una version reducida de la imagen -- el
recorte final se aplica multiplicando esas fracciones por las
dimensiones reales de la imagen de origen, nunca sobre una miniatura.
"""

import io
import time

import cv2
import numpy as np
from PIL import Image

FORMATOS_FIJOS = {
    "formato_cuadrado": (1080, 1080),
    "formato_vertical": (1080, 1350),
    "formato_historia": (1080, 1920),
}
# El horizontal no tiene un tamano unico obligatorio (ver Paso 8, punto
# 14): conserva la proporcion original de la fotografia, solo se limita
# el lado mayor para no subir archivos innecesariamente grandes.
_LADO_MAXIMO_HORIZONTAL = 1920

TIPOS_FORMATO = list(FORMATOS_FIJOS.keys()) + ["formato_horizontal"]

MODOS_RECORTE = ["auto", "manual"]

# El logo ocupa un porcentaje del ancho del lienzo (nunca un tamano fijo
# en pixeles) para que se vea proporcional sin importar el formato.
_LOGO_ANCHO_PORCENTAJE = 0.12
_LOGO_ALTO_MAXIMO_PORCENTAJE = 0.30  # evita logos "gigantes" en fotos muy verticales
_MARGEN_PORCENTAJE = 0.04  # proporcional al lienzo, nunca pegado al borde
_OPACIDAD_MINIMA = 0.15  # nunca invisible, aunque el usuario pida menos
_OPACIDAD_MAXIMA = 1.0

_ZOOM_MINIMO = 1.0
_ZOOM_MAXIMO = 3.0

# Paso 9, punto 13: no se rechaza silenciosamente -- siempre se genera
# un resultado (el mejor encuadre posible entre varios candidatos) y,
# si no fue posible evitar cortar a alguien, se adjunta esta advertencia
# explicita en vez de fallar.
MENSAJE_ENCUADRE_IMPERFECTO = (
    "El formato seleccionado requiere un recorte que puede afectar el encuadre. "
    "Ajusta manualmente la posición."
)


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


# --- Sujeto principal sin rostros: energia de bordes (Sobel) ------------------
# Tecnica clasica y determinista de "saliencia" -- no es un modelo de IA,
# es una suma ponderada de gradientes de intensidad. Las zonas con mas
# detalle (bordes, texturas, formas) suelen corresponder al sujeto de
# una foto; el cielo, una pared o una mesa vacia aportan poca energia.

def calcular_saliencia(imagen_rgb, lado_maximo=400):
    """(cx, cy) normalizados (0-1): centro de masa de la energia de
    bordes. Se calcula sobre una copia reducida (rendimiento, Paso 9
    punto 26) -- el resultado normalizado aplica igual a cualquier
    resolucion de la misma imagen.
    """
    ancho, alto = imagen_rgb.size
    lado_mayor = max(ancho, alto)
    if lado_mayor > lado_maximo:
        escala = lado_maximo / lado_mayor
        imagen_pequena = imagen_rgb.resize((max(1, round(ancho * escala)), max(1, round(alto * escala))))
    else:
        imagen_pequena = imagen_rgb

    gris = np.asarray(imagen_pequena.convert("L")).astype(np.float32)
    gx = cv2.Sobel(gris, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gris, cv2.CV_32F, 0, 1, ksize=3)
    energia = np.sqrt(gx**2 + gy**2)
    total = float(energia.sum())
    if total <= 1e-6:
        return 0.5, 0.5

    alto_e, ancho_e = energia.shape
    yy, xx = np.mgrid[0:alto_e, 0:ancho_e]
    cx = float((xx * energia).sum() / total) / ancho_e
    cy = float((yy * energia).sum() / total) / alto_e
    return cx, cy


# --- Geometria del recorte, en coordenadas normalizadas 0-1 -------------------

def _tamano_ventana_normalizado(ancho_src, alto_src, ancho_obj, alto_obj, zoom):
    """Tamano (ancho, alto), normalizado 0-1, de la ventana de recorte:
    la version "cover" minima necesaria para llenar el formato objetivo
    sin deformar, reducida por el zoom (zoom > 1 = encuadre mas
    cerrado, se ve menos escena pero mas grande).
    """
    zoom = max(_ZOOM_MINIMO, min(_ZOOM_MAXIMO, zoom or _ZOOM_MINIMO))
    escala = max(ancho_obj / ancho_src, alto_obj / alto_src)
    ancho_ventana_px = ancho_obj / escala
    alto_ventana_px = alto_obj / escala
    ancho_norm = min(1.0, (ancho_ventana_px / ancho_src) / zoom)
    alto_norm = min(1.0, (alto_ventana_px / alto_src) / zoom)
    return ancho_norm, alto_norm


def _ventana_centrada(cx, cy, ancho_norm, alto_norm):
    x0 = min(max(cx - ancho_norm / 2, 0.0), 1.0 - ancho_norm)
    y0 = min(max(cy - alto_norm / 2, 0.0), 1.0 - alto_norm)
    return x0, y0, x0 + ancho_norm, y0 + alto_norm


def _rostros_normalizados(rostros, ancho_src, alto_src):
    if not rostros or ancho_src <= 0 or alto_src <= 0:
        return []
    return [
        (x / ancho_src, y / alto_src, (x + w) / ancho_src, (y + h) / alto_src)
        for (x, y, w, h) in rostros
    ]


def _contenido_completo(ventana, caja):
    vx0, vy0, vx1, vy1 = ventana
    cx0, cy0, cx1, cy1 = caja
    return cx0 >= vx0 - 1e-9 and cy0 >= vy0 - 1e-9 and cx1 <= vx1 + 1e-9 and cy1 <= vy1 + 1e-9


def _se_superpone(ventana, caja):
    vx0, vy0, vx1, vy1 = ventana
    cx0, cy0, cx1, cy1 = caja
    return not (cx1 <= vx0 or cx0 >= vx1 or cy1 <= vy0 or cy0 >= vy1)


def _distancia(ventana, cx, cy):
    vx = (ventana[0] + ventana[2]) / 2
    vy = (ventana[1] + ventana[3]) / 2
    return ((vx - cx) ** 2 + (vy - cy) ** 2) ** 0.5


def puntaje_ventana(ventana, rostros_norm):
    """Puntuacion determinista de un candidato de recorte (Paso 9,
    punto 20): +2 por cada rostro totalmente conservado, -3 si un
    rostro queda cortado a la mitad (lo peor posible), -0.5 si un
    rostro queda totalmente fuera del encuadre (se pierde, pero no se
    ve "cortado").
    """
    score = 0.0
    for caja in rostros_norm:
        if _contenido_completo(ventana, caja):
            score += 2.0
        elif _se_superpone(ventana, caja):
            score -= 3.0
        else:
            score -= 0.5
    return score


def _candidatos_centro(rostros_norm, ancho_norm, alto_norm, n=7):
    """Varios candidatos de encuadre (Paso 9, punto 21): centrados en la
    union de todos los rostros, en cada rostro individual, y en una
    rejilla de posiciones a lo largo de ambos ejes -- cubre tanto una
    sola persona como varias sin depender de una sola heuristica.
    """
    centros = []
    if rostros_norm:
        x0 = min(c[0] for c in rostros_norm)
        y0 = min(c[1] for c in rostros_norm)
        x1 = max(c[2] for c in rostros_norm)
        y1 = max(c[3] for c in rostros_norm)
        centros.append(((x0 + x1) / 2, (y0 + y1) / 2))
        for caja in rostros_norm:
            centros.append(((caja[0] + caja[2]) / 2, (caja[1] + caja[3]) / 2))

    for i in range(n):
        t = i / (n - 1) if n > 1 else 0.5
        centros.append((t * (1 - ancho_norm) + ancho_norm / 2, 0.5))
        centros.append((0.5, t * (1 - alto_norm) + alto_norm / 2))

    vistos = set()
    candidatos = []
    for cx, cy in centros:
        ventana = _ventana_centrada(cx, cy, ancho_norm, alto_norm)
        clave = tuple(round(v, 6) for v in ventana)
        if clave not in vistos:
            vistos.add(clave)
            candidatos.append(ventana)
    return candidatos


def calcular_recorte(ancho_src, alto_src, ancho_obj, alto_obj, rostros_px=None, modo="auto", focus_x=None, focus_y=None, zoom=1.0, saliencia_xy=None):
    """Calcula la ventana de recorte (normalizada 0-1) para llevar una
    imagen de ancho_src x alto_src al formato ancho_obj x alto_obj.

    No toca ningun pixel: solo geometria. Por eso puede (y debe) usarse
    tanto para la vista previa liviana del overlay como para el
    resultado final -- ver `aplicar_recorte`.

    Devuelve un dict: ventana, advertencia, algoritmo, focus_x, focus_y.
    """
    ancho_norm, alto_norm = _tamano_ventana_normalizado(ancho_src, alto_src, ancho_obj, alto_obj, zoom)
    rostros_norm = _rostros_normalizados(rostros_px, ancho_src, alto_src)

    if modo == "manual" and focus_x is not None and focus_y is not None:
        focus_x = min(max(focus_x, 0.0), 1.0)
        focus_y = min(max(focus_y, 0.0), 1.0)
        ventana = _ventana_centrada(focus_x, focus_y, ancho_norm, alto_norm)
        cortado = any(_se_superpone(ventana, caja) and not _contenido_completo(ventana, caja) for caja in rostros_norm)
        # La seleccion manual del usuario siempre tiene prioridad (Paso
        # 9, punto 12): se respeta igual, solo se avisa si corta a
        # alguien para que pueda corregirlo el mismo.
        return {
            "ventana": ventana,
            "advertencia": MENSAJE_ENCUADRE_IMPERFECTO if cortado else None,
            "algoritmo": "manual",
            "focus_x": focus_x,
            "focus_y": focus_y,
        }

    if rostros_norm:
        x0 = min(c[0] for c in rostros_norm)
        y0 = min(c[1] for c in rostros_norm)
        x1 = max(c[2] for c in rostros_norm)
        y1 = max(c[3] for c in rostros_norm)
        centro_union = ((x0 + x1) / 2, (y0 + y1) / 2)

        if (x1 - x0) <= ancho_norm and (y1 - y0) <= alto_norm:
            # Cabe una ventana que contenga a TODAS las personas.
            ventana = _ventana_centrada(centro_union[0], centro_union[1], ancho_norm, alto_norm)
            return {"ventana": ventana, "advertencia": None, "algoritmo": "rostros", "focus_x": centro_union[0], "focus_y": centro_union[1]}

        # No caben todas: se evaluan varios candidatos y se elige el que
        # preserve mas personas (Paso 9, punto 4) sin cortarlas si es
        # posible evitarlo.
        candidatos = _candidatos_centro(rostros_norm, ancho_norm, alto_norm)
        mejor = max(candidatos, key=lambda v: (puntaje_ventana(v, rostros_norm), -_distancia(v, *centro_union)))
        cortado = any(_se_superpone(mejor, caja) and not _contenido_completo(mejor, caja) for caja in rostros_norm)
        return {
            "ventana": mejor,
            "advertencia": MENSAJE_ENCUADRE_IMPERFECTO if cortado else None,
            "algoritmo": "rostros",
            "focus_x": centro_union[0],
            "focus_y": centro_union[1],
        }

    # Sin rostros: usar el sujeto principal (saliencia) si esta
    # disponible; nunca "recortar desde el centro sin analizar".
    if saliencia_xy is not None:
        cx, cy = saliencia_xy
        algoritmo = "saliencia"
    else:
        cx, cy = 0.5, 0.5
        algoritmo = "centro"
    ventana = _ventana_centrada(cx, cy, ancho_norm, alto_norm)
    return {"ventana": ventana, "advertencia": None, "algoritmo": algoritmo, "focus_x": cx, "focus_y": cy}


def aplicar_recorte(imagen, ventana, ancho_objetivo, alto_objetivo):
    """Aplica una ventana NORMALIZADA (calculada posiblemente sobre una
    version reducida) a `imagen` -- que debe ser la imagen en su
    resolucion real -- y la redimensiona al tamano exacto del formato.
    Nunca deforma: el recorte ya tiene la proporcion correcta, el
    resize final es uniforme.

    Devuelve (imagen_recortada, (x, y, ancho, alto) en pixeles de
    `imagen`) -- esas coordenadas son las que se guardan como
    crop_x/crop_y/crop_width/crop_height.
    """
    ancho_src, alto_src = imagen.size
    x0n, y0n, x1n, y1n = ventana
    x0 = int(round(x0n * ancho_src))
    y0 = int(round(y0n * alto_src))
    x1 = max(x0 + 1, int(round(x1n * ancho_src)))
    y1 = max(y0 + 1, int(round(y1n * alto_src)))
    x1, y1 = min(x1, ancho_src), min(y1, alto_src)

    recorte = imagen.crop((x0, y0, x1, y1))
    if recorte.size != (ancho_objetivo, alto_objetivo):
        recorte = recorte.resize((ancho_objetivo, alto_objetivo), Image.LANCZOS)
    return recorte, (x0, y0, x1 - x0, y1 - y0)


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
    Se llama SIEMPRE despues del recorte (Paso 9, punto 23) para que el
    logo nunca pueda quedar cortado por un recorte posterior.

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


def calcular_ventana_formato(ancho_base, alto_base, tipo_formato, rostros, modo="auto", focus_x=None, focus_y=None, zoom=1.0, saliencia_xy=None):
    """Atajo: resuelve el tamano objetivo del formato y calcula la
    ventana de recorte. Usado tanto por generar_formato como por el
    endpoint liviano de overlay (que no necesita renderizar ninguna
    imagen, solo devolver estas coordenadas).
    """
    ancho_objetivo, alto_objetivo = _tamano_objetivo(tipo_formato, ancho_base, alto_base)
    resultado = calcular_recorte(
        ancho_base, alto_base, ancho_objetivo, alto_objetivo,
        rostros_px=rostros, modo=modo, focus_x=focus_x, focus_y=focus_y, zoom=zoom, saliencia_xy=saliencia_xy,
    )
    resultado["ancho_objetivo"] = ancho_objetivo
    resultado["alto_objetivo"] = alto_objetivo
    return resultado


def generar_formato(bytes_base, tipo_formato, rostros, logo_bytes=None, aplicacion="sin_logo", posicion="inferior_derecha", opacidad=0.8, modo="auto", focus_x=None, focus_y=None, zoom=1.0, saliencia_xy=None):
    """Genera un formato (cuadrado/vertical/historia/horizontal) a partir
    de los bytes de una fotografia (original o ya mejorada).

    `rostros` se recibe ya calculado por el llamador (evita detectar
    dos veces si ya se corrio la deteccion antes). Si `saliencia_xy` no
    se pasa y hace falta (modo automatico sin rostros), se calcula
    aqui. Siempre devuelve un resultado (Paso 9, punto 19: nunca se
    rechaza silenciosamente) -- `metadata["advertencia"]` explica
    cualquier limitacion del encuadre logrado.
    """
    inicio = time.time()

    imagen = Image.open(io.BytesIO(bytes_base))
    imagen.load()
    imagen = imagen.convert("RGB")
    ancho_base, alto_base = imagen.size

    if modo == "auto" and not rostros and saliencia_xy is None:
        saliencia_xy = calcular_saliencia(imagen)

    calculo = calcular_ventana_formato(
        ancho_base, alto_base, tipo_formato, rostros,
        modo=modo, focus_x=focus_x, focus_y=focus_y, zoom=zoom, saliencia_xy=saliencia_xy,
    )
    recorte, caja_px = aplicar_recorte(imagen, calculo["ventana"], calculo["ancho_objetivo"], calculo["alto_objetivo"])

    # El logo se compone SIEMPRE despues del recorte (punto 23).
    resultado = recorte
    advertencia_logo = None
    if aplicacion != "sin_logo" and logo_bytes:
        logo_probe = cargar_imagen_preservando_alpha(logo_bytes)
        advertencia_logo = advertencia_resolucion_logo(logo_probe.width, logo_probe.height, calculo["ancho_objetivo"])
        resultado = aplicar_logo(resultado, logo_bytes, posicion, opacidad)

    buffer = io.BytesIO()
    resultado.save(buffer, format="JPEG", quality=95)
    bytes_resultado = buffer.getvalue()

    metadata = {
        "advertencia": calculo["advertencia"] or advertencia_logo,
        "ancho_px": calculo["ancho_objetivo"],
        "alto_px": calculo["alto_objetivo"],
        "duracion_segundos": round(time.time() - inicio, 3),
        "crop_mode": modo,
        "focus_x": calculo["focus_x"],
        "focus_y": calculo["focus_y"],
        "crop_x": caja_px[0],
        "crop_y": caja_px[1],
        "crop_width": caja_px[2],
        "crop_height": caja_px[3],
        "algoritmo_recorte": calculo["algoritmo"],
    }
    return bytes_resultado, metadata
