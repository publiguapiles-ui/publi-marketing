"""Motor de KPI y analisis de Datos de Meta (Paso 3).

Capa de LECTURA sobre el motor universal de metricas del Paso 1
(Metrica/CatalogoMetrica) y la sincronizacion real del Paso 2 -- este
archivo NUNCA llama a la Graph API ni sincroniza nada, solo agrega y
compara lo que ya esta guardado en la base de datos. Por eso vive
fuera de app/services/meta/ en cuanto a responsabilidad (aunque el
archivo esta junto a los demas conectores de Meta por conveniencia):
la logica de agregacion en si no sabe nada de OAuth, tokens ni
llamadas HTTP.

Principio central (igual que el resto de Datos de Meta): nunca se
inventa un valor. Si Meta no devolvio una metrica para una entidad o
periodo, esa clave del resultado queda en None -- la interfaz debe
mostrar "No disponible", nunca 0 ni un valor inferido.

Agregacion correcta: las metricas ADITIVAS (spend, impressions, reach,
clicks, conversiones, valor_conversion, video_plays, thruplays,
engagement) se SUMAN entre filas/entidades. Las metricas DERIVADAS
(ctr, cpc, cpm, frequency, costo_por_resultado, tasa_conversion, roas)
NUNCA se promedian entre filas -- se recalculan desde los totales ya
sumados (ej. el CTR de una campana en 30 dias es clicks_total /
impressions_total * 100, no el promedio de 30 CTR diarios). Es el
mismo principio que evita el "promedio de promedios" en reportes de
marketing, y la misma formula que usa "roas" (valor_conversion_total /
spend_total, el ROAS "blended" correcto al agregar varias filas).

Nota sobre "reach": sumar el alcance de varios dias o de varias
entidades es una aproximacion (una misma persona puede repetirse entre
dias/entidades distintos) -- Meta no expone una forma de deduplicar
alcance agregado via la API de Insights estandar, asi que esta
limitacion es inherente a cualquier reporte que agregue reach, no solo
a este motor.
"""

from app.services.periodos import periodo_anterior_equivalente

# Metricas que se suman entre filas/entidades (conteos y montos reales
# que Meta reporto, nunca ratios).
METRICAS_ADITIVAS = [
    "spend", "impressions", "reach", "clicks",
    "conversiones", "valor_conversion", "video_plays", "thruplays", "engagement",
]

# clave -> decimales para redondear al mostrar.
_PRECISION = {
    "spend": 2, "impressions": 0, "reach": 0, "clicks": 0, "frequency": 2,
    "ctr": 2, "cpc": 2, "cpm": 2, "conversiones": 0, "valor_conversion": 2,
    "roas": 2, "costo_por_resultado": 2, "tasa_conversion": 2,
    "video_plays": 0, "thruplays": 0, "engagement": 0,
}

# clave -> funcion(dict_de_totales_aditivos) -> valor_o_None. Cada
# formula es exactamente la misma que usa app/services/metricas.py
# para una sola fila -- aqui se aplica sobre los TOTALES ya sumados,
# nunca sobre un promedio de valores ya calculados.
_DERIVADAS = {
    "ctr": lambda t: (t["clicks"] / t["impressions"] * 100) if t.get("impressions") else None,
    "cpc": lambda t: (t["spend"] / t["clicks"]) if t.get("clicks") else None,
    "cpm": lambda t: (t["spend"] / t["impressions"] * 1000) if t.get("impressions") else None,
    "frequency": lambda t: (t["impressions"] / t["reach"]) if t.get("reach") else None,
    "costo_por_resultado": lambda t: (t["spend"] / t["conversiones"]) if t.get("conversiones") else None,
    "tasa_conversion": lambda t: (t["conversiones"] / t["clicks"] * 100) if t.get("clicks") and t.get("conversiones") is not None else None,
    "roas": lambda t: (t["valor_conversion"] / t["spend"]) if t.get("spend") and t.get("valor_conversion") is not None else None,
}

