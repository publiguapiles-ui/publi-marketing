"""Motor de "OPORTUNIDADES DETECTADAS" (Paso 5, punto 6).

Deliberadamente SIN IA/Claude: son comparaciones aritmeticas de cada
entidad contra el PROMEDIO de su propio grupo (las mismas campañas,
conjuntos o anuncios que ya se estan comparando entre si), usando
UNICAMENTE los KPI que ya calculo app/services/meta/kpi.py -- este
archivo nunca vuelve a sumar/dividir una metrica nativa, solo compara
numeros ya calculados.

Los umbrales de "significativo" son heuristicas de marketing
declaradas EXPLICITAMENTE como constantes aqui (nunca escondidas en un
condicional) para que sean visibles, revisables y ajustables -- no son
un valor que Meta reporte ni una verdad absoluta. Cada oportunidad
incluye el dato real que la respalda para que el usuario pueda
verificarla.

Con un grupo de una sola entidad, esa entidad ES el promedio -> la
diferencia relativa siempre es 0 -> no se detecta nada (comportamiento
seguro por defecto, no un caso especial).
"""

# % de diferencia contra el promedio del grupo para considerar la
# oportunidad "media" o "alta". Ej. UMBRAL_CTR_MEDIO=0.20 significa
# "CTR al menos 20% por encima del promedio del grupo".
UMBRAL_CTR_MEDIO = 0.20
UMBRAL_CTR_ALTO = 0.50
UMBRAL_CPM_MEDIO = 0.20
UMBRAL_CPM_ALTO = 0.40
UMBRAL_COSTO_RESULTADO_MEDIO = 0.20
UMBRAL_COSTO_RESULTADO_ALTO = 0.40
UMBRAL_GASTO_ALTO = 0.20

# Frecuencia (impresiones/alcance) considerada "elevada" -- heuristica
# comun de fatiga publicitaria en pauta digital, no un limite que Meta
# imponga.
FRECUENCIA_ELEVADA_MEDIO = 3.0
FRECUENCIA_ELEVADA_ALTO = 5.0


def _promedio(valores):
    return sum(valores) / len(valores) if valores else None


def _nivel_por_diferencia(diferencia_relativa, umbral_medio, umbral_alto):
    if diferencia_relativa >= umbral_alto:
        return "alto"
    if diferencia_relativa >= umbral_medio:
        return "medio"
    return None


def _oportunidad(tipo, nivel, entidad, que_detectamos, dato):
    return {
        "tipo": tipo,
        "nivel": nivel,
        "que_detectamos": que_detectamos,
        "dato": dato,
        "entidad_id": entidad.id,
        "entidad_nombre": entidad.nombre or entidad.id_externo,
    }


