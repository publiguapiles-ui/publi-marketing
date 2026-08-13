"""Clasificacion de errores de la Graph API de Meta (Paso 2, punto 13).

Los codigos usados aqui estan documentados en
https://developers.facebook.com/docs/graph-api/guides/error-handling
y en la referencia de codigos de error de la Marketing API. NO es una
lista exhaustiva -- Meta tiene cientos de codigos y subcodigos; esto
cubre los casos mas comunes y accionables (los que el punto 13 pide
diferenciar explicitamente). Un codigo no reconocido cae en "interno"
en vez de adivinar, para no mostrarle al usuario una categoria
incorrecta con falsa confianza.
"""

CATEGORIAS_ERROR_META = [
    "autenticacion",
    "permisos",
    "token_expirado",
    "limite_api",
    "activo_inexistente",
    "temporal",
    "interno",
]

MENSAJES_CATEGORIA = {
    "autenticacion": "Hubo un problema autenticando con Meta. Intenta reconectar la cuenta.",
    "permisos": "Esta conexión no tiene los permisos necesarios para esta operación.",
    "token_expirado": "La conexión con Meta expiró. Es necesario reconectar.",
    "limite_api": "Se alcanzó el límite de solicitudes de Meta. Intenta de nuevo en unos minutos.",
    "activo_inexistente": "El recurso solicitado ya no existe o no está disponible en Meta.",
    "temporal": "Meta tuvo un problema temporal. Intenta de nuevo.",
    "interno": "Ocurrió un error al procesar la solicitud.",
}

# codigo -> categoria (codigos documentados de la Graph API)
_CODIGOS_CONOCIDOS = {
    190: "token_expirado",   # Invalid OAuth 2.0 Access Token
    102: "autenticacion",    # Session key invalid or no longer valid
    10: "permisos",          # Permission denied
    200: "permisos",         # Permissions error (rango 200-299 tambien es de permisos)
    4: "limite_api",         # Application request limit reached
    17: "limite_api",        # User request limit reached
    32: "limite_api",        # Page request limit reached
    613: "limite_api",       # Calls to this api have exceeded the rate limit
    100: "activo_inexistente",  # Invalid parameter / objeto no existe o ID invalido
    803: "activo_inexistente",  # El activo solicitado no existe
    2: "temporal",           # Service temporarily unavailable
    1: "temporal",           # Unknown error -- Meta recomienda reintentar
}


def clasificar_error_meta(excepcion):
    """Recibe un MetaAPIError (ver app/services/meta/client.py) y
    devuelve una de CATEGORIAS_ERROR_META. Nunca lanza -- si no puede
    clasificar con confianza, devuelve "interno"."""
    codigo = getattr(excepcion, "codigo", None)
    tipo = getattr(excepcion, "tipo", None)
    mensaje = str(excepcion) if excepcion is not None else ""

    if codigo in _CODIGOS_CONOCIDOS:
        return _CODIGOS_CONOCIDOS[codigo]

    if codigo is not None and 200 <= codigo < 300:
        return "permisos"
    if codigo is not None and 500 <= codigo < 600:
        return "temporal"

    if tipo == "OAuthException":
        return "autenticacion"

    if codigo is None and "No se pudo contactar a Meta" in mensaje:
        # Error de red/timeout, ver MetaClient._solicitar -- nunca un
        # error de negocio de Meta en si.
        return "temporal"

    return "interno"


def mensaje_para_usuario(categoria):
    return MENSAJES_CATEGORIA.get(categoria, MENSAJES_CATEGORIA["interno"])
