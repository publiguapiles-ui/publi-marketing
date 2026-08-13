"""Motor de analisis y correccion fotografica automatica de Photo Studio.

Regla absoluta: este modulo NUNCA recibe una ruta de Storage ni escribe
sobre el original. Opera enteramente en memoria sobre los bytes que se
le entregan y devuelve bytes nuevos -- quien lo llama decide donde
guardar el resultado (siempre como un derivado nuevo, ver
app/services/derivados.py).

Deteccion de rostros: se usa unicamente para UBICAR regiones (bounding
boxes) y protegerlas de la correccion automatica. No se extrae, calcula
ni almacena ninguna caracteristica biometrica, embedding ni cualquier
dato que permita reconocer o identificar a una persona. No hay
retoque facial de ningun tipo: dentro de la mascara de proteccion se
usa exclusivamente el pixel original.
"""

import io
import time

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

_cascada_rostros = None

# Tamano maximo de lado para la deteccion de rostros (mas grande no
# mejora la deteccion y sí la vuelve mucho mas lenta); las coordenadas
# encontradas se reescalan de vuelta a la resolucion real.
_LADO_MAXIMO_DETECCION = 1000

CATEGORIAS = ["personas", "producto", "comida", "paisaje", "evento", "vehiculo", "arquitectura", "general"]


def _obtener_cascada():
    global _cascada_rostros
    if _cascada_rostros is None:
        _cascada_rostros = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
    return _cascada_rostros


def cargar_imagen(bytes_originales):
    imagen = Image.open(io.BytesIO(bytes_originales))
    imagen.load()
    return imagen.convert("RGB")


def analizar_imagen(imagen):
    """Metricas basicas de la fotografia. Incluye tambien los campos de
    deteccion de objetos que el Paso 7 todavia NO implementa (quedan en
    None a proposito) para que Photo Studio pueda usarlos mas adelante
    sin cambiar la forma de este diccionario.
    """
    ancho, alto = imagen.size

    if ancho > alto:
        orientacion = "horizontal"
    elif alto > ancho:
        orientacion = "vertical"
    else:
        orientacion = "cuadrada"

    arr = np.asarray(imagen).astype(np.float32)
    hsv = np.asarray(imagen.convert("HSV")).astype(np.float32)
    gris = np.asarray(imagen.convert("L")).astype(np.float32)

    brillo_promedio = float(gris.mean() / 255)
    contraste = float(gris.std() / 255)
    saturacion_media = float(hsv[..., 1].mean() / 255)
    zonas_oscuras = float((gris < 40).mean())
    zonas_claras = float((gris > 215).mean())

    r_medio = float(arr[..., 0].mean())
    b_medio = float(arr[..., 2].mean())
    diferencia_rb = r_medio - b_medio
    if diferencia_rb > 12:
        temperatura = "calida"
    elif diferencia_rb < -12:
        temperatura = "fria"
    else:
        temperatura = "neutra"

    suavizada = np.asarray(imagen.filter(ImageFilter.GaussianBlur(2))).astype(np.float32)
    ruido_estimado = float(np.abs(arr - suavizada).mean() / 255)

    return {
        "ancho": ancho,
        "alto": alto,
        "orientacion": orientacion,
        "brillo_promedio": round(brillo_promedio, 4),
        "contraste": round(contraste, 4),
        "saturacion_media": round(saturacion_media, 4),
        "temperatura": temperatura,
        "zonas_oscuras": round(zonas_oscuras, 4),
        "zonas_claras": round(zonas_claras, 4),
        "ruido_estimado": round(ruido_estimado, 4),
        # Preparado para deteccion de objetos futura (no implementada aun):
        "cielo_detectado": None,
        "vegetacion_detectada": None,
        "comida_detectada": None,
        "vehiculo_detectado": None,
        "edificio_detectado": None,
        "texto_detectado": None,
    }


