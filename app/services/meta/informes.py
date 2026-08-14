"""Informes ejecutivos de pauta (Paso 15).

Reutiliza INTEGRAMENTE lo ya construido -- este archivo NUNCA vuelve a
calcular un KPI ni a detectar una oportunidad:
  - app/services/meta/centro_control.py (Paso 14), que a su vez
    reutiliza construir_centro_optimizacion() (Paso 11) en una unica
    llamada: KPI principales, comparacion de periodos, estado general,
    campañas (con mejor/peor/veredicto temporal), alertas,
    oportunidades, presupuesto y diagnostico de cuenta.
  - app/services/meta/analisis.py::analizar_audiencias() (Paso 5) para
    la seccion de audiencias.

Los 5 TIPOS de informe (Paso 15, punto 1) NUNCA disparan un calculo
distinto -- todos comparten el MISMO contenido calculado una sola vez
(`construir_contenido_informe`); el tipo solo determina que SECCIONES
de ese contenido se incluyen al mostrar/exportar (ver
SECCIONES_POR_TIPO).

Persistencia como SNAPSHOT (Paso 15, punto 19): `InformePauta.contenido`
guarda el resultado ya calculado en el momento de generarlo -- un
informe historico nunca cambia si despues se sincronizan mas datos de
Meta, igual que un reporte financiero no se recalcula solo. El PDF
(informes_pdf.py) se genera bajo demanda a partir de este mismo
`contenido`, nunca se pre-genera ni se sube a Storage.

Nota sobre serializacion: las funciones `_serializar_*` de este archivo
tienen el MISMO proposito que las de app/modules/datos_meta/routes.py
(convertir objetos ORM/fechas a JSON) -- se mantienen locales a
proposito, para que este servicio nunca importe de la capa de rutas
(evita una dependencia invertida service -> route). El calculo real
que serializan viene siempre de kpi.py/inteligencia.py/optimizacion.py/
centro_control.py, nunca de aqui.
"""

from datetime import datetime, timezone

from app.models import TIPOS_COMPARACION_INFORME, TIPOS_INFORME_PAUTA

SECCIONES_POR_TIPO = {
    "rendimiento": ["resumen", "kpis", "comparacion", "graficos"],
    "campanas": ["resumen", "kpis", "campanas", "graficos"],
    "audiencias": ["resumen", "kpis", "audiencias", "graficos"],
    "optimizacion": ["resumen", "diagnostico", "oportunidades", "recomendaciones", "plan_accion"],
    "ejecutivo": [
        "resumen", "kpis", "comparacion", "campanas", "audiencias",
        "diagnostico", "oportunidades", "recomendaciones", "plan_accion", "graficos",
    ],
}

TITULOS_TIPO = {
    "rendimiento": "Informe de Rendimiento",
    "campanas": "Informe de Campañas",
    "audiencias": "Informe de Audiencias",
    "optimizacion": "Informe de Optimización",
    "ejecutivo": "Informe Ejecutivo",
}

ETIQUETAS_PRIORIDAD_PLAN = {"critico": "ALTA", "alto": "ALTA", "medio": "MEDIA", "bajo": "BAJA", "informativo": "BAJA"}

# Campos que se muestran en MODO CLIENTE (Paso 15, punto 14) -- el
# resto de las secciones (diagnostico tecnico, plan de accion,
# alertas/oportunidades con evidencia detallada) solo se muestran en
# modo interno. Ninguna seccion nueva: es un subconjunto del mismo
# `contenido`.
SECCIONES_MODO_CLIENTE = {"resumen", "kpis", "comparacion", "campanas", "graficos"}


# --- Serializacion (JSON-safe, ver nota del docstring) --------------------------------

def _serializar_entidad_kpi(fila):
    e = fila["entidad"]
    return {
        "id": e.id,
        "nombre": e.nombre or e.id_externo,
        "estado": e.estado,
        "objetivo": (e.atributos or {}).get("objetivo"),
        "kpis": fila["kpis"],
        "es_mejor": fila["es_mejor"],
        "es_peor": fila["es_peor"],
        "veredicto_temporal": fila.get("veredicto_temporal"),
    }


def _serializar_segmento_audiencia(fila):
    e = fila["entidad"]
    return {
        "id": e.id,
        "nombre": e.nombre or e.id_externo,
        "campana_nombre": fila.get("campana_nombre"),
        "kpis": fila["kpis"],
        "es_mejor": fila["es_mejor"],
        "es_peor": fila["es_peor"],
        "targeting": fila.get("targeting"),
    }


