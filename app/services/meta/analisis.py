"""Paquetes estructurados de analisis (Paso 5).

Punto UNICO donde se ensambla lo que las pantallas de "analisis de
campaña" y "audiencias" necesitan -- reutiliza exclusivamente
app/services/meta/kpi.py (Paso 3), app/services/presupuestos.py
(Paso 2), y los nuevos targeting.py/oportunidades.py de este paso.
NINGUN calculo de KPI ocurre en este archivo: solo organiza lo que
esos servicios ya devuelven.

Es tambien el "servicio estructurado" que pide el punto 9 del
enunciado para un futuro motor estrategico (Claude u otro): cualquier
consumidor futuro puede llamar construir_analisis_campana() o
analizar_audiencias() directamente, sin pasar por Flask ni por HTML --
ambas devuelven diccionarios/listas de datos puros (mas los objetos
EntidadPublicitaria/PresupuestoPauta ya cargados), listos para
serializar o para que un LLM los reciba como contexto.
"""


def construir_analisis_campana(empresa_id, campana_id, fecha_inicio, fecha_fin, comparar=False):
    """(paquete_o_None, error_o_None). El paquete incluye: la campaña,
    sus KPI del periodo (+ comparacion contra el periodo anterior si
    `comparar`), su serie diaria (evolucion), sus conjuntos (con KPI +
    targeting interpretado + mejor/peor), sus anuncios (con KPI +
    mejor/peor, incluyendo metricas de video cuando existan via
    kpi.CLAVES_KPI), presupuesto (gasto real siempre calculado desde
    Metrica + cualquier PresupuestoPauta "asignado" a esta campaña +
    lo que Meta reporta como presupuesto de la campaña) y oportunidades
    detectadas (de sus conjuntos, de sus anuncios, y de la campaña
    misma comparada contra sus hermanas de la misma cuenta)."""
    from app.extensions import db
    from app.models import EntidadPublicitaria
    from app.services.meta.cuentas_service import (
        listar_anuncios_de_conjuntos,
        listar_campanas_de_cuenta,
        listar_conjuntos_de_campana,
    )
    from app.services.meta.kpi import calcular_kpis, comparar_entidades, comparar_periodos, serie_diaria
    from app.services.meta.oportunidades import detectar_oportunidades_grupo
    from app.services.meta.targeting import interpretar_targeting
    from app.services.presupuestos import calcular_gasto_real, obtener_presupuestos_de_entidad

    campana = (
        db.session.query(EntidadPublicitaria)
        .filter_by(id=campana_id, empresa_id=empresa_id, tipo="campana")
        .first()
    )
    if campana is None:
        return None, "La campaña no existe o no pertenece a esta empresa."

    kpis = calcular_kpis(empresa_id, [campana.id], fecha_inicio, fecha_fin)
    comparacion = comparar_periodos(empresa_id, [campana.id], fecha_inicio, fecha_fin) if comparar else None
    serie = serie_diaria(empresa_id, [campana.id], fecha_inicio, fecha_fin)

    conjuntos = listar_conjuntos_de_campana(empresa_id, campana.id)
    conjunto_ids = [c.id for c in conjuntos]
    comparacion_conjuntos = (
        comparar_entidades(empresa_id, conjunto_ids, fecha_inicio, fecha_fin, metrica_orden="spend")
        if conjunto_ids else []
    )
    for fila in comparacion_conjuntos:
        fila["targeting"] = interpretar_targeting((fila["entidad"].atributos or {}).get("targeting"))
    oportunidades_conjuntos = detectar_oportunidades_grupo(comparacion_conjuntos)

    anuncios = listar_anuncios_de_conjuntos(empresa_id, conjunto_ids)
    anuncio_ids = [a.id for a in anuncios]
    comparacion_anuncios = (
        comparar_entidades(empresa_id, anuncio_ids, fecha_inicio, fecha_fin, metrica_orden="spend")
        if anuncio_ids else []
    )
    oportunidades_anuncios = detectar_oportunidades_grupo(comparacion_anuncios)

    # Presupuesto (Paso 5, punto 7): el gasto real NUNCA se guarda,
    # siempre se calcula desde Metrica (mismo principio del Paso 2).
    # Se muestran DOS fuentes posibles de "presupuesto", nunca
    # mezcladas: lo que el propio usuario planifico para esta campaña
    # (PresupuestoPauta "asignado") y lo que Meta reporta como
    # presupuesto de la campaña (atributos.presupuesto_diario/total,
    # sincronizado desde el Paso 2).
    gasto_real = calcular_gasto_real(empresa_id, entidad_id=campana.id, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin)
    presupuestos_asignados = obtener_presupuestos_de_entidad(empresa_id, campana.id)

    # "Campaña con buen rendimiento pero poco presupuesto" (punto 6)
    # solo tiene sentido comparando esta campaña contra sus hermanas de
    # la misma cuenta publicitaria -- se recalcula ese grupo aqui y se
    # extrae unicamente la oportunidad de ESTA campaña dentro de el.
    oportunidades_campana = []
    if campana.entidad_padre_id is not None:
        hermanas = listar_campanas_de_cuenta(empresa_id, campana.entidad_padre_id)
        hermanas_ids = [c.id for c in hermanas]
        if len(hermanas_ids) > 1:
            comparacion_hermanas = comparar_entidades(empresa_id, hermanas_ids, fecha_inicio, fecha_fin, metrica_orden="spend")
            oportunidades_campana = [o for o in detectar_oportunidades_grupo(comparacion_hermanas) if o["entidad_id"] == campana.id]

    return {
        "campana": campana,
        "kpis": kpis,
        "comparacion": comparacion,
        "serie_diaria": serie,
        "conjuntos": comparacion_conjuntos,
        "oportunidades_conjuntos": oportunidades_conjuntos,
        "anuncios": comparacion_anuncios,
        "oportunidades_anuncios": oportunidades_anuncios,
        "gasto_real": gasto_real,
        "presupuestos_asignados": presupuestos_asignados,
        "oportunidades_campana": oportunidades_campana,
    }, None


