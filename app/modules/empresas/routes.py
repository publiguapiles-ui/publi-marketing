import re

from flask import Blueprint, abort, redirect, render_template, request, url_for

from app.core.auth import obtener_usuario_actual
from app.core.decorators import login_required
from app.core.empresas import (
    establecer_empresa_activa,
    obtener_empresa_activa,
    obtener_empresas_usuario,
    obtener_rol_usuario_en_empresa,
    usuario_tiene_acceso_a_empresa,
)
from app.extensions import db
from app.models import Empresa, Rol, UsuarioEmpresaRol

empresas_bp = Blueprint("empresas", __name__, url_prefix="/empresas")


def _generar_slug(nombre):
    base = re.sub(r"[^a-z0-9]+", "-", nombre.strip().lower()).strip("-") or "empresa"
    slug = base
    contador = 2
    while db.session.query(Empresa).filter_by(slug=slug).first() is not None:
        slug = f"{base}-{contador}"
        contador += 1
    return slug


@empresas_bp.get("/")
@login_required
def index():
    usuario = obtener_usuario_actual()
    empresas = obtener_empresas_usuario(usuario["id"])
    empresa_activa, _ = obtener_empresa_activa()
    return render_template("empresas/listado.html", empresas=empresas, empresa_activa=empresa_activa)


@empresas_bp.route("/nueva", methods=["GET", "POST"])
@login_required
def nueva():
    error = None
    nombre_enviado = ""

    if request.method == "POST":
        nombre = (request.form.get("nombre") or "").strip()
        nombre_enviado = nombre

        if not nombre:
            error = "El nombre de la empresa es obligatorio."
        else:
            usuario = obtener_usuario_actual()

            rol_admin = db.session.query(Rol).filter_by(nombre="Administrador").first()
            if rol_admin is None:
                error = "No se pudo crear la empresa: falta el rol Administrador en el sistema."
            else:
                empresa = Empresa(nombre=nombre, slug=_generar_slug(nombre))
                db.session.add(empresa)
                db.session.flush()  # asigna empresa.id sin cerrar la transaccion

                relacion = UsuarioEmpresaRol(
                    usuario_id=usuario["id"], empresa_id=empresa.id, rol_id=rol_admin.id
                )
                db.session.add(relacion)
                db.session.commit()

                establecer_empresa_activa(empresa.id)
                return redirect(url_for("dashboard.index"))

    return render_template("empresas/nueva.html", error=error, nombre=nombre_enviado)


@empresas_bp.get("/<slug>")
@login_required
def detalle(slug):
    usuario = obtener_usuario_actual()
    empresa = db.session.query(Empresa).filter_by(slug=slug).first()

    # 404 (no 403) deliberado: no confirmamos ni siquiera que la empresa
    # exista a un usuario sin acceso a ella.
    if empresa is None or not usuario_tiene_acceso_a_empresa(usuario["id"], empresa.id):
        abort(404)

    rol = obtener_rol_usuario_en_empresa(usuario["id"], empresa.id)
    return render_template("empresas/detalle.html", empresa=empresa, rol=rol)


@empresas_bp.post("/activa")
@login_required
def cambiar_activa():
    empresa_id = request.form.get("empresa_id", type=int)
    if empresa_id is not None:
        establecer_empresa_activa(empresa_id)

    destino = request.referrer
    if not destino or not destino.startswith(request.host_url):
        destino = url_for("dashboard.index")
    return redirect(destino)
