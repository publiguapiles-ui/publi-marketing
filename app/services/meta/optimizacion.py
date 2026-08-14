"""Centro de optimizacion de pauta (Paso 11).

Reutiliza INTEGRAMENTE el motor ya construido -- este archivo NUNCA
recalcula un KPI ni vuelve a comparar entidades desde cero:
  - app/services/meta/kpi.py (Paso 3): comparar_entidades,
    comparar_periodos, serie_diaria.
  - app/services/meta/oportunidades.py (Paso 5): deteccion de
    oportunidades por comparacion de grupo (ctr alto/bajo, costo por
    resultado, frecuencia elevada, gasto sin resultado).
  - app/services/meta/inteligencia.py (Paso 8): clasificar_variacion,
    calcular_confianza, detectar_cambios_temporales (mejora/deterioro
    de UNA entidad contra su propio periodo anterior), y los umbrales
    de deterioro ya documentados alli.
  - app/services/presupuestos.py (Paso 2): gasto real y disponible.

Lo UNICO nuevo aqui (no existia en ningun paso anterior) es:
  - deteccion de fatiga (combinacion de 4 señales a la vez, nunca una
    sola metrica aislada);
  - el "gate" explicito de suficiencia de datos ANTES de cualquier
    recomendacion (Paso 11, punto 4 -- "no marcar automaticamente una
    campaña con pocos datos como mala");
  - ritmo de consumo de presupuesto (tiempo transcurrido vs. %
    gastado, no un umbral absoluto);
  - la escala de prioridad CRITICO/ALTO/MEDIO/BAJO/INFORMATIVO:
  - el formato de "recomendacion explicable" (QUE PASO / POR QUE
    IMPORTA / EVIDENCIA / RECOMENDACION / RIESGO).

Nunca llama a la Graph API ni escribe nada en Meta -- es una capa de
LECTURA sobre datos ya sincronizados, igual que inteligencia.py.
"""

from datetime import date

from app.services.meta.inteligencia import (
    UMBRAL_DIAGNOSTICO_ATENCION,
    UMBRAL_DIAGNOSTICO_CRITICO,
    calcular_confianza,
)

NIVELES_PRIORIDAD = ["critico", "alto", "medio", "bajo", "informativo"]
ETIQUETAS_PRIORIDAD = {
    "critico": "CRÍTICO", "alto": "ALTO", "medio": "MEDIO", "bajo": "BAJO", "informativo": "INFORMATIVO",
}

# Volumen minimo para confiar en una recomendacion (Paso 11, punto 4).
# Heuristicas propias, documentadas y ajustables -- nunca un minimo
# oficial de Meta. Con menos de esto, la conclusion mas honesta es "no
# hay suficiente informacion", nunca marcar la entidad como mala.
UMBRAL_DIAS_MINIMOS_RECOMENDACION = 3
UMBRAL_IMPRESIONES_MINIMAS = 1000
UMBRAL_GASTO_MINIMO_POR_MONEDA = {"CRC": 5000, "USD": 10}

# Ritmo de gasto (% presupuesto usado / % tiempo transcurrido) a partir
# del cual se considera que el presupuesto "se esta consumiendo
# rapido" -- 1.3 significa que se esta gastando un 30% mas rapido de
# lo que marca el calendario del periodo. Heuristica propia.
UMBRAL_RITMO_PRESUPUESTO_ACELERADO = 1.3


def _dias_con_datos_entidad(empresa_id, entidad_id, fecha_inicio, fecha_fin):
    from app.services.meta.kpi import serie_diaria

    serie = serie_diaria(empresa_id, [entidad_id], fecha_inicio, fecha_fin)
    return sum(1 for dia in serie if dia.get("spend") is not None or dia.get("impressions") is not None)