def detectar_oportunidades_grupo(filas):
    """`filas`: la salida tal cual de kpi.comparar_entidades() --
    lista de {entidad, kpis, es_mejor, es_peor} de entidades del MISMO
    nivel (todas campañas, o todas conjuntos, o todos anuncios).
    Devuelve una lista de oportunidades detectadas comparando cada
    entidad contra el promedio del propio grupo. Nunca compara contra
    un valor externo, historico de otra empresa, ni inventado."""
    if not filas:
        return []

    promedio_ctr = _promedio([f["kpis"]["ctr"] for f in filas if f["kpis"].get("ctr") is not None])
    promedio_cpm = _promedio([f["kpis"]["cpm"] for f in filas if f["kpis"].get("cpm") is not None])
    promedio_costo = _promedio([f["kpis"]["costo_por_resultado"] for f in filas if f["kpis"].get("costo_por_resultado") is not None])
    promedio_spend = _promedio([f["kpis"]["spend"] for f in filas if f["kpis"].get("spend") is not None])
    promedio_resultados = _promedio([f["kpis"]["resultados"] for f in filas if f["kpis"].get("resultados") is not None])

    oportunidades = []
    for fila in filas:
        entidad, kpis = fila["entidad"], fila["kpis"]

        ctr = kpis.get("ctr")
        if ctr is not None and promedio_ctr:
            diff = (ctr - promedio_ctr) / promedio_ctr
            nivel = _nivel_por_diferencia(diff, UMBRAL_CTR_MEDIO, UMBRAL_CTR_ALTO)
            if nivel:
                oportunidades.append(_oportunidad(
                    "ctr_alto", nivel, entidad,
                    f"CTR de {ctr}% es {round(diff * 100)}% superior al promedio del grupo ({round(promedio_ctr, 2)}%).",
                    ctr,
                ))
            diff_neg = (promedio_ctr - ctr) / promedio_ctr
            nivel_neg = _nivel_por_diferencia(diff_neg, UMBRAL_CTR_MEDIO, UMBRAL_CTR_ALTO)
            if nivel_neg:
                oportunidades.append(_oportunidad(
                    "ctr_bajo", nivel_neg, entidad,
                    f"CTR de {ctr}% es {round(diff_neg * 100)}% inferior al promedio del grupo ({round(promedio_ctr, 2)}%).",
                    ctr,
                ))

        cpm = kpis.get("cpm")
        if cpm is not None and promedio_cpm:
            diff = (promedio_cpm - cpm) / promedio_cpm
            nivel = _nivel_por_diferencia(diff, UMBRAL_CPM_MEDIO, UMBRAL_CPM_ALTO)
            if nivel:
                oportunidades.append(_oportunidad(
                    "cpm_bajo", nivel, entidad,
                    f"CPM de {cpm} es {round(diff * 100)}% inferior al promedio del grupo ({round(promedio_cpm, 2)}).",
                    cpm,
                ))

        costo = kpis.get("costo_por_resultado")
        if costo is not None and promedio_costo:
            diff = (promedio_costo - costo) / promedio_costo
            nivel = _nivel_por_diferencia(diff, UMBRAL_COSTO_RESULTADO_MEDIO, UMBRAL_COSTO_RESULTADO_ALTO)
            if nivel:
                oportunidades.append(_oportunidad(
                    "costo_resultado_bajo", nivel, entidad,
                    f"Costo por resultado de {costo} es {round(diff * 100)}% inferior al promedio del grupo ({round(promedio_costo, 2)}).",
                    costo,
                ))
                # tambien es candidata a "buen rendimiento, poco presupuesto"
                # si ademas invierte menos que el promedio del grupo.
                spend = kpis.get("spend")
                if spend is not None and promedio_spend and spend < promedio_spend:
                    oportunidades.append(_oportunidad(
                        "buen_rendimiento_poco_presupuesto", nivel, entidad,
                        f"Costo por resultado {round(diff * 100)}% mejor que el promedio del grupo, con una inversión por debajo del promedio ({spend} vs {round(promedio_spend, 2)}).",
                        spend,
                    ))
            diff_neg = (costo - promedio_costo) / promedio_costo
            nivel_neg = _nivel_por_diferencia(diff_neg, UMBRAL_COSTO_RESULTADO_MEDIO, UMBRAL_COSTO_RESULTADO_ALTO)
            if nivel_neg:
                oportunidades.append(_oportunidad(
                    "costo_resultado_alto", nivel_neg, entidad,
                    f"Costo por resultado de {costo} es {round(diff_neg * 100)}% superior al promedio del grupo ({round(promedio_costo, 2)}).",
                    costo,
                ))

        frecuencia = kpis.get("frequency")
        if frecuencia is not None:
            if frecuencia >= FRECUENCIA_ELEVADA_ALTO:
                oportunidades.append(_oportunidad(
                    "frecuencia_elevada", "alto", entidad,
                    f"Frecuencia de {frecuencia} -- alto riesgo de fatiga publicitaria.", frecuencia,
                ))
            elif frecuencia >= FRECUENCIA_ELEVADA_MEDIO:
                oportunidades.append(_oportunidad(
                    "frecuencia_elevada", "medio", entidad,
                    f"Frecuencia de {frecuencia} -- vigilar posible fatiga publicitaria.", frecuencia,
                ))

        spend = kpis.get("spend")
        resultados = kpis.get("resultados")
        if spend is not None and promedio_spend:
            diff_spend = (spend - promedio_spend) / promedio_spend
            if diff_spend >= UMBRAL_GASTO_ALTO:
                if resultados is None:
                    oportunidades.append(_oportunidad(
                        "gasto_alto_sin_resultados", "alto", entidad,
                        f"Gasto de {spend} ({round(diff_spend * 100)}% sobre el promedio del grupo) sin ninguna conversión registrada.",
                        spend,
                    ))
                elif promedio_resultados:
                    diff_resultado = (resultados - promedio_resultados) / promedio_resultados
                    if diff_resultado < 0:
                        oportunidades.append(_oportunidad(
                            "gasto_alto_bajo_resultado", "medio", entidad,
                            f"Gasto {round(diff_spend * 100)}% sobre el promedio, pero resultados {round(abs(diff_resultado) * 100)}% por debajo del promedio del grupo.",
                            spend,
                        ))

    return oportunidades