# Para estas metricas, un valor MENOR es mejor rendimiento (costos).
# Todas las demas: mayor es mejor. Usado por comparar_entidades().
METRICAS_MENOR_ES_MEJOR = {"cpc", "cpm", "costo_por_resultado"}

CLAVES_KPI = [
    "spend", "impressions", "reach", "frequency", "clicks", "ctr", "cpc", "cpm",
    "resultados", "conversiones", "costo_por_resultado", "tasa_conversion", "valor_conversion", "roas",
    "video_plays", "thruplays", "engagement",
]

ETIQUETAS_KPI = {
    "spend": "Importe gastado",
    "impressions": "Impresiones",
    "reach": "Alcance",
    "frequency": "Frecuencia",
    "clicks": "Clics",
    "ctr": "CTR",
    "cpc": "CPC",
    "cpm": "CPM",
    "resultados": "Resultados",
    "conversiones": "Conversiones",
    "costo_por_resultado": "Costo por resultado",
    "tasa_conversion": "Tasa de conversión",
    "valor_conversion": "Valor de conversión",
    "roas": "ROAS",
    "video_plays": "Reproducciones de video",
    "thruplays": "ThruPlays",
    "engagement": "Interacciones (Engagement)",
}


def _redondear(valor, decimales):
    return None if valor is None else round(valor, decimales)


def _sumar_por_metrica(filas):
    """dict metrica_nombre -> suma de valor, solo para las metricas
    que aparecieron en al menos una fila (las que nunca aparecieron
    quedan fuera del dict, no en 0)."""
    totales = {}
    for fila in filas:
        if fila.valor is None:
            continue
        totales[fila.metrica_nombre] = totales.get(fila.metrica_nombre, 0.0) + fila.valor
    return totales


def resolver_entidades_para_kpi(empresa_id, entidad_id):
    """Dado un entidad_id de CUALQUIER tipo ya vinculado a esta
    empresa, devuelve (entidad_ids_o_None, error_o_None) -- la lista de
    entidad_ids sobre los que se debe agregar el KPI:

      - campana/conjunto_anuncios/anuncio: la entidad misma (Meta ya
        entrega insights para ese nodo exacto, ver
        insights_service.NIVELES_CON_INSIGHTS).
      - cuenta_publicitaria: todas sus campañas hijas -- la cuenta en
        si no tiene insights propios sincronizados, se agrega desde
        el nivel de campana (evita sumar dos veces si tambien se
        agregara conjunto/anuncio).
      - pagina/cuenta_instagram/creativo: no tienen insights en este
        motor todavia -- lista vacia (el KPI queda en None para todo).
    """
    from app.extensions import db
    from app.models import EntidadPublicitaria

    entidad = db.session.query(EntidadPublicitaria).filter_by(id=entidad_id, empresa_id=empresa_id).first()
    if entidad is None:
        return None, "La entidad seleccionada no pertenece a esta empresa."

    if entidad.tipo in ("campana", "conjunto_anuncios", "anuncio"):
        return [entidad.id], None

    if entidad.tipo == "cuenta_publicitaria":
        hijas = (
            db.session.query(EntidadPublicitaria)
            .filter_by(empresa_id=empresa_id, entidad_padre_id=entidad.id, tipo="campana")
            .all()
        )
        return [h.id for h in hijas], None

    return [], None


def _calcular_desde_filas(filas):
    """Punto UNICO donde se pasa de una lista de filas Metrica a un
    dict de KPI -- calcular_kpis() y serie_diaria() (Paso 4) llaman
    exclusivamente a esta funcion para que la aritmetica de agregacion
    (aditivas sumadas, derivadas recalculadas desde los totales) nunca
    se repita ni diverja entre "KPI del periodo completo" y "KPI de un
    solo dia dentro de una serie"."""
    totales = _sumar_por_metrica(filas)

    resultado = {}
    for clave in METRICAS_ADITIVAS:
        resultado[clave] = _redondear(totales.get(clave), _PRECISION.get(clave, 2)) if clave in totales else None

    for clave, formula in _DERIVADAS.items():
        try:
            valor = formula(totales)
        except (KeyError, ZeroDivisionError, TypeError):
            valor = None
        resultado[clave] = _redondear(valor, _PRECISION.get(clave, 2))

    resultado["resultados"] = resultado["conversiones"]
    return resultado


