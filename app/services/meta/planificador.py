"""Planificador estrategico de pauta (Paso 7).

Reutiliza EXCLUSIVAMENTE lo ya construido: app/services/meta/kpi.py
(Paso 3) para todo el analisis historico, app/services/meta/analisis.py
(Paso 5) para el analisis de audiencias, y app/services/meta/
cuentas_service.py para leer la estructura ya sincronizada. Ningun
calculo de KPI ocurre en este archivo.

Este modulo NUNCA llama a la Graph API ni escribe nada en Meta -- solo
administra el plan (ProyectoPauta/EtapaProyectoPauta), que vive
enteramente en nuestra base de datos.
"""

from app.models import ESTADOS_PROYECTO_PAUTA

# Umbral de gasto diario minimo por fase, usado UNICAMENTE para la
# advertencia de "presupuesto demasiado pequeño para dividir entre
# tantas etapas" (Paso 7, punto 4). NO es un minimo oficial de Meta --
# es un umbral conservador propio, documentado aqui para poder
# ajustarlo con conocimiento de causa. Solo se aplica a las monedas que
# esta plataforma usa realmente hoy (CRC en la cuenta real conectada,
# USD como referencia internacional); una moneda fuera de esta lista
# simplemente no genera la advertencia, en vez de adivinar un umbral.
UMBRAL_GASTO_DIARIO_MINIMO_POR_ETAPA = {"CRC": 5000, "USD": 10}


def crear_proyecto(empresa_id, usuario_id, datos):
    """(proyecto_o_None, error_o_None). Valida los campos obligatorios
    del Paso 7, punto 1 -- nunca persiste un proyecto con presupuesto
    negativo o fechas invertidas."""
    from app.extensions import db
    from app.models import EntidadPublicitaria, ProyectoPauta
    from app.services.meta.kpi import CLAVES_KPI

    nombre = (datos.get("nombre") or "").strip()
    if not nombre:
        return None, "El nombre del proyecto es obligatorio."

    objetivo = (datos.get("objetivo") or "").strip()
    if not objetivo:
        return None, "El objetivo del proyecto es obligatorio."

    kpi_principal = datos.get("kpi_principal")
    if kpi_principal not in CLAVES_KPI:
        return None, "El KPI principal no es válido."

    try:
        presupuesto_total = float(datos.get("presupuesto_total"))
    except (TypeError, ValueError):
        return None, "El presupuesto total debe ser un número."
    if presupuesto_total <= 0:
        return None, "El presupuesto total debe ser mayor que cero."

    fecha_inicio = datos.get("fecha_inicio")
    fecha_fin = datos.get("fecha_fin")
    if not fecha_inicio or not fecha_fin:
        return None, "Las fechas de inicio y fin son obligatorias."
    if fecha_fin < fecha_inicio:
        return None, "La fecha final no puede ser anterior a la fecha de inicio."

    cuenta_publicitaria_id = datos.get("cuenta_publicitaria_id")
    if cuenta_publicitaria_id is not None:
        cuenta = (
            db.session.query(EntidadPublicitaria)
            .filter_by(id=cuenta_publicitaria_id, empresa_id=empresa_id, tipo="cuenta_publicitaria")
            .first()
        )
        if cuenta is None:
            return None, "La cuenta publicitaria seleccionada no pertenece a esta empresa."

    proyecto = ProyectoPauta(
        empresa_id=empresa_id,
        cuenta_publicitaria_id=cuenta_publicitaria_id,
        nombre=nombre,
        objetivo=objetivo,
        kpi_principal=kpi_principal,
        presupuesto_total=presupuesto_total,
        moneda=(datos.get("moneda") or "CRC").strip() or "CRC",
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        resultado_objetivo=(datos.get("resultado_objetivo") or "").strip() or None,
        restricciones=(datos.get("restricciones") or "").strip() or None,
        creado_por=usuario_id,
    )
    db.session.add(proyecto)
    db.session.commit()
    return proyecto, None


def obtener_proyecto(empresa_id, proyecto_id):
    from app.extensions import db
    from app.models import ProyectoPauta

    return db.session.query(ProyectoPauta).filter_by(id=proyecto_id, empresa_id=empresa_id).first()


def listar_proyectos_empresa(empresa_id):
    from app.extensions import db
    from app.models import ProyectoPauta

    return (
        db.session.query(ProyectoPauta)
        .filter_by(empresa_id=empresa_id)
        .order_by(ProyectoPauta.creado_en.desc())
        .all()
    )


