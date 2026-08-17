"""Creacion de Marketing (Paso 4): objetivo y brief estrategico de una
campaña ANTES de pautar. Modulo completamente independiente de Datos
de Meta -- ninguna ruta de aqui llama a la Graph API de Meta ni
publica nada; solo administra el ProyectoMarketing via
app/services/creacion_marketing.py.
"""

from flask import Blueprint, abort, jsonify, render_template, request

from app.core.auth import obtener_usuario_actual
from app.core.decorators import login_required
from app.core.empresas import obtener_empresa_activa
from app.models import ACCIONES_SUGERIDAS, ESTADOS_PROYECTO_MARKETING, OBJETIVOS_SUGERIDOS
from app.services.creacion_marketing import (
    ETIQUETAS_ACCIONES,
    ETIQUETAS_OBJETIVOS,
    actualizar_brief,
    confirmar_brief,
    construir_resumen,
    crear_proyecto,
    detectar_campos_faltantes,
    listar_proyectos_empresa,
    obtener_proyecto,
    sugerir_completado_con_ia,
)
from app.services.ia import ia_configurada
from app.services.marca import obtener_identidad, obtener_logo_principal

creacion_marketing_bp = Blueprint("creacion_marketing", __name__, url_prefix="/creacion-marketing")


def _empresa_activa_o_404():
    empresa, rol = obtener_empresa_activa()
    if empresa is None:
        abort(404)
    return empresa, rol


def _serializar_proyecto(proyecto):
    return {
        "id": proyecto.id,
        "nombre": proyecto.nombre,
        "estado": proyecto.estado,
        "objetivo_tipo": proyecto.objetivo_tipo,
        "objetivo_detalle": proyecto.objetivo_detalle,
        "publico": dict(proyecto.publico or {}),
        "oferta": dict(proyecto.oferta or {}),
        "accion_deseada": proyecto.accion_deseada,
        "accion_detalle": proyecto.accion_detalle,
        "presupuesto_produccion": proyecto.presupuesto_produccion,
        "presupuesto_pauta": proyecto.presupuesto_pauta,
        "moneda": proyecto.moneda,
        "fecha_inicio": proyecto.fecha_inicio.isoformat() if proyecto.fecha_inicio else None,
        "fecha_fin": proyecto.fecha_fin.isoformat() if proyecto.fecha_fin else None,
        "sin_fecha_definida": proyecto.sin_fecha_definida,
        "identidad_marca_brief": dict(proyecto.identidad_marca_brief or {}),
        "informacion_adicional": proyecto.informacion_adicional,
        "creado_en": proyecto.creado_en.isoformat(),
        "actualizado_en": proyecto.actualizado_en.isoformat(),
    }


def _leer_fecha(valor):
    import datetime

    if not valor:
        return None
    try:
        return datetime.date.fromisoformat(valor)
    except ValueError:
        return None


@creacion_marketing_bp.get("/")
@login_required
def index():
    empresa, _rol = _empresa_activa_o_404()
    proyectos = listar_proyectos_empresa(empresa.id)
    return render_template(
        "creacion_marketing/index.html",
        empresa_activa=empresa,
        proyectos=[_serializar_proyecto(p) for p in proyectos],
        etiquetas_objetivos=ETIQUETAS_OBJETIVOS,
    )


@creacion_marketing_bp.post("/crear")
@login_required
def crear():
    empresa, _rol = _empresa_activa_o_404()
    usuario = obtener_usuario_actual()
    datos = request.get_json(silent=True) or {}

    proyecto, error = crear_proyecto(empresa.id, usuario["id"], datos.get("nombre"))
    if error:
        return jsonify({"ok": False, "error": error}), 400
    return jsonify({"ok": True, "proyecto_id": proyecto.id}), 201


@creacion_marketing_bp.get("/<int:proyecto_id>")
@login_required
def detalle(proyecto_id):
    empresa, _rol = _empresa_activa_o_404()
    proyecto = obtener_proyecto(empresa.id, proyecto_id)
    if proyecto is None:
        abort(404)

    identidad_empresa = obtener_identidad(empresa.id)
    logo_principal = obtener_logo_principal(empresa.id)

    return render_template(
        "creacion_marketing/detalle.html",
        empresa_activa=empresa,
        proyecto=_serializar_proyecto(proyecto),
        estados=ESTADOS_PROYECTO_MARKETING,
        objetivos_sugeridos=OBJETIVOS_SUGERIDOS,
        etiquetas_objetivos=ETIQUETAS_OBJETIVOS,
        acciones_sugeridas=ACCIONES_SUGERIDAS,
        etiquetas_acciones=ETIQUETAS_ACCIONES,
        ia_configurada=ia_configurada(),
        marca_existente={
            "nombre_comercial": identidad_empresa.nombre_comercial if identidad_empresa else None,
            "color_principal": identidad_empresa.color_principal if identidad_empresa else None,
            "tiene_logo": logo_principal is not None,
        },
    )


@creacion_marketing_bp.post("/<int:proyecto_id>/brief")
@login_required
def brief_actualizar(proyecto_id):
    empresa, _rol = _empresa_activa_o_404()
    datos = request.get_json(silent=True) or {}

    if "fecha_inicio" in datos:
        datos["fecha_inicio"] = _leer_fecha(datos["fecha_inicio"])
    if "fecha_fin" in datos:
        datos["fecha_fin"] = _leer_fecha(datos["fecha_fin"])

    proyecto, error = actualizar_brief(empresa.id, proyecto_id, datos)
    if error:
        return jsonify({"ok": False, "error": error}), 400
    return jsonify({"ok": True, "proyecto": _serializar_proyecto(proyecto)})


@creacion_marketing_bp.get("/<int:proyecto_id>/resumen")
@login_required
def resumen(proyecto_id):
    empresa, _rol = _empresa_activa_o_404()
    proyecto = obtener_proyecto(empresa.id, proyecto_id)
    if proyecto is None:
        return jsonify({"ok": False, "error": "El proyecto no existe o no pertenece a esta empresa."}), 404

    return jsonify({
        "ok": True,
        "resumen": construir_resumen(empresa.id, proyecto),
        "campos_faltantes": detectar_campos_faltantes(proyecto),
    })


@creacion_marketing_bp.post("/<int:proyecto_id>/confirmar")
@login_required
def confirmar(proyecto_id):
    empresa, _rol = _empresa_activa_o_404()

    proyecto, error = confirmar_brief(empresa.id, proyecto_id)
    if error:
        return jsonify({"ok": False, "error": error}), 400
    return jsonify({"ok": True, "proyecto": _serializar_proyecto(proyecto)})


@creacion_marketing_bp.post("/<int:proyecto_id>/ia/ayuda")
@login_required
def ia_ayuda(proyecto_id):
    """Ayuda opcional de Claude para ordenar que informacion falta
    (Paso 4, punto 13) -- nunca inventa la respuesta del brief."""
    empresa, _rol = _empresa_activa_o_404()
    proyecto = obtener_proyecto(empresa.id, proyecto_id)
    if proyecto is None:
        return jsonify({"ok": False, "error": "El proyecto no existe o no pertenece a esta empresa."}), 404

    texto, error = sugerir_completado_con_ia(empresa, proyecto)
    if error:
        return jsonify({"ok": False, "error": error}), 400
    return jsonify({"ok": True, "sugerencia": texto})
