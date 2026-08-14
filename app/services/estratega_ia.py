"""Estratega IA (Paso 10): orquesta el contexto de negocio + la capa
de modelo (app/services/ia.py) + la persistencia de conversaciones.

Reutiliza EXCLUSIVAMENTE lo ya construido -- NUNCA recalcula un KPI ni
vuelve a detectar una oportunidad:
  - app/services/meta/inteligencia.py (Paso 8): diagnostico, campañas,
    audiencias, creativos, oportunidades, alertas.
  - app/services/meta/proyectos_estrategicos.py (Paso 9): informe
    estructurado de un proyecto (que a su vez ya incluye el diagnostico
    del Paso 8).
  - app/services/presupuestos.py (Paso 2): presupuesto estrategico
    general de la empresa, cuando no hay un proyecto seleccionado.

Este modulo NUNCA llama a la Graph API de Meta ni a la API de
Anthropic directamente -- todo lo segundo pasa por
app/services/ia.py::generar_respuesta().

SEGURIDAD (Paso 10, punto 12): el contexto que se le envia al modelo
se construye ENTERAMENTE a partir de los "informe estructurado" de
Inteligencia/Proyectos, que nunca leen `MetaConexion.access_token_cifrado`
ni ningun otro secreto -- es estructuralmente imposible que un token
llegue al modelo desde aqui. `contexto_utilizado` (lo que se guarda en
MensajeIA) es ademas un RESUMEN ligero (conteos, nunca el detalle
completo), tanto por privacidad como para no inflar la base de datos.
"""

import os
from datetime import datetime, timedelta, timezone

LIMITE_MENSAJES_POR_CONVERSACION = int(os.environ.get("IA_LIMITE_MENSAJES_POR_CONVERSACION", "60"))
LIMITE_MENSAJES_DIARIOS_POR_EMPRESA = int(os.environ.get("IA_LIMITE_MENSAJES_DIARIOS_POR_EMPRESA", "200"))
# Cuantos mensajes previos de la conversacion se reenvian al modelo en
# cada llamada -- limita el crecimiento de tokens de una conversacion
# larga sin perder el contexto reciente.
MAX_MENSAJES_HISTORIAL_ENVIADOS = 20

REGLAS_SISTEMA = """Eres el Estratega IA de Publi Marketing, un asistente de marketing digital para la empresa "{empresa_nombre}". Tu trabajo es analizar el contexto real de datos de Meta ya sincronizado que se te entrega abajo y responder preguntas de forma honesta y accionable.

REGLAS OBLIGATORIAS:
1. NUNCA inventes datos, cifras, campañas, audiencias ni resultados que no aparezcan en el CONTEXTO de abajo.
2. Cuando cites un dato real de Meta, usa este formato:
   DATO: <resultado real, con el número exacto del contexto>
   ANÁLISIS: <tu interpretación>
   RECOMENDACIÓN: <acción propuesta, nunca una promesa de resultado>
3. Distingue SIEMPRE "datos observados" (lo que Meta reportó) de "recomendación estratégica" (tu sugerencia) -- nunca presentes una recomendación como si fuera un dato real.
4. Si el usuario pregunta por un KPI que no aparece en el contexto o cuyo valor es "No disponible", responde exactamente: "No existe información suficiente para calcular este KPI con los datos actualmente sincronizados." No lo inventes ni lo estimes.
5. Nunca afirmes que una acción garantiza un resultado futuro.
6. Cuando propongas una estrategia o distribución de presupuesto, preséntala como una PROPUESTA estructurada (objetivo, audiencia, presupuesto sugerido, duración, contenido, KPI, motivo) -- nunca la ejecutes ni des a entender que ya se aplicó. No puedes crear, modificar ni publicar nada en Meta bajo ninguna circunstancia; solo puedes proponer.
7. Si el contexto indica que no hay datos suficientes para un análisis, dilo con claridad en vez de rellenar con suposiciones.
8. Si el usuario pregunta qué debería optimizar u ordenar por prioridad, usa la lista "PRIORIDADES DEL CENTRO DE OPTIMIZACIÓN" del contexto (ya viene ordenada) en vez de inventar un orden propio -- respétala como base de tu respuesta.

CONTEXTO DISPONIBLE (datos reales, ya sincronizados en Publi Marketing):
{contexto}
"""


def _leer_precio_env(nombre):
    valor = os.environ.get(nombre)
    if not valor:
        return None
    try:
        return float(valor)
    except ValueError:
        return None


