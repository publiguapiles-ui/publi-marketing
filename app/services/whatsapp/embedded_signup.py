"""Registro insertado de WhatsApp (Embedded Signup), incluida
Coexistencia -- ver https://developers.facebook.com/documentation/
business-messaging/whatsapp/embedded-signup/implementation

Reutiliza el MISMO META_APP_ID/META_APP_SECRET que ya usa la conexion
OAuth de Meta Ads (app/services/meta/auth_service.py) y el mismo
MetaClient -- no hay una app de Meta separada para WhatsApp.

Este servicio SOLO habla con la Graph API y traduce sus respuestas --
no toca la base de datos (eso sigue siendo trabajo de
app/services/whatsapp/conexion.py, en particular guardar_conexion(),
que este flujo reutiliza tal cual).
"""

import os

from app.services.meta.client import MetaClient


class ErrorConfiguracionEmbeddedSignup(RuntimeError):
    """Falta META_APP_ID/META_APP_SECRET para completar el intercambio."""


def _config_obligatoria():
    app_id = os.environ.get("META_APP_ID")
    app_secret = os.environ.get("META_APP_SECRET")
    if not (app_id and app_secret):
        raise ErrorConfiguracionEmbeddedSignup("Meta no esta configurado (faltan META_APP_ID / META_APP_SECRET).")
    return app_id, app_secret


def intercambiar_code_por_token(code):
    """`code` (devuelto por FB.login en el navegador, valido solo 30s)
    -> access token. A diferencia del OAuth por redireccion de Meta
    Ads, el registro insertado via SDK de JS no usa `redirect_uri` --
    Meta lo documenta explicitamente como un intercambio sin ese
    parametro."""
    app_id, app_secret = _config_obligatoria()
    cliente = MetaClient()
    respuesta = cliente.get(
        "oauth/access_token",
        params={"client_id": app_id, "client_secret": app_secret, "code": code},
    )
    return respuesta["access_token"]


def suscribir_app_a_waba(waba_id, access_token):
    """POST /{WABA_ID}/subscribed_apps -- sin esto, Meta entrega
    mensajes reales a la WABA pero nunca los reenvia a nuestro webhook
    (la app puede quedar suscrita a un WABA distinto por defecto). Es
    la misma llamada que se hizo manualmente por Graph API Explorer
    para diagnosticar y arreglar la entrega de webhooks reales en esta
    sesion -- aqui queda automatizada para cada conexion nueva."""
    cliente = MetaClient(access_token=access_token)
    cliente.post(f"{waba_id}/subscribed_apps")


def sincronizar_datos_coexistencia(phone_number_id, access_token):
    """Dispara la sincronizacion de contactos e historial de mensajes
    de la app de WhatsApp Business del cliente (solo aplica cuando la
    conexion vino de Coexistencia). Meta exige iniciar esto dentro de
    las 24h siguientes a la incorporacion o el cliente debe repetir el
    registro insertado -- por eso se llama inmediatamente despues de
    guardar la conexion.

    Best-effort a proposito (igual que app/services/whatsapp/webhook.py):
    un fallo aqui no debe impedir que la conexion se guarde ni mostrar
    un error al usuario -- en el peor caso, el historial/contactos
    simplemente no se sincronizan, pero los mensajes nuevos siguen
    llegando por el webhook de "messages" de siempre."""
    cliente = MetaClient(access_token=access_token)
    for tipo_sincronizacion in ("smb_app_state_sync", "history"):
        try:
            cliente.post(
                f"{phone_number_id}/smb_app_data",
                data={"messaging_product": "whatsapp", "sync_type": tipo_sincronizacion},
            )
        except Exception:
            pass
