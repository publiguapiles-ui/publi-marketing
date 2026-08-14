"""Motor de inteligencia estrategica (Paso 8): diagnostico + oportunidades
+ alertas + informe estructurado, basados EXCLUSIVAMENTE en reglas y
datos verificables -- SIN Claude ni ninguna IA generativa.

Reutiliza en su totalidad lo ya construido:
- app/services/meta/kpi.py (Paso 3): todo calculo de KPI, comparacion de
  periodos y comparacion entre entidades. Este archivo NUNCA vuelve a
  sumar/dividir una metrica nativa.
- app/services/meta/oportunidades.py (Paso 5): deteccion de oportunidades
  por comparacion contra el promedio del grupo (ctr alto/bajo, cpm bajo,
  costo por resultado, frecuencia elevada, gasto sin resultado). Este
  modulo solo AGREGA lo que falta (comparacion contra el periodo
  ANTERIOR de la misma entidad, que oportunidades.py no hace) y
  enriquece el formato para el punto 6 del enunciado (titulo/evidencia/
  confianza/impacto).
- app/services/meta/targeting.py y analisis.py (Paso 5): interpretacion
  de audiencia configurada y separacion "configurada" vs "con
  resultados".
- app/services/presupuestos.py (Paso 2): calculo de gasto real y
  disponible -- nunca se recalcula aqui.

Todos los umbrales usados para clasificar (BUENO/ATENCION/CRITICO,
alertas, confianza) son constantes declaradas explicitamente, igual que
en oportunidades.py -- heuristicas de marketing propias y ajustables,
nunca un valor que Meta reporte ni una verdad absoluta.
"""

CLASIFICACIONES_DIAGNOSTICO = ["bueno", "atencion", "critico", "sin_datos"]
NIVELES_CONFIANZA = ["alta", "media", "baja"]

# Variacion % (deterioro) frente al periodo anterior para pasar de
# BUENO a ATENCION o de ATENCION a CRITICO. Se aplican sobre la
# variacion YA calculada por kpi.comparar_periodos() -- nunca sobre un
# numero recalculado aqui.
UMBRAL_DIAGNOSTICO_ATENCION = 15
UMBRAL_DIAGNOSTICO_CRITICO = 35

# Mismos umbrales para clasificar un cambio periodo-contra-periodo de
# UNA campaña como "mejora significativa" o "deterioro" (punto 2).
UMBRAL_CAMBIO_SIGNIFICATIVO = 20

# Confianza de una conclusion, en funcion de cuantos DIAS con datos
# reales respaldan el calculo (ver calcular_confianza) -- una conclusion
# sobre 2 dias de datos no puede tener la misma confianza que una sobre
# 30. Heuristica propia, documentada.
UMBRAL_CONFIANZA_ALTA_DIAS = 14
UMBRAL_CONFIANZA_MEDIA_DIAS = 5

# "Presupuesto agotandose" (alerta): % ya usado de un presupuesto para
# considerar que se acerca al limite.
UMBRAL_PRESUPUESTO_AGOTANDOSE = 85


def calcular_confianza(dias_con_datos, cantidad_entidades=1):
    """ALTA/MEDIA/BAJA segun cuantos dias reales de metricas respaldan
    la conclusion (Paso 8, punto 9) -- nunca segun cuan "segura" se vea
    una cifra. Con menos de 2 dias de datos, o ninguna entidad, no hay
    base para ninguna conclusion confiable."""
    if dias_con_datos is None or dias_con_datos < 2 or cantidad_entidades < 1:
        return "baja"
    if dias_con_datos >= UMBRAL_CONFIANZA_ALTA_DIAS and cantidad_entidades >= 2:
        return "alta"
    if dias_con_datos >= UMBRAL_CONFIANZA_MEDIA_DIAS:
        return "media"
    return "baja"


def _dias_con_datos(serie, claves=("spend", "impressions")):
    return sum(1 for dia in serie if any(dia.get(c) is not None for c in claves))


