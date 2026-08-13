"""Datos de Meta (Paso 1): pantalla de Conexiones.

Ninguna llamada a la Graph API ocurre aqui directamente -- esta ruta
solo orquesta: valida la empresa activa, llama a servicios internos
(app/services/meta/*, app/services/metricas.py) y renderiza. Ningun
detalle de la API de Meta (URLs, campos, tokens) vive en este archivo
ni en los templates.
"""

from flask import Blueprint, abort, jsonify, redirect, render_template, request, session, url_for

from app.core.auth import obtener_usuario_actual
from app.core.decorators import login_required
from app.core.empresas import obtener_empresa_activa
from app.services.meta.auth_service import (
    SCOPES_PREDETERMINADOS,
    construir_url_autorizacion,
    generar_estado_csrf,
    intercambiar_codigo_por_token,
    intercambiar_por_token_larga_duracion,
    meta_configurado,
    obtener_identidad_meta,
)
from app.services.meta.client import MetaAPIError
from app.services.meta.conexiones import (
    crear_conexion,
    desconectar,
    listar_conexiones_empresa,
    obtener_conexion_activa,
)
from app.services.meta.cuentas_service import descubrir_cuentas, listar_entidades_empresa

datos_meta_bp = Blueprint("datos_meta", __name__, url_prefix="/datos-meta")


def _empresa_activa_o_404():
    empresa, rol = obtener_empresa_activa()
    if empresa is None:
        abort(404)
    return empresa, rol


@datos_meta_bp.get("/")
@login_required
def index():
    # Paso 1: solo existe Conexiones. Resumen/Campañas/Analítica/
    # Informes/Comparativas/Claude llegan en pasos futuros -- ver informe.
    return redirect(url_for("datos_meta.conexiones"))


@datos_meta_bp.get("/conexiones")
@login_required
def conexiones():
    empresa, _rol = _empresa_activa_o_404()

    conexion = obtener_conexion_activa(empresa.id)
    entidades_por_tipo = {}
    if conexion is not None:
        for tipo in ("cuenta_publicitaria", "pagina", "cuenta_instagram"):
            entidades_por_tipo[tipo] = listar_entidades_empresa(empresa.id, tipo=tipo)

    return render_template(
        "datos_meta/conexiones.html",
        empresa_activa=empresa,
        conexion=conexion,
        entidades_por_tipo=entidades_por_tipo,
        meta_configurado=meta_configurado(),
        historial=listar_conexiones_empresa(empresa.id),
    )


@datos_meta_bp.get("/conexiones/conectar")
@login_required
def conectar():
    empresa, _rol = _empresa_activa_o_404()

    if not meta_configurado():
        # Nunca se simula una conexion exitosa: si faltan las
        # variables de entorno, se vuelve a la pantalla de Conexiones,
        # que ya muestra el aviso de "Meta no está configurado".
        return redirect(url_for("datos_meta.conexiones"))

    estado = generar_estado_csrf()
    session["meta_oauth_estado"] = estado
    session["meta_oauth_empresa_id"] = empresa.id
    return redirect(construir_url_autorizacion(estado))


@datos_meta_bp.get("/conexiones/callback")
@login_required
def callback():
    empresa, _rol = _empresa_activa_o_404()

    error_meta = request.args.get("error")
    if error_meta:
        mensaje = request.args.get("error_description") or error_meta
        return render_template("datos_meta/conexiones_error.html", empresa_activa=empresa, mensaje=mensaje)

    estado_recibido = request.args.get("state")
    estado_esperado = session.pop("meta_oauth_estado", None)
    empresa_id_esperada = session.pop("meta_oauth_empresa_id", None)
    if not estado_recibido or estado_recibido != estado_esperado or empresa_id_esperada != empresa.id:
        return render_template(
            "datos_meta/conexiones_error.html",
            empresa_activa=empresa,
            mensaje="La solicitud de conexión no es válida o expiró. Intenta conectar de nuevo.",
        )

    codigo = request.args.get("code")
    if not codigo:
        return render_template(
            "datos_meta/conexiones_error.html", empresa_activa=empresa, mensaje="Meta no devolvió un código de autorización."
        )

    usuario = obtener_usuario_actual()
    try:
        token_corto = intercambiar_codigo_por_token(codigo)
        token_largo, expira_en_segundos = intercambiar_por_token_larga_duracion(token_corto)
        identidad = obtener_identidad_meta(token_largo)
    except MetaAPIError as exc:
        return render_template("datos_meta/conexiones_error.html", empresa_activa=empresa, mensaje=str(exc))

    crear_conexion(
        empresa.id,
        usuario["id"],
        identidad.get("id"),
        identidad.get("name"),
        token_largo,
        expira_en_segundos=expira_en_segundos,
        scopes=SCOPES_PREDETERMINADOS,
    )
    return redirect(url_for("datos_meta.conexiones"))


@datos_meta_bp.post("/conexiones/<int:conexion_id>/desconectar")
@login_required
def conexion_desconectar(conexion_id):
    empresa, _rol = _empresa_activa_o_404()
    ok, error = desconectar(empresa.id, conexion_id)
    if not ok:
        return jsonify({"ok": False, "error": error}), 400
    return jsonify({"ok": True})


@datos_meta_bp.post("/conexiones/sincronizar")
@login_required
def conexiones_sincronizar():
    """Descubre/actualiza cuentas publicitarias, páginas y cuentas de
    Instagram de la conexión activa. Manual (botón) por ahora -- la
    arquitectura de SincronizacionMeta ya deja espacio para que esto
    se dispare en segundo plano más adelante (ver informe, Pendientes).
    """
    empresa, _rol = _empresa_activa_o_404()
    resumen, error = descubrir_cuentas(empresa.id)
    if error:
        return jsonify({"ok": False, "error": error}), 400
    return jsonify({"ok": True, "resumen": resumen})
