"""Sincronizacion de la estructura publicitaria (campanas, conjuntos de
anuncios, anuncios) de Meta -- Paso 2, punto 7.

Campos pedidos, todos documentados y estables de la Marketing API:
  Campaign:  https://developers.facebook.com/docs/marketing-api/reference/ad-campaign-group/
             id, name, objective, status, effective_status, start_time,
             stop_time, daily_budget, lifetime_budget, budget_remaining.
  AdSet:     https://developers.facebook.com/docs/marketing-api/reference/ad-campaign/
             id, name, campaign_id, status, effective_status,
             daily_budget, lifetime_budget, targeting, start_time,
             end_time, optimization_goal, billing_event.
  Ad:        https://developers.facebook.com/docs/marketing-api/reference/adgroup/
             id, name, adset_id, campaign_id, status, effective_status,
             creative{id,name,thumbnail_url,body,title,image_url}.

Solo se sincroniza la estructura de cuentas publicitarias ya
VINCULADAS explicitamente (EntidadPublicitaria activo=True, ver
cuentas_service.py::vincular_activos) -- nunca de cuentas descubiertas
pero no confirmadas por el usuario.
"""

CAMPOS_CAMPANA = "id,name,objective,status,effective_status,start_time,stop_time,daily_budget,lifetime_budget,budget_remaining,created_time,updated_time"
CAMPOS_CONJUNTO = "id,name,campaign_id,status,effective_status,daily_budget,lifetime_budget,targeting,start_time,end_time,optimization_goal,billing_event,created_time,updated_time"
CAMPOS_ANUNCIO = "id,name,adset_id,campaign_id,status,effective_status,creative{id,name,thumbnail_url,body,title,image_url},created_time,updated_time"


def _atributos_campana(c):
    return {
        "objetivo": c.get("objective"),
        "fecha_inicio": c.get("start_time"),
        "fecha_fin": c.get("stop_time"),
        "presupuesto_diario": c.get("daily_budget"),
        "presupuesto_total": c.get("lifetime_budget"),
        "presupuesto_restante": c.get("budget_remaining"),
        "actualizado_en_meta": c.get("updated_time"),
    }


def _atributos_conjunto(a):
    return {
        "presupuesto_diario": a.get("daily_budget"),
        "presupuesto_total": a.get("lifetime_budget"),
        "fecha_inicio": a.get("start_time"),
        "fecha_fin": a.get("end_time"),
        "optimizacion": a.get("optimization_goal"),
        "evento_facturacion": a.get("billing_event"),
        # Guardado tal cual lo entrega Meta (edades, generos, ubicaciones,
        # placements, audiencias personalizadas/lookalike si aplican) --
        # ver Paso 2, punto 14. Nunca se inventa ni se completa un campo
        # que Meta no haya devuelto.
        "targeting": a.get("targeting"),
        "actualizado_en_meta": a.get("updated_time"),
    }


def _atributos_anuncio(a):
    creativo = a.get("creative") or {}
    return {
        "creativo": {
            "id": creativo.get("id"),
            "nombre": creativo.get("name"),
            "miniatura_url": creativo.get("thumbnail_url"),
            "titulo": creativo.get("title"),
            "cuerpo": creativo.get("body"),
        },
        "actualizado_en_meta": a.get("updated_time"),
    }


def sincronizar_estructura(empresa_id):
    """Trae campanas -> conjuntos -> anuncios de cada cuenta
    publicitaria vinculada de esta empresa. Devuelve
    (resumen_dict_o_None, error_o_None). No sincroniza metricas (ver
    insights_service.py) -- solo la estructura y su historial de
    estados."""
    from app.services.meta.client import MetaAPIError
    from app.services.meta.conexiones import marcar_error, obtener_cliente_para_empresa, obtener_conexion_activa
    from app.services.meta.cuentas_service import _upsert_entidad, listar_entidades_empresa
    from app.services.meta.errores import clasificar_error_meta, mensaje_para_usuario

    cliente, error = obtener_cliente_para_empresa(empresa_id)
    if cliente is None:
        return None, error

    conexion = obtener_conexion_activa(empresa_id)
    cuentas = listar_entidades_empresa(empresa_id, tipo="cuenta_publicitaria")
    if not cuentas:
        return None, "No hay ninguna cuenta publicitaria vinculada. Ve a Conexiones y selecciona al menos una."

    totales = {"campanas": 0, "conjuntos_anuncios": 0, "anuncios": 0}

    try:
        for cuenta in cuentas:
            campanas = cliente.get_todas_las_paginas(f"{cuenta.id_externo}/campaigns", params={"fields": CAMPOS_CAMPANA})
            for campana_datos in campanas:
                entidad_campana = _upsert_entidad(
                    empresa_id, conexion.id, "campana", campana_datos["id"],
                    campana_datos.get("name"), campana_datos.get("effective_status") or campana_datos.get("status"),
                    _atributos_campana(campana_datos), entidad_padre_id=cuenta.id,
                )
                totales["campanas"] += 1

                conjuntos = cliente.get_todas_las_paginas(f"{campana_datos['id']}/adsets", params={"fields": CAMPOS_CONJUNTO})
                for conjunto_datos in conjuntos:
                    entidad_conjunto = _upsert_entidad(
                        empresa_id, conexion.id, "conjunto_anuncios", conjunto_datos["id"],
                        conjunto_datos.get("name"), conjunto_datos.get("effective_status") or conjunto_datos.get("status"),
                        _atributos_conjunto(conjunto_datos), entidad_padre_id=entidad_campana.id,
                    )
                    totales["conjuntos_anuncios"] += 1

                    anuncios = cliente.get_todas_las_paginas(f"{conjunto_datos['id']}/ads", params={"fields": CAMPOS_ANUNCIO})
                    for anuncio_datos in anuncios:
                        _upsert_entidad(
                            empresa_id, conexion.id, "anuncio", anuncio_datos["id"],
                            anuncio_datos.get("name"), anuncio_datos.get("effective_status") or anuncio_datos.get("status"),
                            _atributos_anuncio(anuncio_datos), entidad_padre_id=entidad_conjunto.id,
                        )
                        totales["anuncios"] += 1

        from app.extensions import db

        db.session.commit()
        return totales, None

    except MetaAPIError as exc:
        from app.extensions import db

        db.session.rollback()
        categoria = clasificar_error_meta(exc)
        marcar_error(conexion, str(exc), categoria=categoria)
        return None, mensaje_para_usuario(categoria)