def clasificar_variacion(clave, variacion_pct):
    """BUENO/ATENCION/CRITICO/SIN_DATOS para una clave de KPI, a partir
    de la variacion% que kpi.comparar_periodos() YA calculo -- nunca
    inventa el numero, solo lo clasifica. Para las metricas donde un
    valor MENOR es mejor (kpi.METRICAS_MENOR_ES_MEJOR, ej. CPC/CPM/costo
    por resultado), la clasificacion invierte el signo de la variacion
    antes de compararla contra los umbrales."""
    from app.services.meta.kpi import METRICAS_MENOR_ES_MEJOR

    if variacion_pct is None:
        return "sin_datos"
    # Para metricas "menor es mejor" (costo_por_resultado, cpc, cpm), un
    # aumento (variacion_pct positiva) ES el deterioro -- se usa tal
    # cual. Para el resto (ctr, spend, conversiones...), una caida
    # (variacion_pct negativa) es el deterioro -- se invierte el signo
    # para que "deterioro" sea siempre positivo cuando algo empeoro.
    deterioro = variacion_pct if clave in METRICAS_MENOR_ES_MEJOR else -variacion_pct
    if deterioro >= UMBRAL_DIAGNOSTICO_CRITICO:
        return "critico"
    if deterioro >= UMBRAL_DIAGNOSTICO_ATENCION:
        return "atencion"
    return "bueno"


def construir_diagnostico_cuenta(empresa_id, cuenta_id, fecha_inicio, fecha_fin):
    """(diagnostico_o_None, error_o_None). Diagnostico por area (Paso 8,
    punto 1): valor actual + variacion% + clasificacion BUENO/ATENCION/
    CRITICO/SIN_DATOS de cada KPI, comparado contra el periodo anterior
    equivalente (histórico de la propia cuenta) y, cuando hay mas de una
    campaña, contra el promedio de las campañas del periodo."""
    from app.services.meta.kpi import CLAVES_KPI, comparar_entidades, comparar_periodos, resolver_entidades_para_kpi, serie_diaria
    from app.services.meta.cuentas_service import listar_campanas_de_cuenta

    entidad_ids = None
    if cuenta_id is not None:
        entidad_ids, error = resolver_entidades_para_kpi(empresa_id, cuenta_id)
        if error:
            return None, error

    comparacion = comparar_periodos(empresa_id, entidad_ids, fecha_inicio, fecha_fin)
    kpis_actuales = comparacion["periodo_actual"]["kpis"]
    variaciones = comparacion["variacion_porcentual"]
    serie = serie_diaria(empresa_id, entidad_ids, fecha_inicio, fecha_fin)
    dias_con_datos = _dias_con_datos(serie)

    campanas = listar_campanas_de_cuenta(empresa_id, cuenta_id) if cuenta_id is not None else []
    comparacion_campanas = (
        comparar_entidades(empresa_id, [c.id for c in campanas], fecha_inicio, fecha_fin, metrica_orden="spend")
        if len(campanas) > 1 else []
    )

    areas = {}
    for clave in CLAVES_KPI:
        valor = kpis_actuales.get(clave)
        variacion = variaciones.get(clave)

        promedio_campanas = None
        if comparacion_campanas:
            valores_campanas = [f["kpis"].get(clave) for f in comparacion_campanas if f["kpis"].get(clave) is not None]
            promedio_campanas = round(sum(valores_campanas) / len(valores_campanas), 2) if valores_campanas else None

        areas[clave] = {
            "valor": valor,
            "variacion_pct": variacion,
            "clasificacion": clasificar_variacion(clave, variacion) if valor is not None else "sin_datos",
            "promedio_campanas": promedio_campanas,
            "confianza": calcular_confianza(dias_con_datos, len(campanas) or 1),
        }

    return {
        "kpis": kpis_actuales,
        "areas": areas,
        "comparacion_periodos": comparacion,
        "dias_con_datos": dias_con_datos,
        "cantidad_campanas": len(campanas),
    }, None


