"""Proyectos estrategicos de campaña (Paso 9).

Convierte el diagnostico/oportunidades del Paso 8 en un plan de fases
concreto, con audiencias, secuencia de contenido y seguimiento
planificado vs real. Reutiliza EXCLUSIVAMENTE lo ya construido:
app/services/meta/kpi.py (Paso 3) y app/services/meta/inteligencia.py
(Paso 8) para todo diagnostico/analisis, app/services/presupuestos.py
(Paso 2) para gasto real, y app/services/meta/cuentas_service.py /
targeting.py (Paso 5) para leer audiencias ya sincronizadas. Ningun
calculo de KPI ni de oportunidades ocurre en este archivo.

Este modulo NUNCA llama a la Graph API ni escribe nada en Meta -- solo
administra el plan (ProyectoEstrategico/FaseEstrategica/
PasoSecuenciaEstrategica), que vive enteramente en nuestra base de
datos.
"""

from app.models import ESTADOS_PROYECTO_ESTRATEGICO


def crear_proyecto(empresa_id, usuario_id, datos):
    """(proyecto_o_None, error_o_None). Valida los campos obligatorios
    del Paso 9, punto 1 -- nunca persiste un proyecto con presupuesto
    negativo, fechas invertidas o un KPI que no exista."""
    from app.extensions import db
    from app.models import EntidadPublicitaria, ProyectoEstrategico
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

    kpi_secundarios = datos.get("kpi_secundarios") or []
    if not isinstance(kpi_secundarios, list) or any(k not in CLAVES_KPI for k in kpi_secundarios):
        return None, "Los KPI secundarios deben ser claves de KPI válidas."

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

    proyecto = ProyectoEstrategico(
        empresa_id=empresa_id,
        cuenta_publicitaria_id=cuenta_publicitaria_id,
        nombre=nombre,
        objetivo=objetivo,
        kpi_principal=kpi_principal,
        kpi_secundarios=kpi_secundarios,
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
    from app.models import ProyectoEstrategico

    return db.session.query(ProyectoEstrategico).filter_by(id=proyecto_id, empresa_id=empresa_id).first()


def listar_proyectos_empresa(empresa_id):
    from app.extensions import db
    from app.models import ProyectoEstrategico

    return (
        db.session.query(ProyectoEstrategico)
        .filter_by(empresa_id=empresa_id)
        .order_by(ProyectoEstrategico.creado_en.desc())
        .all()
    )


def cambiar_estado_proyecto(empresa_id, proyecto_id, nuevo_estado):
    """Cualquier transicion entre los 6 estados del Paso 9 (punto 9) es
    valida -- el sistema SOLO administra el proyecto, un cambio de
    estado nunca ejecuta ni programa nada en Meta."""
    proyecto = obtener_proyecto(empresa_id, proyecto_id)
    if proyecto is None:
        return None, "El proyecto no existe o no pertenece a esta empresa."
    if nuevo_estado not in ESTADOS_PROYECTO_ESTRATEGICO:
        return None, "Estado inválido."

    from app.extensions import db

    proyecto.estado = nuevo_estado
    db.session.commit()
    return proyecto, None


# --- Memoria estrategica (Paso 3: Inteligencia de Marketing) --------------------------

MAX_DECISIONES_CLAVE = 30  # evita que la lista crezca sin limite -- solo lo mas reciente sigue siendo relevante


ESTADOS_DECISION_CLAVE = ["activa", "reemplazada", "cerrada"]


def agregar_decision_clave(empresa_id, proyecto_id, texto, usuario_id=None, contexto=None, motivo=None, estado="activa"):
    """(proyecto_o_None, error_o_None). Guarda una decision importante
    del proyecto EN TEXTO LIBRE (ej. "se decidio priorizar ventas sobre
    alcance") -- nunca el historial completo del chat, solo lo que se
    marco explicitamente como decision, para que conversaciones futuras
    sobre este proyecto tengan ese contexto sin releer todo el chat.

    `contexto` y `motivo` son opcionales (texto libre, ej. "tras la
    caida de CTR en la campaña B" / "para proteger el margen"); cuando
    se dan, se le muestran a Claude junto con la decision (ver
    estratega_ia.py::_formatear_contexto_para_prompt). `proyecto_id` y
    `empresa_id` se guardan tambien dentro de cada entrada -- son
    redundantes con el proyecto contenedor, pero dejan cada decision
    auditable por si sola (Paso 3, cierre)."""
    from datetime import datetime, timezone

    from app.extensions import db

    texto = (texto or "").strip()
    if not texto:
        return None, "La decisión no puede estar vacía."

    if estado not in ESTADOS_DECISION_CLAVE:
        return None, "El estado de la decisión no es válido."

    proyecto = obtener_proyecto(empresa_id, proyecto_id)
    if proyecto is None:
        return None, "El proyecto no existe o no pertenece a esta empresa."

    decisiones = list(proyecto.decisiones_clave or [])
    decisiones.append({
        "texto": texto[:500],
        "contexto": (contexto or "").strip()[:500] or None,
        "motivo": (motivo or "").strip()[:500] or None,
        "estado": estado,
        "creado_en": datetime.now(timezone.utc).isoformat(),
        "usuario_id": usuario_id,
        "proyecto_id": proyecto.id,
        "empresa_id": empresa_id,
    })
    proyecto.decisiones_clave = decisiones[-MAX_DECISIONES_CLAVE:]
    db.session.commit()
    return proyecto, None


def listar_decisiones_clave(empresa_id, proyecto_id):
    proyecto = obtener_proyecto(empresa_id, proyecto_id)
    if proyecto is None:
        return None
    return list(proyecto.decisiones_clave or [])


def resumen_presupuesto_proyecto(proyecto):
    """Total / asignado (suma de fases) / disponible / % asignado --
    Paso 9, punto 4. El presupuesto asignado NUNCA puede superar el
    total porque agregar_fase() ya lo bloquea al crear cada fase."""
    asignado = round(sum(f.presupuesto for f in proyecto.fases), 2)
    disponible = round(proyecto.presupuesto_total - asignado, 2)
    porcentaje_asignado = round((asignado / proyecto.presupuesto_total) * 100, 1) if proyecto.presupuesto_total else None

    return {
        "presupuesto_total": proyecto.presupuesto_total,
        "asignado": asignado,
        "disponible": disponible,
        "porcentaje_asignado": porcentaje_asignado,
    }


def agregar_fase(empresa_id, proyecto_id, datos):
    """(fase_o_None, error_o_None). La suma de presupuestos de TODAS
    las fases (incluida la nueva) nunca puede superar
    proyecto.presupuesto_total -- misma regla explicita del Paso 7,
    ahora aplicada a FaseEstrategica (Paso 9, punto 4). El porcentaje
    NUNCA se calcula ni se impone aqui, solo se muestra despues (ver
    template) a partir del presupuesto que el usuario definio."""
    from app.extensions import db
    from app.models import EntidadPublicitaria

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

    asignado_actual = sum(f.presupuesto for f in proyecto.fases)
    if asignado_actual + presupuesto > proyecto.presupuesto_total + 0.01:
        disponible = round(proyecto.presupuesto_total - asignado_actual, 2)
        return None, f"La suma de las fases no puede superar el presupuesto total del proyecto. Disponible: {disponible} {proyecto.moneda}."

    fecha_inicio = datos.get("fecha_inicio") or None
    fecha_fin = datos.get("fecha_fin") or None
    if fecha_inicio and fecha_fin and fecha_fin < fecha_inicio:
        return None, "La fecha final de la fase no puede ser anterior a su fecha de inicio."

    from app.services.meta.kpi import CLAVES_KPI

    kpi_esperado = datos.get("kpi_esperado") or None
    if kpi_esperado is not None and kpi_esperado not in CLAVES_KPI:
        return None, "El KPI esperado de la fase no es válido."

    # La audiencia puede vincularse a un conjunto de anuncios REAL ya
    # sincronizado de esta empresa -- si no, queda unicamente como
    # estrategia planeada (audiencia_entidad_id=None), NUNCA se crea
    # nada en Meta (Paso 9, punto 5).
    audiencia_entidad_id = datos.get("audiencia_entidad_id") or None
    if audiencia_entidad_id is not None:
        conjunto = (
            db.session.query(EntidadPublicitaria)
            .filter_by(id=audiencia_entidad_id, empresa_id=empresa_id, tipo="conjunto_anuncios")
            .first()
        )
        if conjunto is None:
            return None, "La audiencia seleccionada no existe o no pertenece a esta empresa."

    from app.models import FaseEstrategica

    fase = FaseEstrategica(
        proyecto_id=proyecto.id,
        nombre=nombre,
        objetivo=(datos.get("objetivo") or "").strip() or None,
        presupuesto=presupuesto,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        kpi_esperado=kpi_esperado,
        audiencia_tipo=(datos.get("audiencia_tipo") or "").strip() or None,
        audiencia_descripcion=(datos.get("audiencia_descripcion") or "").strip() or None,
        audiencia_entidad_id=audiencia_entidad_id,
        resultado_esperado=(datos.get("resultado_esperado") or "").strip() or None,
        orden=len(proyecto.fases),
    )
    db.session.add(fase)
    db.session.commit()
    return fase, None


def eliminar_fase(empresa_id, proyecto_id, fase_id):
    proyecto = obtener_proyecto(empresa_id, proyecto_id)
    if proyecto is None:
        return False, "El proyecto no existe o no pertenece a esta empresa."

    from app.extensions import db
    from app.models import FaseEstrategica

    fase = db.session.query(FaseEstrategica).filter_by(id=fase_id, proyecto_id=proyecto.id).first()
    if fase is None:
        return False, "La fase no existe o no pertenece a este proyecto."

    db.session.delete(fase)
    db.session.commit()
    return True, None


def listar_audiencias_disponibles(empresa_id, cuenta_publicitaria_id):
    """Conjuntos de anuncios YA sincronizados de esta cuenta (Paso 9,
    punto 5) -- las unicas audiencias 'reales' que se pueden ofrecer
    para vincular a una fase. Reutiliza targeting.interpretar_targeting
    (Paso 5) para describirlas, nunca vuelve a leer la Graph API."""
    from app.services.meta.cuentas_service import listar_conjuntos_de_empresa
    from app.services.meta.targeting import interpretar_targeting

    conjuntos = listar_conjuntos_de_empresa(empresa_id, cuenta_id=cuenta_publicitaria_id)
    return [
        {
            "id": c.id,
            "nombre": c.nombre or c.id_externo,
            "targeting": interpretar_targeting((c.atributos or {}).get("targeting")),
        }
        for c in conjuntos
    ]


def agregar_paso_secuencia(empresa_id, proyecto_id, datos):
    """(paso_o_None, error_o_None). Secuencia estrategica del proyecto
    (Paso 9, punto 6) -- informacion para que Marketing genere
    contenidos despues, nunca crea ni programa nada en Meta."""
    proyecto = obtener_proyecto(empresa_id, proyecto_id)
    if proyecto is None:
        return None, "El proyecto no existe o no pertenece a esta empresa."

    contenido = (datos.get("contenido") or "").strip()
    if not contenido:
        return None, "El contenido del paso de secuencia es obligatorio."

    duracion_dias = datos.get("duracion_dias")
    try:
        duracion_dias = int(duracion_dias) if duracion_dias not in (None, "") else None
    except (TypeError, ValueError):
        return None, "La duración del paso debe ser un número de días."
    if duracion_dias is not None and duracion_dias <= 0:
        return None, "La duración del paso debe ser mayor que cero días."

    from app.services.meta.kpi import CLAVES_KPI

    kpi = datos.get("kpi") or None
    if kpi is not None and kpi not in CLAVES_KPI:
        return None, "El KPI del paso de secuencia no es válido."

    from app.extensions import db
    from app.models import PasoSecuenciaEstrategica

    paso = PasoSecuenciaEstrategica(
        proyecto_id=proyecto.id,
        contenido=contenido,
        audiencia_descripcion=(datos.get("audiencia_descripcion") or "").strip() or None,
        objetivo=(datos.get("objetivo") or "").strip() or None,
        duracion_dias=duracion_dias,
        kpi=kpi,
        orden=len(proyecto.secuencia),
    )
    db.session.add(paso)
    db.session.commit()
    return paso, None


def eliminar_paso_secuencia(empresa_id, proyecto_id, paso_id):
    proyecto = obtener_proyecto(empresa_id, proyecto_id)
    if proyecto is None:
        return False, "El proyecto no existe o no pertenece a esta empresa."

    from app.extensions import db
    from app.models import PasoSecuenciaEstrategica

    paso = db.session.query(PasoSecuenciaEstrategica).filter_by(id=paso_id, proyecto_id=proyecto.id).first()
    if paso is None:
        return False, "El paso de secuencia no existe o no pertenece a este proyecto."

    db.session.delete(paso)
    db.session.commit()
    return True, None


def construir_diagnostico_proyecto(proyecto, fecha_inicio_analisis=None, fecha_fin_analisis=None):
    """(paquete_o_None, error_o_None). Reutiliza integramente
    inteligencia.construir_inteligencia() (Paso 8) -- diagnostico,
    campañas, audiencias, creativos, oportunidades y alertas -- nunca
    recalcula nada de eso aqui (Paso 9, punto 2). El rango de analisis
    es, por defecto, hacia ATRAS en el tiempo (ultimos 90 dias reales),
    independiente del periodo FUTURO del proyecto -- mismo criterio que
    planificador.construir_paquete_planificador() del Paso 7."""
    if proyecto.cuenta_publicitaria_id is None:
        return None, "Selecciona una cuenta publicitaria en el proyecto para ver el diagnóstico real."

    if fecha_inicio_analisis is None or fecha_fin_analisis is None:
        from app.services.periodos import resolver_periodo

        fecha_inicio_analisis, fecha_fin_analisis = resolver_periodo("ultimos_90_dias")

    from app.services.meta.inteligencia import construir_inteligencia

    return construir_inteligencia(proyecto.empresa_id, proyecto.cuenta_publicitaria_id, fecha_inicio_analisis, fecha_fin_analisis)


def construir_seguimiento(proyecto):
    """Estructura PLANIFICADO vs REAL (Paso 9, punto 10) -- el
    presupuesto real y el KPI principal real se CALCULAN siempre desde
    Metrica (kpi.py), nunca se guardan como numeros aparte. Se resuelven
    las campañas reales de la cuenta vinculada con la MISMA funcion que
    usa el resto del motor de KPI (kpi.resolver_entidades_para_kpi) --
    nunca se suma el gasto de toda la empresa quien tenga varias cuentas
    publicitarias vinculadas, solo el de la cuenta de este proyecto.

    El 'objetivo' del KPI principal es el texto libre
    `resultado_objetivo` (una META, nunca una promesa) -- no se resta
    contra el valor real automaticamente porque no siempre es un numero
    (ver crear_proyecto). Esto es la ESTRUCTURA para comparar despues,
    no un motor de optimizacion (explicitamente fuera de alcance del
    Paso 9)."""
    tiene_cuenta = proyecto.cuenta_publicitaria_id is not None

    gasto_real = None
    valor_real_kpi_principal = None
    if tiene_cuenta:
        from app.services.meta.kpi import calcular_kpis, resolver_entidades_para_kpi

        entidad_ids, error = resolver_entidades_para_kpi(proyecto.empresa_id, proyecto.cuenta_publicitaria_id)
        if not error and entidad_ids is not None:
            kpis = calcular_kpis(proyecto.empresa_id, entidad_ids, proyecto.fecha_inicio, proyecto.fecha_fin)
            gasto_real = kpis.get("spend")
            valor_real_kpi_principal = kpis.get(proyecto.kpi_principal)

    return {
        "tiene_cuenta_vinculada": tiene_cuenta,
        "periodo": {"fecha_inicio": proyecto.fecha_inicio, "fecha_fin": proyecto.fecha_fin},
        "presupuesto": {
            "planificado": proyecto.presupuesto_total,
            "real": gasto_real,
            "moneda": proyecto.moneda,
        },
        "kpi_principal": {
            "clave": proyecto.kpi_principal,
            "objetivo_texto": proyecto.resultado_objetivo,
            "valor_real": valor_real_kpi_principal,
        },
    }


def construir_informe_estructurado(proyecto):
    """Paso 9, punto 11: objeto estructurado listo para que un futuro
    consumidor (Claude u otro, todavia NO conectado) reciba el estado
    completo del proyecto sin pasar por HTML. Reutiliza diagnostico
    (Paso 8) y seguimiento -- nunca recalcula nada."""
    from app.models import Empresa
    from app.extensions import db

    empresa = db.session.query(Empresa).filter_by(id=proyecto.empresa_id).first()
    diagnostico, error_diagnostico = construir_diagnostico_proyecto(proyecto)
    seguimiento = construir_seguimiento(proyecto)
    audiencias_disponibles = (
        listar_audiencias_disponibles(proyecto.empresa_id, proyecto.cuenta_publicitaria_id)
        if proyecto.cuenta_publicitaria_id else []
    )

    return {
        "empresa": {"id": empresa.id, "nombre": empresa.nombre} if empresa else None,
        "objetivo": proyecto.objetivo,
        "presupuesto": resumen_presupuesto_proyecto(proyecto),
        "periodo": {"fecha_inicio": proyecto.fecha_inicio, "fecha_fin": proyecto.fecha_fin},
        "diagnostico": diagnostico["diagnostico"] if diagnostico else None,
        "oportunidades": diagnostico["oportunidades"] if diagnostico else [],
        "alertas": diagnostico["alertas"] if diagnostico else [],
        "fases": [
            {
                "nombre": f.nombre, "objetivo": f.objetivo, "presupuesto": f.presupuesto,
                "kpi_esperado": f.kpi_esperado, "audiencia_tipo": f.audiencia_tipo,
                "audiencia_descripcion": f.audiencia_descripcion,
                "audiencia_vinculada_a_meta": f.audiencia_entidad_id is not None,
                "resultado_esperado": f.resultado_esperado,
            }
            for f in proyecto.fases
        ],
        "audiencias_disponibles": audiencias_disponibles,
        "secuencia": [
            {
                "contenido": p.contenido, "audiencia_descripcion": p.audiencia_descripcion,
                "objetivo": p.objetivo, "duracion_dias": p.duracion_dias, "kpi": p.kpi,
            }
            for p in proyecto.secuencia
        ],
        "kpi": {"principal": proyecto.kpi_principal, "secundarios": proyecto.kpi_secundarios},
        "metas": {"resultado_objetivo": proyecto.resultado_objetivo},
        "contenido_requerido": [p.contenido for p in proyecto.secuencia],
        "resultados_reales": seguimiento,
        "decisiones_clave": list(proyecto.decisiones_clave or []),
    }