def _calcular_costo_estimado(tokens_entrada, tokens_salida):
    """None si no hay precios configurados -- nunca se inventa un
    costo. El usuario puede configurar IA_PRECIO_ENTRADA_USD_POR_1M /
    IA_PRECIO_SALIDA_USD_POR_1M con su tarifa real contratada."""
    precio_entrada = _leer_precio_env("IA_PRECIO_ENTRADA_USD_POR_1M")
    precio_salida = _leer_precio_env("IA_PRECIO_SALIDA_USD_POR_1M")
    if precio_entrada is None or precio_salida is None or tokens_entrada is None or tokens_salida is None:
        return None
    return round((tokens_entrada / 1_000_000) * precio_entrada + (tokens_salida / 1_000_000) * precio_salida, 6)


# --- Conversaciones ------------------------------------------------------------------

def crear_conversacion(empresa_id, usuario_id, proyecto_id=None):
    from app.extensions import db
    from app.models import ConversacionIA, ProyectoEstrategico

    if proyecto_id is not None:
        proyecto = db.session.query(ProyectoEstrategico).filter_by(id=proyecto_id, empresa_id=empresa_id).first()
        if proyecto is None:
            return None, "El proyecto seleccionado no pertenece a esta empresa."

    conversacion = ConversacionIA(empresa_id=empresa_id, usuario_id=usuario_id, proyecto_id=proyecto_id)
    db.session.add(conversacion)
    db.session.commit()
    return conversacion, None


def obtener_conversacion(empresa_id, conversacion_id):
    from app.extensions import db
    from app.models import ConversacionIA

    return db.session.query(ConversacionIA).filter_by(id=conversacion_id, empresa_id=empresa_id).first()


def listar_conversaciones_empresa(empresa_id, limite=50):
    from app.extensions import db
    from app.models import ConversacionIA

    return (
        db.session.query(ConversacionIA)
        .filter_by(empresa_id=empresa_id)
        .order_by(ConversacionIA.actualizado_en.desc())
        .limit(limite)
        .all()
    )


def _contar_mensajes_usuario_hoy(empresa_id):
    from app.extensions import db
    from app.models import ConversacionIA, MensajeIA

    inicio_dia = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        db.session.query(MensajeIA)
        .join(ConversacionIA, MensajeIA.conversacion_id == ConversacionIA.id)
        .filter(ConversacionIA.empresa_id == empresa_id, MensajeIA.rol == "usuario", MensajeIA.creado_en >= inicio_dia)
        .count()
    )


# --- Contexto de negocio (reutiliza Paso 8 / Paso 9 / Paso 2, nunca recalcula) --------

def construir_contexto(empresa, cuenta_publicitaria_id=None, periodo_clave="ultimos_30_dias", proyecto=None):
    """(informe_o_None, resumen_auditoria_o_None, error_o_None).
    Si `proyecto` viene definido, reutiliza integramente
    proyectos_estrategicos.construir_informe_estructurado() (que ya
    incluye el diagnostico del Paso 8) -- de lo contrario, reutiliza
    inteligencia.construir_informe_estructurado() con el presupuesto
    estrategico general de la empresa si existe uno (Paso 2)."""
    from app.services.periodos import resolver_periodo

    fecha_inicio, fecha_fin = resolver_periodo(periodo_clave)

    if proyecto is not None:
        from app.services.meta.proyectos_estrategicos import construir_informe_estructurado

        informe = construir_informe_estructurado(proyecto)
        fuente = "proyecto"
    else:
        from app.services.meta.inteligencia import construir_informe_estructurado
        from app.services.presupuestos import calcular_resumen_presupuesto, obtener_presupuestos_empresa

        presupuestos = [calcular_resumen_presupuesto(p) for p in obtener_presupuestos_empresa(empresa.id)]
        presupuesto_principal = next((r for r in presupuestos if r["presupuesto"].tipo == "estrategico"), None)

        informe, error = construir_informe_estructurado(
            empresa, cuenta_publicitaria_id, fecha_inicio, fecha_fin,
            presupuesto_total=presupuesto_principal["presupuesto"].monto if presupuesto_principal else None,
        )
        if error:
            return None, None, error
        fuente = "inteligencia"

        # Paso 11: las prioridades del centro de optimizacion se
        # agregan al MISMO informe (nunca se vuelve a analizar nada,
        # solo se reutiliza construir_prioridades_para_claude) para que
        # el Estratega IA pueda responder "que deberia optimizar hoy".
        from app.services.meta.optimizacion import construir_prioridades_para_claude

        prioridades, _error_prioridades = construir_prioridades_para_claude(empresa.id, cuenta_publicitaria_id, fecha_inicio, fecha_fin)
        informe["prioridades_optimizacion"] = prioridades

    resumen_auditoria = _resumen_auditoria(informe, fuente, periodo_clave, fecha_inicio, fecha_fin, proyecto, empresa)
    return informe, resumen_auditoria, None