def evaluar_suficiencia_datos(dias, kpis, moneda="CRC"):
    """(bool, motivo_o_None). Antes de CUALQUIER recomendacion basada en
    costo/CTR/frecuencia, verifica volumen minimo real -- dias con
    datos, impresiones, gasto -- para no marcar una entidad con pocos
    datos como mala (Paso 11, punto 4). Nunca usa un solo criterio: los
    tres se evaluan porque una entidad puede fallar en cualquiera de
    ellos por separado (ej. muchas impresiones pero 1 solo dia).
    `dias` se calcula UNA sola vez por entidad en el llamador (ver
    construir_centro_optimizacion) para no repetir la misma consulta a
    Metrica varias veces por la misma entidad."""
    if dias < UMBRAL_DIAS_MINIMOS_RECOMENDACION:
        return False, f"Solo hay {dias} día(s) con datos reales (mínimo recomendado: {UMBRAL_DIAS_MINIMOS_RECOMENDACION})."

    impresiones = kpis.get("impressions")
    if impresiones is not None and impresiones < UMBRAL_IMPRESIONES_MINIMAS:
        return False, f"Solo hay {impresiones} impresiones registradas (mínimo recomendado: {UMBRAL_IMPRESIONES_MINIMAS})."

    gasto = kpis.get("spend")
    umbral_gasto = UMBRAL_GASTO_MINIMO_POR_MONEDA.get(moneda)
    if umbral_gasto is not None and gasto is not None and gasto < umbral_gasto:
        return False, f"Solo se han invertido {gasto} {moneda} (mínimo recomendado: {umbral_gasto} {moneda})."

    return True, None


def clasificar_prioridad_desde_diagnostico(clasificacion):
    """BUENO/ATENCION/CRITICO/SIN_DATOS (inteligencia.py) -> escala de
    prioridad del Paso 11."""
    return {"critico": "critico", "atencion": "alto", "bueno": "informativo", "sin_datos": "informativo"}.get(clasificacion, "informativo")


def clasificar_prioridad_desde_nivel_oportunidad(nivel):
    """alto/medio/bajo (oportunidades.py) -> escala de prioridad del
    Paso 11. Una oportunidad nunca es CRITICA -- lo critico se reserva
    para deterioro real, no para una oportunidad de mejora."""
    return {"alto": "alto", "medio": "medio", "bajo": "bajo"}.get(nivel, "informativo")


def detectar_fatiga(empresa_id, entidades, fecha_inicio, fecha_fin):
    """Señales compatibles con fatiga (Paso 11, punto 5): frecuencia
    creciente, CTR descendente, CPC creciente y resultados
    descendentes, TODAS a la vez -- nunca una sola metrica aislada, y
    nunca se afirma "esta fatigado", solo que hay señales compatibles.
    Si falta el dato de alguna de las 4 señales (sin periodo anterior
    comparable), la entidad se omite en vez de adivinar."""
    from app.services.meta.kpi import comparar_periodos

    resultados = []
    for entidad in entidades:
        comparacion = comparar_periodos(empresa_id, [entidad.id], fecha_inicio, fecha_fin)
        variaciones = comparacion["variacion_porcentual"]
        frecuencia_var = variaciones.get("frequency")
        ctr_var = variaciones.get("ctr")
        cpc_var = variaciones.get("cpc")
        resultados_var = variaciones.get("resultados")
        if None in (frecuencia_var, ctr_var, cpc_var, resultados_var):
            continue
        if frecuencia_var > 0 and ctr_var < 0 and cpc_var > 0 and resultados_var < 0:
            resultados.append({
                "entidad_id": entidad.id,
                "entidad_nombre": entidad.nombre or entidad.id_externo,
                "mensaje": "Existen señales compatibles con posible fatiga.",
                "evidencia": {
                    "frecuencia_variacion_pct": frecuencia_var,
                    "ctr_variacion_pct": ctr_var,
                    "cpc_variacion_pct": cpc_var,
                    "resultados_variacion_pct": resultados_var,
                },
            })
    return resultados