def detectar_cambios_temporales(empresa_id, entidades, fecha_inicio, fecha_fin):
    """'Campañas con deterioro del rendimiento' y 'con mejora
    significativa' (Paso 8, punto 2) -- a diferencia de
    oportunidades.detectar_oportunidades_grupo() (que compara entidades
    ENTRE SI en el mismo periodo), esto compara cada entidad contra SU
    PROPIO periodo anterior, usando costo_por_resultado como KPI de
    referencia (el mas directamente accionable). Solo entidades con dato
    en ambos periodos generan una conclusion."""
    from app.services.meta.kpi import comparar_periodos

    cambios = []
    for entidad in entidades:
        comparacion = comparar_periodos(empresa_id, [entidad.id], fecha_inicio, fecha_fin)
        variacion = comparacion["variacion_porcentual"].get("costo_por_resultado")
        if variacion is None:
            continue
        # costo_por_resultado: un valor MENOR es mejor -> variacion negativa es mejora.
        if variacion <= -UMBRAL_CAMBIO_SIGNIFICATIVO:
            cambios.append({
                "tipo": "mejora_significativa",
                "entidad_id": entidad.id,
                "entidad_nombre": entidad.nombre or entidad.id_externo,
                "evidencia": f"Costo por resultado bajó {abs(variacion)}% frente al período anterior equivalente.",
                "variacion_pct": variacion,
            })
        elif variacion >= UMBRAL_CAMBIO_SIGNIFICATIVO:
            cambios.append({
                "tipo": "deterioro",
                "entidad_id": entidad.id,
                "entidad_nombre": entidad.nombre or entidad.id_externo,
                "evidencia": f"Costo por resultado subió {variacion}% frente al período anterior equivalente.",
                "variacion_pct": variacion,
            })
    return cambios


def construir_analisis_campanas(empresa_id, cuenta_id, fecha_inicio, fecha_fin):
    """(paquete, error). Ensambla el 'Análisis de campañas' del Paso 8:
    reutiliza kpi.comparar_entidades (mejor/peor del periodo) +
    oportunidades.detectar_oportunidades_grupo (alto gasto/bajo
    resultado, frecuencia elevada, buen rendimiento con poco
    presupuesto) + detectar_cambios_temporales (nuevo: mejora/deterioro
    contra el periodo anterior). Ningun calculo de KPI se repite."""
    from app.services.meta.cuentas_service import listar_campanas_de_cuenta
    from app.services.meta.kpi import comparar_entidades
    from app.services.meta.oportunidades import detectar_oportunidades_grupo

    if cuenta_id is None:
        return {"campanas": [], "oportunidades": [], "cambios_temporales": []}, None

    campanas = listar_campanas_de_cuenta(empresa_id, cuenta_id)
    campana_ids = [c.id for c in campanas]
    comparacion = comparar_entidades(empresa_id, campana_ids, fecha_inicio, fecha_fin, metrica_orden="costo_por_resultado") if campana_ids else []
    oportunidades = detectar_oportunidades_grupo(comparacion)
    cambios = detectar_cambios_temporales(empresa_id, campanas, fecha_inicio, fecha_fin)

    return {"campanas": comparacion, "oportunidades": oportunidades, "cambios_temporales": cambios}, None


def construir_analisis_audiencias(empresa_id, cuenta_id, fecha_inicio, fecha_fin):
    """Reutiliza analisis.analizar_audiencias() (Paso 5) tal cual --
    ya separa 'audiencia configurada' de 'audiencia con resultados' y
    detecta oportunidades por segmento. No se duplica nada aqui."""
    from app.services.meta.analisis import analizar_audiencias

    paquete, error = analizar_audiencias(empresa_id, cuenta_id, fecha_inicio, fecha_fin)
    return paquete, error


