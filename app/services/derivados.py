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


def crear_mejora_automatica(empresa_id, proyecto_id, fotografia, usuario_id):
    """Crea (sincronamente, via services/tareas.py) una version mejorada
    de `fotografia`. Devuelve el registro FotografiaDerivada, con
    estado "completada" o "error" (el error se guarda en el registro,
    nunca se pierde silenciosamente y nunca toca el original).
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

            bytes_resultado, metadata = mejorar_fotografia(bytes_originales)

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
