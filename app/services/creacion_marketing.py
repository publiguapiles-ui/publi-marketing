"""Creacion de Marketing (Paso 4): objetivo y brief estrategico de una
campaña ANTES de pautar -- completamente independiente de Datos de
Meta. Este servicio administra unicamente el ProyectoMarketing y su
brief; las etapas futuras (estrategia de contenido, conceptos,
creativos, guiones, produccion, edicion, calendario, publicacion,
pauta) NO se implementan todavia (Paso 4, punto 14).

No se conecta con Meta ni publica nada. Reutiliza la identidad de
marca ya existente (app/services/marca.py) en vez de duplicarla en
cada proyecto -- ver construir_resumen().
"""

from app.models import ACCIONES_SUGERIDAS, OBJETIVOS_SUGERIDOS

ETIQUETAS_OBJETIVOS = {
    "dar_a_conocer": "Dar a conocer mi negocio",
    "conseguir_clientes": "Conseguir clientes",
    "aumentar_ventas": "Aumentar ventas",
    "lanzar_producto": "Lanzar un producto",
    "promocionar_producto": "Promocionar un producto",
    "mensajes_whatsapp": "Conseguir mensajes por WhatsApp",
    "visitas_local": "Conseguir visitas al local",
    "aumentar_seguidores": "Aumentar seguidores",
    "crear_comunidad": "Crear comunidad",
    "promocionar_evento": "Promocionar un evento",
    "otro": "Otro",
}

ETIQUETAS_ACCIONES = {
    "comprar": "Comprar",
    "escribir_whatsapp": "Escribir por WhatsApp",
    "visitar_negocio": "Visitar el negocio",
    "reservar": "Reservar",
    "llamar": "Llamar",
    "solicitar_informacion": "Solicitar información",
    "seguir_pagina": "Seguir la página",
    "compartir": "Compartir",
    "registrarse": "Registrarse",
    "otro": "Otro",
}

CLAVES_PUBLICO = ["ubicacion", "edad", "genero", "tipo_cliente", "intereses", "necesidades", "problema", "comportamiento", "relacion_marca"]
CLAVES_OFERTA = ["producto", "servicio", "oferta", "precio", "promocion", "beneficio_principal", "diferenciador"]
CLAVES_IDENTIDAD_BRIEF = ["tono", "estilo", "personalidad", "restricciones"]


def crear_proyecto(empresa_id, usuario_id, nombre):
    """(proyecto_o_None, error_o_None). Paso 4, punto 2: solo pide
    cliente (empresa activa) + nombre -- el resto del brief se completa
    despues, pregunta por pregunta."""
    from app.extensions import db
    from app.models import ProyectoMarketing

    nombre = (nombre or "").strip()
    if not nombre:
        return None, "El nombre del proyecto es obligatorio."

    proyecto = ProyectoMarketing(empresa_id=empresa_id, nombre=nombre, creado_por=usuario_id)
    db.session.add(proyecto)
    db.session.commit()
    return proyecto, None


def obtener_proyecto(empresa_id, proyecto_id):
    from app.extensions import db
    from app.models import ProyectoMarketing

    return db.session.query(ProyectoMarketing).filter_by(id=proyecto_id, empresa_id=empresa_id).first()


def listar_proyectos_empresa(empresa_id):
    from app.extensions import db
    from app.models import ProyectoMarketing

    return (
        db.session.query(ProyectoMarketing)
        .filter_by(empresa_id=empresa_id)
        .order_by(ProyectoMarketing.actualizado_en.desc())
        .all()
    )


def _limpiar_subdiccionario(bruto, claves_validas):
    """Solo conserva las claves conocidas, como texto libre recortado --
    nunca guarda claves arbitrarias que el cliente decida mandar."""
    if not isinstance(bruto, dict):
        return {}
    limpio = {}
    for clave in claves_validas:
        valor = bruto.get(clave)
        if isinstance(valor, str):
            valor = valor.strip()
        if valor:
            limpio[clave] = valor
    return limpio


