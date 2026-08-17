"""Conexion con WhatsApp Business Platform (Cloud API de Meta) --
NUNCA WhatsApp personal. Los tokens se cifran con la MISMA clave y
funciones que ya usa Datos de Meta (app/core/crypto.py, pensado
explicitamente para reutilizarse con integraciones futuras) -- nunca
se guarda un token en texto plano ni se expone a rutas/templates.

No se agregan variables de entorno globales (WHATSAPP_ACCESS_TOKEN,
etc.) a proposito: cada empresa tiene su propia cuenta de WhatsApp
Business, y una variable de entorno de Railway es global a todo el
despliegue -- usarla rompería el aislamiento multiempresa (punto 7 del
enunciado). Los tokens siguen viviendo cifrados por empresa en
WhatsAppConnection, igual que MetaConexion; la unica variable de
entorno que esta integracion reutiliza es META_TOKEN_ENCRYPTION_KEY
(la clave de cifrado, no un secreto de WhatsApp en si), que ya esta
configurada en Railway desde Datos de Meta.
"""

import secrets

from app.core.crypto import cifrar, descifrar

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


def verify_token_actual(empresa_id):
    """El Verify Token EN CLARO de la empresa, o None. A diferencia del
    Access Token, el enunciado permite mostrar este valor (no es un
    secreto de acceso a la cuenta, solo la palabra que Meta repite en
    el handshake del webhook) -- se descifra unicamente aqui, nunca se
    guarda descifrado."""
    conexion = obtener_conexion(empresa_id)
    if conexion is None:
        return None
    return descifrar(conexion.verify_token_cifrado)


def regenerar_verify_token(empresa_id):
    """(verify_token_nuevo_o_None). Genera un Verify Token nuevo al
    azar y lo guarda cifrado -- el llamador debe mostrarselo UNA vez al
    usuario para que lo actualice tambien en Meta App Dashboard (el
    webhook GET dejara de validar con el token viejo de inmediato)."""
    from app.extensions import db

    conexion = obtener_conexion(empresa_id)
    if conexion is None:
        return None
    nuevo_token = secrets.token_urlsafe(24)
    conexion.verify_token_cifrado = cifrar(nuevo_token)
    db.session.commit()
    return nuevo_token


def probar_conexion_whatsapp(empresa_id):
    """(ok_bool, mensaje, detalle_o_None). Llama a la Graph API real de
    Meta (GET /{phone_number_id}) para confirmar que el token es
    valido, el Phone Number ID existe y la cuenta tiene acceso -- ver
    https://developers.facebook.com/docs/whatsapp/cloud-api/reference/phone-numbers.
    NUNCA expone el Access Token en el mensaje de error; `detalle`
    trae el codigo/tipo que Meta reporto, para diagnosticar sin
    filtrar credenciales."""
    from app.services.meta.client import MetaAPIError, MetaClient

    conexion = obtener_conexion(empresa_id)
    if conexion is None:
        return False, "Todavía no hay ninguna conexión configurada.", None

    access_token = descifrar(conexion.access_token_cifrado)
    if access_token is None:
        return False, "El token guardado no se pudo leer -- vuelve a conectar WhatsApp.", None

    cliente = MetaClient(access_token=access_token)
    try:
        cliente.get(conexion.phone_number_id, params={"fields": "verified_name,display_phone_number,quality_rating"})
    except MetaAPIError as exc:
        return False, str(exc), {"codigo": exc.codigo, "tipo": exc.tipo, "endpoint": conexion.phone_number_id}

    return True, "Conexión correcta.", None
