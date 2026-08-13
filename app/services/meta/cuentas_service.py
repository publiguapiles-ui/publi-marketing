"""Descubrimiento y vinculacion de cuentas publicitarias, paginas de
Facebook y cuentas de Instagram (Paso 1 + Paso 2).

Paso 2, punto 4: descubrir NUNCA persiste nada por si solo -- devuelve
la lista de lo que existe en Meta para que el usuario elija. Solo
`vincular_activos` escribe en la base de datos, y solo para lo que el
usuario selecciono explicitamente. Esto reemplaza el
`descubrir_cuentas()` del Paso 1, que vinculaba automaticamente TODO
lo descubierto -- exactamente lo que este paso pide corregir.

Los campos pedidos a la Graph API (account_id, name, currency,
timezone_name, account_status para cuentas publicitarias; id, name,
category, instagram_business_account para paginas) son campos
documentados y estables de /me/adaccounts y /me/accounts -- ver
https://developers.facebook.com/docs/marketing-api/reference/ad-account
y https://developers.facebook.com/docs/graph-api/reference/page/.
"""

from datetime import datetime, timezone


def listar_activos_disponibles(empresa_id):
    """Consulta la Graph API EN VIVO con la conexion activa de esta
    empresa. NO escribe nada en la base de datos. Devuelve
    (dict_o_None, error_o_None) con listas planas listas para
    renderizar como checkboxes:

    {
      "cuentas_publicitarias": [{"id_externo": "act_123", "nombre": ..., "atributos": {...}}, ...],
      "paginas": [{"id_externo": "456", "nombre": ..., "atributos": {...},
                   "instagram": {"id_externo": "789"} | None}, ...],
    }
    """
    from app.services.meta.client import MetaAPIError
    from app.services.meta.conexiones import marcar_error, obtener_cliente_para_empresa, obtener_conexion_activa
    from app.services.meta.errores import clasificar_error_meta

    cliente, error = obtener_cliente_para_empresa(empresa_id)
    if cliente is None:
        return None, error

    conexion = obtener_conexion_activa(empresa_id)

    try:
        cuentas = cliente.get(
            "me/adaccounts",
            params={"fields": "account_id,name,currency,timezone_name,account_status"},
        ).get("data", [])

        paginas_crudas = cliente.get(
            "me/accounts",
            params={"fields": "id,name,category,instagram_business_account"},
        ).get("data", [])

        cuentas_publicitarias = [
            {
                "id_externo": f"act_{c['account_id']}",
                "nombre": c.get("name"),
                "estado": str(c.get("account_status")),
                "atributos": {"moneda": c.get("currency"), "zona_horaria": c.get("timezone_name")},
            }
            for c in cuentas
        ]

        paginas = []
        for p in paginas_crudas:
            cuenta_ig = p.get("instagram_business_account")
            paginas.append(
                {
                    "id_externo": p["id"],
                    "nombre": p.get("name"),
                    "atributos": {"categoria": p.get("category")},
                    "instagram": {"id_externo": cuenta_ig["id"]} if cuenta_ig and cuenta_ig.get("id") else None,
                }
            )

        return {"cuentas_publicitarias": cuentas_publicitarias, "paginas": paginas}, None

    except MetaAPIError as exc:
        categoria = clasificar_error_meta(exc)
        marcar_error(conexion, str(exc), categoria=categoria)
        from app.services.meta.errores import mensaje_para_usuario

        return None, mensaje_para_usuario(categoria)


def _upsert_entidad(empresa_id, conexion_id, tipo, id_externo, nombre, estado, atributos, entidad_padre_id=None, activo=True):
    from app.extensions import db
    from app.models import EntidadPublicitaria

    entidad = (
        db.session.query(EntidadPublicitaria)
        .filter_by(fuente="meta", conexion_id=conexion_id, id_externo=str(id_externo))
        .first()
    )
    ahora = datetime.now(timezone.utc)
    if entidad is None:
        entidad = EntidadPublicitaria(
            empresa_id=empresa_id,
            conexion_id=conexion_id,
            fuente="meta",
            tipo=tipo,
            id_externo=str(id_externo),
        )
        db.session.add(entidad)

    if nombre is not None:
        entidad.nombre = nombre
    if estado is not None:
        entidad.estado = estado
    if atributos is not None:
        entidad.atributos = {**(entidad.atributos or {}), **atributos}
    if entidad_padre_id is not None:
        entidad.entidad_padre_id = entidad_padre_id
    entidad.activo = activo
    entidad.sincronizado_en = ahora
    db.session.flush()  # asigna entidad.id sin cerrar la transaccion (necesario para hijos con entidad_padre_id)
    return entidad