def _serializar_comparacion_periodos(comp):
    if comp is None:
        return None
    return {
        "periodo_actual": {
            "fecha_inicio": comp["periodo_actual"]["fecha_inicio"].isoformat(),
            "fecha_fin": comp["periodo_actual"]["fecha_fin"].isoformat(),
            "kpis": comp["periodo_actual"]["kpis"],
        },
        "periodo_anterior": {
            "fecha_inicio": comp["periodo_anterior"]["fecha_inicio"].isoformat(),
            "fecha_fin": comp["periodo_anterior"]["fecha_fin"].isoformat(),
            "kpis": comp["periodo_anterior"]["kpis"],
        },
        "variacion_porcentual": comp["variacion_porcentual"],
    }


def _serializar_diagnostico_cuenta(diag):
    if diag is None:
        return None
    return {
        "kpis": diag["kpis"],
        "areas": diag["areas"],
        "dias_con_datos": diag["dias_con_datos"],
        "cantidad_campanas": diag["cantidad_campanas"],
    }


def _serializar_resumen_presupuesto(r):
    if r is None:
        return None
    p = r["presupuesto"]
    return {
        "id": p.id, "nombre": p.nombre, "tipo": p.tipo, "monto": p.monto, "moneda": p.moneda,
        "fecha_inicio": r["fecha_inicio"].isoformat(), "fecha_fin": r["fecha_fin"].isoformat(),
        "gasto_real": r["gasto_real"], "disponible": r["disponible"],
        "porcentaje_usado": r["porcentaje_usado"], "excedido": r["excedido"],
    }


# --- Filtros opcionales (Paso 15, punto 2) ---------------------------------------------
#
# Solo acotan que se LISTA en las tablas de campañas/audiencias -- las
# oportunidades/alertas siguen calculandose sobre TODA la cuenta,
# porque oportunidades.py compara cada entidad contra el promedio de
# su propio grupo (filtrar el grupo despues de detectar cambiaria ese
# promedio y falsearia la comparacion).

def _normalizar_filtros(filtros):
    filtros = filtros or {}
    normalizado = {}
    for clave in ("campana_ids", "audiencia_ids"):
        valores = filtros.get(clave)
        if valores:
            try:
                normalizado[clave] = sorted({int(v) for v in valores})
            except (TypeError, ValueError):
                pass
    objetivo = (filtros.get("objetivo") or "").strip()
    if objetivo:
        normalizado["objetivo"] = objetivo
    return normalizado


def _filtrar_campanas(campanas, filtros):
    resultado = campanas
    if filtros.get("campana_ids"):
        ids = set(filtros["campana_ids"])
        resultado = [c for c in resultado if c["id"] in ids]
    if filtros.get("objetivo"):
        resultado = [c for c in resultado if c.get("objetivo") == filtros["objetivo"]]
    return resultado


def _filtrar_audiencias(segmentos, filtros):
    if filtros.get("audiencia_ids"):
        ids = set(filtros["audiencia_ids"])
        return [s for s in segmentos if s["id"] in ids]
    return segmentos


# --- Resumen ejecutivo (reglas, Paso 15 punto 4) ----------------------------------------

def _listar_nombres(nombres):
    if not nombres:
        return ""
    if len(nombres) == 1:
        return f"la campaña {nombres[0]}"
    if len(nombres) == 2:
        return f"las campañas {nombres[0]} y {nombres[1]}"
    return f"las campañas {', '.join(nombres[:-1])} y {nombres[-1]}"


def _construir_conclusion(estado_general, campanas):
    if estado_general["estado"] == "datos_insuficientes":
        return "El período contiene pocos resultados para realizar una comparación confiable."

    mejores = [c["nombre"] for c in campanas if c.get("veredicto_temporal") == "mejora_significativa"]
    peores = [c["nombre"] for c in campanas if c.get("veredicto_temporal") == "deterioro"]

    if estado_general["estado"] == "buen_rendimiento":
        base = "El rendimiento general mejoró"
        return f"{base}, principalmente por el comportamiento de {_listar_nombres(mejores)}." if mejores else f"{base} frente al período anterior."

    if estado_general["estado"] == "necesita_atencion":
        base = "El rendimiento general requiere atención"
        return f"{base}, principalmente por el comportamiento de {_listar_nombres(peores)}." if peores else f"{base} en este período."

    return estado_general["mensaje"]