def cambiar_estado_proyecto(empresa_id, proyecto_id, nuevo_estado):
    """Borrador <-> Plan aprobado (Paso 7, punto 12: 'guardar como
    Borrador y posteriormente Plan aprobado') -- un cambio de estado
    NUNCA ejecuta ni programa nada en Meta, es solo una marca interna."""
    proyecto = obtener_proyecto(empresa_id, proyecto_id)
    if proyecto is None:
        return None, "El proyecto no existe o no pertenece a esta empresa."
    if nuevo_estado not in ESTADOS_PROYECTO_PAUTA:
        return None, "Estado inválido."

    from app.extensions import db

    proyecto.estado = nuevo_estado
    db.session.commit()
    return proyecto, None


def resumen_presupuesto_proyecto(proyecto):
    """Total / asignado (suma de etapas) / disponible / % asignado --
    Paso 7, punto 4. El presupuesto asignado NUNCA puede superar el
    total porque agregar_etapa() ya lo bloquea al crear cada etapa."""
    asignado = round(sum(e.presupuesto for e in proyecto.etapas), 2)
    disponible = round(proyecto.presupuesto_total - asignado, 2)
    porcentaje_asignado = round((asignado / proyecto.presupuesto_total) * 100, 1) if proyecto.presupuesto_total else None

    return {
        "presupuesto_total": proyecto.presupuesto_total,
        "asignado": asignado,
        "disponible": disponible,
        "porcentaje_asignado": porcentaje_asignado,
    }


def _advertencia_distribucion(proyecto):
    """Paso 7: 'Si el presupuesto es demasiado pequeño para dividirlo
    entre demasiadas etapas, advertirlo.' Se basa en el gasto DIARIO
    real de cada etapa (presupuesto / duracion_dias) contra
    UMBRAL_GASTO_DIARIO_MINIMO_POR_ETAPA -- nunca en un conteo fijo de
    etapas, para que la advertencia dependa del dinero real disponible,
    no de un numero arbitrario de fases."""
    umbral = UMBRAL_GASTO_DIARIO_MINIMO_POR_ETAPA.get(proyecto.moneda)
    if umbral is None or len(proyecto.etapas) < 2:
        return None

    etapas_bajo_umbral = [
        e for e in proyecto.etapas
        if e.duracion_dias and (e.presupuesto / e.duracion_dias) < umbral
    ]
    if len(etapas_bajo_umbral) < 2:
        return None

    nombres = ", ".join(e.nombre for e in etapas_bajo_umbral)
    return (
        f"El presupuesto disponible es limitado para ejecutar {len(proyecto.etapas)} etapas simultáneamente "
        f"(gasto diario por debajo de {umbral} {proyecto.moneda} en: {nombres}). Considere concentrar la inversión."
    )


def agregar_etapa(empresa_id, proyecto_id, datos):
    """(etapa_o_None, error_o_None). La suma de presupuestos de TODAS
    las etapas (incluida la nueva) nunca puede superar
    proyecto.presupuesto_total -- regla explicita del Paso 7, punto 4."""
    proyecto = obtener_proyecto(empresa_id, proyecto_id)
    if proyecto is None:
        return None, "El proyecto no existe o no pertenece a esta empresa."

    nombre = (datos.get("nombre") or "").strip()
    if not nombre:
        return None, "El nombre de la fase es obligatorio."

    try:
        presupuesto = float(datos.get("presupuesto"))
    except (TypeError, ValueError):
        return None, "El presupuesto de la fase debe ser un número."
    if presupuesto <= 0:
        return None, "El presupuesto de la fase debe ser mayor que cero."

    asignado_actual = sum(e.presupuesto for e in proyecto.etapas)
    if asignado_actual + presupuesto > proyecto.presupuesto_total + 0.01:
        disponible = round(proyecto.presupuesto_total - asignado_actual, 2)
        return None, f"La suma de las fases no puede superar el presupuesto total del proyecto. Disponible: {disponible} {proyecto.moneda}."

    duracion_dias = datos.get("duracion_dias")
    try:
        duracion_dias = int(duracion_dias) if duracion_dias not in (None, "") else None
    except (TypeError, ValueError):
        return None, "La duración de la fase debe ser un número de días."
    if duracion_dias is not None and duracion_dias <= 0:
        return None, "La duración de la fase debe ser mayor que cero días."

    from app.extensions import db
    from app.models import EtapaProyectoPauta

    etapa = EtapaProyectoPauta(
        proyecto_id=proyecto.id,
        nombre=nombre,
        objetivo=(datos.get("objetivo") or "").strip() or None,
        presupuesto=presupuesto,
        kpi_esperado=datos.get("kpi_esperado") or None,
        audiencia_descripcion=(datos.get("audiencia_descripcion") or "").strip() or None,
        duracion_dias=duracion_dias,
        orden=len(proyecto.etapas),
    )
    db.session.add(etapa)
    db.session.commit()
    return etapa, None