def _filas_del_alcance(empresa_id, entidad_ids, fecha_inicio, fecha_fin):
    """Filas de Metrica para el alcance (`entidad_ids`) y rango pedido
    -- unico punto que decide COMO se traduce `entidad_ids` en una
    consulta (None = nivel "campana" de toda la empresa, ver nota de
    doble conteo en calcular_kpis). Usado por calcular_kpis() y
    serie_diaria() para que ambos agreguen exactamente el mismo
    conjunto de datos."""
    from app.services.metricas import consultar_metricas

    if entidad_ids is None:
        return consultar_metricas(empresa_id, entidad_tipo="campana", fecha_desde=fecha_inicio, fecha_hasta=fecha_fin)
    if not entidad_ids:
        return []
    filas = []
    for entidad_id in entidad_ids:
        filas.extend(consultar_metricas(empresa_id, entidad_id=entidad_id, fecha_desde=fecha_inicio, fecha_hasta=fecha_fin))
    return filas


def calcular_kpis(empresa_id, entidad_ids, fecha_inicio, fecha_fin):
    """KPI agregados para el conjunto de entidades dado, en el rango
    [fecha_inicio, fecha_fin] (inclusive). `entidad_ids=None` agrega
    TODAS las campañas de la empresa en el periodo (nivel "empresa").
    `entidad_ids=[]` devuelve todas las claves en None (nivel sin
    datos, ej. una pagina de Facebook). SIEMPRE filtrado por
    empresa_id -- aislamiento multi-tenant.

    IMPORTANTE sobre `entidad_ids=None`: se filtra a entidad_tipo=
    "campana" exclusivamente, nunca "todas las filas de Metrica sin
    distincion de nivel". Cada campana, cada uno de sus conjuntos y
    cada uno de sus anuncios tiene SU PROPIA fila de insights
    sincronizada (ver insights_service.NIVELES_CON_INSIGHTS) -- sumar
    los tres niveles a la vez triplicaria el gasto real (el mismo peso
    contado a nivel de anuncio, de su conjunto y de su campana). Sumar
    solo el nivel "campana" (el mas alto bajo la cuenta publicitaria)
    da el total correcto sin doble conteo. Mismo criterio ya aplicado
    en resolver_entidades_para_kpi() para el nivel "cuenta_publicitaria".

    Devuelve un dict con cada clave de CLAVES_KPI -> numero o None, mas
    "resultados" como alias explicito de "conversiones" (ver nota de
    catalogo en app/services/metricas.py sobre esta simplificacion).
    """
    filas = _filas_del_alcance(empresa_id, entidad_ids, fecha_inicio, fecha_fin)
    return _calcular_desde_filas(filas)


def serie_diaria(empresa_id, entidad_ids, fecha_inicio, fecha_fin):
    """KPI dia por dia dentro de [fecha_inicio, fecha_fin] (Paso 4:
    graficos de evolucion) -- reutiliza EXACTAMENTE la misma agregacion
    que calcular_kpis() (_calcular_desde_filas), solo que agrupada por
    fecha en vez de colapsada a un unico total. Una sola consulta a la
    base de datos (no una por dia) -- se agrupa en Python.

    Devuelve una lista ordenada por fecha de dicts
    {"fecha": date, **kpis_de_ese_dia}. Un dia sin ninguna fila
    sincronizada devuelve sus KPI en None (nunca 0 inventado) --
    distinto de un dia con spend=0.0 realmente reportado por Meta."""
    from datetime import timedelta

    filas = _filas_del_alcance(empresa_id, entidad_ids, fecha_inicio, fecha_fin)

    filas_por_fecha = {}
    for fila in filas:
        filas_por_fecha.setdefault(fila.fecha, []).append(fila)

    dias = []
    fecha = fecha_inicio
    while fecha <= fecha_fin:
        dias.append({"fecha": fecha, **_calcular_desde_filas(filas_por_fecha.get(fecha, []))})
        fecha += timedelta(days=1)
    return dias


