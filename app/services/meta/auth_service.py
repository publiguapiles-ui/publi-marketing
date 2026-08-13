"""Flujo OAuth de Meta (Login for Business / Facebook Login), documentado en
https://developers.facebook.com/docs/facebook-login/guides/access-tokens/get-long-lived
y https://developers.facebook.com/docs/graph-api/guides/games/access-tokens

Este servicio SOLO construye URLs y traduce respuestas de OAuth -- no
toca la base de datos (eso es trabajo de conexiones.py, que llama a
este servicio, nunca al reves).
"""

import os
import secrets

from app.services.meta.client import MetaClient, _version_api

# Scopes de solo lectura para el Paso 1: alcanza para descubrir cuentas
# publicitarias/paginas/Instagram y leer insights en pasos futuros.
# `ads_management` (crear/pausar campanas) se agrega deliberadamente
# despues, cuando exista esa funcionalidad -- pedir permisos que
# todavia no se usan es una mala practica frente a Meta App Review.
#
# "instagram_basic" quedo fuera (Paso 6, verificacion real): Meta
# rechazo el dialogo de OAuth completo con "Invalid Scopes:
# instagram_basic" para la app real creada en este paso, aunque la
# documentacion publica todavia lo lista como vigente -- probablemente
# porque a esta app le falta agregar el producto "Instagram" en el
# panel de Meta for Developers. Sacarlo de la lista predeterminada no
# es una decision de diseño, es la unica forma de que ads_read/
# pages_show_list (el requisito central de este paso) funcionen hoy;
# ver informe del Paso 6, pendientes.
SCOPES_PREDETERMINADOS = [
    "ads_read",
    "pages_show_list",
    "pages_read_engagement",
    "business_management",
]


class ErrorConfiguracionMeta(RuntimeError):
    """Faltan variables de entorno para hablar con Meta."""


def meta_configurado():
    return bool(os.environ.get("META_APP_ID") and os.environ.get("META_APP_SECRET") and os.environ.get("META_REDIRECT_URI"))


def _config_obligatoria():
    app_id = os.environ.get("META_APP_ID")
    app_secret = os.environ.get("META_APP_SECRET")
    redirect_uri = os.environ.get("META_REDIRECT_URI")
    if not (app_id and app_secret and redirect_uri):
        raise ErrorConfiguracionMeta(
            "Meta no esta configurado (faltan META_APP_ID / META_APP_SECRET / META_REDIRECT_URI)."
        )
    return app_id, app_secret, redirect_uri


def generar_estado_csrf():
    """Token aleatorio de un solo uso para el parametro `state` de
    OAuth -- se guarda en la sesion de Flask antes de redirigir a Meta
    y se compara al volver, para que nadie pueda forzar el callback
    con un `code` ajeno (CSRF del flujo OAuth)."""
    return secrets.token_urlsafe(32)


def construir_url_autorizacion(estado, scopes=None):
    app_id, _secret, redirect_uri = _config_obligatoria()
    scopes = scopes or SCOPES_PREDETERMINADOS
    version = _version_api()
    params = "&".join(
        [
            f"client_id={app_id}",
            f"redirect_uri={redirect_uri}",
            f"state={estado}",
            f"scope={','.join(scopes)}",
            "response_type=code",
        ]
    )
    return f"https://www.facebook.com/{version}/dialog/oauth?{params}"


def intercambiar_codigo_por_token(codigo):
    """Codigo de autorizacion -> token de corta duracion (~1-2h)."""
    app_id, app_secret, redirect_uri = _config_obligatoria()
    cliente = MetaClient()
    respuesta = cliente.get(
        "oauth/access_token",
        params={
            "client_id": app_id,
            "client_secret": app_secret,
            "redirect_uri": redirect_uri,
            "code": codigo,
        },
    )
    return respuesta["access_token"]


def intercambiar_por_token_larga_duracion(token_corto):
    """Token de corta duracion -> token de larga duracion (~60 dias).
    Es el token que realmente se guarda cifrado en MetaConexion."""
    app_id, app_secret, _redirect_uri = _config_obligatoria()
    cliente = MetaClient()
    respuesta = cliente.get(
        "oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": token_corto,
        },
    )
    return respuesta["access_token"], respuesta.get("expires_in")


def obtener_identidad_meta(access_token):
    """Devuelve {"id": ..., "name": ...} del usuario de Meta dueño del token."""
    cliente = MetaClient(access_token=access_token)
    return cliente.get("me", params={"fields": "id,name"})
