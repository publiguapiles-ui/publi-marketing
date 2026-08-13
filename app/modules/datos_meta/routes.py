"""Datos de Meta: pantalla de Conexiones (Paso 1) + seleccion de
activos, sincronizacion real y presupuesto de pauta (Paso 2).

Ninguna llamada a la Graph API ocurre aqui directamente -- esta ruta
solo orquesta: valida la empresa activa, llama a servicios internos
(app/services/meta/*, app/services/metricas.py, app/services/
presupuestos.py, app/services/periodos.py) y renderiza. Ningun detalle
de la API de Meta (URLs, campos, tokens) vive en este archivo ni en
los templates.
"""

import datetime

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
from app.services.meta.cuentas_service import (
    listar_activos_disponibles,
    listar_campanas_de_cuenta,
    listar_entidades_empresa,
    vincular_activos,
)
from app.services.meta.kpi import (
    CLAVES_KPI,
    ETIQUETAS_KPI,
    calcular_kpis,
    comparar_entidades,
    comparar_periodos,
    resolver_entidades_para_kpi,
    serie_diaria,
)
from app.services.meta.sincronizacion import (
    MAX_INTENTOS,
    iniciar_sincronizacion,
    listar_sincronizaciones_empresa,
    obtener_ultima_sincronizacion,
    reintentar_sincronizacion,
)
from app.services.periodos import ETIQUETAS_PERIODOS, PERIODOS_PREDEFINIDOS, resolver_periodo
from app.services.presupuestos import (
    calcular_resumen_presupuesto,
    crear_presupuesto,
    eliminar_presupuesto,
    obtener_presupuestos_empresa,
)

datos_meta_bp = Blueprint("datos_meta", __name__, url_prefix="/datos-meta")


def _empresa_activa_o_404():
    empresa, rol = obtener_empresa_activa()
    if empresa is None:
        abort(404)
    return empresa, rol


@datos_meta_bp.get("/")
@login_required
def index():
    # Solo existe Conexiones. Resumen/Campañas/Analítica/Audiencias/
    # Comparativas/Informes/Claude llegan en pasos futuros -- ver informe.
    return redirect(url_for("datos_meta.conexiones"))