def vincular_activos(empresa_id, seleccion):
    """Persiste SOLO los activos que el usuario selecciono
    explicitamente en la pantalla de seleccion (Paso 2, punto 4).
    `seleccion` es una lista de dicts:
      {"tipo": "cuenta_publicitaria"|"pagina"|"cuenta_instagram",
       "id_externo": str, "nombre": str|None, "atributos": dict,
       "id_externo_padre": str|None}  # solo para cuenta_instagram (su pagina)

    Nunca vincula lo que no viene en `seleccion` -- si el usuario
    desmarca una cuenta que estaba vinculada antes, esta funcion la
    desactiva (activo=False), sin borrar su historial de entidades
    hijas/metricas ya sincronizadas.
    """
    from app.extensions import db
    from app.models import EntidadPublicitaria
    from app.services.meta.conexiones import obtener_conexion_activa

    conexion = obtener_conexion_activa(empresa_id)
    if conexion is None:
        return False, "No hay una conexión activa con Meta."

    ids_seleccionados_por_tipo = {}
    entidades_padre_por_id_externo = {}

    for item in seleccion:
        if item["tipo"] == "cuenta_instagram":
            continue  # se procesan despues, necesitan el id interno de su pagina ya vinculada
        entidad = _upsert_entidad(
            empresa_id, conexion.id, item["tipo"], item["id_externo"],
            item.get("nombre"), item.get("estado"), item.get("atributos") or {},
            activo=True,
        )
        entidades_padre_por_id_externo[item["id_externo"]] = entidad.id
        ids_seleccionados_por_tipo.setdefault(item["tipo"], set()).add(item["id_externo"])

    for item in seleccion:
        if item["tipo"] != "cuenta_instagram":
            continue
        padre_id = entidades_padre_por_id_externo.get(item.get("id_externo_padre"))
        entidad = _upsert_entidad(
            empresa_id, conexion.id, "cuenta_instagram", item["id_externo"],
            item.get("nombre"), item.get("estado"), item.get("atributos") or {},
            entidad_padre_id=padre_id, activo=True,
        )
        ids_seleccionados_por_tipo.setdefault("cuenta_instagram", set()).add(item["id_externo"])

    # Desactivar lo que estaba vinculado y ya no viene seleccionado
    # (el usuario lo desmarco) -- nunca se borra la fila.
    for tipo in ("cuenta_publicitaria", "pagina", "cuenta_instagram"):
        seleccionados = ids_seleccionados_por_tipo.get(tipo, set())
        vinculadas_actuales = (
            db.session.query(EntidadPublicitaria)
            .filter_by(empresa_id=empresa_id, conexion_id=conexion.id, tipo=tipo, activo=True)
            .all()
        )
        for entidad in vinculadas_actuales:
            if entidad.id_externo not in seleccionados:
                entidad.activo = False

    db.session.commit()
    return True, None


def listar_campanas_de_cuenta(empresa_id, cuenta_id):
    """Campañas hijas de una cuenta publicitaria ya vinculada -- lectura
    pura, sin llamar a Meta (Paso 4: filtro y tabla del dashboard).
    SIEMPRE filtrado por empresa_id, incluso si `cuenta_id` viniera de
    otra empresa (aislamiento multi-tenant)."""
    from app.extensions import db
    from app.models import EntidadPublicitaria

    return (
        db.session.query(EntidadPublicitaria)
        .filter_by(empresa_id=empresa_id, entidad_padre_id=cuenta_id, tipo="campana", activo=True)
        .order_by(EntidadPublicitaria.nombre)
        .all()
    )


def listar_conjuntos_de_campana(empresa_id, campana_id):
    """Conjuntos de anuncios hijos de una campaña -- lectura pura
    (Paso 5: analisis de campaña). SIEMPRE filtrado por empresa_id."""
    from app.extensions import db
    from app.models import EntidadPublicitaria

    return (
        db.session.query(EntidadPublicitaria)
        .filter_by(empresa_id=empresa_id, entidad_padre_id=campana_id, tipo="conjunto_anuncios", activo=True)
        .order_by(EntidadPublicitaria.nombre)
        .all()
    )


def listar_anuncios_de_conjuntos(empresa_id, conjunto_ids):
    """Anuncios hijos de cualquiera de los conjuntos dados -- lectura
    pura (Paso 5: analisis de campaña/conjunto). SIEMPRE filtrado por
    empresa_id, incluso si algun conjunto_id no perteneciera a esta
    empresa (aislamiento multi-tenant)."""
    from app.extensions import db
    from app.models import EntidadPublicitaria

    if not conjunto_ids:
        return []
    return (
        db.session.query(EntidadPublicitaria)
        .filter(
            EntidadPublicitaria.empresa_id == empresa_id,
            EntidadPublicitaria.entidad_padre_id.in_(conjunto_ids),
            EntidadPublicitaria.tipo == "anuncio",
            EntidadPublicitaria.activo == True,  # noqa: E712
        )
        .order_by(EntidadPublicitaria.nombre)
        .all()
    )


def listar_conjuntos_de_empresa(empresa_id, cuenta_id=None):
    """Todos los conjuntos de anuncios de la empresa (Paso 5: analisis
    de audiencias) -- opcionalmente acotado a una sola cuenta
    publicitaria. Sin `cuenta_id`, recorre TODAS las cuentas vinculadas
    de la empresa."""
    if cuenta_id is not None:
        conjuntos = []
        for campana in listar_campanas_de_cuenta(empresa_id, cuenta_id):
            conjuntos.extend(listar_conjuntos_de_campana(empresa_id, campana.id))
        return conjuntos

    from app.extensions import db
    from app.models import EntidadPublicitaria

    return (
        db.session.query(EntidadPublicitaria)
        .filter_by(empresa_id=empresa_id, tipo="conjunto_anuncios", activo=True)
        .order_by(EntidadPublicitaria.nombre)
        .all()
    )


def listar_entidades_empresa(empresa_id, tipo=None, solo_activas=True):
    """Entidades ya vinculadas y guardadas para esta empresa (lectura
    pura, sin llamar a Meta) -- lo que la pantalla de Conexiones
    muestra."""
    from app.extensions import db
    from app.models import EntidadPublicitaria

    consulta = db.session.query(EntidadPublicitaria).filter_by(empresa_id=empresa_id)
    if solo_activas:
        consulta = consulta.filter_by(activo=True)
    if tipo:
        consulta = consulta.filter_by(tipo=tipo)
    return consulta.order_by(EntidadPublicitaria.tipo, EntidadPublicitaria.nombre).all()