def actualizar_brief(empresa_id, proyecto_id, datos):
    """(proyecto_o_None, error_o_None). Guardado incremental -- el
    llamador puede mandar solo las claves que corresponden a la
    pregunta que el usuario acaba de responder, sin tener que completar
    el brief entero de una vez (Paso 4: wizard de preguntas)."""
    from app.extensions import db

    proyecto = obtener_proyecto(empresa_id, proyecto_id)
    if proyecto is None:
        return None, "El proyecto no existe o no pertenece a esta empresa."

    if "nombre" in datos:
        nombre = (datos.get("nombre") or "").strip()
        if not nombre:
            return None, "El nombre del proyecto es obligatorio."
        proyecto.nombre = nombre

    if "objetivo_tipo" in datos:
        objetivo_tipo = datos.get("objetivo_tipo") or None
        if objetivo_tipo is not None and objetivo_tipo not in OBJETIVOS_SUGERIDOS:
            return None, "El objetivo indicado no es válido."
        proyecto.objetivo_tipo = objetivo_tipo
    if "objetivo_detalle" in datos:
        proyecto.objetivo_detalle = (datos.get("objetivo_detalle") or "").strip() or None

    if "publico" in datos:
        proyecto.publico = _limpiar_subdiccionario(datos.get("publico"), CLAVES_PUBLICO)

    if "oferta" in datos:
        proyecto.oferta = _limpiar_subdiccionario(datos.get("oferta"), CLAVES_OFERTA)

    if "accion_deseada" in datos:
        accion_deseada = datos.get("accion_deseada") or None
        if accion_deseada is not None and accion_deseada not in ACCIONES_SUGERIDAS:
            return None, "La acción deseada indicada no es válida."
        proyecto.accion_deseada = accion_deseada
    if "accion_detalle" in datos:
        proyecto.accion_detalle = (datos.get("accion_detalle") or "").strip() or None

    if "presupuesto_produccion" in datos:
        proyecto.presupuesto_produccion = _leer_float_o_none(datos.get("presupuesto_produccion"))
    if "presupuesto_pauta" in datos:
        proyecto.presupuesto_pauta = _leer_float_o_none(datos.get("presupuesto_pauta"))
    if "moneda" in datos:
        proyecto.moneda = (datos.get("moneda") or "CRC").strip() or "CRC"

    if "fecha_inicio" in datos:
        proyecto.fecha_inicio = datos.get("fecha_inicio")
    if "fecha_fin" in datos:
        proyecto.fecha_fin = datos.get("fecha_fin")
    if "sin_fecha_definida" in datos:
        proyecto.sin_fecha_definida = bool(datos.get("sin_fecha_definida"))

    if "identidad_marca_brief" in datos:
        proyecto.identidad_marca_brief = _limpiar_subdiccionario(datos.get("identidad_marca_brief"), CLAVES_IDENTIDAD_BRIEF)

    if "informacion_adicional" in datos:
        proyecto.informacion_adicional = (datos.get("informacion_adicional") or "").strip() or None

    db.session.commit()
    return proyecto, None


def _leer_float_o_none(valor):
    if valor in (None, ""):
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def detectar_campos_faltantes(proyecto):
    """Lista de textos en español describiendo que falta por definir --
    nunca inventa la respuesta, solo señala la pregunta pendiente (Paso
    4, punto 13). Reglas deterministicas, no depende de IA ni de que
    ANTHROPIC_API_KEY este configurada."""
    faltantes = []

    if not proyecto.objetivo_tipo:
        faltantes.append("Falta definir qué quiere lograr con este proyecto.")
    elif proyecto.objetivo_tipo == "otro" and not proyecto.objetivo_detalle:
        faltantes.append("Falta describir el objetivo (se marcó \"Otro\").")

    if not proyecto.accion_deseada:
        faltantes.append("Falta definir qué acción queremos que realice el cliente.")
    elif proyecto.accion_deseada == "otro" and not proyecto.accion_detalle:
        faltantes.append("Falta describir la acción deseada (se marcó \"Otro\").")

    if not proyecto.publico:
        faltantes.append("Todavía no se definió a quién queremos llegar (público objetivo).")

    if not proyecto.oferta:
        faltantes.append("Todavía no se definió qué vamos a promocionar (producto, servicio u oferta).")

    if proyecto.fecha_inicio is None and proyecto.fecha_fin is None and not proyecto.sin_fecha_definida:
        faltantes.append("Falta indicar cuándo quiere comenzar o marcar \"sin fecha definida\".")

    return faltantes


MINIMOS_PARA_CONFIRMAR = ["objetivo_tipo", "accion_deseada"]


def confirmar_brief(empresa_id, proyecto_id):
    """(proyecto_o_None, error_o_None). Solo exige lo minimo indispensable
    (objetivo + accion deseada, con su detalle si es "otro") -- el resto
    del brief puede quedar incompleto/"por definir" y confirmarse igual,
    tal como el enunciado permite explicitamente para el presupuesto."""
    proyecto = obtener_proyecto(empresa_id, proyecto_id)
    if proyecto is None:
        return None, "El proyecto no existe o no pertenece a esta empresa."

    if not proyecto.objetivo_tipo:
        return None, "Falta definir qué quiere lograr con este proyecto antes de confirmar."
    if proyecto.objetivo_tipo == "otro" and not proyecto.objetivo_detalle:
        return None, "Falta describir el objetivo (se marcó \"Otro\") antes de confirmar."
    if not proyecto.accion_deseada:
        return None, "Falta definir qué acción queremos que realice el cliente antes de confirmar."
    if proyecto.accion_deseada == "otro" and not proyecto.accion_detalle:
        return None, "Falta describir la acción deseada (se marcó \"Otro\") antes de confirmar."

    from app.extensions import db

    proyecto.estado = "confirmado"
    db.session.commit()
    return proyecto, None