@datos_meta_bp.get("/conexiones")
@login_required
def conexiones():
    empresa, _rol = _empresa_activa_o_404()

    conexion = obtener_conexion_activa(empresa.id)
    entidades_por_tipo = {}
    conteos_estructura = {}
    if conexion is not None:
        for tipo in ("cuenta_publicitaria", "pagina", "cuenta_instagram", "campana", "conjunto_anuncios", "anuncio"):
            entidades = listar_entidades_empresa(empresa.id, tipo=tipo)
            entidades_por_tipo[tipo] = entidades
            conteos_estructura[tipo] = len(entidades)

    presupuestos = [calcular_resumen_presupuesto(p) for p in obtener_presupuestos_empresa(empresa.id)]

    return render_template(
        "datos_meta/conexiones.html",
        empresa_activa=empresa,
        conexion=conexion,
        entidades_por_tipo=entidades_por_tipo,
        conteos_estructura=conteos_estructura,
        meta_configurado=meta_configurado(),
        historial=listar_conexiones_empresa(empresa.id),
        ultima_sincronizacion=obtener_ultima_sincronizacion(empresa.id) if conexion else None,
        sincronizaciones=listar_sincronizaciones_empresa(empresa.id) if conexion else [],
        max_intentos=MAX_INTENTOS,
        periodos=PERIODOS_PREDEFINIDOS,
        etiquetas_periodos=ETIQUETAS_PERIODOS,
        presupuestos=presupuestos,
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
    # Paso 2, punto 4: tras autenticar, mostrar los activos para que el
    # usuario elija -- nunca vincular todo automaticamente.
    return redirect(url_for("datos_meta.seleccionar_activos"))


@datos_meta_bp.post("/conexiones/<int:conexion_id>/desconectar")
@login_required
def conexion_desconectar(conexion_id):
    empresa, _rol = _empresa_activa_o_404()
    ok, error = desconectar(empresa.id, conexion_id)
    if not ok:
        return jsonify({"ok": False, "error": error}), 400
    return jsonify({"ok": True})


# --- Seleccion de activos (Paso 2, punto 4) --------------------------------------

@datos_meta_bp.get("/conexiones/seleccionar-activos")
@login_required
def seleccionar_activos():
    empresa, _rol = _empresa_activa_o_404()

    disponibles, error = listar_activos_disponibles(empresa.id)
    if error:
        return render_template("datos_meta/conexiones_error.html", empresa_activa=empresa, mensaje=error)

    ya_vinculadas = {
        (e.tipo, e.id_externo) for e in listar_entidades_empresa(empresa.id)
    }

    return render_template(
        "datos_meta/seleccionar_activos.html",
        empresa_activa=empresa,
        cuentas_publicitarias=disponibles["cuentas_publicitarias"],
        paginas=disponibles["paginas"],
        ya_vinculadas=ya_vinculadas,
    )


@datos_meta_bp.post("/conexiones/vincular-activos")
@login_required
def conexiones_vincular_activos():
    empresa, _rol = _empresa_activa_o_404()

    datos = request.get_json(silent=True) or {}
    seleccion = datos.get("seleccion")
    if not isinstance(seleccion, list):
        return jsonify({"ok": False, "error": "Selección inválida."}), 400

    ok, error = vincular_activos(empresa.id, seleccion)
    if not ok:
        return jsonify({"ok": False, "error": error}), 400
    return jsonify({"ok": True, "url": url_for("datos_meta.conexiones")})


# --- Sincronizacion (Paso 2, puntos 6, 12, 13) ------------------------------------

@datos_meta_bp.post("/conexiones/sincronizar")
@login_required
def conexiones_sincronizar():
    """Sincroniza estructura (campañas/conjuntos/anuncios) + insights
    de las cuentas ya vinculadas, para el período solicitado. Manual
    (botón) por ahora -- la arquitectura ya está lista para dispararse
    en segundo plano más adelante (ver informe, Pendientes)."""
    empresa, _rol = _empresa_activa_o_404()
    usuario = obtener_usuario_actual()

    datos = request.get_json(silent=True) or {}
    periodo_clave = datos.get("periodo") or "ultimos_30_dias"

    try:
        if periodo_clave == "personalizado":
            fecha_inicio = datetime.date.fromisoformat(datos["fecha_inicio"])
            fecha_fin = datetime.date.fromisoformat(datos["fecha_fin"])
        else:
            fecha_inicio, fecha_fin = resolver_periodo(periodo_clave)
    except (ValueError, KeyError, TypeError) as exc:
        return jsonify({"ok": False, "error": f"Período inválido: {exc}"}), 400

    conexion_previa = obtener_conexion_activa(empresa.id)
    tipo = "inicial" if conexion_previa and conexion_previa.ultima_sincronizacion_en is None else "incremental"

    sincronizacion, error = iniciar_sincronizacion(empresa.id, usuario["id"], tipo, fecha_inicio, fecha_fin)
    if error:
        return jsonify({"ok": False, "error": error}), 400

    if sincronizacion.estado == "error":
        return jsonify({"ok": False, "error": sincronizacion.error_mensaje, "sincronizacion_id": sincronizacion.id}), 502

    return jsonify(
        {
            "ok": True,
            "sincronizacion_id": sincronizacion.id,
            "estado": sincronizacion.estado,
            "registros_procesados": sincronizacion.registros_procesados,
        }
    )


@datos_meta_bp.post("/conexiones/sincronizaciones/<int:sincronizacion_id>/reintentar")
@login_required
def conexiones_reintentar(sincronizacion_id):
    empresa, _rol = _empresa_activa_o_404()
    sincronizacion, error = reintentar_sincronizacion(empresa.id, sincronizacion_id)
    if error:
        return jsonify({"ok": False, "error": error}), 400
    return jsonify({"ok": True, "estado": sincronizacion.estado, "error": sincronizacion.error_mensaje})


# --- Presupuesto de pauta (Paso 2, puntos 9 y 10) ---------------------------------

@datos_meta_bp.post("/conexiones/presupuesto")
@login_required
def conexiones_crear_presupuesto():
    empresa, _rol = _empresa_activa_o_404()
    usuario = obtener_usuario_actual()

    datos = request.get_json(silent=True) or {}
    fecha_inicio = datetime.date.fromisoformat(datos["fecha_inicio"]) if datos.get("fecha_inicio") else None
    fecha_fin = datetime.date.fromisoformat(datos["fecha_fin"]) if datos.get("fecha_fin") else None

    presupuesto, error = crear_presupuesto(
        empresa.id, usuario["id"],
        datos.get("nombre"), datos.get("tipo") or "estrategico", datos.get("monto"),
        moneda=datos.get("moneda") or "CRC",
        periodo_tipo=datos.get("periodo_tipo") or "mensual",
        fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
        entidad_id=datos.get("entidad_id"),
        objetivo=datos.get("objetivo"), notas=datos.get("notas"),
    )
    if error:
        return jsonify({"ok": False, "error": error}), 400
    return jsonify({"ok": True, "presupuesto_id": presupuesto.id}), 201


@datos_meta_bp.post("/conexiones/presupuesto/<int:presupuesto_id>/eliminar")
@login_required
def conexiones_eliminar_presupuesto(presupuesto_id):
    empresa, _rol = _empresa_activa_o_404()
    ok, error = eliminar_presupuesto(empresa.id, presupuesto_id)
    if not ok:
        return jsonify({"ok": False, "error": error}), 400
    return jsonify({"ok": True})


# --- Motor de KPI: pantalla de prueba (Paso 3) ------------------------------------
#
# Unicamente para verificar que el motor de KPI funciona -- NO es el
# dashboard definitivo (ver enunciado del Paso 3). Formulario GET
# simple (sin JS nuevo): elegir cuenta publicitaria + periodo recarga
# la pagina con los resultados.

@datos_meta_bp.get("/kpi")
@login_required
def kpi_prueba():
    empresa, _rol = _empresa_activa_o_404()

    cuentas = listar_entidades_empresa(empresa.id, tipo="cuenta_publicitaria")

    cuenta_id = request.args.get("cuenta_id", type=int)
    periodo_clave = request.args.get("periodo") or "ultimos_30_dias"
    if periodo_clave not in PERIODOS_PREDEFINIDOS:
        periodo_clave = "ultimos_30_dias"

    try:
        if periodo_clave == "personalizado":
            fecha_inicio = datetime.date.fromisoformat(request.args["fecha_inicio"])
            fecha_fin = datetime.date.fromisoformat(request.args["fecha_fin"])
        else:
            fecha_inicio, fecha_fin = resolver_periodo(periodo_clave)
    except (ValueError, KeyError, TypeError):
        periodo_clave = "ultimos_30_dias"
        fecha_inicio, fecha_fin = resolver_periodo(periodo_clave)

    entidad_seleccionada = None
    error_entidad = None
    entidad_ids = None  # None = agregado de toda la empresa (ver kpi.calcular_kpis)
    comparacion_entidades = []

    if cuenta_id is not None:
        entidad_seleccionada = next((c for c in cuentas if c.id == cuenta_id), None)
        if entidad_seleccionada is None:
            abort(404)
        entidad_ids, error_entidad = resolver_entidades_para_kpi(empresa.id, cuenta_id)
        if entidad_ids:
            comparacion_entidades = comparar_entidades(empresa.id, entidad_ids, fecha_inicio, fecha_fin, metrica_orden="spend")

    comparacion_periodos = comparar_periodos(empresa.id, entidad_ids, fecha_inicio, fecha_fin)
    presupuestos = [calcular_resumen_presupuesto(p) for p in obtener_presupuestos_empresa(empresa.id)]

    return render_template(
        "datos_meta/kpi_prueba.html",
        empresa_activa=empresa,
        cuentas=cuentas,
        cuenta_id=cuenta_id,
        entidad_seleccionada=entidad_seleccionada,
        error_entidad=error_entidad,
        periodo_clave=periodo_clave,
        periodos=PERIODOS_PREDEFINIDOS,
        etiquetas_periodos=ETIQUETAS_PERIODOS,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        comparacion_periodos=comparacion_periodos,
        comparacion_entidades=comparacion_entidades,
        presupuestos=presupuestos,
        claves_kpi=CLAVES_KPI,
        etiquetas_kpi=ETIQUETAS_KPI,
    )


# --- Dashboard visual (Paso 4) -----------------------------------------------------
#
# Esta seccion NO calcula ningun KPI -- solo arma/serializa lo que ya
# devuelve app/services/meta/kpi.py (Paso 3) y app/services/
# presupuestos.py (Paso 2) hacia JSON. El template no hace aritmetica;
# todo el renderizado de tarjetas/graficos/tabla ocurre en
# datos_meta_dashboard.js a partir de ese JSON, tanto en la carga
# inicial (embebido en la pagina) como al cambiar filtros (via fetch a
# /datos-meta/dashboard/datos, sin recargar la aplicacion completa).

ESTADOS_CAMPANA_FILTRO = {
    # Mapeo honesto a partir de los valores REALES que Meta reporta en
    # effective_status/status (ver campanas_service.py) -- nunca se
    # inventan estados que Meta no use. "finalizadas" cubre campanas
    # archivadas o eliminadas manualmente; Meta no tiene un estado
    # "completada" propio para cuando solo vence el stop_time.
    "activas": ("ACTIVE",),
    "desactivadas": ("PAUSED", "CAMPAIGN_PAUSED", "ADSET_PAUSED"),
    "finalizadas": ("ARCHIVED", "DELETED"),
}


def _filtrar_campanas_por_estado(campanas, estado_clave):
    if not estado_clave or estado_clave == "todas":
        return list(campanas)
    permitidos = ESTADOS_CAMPANA_FILTRO.get(estado_clave)
    if not permitidos:
        return list(campanas)
    return [c for c in campanas if c.estado in permitidos]


def _serializar_campana(c):
    return {
        "id": c.id,
        "nombre": c.nombre or c.id_externo,
        "id_externo": c.id_externo,
        "estado": c.estado,
        "objetivo": (c.atributos or {}).get("objetivo"),
    }


def _serializar_comparacion(comparacion):
    if comparacion is None:
        return None
    return {
        "periodo_actual": {
            "fecha_inicio": comparacion["periodo_actual"]["fecha_inicio"].isoformat(),
            "fecha_fin": comparacion["periodo_actual"]["fecha_fin"].isoformat(),
            "kpis": comparacion["periodo_actual"]["kpis"],
        },
        "periodo_anterior": {
            "fecha_inicio": comparacion["periodo_anterior"]["fecha_inicio"].isoformat(),
            "fecha_fin": comparacion["periodo_anterior"]["fecha_fin"].isoformat(),
            "kpis": comparacion["periodo_anterior"]["kpis"],
        },
        "variacion_porcentual": comparacion["variacion_porcentual"],
    }


def _serializar_resumen_presupuesto(r):
    if r is None:
        return None
    p = r["presupuesto"]
    return {
        "id": p.id,
        "nombre": p.nombre,
        "tipo": p.tipo,
        "monto": p.monto,
        "moneda": p.moneda,
        "fecha_inicio": r["fecha_inicio"].isoformat(),
        "fecha_fin": r["fecha_fin"].isoformat(),
        "gasto_real": r["gasto_real"],
        "disponible": r["disponible"],
        "porcentaje_usado": r["porcentaje_usado"],
        "excedido": r["excedido"],
    }


def _leer_filtros_dashboard(args):
    cuenta_id = args.get("cuenta_id", type=int)
    campana_id = args.get("campana_id", type=int)

    estado_clave = args.get("estado") or "todas"
    if estado_clave not in ("todas",) + tuple(ESTADOS_CAMPANA_FILTRO.keys()):
        estado_clave = "todas"

    comparar = args.get("comparar") in ("1", "true", "True")

    periodo_clave = args.get("periodo") or "ultimos_30_dias"
    if periodo_clave not in PERIODOS_PREDEFINIDOS:
        periodo_clave = "ultimos_30_dias"

    try:
        if periodo_clave == "personalizado":
            fecha_inicio = datetime.date.fromisoformat(args["fecha_inicio"])
            fecha_fin = datetime.date.fromisoformat(args["fecha_fin"])
        else:
            fecha_inicio, fecha_fin = resolver_periodo(periodo_clave)
    except (ValueError, KeyError, TypeError):
        periodo_clave = "ultimos_30_dias"
        fecha_inicio, fecha_fin = resolver_periodo(periodo_clave)

    return {
        "cuenta_id": cuenta_id,
        "campana_id": campana_id,
        "periodo_clave": periodo_clave,
        "fecha_inicio": fecha_inicio,
        "fecha_fin": fecha_fin,
        "comparar": comparar,
        "estado_clave": estado_clave,
    }


def _construir_datos_dashboard(empresa, cuenta_id, campana_id, periodo_clave, fecha_inicio, fecha_fin, comparar, estado_clave):
    cuentas = listar_entidades_empresa(empresa.id, tipo="cuenta_publicitaria")

    campanas_cuenta = []
    error_cuenta = None
    entidad_ids_kpi = None  # None = toda la empresa (ver kpi.calcular_kpis)
    moneda_cuenta = None

    if cuenta_id is not None:
        cuenta_seleccionada = next((c for c in cuentas if c.id == cuenta_id), None)
        # Solo se muestra un codigo de moneda cuando hay UNA cuenta
        # publicitaria especifica seleccionada (dato real de
        # atributos.moneda, tomado de Meta) -- con "Toda la empresa"
        # podria haber cuentas en distintas monedas, y mostrar una sola
        # seria inventar un supuesto que no se puede garantizar.
        if cuenta_seleccionada is not None:
            moneda_cuenta = (cuenta_seleccionada.atributos or {}).get("moneda")
        campanas_cuenta = listar_campanas_de_cuenta(empresa.id, cuenta_id)
        entidad_ids_kpi, error_cuenta = resolver_entidades_para_kpi(empresa.id, cuenta_id)

    campanas_filtradas = _filtrar_campanas_por_estado(campanas_cuenta, estado_clave)

    if cuenta_id is not None:
        # el filtro de estado tambien acota el alcance de tarjetas/graficos,
        # no solo el de la tabla -- son "filtros superiores" del dashboard
        entidad_ids_kpi = [c.id for c in campanas_filtradas]

    if campana_id is not None and entidad_ids_kpi is not None and campana_id in entidad_ids_kpi:
        # drill-down a una sola campana ya validada como propia de esta empresa/cuenta
        entidad_ids_kpi = [campana_id]

    kpis = calcular_kpis(empresa.id, entidad_ids_kpi, fecha_inicio, fecha_fin)
    comparacion = comparar_periodos(empresa.id, entidad_ids_kpi, fecha_inicio, fecha_fin) if comparar else None
    serie = serie_diaria(empresa.id, entidad_ids_kpi, fecha_inicio, fecha_fin)

    tabla = []
    if campanas_filtradas:
        comparacion_entidades = comparar_entidades(
            empresa.id, [c.id for c in campanas_filtradas], fecha_inicio, fecha_fin, metrica_orden="spend",
        )
        for fila in comparacion_entidades:
            tabla.append({
                **_serializar_campana(fila["entidad"]),
                "kpis": fila["kpis"],
                "es_mejor": fila["es_mejor"],
                "es_peor": fila["es_peor"],
            })

    presupuestos = [calcular_resumen_presupuesto(p) for p in obtener_presupuestos_empresa(empresa.id)]
    presupuesto_principal = next((r for r in presupuestos if r["presupuesto"].tipo == "estrategico"), None)

    return {
        "empresa": {"id": empresa.id, "nombre": empresa.nombre},
        "cuentas": [{"id": c.id, "nombre": c.nombre or c.id_externo} for c in cuentas],
        "campanas_filtro": [_serializar_campana(c) for c in campanas_cuenta],
        "filtros": {
            "cuenta_id": cuenta_id,
            "campana_id": campana_id,
            "periodo": periodo_clave,
            "fecha_inicio": fecha_inicio.isoformat(),
            "fecha_fin": fecha_fin.isoformat(),
            "comparar": bool(comparar),
            "estado": estado_clave or "todas",
        },
        "moneda_cuenta": moneda_cuenta,
        "error_cuenta": error_cuenta,
        "kpis": kpis,
        "comparacion": _serializar_comparacion(comparacion),
        "serie_diaria": [{**d, "fecha": d["fecha"].isoformat()} for d in serie],
        "tabla_campanas": tabla,
        "presupuestos": [_serializar_resumen_presupuesto(r) for r in presupuestos],
        "presupuesto_principal": _serializar_resumen_presupuesto(presupuesto_principal),
        "claves_kpi": CLAVES_KPI,
        "etiquetas_kpi": ETIQUETAS_KPI,
    }


@datos_meta_bp.get("/dashboard")
@login_required
def dashboard():
    empresa, _rol = _empresa_activa_o_404()
    filtros = _leer_filtros_dashboard(request.args)
    datos = _construir_datos_dashboard(empresa, **filtros)

    return render_template(
        "datos_meta/dashboard.html",
        empresa_activa=empresa,
        datos=datos,
        periodos=PERIODOS_PREDEFINIDOS,
        etiquetas_periodos=ETIQUETAS_PERIODOS,
        estados_campana=["todas"] + list(ESTADOS_CAMPANA_FILTRO.keys()),
    )


@datos_meta_bp.get("/dashboard/datos")
@login_required
def dashboard_datos():
    empresa, _rol = _empresa_activa_o_404()
    filtros = _leer_filtros_dashboard(request.args)
    datos = _construir_datos_dashboard(empresa, **filtros)
    return jsonify(datos)