def construir_analisis_creativos(empresa_id, cuenta_id, fecha_inicio, fecha_fin):
    """(paquete, error). Compara anuncios por CTR/CPC/CPM/resultados/
    costo por resultado/reproducciones (Paso 8, punto 4). La deteccion
    de 'formato video' NO inventa un campo que Meta no sincronizo
    (creativo.tipo no existe en nuestros datos, ver campanas_service.py)
    -- usa `video_plays` (metrica real de insights: solo los anuncios de
    video reportan reproducciones) como la unica señal honesta
    disponible para distinguir video de no-video."""
    from app.services.meta.cuentas_service import listar_anuncios_de_conjuntos, listar_conjuntos_de_empresa
    from app.services.meta.kpi import comparar_entidades

    if cuenta_id is None:
        return {"anuncios": [], "patron_video": None}, None

    conjuntos = listar_conjuntos_de_empresa(empresa_id, cuenta_id=cuenta_id)
    anuncios = listar_anuncios_de_conjuntos(empresa_id, [c.id for c in conjuntos])
    anuncio_ids = [a.id for a in anuncios]
    comparacion = comparar_entidades(empresa_id, anuncio_ids, fecha_inicio, fecha_fin, metrica_orden="costo_por_resultado") if anuncio_ids else []

    con_video = [f for f in comparacion if (f["kpis"].get("video_plays") or 0) > 0]
    sin_video = [f for f in comparacion if not (f["kpis"].get("video_plays") or 0) > 0]

    patron_video = None
    if con_video and sin_video:
        ctr_con = [f["kpis"]["ctr"] for f in con_video if f["kpis"].get("ctr") is not None]
        ctr_sin = [f["kpis"]["ctr"] for f in sin_video if f["kpis"].get("ctr") is not None]
        if ctr_con and ctr_sin:
            promedio_con = round(sum(ctr_con) / len(ctr_con), 2)
            promedio_sin = round(sum(ctr_sin) / len(ctr_sin), 2)
            if promedio_sin:
                diferencia = round((promedio_con - promedio_sin) / promedio_sin * 100, 1)
                patron_video = {
                    "promedio_ctr_con_video": promedio_con,
                    "promedio_ctr_sin_video": promedio_sin,
                    "diferencia_pct": diferencia,
                    "mensaje": (
                        f"Los anuncios con reproducciones de video registradas tienen un CTR promedio "
                        f"{'superior' if diferencia > 0 else 'inferior'} ({promedio_con}% vs {promedio_sin}%) "
                        f"al de los anuncios sin reproducciones de video en este período."
                    ),
                }

    return {"anuncios": comparacion, "patron_video": patron_video}, None


def construir_analisis_presupuesto(empresa_id, cuenta_id, fecha_inicio, fecha_fin):
    """Relaciona el presupuesto estrategico (Paso 2/7) con el
    rendimiento real (Paso 8, punto 5) -- reutiliza presupuestos.py sin
    ninguna formula nueva. Nunca cambia ningun presupuesto."""
    from app.services.meta.cuentas_service import listar_campanas_de_cuenta
    from app.services.meta.kpi import comparar_entidades
    from app.services.presupuestos import calcular_resumen_presupuesto, obtener_presupuestos_empresa

    presupuestos = [calcular_resumen_presupuesto(p) for p in obtener_presupuestos_empresa(empresa_id)]

    concentracion = []
    if cuenta_id is not None:
        campanas = listar_campanas_de_cuenta(empresa_id, cuenta_id)
        comparacion = comparar_entidades(empresa_id, [c.id for c in campanas], fecha_inicio, fecha_fin, metrica_orden="spend") if campanas else []
        gasto_total = sum(f["kpis"].get("spend") or 0 for f in comparacion)
        for fila in comparacion:
            spend = fila["kpis"].get("spend")
            if spend is not None and gasto_total:
                porcentaje = round(spend / gasto_total * 100, 1)
                if porcentaje >= 50 and len(comparacion) > 1:
                    concentracion.append({
                        "entidad_id": fila["entidad"].id,
                        "entidad_nombre": fila["entidad"].nombre or fila["entidad"].id_externo,
                        "porcentaje_del_gasto_total": porcentaje,
                        "mensaje": f"Concentra el {porcentaje}% del gasto total de la cuenta en este período.",
                    })

    return {"presupuestos": presupuestos, "concentracion": concentracion}, None