def _resumen_auditoria(informe, fuente, periodo_clave, fecha_inicio, fecha_fin, proyecto, empresa):
    resumen = {
        "fuente": fuente,
        "empresa": empresa.nombre,
        "proyecto": proyecto.nombre if proyecto else None,
        "periodo": periodo_clave,
        "fecha_inicio": fecha_inicio.isoformat(),
        "fecha_fin": fecha_fin.isoformat(),
    }
    if fuente == "inteligencia":
        resumen["campanas_analizadas"] = len(informe["campanas"]["campanas"])
        resumen["audiencias_analizadas"] = len(informe["audiencias"]["segmentos"]) if informe.get("audiencias") else 0
        resumen["oportunidades_detectadas"] = len(informe["oportunidades"])
        resumen["alertas_detectadas"] = len(informe["alertas"])
        resumen["gasto_invertido"] = informe["kpi"].get("spend")
    else:
        resumen["fases"] = len(informe["fases"])
        resumen["audiencias_disponibles"] = len(informe["audiencias_disponibles"])
        resumen["oportunidades_detectadas"] = len(informe.get("oportunidades") or [])
        resumen["alertas_detectadas"] = len(informe.get("alertas") or [])
        resumen["presupuesto_total"] = informe["presupuesto"]["presupuesto_total"]
    return resumen


def _fmt(valor, sufijo=""):
    return "No disponible" if valor is None else f"{valor}{sufijo}"


def _formatear_kpis(kpis, etiquetas_kpi):
    lineas = []
    for clave, etiqueta in etiquetas_kpi.items():
        if clave in kpis:
            lineas.append(f"  - {etiqueta}: {_fmt(kpis.get(clave))}")
    return "\n".join(lineas) if lineas else "  (sin datos)"