def evaluar_ritmo_presupuesto(resumen_presupuesto, hoy=None):
    """% de tiempo transcurrido del periodo del presupuesto vs. % ya
    gastado (Paso 11, punto 3: "presupuesto consumiendose rapido" es un
    RITMO, no un umbral absoluto de gasto). None si el presupuesto no
    tiene fechas o monto validos para comparar."""
    hoy = hoy or date.today()
    fecha_inicio = resumen_presupuesto.get("fecha_inicio")
    fecha_fin = resumen_presupuesto.get("fecha_fin")
    porcentaje_gasto = resumen_presupuesto.get("porcentaje_usado")
    gasto_real = resumen_presupuesto.get("gasto_real")
    if not fecha_inicio or not fecha_fin or porcentaje_gasto is None:
        return None

    duracion_total = (fecha_fin - fecha_inicio).days + 1
    if duracion_total <= 0:
        return None
    transcurridos = max(0, min((hoy - fecha_inicio).days + 1, duracion_total))
    porcentaje_tiempo = round(transcurridos / duracion_total * 100, 1)

    ritmo = round(porcentaje_gasto / porcentaje_tiempo, 2) if porcentaje_tiempo > 0 else None

    # Gasto promedio diario y proyeccion (Paso 14, punto 10) -- SOLO se
    # calculan si ya transcurrio al menos 1 dia real del periodo; nunca
    # se inventa una proyeccion con 0 dias de datos (division por cero
    # evitada explicitamente, no un catch generico).
    gasto_promedio_diario = None
    proyeccion_fin_periodo = None
    if transcurridos > 0 and gasto_real is not None:
        gasto_promedio_diario = round(gasto_real / transcurridos, 2)
        proyeccion_fin_periodo = round(gasto_promedio_diario * duracion_total, 2)

    return {
        "porcentaje_tiempo_transcurrido": porcentaje_tiempo,
        "porcentaje_presupuesto_usado": porcentaje_gasto,
        "ritmo": ritmo,
        "consumiendose_rapido": ritmo is not None and ritmo >= UMBRAL_RITMO_PRESUPUESTO_ACELERADO,
        "gasto_promedio_diario": gasto_promedio_diario,
        "proyeccion_fin_periodo": proyeccion_fin_periodo,
    }


def recomendar_accion_presupuesto(variacion_costo_resultado, suficiente_datos):
    """'Mantener'/'Reducir'/'Evaluar aumento'/'Esperar más datos' (Paso
    11, punto 7) -- texto de recomendacion, NUNCA ejecuta nada. Se basa
    en la MISMA variacion de costo por resultado que clasifica el
    diagnostico del Paso 8, nunca en un calculo nuevo."""
    if not suficiente_datos or variacion_costo_resultado is None:
        return "Esperar más datos"
    if variacion_costo_resultado >= UMBRAL_DIAGNOSTICO_CRITICO:
        return "Reducir"
    if variacion_costo_resultado <= -UMBRAL_DIAGNOSTICO_ATENCION:
        return "Evaluar aumento"
    return "Mantener"


def construir_recomendacion_explicable(tipo, entidad_id, entidad_nombre, que_paso, por_que_importa, evidencia, recomendacion, prioridad, confianza, suficiente_datos=True, motivo_insuficiencia=None):
    """Empaqueta cualquier hallazgo (oportunidad, alerta, fatiga,
    cambio temporal) en el formato QUE PASO / POR QUE IMPORTA /
    EVIDENCIA / RECOMENDACION / RIESGO (Paso 11, punto 9). Si no hay
    suficientes datos, la recomendacion se reemplaza por el mensaje
    honesto del punto 4 -- nunca se sugiere una accion sobre datos
    insuficientes."""
    if not suficiente_datos:
        recomendacion_final = "Datos insuficientes para recomendar un cambio."
        riesgo = motivo_insuficiencia or "Volumen de datos insuficiente para esta entidad en el período."
        prioridad = "informativo"
    else:
        recomendacion_final = recomendacion
        riesgo = f"Confianza {confianza} — basada en el volumen de datos disponible actualmente en este período."

    return {
        "tipo": tipo,
        "entidad_id": entidad_id,
        "entidad_nombre": entidad_nombre,
        "prioridad": prioridad,
        "que_paso": que_paso,
        "por_que_importa": por_que_importa,
        "evidencia": evidencia,
        "recomendacion": recomendacion_final,
        "riesgo": riesgo,
        "confianza": confianza,
    }


