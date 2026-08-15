"""Sincronizacion de insights/metricas reales de Meta hacia el motor
universal de metricas del Paso 1 (Paso 2, punto 7; extendido en el
Paso 3 con mas campos de Insights para el motor de KPI).

Endpoint documentado: https://developers.facebook.com/docs/marketing-api/insights
`GET /{ad_account_id}/insights?level={campaign|adset|ad}&fields=...&
time_range={"since":...,"until":...}&time_increment=1` devuelve una
fila POR DIA (time_increment=1) Y POR ENTIDAD de ese nivel bajo la
cuenta -- UNA sola llamada (paginada) trae todas las campanas (o todos
los conjuntos, o todos los anuncios) de la cuenta a la vez, en vez de
una llamada separada por cada campana/conjunto/anuncio individual.

Paso 16.1 (correccion): la version anterior consultaba
`{entidad.id_externo}/insights` UNA VEZ POR CADA entidad ya
sincronizada -- con varias campanas/conjuntos/anuncios, un solo
"Sincronizar ahora" disparaba decenas de llamadas seguidas contra la
misma cuenta publicitaria. Meta aplica a Insights un limite de cuota
propio (Business Use Case), mas estricto en cuentas con poca actividad,
que NO aparece en los encabezados x-app-usage/x-ad-account-usage que
ya se le mostraban al usuario en Conexiones -- de ahi que el error
"User request limit reached" (code=17) apareciera con esos encabezados
en 0%. Agrupar por nivel (3 llamadas como maximo por cuenta vinculada,
en vez de una por entidad) es el patron que la propia documentacion de
Meta recomienda para reducir presion sobre ese limite; las filas
devueltas se re-asocian a la entidad local ya sincronizada usando
campaign_id/adset_id/ad_id (ver NIVEL_A_META), nunca se inventa una
entidad que no exista ya en `EntidadPublicitaria`.

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

# tipo local -> (level de Meta, campo que identifica la entidad en cada
# fila devuelta). Usado para pedir insights agrupados por nivel bajo la
# cuenta publicitaria y re-asociar cada fila a la EntidadPublicitaria ya
# sincronizada (por id_externo), en vez de consultar entidad por entidad.
NIVEL_A_META = {
    "campana": ("campaign", "campaign_id"),
    "conjunto_anuncios": ("adset", "adset_id"),
    "anuncio": ("ad", "ad_id"),
}


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

    UNA llamada a Meta por (cuenta publicitaria vinculada x nivel con
    al menos una entidad rastreada) -- nunca una por entidad individual
    (ver nota del modulo). Las filas se re-asocian a la
    EntidadPublicitaria local por id_externo; una fila cuyo
    campaign_id/adset_id/ad_id no corresponde a ninguna entidad ya
    sincronizada se ignora (Meta puede incluir entidades que el usuario
    no selecciono al vincular la cuenta)."""
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

    cuentas = listar_entidades_empresa(empresa_id, tipo="cuenta_publicitaria")
    if not cuentas:
        return None, "No hay cuentas publicitarias vinculadas todavía."

    entidades_por_tipo = {tipo: listar_entidades_empresa(empresa_id, tipo=tipo) for tipo in niveles}
    total_entidades = sum(len(lista) for lista in entidades_por_tipo.values())
    if total_entidades == 0:
        return None, "No hay campañas, conjuntos o anuncios sincronizados todavía. Sincroniza la estructura primero."

    entidad_por_id_externo = {
        (tipo, entidad.id_externo): entidad
        for tipo, lista in entidades_por_tipo.items()
        for entidad in lista
    }

    rango = {"since": fecha_inicio.isoformat(), "until": fecha_fin.isoformat()}
    total_filas_metrica = 0
    ids_entidad_con_datos = set()
    filas_no_reconocidas = 0
    # Documentacion del volumen real de llamadas (punto 2 del Paso
    # 16.1): como maximo, len(cuentas) * (niveles con al menos una
    # entidad rastreada) -- 3 niveles como mucho, sin importar cuantas
    # campanas/conjuntos/anuncios existan. get_todas_las_paginas cuenta
    # como una sola "consulta" aqui aunque siga paginas adicionales
    # (paging.next), porque esa paginacion es inherente al tamano de
    # los resultados, no al numero de entidades -- lo que este numero
    # documenta es la reduccion real lograda por el punto 1
    # (agrupar por nivel), no cada peticion HTTP individual.
    llamadas_realizadas = 0

    try:
        for cuenta in cuentas:
            for tipo in niveles:
                if not entidades_por_tipo[tipo]:
                    continue  # nada rastreado en este nivel -- evita una llamada que no serviria para nada
                nivel_meta, campo_id = NIVEL_A_META[tipo]
                filas = cliente.get_todas_las_paginas(
                    f"{cuenta.id_externo}/insights",
                    params={
                        "level": nivel_meta,
                        "fields": f"{CAMPOS_INSIGHTS},{campo_id}",
                        "time_range": _json_compacto(rango),
                        "time_increment": 1,
                    },
                )
                llamadas_realizadas += 1

                for fila in filas:
                    entidad = entidad_por_id_externo.get((tipo, fila.get(campo_id)))
                    if entidad is None:
                        # Meta devolvio una entidad que no esta en
                        # EntidadPublicitaria (ej. una campana creada en
                        # Meta despues de la ultima sincronizacion de
                        # estructura, o no seleccionada al vincular la
                        # cuenta) -- se documenta en vez de descartarse
                        # en silencio (punto 11: reconciliacion).
                        filas_no_reconocidas += 1
                        continue

                    ids_entidad_con_datos.add(entidad.id)
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
            "entidades_consultadas": total_entidades,
            "entidades_con_datos": len(ids_entidad_con_datos),
            "filas_metrica_guardadas": total_filas_metrica,
            "llamadas_realizadas": llamadas_realizadas,
            "filas_no_reconocidas": filas_no_reconocidas,
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