def detectar_rostros(imagen):
    """Bounding boxes (x, y, w, h) en coordenadas de la imagen original.

    Solo ubicacion espacial -- nunca identidad. No es reconocimiento
    facial: un Haar Cascade clasico no puede distinguir personas entre
    si, solo encuentra regiones con patrones geometricos de un rostro.
    """
    ancho, alto = imagen.size
    lado_mayor = max(ancho, alto)
    escala = 1.0
    imagen_deteccion = imagen
    if lado_mayor > _LADO_MAXIMO_DETECCION:
        escala = _LADO_MAXIMO_DETECCION / lado_mayor
        imagen_deteccion = imagen.resize((max(1, int(ancho * escala)), max(1, int(alto * escala))))

    arr = np.asarray(imagen_deteccion)
    gris = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    gris = cv2.equalizeHist(gris)

    cascada = _obtener_cascada()
    detecciones = cascada.detectMultiScale(gris, scaleFactor=1.05, minNeighbors=5, minSize=(40, 40))

    rostros = []
    for (x, y, w, h) in detecciones:
        rostros.append((int(x / escala), int(y / escala), int(w / escala), int(h / escala)))
    return rostros


def clasificar_imagen(analisis, rostros):
    """Clasificacion honesta: sin un modelo de deteccion de objetos
    entrenado (fuera del alcance de este paso), solo podemos afirmar
    con confianza razonable si hay personas o no. Para el resto de
    categorias devolvemos GENERAL con confianza baja en vez de fingir
    precision que no tenemos.
    """
    if rostros:
        return "personas", 0.9
    return "general", 0.3


def _mascara_proteccion_rostros(tamano, rostros, expansion=0.25, difuminado_px=15):
    """Mascara float32 (alto, ancho), 1 = usar pixel original (proteger),
    0 = libre para la correccion. Elipses con borde difuminado (Gaussian
    blur) para evitar halos duros en el limite de la mascara.

    El nucleo de cada elipse (el 70% central) queda garantizado en
    exactamente 1.0 despues del difuminado -- sin este "re-estampado"
    el blur erosiona muy levemente incluso el centro (diferencias de
    +-1/255 detectadas en pruebas), lo cual violaria la garantia de que
    el rostro nunca se toca ni un pixel. El difuminado solo afecta el
    30% exterior de cada elipse (la transicion hacia el fondo).
    """
    ancho, alto = tamano
    mascara = np.zeros((alto, ancho), dtype=np.float32)
    nucleo = np.zeros((alto, ancho), dtype=np.float32)

    for (x, y, w, h) in rostros:
        ex, ey = int(w * expansion), int(h * expansion)
        x0, y0 = max(0, x - ex), max(0, y - ey)
        x1, y1 = min(ancho, x + w + ex), min(alto, y + h + ey)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        rx, ry = max(1, (x1 - x0) / 2), max(1, (y1 - y0) / 2)
        yy, xx = np.ogrid[0:alto, 0:ancho]
        elipse = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2
        mascara = np.maximum(mascara, (elipse <= 1).astype(np.float32))
        nucleo = np.maximum(nucleo, (elipse <= 0.49).astype(np.float32))  # 70% del radio

    if mascara.max() > 0:
        mascara = cv2.GaussianBlur(mascara, (0, 0), sigmaX=difuminado_px)
        mascara = np.clip(mascara, 0.0, 1.0)
        mascara = np.where(nucleo > 0, 1.0, mascara)
    return mascara


