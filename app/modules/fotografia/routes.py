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

from flask import Blueprint, Response, abort, jsonify, redirect, render_template, request, url_for

from app.core.auth import obtener_usuario_actual
from app.core.decorators import login_required
from app.core.empresas import obtener_empresa_activa
from app.models import APLICACIONES_LOGO, POSICIONES_LOGO, POSICION_LOGO_PREDETERMINADA, MODOS_RECORTE
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
from app.services.formatos import TIPOS_FORMATO, calcular_saliencia, calcular_ventana_formato, generar_formato
from app.services.marca import obtener_logo, obtener_logo_marca_agua, obtener_logo_principal, obtener_logos_empresa
from app.services.storage import (
    BUCKET_FOTOGRAFIAS,
    BUCKET_LOGOS,
    TAMANO_MAXIMO_FOTO_BYTES,
    descargar_archivo,
    detectar_tipo_mime_real,
    ruta_fotografia_original,
    storage_configurado,
    subir_archivo,
    url_firmada,
)
from app.services.derivados import crear_formato, crear_mejora_automatica, mejor_base_disponible, obtener_derivado, obtener_derivados_fotografia
from app.services.procesamiento import cargar_imagen, detectar_rostros

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
    logos = obtener_logos_empresa(empresa.id)
    logo_principal = obtener_logo_principal(empresa.id)
    return render_template(
        "photo_studio/proyecto_detalle.html",
        empresa_activa=empresa,
        proyecto=proyecto,
        fotos=fotos_con_url,
        logos=logos,
        logo_principal=logo_principal,
        posiciones=POSICIONES_LOGO,
        posicion_predeterminada=POSICION_LOGO_PREDETERMINADA,
        formatos=TIPOS_FORMATO,
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
    derivados = obtener_derivados_fotografia(foto.id)
    return render_template(
        "photo_studio/foto_detalle.html",
        empresa_activa=empresa,
        foto=foto,
        proyecto=proyecto,
        url=url,
        derivados=derivados,
    )


@fotografia_bp.get("/fotos/<int:fotografia_id>/mejorar")
@login_required
def foto_mejorar_confirmar(fotografia_id):
    empresa, _rol, foto = _fotografia_de_empresa_activa(fotografia_id)
    return render_template("photo_studio/foto_mejorar.html", empresa_activa=empresa, foto=foto)


@fotografia_bp.post("/fotos/<int:fotografia_id>/mejorar")
@login_required
def foto_mejorar(fotografia_id):
    empresa, _rol, foto = _fotografia_de_empresa_activa(fotografia_id)
    usuario = obtener_usuario_actual()

    if not storage_configurado():
        return jsonify({"ok": False, "error": "El almacenamiento no está disponible en este momento."}), 503

    derivado = crear_mejora_automatica(empresa.id, foto.proyecto_id, foto, usuario["id"])

    if derivado.estado == "error":
        return jsonify({"ok": False, "error": derivado.error_mensaje or "No se pudo procesar la fotografía."}), 502

    return jsonify(
        {
            "ok": True,
            "derivado_id": derivado.id,
            "estado": derivado.estado,
            "url_resultado": url_for("fotografia.derivado_detalle", derivado_id=derivado.id),
        }
    ), 201


def _logo_validado(empresa_id, datos):
    """(logo_o_None, error_o_None). Un logo_id que no pertenece a la
    empresa activa es un error explicito -- nunca se confia en el
    frontend para esto (Paso 8, puntos 30 y 31).
    """
    logo_id = datos.get("logo_id")
    if not logo_id:
        return None, None
    try:
        logo_id = int(logo_id)
    except (TypeError, ValueError):
        return None, "Logo inválido."
    logo = obtener_logo(empresa_id, logo_id)
    if logo is None:
        return None, "El logo seleccionado no pertenece a esta empresa."
    return logo, None


def _parametros_preparacion(empresa, datos):
    aplicacion = datos.get("aplicacion") or "sin_logo"
    if aplicacion not in APLICACIONES_LOGO:
        return None, "Modo de aplicación inválido."

    posicion = datos.get("posicion") or POSICION_LOGO_PREDETERMINADA
    if posicion not in POSICIONES_LOGO:
        return None, "Posición inválida."

    try:
        opacidad = float(datos.get("opacidad", 0.8))
    except (TypeError, ValueError):
        opacidad = 0.8
    opacidad = max(0.15, min(1.0, opacidad))

    logo, error = _logo_validado(empresa.id, datos)
    if error:
        return None, error
    if aplicacion != "sin_logo" and logo is None:
        return None, "Selecciona un logo para aplicar."

    modo = datos.get("crop_mode") or "auto"
    if modo not in MODOS_RECORTE:
        return None, "Modo de encuadre inválido."

    focus_x = datos.get("focus_x")
    focus_y = datos.get("focus_y")
    if focus_x is not None and focus_y is not None:
        try:
            focus_x = max(0.0, min(1.0, float(focus_x)))
            focus_y = max(0.0, min(1.0, float(focus_y)))
        except (TypeError, ValueError):
            return None, "Punto de enfoque inválido."
    else:
        focus_x = focus_y = None

    if modo == "manual" and focus_x is None:
        return None, "El modo manual requiere un punto de enfoque."

    try:
        zoom = float(datos.get("zoom", 1.0))
    except (TypeError, ValueError):
        zoom = 1.0
    zoom = max(1.0, min(3.0, zoom))

    return {
        "logo": logo,
        "aplicacion": aplicacion,
        "posicion": posicion,
        "opacidad": opacidad,
        "modo": modo,
        "focus_x": focus_x,
        "focus_y": focus_y,
        "zoom": zoom,
    }, None


@fotografia_bp.get("/fotos/<int:fotografia_id>/preparar")
@login_required
def foto_preparar_formulario(fotografia_id):
    empresa, _rol, foto = _fotografia_de_empresa_activa(fotografia_id)
    logos = obtener_logos_empresa(empresa.id)
    logo_principal = obtener_logo_principal(empresa.id)
    logo_marca_agua = obtener_logo_marca_agua(empresa.id)
    url_foto = url_firmada(BUCKET_FOTOGRAFIAS, foto.ruta_storage)
    return render_template(
        "photo_studio/foto_preparar.html",
        empresa_activa=empresa,
        foto=foto,
        logos=logos,
        logo_principal=logo_principal,
        logo_marca_agua=logo_marca_agua,
        url_foto=url_foto,
        posiciones=POSICIONES_LOGO,
        posicion_predeterminada=POSICION_LOGO_PREDETERMINADA,
        formatos=TIPOS_FORMATO,
    )


@fotografia_bp.post("/fotos/<int:fotografia_id>/preparar")
@login_required
def foto_preparar(fotografia_id):
    empresa, _rol, foto = _fotografia_de_empresa_activa(fotografia_id)
    usuario = obtener_usuario_actual()

    if not storage_configurado():
        return jsonify({"ok": False, "error": "El almacenamiento no está disponible en este momento."}), 503

    datos = request.get_json(silent=True) or {}
    parametros, error = _parametros_preparacion(empresa, datos)
    if error:
        return jsonify({"ok": False, "error": error}), 400

    formatos_pedidos = [f for f in (datos.get("formatos") or []) if f in TIPOS_FORMATO]
    if not formatos_pedidos:
        return jsonify({"ok": False, "error": "Selecciona al menos un formato."}), 400

    resultados = []
    for tipo_formato in formatos_pedidos:
        derivado = crear_formato(
            empresa.id,
            foto.proyecto_id,
            foto,
            usuario["id"],
            tipo_formato,
            logo=parametros["logo"],
            aplicacion=parametros["aplicacion"],
            posicion=parametros["posicion"],
            opacidad=parametros["opacidad"],
            modo=parametros["modo"],
            focus_x=parametros["focus_x"],
            focus_y=parametros["focus_y"],
            zoom=parametros["zoom"],
        )
        resultados.append(
            {
                "tipo": tipo_formato,
                "ok": derivado.estado == "completada",
                "derivado_id": derivado.id,
                "estado": derivado.estado,
                "error": derivado.error_mensaje if derivado.estado == "error" else None,
                "advertencia": derivado.advertencia,
                "url_resultado": url_for("fotografia.derivado_detalle", derivado_id=derivado.id),
            }
        )

    ok_general = any(r["ok"] for r in resultados)
    codigo = 201 if ok_general else 502
    return jsonify({"ok": ok_general, "resultados": resultados}), codigo


@fotografia_bp.post("/fotos/<int:fotografia_id>/preparar/vista-previa")
@login_required
def foto_preparar_vista_previa(fotografia_id):
    """Genera la vista previa con EXACTAMENTE el mismo algoritmo de
    composicion que el resultado final (app.services.formatos), pero
    sin guardar nada en Storage ni en la base de datos.
    """
    empresa, _rol, foto = _fotografia_de_empresa_activa(fotografia_id)

    if not storage_configurado():
        abort(503)

    datos = request.get_json(silent=True) or {}
    parametros, error = _parametros_preparacion(empresa, datos)
    if error:
        return jsonify({"ok": False, "error": error}), 400

    tipo_formato = datos.get("formato")
    if tipo_formato not in TIPOS_FORMATO:
        return jsonify({"ok": False, "error": "Formato inválido."}), 400

    bucket_base, ruta_base = mejor_base_disponible(foto)
    try:
        bytes_base = descargar_archivo(bucket_base, ruta_base)
    except Exception:
        return jsonify({"ok": False, "error": "No se pudo cargar la fotografía."}), 502

    imagen_base = cargar_imagen(bytes_base)
    rostros = detectar_rostros(imagen_base)

    logo_bytes = None
    if parametros["logo"] is not None and parametros["aplicacion"] != "sin_logo":
        logo_bytes = descargar_archivo(BUCKET_LOGOS, parametros["logo"].ruta_storage)

    bytes_resultado, metadata = generar_formato(
        bytes_base,
        tipo_formato,
        rostros,
        logo_bytes=logo_bytes,
        aplicacion=parametros["aplicacion"],
        posicion=parametros["posicion"],
        opacidad=parametros["opacidad"],
        modo=parametros["modo"],
        focus_x=parametros["focus_x"],
        focus_y=parametros["focus_y"],
        zoom=parametros["zoom"],
    )
    if bytes_resultado is None:
        return jsonify({"ok": False, "error": metadata.get("advertencia") or "No se pudo generar la vista previa."}), 422

    return Response(bytes_resultado, mimetype="image/jpeg")


@fotografia_bp.post("/fotos/<int:fotografia_id>/encuadre/calcular")
@login_required
def foto_encuadre_calcular(fotografia_id):
    """Calculo LIVIANO del area de recorte (Paso 9, punto 8): solo
    devuelve las coordenadas normalizadas de la ventana, sin componer
    ni codificar ninguna imagen -- para dibujar el overlay mientras el
    usuario arrastra el punto de enfoque o mueve el zoom, sin pagar el
    costo de regenerar el JPEG en cada movimiento.
    """
    empresa, _rol, foto = _fotografia_de_empresa_activa(fotografia_id)

    if not storage_configurado():
        abort(503)

    datos = request.get_json(silent=True) or {}
    modo = datos.get("crop_mode") or "auto"
    if modo not in MODOS_RECORTE:
        return jsonify({"ok": False, "error": "Modo de encuadre inválido."}), 400

    tipo_formato = datos.get("formato")
    if tipo_formato not in TIPOS_FORMATO:
        return jsonify({"ok": False, "error": "Formato inválido."}), 400

    focus_x = datos.get("focus_x")
    focus_y = datos.get("focus_y")
    try:
        focus_x = max(0.0, min(1.0, float(focus_x))) if focus_x is not None else None
        focus_y = max(0.0, min(1.0, float(focus_y))) if focus_y is not None else None
        zoom = max(1.0, min(3.0, float(datos.get("zoom", 1.0))))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Parámetros de encuadre inválidos."}), 400

    bucket_base, ruta_base = mejor_base_disponible(foto)
    try:
        bytes_base = descargar_archivo(bucket_base, ruta_base)
    except Exception:
        return jsonify({"ok": False, "error": "No se pudo cargar la fotografía."}), 502

    imagen_base = cargar_imagen(bytes_base)
    ancho_base, alto_base = imagen_base.size
    rostros = detectar_rostros(imagen_base)

    saliencia_xy = None
    if modo == "auto" and not rostros:
        saliencia_xy = calcular_saliencia(imagen_base)

    calculo = calcular_ventana_formato(
        ancho_base, alto_base, tipo_formato, rostros,
        modo=modo, focus_x=focus_x, focus_y=focus_y, zoom=zoom, saliencia_xy=saliencia_xy,
    )
    x0, y0, x1, y1 = calculo["ventana"]

    return jsonify(
        {
            "ok": True,
            "crop_x0": x0,
            "crop_y0": y0,
            "crop_x1": x1,
            "crop_y1": y1,
            "focus_x": calculo["focus_x"],
            "focus_y": calculo["focus_y"],
            "algoritmo": calculo["algoritmo"],
            "advertencia": calculo["advertencia"],
        }
    )


@fotografia_bp.get("/derivados/<int:derivado_id>")
@login_required
def derivado_detalle(derivado_id):
    empresa, _rol = obtener_empresa_activa()
    if empresa is None:
        abort(404)
    derivado = obtener_derivado(empresa.id, derivado_id)
    if derivado is None:
        abort(404)

    foto = obtener_fotografia(empresa.id, derivado.fotografia_id)
    proyecto = obtener_proyecto(empresa.id, foto.proyecto_id)
    url_original = url_firmada(BUCKET_FOTOGRAFIAS, foto.ruta_storage)
    url_derivado = url_firmada(BUCKET_FOTOGRAFIAS, derivado.ruta_storage) if derivado.ruta_storage else None

    correcciones = derivado.correcciones_aplicadas.split(",") if derivado.correcciones_aplicadas else []
    logo_usado = obtener_logo(empresa.id, derivado.logo_id) if derivado.logo_id else None

    return render_template(
        "photo_studio/derivado_detalle.html",
        empresa_activa=empresa,
        foto=foto,
        proyecto=proyecto,
        derivado=derivado,
        url_original=url_original,
        url_derivado=url_derivado,
        correcciones=correcciones,
        logo_usado=logo_usado,
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