def construir_oportunidades_estrategicas(analisis_campanas, analisis_audiencias, dias_con_datos):
    """Enriquece las oportunidades YA detectadas (oportunidades.py, sin
    IA) al formato del Paso 8, punto 6: titulo/descripcion/evidencia/
    KPI relacionado/confianza/impacto/datos utilizados. No detecta nada
    nuevo -- es una capa de presentacion sobre detectar_oportunidades_grupo()."""
    TITULOS = {
        "ctr_alto": "Evaluar mayor inversión en esta campaña",
        "ctr_bajo": "Revisar el creativo o segmentación de esta campaña",
        "cpm_bajo": "Costo de exposición favorable — oportunidad de escalar",
        "costo_resultado_bajo": "Costo por resultado favorable",
        "costo_resultado_alto": "Costo por resultado elevado — revisar",
        "buen_rendimiento_poco_presupuesto": "Evaluar mayor inversión",
        "frecuencia_elevada": "Riesgo de fatiga publicitaria",
        "gasto_alto_sin_resultados": "Gasto elevado sin resultados registrados",
        "gasto_alto_bajo_resultado": "Gasto elevado con resultados por debajo del promedio",
    }
    KPI_POR_TIPO = {
        "ctr_alto": "ctr", "ctr_bajo": "ctr", "cpm_bajo": "cpm",
        "costo_resultado_bajo": "costo_por_resultado", "costo_resultado_alto": "costo_por_resultado",
        "buen_rendimiento_poco_presupuesto": "costo_por_resultado", "frecuencia_elevada": "frequency",
        "gasto_alto_sin_resultados": "spend", "gasto_alto_bajo_resultado": "spend",
    }

    fuentes = list(analisis_campanas.get("oportunidades", [])) + list(analisis_audiencias.get("oportunidades", []) if analisis_audiencias else [])

    resultado = []
    for op in fuentes:
        confianza = "alta" if op["nivel"] == "alto" and dias_con_datos and dias_con_datos >= UMBRAL_CONFIANZA_ALTA_DIAS else (
            "media" if dias_con_datos and dias_con_datos >= UMBRAL_CONFIANZA_MEDIA_DIAS else "baja"
        )
        resultado.append({
            "titulo": TITULOS.get(op["tipo"], "Oportunidad detectada"),
            "descripcion": op["que_detectamos"],
            "evidencia": op["que_detectamos"],
            "kpi_relacionado": KPI_POR_TIPO.get(op["tipo"]),
            "nivel_confianza": confianza,
            "impacto_potencial": op["nivel"],
            "entidad_id": op["entidad_id"],
            "entidad_nombre": op["entidad_nombre"],
            "datos_utilizados": {"dato": op["dato"]},
        })
    return resultado


def construir_alertas(diagnostico, analisis_campanas, analisis_presupuesto):
    """'ALERTAS' (Paso 8, punto 7): situaciones detectadas por regla,
    cada una con qué ocurrió / qué KPI lo demuestra. Reutiliza el
    diagnostico ya clasificado (variaciones), las oportunidades de
    'gasto sin resultados' ya detectadas, y el % usado del presupuesto
    estrategico -- ningun calculo nuevo."""
    alertas = []

    for clave, area in diagnostico["areas"].items():
        if area["clasificacion"] in ("atencion", "critico") and area["variacion_pct"] is not None:
            alertas.append({
                "tipo": f"deterioro_{clave}",
                "severidad": area["clasificacion"],
                "que_ocurrio": f"{clave} empeoró {abs(area['variacion_pct'])}% frente al período anterior.",
                "kpi": clave,
                "variacion_pct": area["variacion_pct"],
            })

    for op in analisis_campanas.get("oportunidades", []):
        if op["tipo"] in ("gasto_alto_sin_resultados", "gasto_alto_bajo_resultado", "frecuencia_elevada"):
            alertas.append({
                "tipo": op["tipo"],
                "severidad": op["nivel"],
                "que_ocurrio": op["que_detectamos"],
                "kpi": KPI_POR_TIPO_ALERTA.get(op["tipo"], "spend"),
                "entidad_id": op["entidad_id"],
                "entidad_nombre": op["entidad_nombre"],
            })

    for cambio in analisis_campanas.get("cambios_temporales", []):
        if cambio["tipo"] == "deterioro":
            alertas.append({
                "tipo": "deterioro_campana",
                "severidad": "atencion",
                "que_ocurrio": f"{cambio['entidad_nombre']}: {cambio['evidencia']}",
                "kpi": "costo_por_resultado",
                "entidad_id": cambio["entidad_id"],
                "entidad_nombre": cambio["entidad_nombre"],
            })

    for r in analisis_presupuesto.get("presupuestos", []):
        if r["porcentaje_usado"] is not None and r["porcentaje_usado"] >= UMBRAL_PRESUPUESTO_AGOTANDOSE:
            alertas.append({
                "tipo": "presupuesto_agotandose",
                "severidad": "alto" if r["porcentaje_usado"] >= 100 else "atencion",
                "que_ocurrio": f"Presupuesto '{r['presupuesto'].nombre}' con {r['porcentaje_usado']}% ya utilizado.",
                "kpi": "spend",
            })

    return alertas


