"""Orquestador de sincronizacion (Paso 2, puntos 6, 12 y 13): crea y
actualiza filas reales de SincronizacionMeta (el modelo del Paso 1
existia pero ningun codigo lo usaba todavia), llama a
campanas_service.py + insights_service.py, y clasifica errores.

Disciplina igual que app/services/sesiones.py de Photo Studio: el
trabajo real pasa por app.services.tareas.encolar() recibiendo solo
IDs (nunca objetos ORM en el closure), para que cambiar `encolar()`
por una cola real despues no requiera tocar este modulo.
"""

from datetime import datetime, timezone

MAX_INTENTOS = 3


def iniciar_sincronizacion(empresa_id, usuario_id, tipo, fecha_inicio, fecha_fin):
    """Crea la fila de SincronizacionMeta y ejecuta el trabajo (via
    encolar -- hoy sincrono). Devuelve (sincronizacion, error_o_None):
    error_o_None viene de validaciones PREVIAS (ej. sin conexion), no
    del resultado del trabajo en si -- para eso hay que releer el
    estado de la sincronizacion devuelta."""
    from app.extensions import db
    from app.models import SincronizacionMeta
    from app.services.meta.conexiones import obtener_conexion_activa
    from app.services.tareas import encolar

    conexion = obtener_conexion_activa(empresa_id)
    if conexion is None:
        return None, "No hay una conexión activa con Meta."

    sincronizacion = SincronizacionMeta(
        empresa_id=empresa_id,
        conexion_id=conexion.id,
        tipo=tipo,
        estado="pendiente",
        fecha_inicio_periodo=fecha_inicio,
        fecha_fin_periodo=fecha_fin,
        creado_por=usuario_id,
    )
    db.session.add(sincronizacion)
    db.session.commit()

    encolar(_ejecutar_sincronizacion, sincronizacion.id)

    # Se relee desde la base de datos a proposito (no se confia en un
    # valor de retorno de encolar()) -- mismo motivo que en
    # sesiones.py::procesar_siguiente_item.
    sincronizacion_actualizada = db.session.get(SincronizacionMeta, sincronizacion.id)
    return sincronizacion_actualizada, None


def _ejecutar_sincronizacion(sincronizacion_id):
    from app.extensions import db
    from app.models import SincronizacionMeta
    from app.services.meta.campanas_service import sincronizar_estructura
    from app.services.meta.insights_service import sincronizar_insights

    sincronizacion = db.session.get(SincronizacionMeta, sincronizacion_id)
    if sincronizacion is None:
        return None

    sincronizacion.estado = "en_progreso"
    sincronizacion.iniciada_en = datetime.now(timezone.utc)
    sincronizacion.intentos += 1
    db.session.commit()

    resumen_estructura, error_estructura = sincronizar_estructura(sincronizacion.empresa_id)
    if error_estructura:
        _marcar_error(sincronizacion, error_estructura)
        return sincronizacion

    resumen_insights, error_insights = sincronizar_insights(
        sincronizacion.empresa_id,
        sincronizacion.fecha_inicio_periodo,
        sincronizacion.fecha_fin_periodo,
        sincronizacion_id=sincronizacion.id,
    )
    if error_insights:
        _marcar_error(sincronizacion, error_insights)
        return sincronizacion

    sincronizacion.registros_procesados = (
        resumen_estructura["campanas"] + resumen_estructura["conjuntos_anuncios"] + resumen_estructura["anuncios"]
        + resumen_insights["filas_metrica_guardadas"]
    )
    sincronizacion.estado = "completada"
    sincronizacion.finalizada_en = datetime.now(timezone.utc)
    sincronizacion.error_mensaje = None
    db.session.commit()
    return sincronizacion


def _marcar_error(sincronizacion, mensaje):
    from app.extensions import db

    sincronizacion.estado = "error"
    sincronizacion.error_mensaje = (mensaje or "")[:500]
    sincronizacion.finalizada_en = datetime.now(timezone.utc)
    db.session.commit()


def reintentar_sincronizacion(empresa_id, sincronizacion_id):
    """Reintenta una sincronizacion que quedo en error. Nunca reintenta
    automaticamente -- solo cuando el usuario lo pide explicitamente
    (boton [Reintentar]), y nunca mas de MAX_INTENTOS veces en total
    (Paso 2, punto 13: "no hacer reintentos infinitos")."""
    from app.extensions import db
    from app.models import SincronizacionMeta
    from app.services.tareas import encolar

    sincronizacion = (
        db.session.query(SincronizacionMeta).filter_by(id=sincronizacion_id, empresa_id=empresa_id).first()
    )
    if sincronizacion is None:
        return None, "La sincronización no existe o no pertenece a esta empresa."
    if sincronizacion.estado != "error":
        return None, "Esta sincronización no está en estado de error."
    if sincronizacion.intentos >= MAX_INTENTOS:
        return None, f"Se alcanzó el máximo de {MAX_INTENTOS} intentos. Verifica la conexión e inicia una sincronización nueva."

    encolar(_ejecutar_sincronizacion, sincronizacion.id)
    sincronizacion_actualizada = db.session.get(SincronizacionMeta, sincronizacion_id)
    return sincronizacion_actualizada, None


def obtener_sincronizacion(empresa_id, sincronizacion_id):
    from app.extensions import db
    from app.models import SincronizacionMeta

    return db.session.query(SincronizacionMeta).filter_by(id=sincronizacion_id, empresa_id=empresa_id).first()


def obtener_ultima_sincronizacion(empresa_id):
    from app.extensions import db
    from app.models import SincronizacionMeta

    return (
        db.session.query(SincronizacionMeta)
        .filter_by(empresa_id=empresa_id)
        .order_by(SincronizacionMeta.creado_en.desc())
        .first()
    )


def listar_sincronizaciones_empresa(empresa_id, limite=10):
    from app.extensions import db
    from app.models import SincronizacionMeta

    return (
        db.session.query(SincronizacionMeta)
        .filter_by(empresa_id=empresa_id)
        .order_by(SincronizacionMeta.creado_en.desc())
        .limit(limite)
        .all()
    )
