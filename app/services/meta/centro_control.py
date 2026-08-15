"""Centro de Control de Pauta (Paso 14).

Convierte en UNA sola pantalla lo que ya existe en Datos de Meta -- este
archivo NO detecta ninguna señal nueva ni vuelve a calcular ningun KPI,
es una capa de composicion sobre lo ya construido:

  - app/services/meta/optimizacion.py (Paso 11): construir_centro_optimizacion()
    se llama UNA sola vez aqui y ya entrega comparacion de campañas (con
    es_mejor/es_peor/veredicto_temporal), oportunidades, cambios
    temporales, fatiga, recomendaciones priorizadas (formato QUE PASO/
    POR QUE IMPORTA/EVIDENCIA/RECOMENDACION/RIESGO), diagnostico de
    cuenta y ritmo de presupuesto -- este archivo solo reparte ese
    mismo resultado entre las secciones de la pantalla (alertas vs.
    oportunidades, mejor/peor, estado general).
  - app/services/meta/kpi.py (Paso 3): comparar_periodos()/serie_diaria()
    para las tarjetas de KPI principales y los graficos de evolucion.
  - app/services/presupuestos.py (Paso 2): calcular_resumen_presupuesto()
    (via optimizacion.py, nunca se recalcula aqui).
  - app/services/meta/acciones.py (Paso 12): listar_acciones_empresa()
    solo para CONTAR cuantas estan pendientes de aprobacion -- esta
    pantalla nunca aprueba, rechaza ni ejecuta ninguna accion.
  - app/services/meta/optimizacion.py::construir_prioridades_para_claude()
    (Paso 11, ya usado por el Estratega IA) para el bloque "Claude
    recomienda" (ver nota abajo).

Nota sobre "Claude recomienda" (Paso 14, punto 9): esta pantalla NUNCA
llama a la API de Anthropic en cada carga -- hacerlo gastaria una
llamada real de IA (y el limite diario de mensajes del Paso 10) solo
por abrir un dashboard, y el punto 20 del enunciado pide explicitamente
evitar consultas innecesarias. En su lugar se muestra la recomendacion
#1 de `paquete_opt["recomendaciones"]` (la MISMA lista ya priorizada
que optimizacion.py::construir_prioridades_para_claude() convierte a
texto para el Estratega IA -- aqui se usa la version ESTRUCTURADA
directamente, sin llamar a esa funcion de nuevo ni repetir
construir_centro_optimizacion(), para poder ofrecer el boton
"Preparar acción" con el entidad_id real), con un enlace a Chat de
Pauta (Paso 13) para pedirle a Claude un analisis conversacional de
verdad cuando el usuario lo solicite explicitamente.

Nunca llama a la Graph API ni escribe nada en Meta -- es una capa de
LECTURA, igual que optimizacion.py e inteligencia.py.
"""

from app.services.meta.optimizacion import (
    UMBRAL_DIAS_MINIMOS_RECOMENDACION,
    construir_centro_optimizacion,
    evaluar_ritmo_presupuesto,
    evaluar_suficiencia_datos,
)
from app.services.meta.kpi import TIPOS_COMPARACION_PERIODO

# Tipos que ya devuelve construir_centro_optimizacion()["recomendaciones"]
# (oportunidades.py + inteligencia.py) que representan una señal
# POSITIVA -- algo que esta funcionando bien y podria escalarse. El
# resto de los tipos se muestran como "alertas" (Paso 14, punto 7 vs.
# punto 8). Ninguna deteccion nueva: solo se reparte lo que el motor ya
# clasifico entre las dos secciones de la pantalla.
TIPOS_OPORTUNIDAD_POSITIVA = {
    "ctr_alto", "cpm_bajo", "costo_resultado_bajo",
    "buen_rendimiento_poco_presupuesto", "mejora_significativa",
}

