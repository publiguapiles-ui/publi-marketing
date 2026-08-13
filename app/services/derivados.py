"""Orquesta la creacion de derivados de fotografias (mejora automatica).

Flujo: descargar el original desde Storage -> procesar en memoria
(app.services.procesamiento) -> subir el resultado como un archivo
NUEVO -> registrar el derivado en la base de datos. El original nunca
se sobreescribe: se verifica con un hash antes y despues de todo el
proceso (ver `_hash` mas abajo) que sus bytes en Storage no cambiaron.
"""

import hashlib


def _hash(datos):
    return hashlib.sha256(datos).hexdigest()


def obtener_derivados_fotografia(fotografia_id):
    from app.extensions import db
    from app.models import FotografiaDerivada

    return (
        db.session.query(FotografiaDerivada)
        .filter_by(fotografia_id=fotografia_id)
        .order_by(FotografiaDerivada.creado_en.desc())
        .all()
    )


def obtener_derivado(empresa_id, derivado_id):
    from app.extensions import db
    from app.models import FotografiaDerivada

    return (
        db.session.query(FotografiaDerivada)
        .filter_by(id=derivado_id, empresa_id=empresa_id)
        .first()
    )


def _siguiente_version(fotografia_id, tipo):
    from app.extensions import db
    from app.models import FotografiaDerivada

    ultimo = (
        db.session.query(FotografiaDerivada)
        .filter_by(fotografia_id=fotografia_id, tipo=tipo)
        .order_by(FotografiaDerivada.version.desc())
        .first()
    )
    return (ultimo.version + 1) if ultimo else 1


def mejor_base_disponible(fotografia):
    """(bucket, ruta) de la mejor version disponible para partir al
    generar un formato: la ultima mejora automatica COMPLETADA si
    existe (ver flujo ORIGINAL -> MEJORA -> FORMATOS del Paso 8),
    si no el original. El original en si nunca se elige para
    verificar su integridad mas abajo: eso siempre se hace contra
    `fotografia.ruta_storage`, sin importar cual haya sido la base.
    """
    from app.extensions import db
    from app.models import FotografiaDerivada
    from app.services.storage import BUCKET_FOTOGRAFIAS

    mejora = (
        db.session.query(FotografiaDerivada)
        .filter_by(fotografia_id=fotografia.id, tipo="mejora_automatica", estado="completada")
        .order_by(FotografiaDerivada.version.desc())
        .first()
    )
    if mejora is not None and mejora.ruta_storage:
        return BUCKET_FOTOGRAFIAS, mejora.ruta_storage
    return BUCKET_FOTOGRAFIAS, fotografia.ruta_storage


def crear_mejora_automatica(empresa_id, proyecto_id, fotografia, usuario_id, preset=None, contexto_sesion=None, sesion_id=None):
    """Crea (sincronamente, via services/tareas.py) una version mejorada
    de `fotografia`. Devuelve el registro FotografiaDerivada, con
    estado "completada" o "error" (el error se guarda en el registro,
    nunca se pierde silenciosamente y nunca toca el original).

    `preset` (Paso 10), si se pasa, DEBE ser un objeto Preset ya
    validado por el llamador (ver app/services/presets.py) -- sin el,
    el comportamiento es identico al que tenia esta funcion antes de
    que existieran los presets. `contexto_sesion` es el dict de
    promedios de la sesion (consistencia entre fotografias) y
    `sesion_id` solo etiqueta el derivado para poder agruparlo despues;
    ninguno de los dos cambia como se valida o se sube el archivo.
    """
    from app.extensions import db
    from app.models import FotografiaDerivada
    from app.services.procesamiento import mejorar_fotografia
    from app.services.storage import (
        BUCKET_FOTOGRAFIAS,
        descargar_archivo,
        ruta_derivado_mejora,
        subir_archivo,
    )
    from app.services.tareas import encolar

    derivado = FotografiaDerivada(
        empresa_id=empresa_id,
        fotografia_id=fotografia.id,
        tipo="mejora_automatica",
        version=_siguiente_version(fotografia.id, "mejora_automatica"),
        estado="pendiente",
        sesion_id=sesion_id,
        preset_id=preset.id if preset else None,
        # Paso 11: snapshot INMUTABLE tomado AHORA -- si el preset se
        # edita o elimina despues, este derivado sigue mostrando el
        # nombre/version que realmente se uso para generarlo.
        preset_nombre=preset.nombre if preset else None,
        preset_version=preset.version if preset else None,
        creado_por=usuario_id,
    )
    db.session.add(derivado)
    db.session.commit()

    def _procesar():
        derivado.estado = "procesando"
        db.session.commit()

        try:
            bytes_originales = descargar_archivo(BUCKET_FOTOGRAFIAS, fotografia.ruta_storage)
            hash_antes = _hash(bytes_originales)

            bytes_resultado, metadata = mejorar_fotografia(
                bytes_originales,
                preset=preset.parametros if preset else None,
                contexto_sesion=contexto_sesion,
            )

            # Verificacion de integridad del original (Paso 7, punto 31):
            # se vuelve a descargar y se compara el hash. Si cambio, es un
            # error critico y el derivado se marca con error explicito.
            bytes_originales_despues = descargar_archivo(BUCKET_FOTOGRAFIAS, fotografia.ruta_storage)
            hash_despues = _hash(bytes_originales_despues)
            if hash_antes != hash_despues:
                derivado.estado = "error"
                derivado.error_mensaje = "Verificacion de integridad fallida: el original cambio durante el procesamiento."
                db.session.commit()
                return derivado

            ruta = ruta_derivado_mejora(empresa_id, proyecto_id)
            subir_archivo(BUCKET_FOTOGRAFIAS, ruta, bytes_resultado, "image/png")

            derivado.ruta_storage = ruta
            derivado.tipo_mime = "image/png"
            derivado.tamano_bytes = len(bytes_resultado)
            derivado.categoria_detectada = metadata["categoria"]
            derivado.confianza_categoria = metadata["confianza_categoria"]
            derivado.rostros_detectados = metadata["rostros_detectados"]
            derivado.rostros_protegidos = metadata["rostros_protegidos"]
            derivado.correcciones_aplicadas = ",".join(metadata["correcciones_aplicadas"])
            derivado.duracion_segundos = metadata["duracion_segundos"]
            derivado.estado = "completada"
        except Exception as exc:
            derivado.estado = "error"
            derivado.error_mensaje = str(exc)[:500]
        db.session.commit()
        return derivado

    return encolar(_procesar)