_POR_QUE_IMPORTA = {
    "ctr_alto": "Un CTR superior al promedio suele indicar un creativo o segmentación más relevante para la audiencia.",
    "ctr_bajo": "Un CTR por debajo del promedio puede indicar un creativo poco relevante o una audiencia mal ajustada.",
    "cpm_bajo": "Un CPM bajo significa que se está pagando menos por cada mil impresiones que el resto del grupo.",
    "costo_resultado_bajo": "Un costo por resultado bajo significa que esta entidad está generando resultados de forma más eficiente que el resto del grupo.",
    "costo_resultado_alto": "Un costo por resultado alto significa que se está pagando más por cada resultado que el resto del grupo.",
    "buen_rendimiento_poco_presupuesto": "Buen rendimiento con poca inversión puede ser una oportunidad de escalar sin haber alcanzado su techo todavía.",
    "frecuencia_elevada": "Una frecuencia elevada aumenta el riesgo de que la misma persona vea el anuncio demasiadas veces, lo que puede desgastar el rendimiento.",
    "gasto_alto_sin_resultados": "Gasto elevado sin ningún resultado registrado representa presupuesto invertido sin retorno medible.",
    "gasto_alto_bajo_resultado": "Gasto elevado con resultados por debajo del promedio puede indicar una distribución de presupuesto ineficiente.",
    "mejora_significativa": "Una mejora significativa en el costo por resultado frente al período anterior puede representar una oportunidad de escalar esa entidad.",
    "deterioro": "Un deterioro significativo en el costo por resultado frente al período anterior puede representar presupuesto perdiéndose de forma creciente.",
    "fatiga": "La combinación de frecuencia en aumento, CTR y resultados en caída, con CPC en aumento, es un patrón típico de audiencias que empiezan a saturarse.",
}

_RECOMENDACION_SUGERIDA = {
    "ctr_alto": "Evaluar aumentar gradualmente su participación presupuestaria.",
    "ctr_bajo": "Revisar el creativo o la segmentación.",
    "cpm_bajo": "Evaluar escalar la inversión gradualmente.",
    "costo_resultado_bajo": "Evaluar aumentar gradualmente su participación presupuestaria.",
    "costo_resultado_alto": "Revisar la entidad antes de seguir invirtiendo al mismo ritmo.",
    "buen_rendimiento_poco_presupuesto": "Evaluar aumentar gradualmente su presupuesto.",
    "frecuencia_elevada": "Vigilar de cerca; evaluar renovar el creativo o ampliar la audiencia si continúa subiendo.",
    "gasto_alto_sin_resultados": "Revisar de inmediato antes de seguir invirtiendo en esta entidad.",
    "gasto_alto_bajo_resultado": "Revisar la distribución de presupuesto de esta entidad.",
    "mejora_significativa": "Evaluar aumentar gradualmente su participación presupuestaria.",
    "deterioro": "Revisar la entidad con mayor deterioro antes de continuar invirtiendo al mismo ritmo.",
    "fatiga": "Evaluar renovar el creativo o ampliar/rotar la audiencia.",
}


def _envolver_oportunidad(op, dias_por_entidad, moneda, kpis_por_entidad):
    kpis = kpis_por_entidad.get(op["entidad_id"], {})
    dias = dias_por_entidad.get(op["entidad_id"], 0)
    suficiente, motivo = evaluar_suficiencia_datos(dias, kpis, moneda)
    return construir_recomendacion_explicable(
        tipo=op["tipo"],
        entidad_id=op["entidad_id"],
        entidad_nombre=op["entidad_nombre"],
        que_paso=op["que_detectamos"],
        por_que_importa=_POR_QUE_IMPORTA.get(op["tipo"], "Se detectó una diferencia relevante frente al promedio del grupo."),
        evidencia=op["que_detectamos"],
        recomendacion=_RECOMENDACION_SUGERIDA.get(op["tipo"], "Revisar esta entidad."),
        prioridad=clasificar_prioridad_desde_nivel_oportunidad(op["nivel"]),
        confianza=calcular_confianza(dias),
        suficiente_datos=suficiente,
        motivo_insuficiencia=motivo,
    )


def _envolver_cambio_temporal(cambio, dias_por_entidad, moneda, kpis_por_entidad):
    kpis = kpis_por_entidad.get(cambio["entidad_id"], {})
    dias = dias_por_entidad.get(cambio["entidad_id"], 0)
    suficiente, motivo = evaluar_suficiencia_datos(dias, kpis, moneda)
    prioridad = "critico" if cambio["tipo"] == "deterioro" else "medio"
    return construir_recomendacion_explicable(
        tipo=cambio["tipo"],
        entidad_id=cambio["entidad_id"],
        entidad_nombre=cambio["entidad_nombre"],
        que_paso=cambio["evidencia"],
        por_que_importa=_POR_QUE_IMPORTA.get(cambio["tipo"]),
        evidencia=cambio["evidencia"],
        recomendacion=_RECOMENDACION_SUGERIDA.get(cambio["tipo"], "Revisar esta entidad."),
        prioridad=prioridad,
        confianza=calcular_confianza(dias),
        suficiente_datos=suficiente,
        motivo_insuficiencia=motivo,
    )