def _construir_resumen(datos_cc, campanas):
    kpis = datos_cc["kpis"]
    comparacion_texto = None
    if datos_cc["comparacion_periodos"] is not None:
        variacion_costo = datos_cc["comparacion_periodos"]["variacion_porcentual"].get("costo_por_resultado")
        if variacion_costo is not None:
            # costo_por_resultado: MENOR es mejor (mismo criterio de
            # kpi.METRICAS_MENOR_ES_MEJOR usado en todo el resto de la
            # plataforma) -- una disminucion aqui es "mejoró", nunca "bajó".
            verbo = "mejoró" if variacion_costo < 0 else "empeoró"
            comparacion_texto = f"Comparado con el período de referencia, el costo por resultado {verbo} {abs(variacion_costo)}%."

    return {
        "inversion": kpis.get("spend"),
        "resultados": kpis.get("resultados"),
        "costo_por_resultado": kpis.get("costo_por_resultado"),
        "moneda": datos_cc["moneda"],
        "comparacion_texto": comparacion_texto,
        "conclusion": _construir_conclusion(datos_cc["estado_general"], campanas),
    }


# --- Diagnostico narrativo (Paso 15, punto 9) -------------------------------------------

def _construir_diagnostico_narrativo(diagnostico_cuenta, campanas, alertas):
    from app.services.meta.kpi import ETIQUETAS_KPI

    if diagnostico_cuenta is None:
        return {"que_funciono": [], "que_empeoro": [], "que_cambio": [], "que_requiere_atencion": []}

    que_funciono = [
        f"{ETIQUETAS_KPI.get(clave, clave)} se mantuvo en buen nivel ({area['valor']})."
        for clave, area in diagnostico_cuenta["areas"].items() if area["clasificacion"] == "bueno" and area["valor"] is not None
    ]
    que_funciono += [f"{c['nombre']}: mejora significativa frente al período anterior." for c in campanas if c.get("veredicto_temporal") == "mejora_significativa"]

    que_empeoro = [
        f"{ETIQUETAS_KPI.get(clave, clave)} empeoró {abs(area['variacion_pct'])}% frente al período anterior."
        for clave, area in diagnostico_cuenta["areas"].items() if area["clasificacion"] in ("atencion", "critico") and area["variacion_pct"] is not None
    ]
    que_empeoro += [f"{c['nombre']}: deterioro significativo frente al período anterior." for c in campanas if c.get("veredicto_temporal") == "deterioro"]

    que_cambio = [f"{c['nombre']}: {c['veredicto_temporal'].replace('_', ' ')}." for c in campanas if c.get("veredicto_temporal") in ("mejora_significativa", "deterioro")]

    que_requiere_atencion = [f"{a['entidad_nombre']}: {a['que_paso']}" for a in alertas if a["prioridad"] in ("critico", "alto")]

    return {"que_funciono": que_funciono, "que_empeoro": que_empeoro, "que_cambio": que_cambio, "que_requiere_atencion": que_requiere_atencion}


# --- Plan de accion (Paso 15, punto 13) --------------------------------------------------

def _construir_plan_accion(alertas, oportunidades):
    plan = []
    for r in (alertas + oportunidades):
        plan.append({
            "prioridad": r["prioridad"],
            "prioridad_etiqueta": ETIQUETAS_PRIORIDAD_PLAN.get(r["prioridad"], "BAJA"),
            "accion": r["recomendacion"],
            "motivo": r["que_paso"],
            "responsable": "Por asignar",
            "estado": "Pendiente",
            "entidad_id": r.get("entidad_id"),
            "entidad_nombre": r.get("entidad_nombre"),
        })
    orden = {"critico": 0, "alto": 1, "medio": 2, "bajo": 3, "informativo": 4}
    plan.sort(key=lambda p: orden.get(p["prioridad"], 99))
    return plan


# --- Resumen generado por Claude (Paso 15, punto 12) --------------------------------------

REGLAS_SISTEMA_RESUMEN = """Eres un analista de marketing digital escribiendo el RESUMEN EJECUTIVO de un informe de pauta para la empresa "{empresa_nombre}".

REGLAS OBLIGATORIAS:
1. Escribe SOLO el resumen ejecutivo: 3 a 5 oraciones en español, en tono profesional y directo.
2. Usa EXCLUSIVAMENTE los datos reales del CONTEXTO de abajo -- nunca inventes cifras, campañas ni resultados que no aparezcan ahí.
3. Si el contexto indica que los datos son insuficientes o el período tiene poco volumen, dilo explícitamente en el resumen -- nunca redactes una conclusión que los datos no sostengan.
4. No repitas literalmente la lista de KPI -- interpreta lo que significan para el negocio.
5. No propongas ejecutar ninguna acción en Meta; como mucho, sugiere qué revisar.

CONTEXTO (datos reales de este informe):
{contexto}
"""


