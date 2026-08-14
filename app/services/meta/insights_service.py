"""Sincronizacion de insights/metricas reales de Meta hacia el motor
universal de metricas del Paso 1 (Paso 2, punto 7; extendido en el
Paso 3 con mas campos de Insights para el motor de KPI).

Endpoint documentado: https://developers.facebook.com/docs/marketing-api/insights
`GET /{entity_id}/insights?fields=...&time_range={"since":...,"until":...}&time_increment=1`
devuelve una fila POR DIA (time_increment=1) para el nodo consultado
-- se consulta directamente sobre cada campana/conjunto/anuncio ya
sincronizado (campanas_service.py), nunca se inventa un nivel de
agregacion que Meta no soporte para ese nodo.

Campos pedidos, todos documentados como campos estandar de Insights:
  spend, impressions, reach, clicks, frequency -- escalares directos.
  actions / action_values -- arreglos [{action_type, value}], de ahi
    se extrae UNICAMENTE action_type="purchase" para "conversiones"/
    "valor_conversion" (ver nota en app/services/metricas.py sobre por
    que se limita a compras y no se inventa un mapeo de "resultado"
    generico por objetivo).
  video_play_actions / video_thruplay_watched_actions -- arreglos,
    se suman todos sus valores.
  inline_post_engagement -- escalar directo.
  purchase_roas -- arreglo [{action_type, value}], se toma el primer
    valor (Meta solo devuelve una entrada en la practica).

CTR/CPC/CPM/costo_por_resultado/tasa_conversion se siguen calculando
localmente (ver app/services/metricas.py), nunca se piden a Meta.

Si un campo no viene en la respuesta de Meta para una cuenta/campana
(ej. no tiene pixel de compras configurado), el valor extraido queda
en None y `registrar_metricas_nativas_y_calculadas` simplemente no
guarda esa fila -- nunca se inventa un cero.
"""

from datetime import datetime

CAMPOS_INSIGHTS = (
    "spend,impressions,reach,clicks,frequency,actions,action_values,"
    "video_play_actions,video_thruplay_watched_actions,inline_post_engagement,"
    "purchase_roas,date_start,date_stop"
)

NIVELES_CON_INSIGHTS = ["campana", "conjunto_anuncios", "anuncio"]


def _parsear_fecha(cadena):
    return datetime.strptime(cadena, "%Y-%m-%d").date()


def _sumar_valor_accion(lista_acciones, action_type):
    """Suma el `value` de las entradas de un arreglo actions/action_values
    cuyo action_type coincide -- None si el arreglo no trae ese tipo."""
    if not lista_acciones:
        return None
    total = None
    for item in lista_acciones:
        if item.get("action_type") == action_type:
            total = (total or 0.0) + float(item.get("value") or 0)
    return total


def _sumar_todos_los_valores(lista):
    """Suma el `value` de TODAS las entradas de un arreglo (usado para
    video_play_actions/video_thruplay_watched_actions, que pueden traer
    mas de una entrada por distintas fuentes de reproduccion) -- None
    si el arreglo no vino en la respuesta."""
    if not lista:
        return None
    return sum(float(item.get("value") or 0) for item in lista)


def _valor_roas(lista):
    """purchase_roas es un arreglo [{action_type, value}] -- Meta solo
    devuelve una entrada en la practica; se toma su valor tal cual,
    nunca se recalcula (Meta aplica sus propias ventanas de
    atribucion, que este sistema no reproduce)."""
    if not lista:
        return None
    try:
        return float(lista[0].get("value"))
    except (TypeError, ValueError):
        return None


def sincronizar_insights(empresa_id, fecha_inicio, fecha_fin, niveles=None, sincronizacion_id=None):
    """Trae insights diarios de Meta para cada entidad ya sincronizada
    (campana/conjunto_anuncios/anuncio) de esta empresa, dentro del
    rango [fecha_inicio, fecha_fin], y los guarda con el motor
    universal de metricas. Devuelve (resumen_dict_o_None, error_o_None).
    """
    from app.services.meta.client import MetaAPIError
    from app.services.meta.conexiones import marcar_error, obtener_cliente_para_empresa, obtener_conexion_activa
    from app.services.meta.cuentas_service import listar_entidades_empresa
    from app.services.meta.errores import clasificar_error_meta, detalle_tecnico, mensaje_para_usuario
    from app.services.metricas import reemplazar_metricas_del_dia, registrar_metricas_nativas_y_calculadas

    cliente, error = obtener_cliente_para_empresa(empresa_id)
    if cliente is None:
        return None, error

    conexion = obtener_conexion_activa(empresa_id)
    niveles = niveles or NIVELES_CON_INSIGHTS

    entidades = []
    for tipo in niveles:
        entidades.extend(listar_entidades_empresa(empresa_id, tipo=tipo))

    if not entidades:
        return None, "No hay campañas, conjuntos o anuncios sincronizados todavía. Sincroniza la estructura primero."

    rango = {"since": fecha_inicio.isoformat(), "until": fecha_fin.isoformat()}
    total_filas_metrica = 0
    entidades_con_datos = 0

    try:
        for entidad in entidades:
            filas = cliente.get_todas_las_paginas(
                f"{entidad.id_externo}/insights",
                params={"fields": CAMPOS_INSIGHTS, "time_range": _json_compacto(rango), "time_increment": 1},
            )
            if filas:
                entidades_con_datos += 1

            for fila in filas:
                fecha = _parsear_fecha(fila["date_start"])
                acciones = fila.get("actions") or []
                valores_acciones = fila.get("action_values") or []
                valores_nativos = {
                    "spend": fila.get("spend"),
                    "impressions": fila.get("impressions"),
                    "reach": fila.get("reach"),
                    "clicks": fila.get("clicks"),
                    "frequency": fila.get("frequency"),
                    "conversiones": _sumar_valor_accion(acciones, "purchase"),
                    "valor_conversion": _sumar_valor_accion(valores_acciones, "purchase"),
                    "video_plays": _sumar_todos_los_valores(fila.get("video_play_actions")),
                    "thruplays": _sumar_todos_los_valores(fila.get("video_thruplay_watched_actions")),
                    "engagement": fila.get("inline_post_engagement"),
                    "roas": _valor_roas(fila.get("purchase_roas")),
                }
                reemplazar_metricas_del_dia(empresa_id, entidad.id, fecha, fuente="meta")
                guardadas = registrar_metricas_nativas_y_calculadas(
                    empresa_id, entidad.id, entidad.tipo, valores_nativos, fecha,
                    fuente="meta", sincronizacion_id=sincronizacion_id,
                )
                total_filas_metrica += len(guardadas)

        from app.services.meta.conexiones import registrar_sincronizacion_exitosa

        registrar_sincronizacion_exitosa(conexion)

        return {
            "entidades_consultadas": len(entidades),
            "entidades_con_datos": entidades_con_datos,
            "filas_metrica_guardadas": total_filas_metrica,
        }, None

    except MetaAPIError as exc:
        from app.extensions import db

        db.session.rollback()
        categoria = clasificar_error_meta(exc)
        marcar_error(conexion, detalle_tecnico(exc), categoria=categoria)
        return None, mensaje_para_usuario(categoria, exc)


def _json_compacto(d):
    import json

    return json.dumps(d, separators=(",", ":"))
