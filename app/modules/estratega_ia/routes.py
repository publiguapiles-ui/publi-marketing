"""Estratega IA (Paso 10): interfaz de conversacion con Claude dentro
de Publi Marketing. Ninguna llamada a Anthropic ni a la Graph API de
Meta ocurre aqui -- esta ruta solo orquesta: valida la empresa activa,
llama a app/services/estratega_ia.py (que a su vez reutiliza
inteligencia.py y proyectos_estrategicos.py) y renderiza/serializa.
"""

from flask import Blueprint, abort, jsonify, render_template, request

from app.core.auth import obtener_usuario_actual
from app.core.decorators import login_required
from app.core.empresas import obtener_empresa_activa
from app.services.estratega_ia import (
    LIMITE_MENSAJES_DIARIOS_POR_EMPRESA,
    LIMITE_MENSAJES_POR_CONVERSACION,
    construir_contexto,
    crear_conversacion,
    listar_conversaciones_empresa,
    obtener_conversacion,
    responder,
)
from app.services.ia import ia_configurada
from app.services.meta.cuentas_service import listar_entidades_empresa
from app.services.meta.proyectos_estrategicos import listar_proyectos_empresa, obtener_proyecto
from app.services.periodos import ETIQUETAS_PERIODOS, PERIODOS_PREDEFINIDOS

estratega_ia_bp = Blueprint("estratega_ia", __name__, url_prefix="/marketing/estratega-ia")


def _empresa_activa_o_404():
    empresa, rol = obtener_empresa_activa()
    if empresa is None:
        abort(404)
    return empresa, rol


def _serializar_conversacion(c):
    return {
        "id": c.id,
        "titulo": c.titulo or "Nueva conversación",
        "proyecto_id": c.proyecto_id,
        "proyecto_nombre": c.proyecto.nombre if c.proyecto else None,
        "creado_en": c.creado_en.isoformat(),
        "actualizado_en": c.actualizado_en.isoformat(),
    }


def _serializar_mensaje(m):
    return {
        "id": m.id,
        "rol": m.rol,
        "contenido": m.contenido,
        "creado_en": m.creado_en.isoformat(),
        "contexto_utilizado": m.contexto_utilizado,
        "modelo": m.modelo,
        "tokens_entrada": m.tokens_entrada,
        "tokens_salida": m.tokens_salida,
        "costo_estimado_usd": m.costo_estimado_usd,
    }


def _leer_periodo(args):
    periodo = args.get("periodo") or "ultimos_30_dias"
    if periodo not in PERIODOS_PREDEFINIDOS or periodo == "personalizado":
        periodo = "ultimos_30_dias"
    return periodo


@estratega_ia_bp.get("/")
@login_required
def index():
    empresa, _rol = _empresa_activa_o_404()

    conversaciones = listar_conversaciones_empresa(empresa.id)
    cuentas = listar_entidades_empresa(empresa.id, tipo="cuenta_publicitaria")
    proyectos = listar_proyectos_empresa(empresa.id)

    proyecto_id = request.args.get("proyecto_id", type=int)
    conversacion_id = request.args.get("conversacion_id", type=int)
    cuenta_id = request.args.get("cuenta_id", type=int)
    periodo_inicial = _leer_periodo(request.args)

    proyecto_inicial = None
    if proyecto_id is not None:
        proyecto_inicial = obtener_proyecto(empresa.id, proyecto_id)
        if proyecto_inicial is None:
            abort(404)

    conversacion_inicial = None
    if conversacion_id is not None:
        conversacion_inicial = obtener_conversacion(empresa.id, conversacion_id)
        if conversacion_inicial is None:
            abort(404)

    return render_template(
        "estratega_ia/index.html",
        empresa_activa=empresa,
        conversaciones=[_serializar_conversacion(c) for c in conversaciones],
        cuentas=cuentas,
        proyectos=proyectos,
        proyecto_inicial_id=proyecto_inicial.id if proyecto_inicial else (proyecto_id if proyecto_id else None),
        conversacion_inicial_id=conversacion_inicial.id if conversacion_inicial else None,
        cuenta_inicial_id=cuenta_id,
        periodo_inicial=periodo_inicial,
        ia_configurada=ia_configurada(),
        periodos=PERIODOS_PREDEFINIDOS,
        etiquetas_periodos=ETIQUETAS_PERIODOS,
        limite_mensajes_conversacion=LIMITE_MENSAJES_POR_CONVERSACION,
        limite_mensajes_diarios=LIMITE_MENSAJES_DIARIOS_POR_EMPRESA,
    )