KPI_POR_TIPO_ALERTA = {
    "gasto_alto_sin_resultados": "spend",
    "gasto_alto_bajo_resultado": "spend",
    "frecuencia_elevada": "frequency",
}


def construir_inteligencia(empresa_id, cuenta_id, fecha_inicio, fecha_fin):
    """Punto de entrada UNICO del Paso 8: ensambla diagnostico +
    campañas + audiencias + creativos + presupuesto + oportunidades +
    alertas para una empresa/cuenta/periodo. (paquete_o_None, error)."""
    diagnostico, error = construir_diagnostico_cuenta(empresa_id, cuenta_id, fecha_inicio, fecha_fin)
    if error:
        return None, error

    analisis_campanas, _ = construir_analisis_campanas(empresa_id, cuenta_id, fecha_inicio, fecha_fin)
    analisis_audiencias, _ = construir_analisis_audiencias(empresa_id, cuenta_id, fecha_inicio, fecha_fin)
    analisis_creativos, _ = construir_analisis_creativos(empresa_id, cuenta_id, fecha_inicio, fecha_fin)
    analisis_presupuesto, _ = construir_analisis_presupuesto(empresa_id, cuenta_id, fecha_inicio, fecha_fin)

    oportunidades = construir_oportunidades_estrategicas(analisis_campanas, analisis_audiencias, diagnostico["dias_con_datos"])
    alertas = construir_alertas(diagnostico, analisis_campanas, analisis_presupuesto)

    return {
        "diagnostico": diagnostico,
        "campanas": analisis_campanas,
        "audiencias": analisis_audiencias,
        "creativos": analisis_creativos,
        "presupuesto": analisis_presupuesto,
        "oportunidades": oportunidades,
        "alertas": alertas,
    }, None


def construir_informe_estructurado(empresa, cuenta_id, fecha_inicio, fecha_fin, objetivo=None, presupuesto_total=None):
    """Paso 8, punto 8: objeto estructurado listo para que un futuro
    consumidor (Claude u otro, todavia NO conectado) reciba el estado
    completo sin pasar por HTML. `objetivo`/`presupuesto_total` son
    opcionales -- vienen de un ProyectoPauta (Paso 7) cuando existe uno
    para esta empresa/cuenta, nunca inventados si no hay proyecto."""
    paquete, error = construir_inteligencia(empresa.id, cuenta_id, fecha_inicio, fecha_fin)
    if error:
        return None, error

    return {
        "empresa": {"id": empresa.id, "nombre": empresa.nombre},
        "objetivo": objetivo,
        "presupuesto_total": presupuesto_total,
        "periodo": {"fecha_inicio": fecha_inicio, "fecha_fin": fecha_fin},
        "diagnostico": paquete["diagnostico"],
        "campanas": paquete["campanas"],
        "audiencias": paquete["audiencias"],
        "creativos": paquete["creativos"],
        "kpi": paquete["diagnostico"]["kpis"],
        "oportunidades": paquete["oportunidades"],
        "alertas": paquete["alertas"],
        "historico": paquete["diagnostico"]["comparacion_periodos"],
    }, None