# CRITICO/ALTO -> "URGENTE", MEDIO -> "ATENCIÓN", BAJO/INFORMATIVO ->
# "INFORMATIVO" (Paso 16, punto 12) -- un re-etiquetado de la escala de
# 5 niveles del Paso 11 para la vista compacta del Centro de Control,
# nunca una escala de severidad nueva. El texto (no solo el color)
# distingue cada nivel para accesibilidad (Paso 16, punto 22).
ETIQUETAS_SEVERIDAD_ALERTA = {
    "critico": "URGENTE", "alto": "URGENTE", "medio": "ATENCIÓN", "bajo": "INFORMATIVO", "informativo": "INFORMATIVO",
}

# Cuantas alertas del MISMO tipo se muestran individualmente antes de
# agruparlas en una sola tarjeta (Paso 16, punto 12: "no mostrar 20
# alertas iguales") -- ninguna deteccion nueva, solo una regla de
# presentacion sobre `recomendaciones` (que optimizacion.py ya
# devuelve ordenada por prioridad).
UMBRAL_AGRUPAR_ALERTAS = 4

KPIS_TARJETAS_PRINCIPALES = ["spend", "resultados", "costo_por_resultado", "reach", "impressions", "roas"]

KPIS_MEJOR_PEOR_DISPONIBLES = ["costo_por_resultado", "ctr", "cpc", "roas"]

# Explicaciones en lenguaje sencillo (Paso 14, punto 17 / Paso 16,
# punto 11) -- solo para los KPI que esta pantalla realmente muestra.
EXPLICACIONES_KPI = {
    "spend": "Cuánto has invertido en total en el período seleccionado.",
    "resultados": "Cuántas conversiones (compras, mensajes, registros, etc.) generaron tus anuncios.",
    "costo_por_resultado": "Cuánto te cuesta, en promedio, conseguir cada resultado.",
    "reach": "Cuántas personas distintas vieron al menos un anuncio.",
    "impressions": "Cuántas veces se mostraron tus anuncios en total (una persona puede verlo más de una vez).",
    "ctr": "Porcentaje de personas que hicieron clic después de ver el anuncio.",
    "cpc": "Cuánto pagaste, en promedio, por cada clic.",
    "cpm": "Cuánto cuesta mostrar el anuncio 1.000 veces.",
    "roas": "Cuánto valor generaste por cada colón/dólar invertido.",
}

# Etiquetas "para niños" (Paso 16, punto 10): reemplazan el nombre
# técnico como TÍTULO principal de la tarjeta -- el acrónimo (CTR/CPC/
# CPM/ROAS) queda disponible atrás de "Ver detalle técnico" en vez de
# ser lo primero que el usuario lee. Los KPI que ya tienen un nombre en
# español sencillo (spend/resultados/costo_por_resultado/reach/
# impressions) no necesitan una entrada aquí -- se usa ETIQUETAS_KPI tal
# cual.
ETIQUETAS_KPI_SENCILLAS = {
    "ctr": "Personas que hicieron clic",
    "cpc": "Costo por cada clic",
    "cpm": "Costo por cada 1.000 personas que vieron tu anuncio",
    "roas": "Retorno por cada colón invertido",
    "frequency": "Veces que la misma persona vio tu anuncio",
}