def _texto_presupuesto(valor, moneda):
    return "Por definir" if valor is None else f"{valor} {moneda}"


def _texto_plazo(proyecto):
    if proyecto.sin_fecha_definida and not proyecto.fecha_inicio and not proyecto.fecha_fin:
        return "Sin fecha definida"
    inicio = proyecto.fecha_inicio.isoformat() if proyecto.fecha_inicio else "Por definir"
    fin = proyecto.fecha_fin.isoformat() if proyecto.fecha_fin else "Por definir"
    return f"{inicio} – {fin}"


def construir_resumen(empresa_id, proyecto):
    """Resumen automatico de las 9 secciones del brief (Paso 4, punto
    11) para la pantalla de validacion "esto es lo que entendimos". La
    identidad de marca combina lo que YA existe en Publi Marketing
    (nombre comercial, colores, logo -- via app/services/marca.py) con
    lo que es especifico de este brief (tono, estilo, personalidad,
    restricciones), sin duplicar la primera parte en cada proyecto."""
    from app.services.marca import obtener_identidad, obtener_logo_principal

    identidad_empresa = obtener_identidad(empresa_id)
    logo_principal = obtener_logo_principal(empresa_id)

    return {
        "objetivo": {
            "tipo": proyecto.objetivo_tipo,
            "etiqueta": ETIQUETAS_OBJETIVOS.get(proyecto.objetivo_tipo, proyecto.objetivo_tipo),
            "detalle": proyecto.objetivo_detalle,
        },
        "publico": dict(proyecto.publico or {}),
        "oferta": dict(proyecto.oferta or {}),
        "mensaje_principal": (proyecto.oferta or {}).get("beneficio_principal") or (proyecto.oferta or {}).get("diferenciador"),
        "accion_deseada": {
            "tipo": proyecto.accion_deseada,
            "etiqueta": ETIQUETAS_ACCIONES.get(proyecto.accion_deseada, proyecto.accion_deseada),
            "detalle": proyecto.accion_detalle,
        },
        "presupuesto": {
            "produccion": _texto_presupuesto(proyecto.presupuesto_produccion, proyecto.moneda),
            "pauta": _texto_presupuesto(proyecto.presupuesto_pauta, proyecto.moneda),
        },
        "plazo": _texto_plazo(proyecto),
        "marca": {
            "nombre_comercial": identidad_empresa.nombre_comercial if identidad_empresa else None,
            "color_principal": identidad_empresa.color_principal if identidad_empresa else None,
            "color_secundario": identidad_empresa.color_secundario if identidad_empresa else None,
            "tiene_logo": logo_principal is not None,
            **dict(proyecto.identidad_marca_brief or {}),
        },
        "informacion_adicional": proyecto.informacion_adicional,
    }


def sugerir_completado_con_ia(empresa, proyecto):
    """(texto_o_None, error_o_None). Ayuda opcional de Claude para
    ordenar/redactar que falta (Paso 4, punto 13) -- NUNCA inventa la
    respuesta, solo reformula los campos_faltantes ya detectados por
    reglas en detectar_campos_faltantes(). Reutiliza la unica capa de
    IA existente (app/services/ia.py), igual que estratega_ia.py."""
    from app.services.ia import generar_respuesta

    faltantes = detectar_campos_faltantes(proyecto)
    if not faltantes:
        return "El brief ya tiene toda la información mínima necesaria.", None

    resumen_actual = construir_resumen(empresa.id, proyecto)
    system = (
        "Eres un asistente que ayuda a completar el brief de una campaña de "
        "marketing para una pequeña empresa en Costa Rica. NUNCA inventes "
        "información que el usuario no dio -- tu única tarea es explicar, en "
        "una lista breve y clara, qué preguntas todavía necesitan respuesta. "
        "No propongas respuestas, solo formula las preguntas de forma amable."
    )
    mensaje = (
        f"Brief actual del proyecto \"{proyecto.nombre}\":\n{resumen_actual}\n\n"
        f"Campos detectados como pendientes:\n" + "\n".join(f"- {f}" for f in faltantes)
    )

    texto, _uso, error = generar_respuesta([{"role": "user", "content": mensaje}], system=system)
    if error:
        return None, error
    return texto, None