def _formatear_contexto_resumen(datos_cc, campanas, audiencias, diagnostico_narrativo, oportunidades):
    from app.services.meta.kpi import ETIQUETAS_KPI

    partes = [f"Estado general: {datos_cc['estado_general']['titulo']} — {datos_cc['estado_general']['mensaje']}"]
    partes.append("KPI del período:")
    for clave, etiqueta in ETIQUETAS_KPI.items():
        if clave in datos_cc["kpis"] and datos_cc["kpis"][clave] is not None:
            partes.append(f"  - {etiqueta}: {datos_cc['kpis'][clave]}")

    partes.append(f"\nCampañas analizadas ({len(campanas)}):")
    for c in campanas[:10]:
        marca = " [mejora significativa]" if c.get("veredicto_temporal") == "mejora_significativa" else (" [deterioro]" if c.get("veredicto_temporal") == "deterioro" else "")
        partes.append(f"  - {c['nombre']}{marca}: gasto {c['kpis'].get('spend')}, costo por resultado {c['kpis'].get('costo_por_resultado')}")

    if audiencias:
        partes.append(f"\nAudiencias analizadas ({len(audiencias['segmentos'])}):")
        for s in audiencias["segmentos"][:10]:
            partes.append(f"  - {s['nombre']}: costo por resultado {s['kpis'].get('costo_por_resultado')}")

    partes.append(f"\nQué funcionó: {'; '.join(diagnostico_narrativo['que_funciono']) or '(nada destacable)'}")
    partes.append(f"Qué empeoró: {'; '.join(diagnostico_narrativo['que_empeoro']) or '(nada destacable)'}")

    partes.append(f"\nOportunidades detectadas ({len(oportunidades)}):")
    for o in oportunidades[:6]:
        partes.append(f"  - {o['entidad_nombre']}: {o['que_paso']}")

    return "\n".join(partes)


def generar_resumen_con_claude(empresa, datos_cc, campanas, audiencias, diagnostico_narrativo, oportunidades):
    """(texto_o_None, error_o_None). Llamada UNICA a la API de
    Anthropic (via app/services/ia.py, la misma capa de modelo
    intercambiable del Paso 10) al CREAR el informe -- nunca se repite
    al verlo despues, porque el resultado queda guardado en
    `contenido['resumen']['conclusion']` como parte del snapshot."""
    from app.services.ia import generar_respuesta, ia_configurada

    if not ia_configurada():
        return None, "El asistente de IA no está configurado en este entorno."

    contexto = _formatear_contexto_resumen(datos_cc, campanas, audiencias, diagnostico_narrativo, oportunidades)
    system = REGLAS_SISTEMA_RESUMEN.format(empresa_nombre=empresa.nombre, contexto=contexto)
    texto, _uso, error = generar_respuesta([{"role": "user", "content": "Genera el resumen ejecutivo de este informe."}], system=system)
    if error:
        return None, error
    return texto, None


# --- Construccion del contenido (punto de entrada compartido por los 5 tipos) -----------

