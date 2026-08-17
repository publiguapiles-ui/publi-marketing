"""Webhook de WhatsApp Cloud API -- recibe mensajes entrantes. NUNCA
procesa IA ni envia respuestas automaticas (eso queda explicitamente
fuera de este modulo, ver enunciado punto 13).

El webhook es UNA URL publica compartida (Meta llama a la misma URL
para todas las empresas que compartan la app de Meta que la
administra) -- no hay forma de saber a que empresa pertenece un evento
hasta leer `phone_number_id` dentro del payload (punto 9, paso 3:
"identificar empresa/conexion"). La verificacion GET (handshake) por
eso compara contra el verify_token de CUALQUIER conexion activa, no
contra una sola empresa.
"""

from datetime import datetime, timezone

ETIQUETAS_TIPO_MENSAJE_NO_TEXTO = {
    "image": "[Imagen]",
    "video": "[Video]",
    "audio": "[Audio]",
    "document": "[Documento]",
    "location": "[Ubicación]",
    "sticker": "[Sticker]",
    "contacts": "[Contacto compartido]",
    "reaction": "[Reacción]",
}


def verificar_challenge(modo, token, challenge):
    """(challenge_o_None). Implementa el handshake GET que exige Meta
    al configurar un webhook: responde el challenge tal cual si el
    modo es "subscribe" y el token coincide con el verify_token
    (descifrado) de alguna conexion -- nunca compara contra texto
    plano guardado en la base de datos."""
    from app.core.crypto import descifrar
    from app.extensions import db
    from app.models import WhatsAppConnection

    if modo != "subscribe" or not token:
        return None

    conexiones = db.session.query(WhatsAppConnection).filter_by(estado="conectada").all()
    for conexion in conexiones:
        if descifrar(conexion.verify_token_cifrado) == token:
            return challenge
    return None


def _extraer_contenido(mensaje):
    tipo = mensaje.get("type")
    if tipo == "text":
        return mensaje.get("text", {}).get("body", "") or "[Mensaje de texto vacío]"
    return ETIQUETAS_TIPO_MENSAJE_NO_TEXTO.get(tipo, f"[Mensaje de tipo {tipo}]" if tipo else "[Mensaje]")


def _guardar_mensaje_entrante(conexion, mensaje, perfiles):
    from app.extensions import db
    from app.models import WhatsAppContact, WhatsAppConversation, WhatsAppMessage

    id_externo = mensaje.get("id")
    if id_externo and db.session.query(WhatsAppMessage).filter_by(id_externo=id_externo).first():
        return False  # ya guardado -- Meta reintenta webhooks que no confirman 200 a tiempo

    telefono = mensaje.get("from")
    if not telefono:
        return False

    contacto = db.session.query(WhatsAppContact).filter_by(empresa_id=conexion.empresa_id, telefono=telefono).first()
    if contacto is None:
        contacto = WhatsAppContact(
            empresa_id=conexion.empresa_id, conexion_id=conexion.id, telefono=telefono, nombre=perfiles.get(telefono),
        )
        db.session.add(contacto)
        db.session.flush()
    elif perfiles.get(telefono) and not contacto.nombre:
        contacto.nombre = perfiles.get(telefono)

    conversacion = (
        db.session.query(WhatsAppConversation)
        .filter_by(empresa_id=conexion.empresa_id, contacto_id=contacto.id)
        .first()
    )
    if conversacion is None:
        conversacion = WhatsAppConversation(empresa_id=conexion.empresa_id, contacto_id=contacto.id)
        db.session.add(conversacion)
        db.session.flush()

    timestamp = mensaje.get("timestamp")
    try:
        creado_en = datetime.fromtimestamp(int(timestamp), tz=timezone.utc) if timestamp else datetime.now(timezone.utc)
    except (TypeError, ValueError):
        creado_en = datetime.now(timezone.utc)

    db.session.add(WhatsAppMessage(
        conversacion_id=conversacion.id, direccion="entrante", contenido=_extraer_contenido(mensaje),
        id_externo=id_externo, creado_en=creado_en,
    ))
    conversacion.actualizado_en = datetime.now(timezone.utc)
    return True


def procesar_evento(payload):
    """Procesa el body de un webhook POST de WhatsApp Cloud API.
    Idempotente (ignora mensajes ya guardados por id_externo) y nunca
    lanza -- una entrada con forma inesperada se cuenta como "no
    reconocida" y se ignora, en vez de fallar con 500 (un 500 aqui
    haria que Meta reintente el mismo webhook indefinidamente).
    Devuelve un resumen para logging/tests, nunca se le muestra al
    remitente del webhook."""
    from app.extensions import db
    from app.models import WhatsAppConnection

    resultado = {"mensajes_guardados": 0, "mensajes_duplicados": 0, "entradas_no_reconocidas": 0}

    for entrada in payload.get("entry") or []:
        for cambio in entrada.get("changes") or []:
            valor = cambio.get("value") or {}
            phone_number_id = (valor.get("metadata") or {}).get("phone_number_id")
            if not phone_number_id:
                resultado["entradas_no_reconocidas"] += 1
                continue

            conexion = db.session.query(WhatsAppConnection).filter_by(phone_number_id=phone_number_id).first()
            if conexion is None:
                resultado["entradas_no_reconocidas"] += 1
                continue

            perfiles = {c.get("wa_id"): (c.get("profile") or {}).get("name") for c in (valor.get("contacts") or [])}

            for mensaje in valor.get("messages") or []:
                if _guardar_mensaje_entrante(conexion, mensaje, perfiles):
                    resultado["mensajes_guardados"] += 1
                else:
                    resultado["mensajes_duplicados"] += 1

            conexion.ultima_sincronizacion_en = datetime.now(timezone.utc)

    db.session.commit()
    return resultado
