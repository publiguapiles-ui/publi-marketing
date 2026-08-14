"""Servicio interno de conexiones con Meta (Paso 1 de Datos de Meta).

Esta es la UNICA puerta de entrada que el resto de Publi Marketing
(rutas de app/modules/datos_meta, y en el futuro Campañas/Analítica/
Informes dentro del mismo modulo) debe usar para saber "¿esta empresa
tiene Meta conectado?" y para obtener un MetaClient ya autenticado.
Nadie fuera de este archivo debe leer `MetaConexion.access_token_cifrado`
directamente ni llamar a app.core.crypto por su cuenta para esto.

Ninguna funcion aqui valida permisos de usuario en si (eso es
responsabilidad de las rutas, que deben llamar con una empresa_id ya
validada via app.core.empresas.obtener_empresa_activa) -- mismo patron
que app/services/presets.py y el resto de Photo Studio.
"""

from datetime import datetime, timedelta, timezone


def obtener_conexion_activa(empresa_id):
    """La conexion vigente de esta empresa, o None. Nunca devuelve una
    conexion de otra empresa: el filtro por empresa_id es obligatorio
    y nunca opcional, es el aislamiento multi-tenant de este modulo."""
    from app.extensions import db
    from app.models import MetaConexion

    return (
        db.session.query(MetaConexion)
        .filter_by(empresa_id=empresa_id, estado="activa")
        .order_by(MetaConexion.creado_en.desc())
        .first()
    )


def obtener_conexion_mas_reciente(empresa_id):
    """La conexion mas reciente de esta empresa SIN IMPORTAR su estado
    (activa, error o revocada) -- a diferencia de
    obtener_conexion_activa(), esta funcion es para MOSTRAR en pantalla
    por que una conexion dejo de funcionar (token expirado, revocado,
    error de permisos...), nunca para obtener un MetaClient utilizable.
    Para eso siempre obtener_conexion_activa()/obtener_cliente_para_empresa()
    (Paso 6, punto 10: sin esto, una conexion vencida desaparecia de la
    pantalla de Conexiones y se mostraba como "nunca conectado", en vez
    de "tu conexion expiro, reconecta")."""
    from app.extensions import db
    from app.models import MetaConexion

    return (
        db.session.query(MetaConexion)
        .filter_by(empresa_id=empresa_id)
        .order_by(MetaConexion.creado_en.desc())
        .first()
    )


def obtener_conexion(empresa_id, conexion_id):
    """Como obtener_conexion_activa, pero por id -- para acciones sobre
    una conexion especifica (desconectar), siempre revalidando que
    pertenece a la empresa indicada."""
    from app.extensions import db
    from app.models import MetaConexion

    return db.session.query(MetaConexion).filter_by(id=conexion_id, empresa_id=empresa_id).first()


def listar_conexiones_empresa(empresa_id):
    """Historial completo (activas, revocadas, con error) de esta
    empresa -- nunca se borra una fila al desconectar, solo cambia de
    estado, para conservar el historial de qué se conecto y cuándo."""
    from app.extensions import db
    from app.models import MetaConexion

    return (
        db.session.query(MetaConexion)
        .filter_by(empresa_id=empresa_id)
        .order_by(MetaConexion.creado_en.desc())
        .all()
    )


def crear_conexion(empresa_id, usuario_id, meta_user_id, nombre_usuario_meta, access_token, expira_en_segundos=None, scopes=None):
    """Registra una nueva conexion activa para la empresa. Si ya
    existia una conexion activa, queda marcada "revocada" (superseded)
    -- nunca se borra, pero deja de ser ambiguo cual es "la" conexion
    vigente para obtener_conexion_activa().
    """
    from app.core.crypto import cifrar
    from app.extensions import db
    from app.models import MetaConexion

    anteriores = db.session.query(MetaConexion).filter_by(empresa_id=empresa_id, estado="activa").all()
    for anterior in anteriores:
        anterior.estado = "revocada"

    expira_en = None
    if expira_en_segundos:
        expira_en = datetime.now(timezone.utc) + timedelta(seconds=int(expira_en_segundos))

    conexion = MetaConexion(
        empresa_id=empresa_id,
        meta_user_id=str(meta_user_id),
        nombre_usuario_meta=nombre_usuario_meta,
        access_token_cifrado=cifrar(access_token),
        token_expira_en=expira_en,
        scopes_concedidos=",".join(scopes) if scopes else None,
        estado="activa",
        conectado_por=usuario_id,
    )
    db.session.add(conexion)
    db.session.commit()
    return conexion


def obtener_token_descifrado(conexion):
    """Descifra el token de una conexion YA obtenida (por
    obtener_conexion_activa/obtener_conexion, ambas ya validadas contra
    empresa_id). Devuelve None si el token no se puede descifrar (ver
    app/core/crypto.py::descifrar) -- el llamador debe tratar eso como
    "hay que reconectar", nunca reintentar con un valor vacio."""
    from app.core.crypto import descifrar

    if conexion is None:
        return None
    return descifrar(conexion.access_token_cifrado)


