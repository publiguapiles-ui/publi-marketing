"""Sistema anterior de solicitudes/citas.

Este modulo NO es parte del producto Publi Marketing (dashboard,
clientes, contenido, etc.). Es el prototipo construido antes de definir
la arquitectura final, aislado aqui bajo el prefijo /legacy para que
siga funcionando sin interferir con las rutas nuevas (en particular,
para liberar "/" para el dashboard). El codigo original sin modificar
queda ademas conservado en legacy_app_original.py, en la raiz del
proyecto.
"""

import os
import secrets
import string
import urllib.request
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request, send_from_directory
from supabase import create_client

legacy_bp = Blueprint("legacy_solicitudes", __name__, url_prefix="/legacy")

PUBLIC_DIR = Path(__file__).resolve().parents[3] / "public"

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY) if SUPABASE_URL and SUPABASE_ANON_KEY else None
supabase_admin = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None


def generar_codigo_seguimiento():
    alfabeto = string.ascii_uppercase + string.digits
    sufijo = "".join(secrets.choice(alfabeto) for _ in range(6))
    return f"SOL-{sufijo}"


@legacy_bp.get("/")
def index():
    return send_from_directory(PUBLIC_DIR, "index.html")


@legacy_bp.get("/style.css")
def style():
    return send_from_directory(PUBLIC_DIR, "style.css")


@legacy_bp.get("/script.js")
def script():
    return send_from_directory(PUBLIC_DIR, "script.js")


@legacy_bp.get("/health")
def health():
    db_status = "not_configured"
    if SUPABASE_URL and SUPABASE_ANON_KEY:
        try:
            req = urllib.request.Request(
                f"{SUPABASE_URL}/auth/v1/health",
                headers={"apikey": SUPABASE_ANON_KEY},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                db_status = "connected" if resp.status == 200 else "error"
        except Exception:
            db_status = "error"
    return jsonify({"status": "ok", "db": db_status})


@legacy_bp.post("/solicitudes")
def crear_solicitud():
    if supabase_admin is None:
        return jsonify({"error": "Supabase no está configurado"}), 500

    data = request.get_json(silent=True) or {}
    nombre = data.get("nombre")
    contacto = data.get("contacto")
    fecha_hora = data.get("fecha_hora")

    if not nombre or not contacto or not fecha_hora:
        return jsonify({"error": "nombre, contacto y fecha_hora son requeridos"}), 400

    try:
        datetime.fromisoformat(fecha_hora.replace("Z", "+00:00"))
    except ValueError:
        return jsonify({"error": "fecha_hora debe ser una fecha/hora ISO 8601 válida"}), 400

    codigo_seguimiento = generar_codigo_seguimiento()

    try:
        result = (
            supabase_admin.table("solicitudes")
            .insert(
                {
                    "nombre": nombre,
                    "contacto": contacto,
                    "fecha_hora": fecha_hora,
                    "codigo_seguimiento": codigo_seguimiento,
                    "estado": "pendiente",
                }
            )
            .execute()
        )
    except Exception as exc:
        return jsonify({"error": f"No se pudo crear la solicitud: {exc}"}), 502

    return jsonify(result.data[0]), 201


def buscar_solicitud(codigo):
    result = (
        supabase_admin.table("solicitudes")
        .select("*")
        .eq("codigo_seguimiento", codigo)
        .execute()
    )
    return result.data[0] if result.data else None


@legacy_bp.get("/solicitudes/<codigo>")
def obtener_solicitud(codigo):
    if supabase_admin is None:
        return jsonify({"error": "Supabase no está configurado"}), 500

    try:
        solicitud = buscar_solicitud(codigo)
    except Exception as exc:
        return jsonify({"error": f"No se pudo consultar la solicitud: {exc}"}), 502

    if solicitud is None:
        return jsonify({"error": f"No existe ninguna solicitud con el código '{codigo}'"}), 404

    return jsonify(solicitud), 200


@legacy_bp.patch("/solicitudes/<codigo>/confirmar")
def confirmar_solicitud(codigo):
    if supabase_admin is None:
        return jsonify({"error": "Supabase no está configurado"}), 500

    try:
        if buscar_solicitud(codigo) is None:
            return jsonify({"error": f"No existe ninguna solicitud con el código '{codigo}'"}), 404

        result = (
            supabase_admin.table("solicitudes")
            .update({"estado": "confirmada"})
            .eq("codigo_seguimiento", codigo)
            .execute()
        )
    except Exception as exc:
        return jsonify({"error": f"No se pudo confirmar la solicitud: {exc}"}), 502

    return jsonify(result.data[0]), 200
