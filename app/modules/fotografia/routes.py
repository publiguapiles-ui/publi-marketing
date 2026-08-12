"""Photo Studio: biblioteca fotografica (proyectos + carga + galeria).

Este paso es exclusivamente biblioteca -- ningun procesamiento de
imagen (color, recorte, formatos, logo automatico, IA) ocurre aqui.
Ver app/models/fotografia.py para la regla de "el original nunca se
modifica".

Todo se resuelve contra la empresa ACTIVA (no contra cualquier empresa
a la que el usuario tenga acceso): si cambias de empresa, un proyecto
o fotografia de la empresa anterior deja de ser accesible aunque el
ID se escriba directamente en la URL, hasta que esa empresa vuelva a
estar activa. Esto es intencional (ver Paso 4 y las pruebas de
aislamiento de este paso).
"""

from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for

from app.core.auth import obtener_usuario_actual
from app.core.decorators import login_required
from app.core.empresas import obtener_empresa_activa
from app.services.fotografia import (
    contar_fotografias,
    crear_fotografia,
    crear_proyecto,
    eliminar_fotografia,
    obtener_fotografia,
    obtener_fotografias_proyecto,
    obtener_proyecto,
    obtener_proyectos_empresa,
)
from app.services.storage import (
    BUCKET_FOTOGRAFIAS,
    TAMANO_MAXIMO_FOTO_BYTES,
    detectar_tipo_mime_real,
    ruta_fotografia_original,
    storage_configurado,
    subir_archivo,
    url_firmada,
)

fotografia_bp = Blueprint("fotografia", __name__, url_prefix="/photo-studio")


def _proyecto_de_empresa_activa(proyecto_id):
    """Empresa activa + proyecto, solo si el proyecto pertenece a esa
    empresa. abort(404) en cualquier otro caso (incluida la ausencia
    de empresa activa) -- nunca se confia en el proyecto_id de la URL
    por si solo.
    """
    empresa, rol = obtener_empresa_activa()
    if empresa is None:
        abort(404)
    proyecto = obtener_proyecto(empresa.id, proyecto_id)
    if proyecto is None:
        abort(404)
    return empresa, rol, proyecto


def _fotografia_de_empresa_activa(fotografia_id):
    empresa, rol = obtener_empresa_activa()
    if empresa is None:
        abort(404)
    foto = obtener_fotografia(empresa.id, fotografia_id)
    if foto is None or not foto.activo:
        abort(404)
    return empresa, rol, foto


@fotografia_bp.get("/")
@login_required
def index():
    empresa, _rol = obtener_empresa_activa()
    proyectos_con_conteo = []
    if empresa is not None:
        proyectos_con_conteo = [(p, contar_fotografias(p.id)) for p in obtener_proyectos_empresa(empresa.id)]
    return render_template("photo_studio/index.html", empresa_activa=empresa, proyectos=proyectos_con_conteo)


@fotografia_bp.route("/proyectos/nuevo", methods=["GET", "POST"])
@login_required
def proyecto_nuevo():
    empresa, _rol = obtener_empresa_activa()
    if empresa is None:
        abort(404)

    error = None
    nombre_enviado = ""
    descripcion_enviada = ""

    if request.method == "POST":
        nombre = (request.form.get("nombre") or "").strip()
        descripcion = (request.form.get("descripcion") or "").strip()
        nombre_enviado, descripcion_enviada = nombre, descripcion

        if not nombre:
            error = "El nombre del proyecto es obligatorio."
        else:
            usuario = obtener_usuario_actual()
            proyecto = crear_proyecto(empresa.id, nombre, descripcion, usuario["id"])
            return redirect(url_for("fotografia.proyecto_detalle", proyecto_id=proyecto.id))

    return render_template(
        "photo_studio/proyecto_nuevo.html",
        empresa_activa=empresa,
        error=error,
        nombre=nombre_enviado,
        descripcion=descripcion_enviada,
    )


@fotografia_bp.get("/proyectos/<int:proyecto_id>")
@login_required
def proyecto_detalle(proyecto_id):
    empresa, _rol, proyecto = _proyecto_de_empresa_activa(proyecto_id)
    fotos = obtener_fotografias_proyecto(proyecto.id)
    fotos_con_url = [(f, url_firmada(BUCKET_FOTOGRAFIAS, f.ruta_storage)) for f in fotos]
    return render_template(
        "photo_studio/proyecto_detalle.html", empresa_activa=empresa, proyecto=proyecto, fotos=fotos_con_url
    )


@fotografia_bp.post("/proyectos/<int:proyecto_id>/fotos")
@login_required
def subir_foto(proyecto_id):
    empresa, _rol, proyecto = _proyecto_de_empresa_activa(proyecto_id)
    usuario = obtener_usuario_actual()

    archivo = request.files.get("archivo")
    if archivo is None or archivo.filename == "":
        return jsonify({"ok": False, "error": "No se recibió ningún archivo."}), 400

    contenido = archivo.read()
    if len(contenido) > TAMANO_MAXIMO_FOTO_BYTES:
        return jsonify({"ok": False, "error": "El archivo supera el tamaño máximo permitido (30 MB)."}), 400

    tipo_mime = detectar_tipo_mime_real(contenido)
    if tipo_mime is None:
        return jsonify({"ok": False, "error": "Formato no soportado. Usa JPG, PNG o WebP."}), 400

    if not storage_configurado():
        return jsonify({"ok": False, "error": "El almacenamiento no está disponible en este momento."}), 503

    ruta = ruta_fotografia_original(empresa.id, proyecto.id, tipo_mime)
    try:
        subir_archivo(BUCKET_FOTOGRAFIAS, ruta, contenido, tipo_mime)
    except Exception:
        return jsonify({"ok": False, "error": "No se pudo subir el archivo. Intenta de nuevo."}), 502

    fotografia = crear_fotografia(
        empresa.id, proyecto.id, archivo.filename, ruta, tipo_mime, len(contenido), usuario["id"]
    )
    return jsonify({"ok": True, "id": fotografia.id, "nombre": fotografia.nombre_archivo_original}), 201


@fotografia_bp.get("/fotos/<int:fotografia_id>")
@login_required
def foto_detalle(fotografia_id):
    empresa, _rol, foto = _fotografia_de_empresa_activa(fotografia_id)
    proyecto = obtener_proyecto(empresa.id, foto.proyecto_id)
    url = url_firmada(BUCKET_FOTOGRAFIAS, foto.ruta_storage)
    return render_template(
        "photo_studio/foto_detalle.html", empresa_activa=empresa, foto=foto, proyecto=proyecto, url=url
    )


@fotografia_bp.get("/fotos/<int:fotografia_id>/descargar")
@login_required
def foto_descargar(fotografia_id):
    _empresa, _rol, foto = _fotografia_de_empresa_activa(fotografia_id)
    url = url_firmada(BUCKET_FOTOGRAFIAS, foto.ruta_storage, nombre_descarga=foto.nombre_archivo_original)
    if url is None:
        abort(502)
    return redirect(url)


@fotografia_bp.route("/fotos/<int:fotografia_id>/eliminar", methods=["GET", "POST"])
@login_required
def foto_eliminar(fotografia_id):
    empresa, _rol, foto = _fotografia_de_empresa_activa(fotografia_id)

    if request.method == "POST":
        proyecto_id = foto.proyecto_id
        eliminar_fotografia(empresa.id, foto.id)
        return redirect(url_for("fotografia.proyecto_detalle", proyecto_id=proyecto_id))

    return render_template("photo_studio/foto_eliminar.html", empresa_activa=empresa, foto=foto)