def _envolver_fatiga(f, dias_por_entidad, moneda, kpis_por_entidad):
    kpis = kpis_por_entidad.get(f["entidad_id"], {})
    dias = dias_por_entidad.get(f["entidad_id"], 0)
    suficiente, motivo = evaluar_suficiencia_datos(dias, kpis, moneda)
    ev = f["evidencia"]
    evidencia_texto = (
        f"Frecuencia {'+' if ev['frecuencia_variacion_pct'] > 0 else ''}{ev['frecuencia_variacion_pct']}%, "
        f"CTR {ev['ctr_variacion_pct']}%, CPC {'+' if ev['cpc_variacion_pct'] > 0 else ''}{ev['cpc_variacion_pct']}%, "
        f"resultados {ev['resultados_variacion_pct']}% frente al período anterior."
    )
    return construir_recomendacion_explicable(
        tipo="fatiga",
        entidad_id=f["entidad_id"],
        entidad_nombre=f["entidad_nombre"],
        que_paso=f["mensaje"],
        por_que_importa=_POR_QUE_IMPORTA["fatiga"],
        evidencia=evidencia_texto,
        recomendacion=_RECOMENDACION_SUGERIDA["fatiga"],
        prioridad="alto",
        confianza=calcular_confianza(dias),
        suficiente_datos=suficiente,
        motivo_insuficiencia=motivo,
    )


def construir_comparacion_con_veredicto(comparacion, cambios_temporales):
    """Anota cada fila de kpi.comparar_entidades() con el veredicto del
    Paso 11 punto 2: MEJOR/PEOR (ya viene de comparar_entidades) +
    CAMBIÓ/SIN CAMBIO SIGNIFICATIVO (de detectar_cambios_temporales,
    reutilizado tal cual) -- nunca se vuelve a calcular nada."""
    cambios_por_entidad = {c["entidad_id"]: c["tipo"] for c in cambios_temporales}
    filas = []
    for fila in comparacion:
        entidad_id = fila["entidad"].id
        veredicto_temporal = cambios_por_entidad.get(entidad_id, "sin_cambio_significativo")
        filas.append({**fila, "veredicto_temporal": veredicto_temporal})
    return filas