def obtener_cliente_para_empresa(empresa_id):
    """Atajo: MetaClient ya autenticado con el token de la conexion
    activa de esta empresa, o (None, motivo) si no hay conexion
    utilizable. Pensado para que services/meta/cuentas_service.py (y
    el futuro insights_service.py) nunca tengan que lidiar con
    conexiones/tokens/cifrado directamente.

    Paso 6, punto 10: la expiracion se detecta AQUI, de forma
    proactiva, comparando `token_expira_en` contra la hora actual --
    antes de esto, un token vencido solo se detectaba de forma
    reactiva cuando Meta respondia con un error 190 durante una
    sincronizacion real (desperdiciando esa llamada y tardando un ciclo
    completo en avisarle al usuario). El resultado final es el mismo
    (categoria "token_expirado", la conexion pasa a estado "error"),
    pero ahora se sabe sin necesidad de llamar a la Graph API.
    """
    from app.services.meta.client import MetaClient

    conexion = obtener_conexion_activa(empresa_id)
    if conexion is None:
        return None, "Esta empresa no tiene Meta conectado."

    # `token_expira_en` se guarda en una columna DateTime SIN timezone
    # (igual que el resto del modelo, ver meta_conexion.py) -- tanto
    # SQLite como Postgres devuelven un datetime NAIVE al leerla, que
    # representa UTC implicitamente. Comparar contra
    # datetime.now(timezone.utc) (aware) lanza TypeError, asi que se le
    # quita el tzinfo despues de obtenerlo (evita datetime.utcnow(),
    # deprecado) para que ambos lados sean naive-UTC consistentes.
    ahora_utc_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    if conexion.token_expira_en is not None and conexion.token_expira_en <= ahora_utc_naive:
        marcar_error(conexion, "El token de acceso expiró.", categoria="token_expirado")
        return None, "El token de la conexión con Meta expiró. Reconecta la cuenta."

    token = obtener_token_descifrado(conexion)
    if token is None:
        marcar_error(conexion, "El token guardado no se pudo descifrar. Es necesario reconectar.")
        return None, "El token de la conexión no es válido. Reconecta Meta."

    return MetaClient(access_token=token), None


# Categorias de error (ver app/services/meta/errores.py) que invalidan
# la conexion EN SI -- el token ya no sirve, hay que reconectar. Un
# error transitorio (limite de API, activo inexistente, error interno
# de Meta) no significa que el token este mal: la conexion sigue
# "activa" y el usuario puede simplemente reintentar la sincronizacion.
CATEGORIAS_QUE_INVALIDAN_CONEXION = ("token_expirado", "autenticacion")


def marcar_error(conexion, mensaje, categoria=None):
    """Registra `ultimo_error` siempre. Solo cambia `estado` a "error"
    (y por lo tanto deja de ser "la" conexion activa, ver
    obtener_conexion_activa) si la categoria del error indica que el
    TOKEN en si ya no sirve -- nunca por un error transitorio de una
    sola llamada."""
    from app.extensions import db

    conexion.ultimo_error = (mensaje or "")[:500]
    if categoria in CATEGORIAS_QUE_INVALIDAN_CONEXION:
        conexion.estado = "error"
    db.session.commit()
    return conexion


def registrar_sincronizacion_exitosa(conexion):
    """Bug real encontrado y corregido: un error TRANSITORIO (categoria
    'temporal'/'limite_api'/etc, ver CATEGORIAS_QUE_INVALIDAN_CONEXION)
    deja `ultimo_error` con el detalle real de Meta pero NUNCA cambia
    `estado` a "error" -- por diseno, el token sigue sirviendo. Antes,
    `ultimo_error` solo se limpiaba dentro del `if conexion.estado ==
    "error"`, asi que una conexion que jamas dejo de estar "activa"
    (el caso mas comun: fallos transitorios repetidos) se quedaba
    mostrando para siempre el ultimo error viejo, incluso despues de
    una sincronizacion real exitosa. `ultimo_error` ahora se limpia
    SIEMPRE que una sincronizacion termina bien, sin importar el estado
    de la conexion."""
    from app.extensions import db

    conexion.ultima_sincronizacion_en = datetime.now(timezone.utc)
    conexion.ultimo_error = None
    if conexion.estado == "error":
        conexion.estado = "activa"
    db.session.commit()
    return conexion


def desconectar(empresa_id, conexion_id):
    """Marca la conexion como revocada. Nunca borra las
    EntidadPublicitaria/Metrica ya sincronizadas (siguen siendo
    historial valido de lo que se leyo mientras la conexion estuvo
    activa) -- mismo criterio de soft-delete que el resto del proyecto.
    """
    from app.extensions import db

    conexion = obtener_conexion(empresa_id, conexion_id)
    if conexion is None:
        return False, "La conexión no existe o no pertenece a esta empresa."
    if conexion.estado != "activa":
        return False, "Esta conexión ya no está activa."

    conexion.estado = "revocada"
    db.session.commit()
    return True, None
