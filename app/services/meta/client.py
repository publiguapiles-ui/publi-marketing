"""Cliente HTTP puro para la Graph API de Meta.

No sabe nada de Publi Marketing: no importa modelos, no abre sesion de
base de datos, no sabe que es una "empresa". Solo habla HTTP con
graph.facebook.com y traduce errores de Meta a `MetaAPIError`. Esto es
a proposito el unico lugar del proyecto que construye URLs de
graph.facebook.com -- todo lo demas (auth_service, cuentas_service,
futuro insights_service) pasa por aqui.
"""

import json
import os

import requests

# Causa raiz real encontrada en produccion (Paso 6, diagnostico): un
# timeout de 15s es demasiado agresivo para /insights de la Marketing
# API -- Meta puede tardar mas que eso en responder bajo carga real,
# sobre todo con varios dias de datos. Cuando eso pasaba, requests
# lanzaba ReadTimeout, MetaClient lo envolvia como "No se pudo
# contactar a Meta: ..." y errores.clasificar_error_meta lo clasificaba
# como "temporal" -- el usuario veia "Meta tuvo un problema temporal"
# una y otra vez, cuando el problema nunca fue de Meta ni de limite de
# cuota, era nuestro propio timeout demasiado corto. 60s da margen real
# sin arriesgar el timeout de gunicorn (300s, ver Procfile), incluso
# sincronizando muchas entidades una por una (insights_service.py).
TIEMPO_ESPERA_SEGUNDOS = 60

# Headers documentados por Meta para reportar cuanto de la cuota de
# solicitudes ya se consumio (https://developers.facebook.com/docs/
# graph-api/overview/rate-limiting) -- Meta no los envia siempre (depende
# del endpoint/version), asi que _extraer_uso_meta() nunca asume que van
# a estar presentes.
_HEADERS_USO_META = {
    "x-app-usage": "app",
    "x-ad-account-usage": "cuenta_publicitaria",
    "x-page-usage": "pagina",
    "x-business-use-case-usage": "business_use_case",
}


def _extraer_uso_meta(resp):
    """Devuelve {"app": {...}, "cuenta_publicitaria": {...}, ...} con lo
    que Meta realmente reporto sobre el uso de la cuota de solicitudes
    en ESTA respuesta -- nunca un valor inventado ni estimado por
    nosotros. None si Meta no mando ninguno de estos headers."""
    uso = {}
    for nombre_header, clave in _HEADERS_USO_META.items():
        valor = resp.headers.get(nombre_header)
        if not valor:
            continue
        try:
            uso[clave] = json.loads(valor)
        except ValueError:
            continue
    return uso or None


class MetaAPIError(RuntimeError):
    """Un error devuelto por la Graph API de Meta (nunca un error de
    red/HTTP generico -- ver MetaClient._solicitar, que distingue
    ambos casos)."""

    def __init__(self, mensaje, codigo=None, tipo=None, subcodigo=None, uso_meta=None):
        super().__init__(mensaje)
        self.codigo = codigo
        self.tipo = tipo
        self.subcodigo = subcodigo
        # Ver _extraer_uso_meta -- solo presente si Meta lo reporto en la
        # respuesta que produjo este error (tipicamente utilizado por
        # errores.py para explicar un "limite_api" con datos reales en
        # vez de un mensaje generico).
        self.uso_meta = uso_meta


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
        es_url_completa = ruta.startswith("http")
        token = access_token or self.access_token
        params = dict(params or {})
        if token and not es_url_completa:
            # Una URL completa (ver get_todas_las_paginas) ya viene con
            # su propio access_token embebido por Meta -- agregarlo de
            # nuevo duplicaria el parametro en la query string.
            params["access_token"] = token

        url = ruta if es_url_completa else f"{self.base_url}/{ruta.lstrip('/')}"
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
                uso_meta=_extraer_uso_meta(resp),
            )
        return cuerpo

    def get(self, ruta, params=None, access_token=None):
        return self._solicitar("GET", ruta, params=params, access_token=access_token)

    def post(self, ruta, data=None, access_token=None):
        return self._solicitar("POST", ruta, data=data, access_token=access_token)

    def get_todas_las_paginas(self, ruta, params=None, limite_paginas=20):
        """Sigue `paging.next` (paginacion por cursor de la Graph API,
        https://developers.facebook.com/docs/graph-api/results) hasta
        agotar las paginas o `limite_paginas` -- lo que ocurra primero.
        El limite existe para nunca quedar en un bucle sin fin si Meta
        devolviera un `next` que apunta a si mismo.
        """
        resultados = []
        respuesta = self.get(ruta, params=params)
        resultados.extend(respuesta.get("data", []))

        siguiente = respuesta.get("paging", {}).get("next")
        paginas = 1
        while siguiente and paginas < limite_paginas:
            respuesta = self.get(siguiente)
            resultados.extend(respuesta.get("data", []))
            siguiente = respuesta.get("paging", {}).get("next")
            paginas += 1

        return resultados