def _ajustar_exposicion(imagen, analisis, objetivo_brillo=0.5, intensidad=1.0):
    """Correccion por gamma (no un +/-% fijo): protege altas luces y
    sombras profundas mucho mejor que escalar el brillo linealmente.

    `objetivo_brillo` es el grado de libertad que un preset (Paso 10)
    puede sesgar; `intensidad` (Paso 11, 0..1) mezcla el resultado con
    el original -- 1.0 (por defecto, igual que antes del Paso 11) es
    la correccion completa, valores menores dejan una version mas
    sutil sin cambiar el objetivo en si (un preset "moderado" reduce
    la intensidad, no el objetivo).
    """
    diferencia = objetivo_brillo - analisis["brillo_promedio"]
    if abs(diferencia) <= 0.03 or intensidad <= 0:
        return imagen
    gamma = float(np.clip(1.0 - diferencia * 0.9, 0.6, 1.6))
    arr_original = np.asarray(imagen).astype(np.float32)
    arr_corregida = np.power(arr_original / 255.0, gamma) * 255.0
    intensidad = float(np.clip(intensidad, 0.0, 1.0))
    arr_final = arr_original * (1 - intensidad) + arr_corregida * intensidad
    return Image.fromarray(np.clip(arr_final, 0, 255).astype(np.uint8))


def _ajustar_balance_blancos(imagen, analisis, sesgo_calidez=0.0, intensidad=1.0):
    """Correccion PARCIAL (50%) hacia gris neutro -- nunca neutraliza
    del todo, para respetar la intencion visual de la escena (ver
    restriccion del Paso 7 sobre balance de blancos).

    `sesgo_calidez` (Paso 10, -1..1) empuja el resultado un poco mas
    alla del neutro: positivo = mas calido, negativo = mas frio. Con
    sesgo 0.0 e intensidad 1.0 (preset "Automatico") el rango de
    recorte es exactamente el mismo (0.85-1.15) que antes del Paso 10
    -- el comportamiento por defecto no cambia ni un bit.

    `intensidad` (Paso 11, 0..1) mezcla el resultado con el original:
    permite un preset "temperatura cálida, pero sutil" sin tener que
    reducir `sesgo_calidez` en si (que tambien controla la DIRECCION).
    """
    if intensidad <= 0:
        return imagen
    arr_original = np.asarray(imagen).astype(np.float32)
    r_medio, g_medio, b_medio = arr_original[..., 0].mean(), arr_original[..., 1].mean(), arr_original[..., 2].mean()
    gris_medio = (r_medio + g_medio + b_medio) / 3
    if gris_medio < 1:
        return imagen

    factor_r = 1 + ((gris_medio / max(r_medio, 1)) - 1) * 0.5
    factor_b = 1 + ((gris_medio / max(b_medio, 1)) - 1) * 0.5
    factor_r *= 1 + sesgo_calidez * 0.08
    factor_b *= 1 - sesgo_calidez * 0.08

    margen = 0.15 + abs(sesgo_calidez) * 0.15
    factor_r = float(np.clip(factor_r, 1 - margen, 1 + margen))
    factor_b = float(np.clip(factor_b, 1 - margen, 1 + margen))
    arr_corregida = arr_original.copy()
    arr_corregida[..., 0] = arr_original[..., 0] * factor_r
    arr_corregida[..., 2] = arr_original[..., 2] * factor_b

    intensidad = float(np.clip(intensidad, 0.0, 1.0))
    arr_final = arr_original * (1 - intensidad) + arr_corregida * intensidad
    return Image.fromarray(np.clip(arr_final, 0, 255).astype(np.uint8))


def _ajustar_contraste(imagen, analisis, objetivo_contraste=0.22, intensidad=1.0):
    """`intensidad` (Paso 11, 0..1) mezcla el resultado con el original
    via Image.blend -- en 1.0 (por defecto) es identico byte a byte al
    comportamiento previo al Paso 11 (Image.blend(a, b, 1.0) == b)."""
    if analisis["contraste"] >= objetivo_contraste or intensidad <= 0:
        return imagen  # ya tiene buen contraste: no forzar mas (evita clipping)
    factor = float(np.clip(1 + (objetivo_contraste - analisis["contraste"]) * 1.5, 1.0, 1.3))
    corregida = ImageEnhance.Contrast(imagen).enhance(factor)
    if intensidad >= 1.0:
        return corregida
    return Image.blend(imagen, corregida, float(np.clip(intensidad, 0.0, 1.0)))


