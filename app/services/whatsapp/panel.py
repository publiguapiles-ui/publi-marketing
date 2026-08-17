"""Panel principal de API WhatsApp -- SOLAMENTE los 3 bloques que pide
el enunciado (conversaciones sin responder / sin abrir / ultimos 3
mensajes recibidos). Nunca procesa IA, nunca envia mensajes -- es
lectura pura de lo que ya llego por webhook.py.
"""

from datetime import datetime, timezone


def _mensajes_recientes_por_conversacion(empresa_id):
    """dict {conversacion_id: ultimo_mensaje} -- el ultimo mensaje
    (de cualquier direccion) de cada conversacion de la empresa, para
    decidir "sin responder" (punto 5) y "sin abrir" (punto 6)."""
    from sqlalchemy import and_, func

    from app.extensions import db
    from app.models import WhatsAppConversation, WhatsAppMessage

    subconsulta = (
        db.session.query(
            WhatsAppMessage.conversacion_id.label("conversacion_id"),
            func.max(WhatsAppMessage.creado_en).label("ultimo_creado_en"),
        )
        .join(WhatsAppConversation, WhatsAppMessage.conversacion_id == WhatsAppConversation.id)
        .filter(WhatsAppConversation.empresa_id == empresa_id)
        .group_by(WhatsAppMessage.conversacion_id)
        .subquery()
    )

    filas = (
        db.session.query(WhatsAppMessage)
        .join(
            subconsulta,
            and_(
                WhatsAppMessage.conversacion_id == subconsulta.c.conversacion_id,
                WhatsAppMessage.creado_en == subconsulta.c.ultimo_creado_en,
            ),
        )
        .all()
    )
    return {m.conversacion_id: m for m in filas}


def _serializar_mensaje(mensaje):
    from app.extensions import db
    from app.models import WhatsAppContact, WhatsAppConversation

    contacto = (
        db.session.query(WhatsAppContact)
        .join(WhatsAppConversation, WhatsAppContact.id == WhatsAppConversation.contacto_id)
        .filter(WhatsAppConversation.id == mensaje.conversacion_id)
        .first()
    )
    return {
        "conversacion_id": mensaje.conversacion_id,
        "contacto_nombre": contacto.nombre if contacto else None,
        "contacto_telefono": contacto.telefono if contacto else None,
        "contenido": mensaje.contenido,
        "creado_en": mensaje.creado_en.isoformat(),
    }


def construir_panel(empresa_id):
    """Los 3 bloques + el estado de conexion. "Sin responder" cuenta
    CONVERSACIONES (no mensajes sueltos): varios mensajes entrantes
    seguidos del mismo contacto son 1 sola conversacion pendiente
    (punto 5). "Sin abrir" cuenta conversaciones cuyo ultimo mensaje es
    mas reciente que la ultima vez que alguien la marco como vista
    (`leida_en`), o que nunca se marcaron como vistas (punto 6)."""
    from app.extensions import db
    from app.models import WhatsAppConversation, WhatsAppMessage
    from app.services.whatsapp.conexion import estado_conexion

    conectada, ultima_sync = estado_conexion(empresa_id)

    ultimo_por_conversacion = _mensajes_recientes_por_conversacion(empresa_id)
    conversaciones = db.session.query(WhatsAppConversation).filter_by(empresa_id=empresa_id).all()

    sin_responder = 0
    sin_abrir = 0
    for conversacion in conversaciones:
        ultimo = ultimo_por_conversacion.get(conversacion.id)
        if ultimo is None:
            continue
        if ultimo.direccion == "entrante":
            sin_responder += 1
        if conversacion.leida_en is None or conversacion.leida_en < ultimo.creado_en:
            sin_abrir += 1

    ultimos_mensajes = (
        db.session.query(WhatsAppMessage)
        .join(WhatsAppConversation, WhatsAppMessage.conversacion_id == WhatsAppConversation.id)
        .filter(WhatsAppConversation.empresa_id == empresa_id, WhatsAppMessage.direccion == "entrante")
        .order_by(WhatsAppMessage.creado_en.desc())
        .limit(3)
        .all()
    )

    return {
        "conectada": conectada,
        "ultima_sincronizacion": ultima_sync.isoformat() if ultima_sync else None,
        "ultima_sincronizacion_texto": ultima_sync.strftime("%d/%m/%Y %H:%M UTC") if ultima_sync else None,
        "sin_responder": sin_responder,
        "sin_abrir": sin_abrir,
        "ultimos_mensajes": [_serializar_mensaje(m) for m in ultimos_mensajes],
    }


def marcar_conversacion_vista(empresa_id, conversacion_id):
    """True si se marco -- False si la conversacion no existe o no
    pertenece a esta empresa (aislamiento multiempresa)."""
    from app.extensions import db
    from app.models import WhatsAppConversation

    conversacion = db.session.query(WhatsAppConversation).filter_by(id=conversacion_id, empresa_id=empresa_id).first()
    if conversacion is None:
        return False
    conversacion.leida_en = datetime.now(timezone.utc)
    db.session.commit()
    return True
