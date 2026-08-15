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


def detalle_tecnico(excepcion):
    """Representacion COMPLETA de un MetaAPIError para diagnostico
    interno (lo que se guarda en MetaConexion.ultimo_error) -- incluye
    codigo/subcodigo/tipo documentados por Meta ademas del mensaje,
    nunca solo el mensaje generico. `str(excepcion)` por si solo pierde
    el codigo/subcodigo (son atributos aparte, ver MetaAPIError), que es
    justo lo que hace falta para diagnosticar un error real sin
    adivinar. Nunca incluye el token de acceso ni ningun secreto --
    MetaAPIError nunca los guarda como atributo."""
    if excepcion is None:
        return None
    partes = [str(excepcion)]
    etiquetas = []
    if getattr(excepcion, "codigo", None) is not None:
        etiquetas.append(f"code={excepcion.codigo}")
    if getattr(excepcion, "subcodigo", None) is not None:
        etiquetas.append(f"subcode={excepcion.subcodigo}")
    if getattr(excepcion, "tipo", None):
        etiquetas.append(f"type={excepcion.tipo}")
    if etiquetas:
        partes.append(f"({', '.join(etiquetas)})")
    return " ".join(partes)


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


def categoria_desde_mensaje(mensaje):
    """Recupera la categoria a partir de un mensaje YA formateado por
    mensaje_para_usuario() -- para cuando el llamador solo tiene el
    mensaje de vuelta (ej. sincronizacion.py, que recibe el error de
    sincronizar_insights/sincronizar_estructura como string, no como el
    MetaAPIError original). Compara contra el prefijo EXACTO de
    MENSAJES_CATEGORIA (una constante nuestra, no el texto libre de
    Meta), asi que nunca es una adivinanza: o el mensaje empieza con
    exactamente ese texto o no. None si no coincide con ninguna."""
    if not mensaje:
        return None
    for categoria, texto in MENSAJES_CATEGORIA.items():
        if mensaje.startswith(texto):
            return categoria
    return None


def mensaje_para_usuario(categoria, excepcion=None):
    """`excepcion` es opcional -- si es un MetaAPIError con `uso_meta`
    (ver client.py::_extraer_uso_meta), se le agrega al mensaje generico
    el porcentaje/tiempo de espera REAL que Meta reporto en la
    respuesta, en vez de dejar solo "intenta de nuevo en unos minutos"
    a ciegas. Nunca inventa un numero: si Meta no lo mando, no se
    muestra."""
    mensaje = MENSAJES_CATEGORIA.get(categoria, MENSAJES_CATEGORIA["interno"])
    if categoria == "limite_api" and excepcion is not None:
        detalle = _detalle_uso_meta(getattr(excepcion, "uso_meta", None))
        if detalle:
            mensaje = f"{mensaje} {detalle}"
        # Paso 16.1: los porcentajes de arriba (si vinieron) son SOLO lo
        # que Meta reporta en x-app-usage/x-ad-account-usage -- limites
        # de llamadas normales. El limite especifico de Insights
        # (Business Use Case) que produce el error "User request limit
        # reached" en cuentas con poca actividad es OTRO limite, que no
        # siempre viaja en esos mismos encabezados. Un 0% ahi NO
        # significa "no hay ningun limite activo" -- decirlo tal cual
        # evita que el usuario interprete el numero al reves.
        mensaje = (
            f"{mensaje} No se realizarán más consultas automáticas hasta que Meta libere el límite. "
            "Nota: los porcentajes de arriba son la cuota general de la API, no reflejan necesariamente "
            "el límite específico de Insights que produjo este error."
        )
    return mensaje


def _detalle_uso_meta(uso_meta):
    """Traduce el dict de _extraer_uso_meta a una frase corta y honesta
    sobre la cuota real. Prioriza la cuenta publicitaria (la que
    realmente usa insights_service.py) sobre el app/pagina, y el
    "estimated_time_to_regain_access" de business_use_case_usage cuando
    esta disponible (es el unico campo que Meta documenta con un tiempo
    de espera real, en minutos)."""
    if not uso_meta:
        return None

    partes = []

    cuenta = uso_meta.get("cuenta_publicitaria")
    if isinstance(cuenta, dict) and "acc_id_util_pct" in cuenta:
        partes.append(f"Cuenta publicitaria: {cuenta['acc_id_util_pct']}% de la cuota usada.")

    business = uso_meta.get("business_use_case")
    if isinstance(business, dict):
        for entradas in business.values():
            if not isinstance(entradas, list):
                continue
            for entrada in entradas:
                espera = entrada.get("estimated_time_to_regain_access")
                if espera is not None:
                    partes.append(f"Meta estima {espera} minutos para recuperar acceso.")
                    break
            if partes:
                break

    # Siempre se muestra el uso a nivel de app tambien (no solo cuando la
    # cuenta publicitaria no reporto nada) -- son cuotas INDEPENDIENTES en
    # Meta, y una cuenta publicitaria en 0% no significa que la app en su
    # conjunto (compartida entre todas las pruebas hechas con este mismo
    # META_APP_ID) no este topada. Ocultarla llevaria a pensar que no hay
    # ningun limite activo cuando en realidad si lo hay, solo que en otro
    # nivel.
    app = uso_meta.get("app")
    if isinstance(app, dict):
        maximo = max((v for v in app.values() if isinstance(v, (int, float))), default=None)
        if maximo is not None:
            partes.append(f"App: {maximo}% de la cuota usada.")

    return " ".join(partes) or None