def construir_contenido_informe(empresa, cuenta_id, tipo, fecha_inicio, fecha_fin, tipo_comparacion, filtros):
    """(contenido_o_None, error_o_None). Arma el contenido COMPLETO
    (todas las secciones posibles) reutilizando centro_control.py y
    analisis.py -- el `tipo` de informe NO cambia este calculo, solo se
    usa despues para decidir que secciones mostrar/exportar (ver
    SECCIONES_POR_TIPO)."""
    from app.services.meta.centro_control import construir_centro_control
    from app.services.meta.analisis import analizar_audiencias
    from app.services.meta.kpi import CLAVES_KPI, ETIQUETAS_KPI
    from app.services.meta.centro_control import EXPLICACIONES_KPI

    tipo_comparacion_calculo = "periodo_anterior" if tipo_comparacion == "sin_comparacion" else tipo_comparacion
    datos_cc, error = construir_centro_control(empresa.id, cuenta_id, fecha_inicio, fecha_fin, tipo_comparacion=tipo_comparacion_calculo)
    if error:
        return None, error

    # `campanas_todas` (sin el filtro opcional) se usa para el resumen
    # y el diagnostico narrativo -- deben reflejar la cuenta completa,
    # igual que alertas/oportunidades (ver nota arriba). `campanas`
    # (filtrada) es lo que se LISTA en la tabla del informe.
    campanas_todas = [_serializar_entidad_kpi(f) for f in datos_cc["campanas"]]
    campanas = _filtrar_campanas(campanas_todas, filtros)
    mejores_campanas = [c for c in campanas if c["es_mejor"] or c.get("veredicto_temporal") == "mejora_significativa"]
    campanas_atencion = [c for c in campanas if c["es_peor"] or c.get("veredicto_temporal") == "deterioro"]

    paquete_audiencias, _error_audiencias = analizar_audiencias(empresa.id, cuenta_id, fecha_inicio, fecha_fin)
    audiencias = None
    if paquete_audiencias and paquete_audiencias["segmentos"]:
        audiencias = {
            "segmentos": _filtrar_audiencias([_serializar_segmento_audiencia(f) for f in paquete_audiencias["segmentos"]], filtros),
            "oportunidades": paquete_audiencias["oportunidades"],
        }

    diagnostico_narrativo = _construir_diagnostico_narrativo(datos_cc["diagnostico_cuenta"], campanas_todas, datos_cc["alertas"])
    plan_accion = _construir_plan_accion(datos_cc["alertas"], datos_cc["oportunidades"])
    resumen = _construir_resumen(datos_cc, campanas_todas)

    recomendaciones_texto = [
        f"{r['entidad_nombre']}: {r['recomendacion']}"
        for r in (datos_cc["alertas"] + datos_cc["oportunidades"])[:8]
    ]

    mostrar_comparacion = tipo_comparacion != "sin_comparacion"

    return {
        "tipo": tipo,
        "titulo": TITULOS_TIPO[tipo],
        "secciones": SECCIONES_POR_TIPO[tipo],
        "generado_en": datetime.now(timezone.utc).isoformat(),
        "moneda": datos_cc["moneda"],
        "resumen": resumen,
        "kpis": datos_cc["kpis"],
        "comparacion_periodos": _serializar_comparacion_periodos(datos_cc["comparacion_periodos"]) if mostrar_comparacion else None,
        "tipo_comparacion": tipo_comparacion,
        "estado_general": datos_cc["estado_general"],
        "campanas": campanas,
        "mejores_campanas": mejores_campanas,
        "campanas_atencion": campanas_atencion,
        "audiencias": audiencias,
        "diagnostico": {**_serializar_diagnostico_cuenta(datos_cc["diagnostico_cuenta"]), **diagnostico_narrativo} if datos_cc["diagnostico_cuenta"] else diagnostico_narrativo,
        "oportunidades": datos_cc["oportunidades"],
        "recomendaciones": recomendaciones_texto,
        "plan_accion": plan_accion,
        "presupuesto": {
            "principal": _serializar_resumen_presupuesto(datos_cc["presupuesto"]["principal"]),
            "ritmo": datos_cc["presupuesto"]["ritmo"],
            "presupuesto_diario_meta": datos_cc["presupuesto"]["presupuesto_diario_meta"],
        },
        "serie_diaria": [{**d, "fecha": d["fecha"].isoformat()} for d in datos_cc["serie_diaria"]],
        "claves_kpi": CLAVES_KPI,
        "etiquetas_kpi": ETIQUETAS_KPI,
        "explicaciones_kpi": EXPLICACIONES_KPI,
        "filtros": filtros,
    }, None


def _siguiente_version(empresa_id, cuenta_id, tipo, fecha_inicio, fecha_fin, tipo_comparacion, filtros_normalizados):
    """Version dentro del mismo grupo empresa+cuenta+tipo+fechas+
    comparacion+filtros (Paso 15, punto 19: nunca sobrescribe). Compara
    `filtros` en Python (no con el operador de igualdad JSON de la BD,
    que no es portable entre SQLite y Postgres)."""
    from app.extensions import db
    from app.models import InformePauta

    candidatos = (
        db.session.query(InformePauta)
        .filter_by(
            empresa_id=empresa_id, cuenta_publicitaria_id=cuenta_id, tipo=tipo,
            fecha_inicio=fecha_inicio, fecha_fin=fecha_fin, tipo_comparacion=tipo_comparacion,
        )
        .all()
    )
    coincidentes = [c for c in candidatos if (c.filtros or {}) == filtros_normalizados]
    return (max(c.version for c in coincidentes) + 1) if coincidentes else 1


