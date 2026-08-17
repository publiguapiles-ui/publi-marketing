"""API WhatsApp: conexion con WhatsApp Business Platform (Cloud API de
Meta) y panel de conversaciones pendientes. Solo lectura -- no envia
mensajes, no procesa IA, no es un CRM (ver enunciado punto 13).

El webhook (`/webhook`) es la UNICA ruta publica de este blueprint --
Meta la llama directamente, sin sesion de usuario, por eso NO lleva
@login_required. Todas las demas rutas requieren empresa activa.
"""

from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for

from app.core.auth import obtener_usuario_actual
from app.core.decorators import login_required
from app.core.empresas import obtener_empresa_activa
from app.services.whatsapp.conexion import guardar_conexion, obtener_conexion
from app.services.whatsapp.panel import construir_panel, marcar_conversacion_vista
from app.services.whatsapp.webhook import procesar_evento, verificar_challenge

api_whatsapp_bp = Blueprint("api_whatsapp", __name__, url_prefix="/api-whatsapp")


def _empresa_activa_o_404():
    empresa, rol = obtener_empresa_activa()
    if empresa is None:
        abort(404)
    return empresa, rol


@api_whatsapp_bp.get("/")
@login_required
def index():
    empresa, _rol = _empresa_activa_o_404()
    return render_template("api_whatsapp/index.html", empresa_activa=empresa, panel=construir_panel(empresa.id))


@api_whatsapp_bp.get("/panel")
@login_required
def panel_json():
    empresa, _rol = _empresa_activa_o_404()
    return jsonify({"ok": True, "panel": construir_panel(empresa.id)})


@api_whatsapp_bp.get("/configuracion")
@login_required
def configuracion_formulario():
    empresa, _rol = _empresa_activa_o_404()
    return render_template(
        "api_whatsapp/configuracion.html",
        empresa_activa=empresa,
        conexion=obtener_conexion(empresa.id),
        url_webhook=url_for("api_whatsapp.webhook_recibir", _external=True),
    )


@api_whatsapp_bp.post("/configuracion")
@login_required
def configuracion_guardar():
    empresa, _rol = _empresa_activa_o_404()
    usuario = obtener_usuario_actual()
    datos = request.form

    conexion, error = guardar_conexion(
        empresa.id, usuario["id"],
        phone_number_id=datos.get("phone_number_id"),
        whatsapp_business_account_id=datos.get("whatsapp_business_account_id"),
        access_token=datos.get("access_token"),
        verify_token=datos.get("verify_token"),
    )
    if error:
        return render_template(
            "api_whatsapp/configuracion.html",
            empresa_activa=empresa,
            conexion=obtener_conexion(empresa.id),
            url_webhook=url_for("api_whatsapp.webhook_recibir", _external=True),
            error=error,
        ), 400
    return redirect(url_for("api_whatsapp.index"))


@api_whatsapp_bp.post("/conversaciones/<int:conversacion_id>/marcar-vista")
@login_required
def marcar_vista(conversacion_id):
    empresa, _rol = _empresa_activa_o_404()
    if not marcar_conversacion_vista(empresa.id, conversacion_id):
        return jsonify({"ok": False, "error": "La conversación no existe o no pertenece a esta empresa."}), 404
    return jsonify({"ok": True})


# --- Webhook publico (llamado por Meta -- nunca lleva sesion de usuario) ---------------

@api_whatsapp_bp.get("/webhook")
def webhook_verificar():
    resultado = verificar_challenge(
        request.args.get("hub.mode"), request.args.get("hub.verify_token"), request.args.get("hub.challenge"),
    )
    if resultado is None:
        abort(403)
    return resultado, 200


@api_whatsapp_bp.post("/webhook")
def webhook_recibir():
    procesar_evento(request.get_json(silent=True) or {})
    # Meta reintenta el webhook si no recibe 200 -- siempre se confirma
    # recepcion aunque la entrada no se haya podido asociar a ninguna
    # empresa (eso queda registrado como "no reconocida", nunca como
    # error 500 que dispare reintentos infinitos).
    return jsonify({"status": "ok"}), 200