def _mejor_peor_por_kpi(comparacion, dias_por_entidad, moneda, kpi_clave):
    """(mejor_o_None, peor_o_None) segun `kpi_clave`, reutilizando las
    MISMAS filas que construir_centro_optimizacion() ya calculo -- sin
    ninguna consulta nueva, ya que cada fila trae todos los KPI. Ordena
    en Python. Nunca marca mejor/peor sin volumen suficiente (Paso 14,
    punto 6, "IMPORTANTE"): una entidad con datos insuficientes queda
    fuera de la comparacion en vez de arriesgarse a etiquetarla como
    "peor" solo por tener pocos datos."""
    from app.services.meta.kpi import METRICAS_MENOR_ES_MEJOR

    mayor_es_mejor = kpi_clave not in METRICAS_MENOR_ES_MEJOR
    candidatas = []
    for fila in comparacion:
        valor = fila["kpis"].get(kpi_clave)
        if valor is None:
            continue
        dias = dias_por_entidad.get(fila["entidad"].id, 0)
        suficiente, _motivo = evaluar_suficiencia_datos(dias, fila["kpis"], moneda)
        if not suficiente:
            continue
        candidatas.append({"entidad": fila["entidad"], "valor": valor})

    if not candidatas:
        return None, None
    candidatas.sort(key=lambda c: c["valor"], reverse=mayor_es_mejor)
    mejor = candidatas[0]
    peor = candidatas[-1] if len(candidatas) > 1 else None
    return mejor, peor


def _clasificar_estado_general(diagnostico_cuenta, cambios_temporales):
    """BUEN_RENDIMIENTO/NECESITA_ATENCION/DATOS_INSUFICIENTES (Paso 14,
    punto 4) -- reutiliza EXCLUSIVAMENTE la clasificacion BUENO/ATENCION/
    CRITICO/SIN_DATOS que inteligencia.py ya calculo para el area
    "costo_por_resultado" (el KPI mas directamente accionable, mismo
    criterio que usa detectar_cambios_temporales), mas el conteo de
    campañas con deterioro real que optimizacion.py ya detecto. Ninguna
    clasificacion ni umbral nuevo: solo combina dos conclusiones que el
    motor existente ya calculo."""
    mensaje_sin_datos = "No hay suficiente información para determinar el rendimiento."
    if diagnostico_cuenta is None or diagnostico_cuenta["dias_con_datos"] < UMBRAL_DIAS_MINIMOS_RECOMENDACION:
        return {"estado": "datos_insuficientes", "titulo": "DATOS INSUFICIENTES", "mensaje": mensaje_sin_datos}

    area_costo = diagnostico_cuenta["areas"].get("costo_por_resultado", {})
    clasificacion = area_costo.get("clasificacion", "sin_datos")
    deterioros = [c for c in cambios_temporales if c["tipo"] == "deterioro"]

    if clasificacion == "sin_datos":
        return {"estado": "datos_insuficientes", "titulo": "DATOS INSUFICIENTES", "mensaje": mensaje_sin_datos}

    if clasificacion in ("critico", "atencion") or deterioros:
        partes = []
        if clasificacion in ("critico", "atencion") and area_costo.get("variacion_pct") is not None:
            partes.append(f"El costo por resultado subió {abs(area_costo['variacion_pct'])}% frente al período anterior")
        if deterioros:
            plural = "campañas presentan" if len(deterioros) != 1 else "campaña presenta"
            frase = f"{len(deterioros)} {plural} deterioro significativo"
            partes.append(frase if not partes else frase[0].lower() + frase[1:])
        mensaje = (" y ".join(partes) + ".") if partes else "Se detectaron señales que requieren revisión."

        # RENDIMIENTO BAJO vs. NECESITA ATENCIÓN (Paso 16, punto 4: 4
        # niveles, no 3) -- la MISMA clasificacion critico/atencion que
        # inteligencia.py ya calculo, mas cuantas campañas ya cayeron en
        # deterioro real, deciden cual de los dos, nunca un umbral nuevo:
        # "critico" en la cuenta completa, o 2+ campañas en deterioro, es
        # mas severo que una sola señal aislada.
        if clasificacion == "critico" or len(deterioros) >= 2:
            return {"estado": "rendimiento_bajo", "titulo": "RENDIMIENTO BAJO", "mensaje": mensaje}
        return {"estado": "necesita_atencion", "titulo": "NECESITA ATENCIÓN", "mensaje": mensaje}

    return {
        "estado": "buen_rendimiento",
        "titulo": "BUEN RENDIMIENTO",
        "mensaje": "Las campañas están generando resultados a un costo estable o menor que el período anterior.",
    }