def eliminar_etapa(empresa_id, proyecto_id, etapa_id):
    proyecto = obtener_proyecto(empresa_id, proyecto_id)
    if proyecto is None:
        return False, "El proyecto no existe o no pertenece a esta empresa."

    from app.extensions import db
    from app.models import EtapaProyectoPauta

    etapa = db.session.query(EtapaProyectoPauta).filter_by(id=etapa_id, proyecto_id=proyecto.id).first()
    if etapa is None:
        return False, "La fase no existe o no pertenece a este proyecto."

    db.session.delete(etapa)
    db.session.commit()
    return True, None


def construir_analisis_historico(empresa_id, cuenta_publicitaria_id, fecha_inicio, fecha_fin):
    """Paso 7, punto 2: 'Al crear el proyecto, mostrar el diagnóstico
    ... campañas relevantes, audiencias, mejores/peores anuncios,
    oportunidades, alertas, histórico.' Las oportunidades/alertas
    completas son del Paso 8 (todavia no construido) -- aqui se
    entrega el HISTORICO REAL disponible hoy: campañas comparadas
    (mejor/peor por costo por resultado), audiencias con su
    rendimiento real, y el mejor día real del período. Si no hay
    ninguna campaña sincronizada para la cuenta, `datos_suficientes`
    queda en False y no se inventa ningún dato.
    """
    from app.services.meta.analisis import analizar_audiencias
    from app.services.meta.cuentas_service import listar_campanas_de_cuenta
    from app.services.meta.kpi import comparar_entidades, serie_diaria

    if cuenta_publicitaria_id is None:
        return {
            "datos_suficientes": False,
            "campanas": [],
            "audiencias": [],
            "mejor_dia": None,
            "mensaje": "Selecciona una cuenta publicitaria para ver el histórico real disponible.",
        }

    campanas = listar_campanas_de_cuenta(empresa_id, cuenta_publicitaria_id)
    campana_ids = [c.id for c in campanas]

    comparacion_campanas = (
        comparar_entidades(empresa_id, campana_ids, fecha_inicio, fecha_fin, metrica_orden="costo_por_resultado")
        if campana_ids else []
    )

    audiencias_paquete, _error_audiencias = analizar_audiencias(empresa_id, cuenta_publicitaria_id, fecha_inicio, fecha_fin)
    audiencias = audiencias_paquete["segmentos"] if audiencias_paquete else []

    serie = serie_diaria(empresa_id, campana_ids, fecha_inicio, fecha_fin) if campana_ids else []
    dias_con_dato = [d for d in serie if d.get("costo_por_resultado") is not None]
    mejor_dia = min(dias_con_dato, key=lambda d: d["costo_por_resultado"]) if dias_con_dato else None

    # "Suficiente" significa: al menos una campaña con algun KPI real
    # calculado en el periodo -- nunca "existe la tabla", sino "existe
    # al menos un numero real que comparar".
    datos_suficientes = any(f["kpis"].get("spend") is not None for f in comparacion_campanas)

    return {
        "datos_suficientes": datos_suficientes,
        "campanas": comparacion_campanas,
        "audiencias": audiencias,
        "mejor_dia": mejor_dia,
        "mensaje": (
            "Existe suficiente información histórica para justificar esta distribución."
            if datos_suficientes
            else "No existe información histórica suficiente para esta cuenta y período — la propuesta de distribución no puede basarse en datos reales todavía."
        ),
    }


def construir_paquete_planificador(proyecto, fecha_inicio_analisis=None, fecha_fin_analisis=None):
    """Ensambla resumen + presupuesto + advertencia + analisis
    historico de un proyecto -- el 'servicio estructurado' que
    permitiria a un futuro consumidor (Claude u otro, Paso 8+) recibir
    el estado completo de un proyecto sin pasar por HTML.

    IMPORTANTE: `proyecto.fecha_inicio`/`fecha_fin` son el periodo FUTURO
    que el proyecto planea ejecutar -- nunca tienen metricas reales
    todavia. El analisis "historico" (Paso 7, punto 2) debe mirar hacia
    ATRAS en el tiempo, por eso recibe su propio rango
    (`fecha_inicio_analisis`/`fecha_fin_analisis`), independiente del
    periodo del proyecto; por defecto, los ultimos 90 dias reales."""
    if fecha_inicio_analisis is None or fecha_fin_analisis is None:
        from app.services.periodos import resolver_periodo

        fecha_inicio_analisis, fecha_fin_analisis = resolver_periodo("ultimos_90_dias")

    analisis = construir_analisis_historico(
        proyecto.empresa_id, proyecto.cuenta_publicitaria_id, fecha_inicio_analisis, fecha_fin_analisis,
    )
    return {
        "proyecto": proyecto,
        "presupuesto": resumen_presupuesto_proyecto(proyecto),
        "advertencia_distribucion": _advertencia_distribucion(proyecto),
        "analisis_historico": analisis,
        "periodo_analisis": {"fecha_inicio": fecha_inicio_analisis, "fecha_fin": fecha_fin_analisis},
    }