def calcular_variacion_porcentual(valor_anterior, valor_actual):
    """% de cambio de `valor_anterior` a `valor_actual`. None si falta
    alguno de los dos valores o si el anterior es 0 (una division por
    cero no se aproxima honestamente a ningun porcentaje)."""
    if valor_anterior is None or valor_actual is None:
        return None
    if valor_anterior == 0:
        return None
    return round((valor_actual - valor_anterior) / abs(valor_anterior) * 100, 2)


def comparar_periodos(empresa_id, entidad_ids, fecha_inicio, fecha_fin):
    """KPI del periodo solicitado + KPI del periodo anterior
    equivalente (misma duracion, ver periodos.py) + variacion
    porcentual de cada clave. `entidad_ids=None` agrega toda la
    empresa."""
    actual = calcular_kpis(empresa_id, entidad_ids, fecha_inicio, fecha_fin)
    inicio_anterior, fin_anterior = periodo_anterior_equivalente(fecha_inicio, fecha_fin)
    anterior = calcular_kpis(empresa_id, entidad_ids, inicio_anterior, fin_anterior)

    variaciones = {clave: calcular_variacion_porcentual(anterior.get(clave), actual.get(clave)) for clave in actual}

    return {
        "periodo_actual": {"fecha_inicio": fecha_inicio, "fecha_fin": fecha_fin, "kpis": actual},
        "periodo_anterior": {"fecha_inicio": inicio_anterior, "fecha_fin": fin_anterior, "kpis": anterior},
        "variacion_porcentual": variaciones,
    }


def comparar_entidades(empresa_id, entidad_ids, fecha_inicio, fecha_fin, metrica_orden="spend", mayor_es_mejor=None):
    """KPI individual de cada entidad de `entidad_ids` (se asume mismo
    nivel -- todas campañas, o todas conjuntos, o todos anuncios; sirve
    igual para "campaña vs campaña", "conjunto vs conjunto" y "anuncio
    vs anuncio", ya que la comparacion no depende del tipo) + deteccion
    de mejor/peor segun `metrica_orden`.

    `mayor_es_mejor` se infiere automaticamente de
    METRICAS_MENOR_ES_MEJOR si no se especifica (ej. para "cpc" un
    valor MENOR es mejor rendimiento).

    Devuelve una lista de dicts {entidad, kpis, es_mejor, es_peor},
    ordenada de mejor a peor segun `metrica_orden`. Las entidades sin
    dato para esa metrica quedan al final, sin marcar mejor/peor."""
    from app.extensions import db
    from app.models import EntidadPublicitaria

    if mayor_es_mejor is None:
        mayor_es_mejor = metrica_orden not in METRICAS_MENOR_ES_MEJOR

    entidades_por_id = {}
    if entidad_ids:
        entidades = (
            db.session.query(EntidadPublicitaria)
            .filter(EntidadPublicitaria.empresa_id == empresa_id, EntidadPublicitaria.id.in_(entidad_ids))
            .all()
        )
        entidades_por_id = {e.id: e for e in entidades}

    filas = []
    for entidad_id in entidad_ids or []:
        entidad = entidades_por_id.get(entidad_id)
        if entidad is None:
            continue  # no pertenece a esta empresa -- se omite, nunca se filtra por otro lado
        kpis = calcular_kpis(empresa_id, [entidad_id], fecha_inicio, fecha_fin)
        filas.append({"entidad": entidad, "kpis": kpis, "es_mejor": False, "es_peor": False})

    con_dato = [f for f in filas if f["kpis"].get(metrica_orden) is not None]
    sin_dato = [f for f in filas if f["kpis"].get(metrica_orden) is None]
    con_dato.sort(key=lambda f: f["kpis"][metrica_orden], reverse=mayor_es_mejor)

    if con_dato:
        con_dato[0]["es_mejor"] = True
        if len(con_dato) > 1:
            con_dato[-1]["es_peor"] = True

    return con_dato + sin_dato