_DESCRIPCION_TIPO_ALERTA = {
    "costo_resultado_alto": "costo por resultado elevado",
    "ctr_bajo": "CTR por debajo del promedio",
    "frecuencia_elevada": "frecuencia elevada",
    "gasto_alto_sin_resultados": "gasto alto sin resultados",
    "gasto_alto_bajo_resultado": "gasto alto con resultados bajos",
    "deterioro": "deterioro frente al período anterior",
    "fatiga": "señales compatibles con fatiga",
}


def _agrupar_alertas(alertas):
    """Agrupa alertas del MISMO tipo cuando hay mas de
    UMBRAL_AGRUPAR_ALERTAS (Paso 16, punto 12: "no mostrar 20 alertas
    iguales. Agrupar cuando sea posible") -- nunca oculta informacion:
    el grupo conserva la lista completa en "items" para expandir. Los
    tipos con pocas alertas se muestran individuales, sin envolver."""
    por_tipo = {}
    for a in alertas:
        por_tipo.setdefault(a["tipo"], []).append(a)

    resultado = []
    for tipo, items in por_tipo.items():
        if len(items) <= UMBRAL_AGRUPAR_ALERTAS:
            resultado.extend(items)
            continue
        prioridad_grupo = min(items, key=lambda i: ["critico", "alto", "medio", "bajo", "informativo"].index(i["prioridad"]))["prioridad"]
        descripcion = _DESCRIPCION_TIPO_ALERTA.get(tipo, tipo.replace("_", " "))
        resultado.append({
            "agrupado": True,
            "tipo": tipo,
            "prioridad": prioridad_grupo,
            "severidad_etiqueta": ETIQUETAS_SEVERIDAD_ALERTA.get(prioridad_grupo, "INFORMATIVO"),
            "entidad_nombre": f"{len(items)} campañas",
            "que_paso": f"{len(items)} campañas con {descripcion}.",
            "recomendacion": "Revisar cada una para decidir si necesitan la misma acción.",
            "items": items,
        })

    orden = {"critico": 0, "alto": 1, "medio": 2, "bajo": 3, "informativo": 4}
    resultado.sort(key=lambda r: orden.get(r["prioridad"], 99))
    return resultado


def _construir_presupuesto_centro_control(comparacion, analisis_presupuesto):
    """Presupuesto ESTRATEGICO (PresupuestoPauta, capital que el
    cliente define) + presupuesto DIARIO tal como Meta lo reporta
    (Paso 14, punto 10) -- este segundo dato NUNCA se recalcula: es la
    suma de `presupuesto_diario` ya sincronizado en Meta (atributos de
    cada campaña activa, ver campanas_service.py), tomado de las
    mismas filas que construir_centro_optimizacion() ya cargo, sin
    ninguna consulta adicional."""
    presupuestos = analisis_presupuesto["presupuestos"] if analisis_presupuesto else []
    principal = next((r for r in presupuestos if r["presupuesto"].tipo == "estrategico"), None)
    ritmo = evaluar_ritmo_presupuesto(principal) if principal else None

    valores_diarios = [
        fila["entidad"].atributos.get("presupuesto_diario")
        for fila in comparacion
        if fila["entidad"].estado == "ACTIVE" and (fila["entidad"].atributos or {}).get("presupuesto_diario") is not None
    ]
    presupuesto_diario_meta = round(sum(valores_diarios), 2) if valores_diarios else None

    return {
        "principal": principal,
        "ritmo": ritmo,
        "presupuesto_diario_meta": presupuesto_diario_meta,
        "todos": presupuestos,
    }