def analizar_audiencias(empresa_id, cuenta_id, fecha_inicio, fecha_fin):
    """(paquete_o_None, error_o_None). Analiza TODOS los conjuntos de
    anuncios de la empresa (o de una sola cuenta si se indica
    `cuenta_id`), separando SIEMPRE "audiencia configurada"
    (`targeting`, lo que se le pidio a Meta) de "audiencia que
    realmente produjo resultados" (`kpis`, lo medido) -- nunca se
    asume que una segmentacion funciono solo porque se uso; el ranking
    de mejor/peor viene de comparar_entidades() ordenado por costo por
    resultado (mas barato = mejor), exactamente igual que cualquier
    otra comparacion del motor de KPI."""
    from app.services.meta.cuentas_service import listar_conjuntos_de_empresa
    from app.services.meta.kpi import comparar_entidades, resolver_entidades_para_kpi
    from app.services.meta.oportunidades import detectar_oportunidades_grupo
    from app.services.meta.targeting import interpretar_targeting

    if cuenta_id is not None:
        _entidad_ids, error = resolver_entidades_para_kpi(empresa_id, cuenta_id)
        if error:
            return None, error

    conjuntos = listar_conjuntos_de_empresa(empresa_id, cuenta_id=cuenta_id)
    conjunto_ids = [c.id for c in conjuntos]

    comparacion = (
        comparar_entidades(empresa_id, conjunto_ids, fecha_inicio, fecha_fin, metrica_orden="costo_por_resultado")
        if conjunto_ids else []
    )

    # Nombre de la campaña padre de cada conjunto -- para contexto en
    # la tabla de segmentos (un conjunto no tiene nombre de campaña
    # propio, hay que resolverlo via entidad_padre_id).
    padre_ids = {f["entidad"].entidad_padre_id for f in comparacion if f["entidad"].entidad_padre_id}
    campanas_por_id = {}
    if padre_ids:
        from app.extensions import db
        from app.models import EntidadPublicitaria

        campanas_por_id = {
            c.id: c for c in db.session.query(EntidadPublicitaria).filter(EntidadPublicitaria.id.in_(padre_ids)).all()
        }

    for fila in comparacion:
        fila["targeting"] = interpretar_targeting((fila["entidad"].atributos or {}).get("targeting"))
        campana_padre = campanas_por_id.get(fila["entidad"].entidad_padre_id)
        fila["campana_nombre"] = (campana_padre.nombre or campana_padre.id_externo) if campana_padre else None

    oportunidades = detectar_oportunidades_grupo(comparacion)

    return {"segmentos": comparacion, "oportunidades": oportunidades}, None