def crear_formato(empresa_id, proyecto_id, fotografia, usuario_id, tipo_formato, logo=None, aplicacion="sin_logo", posicion="inferior_derecha", opacidad=0.8, modo="auto", focus_x=None, focus_y=None, zoom=1.0, sesion_id=None):
    """Crea (sincronamente, via services/tareas.py) un formato para
    redes sociales (cuadrado/vertical/historia/horizontal), con logo o
    marca de agua opcional y encuadre automatico o manual (Paso 9).

    `logo`, si se pasa, DEBE ser un objeto Logo ya validado por el
    llamador (obtenido con empresa_id, ver app/services/marca.py) --
    esta funcion no vuelve a validar pertenencia de empresa, igual que
    crear_mejora_automatica no vuelve a validar la fotografia.
    """
    from app.extensions import db
    from app.models import FotografiaDerivada
    from app.services.formatos import generar_formato
    from app.services.procesamiento import cargar_imagen, detectar_rostros
    from app.services.storage import (
        BUCKET_FOTOGRAFIAS,
        BUCKET_LOGOS,
        descargar_archivo,
        ruta_derivado_formato,
        subir_archivo,
    )
    from app.services.tareas import encolar

    derivado = FotografiaDerivada(
        empresa_id=empresa_id,
        fotografia_id=fotografia.id,
        tipo=tipo_formato,
        version=_siguiente_version(fotografia.id, tipo_formato),
        estado="pendiente",
        logo_id=logo.id if logo else None,
        aplicacion_logo=aplicacion,
        posicion_logo=posicion if aplicacion != "sin_logo" else None,
        opacidad_logo=opacidad if aplicacion != "sin_logo" else None,
        crop_mode=modo,
        sesion_id=sesion_id,
        creado_por=usuario_id,
    )
    db.session.add(derivado)
    db.session.commit()

    def _procesar():
        derivado.estado = "procesando"
        db.session.commit()

        try:
            hash_antes = _hash(descargar_archivo(BUCKET_FOTOGRAFIAS, fotografia.ruta_storage))

            bucket_base, ruta_base = mejor_base_disponible(fotografia)
            bytes_base = descargar_archivo(bucket_base, ruta_base)

            imagen_base = cargar_imagen(bytes_base)
            rostros = detectar_rostros(imagen_base)

            logo_bytes = None
            if logo is not None and aplicacion != "sin_logo":
                logo_bytes = descargar_archivo(BUCKET_LOGOS, logo.ruta_storage)

            bytes_resultado, metadata = generar_formato(
                bytes_base,
                tipo_formato,
                rostros,
                logo_bytes=logo_bytes,
                aplicacion=aplicacion,
                posicion=posicion,
                opacidad=opacidad,
                modo=modo,
                focus_x=focus_x,
                focus_y=focus_y,
                zoom=zoom,
            )

            # Verificacion de integridad del original (misma regla del
            # Paso 7): si cambio durante el procesamiento, es un error
            # critico, sin importar si la base usada fue el original o
            # una mejora ya existente.
            hash_despues = _hash(descargar_archivo(BUCKET_FOTOGRAFIAS, fotografia.ruta_storage))
            if hash_antes != hash_despues:
                derivado.estado = "error"
                derivado.error_mensaje = "Verificacion de integridad fallida: el original cambio durante el procesamiento."
                db.session.commit()
                return derivado

            if bytes_resultado is None:
                derivado.estado = "error"
                derivado.error_mensaje = metadata.get("advertencia") or "No se pudo generar el formato."
                db.session.commit()
                return derivado

            ruta = ruta_derivado_formato(empresa_id, proyecto_id, tipo_formato)
            subir_archivo(BUCKET_FOTOGRAFIAS, ruta, bytes_resultado, "image/jpeg")

            derivado.ruta_storage = ruta
            derivado.tipo_mime = "image/jpeg"
            derivado.tamano_bytes = len(bytes_resultado)
            derivado.rostros_detectados = len(rostros)
            derivado.ancho_px = metadata["ancho_px"]
            derivado.alto_px = metadata["alto_px"]
            derivado.advertencia = metadata.get("advertencia")
            derivado.duracion_segundos = metadata["duracion_segundos"]
            derivado.focus_x = metadata.get("focus_x")
            derivado.focus_y = metadata.get("focus_y")
            derivado.crop_x = metadata.get("crop_x")
            derivado.crop_y = metadata.get("crop_y")
            derivado.crop_width = metadata.get("crop_width")
            derivado.crop_height = metadata.get("crop_height")
            derivado.algoritmo_recorte = metadata.get("algoritmo_recorte")
            derivado.estado = "completada"
        except Exception as exc:
            derivado.estado = "error"
            derivado.error_mensaje = str(exc)[:500]
        db.session.commit()
        return derivado

    return encolar(_procesar)