def _ajustar_saturacion(imagen, analisis, objetivo_saturacion=0.35, factor_maximo_saturacion=1.35, intensidad=1.0):
    """Aproximacion de "vibrance": cuanto mas apagados esten los colores
    mayor es el impulso; si ya estan vivos, el ajuste es minimo (evita
    piel naranja, cielos irreales, vegetacion artificial).

    `factor_maximo_saturacion` es el techo absoluto (Paso 10): incluso
    el preset "Vibrante" lo mantiene moderado, nunca sobresaturado.
    `intensidad` (Paso 11, 0..1) mezcla con el original, igual que en
    _ajustar_contraste.
    """
    if intensidad <= 0:
        return imagen
    if analisis["saturacion_media"] >= objetivo_saturacion:
        factor = 1.05
    else:
        factor = float(np.clip(1 + (objetivo_saturacion - analisis["saturacion_media"]) * 1.2, 1.05, factor_maximo_saturacion))
    corregida = ImageEnhance.Color(imagen).enhance(factor)
    if intensidad >= 1.0:
        return corregida
    return Image.blend(imagen, corregida, float(np.clip(intensidad, 0.0, 1.0)))


def _ajustar_nitidez(imagen, intensidad_nitidez=80):
    ancho, alto = imagen.size
    radio = max(1, min(3, round(max(ancho, alto) / 1000)))
    # PIL exige un int para "percent" -- un preset normalizado (Paso 11)
    # puede traer este valor como float (ej. 80.0), asi que se redondea
    # aqui explicitamente en vez de confiar en el tipo del llamador.
    return imagen.filter(ImageFilter.UnsharpMask(radius=radio, percent=round(intensidad_nitidez), threshold=3))


def _reducir_ruido_si_hace_falta(imagen, analisis):
    if analisis["ruido_estimado"] <= 0.045:
        return imagen, False
    return imagen.filter(ImageFilter.MedianFilter(size=3)), True



# Objetivos usados cuando no se pasa preset -- EXACTAMENTE los valores
# que este motor ya usaba como constantes fijas antes del Paso 10.
# `presets.py` los replica en su entrada "automatico"; se mantienen
# duplicados a proposito (procesamiento.py no depende de presets.py)
# para que este modulo siga siendo utilizable de forma aislada.
#
# Paso 11: se agregan las "intensidad_*" (0..1, por defecto 1.0 = 100%
# de la correccion, EXACTAMENTE el comportamiento que existia antes de
# este paso). Un preset que no las incluya se comporta como siempre;
# solo un preset que las baje deliberadamente aplica una version mas
# sutil de la misma correccion -- nunca es un filtro nuevo, es la
# MISMA correccion adaptativa mezclada con el original en proporcion
# variable (ver _ajustar_exposicion/_ajustar_contraste/etc.).
PARAMETROS_POR_DEFECTO = {
    "objetivo_brillo": 0.5,
    "intensidad_exposicion": 1.0,
    "objetivo_contraste": 0.22,
    "intensidad_contraste": 1.0,
    "objetivo_saturacion": 0.35,
    "factor_maximo_saturacion": 1.35,
    "intensidad_saturacion": 1.0,
    "sesgo_calidez": 0.0,
    "intensidad_calidez": 1.0,
    "intensidad_nitidez": 80,
}


def _resolver_parametros(preset, contexto_sesion):
    """Combina los objetivos del preset (o los valores por defecto) con
    un pequeno sesgo hacia el promedio de la sesion, si se paso uno
    (Paso 10, "Consistencia entre fotografias"): el preset define el
    ESTILO, el contexto de sesion solo lo empuja levemente para que
    las fotos de un mismo lote no se vean como estilos distintos --
    nunca reemplaza el objetivo del preset, solo lo desplaza un 25%
    hacia la media real de esta sesion en particular.
    """
    parametros = dict(PARAMETROS_POR_DEFECTO)
    if preset:
        parametros.update({clave: valor for clave, valor in preset.items() if clave in parametros})

    if contexto_sesion:
        peso = 0.25
        if contexto_sesion.get("brillo_promedio") is not None:
            parametros["objetivo_brillo"] = (
                parametros["objetivo_brillo"] * (1 - peso) + contexto_sesion["brillo_promedio"] * peso
            )
        if contexto_sesion.get("contraste_promedio") is not None:
            parametros["objetivo_contraste"] = (
                parametros["objetivo_contraste"] * (1 - peso) + contexto_sesion["contraste_promedio"] * peso
            )
        if contexto_sesion.get("saturacion_promedio") is not None:
            parametros["objetivo_saturacion"] = (
                parametros["objetivo_saturacion"] * (1 - peso) + contexto_sesion["saturacion_promedio"] * peso
            )
    return parametros