def construir_centro_control(empresa_id, cuenta_id, fecha_inicio, fecha_fin, tipo_comparacion="periodo_anterior", kpi_mejor_peor="costo_por_resultado"):
    """(paquete_o_None, error_o_None). Punto de entrada UNICO del Paso
    14 -- arma toda la pantalla a partir de UNA sola llamada a
    construir_centro_optimizacion() (Paso 11) mas los KPI principales/
    serie diaria (Paso 3) y el conteo de acciones pendientes (Paso 12).
    Requiere `cuenta_id` (igual que Optimizacion, Paso 11): el motor de
    comparacion de campañas opera sobre UNA cuenta publicitaria a la
    vez, nunca se inventa una agregacion multi-cuenta que ese motor no
    soporta."""
    from app.services.meta.kpi import comparar_periodos, resolver_entidades_para_kpi, serie_diaria

    if kpi_mejor_peor not in KPIS_MEJOR_PEOR_DISPONIBLES:
        kpi_mejor_peor = "costo_por_resultado"
    if tipo_comparacion not in TIPOS_COMPARACION_PERIODO:
        tipo_comparacion = "periodo_anterior"

    paquete_opt, error = construir_centro_optimizacion(empresa_id, cuenta_id, fecha_inicio, fecha_fin)
    if error:
        return None, error

    diagnostico_cuenta = paquete_opt["diagnostico_cuenta"]
    entidad_ids, _error_entidad = resolver_entidades_para_kpi(empresa_id, cuenta_id)

    if diagnostico_cuenta is not None and tipo_comparacion == "periodo_anterior":
        # Reutiliza la MISMA comparacion de periodos que
        # construir_diagnostico_cuenta() ya calculo -- nunca se repite
        # la consulta cuando el tipo de comparacion pedido es el que
        # ese motor ya usa por defecto.
        comparacion_periodos = diagnostico_cuenta["comparacion_periodos"]
    else:
        comparacion_periodos = comparar_periodos(empresa_id, entidad_ids, fecha_inicio, fecha_fin, tipo_comparacion=tipo_comparacion)

    serie = serie_diaria(empresa_id, entidad_ids, fecha_inicio, fecha_fin)

    estado_general = _clasificar_estado_general(diagnostico_cuenta, paquete_opt["cambios_temporales"])

    recomendaciones = paquete_opt["recomendaciones"]
    oportunidades = [r for r in recomendaciones if r["tipo"] in TIPOS_OPORTUNIDAD_POSITIVA]
    alertas_individuales = [r for r in recomendaciones if r["tipo"] not in TIPOS_OPORTUNIDAD_POSITIVA]
    for a in alertas_individuales:
        a["severidad_etiqueta"] = ETIQUETAS_SEVERIDAD_ALERTA.get(a["prioridad"], "INFORMATIVO")
    alertas = _agrupar_alertas(alertas_individuales)

    mejor, peor = _mejor_peor_por_kpi(paquete_opt["comparacion"], paquete_opt["dias_por_entidad"], paquete_opt["moneda"], kpi_mejor_peor)

    recomendacion_claude = recomendaciones[0] if recomendaciones else None

    presupuesto = _construir_presupuesto_centro_control(paquete_opt["comparacion"], paquete_opt["analisis_presupuesto"])

    return {
        "cuenta_id": cuenta_id,
        "moneda": paquete_opt["moneda"],
        "kpis": comparacion_periodos["periodo_actual"]["kpis"],
        "comparacion_periodos": comparacion_periodos,
        "tipo_comparacion": tipo_comparacion,
        "serie_diaria": serie,
        "estado_general": estado_general,
        "campanas": paquete_opt["comparacion"],
        "kpi_mejor_peor": kpi_mejor_peor,
        "mejor": mejor,
        "peor": peor,
        "alertas": alertas,
        "oportunidades": oportunidades,
        "recomendacion_claude": recomendacion_claude,
        "presupuesto": presupuesto,
        "diagnostico_cuenta": diagnostico_cuenta,
        "dias_con_datos": diagnostico_cuenta["dias_con_datos"] if diagnostico_cuenta else 0,
    }, None