def _formatear_contexto_para_prompt(informe, fuente, proyecto=None):
    """Convierte el informe estructurado (dict con objetos del ORM,
    ver inteligencia.py/proyectos_estrategicos.py) a texto plano
    legible para el modelo -- nunca envia objetos ni tokens, solo
    nombres/numeros ya calculados por los servicios que se reutilizan."""
    from app.services.meta.kpi import ETIQUETAS_KPI

    partes = []
    partes.append(f"Período analizado: {informe['periodo']['fecha_inicio']} a {informe['periodo']['fecha_fin']}")

    if fuente == "proyecto":
        partes.append(f"\nPROYECTO ESTRATÉGICO: {proyecto.nombre}")
        partes.append(f"Objetivo del proyecto: {informe['objetivo']}")
        presu = informe["presupuesto"]
        partes.append(f"Presupuesto: total {_fmt(presu['presupuesto_total'])}, asignado a fases {_fmt(presu['asignado'])}, disponible {_fmt(presu['disponible'])}")
        partes.append(f"Meta del proyecto (no un resultado real): {informe['metas']['resultado_objetivo'] or 'no definida'}")

        partes.append("\nFASES:")
        if informe["fases"]:
            for f in informe["fases"]:
                audiencia = f["audiencia_descripcion"] or f["audiencia_tipo"] or "no definida"
                vinculo = "vinculada a una audiencia real de Meta" if f["audiencia_vinculada_a_meta"] else "audiencia SOLO PLANEADA, no existe todavía en Meta"
                partes.append(f"  - {f['nombre']}: presupuesto {_fmt(f['presupuesto'])}, objetivo {f['objetivo'] or '—'}, KPI esperado {f['kpi_esperado'] or '—'}, audiencia: {audiencia} ({vinculo})")
        else:
            partes.append("  (todavía no hay ninguna fase definida)")

        partes.append("\nSECUENCIA ESTRATÉGICA:")
        if informe["secuencia"]:
            for i, p in enumerate(informe["secuencia"], 1):
                partes.append(f"  {i}. {p['contenido']} -- audiencia: {p['audiencia_descripcion'] or '—'}, objetivo: {p['objetivo'] or '—'}, duración: {_fmt(p['duracion_dias'], ' días')}, KPI: {p['kpi'] or '—'}")
        else:
            partes.append("  (todavía no hay ninguna secuencia definida)")

        partes.append("\nAUDIENCIAS REALES YA SINCRONIZADAS DISPONIBLES PARA ESTE PROYECTO:")
        if informe["audiencias_disponibles"]:
            for a in informe["audiencias_disponibles"]:
                partes.append(f"  - {a['nombre']}")
        else:
            partes.append("  (ninguna todavía)")

        diagnostico = informe.get("diagnostico")
        oportunidades = informe.get("oportunidades") or []
        alertas = informe.get("alertas") or []
        seguimiento = informe.get("resultados_reales") or {}
    else:
        if informe.get("presupuesto_total") is not None:
            partes.append(f"\nPresupuesto estratégico general de la empresa: {informe['presupuesto_total']}")
        partes.append("\nKPI DEL PERÍODO:")
        partes.append(_formatear_kpis(informe["kpi"], ETIQUETAS_KPI))

        campanas = informe["campanas"]["campanas"]
        partes.append(f"\nCAMPAÑAS ANALIZADAS ({len(campanas)}):")
        if campanas:
            for fila in campanas:
                nombre = fila["entidad"].nombre or fila["entidad"].id_externo
                marca = " [MEJOR del grupo]" if fila["es_mejor"] else (" [PEOR del grupo]" if fila["es_peor"] else "")
                partes.append(f"  - {nombre}{marca}: gasto {_fmt(fila['kpis'].get('spend'))}, resultados {_fmt(fila['kpis'].get('resultados'))}, costo por resultado {_fmt(fila['kpis'].get('costo_por_resultado'))}, CTR {_fmt(fila['kpis'].get('ctr'), '%')}")
        else:
            partes.append("  (ninguna campaña sincronizada para este período)")

        segmentos = informe["audiencias"]["segmentos"] if informe.get("audiencias") else []
        partes.append(f"\nAUDIENCIAS ANALIZADAS ({len(segmentos)}):")
        if segmentos:
            for fila in segmentos:
                nombre = fila["entidad"].nombre or fila["entidad"].id_externo
                marca = " [MEJOR del grupo]" if fila["es_mejor"] else (" [PEOR del grupo]" if fila["es_peor"] else "")
                partes.append(f"  - {nombre}{marca}: costo por resultado {_fmt(fila['kpis'].get('costo_por_resultado'))}")
        else:
            partes.append("  (ninguna sincronizada para este período)")

        diagnostico = informe.get("diagnostico")
        oportunidades = informe.get("oportunidades") or []
        alertas = informe.get("alertas") or []
        seguimiento = None

    if diagnostico:
        partes.append("\nDIAGNÓSTICO POR ÁREA (comparado contra el período anterior):")
        for clave, area in diagnostico["areas"].items():
            if area["clasificacion"] != "sin_datos":
                partes.append(f"  - {ETIQUETAS_KPI.get(clave, clave)}: {_fmt(area['valor'])} -- clasificación: {area['clasificacion'].upper()} (confianza {area['confianza']})")

    partes.append(f"\nOPORTUNIDADES ESTRATÉGICAS DETECTADAS ({len(oportunidades)}):")
    if oportunidades:
        for o in oportunidades:
            titulo = o.get("titulo") or o.get("que_detectamos") or o.get("tipo")
            evidencia = o.get("evidencia") or o.get("dato")
            partes.append(f"  - {titulo}. Evidencia: {evidencia}. Confianza: {o.get('nivel_confianza') or o.get('nivel')}")
    else:
        partes.append("  (ninguna con los datos y umbrales actuales)")

    partes.append(f"\nALERTAS ({len(alertas)}):")
    if alertas:
        for a in alertas:
            partes.append(f"  - {a.get('que_ocurrio')}")
    else:
        partes.append("  (ninguna)")

    prioridades_optimizacion = informe.get("prioridades_optimizacion") or []
    if prioridades_optimizacion:
        partes.append(f"\nPRIORIDADES DEL CENTRO DE OPTIMIZACIÓN (Paso 11, ya ordenadas de mayor a menor prioridad -- úsalas para responder qué revisar primero):")
        for linea in prioridades_optimizacion:
            partes.append(f"  - {linea}")

    if seguimiento and seguimiento.get("tiene_cuenta_vinculada"):
        partes.append("\nSEGUIMIENTO PLANIFICADO VS. REAL:")
        partes.append(f"  - Presupuesto: planificado {_fmt(seguimiento['presupuesto']['planificado'])}, real {_fmt(seguimiento['presupuesto']['real'])}")
        partes.append(f"  - {seguimiento['kpi_principal']['clave']}: objetivo (meta, no promesa) '{seguimiento['kpi_principal']['objetivo_texto'] or 'no definido'}', real {_fmt(seguimiento['kpi_principal']['valor_real'])}")

    return "\n".join(partes)