def mejorar_fotografia(bytes_originales, preset=None, contexto_sesion=None):
    """Analiza + corrige una fotografia. Devuelve (bytes_resultado, metadata).

    No recibe ni toca el archivo original en Storage: trabaja solo con
    los bytes que se le pasan y devuelve un resultado nuevo en memoria.

    `preset` (Paso 10) es un dict opcional de objetivos (ver
    PARAMETROS_POR_DEFECTO) que sesga la correccion; sin el (el uso
    existente desde el Paso 7), el comportamiento es identico al que
    tenia esta funcion antes de que existieran los presets.
    `contexto_sesion` es un dict opcional con promedios de la sesion
    para mantener consistencia entre muchas fotografias del mismo lote.
    """
    inicio = time.time()
    parametros = _resolver_parametros(preset, contexto_sesion)

    imagen = cargar_imagen(bytes_originales)
    analisis = analizar_imagen(imagen)
    rostros = detectar_rostros(imagen)
    categoria, confianza = clasificar_imagen(analisis, rostros)

    corregida = imagen
    corregida = _ajustar_exposicion(corregida, analisis, parametros["objetivo_brillo"], parametros["intensidad_exposicion"])
    corregida = _ajustar_balance_blancos(corregida, analisis, parametros["sesgo_calidez"], parametros["intensidad_calidez"])
    corregida = _ajustar_contraste(corregida, analisis, parametros["objetivo_contraste"], parametros["intensidad_contraste"])
    corregida = _ajustar_saturacion(corregida, analisis, parametros["objetivo_saturacion"], parametros["factor_maximo_saturacion"], parametros["intensidad_saturacion"])
    corregida = _ajustar_nitidez(corregida, parametros["intensidad_nitidez"])
    corregida, ruido_reducido = _reducir_ruido_si_hace_falta(corregida, analisis)

    rostros_protegidos = False
    if rostros:
        mascara = _mascara_proteccion_rostros(imagen.size, rostros)
        arr_original = np.asarray(imagen).astype(np.float32)
        arr_corregida = np.asarray(corregida.convert("RGB")).astype(np.float32)
        m = mascara[..., None]
        arr_final = arr_corregida * (1 - m) + arr_original * m
        corregida = Image.fromarray(np.clip(arr_final, 0, 255).astype(np.uint8))
        rostros_protegidos = True

    # PNG (sin perdida), no JPEG: una compresion con perdida alteraria
    # levemente TODOS los pixeles al guardar -- incluidos los del rostro
    # protegido -- lo que violaria la garantia de "ni un pixel". El
    # costo es un archivo mas pesado, aceptable frente a esa garantia.
    buffer = io.BytesIO()
    corregida.save(buffer, format="PNG")
    bytes_resultado = buffer.getvalue()

    correcciones = ["exposicion", "balance_blancos", "contraste", "saturacion", "nitidez"]
    if ruido_reducido:
        correcciones.append("reduccion_ruido")

    metadata = {
        "analisis": analisis,
        "categoria": categoria,
        "confianza_categoria": confianza,
        "rostros_detectados": len(rostros),
        "rostros_protegidos": rostros_protegidos,
        "correcciones_aplicadas": correcciones,
        "duracion_segundos": round(time.time() - inicio, 3),
        "parametros_utilizados": parametros,
    }
    return bytes_resultado, metadata
