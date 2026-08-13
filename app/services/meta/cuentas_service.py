"""Descubrimiento de cuentas publicitarias, paginas de Facebook y
cuentas de Instagram vinculadas a una conexion de Meta (Paso 1).

Los campos pedidos a la Graph API en este archivo (account_id, name,
currency, timezone_name, account_status para cuentas publicitarias;
id, name, category, instagram_business_account para paginas) son
campos documentados y estables de /me/adaccounts y /me/accounts --
ver https://developers.facebook.com/docs/marketing-api/reference/ad-account
y https://developers.facebook.com/docs/graph-api/reference/page/.
No se inventa ningun campo no documentado.
"""

from datetime import datetime, timezone


def _upsert_entidad(empresa_id, conexion_id, tipo, id_externo, nombre, estado, atributos, entidad_padre_id=None):
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

    entidad.nombre = nombre
    entidad.estado = estado
    entidad.atributos = atributos or {}
    entidad.entidad_padre_id = entidad_padre_id
    entidad.activo = True
    entidad.sincronizado_en = ahora
    db.session.flush()  # asigna entidad.id sin cerrar la transaccion (necesario para hijos con entidad_padre_id)
    return entidad


def descubrir_cuentas(empresa_id):
    """Consulta la Graph API con la conexion activa de esta empresa y
    guarda/actualiza cuentas publicitarias, paginas y cuentas de
    Instagram como EntidadPublicitaria. Devuelve
    (resumen_dict_o_None, error_o_None).
    """
    from app.extensions import db
    from app.services.meta.client import MetaAPIError
    from app.services.meta.conexiones import marcar_error, obtener_cliente_para_empresa, obtener_conexion_activa, registrar_sincronizacion_exitosa

    cliente, error = obtener_cliente_para_empresa(empresa_id)
    if cliente is None:
        return None, error

    conexion = obtener_conexion_activa(empresa_id)

    try:
        cuentas_publicitarias = cliente.get(
            "me/adaccounts",
            params={"fields": "account_id,name,currency,timezone_name,account_status"},
        ).get("data", [])

        for cuenta in cuentas_publicitarias:
            _upsert_entidad(
                empresa_id,
                conexion.id,
                "cuenta_publicitaria",
                f"act_{cuenta['account_id']}",
                cuenta.get("name"),
                str(cuenta.get("account_status")),
                {"moneda": cuenta.get("currency"), "zona_horaria": cuenta.get("timezone_name")},
            )

        paginas = cliente.get(
            "me/accounts",
            params={"fields": "id,name,category,instagram_business_account"},
        ).get("data", [])

        total_instagram = 0
        for pagina in paginas:
            entidad_pagina = _upsert_entidad(
                empresa_id,
                conexion.id,
                "pagina",
                pagina["id"],
                pagina.get("name"),
                None,
                {"categoria": pagina.get("category")},
            )

            cuenta_ig = pagina.get("instagram_business_account")
            if cuenta_ig and cuenta_ig.get("id"):
                _upsert_entidad(
                    empresa_id,
                    conexion.id,
                    "cuenta_instagram",
                    cuenta_ig["id"],
                    None,
                    None,
                    {},
                    entidad_padre_id=entidad_pagina.id,
                )
                total_instagram += 1

        db.session.commit()
        registrar_sincronizacion_exitosa(conexion)

        return {
            "cuentas_publicitarias": len(cuentas_publicitarias),
            "paginas": len(paginas),
            "cuentas_instagram": total_instagram,
        }, None

    except MetaAPIError as exc:
        db.session.rollback()
        marcar_error(conexion, str(exc))
        return None, str(exc)


def listar_entidades_empresa(empresa_id, tipo=None):
    """Entidades ya descubiertas y guardadas para esta empresa
    (lectura pura, sin llamar a Meta) -- lo que la pantalla de
    Conexiones muestra."""
    from app.extensions import db
    from app.models import EntidadPublicitaria

    consulta = db.session.query(EntidadPublicitaria).filter_by(empresa_id=empresa_id, activo=True)
    if tipo:
        consulta = consulta.filter_by(tipo=tipo)
    return consulta.order_by(EntidadPublicitaria.tipo, EntidadPublicitaria.nombre).all()
