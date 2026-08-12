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
from app.models import TIPOS_LOGO, Empresa, Rol, UsuarioEmpresaRol
from app.services.marca import (
    color_valido,
    crear_logo,
    eliminar_logo,
    guardar_identidad,
    marcar_logo_marca_agua,
    marcar_logo_principal,
    obtener_identidad,
    obtener_logo,
    obtener_logos_empresa,
    reemplazar_archivo_logo,
)
from app.services.storage import (
    TAMANO_MAXIMO_BYTES,
    detectar_tipo_mime_real,
    ruta_logo,
    storage_configurado,
    subir_archivo,
    url_firmada,
)

empresas_bp = Blueprint("empresas", __name__, url_prefix="/empresas")


def _generar_slug(nombre):
    base = re.sub(r"[^a-z0-9]+", "-", nombre.strip().lower()).strip("-") or "empresa"
    slug = base
    contador = 2
    while db.session.query(Empresa).filter_by(slug=slug).first() is not None:
        slug = f"{base}-{contador}"
        contador += 1
    return slug


def _obtener_empresa_autorizada(slug):
    """Empresa + usuario actual, o abort(404) si no tiene acceso.

    404 (no 403) deliberado: no confirmamos ni siquiera que la empresa
    exista a un usuario sin acceso a ella. Punto unico de validacion
    para todas las rutas de este blueprint que reciben un slug.
    """
    usuario = obtener_usuario_actual()
    empresa = db.session.query(Empresa).filter_by(slug=slug).first()
    if empresa is None or not usuario_tiene_acceso_a_empresa(usuario["id"], empresa.id):
        abort(404)
    return empresa, usuario


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
    empresa, usuario = _obtener_empresa_autorizada(slug)
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


# --- Identidad de marca -----------------------------------------------

@empresas_bp.route("/<slug>/marca", methods=["GET", "POST"])
@login_required
def marca(slug):
    empresa, _usuario = _obtener_empresa_autorizada(slug)
    error = None

    if request.method == "POST":
        nombre_comercial = (request.form.get("nombre_comercial") or "").strip()
        color_principal = (request.form.get("color_principal") or "").strip()
        color_secundario = (request.form.get("color_secundario") or "").strip()
        color_texto = (request.form.get("color_texto") or "").strip()
        color_fondo = (request.form.get("color_fondo") or "").strip()

        if not all(color_valido(c) for c in (color_principal, color_secundario, color_texto, color_fondo)):
            error = "Los colores deben ser valores HEX válidos, por ejemplo #E31E24."
        else:
            guardar_identidad(
                empresa.id, nombre_comercial, color_principal, color_secundario, color_texto, color_fondo
            )
            return redirect(url_for("empresas.marca", slug=slug))

    identidad = obtener_identidad(empresa.id)
    return render_template("empresas/marca.html", empresa=empresa, identidad=identidad, error=error)


# --- Biblioteca de logos ------------------------------------------------

@empresas_bp.get("/<slug>/logos")
@login_required
def logos(slug):
    empresa, _usuario = _obtener_empresa_autorizada(slug)
    lista = obtener_logos_empresa(empresa.id)
    logos_con_url = [(logo, url_firmada(logo.ruta_storage)) for logo in lista]
    return render_template("empresas/logos.html", empresa=empresa, logos=logos_con_url)


@empresas_bp.route("/<slug>/logos/nuevo", methods=["GET", "POST"])
@login_required
def logo_nuevo(slug):
    empresa, usuario = _obtener_empresa_autorizada(slug)
    error = None

    if request.method == "POST":
        tipo = request.form.get("tipo")
        archivo = request.files.get("archivo")

        if tipo not in TIPOS_LOGO:
            error = "Selecciona un tipo de logo válido."
        elif archivo is None or archivo.filename == "":
            error = "Selecciona un archivo."
        else:
            contenido = archivo.read()
            if len(contenido) > TAMANO_MAXIMO_BYTES:
                error = "El archivo supera el tamaño máximo permitido (15 MB)."
            else:
                tipo_mime = detectar_tipo_mime_real(contenido)
                if tipo_mime is None:
                    error = "Formato no soportado. Usa PNG, JPG o WebP."
                elif not storage_configurado():
                    error = "El almacenamiento de archivos no está disponible en este momento."
                else:
                    ruta = ruta_logo(empresa.id, tipo, tipo_mime)
                    try:
                        subir_archivo(ruta, contenido, tipo_mime)
                    except Exception:
                        error = "No se pudo subir el archivo. Intenta de nuevo."
                    else:
                        crear_logo(
                            empresa.id, tipo, archivo.filename, ruta, tipo_mime, len(contenido), usuario["id"]
                        )
                        return redirect(url_for("empresas.logos", slug=slug))

    return render_template("empresas/logo_nuevo.html", empresa=empresa, error=error, tipos=TIPOS_LOGO)


@empresas_bp.post("/<slug>/logos/<int:logo_id>/principal")
@login_required
def logo_marcar_principal(slug, logo_id):
    empresa, _usuario = _obtener_empresa_autorizada(slug)
    marcar_logo_principal(empresa.id, logo_id)
    return redirect(url_for("empresas.logos", slug=slug))


@empresas_bp.post("/<slug>/logos/<int:logo_id>/marca-agua")
@login_required
def logo_marcar_marca_agua(slug, logo_id):
    empresa, _usuario = _obtener_empresa_autorizada(slug)
    marcar_logo_marca_agua(empresa.id, logo_id)
    return redirect(url_for("empresas.logos", slug=slug))


@empresas_bp.route("/<slug>/logos/<int:logo_id>/reemplazar", methods=["GET", "POST"])
@login_required
def logo_reemplazar(slug, logo_id):
    empresa, _usuario = _obtener_empresa_autorizada(slug)
    logo = obtener_logo(empresa.id, logo_id)
    if logo is None or not logo.activo:
        abort(404)

    error = None

    if request.method == "POST":
        archivo = request.files.get("archivo")
        if archivo is None or archivo.filename == "":
            error = "Selecciona un archivo."
        else:
            contenido = archivo.read()
            if len(contenido) > TAMANO_MAXIMO_BYTES:
                error = "El archivo supera el tamaño máximo permitido (15 MB)."
            else:
                tipo_mime = detectar_tipo_mime_real(contenido)
                if tipo_mime is None:
                    error = "Formato no soportado. Usa PNG, JPG o WebP."
                else:
                    ruta = ruta_logo(empresa.id, logo.tipo, tipo_mime)
                    try:
                        subir_archivo(ruta, contenido, tipo_mime)
                    except Exception:
                        error = "No se pudo subir el archivo. Intenta de nuevo."
                    else:
                        reemplazar_archivo_logo(
                            empresa.id, logo_id, archivo.filename, ruta, tipo_mime, len(contenido)
                        )
                        return redirect(url_for("empresas.logos", slug=slug))

    return render_template("empresas/logo_reemplazar.html", empresa=empresa, logo=logo, error=error)


@empresas_bp.route("/<slug>/logos/<int:logo_id>/eliminar", methods=["GET", "POST"])
@login_required
def logo_eliminar(slug, logo_id):
    empresa, _usuario = _obtener_empresa_autorizada(slug)
    logo = obtener_logo(empresa.id, logo_id)
    if logo is None or not logo.activo:
        abort(404)

    if request.method == "POST":
        eliminar_logo(empresa.id, logo_id)
        return redirect(url_for("empresas.logos", slug=slug))

    return render_template("empresas/logo_eliminar.html", empresa=empresa, logo=logo)