@estratega_ia_bp.get("/conversaciones")
@login_required
def conversaciones_lista():
    empresa, _rol = _empresa_activa_o_404()
    return jsonify({"ok": True, "conversaciones": [_serializar_conversacion(c) for c in listar_conversaciones_empresa(empresa.id)]})


@estratega_ia_bp.post("/conversaciones")
@login_required
def conversaciones_crear():
    empresa, _rol = _empresa_activa_o_404()
    usuario = obtener_usuario_actual()
    datos = request.get_json(silent=True) or {}

    conversacion, error = crear_conversacion(empresa.id, usuario["id"], proyecto_id=datos.get("proyecto_id"))
    if error:
        return jsonify({"ok": False, "error": error}), 400
    return jsonify({"ok": True, "conversacion": _serializar_conversacion(conversacion)}), 201


@estratega_ia_bp.get("/conversaciones/<int:conversacion_id>")
@login_required
def conversaciones_detalle(conversacion_id):
    empresa, _rol = _empresa_activa_o_404()
    conversacion = obtener_conversacion(empresa.id, conversacion_id)
    if conversacion is None:
        return jsonify({"ok": False, "error": "La conversación no existe o no pertenece a esta empresa."}), 404

    return jsonify({
        "ok": True,
        "conversacion": _serializar_conversacion(conversacion),
        "mensajes": [_serializar_mensaje(m) for m in conversacion.mensajes],
    })


@estratega_ia_bp.post("/conversaciones/<int:conversacion_id>/mensajes")
@login_required
def conversaciones_enviar_mensaje(conversacion_id):
    empresa, _rol = _empresa_activa_o_404()
    conversacion = obtener_conversacion(empresa.id, conversacion_id)
    if conversacion is None:
        return jsonify({"ok": False, "error": "La conversación no existe o no pertenece a esta empresa."}), 404

    datos = request.get_json(silent=True) or {}
    mensaje = datos.get("mensaje")
    cuenta_publicitaria_id = datos.get("cuenta_publicitaria_id")
    periodo = datos.get("periodo") or "ultimos_30_dias"
    if periodo not in PERIODOS_PREDEFINIDOS or periodo == "personalizado":
        periodo = "ultimos_30_dias"

    mensaje_asistente, error = responder(
        empresa, conversacion, mensaje, cuenta_publicitaria_id=cuenta_publicitaria_id, periodo_clave=periodo,
    )
    if error:
        return jsonify({"ok": False, "error": error}), 400
    return jsonify({"ok": True, "mensaje": _serializar_mensaje(mensaje_asistente)})


@estratega_ia_bp.get("/contexto")
@login_required
def contexto():
    """Resumen ligero del contexto automatico (Paso 10, punto 2) --
    para el panel derecho de la interfaz. Nunca incluye el detalle
    completo ni ningun secreto, solo lo que estratega_ia.py ya arma
    como resumen de auditoria."""
    empresa, _rol = _empresa_activa_o_404()

    cuenta_publicitaria_id = request.args.get("cuenta_id", type=int)
    periodo = _leer_periodo(request.args)
    proyecto_id = request.args.get("proyecto_id", type=int)

    proyecto = None
    if proyecto_id is not None:
        proyecto = obtener_proyecto(empresa.id, proyecto_id)
        if proyecto is None:
            return jsonify({"ok": False, "error": "El proyecto no existe o no pertenece a esta empresa."}), 404

    _informe, resumen, error = construir_contexto(empresa, cuenta_publicitaria_id, periodo, proyecto=proyecto)
    if error:
        return jsonify({"ok": True, "contexto": None, "error": error})
    return jsonify({"ok": True, "contexto": resumen, "error": None})