def construir_centro_optimizacion(empresa_id, cuenta_id, fecha_inicio, fecha_fin, campana_id=None, conjunto_id=None):
    """(paquete_o_None, error_o_None). Nivel de analisis segun lo que
    se seleccione (Paso 11, punto 1):
      - Sin campana_id: nivel CUENTA -> compara las campañas entre si.
      - Con campana_id, sin conjunto_id: nivel CAMPAÑA -> compara sus conjuntos.
      - Con conjunto_id: nivel CONJUNTO -> compara sus anuncios.
    Reutiliza inteligencia.construir_diagnostico_cuenta()/
    construir_analisis_presupuesto() para el panel de cuenta, y
    kpi.comparar_entidades()/oportunidades.detectar_oportunidades_grupo()
    para el nivel seleccionado -- ningun calculo de KPI ni de
    oportunidades ocurre en este archivo."""
    from app.models import EntidadPublicitaria
    from app.extensions import db
    from app.services.meta.cuentas_service import listar_anuncios_de_conjuntos, listar_campanas_de_cuenta, listar_conjuntos_de_campana
    from app.services.meta.kpi import comparar_entidades
    from app.services.meta.oportunidades import detectar_oportunidades_grupo
    from app.services.meta.inteligencia import construir_analisis_presupuesto, construir_diagnostico_cuenta

    cuenta = None
    moneda = "CRC"
    if cuenta_id is not None:
        cuenta = db.session.query(EntidadPublicitaria).filter_by(id=cuenta_id, empresa_id=empresa_id, tipo="cuenta_publicitaria").first()
        if cuenta is None:
            return None, "La cuenta publicitaria seleccionada no pertenece a esta empresa."
        moneda = (cuenta.atributos or {}).get("moneda") or "CRC"

    nivel = "cuenta"
    entidades = []
    if conjunto_id is not None:
        conjunto = db.session.query(EntidadPublicitaria).filter_by(id=conjunto_id, empresa_id=empresa_id, tipo="conjunto_anuncios").first()
        if conjunto is None:
            return None, "El conjunto de anuncios seleccionado no pertenece a esta empresa."
        nivel = "conjunto"
        entidades = listar_anuncios_de_conjuntos(empresa_id, [conjunto.id])
    elif campana_id is not None:
        campana = db.session.query(EntidadPublicitaria).filter_by(id=campana_id, empresa_id=empresa_id, tipo="campana").first()
        if campana is None:
            return None, "La campaña seleccionada no pertenece a esta empresa."
        nivel = "campana"
        entidades = listar_conjuntos_de_campana(empresa_id, campana.id)
    elif cuenta_id is not None:
        entidades = listar_campanas_de_cuenta(empresa_id, cuenta_id)

    entidad_ids = [e.id for e in entidades]
    comparacion = comparar_entidades(empresa_id, entidad_ids, fecha_inicio, fecha_fin, metrica_orden="costo_por_resultado") if entidad_ids else []
    kpis_por_entidad = {f["entidad"].id: f["kpis"] for f in comparacion}

    oportunidades = detectar_oportunidades_grupo(comparacion)

    from app.services.meta.inteligencia import detectar_cambios_temporales

    cambios_temporales = detectar_cambios_temporales(empresa_id, entidades, fecha_inicio, fecha_fin) if entidades else []
    comparacion_con_veredicto = construir_comparacion_con_veredicto(comparacion, cambios_temporales)

    fatiga = detectar_fatiga(empresa_id, entidades, fecha_inicio, fecha_fin) if entidades else []

    # Los dias-con-datos de cada entidad se calculan UNA sola vez aqui
    # (una consulta a Metrica por entidad) y se reutilizan para todas
    # las recomendaciones de esa misma entidad, en vez de repetir la
    # consulta por cada oportunidad/cambio/fatiga detectado sobre ella.
    dias_por_entidad = {e.id: _dias_con_datos_entidad(empresa_id, e.id, fecha_inicio, fecha_fin) for e in entidades}

    recomendaciones = []
    for op in oportunidades:
        recomendaciones.append(_envolver_oportunidad(op, dias_por_entidad, moneda, kpis_por_entidad))
    for cambio in cambios_temporales:
        recomendaciones.append(_envolver_cambio_temporal(cambio, dias_por_entidad, moneda, kpis_por_entidad))
    for f in fatiga:
        recomendaciones.append(_envolver_fatiga(f, dias_por_entidad, moneda, kpis_por_entidad))

    orden_prioridad = {p: i for i, p in enumerate(NIVELES_PRIORIDAD)}
    recomendaciones.sort(key=lambda r: orden_prioridad.get(r["prioridad"], 99))

    diagnostico_cuenta = None
    analisis_presupuesto = None
    if cuenta_id is not None and nivel == "cuenta":
        diagnostico_cuenta, _error = construir_diagnostico_cuenta(empresa_id, cuenta_id, fecha_inicio, fecha_fin)
        analisis_presupuesto, _error = construir_analisis_presupuesto(empresa_id, cuenta_id, fecha_inicio, fecha_fin)

        # Areas del diagnostico de CUENTA (Paso 8) con clasificacion
        # ATENCION/CRITICO se suman como recomendaciones tambien --
        # asi "que necesita atencion primero" (DONE WHEN) combina tanto
        # deterioro a nivel de cuenta como hallazgos por entidad, en
        # una unica lista ordenada por prioridad.
        if diagnostico_cuenta:
            from app.services.meta.kpi import ETIQUETAS_KPI

            for clave, area in diagnostico_cuenta["areas"].items():
                if area["clasificacion"] not in ("atencion", "critico"):
                    continue
                recomendaciones.append(construir_recomendacion_explicable(
                    tipo=f"deterioro_cuenta_{clave}",
                    entidad_id=None,
                    entidad_nombre="Toda la cuenta",
                    que_paso=f"{ETIQUETAS_KPI.get(clave, clave)} varió {area['variacion_pct']}% frente al período anterior (valor actual: {area['valor']}).",
                    por_que_importa="Es una métrica agregada de toda la cuenta, no de una sola campaña -- un deterioro aquí afecta a toda la inversión del período.",
                    evidencia=f"{ETIQUETAS_KPI.get(clave, clave)}: {area['valor']} ({area['variacion_pct']}% vs. período anterior).",
                    recomendacion="Revisar qué campañas están impulsando este cambio.",
                    prioridad=clasificar_prioridad_desde_diagnostico(area["clasificacion"]),
                    confianza=area["confianza"],
                    suficiente_datos=area["confianza"] != "baja",
                    motivo_insuficiencia="Confianza baja: pocos días con datos o pocas campañas para comparar." if area["confianza"] == "baja" else None,
                ))
            recomendaciones.sort(key=lambda r: orden_prioridad.get(r["prioridad"], 99))

    # Recomendacion de accion por presupuesto (Paso 11, punto 7):
    # basada en la MISMA variacion de costo por resultado que ya
    # clasifico el diagnostico de cuenta -- solo aplica a presupuestos
    # de tipo "estrategico" (sin entidad_id propia, ver
    # presupuestos.py), donde el costo por resultado de TODA la cuenta
    # es la referencia razonable; un presupuesto "asignado" a una
    # campaña especifica queda sin accion automatica aqui (requeriria
    # su propio calculo, fuera del alcance de este paso).
    variacion_costo_cuenta = diagnostico_cuenta["areas"]["costo_por_resultado"]["variacion_pct"] if diagnostico_cuenta else None
    suficiente_datos_cuenta = bool(diagnostico_cuenta and diagnostico_cuenta["dias_con_datos"] >= UMBRAL_DIAS_MINIMOS_RECOMENDACION)

    ritmo_presupuestos = []
    if analisis_presupuesto:
        for r in analisis_presupuesto["presupuestos"]:
            if r["presupuesto"].entidad_id is None:
                r["accion_recomendada"] = recomendar_accion_presupuesto(variacion_costo_cuenta, suficiente_datos_cuenta)
            else:
                r["accion_recomendada"] = None

            ritmo = evaluar_ritmo_presupuesto(r)
            if ritmo and ritmo["consumiendose_rapido"]:
                ritmo_presupuestos.append({
                    "presupuesto_nombre": r["presupuesto"].nombre,
                    **ritmo,
                    "mensaje": f"El presupuesto \"{r['presupuesto'].nombre}\" lleva usado {ritmo['porcentaje_presupuesto_usado']}% con solo {ritmo['porcentaje_tiempo_transcurrido']}% del período transcurrido.",
                })

    return {
        "nivel": nivel,
        "cuenta_id": cuenta_id,
        "campana_id": campana_id,
        "conjunto_id": conjunto_id,
        "moneda": moneda,
        "comparacion": comparacion_con_veredicto,
        "oportunidades": oportunidades,
        "cambios_temporales": cambios_temporales,
        "fatiga": fatiga,
        "recomendaciones": recomendaciones,
        "diagnostico_cuenta": diagnostico_cuenta,
        "analisis_presupuesto": analisis_presupuesto,
        "ritmo_presupuestos": ritmo_presupuestos,
        # Expuesto para que otros consumidores (Paso 14: Centro de
        # Control, "mejor/peor segun el KPI seleccionado") no repitan
        # la misma consulta de dias-con-datos por entidad ya hecha aqui.
        "dias_por_entidad": dias_por_entidad,
    }, None


def construir_prioridades_para_claude(empresa_id, cuenta_id, fecha_inicio, fecha_fin, limite=5):
    """Lista simple y priorizada ('1. Revisar campaña X...') para que
    el Estratega IA (Paso 10) pueda responder '¿qué debería optimizar
    hoy?' -- reutiliza construir_centro_optimizacion() a nivel cuenta,
    nunca vuelve a analizar nada."""
    paquete, error = construir_centro_optimizacion(empresa_id, cuenta_id, fecha_inicio, fecha_fin)
    if error:
        return [], error

    lineas = []
    for r in paquete["recomendaciones"][:limite]:
        etiqueta = ETIQUETAS_PRIORIDAD.get(r["prioridad"], r["prioridad"])
        lineas.append(f"[{etiqueta}] {r['entidad_nombre']}: {r['que_paso']} Recomendación: {r['recomendacion']}")

    for rp in paquete["ritmo_presupuestos"][:limite]:
        lineas.append(f"[ALTO] Presupuesto: {rp['mensaje']}")

    return lineas, None
