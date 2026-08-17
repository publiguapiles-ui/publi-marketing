"""Conexion con WhatsApp Business Platform (Cloud API de Meta) --
NUNCA WhatsApp personal. Los tokens se cifran con la MISMA clave y
funciones que ya usa Datos de Meta (app/core/crypto.py, pensado
explicitamente para reutilizarse con integraciones futuras) -- nunca
se guarda un token en texto plano ni se expone a rutas/templates.
"""

from app.core.crypto import cifrar

ESTADOS_CONEXION_WHATSAPP = ["conectada", "desconectada"]


def obtener_conexion(empresa_id):
    from app.extensions import db
    from app.models import WhatsAppConnection

    return db.session.query(WhatsAppConnection).filter_by(empresa_id=empresa_id).first()


def estado_conexion(empresa_id):
    """(conectada_bool, ultima_sincronizacion_o_None). Nunca expone
    ningun token -- solo si existe una conexion guardada y su estado."""
    conexion = obtener_conexion(empresa_id)
    if conexion is None or conexion.estado != "conectada":
        return False, None
    return True, conexion.ultima_sincronizacion_en


def guardar_conexion(empresa_id, usuario_id, phone_number_id, whatsapp_business_account_id, access_token, verify_token):
    """(conexion_o_None, error_o_None). Crea o actualiza la conexion de
    la empresa (una por empresa, se sobreescribe al reconfigurar en vez
    de guardar historico -- a diferencia de MetaConexion, aqui no hay
    flujo OAuth con expiracion frecuente). Si `access_token`/
    `verify_token` llegan vacios y ya existe una conexion, se conserva
    el valor cifrado anterior -- permite editar el resto de los campos
    sin forzar a re-pegar el token cada vez (nunca se muestra para
    poder copiarlo de vuelta, punto 12 del enunciado)."""
    from app.extensions import db
    from app.models import WhatsAppConnection

    phone_number_id = (phone_number_id or "").strip()
    whatsapp_business_account_id = (whatsapp_business_account_id or "").strip()
    access_token = (access_token or "").strip()
    verify_token = (verify_token or "").strip()

    if not phone_number_id:
        return None, "El Phone Number ID es obligatorio."
    if not whatsapp_business_account_id:
        return None, "El WhatsApp Business Account ID es obligatorio."

    conexion = obtener_conexion(empresa_id)

    if not access_token and conexion is None:
        return None, "El Access Token es obligatorio."
    if not verify_token and conexion is None:
        return None, "El Verify Token es obligatorio."

    if conexion is None:
        conexion = WhatsAppConnection(empresa_id=empresa_id)
        db.session.add(conexion)

    conexion.phone_number_id = phone_number_id
    conexion.whatsapp_business_account_id = whatsapp_business_account_id
    if access_token:
        conexion.access_token_cifrado = cifrar(access_token)
    if verify_token:
        conexion.verify_token_cifrado = cifrar(verify_token)
    conexion.estado = "conectada"
    conexion.configurado_por = usuario_id
    db.session.commit()
    return conexion, None


def desconectar(empresa_id):
    """Marca la conexion como desconectada -- nunca borra el historico
    de contactos/conversaciones/mensajes ya recibidos."""
    from app.extensions import db

    conexion = obtener_conexion(empresa_id)
    if conexion is None:
        return False
    conexion.estado = "desconectada"
    db.session.commit()
    return True
