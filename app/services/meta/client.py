"""Cliente HTTP puro para la Graph API de Meta.

No sabe nada de Publi Marketing: no importa modelos, no abre sesion de
base de datos, no sabe que es una "empresa". Solo habla HTTP con
graph.facebook.com y traduce errores de Meta a `MetaAPIError`. Esto es
a proposito el unico lugar del proyecto que construye URLs de
graph.facebook.com -- todo lo demas (auth_service, cuentas_service,
futuro insights_service) pasa por aqui.
"""

import os

import requests

TIEMPO_ESPERA_SEGUNDOS = 15


class MetaAPIError(RuntimeError):
    """Un error devuelto por la Graph API de Meta (nunca un error de
    red/HTTP generico -- ver MetaClient._solicitar, que distingue
    ambos casos)."""

    def __init__(self, mensaje, codigo=None, tipo=None, subcodigo=None):
        super().__init__(mensaje)
        self.codigo = codigo
        self.tipo = tipo
        self.subcodigo = subcodigo


def _version_api():
    return os.environ.get("META_API_VERSION", "v21.0")


class MetaClient:
    """Envoltorio delgado sobre la Graph API. `access_token` se recibe
    ya descifrado por el llamador (ver services/meta/conexiones.py) --
    este cliente nunca descifra ni guarda tokens, solo los usa para la
    peticion en curso.
    """

    def __init__(self, access_token=None, version_api=None):
        self.access_token = access_token
        self.version_api = version_api or _version_api()
        self.base_url = f"https://graph.facebook.com/{self.version_api}"

    def _solicitar(self, metodo, ruta, params=None, data=None, access_token=None):
        token = access_token or self.access_token
        params = dict(params or {})
        if token:
            params["access_token"] = token

        url = ruta if ruta.startswith("http") else f"{self.base_url}/{ruta.lstrip('/')}"
        try:
            resp = requests.request(metodo, url, params=params, data=data, timeout=TIEMPO_ESPERA_SEGUNDOS)
        except requests.RequestException as exc:
            # Error de red/timeout -- nunca se confunde con un error de
            # negocio de Meta (permiso denegado, token invalido, etc.).
            raise MetaAPIError(f"No se pudo contactar a Meta: {exc}") from exc

        try:
            cuerpo = resp.json()
        except ValueError:
            cuerpo = {}

        if resp.status_code >= 400 or "error" in cuerpo:
            error = cuerpo.get("error", {})
            raise MetaAPIError(
                error.get("message", f"Error HTTP {resp.status_code} de Meta"),
                codigo=error.get("code"),
                tipo=error.get("type"),
                subcodigo=error.get("error_subcode"),
            )
        return cuerpo

    def get(self, ruta, params=None, access_token=None):
        return self._solicitar("GET", ruta, params=params, access_token=access_token)

    def post(self, ruta, data=None, access_token=None):
        return self._solicitar("POST", ruta, data=data, access_token=access_token)