def crear_informe(empresa, usuario_id, cuenta_id, tipo, periodo_clave, fecha_inicio, fecha_fin,
                   tipo_comparacion="periodo_anterior", filtros=None, generar_resumen_claude=False):
    """(informe_o_None, error_o_None). Punto de entrada UNICO del Paso
    15 para crear un informe -- valida, construye el contenido
    (reutilizando centro_control.py), opcionalmente le pide a Claude
    SOLO el resumen ejecutivo, calcula la version siguiente y persiste
    el snapshot completo."""
    if tipo not in TIPOS_INFORME_PAUTA:
        return None, "Tipo de informe inválido."
    if tipo_comparacion not in TIPOS_COMPARACION_INFORME:
        tipo_comparacion = "periodo_anterior"
    if fecha_fin < fecha_inicio:
        return None, "El período seleccionado no es válido."

    from app.extensions import db
    from app.models import EntidadPublicitaria, InformePauta

    cuenta = db.session.query(EntidadPublicitaria).filter_by(id=cuenta_id, empresa_id=empresa.id, tipo="cuenta_publicitaria").first()
    if cuenta is None:
        return None, "La cuenta publicitaria seleccionada no pertenece a esta empresa."

    filtros_normalizados = _normalizar_filtros(filtros)

    contenido, error = construir_contenido_informe(empresa, cuenta_id, tipo, fecha_inicio, fecha_fin, tipo_comparacion, filtros_normalizados)

    resumen_generado_por = "reglas"
    if contenido and generar_resumen_claude:
        texto_claude, error_claude = generar_resumen_con_claude(
            empresa,
            {"kpis": contenido["kpis"], "comparacion_periodos": contenido["comparacion_periodos"], "estado_general": contenido["estado_general"], "moneda": contenido["moneda"]},
            contenido["campanas"], contenido["audiencias"], contenido["diagnostico"], contenido["oportunidades"],
        )
        if texto_claude:
            contenido["resumen"]["conclusion"] = texto_claude
            resumen_generado_por = "claude"
        else:
            contenido["resumen"]["aviso_claude"] = error_claude

    version = _siguiente_version(empresa.id, cuenta_id, tipo, fecha_inicio, fecha_fin, tipo_comparacion, filtros_normalizados)

    informe = InformePauta(
        empresa_id=empresa.id, usuario_id=usuario_id, cuenta_publicitaria_id=cuenta_id,
        tipo=tipo, titulo=f"{TITULOS_TIPO[tipo]} — {cuenta.nombre or cuenta.id_externo}",
        periodo_clave=periodo_clave, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
        tipo_comparacion=tipo_comparacion, filtros=filtros_normalizados, version=version,
        contenido=contenido, resumen_generado_por=resumen_generado_por if contenido else None,
        estado="listo" if contenido else "error", error_mensaje=error,
    )
    db.session.add(informe)
    db.session.commit()
    return informe, None


def obtener_informe(empresa_id, informe_id):
    from app.extensions import db
    from app.models import InformePauta

    return db.session.query(InformePauta).filter_by(id=informe_id, empresa_id=empresa_id).first()


def listar_informes_empresa(empresa_id, cuenta_id=None, tipo=None, limite=100):
    from app.extensions import db
    from app.models import InformePauta

    consulta = db.session.query(InformePauta).filter_by(empresa_id=empresa_id)
    if cuenta_id:
        consulta = consulta.filter_by(cuenta_publicitaria_id=cuenta_id)
    if tipo:
        consulta = consulta.filter_by(tipo=tipo)
    return consulta.order_by(InformePauta.creado_en.desc()).limit(limite).all()


def contenido_para_modo(contenido, modo):
    """Recorta `contenido` a las secciones permitidas en MODO CLIENTE
    (Paso 15, punto 14) -- nunca oculta datos en modo interno, y en
    modo cliente nunca expone diagnostico tecnico/plan de
    accion/detalle de oportunidades. Devuelve un dict nuevo (nunca
    modifica el snapshot guardado)."""
    if modo != "cliente":
        return contenido
    secciones = [s for s in contenido["secciones"] if s in SECCIONES_MODO_CLIENTE]
    recortado = dict(contenido)
    recortado["secciones"] = secciones
    # Detalle tecnico que nunca se muestra en modo cliente, tenga o no
    # el tipo de informe esa seccion (Paso 15, punto 14: "no mostrar
    # información técnica innecesaria").
    for clave in ("diagnostico", "oportunidades", "recomendaciones", "plan_accion", "campanas_atencion"):
        recortado[clave] = None
    if "audiencias" not in secciones:
        recortado["audiencias"] = None
    return recortado