def _historial_para_modelo(conversacion):
    mapa_rol = {"usuario": "user", "asistente": "assistant"}
    mensajes = list(conversacion.mensajes)[-MAX_MENSAJES_HISTORIAL_ENVIADOS:]
    return [{"role": mapa_rol[m.rol], "content": m.contenido} for m in mensajes if m.rol in mapa_rol]


# --- Responder (punto de entrada usado por las rutas) ---------------------------------

def responder(empresa, conversacion, mensaje_usuario, cuenta_publicitaria_id=None, periodo_clave="ultimos_30_dias"):
    """(mensaje_asistente_o_None, error_o_None). Construye el contexto,
    llama al modelo (app/services/ia.py) y persiste tanto la pregunta
    del usuario como la respuesta -- o solo la pregunta si la IA
    falla, para no perder lo que el usuario escribio."""
    from app.services.ia import generar_respuesta, ia_configurada

    mensaje_usuario = (mensaje_usuario or "").strip()
    if not mensaje_usuario:
        return None, "El mensaje no puede estar vacío."

    if not ia_configurada():
        return None, "El asistente de IA no está configurado en este entorno."

    if len(conversacion.mensajes) >= LIMITE_MENSAJES_POR_CONVERSACION:
        return None, f"Esta conversación alcanzó el máximo de {LIMITE_MENSAJES_POR_CONVERSACION} mensajes. Inicia una nueva conversación."

    if _contar_mensajes_usuario_hoy(empresa.id) >= LIMITE_MENSAJES_DIARIOS_POR_EMPRESA:
        return None, f"Se alcanzó el límite diario de {LIMITE_MENSAJES_DIARIOS_POR_EMPRESA} mensajes de IA para esta empresa. Intenta de nuevo mañana."

    informe, resumen_auditoria, error_contexto = construir_contexto(
        empresa, cuenta_publicitaria_id, periodo_clave, proyecto=conversacion.proyecto,
    )

    if error_contexto:
        contexto_texto = f"No hay datos reales disponibles todavía: {error_contexto}"
        resumen_auditoria = {"fuente": "sin_datos", "motivo": error_contexto, "empresa": empresa.nombre}
    else:
        fuente = resumen_auditoria["fuente"]
        contexto_texto = _formatear_contexto_para_prompt(informe, fuente, proyecto=conversacion.proyecto)

    system = REGLAS_SISTEMA.format(empresa_nombre=empresa.nombre, contexto=contexto_texto)

    # El historial se arma ANTES de agregar el mensaje nuevo a la
    # sesion -- `conversacion.mensajes` es una coleccion ya cargada por
    # el chequeo de limite de arriba, y no se refresca sola dentro de
    # la misma sesion tras un flush(). Agregar el mensaje actual a mano
    # evita depender de ese comportamiento de SQLAlchemy.
    mensajes_api = _historial_para_modelo(conversacion) + [{"role": "user", "content": mensaje_usuario}]
    texto_respuesta, uso, error_ia = generar_respuesta(mensajes_api, system=system)

    from app.extensions import db
    from app.models import MensajeIA

    msg_usuario = MensajeIA(
        conversacion_id=conversacion.id, rol="usuario", contenido=mensaje_usuario, contexto_utilizado=resumen_auditoria,
    )
    db.session.add(msg_usuario)

    if error_ia:
        db.session.commit()  # se conserva la pregunta del usuario aunque la IA haya fallado
        return None, error_ia

    tokens_entrada = uso["tokens_entrada"] if uso else None
    tokens_salida = uso["tokens_salida"] if uso else None

    msg_asistente = MensajeIA(
        conversacion_id=conversacion.id, rol="asistente", contenido=texto_respuesta, contexto_utilizado=resumen_auditoria,
        modelo=uso["modelo"] if uso else None, tokens_entrada=tokens_entrada, tokens_salida=tokens_salida,
        costo_estimado_usd=_calcular_costo_estimado(tokens_entrada, tokens_salida),
    )
    db.session.add(msg_asistente)

    if conversacion.titulo is None:
        conversacion.titulo = mensaje_usuario[:80] + ("…" if len(mensaje_usuario) > 80 else "")
    conversacion.actualizado_en = datetime.now(timezone.utc)
    db.session.commit()
    return msg_asistente, None
