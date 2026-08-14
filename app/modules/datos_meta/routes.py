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
from app.services.meta.analisis import analizar_audiencias, construir_analisis_campana
from app.services.meta.client import MetaAPIError
from app.services.meta.conexiones import (
    crear_conexion,
    desconectar,
    listar_conexiones_empresa,
    obtener_conexion_activa,
    obtener_conexion_mas_reciente,
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
from app.services.meta.planificador import (
    agregar_etapa,
    cambiar_estado_proyecto,
    construir_paquete_planificador,
    crear_proyecto,
    eliminar_etapa,
    listar_proyectos_empresa,
    obtener_proyecto,
)
from app.services.meta.inteligencia import construir_inteligencia
from app.services.meta.proyectos_estrategicos import (
    agregar_fase,
    agregar_paso_secuencia,
    cambiar_estado_proyecto as cambiar_estado_proyecto_estrategico,
    construir_diagnostico_proyecto,
    construir_seguimiento,
    crear_proyecto as crear_proyecto_estrategico,
    eliminar_fase,
    eliminar_paso_secuencia,
    listar_audiencias_disponibles,
    listar_proyectos_empresa as listar_proyectos_estrategicos_empresa,
    obtener_proyecto as obtener_proyecto_estrategico,
    resumen_presupuesto_proyecto as resumen_presupuesto_proyecto_estrategico,
)
from app.services.periodos import ETIQUETAS_PERIODOS, PERIODOS_PREDEFINIDOS, resolver_periodo
from app.services.presupuestos import (
    calcular_resumen_presupuesto,
    crear_presupuesto,
    eliminar_presupuesto,
    obtener_presupuestos_empresa,
)
from app.models import ESTADOS_PROYECTO_PAUTA, ESTADOS_PROYECTO_ESTRATEGICO, TIPOS_AUDIENCIA_ESTRATEGICA

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

    # Paso 6, punto 10: se muestra la conexion mas RECIENTE (activa,
    # con error o revocada), no solo la activa -- de lo contrario una
    # conexion expirada/revocada desaparece de la pantalla y se
    # confunde con "nunca se conecto Meta".
    conexion = obtener_conexion_mas_reciente(empresa.id)
    conexion_activa = conexion is not None and conexion.estado == "activa"

    # Lectura pura de lo YA sincronizado (sin llamar a Meta) -- se
    # muestra siempre que exista una conexion, activa o no, porque
    # estos activos siguen siendo datos reales aunque el token haya
    # expirado despues de sincronizarlos.
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
        conexion_activa=conexion_activa,
        entidades_por_tipo=entidades_por_tipo,
        conteos_estructura=conteos_estructura,
        meta_configurado=meta_configurado(),
        historial=listar_conexiones_empresa(empresa.id),
        ultima_sincronizacion=obtener_ultima_sincronizacion(empresa.id) if conexion_activa else None,
        sincronizaciones=listar_sincronizaciones_empresa(empresa.id) if conexion_activa else [],
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


def _leer_periodo_y_comparar(args):
    """Lectura compartida de periodo/comparar (Paso 4 y Paso 5) --
    misma logica de respaldo ante un periodo invalido o fechas
    personalizadas incompletas: nunca un 500, siempre cae de vuelta a
    "ultimos_30_dias"."""
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

    return {"periodo_clave": periodo_clave, "fecha_inicio": fecha_inicio, "fecha_fin": fecha_fin, "comparar": comparar}


def _leer_filtros_dashboard(args):
    cuenta_id = args.get("cuenta_id", type=int)
    campana_id = args.get("campana_id", type=int)

    estado_clave = args.get("estado") or "todas"
    if estado_clave not in ("todas",) + tuple(ESTADOS_CAMPANA_FILTRO.keys()):
        estado_clave = "todas"

    periodo = _leer_periodo_y_comparar(args)

    return {
        "cuenta_id": cuenta_id,
        "campana_id": campana_id,
        "periodo_clave": periodo["periodo_clave"],
        "fecha_inicio": periodo["fecha_inicio"],
        "fecha_fin": periodo["fecha_fin"],
        "comparar": periodo["comparar"],
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


# --- Analisis de campañas y audiencias (Paso 5) ------------------------------------
#
# Reutiliza exclusivamente app/services/meta/analisis.py (que a su vez
# reutiliza kpi.py, presupuestos.py y los nuevos targeting.py/
# oportunidades.py) -- ningun calculo de KPI ocurre en este archivo,
# solo se serializa a JSON lo que analisis.py ya devuelve.

def _serializar_fila_kpi(fila, incluir_targeting=False, incluir_creativo=False):
    atributos = fila["entidad"].atributos or {}
    fila_serializada = {
        **_serializar_campana(fila["entidad"]),
        "kpis": fila["kpis"],
        "es_mejor": fila["es_mejor"],
        "es_peor": fila["es_peor"],
        # presente en conjunto_anuncios (campos daily_budget/lifetime_budget
        # del AdSet, sincronizados en el Paso 2) -- None para otros tipos.
        "presupuesto_diario_meta": atributos.get("presupuesto_diario"),
        "presupuesto_total_meta": atributos.get("presupuesto_total"),
        # presente solo en filas de audiencias.analizar_audiencias() (un
        # conjunto no tiene nombre de campaña propio, ver analisis.py).
        "campana_nombre": fila.get("campana_nombre"),
    }
    if incluir_targeting:
        fila_serializada["targeting"] = fila.get("targeting")
    if incluir_creativo:
        fila_serializada["creativo"] = atributos.get("creativo")
    return fila_serializada


def _serializar_campana_detalle(campana):
    atributos = campana.atributos or {}
    return {
        "id": campana.id,
        "nombre": campana.nombre or campana.id_externo,
        "id_externo": campana.id_externo,
        "estado": campana.estado,
        "objetivo": atributos.get("objetivo"),
        "fecha_inicio": atributos.get("fecha_inicio"),
        "fecha_fin": atributos.get("fecha_fin"),
        # Presupuesto tal como lo reporta Meta (campos daily_budget/
        # lifetime_budget/budget_remaining de la Campaign API,
        # sincronizados desde el Paso 2) -- se muestran sin convertir,
        # ver informe del Paso 5 sobre la unidad monetaria de Meta.
        "presupuesto_diario_meta": atributos.get("presupuesto_diario"),
        "presupuesto_total_meta": atributos.get("presupuesto_total"),
        "presupuesto_restante_meta": atributos.get("presupuesto_restante"),
    }


def _serializar_analisis_campana(paquete, filtros):
    presupuestos_asignados = [
        _serializar_resumen_presupuesto(calcular_resumen_presupuesto(p)) for p in paquete["presupuestos_asignados"]
    ]

    return {
        "campana": _serializar_campana_detalle(paquete["campana"]),
        "kpis": paquete["kpis"],
        "comparacion": _serializar_comparacion(paquete["comparacion"]),
        "serie_diaria": [{**d, "fecha": d["fecha"].isoformat()} for d in paquete["serie_diaria"]],
        "conjuntos": [_serializar_fila_kpi(f, incluir_targeting=True) for f in paquete["conjuntos"]],
        "oportunidades_conjuntos": paquete["oportunidades_conjuntos"],
        "anuncios": [_serializar_fila_kpi(f, incluir_creativo=True) for f in paquete["anuncios"]],
        "oportunidades_anuncios": paquete["oportunidades_anuncios"],
        "gasto_real": paquete["gasto_real"],
        "presupuestos_asignados": presupuestos_asignados,
        "oportunidades_campana": paquete["oportunidades_campana"],
        "filtros": {
            "periodo": filtros["periodo_clave"],
            "fecha_inicio": filtros["fecha_inicio"].isoformat(),
            "fecha_fin": filtros["fecha_fin"].isoformat(),
            "comparar": filtros["comparar"],
        },
        "claves_kpi": CLAVES_KPI,
        "etiquetas_kpi": ETIQUETAS_KPI,
    }


@datos_meta_bp.get("/campanas")
@login_required
def campanas_lista():
    """Historico de campañas (Paso 5, punto 8): activas, finalizadas y
    desactivadas, con su KPI del periodo -- entrada de navegacion hacia
    el analisis detallado de cada una."""
    empresa, _rol = _empresa_activa_o_404()
    cuentas = listar_entidades_empresa(empresa.id, tipo="cuenta_publicitaria")

    cuenta_id = request.args.get("cuenta_id", type=int)
    estado_clave = request.args.get("estado") or "todas"
    if estado_clave not in ("todas",) + tuple(ESTADOS_CAMPANA_FILTRO.keys()):
        estado_clave = "todas"

    periodo = _leer_periodo_y_comparar(request.args)

    campanas = []
    comparacion = []
    if cuenta_id is not None:
        campanas = _filtrar_campanas_por_estado(listar_campanas_de_cuenta(empresa.id, cuenta_id), estado_clave)
        if campanas:
            comparacion = comparar_entidades(empresa.id, [c.id for c in campanas], periodo["fecha_inicio"], periodo["fecha_fin"], metrica_orden="spend")

    return render_template(
        "datos_meta/campanas_lista.html",
        empresa_activa=empresa,
        cuentas=cuentas,
        cuenta_id=cuenta_id,
        estado_clave=estado_clave,
        estados_campana=["todas"] + list(ESTADOS_CAMPANA_FILTRO.keys()),
        periodo_clave=periodo["periodo_clave"],
        periodos=PERIODOS_PREDEFINIDOS,
        etiquetas_periodos=ETIQUETAS_PERIODOS,
        fecha_inicio=periodo["fecha_inicio"],
        fecha_fin=periodo["fecha_fin"],
        comparacion=comparacion,
        etiquetas_kpi=ETIQUETAS_KPI,
    )


@datos_meta_bp.get("/campanas/<int:campana_id>")
@login_required
def campana_detalle(campana_id):
    empresa, _rol = _empresa_activa_o_404()
    periodo = _leer_periodo_y_comparar(request.args)

    paquete, error = construir_analisis_campana(empresa.id, campana_id, periodo["fecha_inicio"], periodo["fecha_fin"], comparar=periodo["comparar"])
    if paquete is None:
        abort(404, error)

    return render_template(
        "datos_meta/campana_detalle.html",
        empresa_activa=empresa,
        campana_id=campana_id,
        datos=_serializar_analisis_campana(paquete, periodo),
        periodos=PERIODOS_PREDEFINIDOS,
        etiquetas_periodos=ETIQUETAS_PERIODOS,
    )


@datos_meta_bp.get("/campanas/<int:campana_id>/datos")
@login_required
def campana_datos(campana_id):
    empresa, _rol = _empresa_activa_o_404()
    periodo = _leer_periodo_y_comparar(request.args)

    paquete, error = construir_analisis_campana(empresa.id, campana_id, periodo["fecha_inicio"], periodo["fecha_fin"], comparar=periodo["comparar"])
    if paquete is None:
        return jsonify({"ok": False, "error": error}), 404

    return jsonify(_serializar_analisis_campana(paquete, periodo))


def _serializar_audiencias(paquete, error, cuenta_id, periodo):
    return {
        "error": error,
        "cuenta_id": cuenta_id,
        "segmentos": [_serializar_fila_kpi(f, incluir_targeting=True) for f in paquete["segmentos"]] if paquete else [],
        "oportunidades": paquete["oportunidades"] if paquete else [],
        "filtros": {
            "periodo": periodo["periodo_clave"],
            "fecha_inicio": periodo["fecha_inicio"].isoformat(),
            "fecha_fin": periodo["fecha_fin"].isoformat(),
        },
        "etiquetas_kpi": ETIQUETAS_KPI,
    }


@datos_meta_bp.get("/audiencias")
@login_required
def audiencias():
    """Analisis de audiencias (Paso 5, punto 5): separa SIEMPRE
    "audiencia configurada" (targeting) de "audiencia que realmente
    produjo resultados" (kpis medidos) -- nunca se asume que una
    segmentacion funciono solo porque se uso."""
    empresa, _rol = _empresa_activa_o_404()
    cuentas = listar_entidades_empresa(empresa.id, tipo="cuenta_publicitaria")
    cuenta_id = request.args.get("cuenta_id", type=int)
    periodo = _leer_periodo_y_comparar(request.args)

    paquete, error = analizar_audiencias(empresa.id, cuenta_id, periodo["fecha_inicio"], periodo["fecha_fin"])

    return render_template(
        "datos_meta/audiencias.html",
        empresa_activa=empresa,
        cuentas=cuentas,
        cuenta_id=cuenta_id,
        datos=_serializar_audiencias(paquete, error, cuenta_id, periodo),
        periodos=PERIODOS_PREDEFINIDOS,
        etiquetas_periodos=ETIQUETAS_PERIODOS,
    )


@datos_meta_bp.get("/audiencias/datos")
@login_required
def audiencias_datos():
    empresa, _rol = _empresa_activa_o_404()
    cuenta_id = request.args.get("cuenta_id", type=int)
    periodo = _leer_periodo_y_comparar(request.args)

    paquete, error = analizar_audiencias(empresa.id, cuenta_id, periodo["fecha_inicio"], periodo["fecha_fin"])
    return jsonify(_serializar_audiencias(paquete, error, cuenta_id, periodo))


# --- Planificador estrategico de pauta (Paso 7) -----------------------------------
#
# Reutiliza exclusivamente app/services/meta/planificador.py (que a su
# vez reutiliza kpi.py del Paso 3 y analisis.py del Paso 5) -- ningun
# calculo de KPI nuevo. NUNCA crea, modifica ni programa nada en Meta:
# el planificador solo administra un plan que vive en nuestra base de
# datos (ProyectoPauta/EtapaProyectoPauta).

def _serializar_proyecto(proyecto):
    return {
        "id": proyecto.id,
        "nombre": proyecto.nombre,
        "objetivo": proyecto.objetivo,
        "kpi_principal": proyecto.kpi_principal,
        "presupuesto_total": proyecto.presupuesto_total,
        "moneda": proyecto.moneda,
        "fecha_inicio": proyecto.fecha_inicio.isoformat(),
        "fecha_fin": proyecto.fecha_fin.isoformat(),
        "resultado_objetivo": proyecto.resultado_objetivo,
        "restricciones": proyecto.restricciones,
        "cuenta_publicitaria_id": proyecto.cuenta_publicitaria_id,
        "estado": proyecto.estado,
    }


def _serializar_etapa(etapa):
    return {
        "id": etapa.id,
        "nombre": etapa.nombre,
        "objetivo": etapa.objetivo,
        "presupuesto": etapa.presupuesto,
        "kpi_esperado": etapa.kpi_esperado,
        "audiencia_descripcion": etapa.audiencia_descripcion,
        "duracion_dias": etapa.duracion_dias,
        "orden": etapa.orden,
    }


def _serializar_paquete_planificador(paquete):
    analisis = paquete["analisis_historico"]
    return {
        "proyecto": _serializar_proyecto(paquete["proyecto"]),
        "etapas": [_serializar_etapa(e) for e in paquete["proyecto"].etapas],
        "presupuesto": paquete["presupuesto"],
        "advertencia_distribucion": paquete["advertencia_distribucion"],
        "periodo_analisis": {
            "fecha_inicio": paquete["periodo_analisis"]["fecha_inicio"].isoformat(),
            "fecha_fin": paquete["periodo_analisis"]["fecha_fin"].isoformat(),
        },
        "analisis_historico": {
            "datos_suficientes": analisis["datos_suficientes"],
            "mensaje": analisis["mensaje"],
            "campanas": [_serializar_fila_kpi(f) for f in analisis["campanas"]],
            "audiencias": [_serializar_fila_kpi(f, incluir_targeting=True) for f in analisis["audiencias"]],
            "mejor_dia": (
                {**analisis["mejor_dia"], "fecha": analisis["mejor_dia"]["fecha"].isoformat()}
                if analisis["mejor_dia"] else None
            ),
        },
        "claves_kpi": CLAVES_KPI,
        "etiquetas_kpi": ETIQUETAS_KPI,
    }


@datos_meta_bp.get("/planificador")
@login_required
def planificador_lista():
    empresa, _rol = _empresa_activa_o_404()
    proyectos = listar_proyectos_empresa(empresa.id)
    cuentas = listar_entidades_empresa(empresa.id, tipo="cuenta_publicitaria")

    return render_template(
        "datos_meta/planificador_lista.html",
        empresa_activa=empresa,
        proyectos=proyectos,
        cuentas=cuentas,
        claves_kpi=CLAVES_KPI,
        etiquetas_kpi=ETIQUETAS_KPI,
    )


@datos_meta_bp.post("/planificador/crear")
@login_required
def planificador_crear():
    empresa, _rol = _empresa_activa_o_404()
    usuario = obtener_usuario_actual()

    datos = request.get_json(silent=True) or {}
    try:
        if datos.get("fecha_inicio"):
            datos["fecha_inicio"] = datetime.date.fromisoformat(datos["fecha_inicio"])
        if datos.get("fecha_fin"):
            datos["fecha_fin"] = datetime.date.fromisoformat(datos["fecha_fin"])
    except ValueError:
        return jsonify({"ok": False, "error": "Formato de fecha inválido."}), 400

    proyecto, error = crear_proyecto(empresa.id, usuario["id"], datos)
    if error:
        return jsonify({"ok": False, "error": error}), 400
    return jsonify({"ok": True, "proyecto_id": proyecto.id}), 201


@datos_meta_bp.get("/planificador/<int:proyecto_id>")
@login_required
def planificador_detalle(proyecto_id):
    empresa, _rol = _empresa_activa_o_404()
    proyecto = obtener_proyecto(empresa.id, proyecto_id)
    if proyecto is None:
        abort(404)

    periodo = _leer_periodo_y_comparar(request.args)
    paquete = construir_paquete_planificador(proyecto, periodo["fecha_inicio"], periodo["fecha_fin"])

    return render_template(
        "datos_meta/planificador_detalle.html",
        empresa_activa=empresa,
        cuentas=listar_entidades_empresa(empresa.id, tipo="cuenta_publicitaria"),
        datos=_serializar_paquete_planificador(paquete),
        periodos=PERIODOS_PREDEFINIDOS,
        etiquetas_periodos=ETIQUETAS_PERIODOS,
        periodo_clave=periodo["periodo_clave"],
        estados_proyecto=ESTADOS_PROYECTO_PAUTA,
    )


@datos_meta_bp.get("/planificador/<int:proyecto_id>/datos")
@login_required
def planificador_datos(proyecto_id):
    empresa, _rol = _empresa_activa_o_404()
    proyecto = obtener_proyecto(empresa.id, proyecto_id)
    if proyecto is None:
        return jsonify({"ok": False, "error": "El proyecto no existe o no pertenece a esta empresa."}), 404

    periodo = _leer_periodo_y_comparar(request.args)
    paquete = construir_paquete_planificador(proyecto, periodo["fecha_inicio"], periodo["fecha_fin"])
    return jsonify(_serializar_paquete_planificador(paquete))


@datos_meta_bp.post("/planificador/<int:proyecto_id>/estado")
@login_required
def planificador_cambiar_estado(proyecto_id):
    empresa, _rol = _empresa_activa_o_404()
    datos = request.get_json(silent=True) or {}

    proyecto, error = cambiar_estado_proyecto(empresa.id, proyecto_id, datos.get("estado"))
    if error:
        return jsonify({"ok": False, "error": error}), 400
    return jsonify({"ok": True, "estado": proyecto.estado})


@datos_meta_bp.post("/planificador/<int:proyecto_id>/etapas")
@login_required
def planificador_agregar_etapa(proyecto_id):
    empresa, _rol = _empresa_activa_o_404()
    datos = request.get_json(silent=True) or {}

    etapa, error = agregar_etapa(empresa.id, proyecto_id, datos)
    if error:
        return jsonify({"ok": False, "error": error}), 400
    return jsonify({"ok": True, "etapa_id": etapa.id}), 201


@datos_meta_bp.post("/planificador/<int:proyecto_id>/etapas/<int:etapa_id>/eliminar")
@login_required
def planificador_eliminar_etapa(proyecto_id, etapa_id):
    empresa, _rol = _empresa_activa_o_404()
    ok, error = eliminar_etapa(empresa.id, proyecto_id, etapa_id)
    if not ok:
        return jsonify({"ok": False, "error": error}), 400
    return jsonify({"ok": True})


# --- Motor de inteligencia estrategica (Paso 8) ------------------------------------
#
# Reutiliza exclusivamente app/services/meta/inteligencia.py, que a su
# vez reutiliza kpi.py (Paso 3), analisis.py/oportunidades.py/
# targeting.py (Paso 5) y presupuestos.py (Paso 2) -- ningun calculo de
# KPI nuevo ocurre en este archivo. SIN Claude/IA generativa: todo lo
# que se muestra viene de reglas y datos verificables.

def _serializar_diagnostico(diagnostico):
    return {
        "kpis": diagnostico["kpis"],
        "areas": diagnostico["areas"],
        "comparacion_periodos": _serializar_comparacion(diagnostico["comparacion_periodos"]),
        "dias_con_datos": diagnostico["dias_con_datos"],
        "cantidad_campanas": diagnostico["cantidad_campanas"],
    }


def _serializar_analisis_campanas_inteligencia(analisis):
    return {
        "campanas": [_serializar_fila_kpi(f) for f in analisis["campanas"]],
        "oportunidades": analisis["oportunidades"],
        "cambios_temporales": analisis["cambios_temporales"],
    }


def _serializar_analisis_creativos(analisis):
    return {
        "anuncios": [_serializar_fila_kpi(f, incluir_creativo=True) for f in analisis["anuncios"]],
        "patron_video": analisis["patron_video"],
    }


def _serializar_analisis_presupuesto_inteligencia(analisis):
    return {
        "presupuestos": [_serializar_resumen_presupuesto(r) for r in analisis["presupuestos"]],
        "concentracion": analisis["concentracion"],
    }


def _serializar_inteligencia(paquete, cuenta_id, periodo):
    return {
        "cuenta_id": cuenta_id,
        "diagnostico": _serializar_diagnostico(paquete["diagnostico"]),
        "campanas": _serializar_analisis_campanas_inteligencia(paquete["campanas"]),
        "audiencias": {
            "segmentos": [_serializar_fila_kpi(f, incluir_targeting=True) for f in paquete["audiencias"]["segmentos"]] if paquete["audiencias"] else [],
            "oportunidades": paquete["audiencias"]["oportunidades"] if paquete["audiencias"] else [],
        },
        "creativos": _serializar_analisis_creativos(paquete["creativos"]),
        "presupuesto": _serializar_analisis_presupuesto_inteligencia(paquete["presupuesto"]),
        "oportunidades": paquete["oportunidades"],
        "alertas": paquete["alertas"],
        "filtros": {
            "periodo": periodo["periodo_clave"],
            "fecha_inicio": periodo["fecha_inicio"].isoformat(),
            "fecha_fin": periodo["fecha_fin"].isoformat(),
        },
        "claves_kpi": CLAVES_KPI,
        "etiquetas_kpi": ETIQUETAS_KPI,
    }


@datos_meta_bp.get("/inteligencia")
@login_required
def inteligencia():
    empresa, _rol = _empresa_activa_o_404()
    cuentas = listar_entidades_empresa(empresa.id, tipo="cuenta_publicitaria")
    cuenta_id = request.args.get("cuenta_id", type=int)
    periodo = _leer_periodo_y_comparar(request.args)

    paquete, error = construir_inteligencia(empresa.id, cuenta_id, periodo["fecha_inicio"], periodo["fecha_fin"])
    if error:
        return render_template("datos_meta/inteligencia.html", empresa_activa=empresa, cuentas=cuentas, cuenta_id=cuenta_id, error=error, datos=None, periodos=PERIODOS_PREDEFINIDOS, etiquetas_periodos=ETIQUETAS_PERIODOS, periodo_clave=periodo["periodo_clave"])

    return render_template(
        "datos_meta/inteligencia.html",
        empresa_activa=empresa,
        cuentas=cuentas,
        cuenta_id=cuenta_id,
        error=None,
        datos=_serializar_inteligencia(paquete, cuenta_id, periodo),
        periodos=PERIODOS_PREDEFINIDOS,
        etiquetas_periodos=ETIQUETAS_PERIODOS,
        periodo_clave=periodo["periodo_clave"],
    )


@datos_meta_bp.get("/inteligencia/datos")
@login_required
def inteligencia_datos():
    empresa, _rol = _empresa_activa_o_404()
    cuenta_id = request.args.get("cuenta_id", type=int)
    periodo = _leer_periodo_y_comparar(request.args)

    paquete, error = construir_inteligencia(empresa.id, cuenta_id, periodo["fecha_inicio"], periodo["fecha_fin"])
    if error:
        return jsonify({"ok": False, "error": error}), 400
    return jsonify({"ok": True, **_serializar_inteligencia(paquete, cuenta_id, periodo)})


# --- Proyectos estrategicos de campaña (Paso 9) -------------------------------------
#
# Reutiliza exclusivamente app/services/meta/proyectos_estrategicos.py,
# que a su vez reutiliza kpi.py (Paso 3), inteligencia.py (Paso 8) y
# cuentas_service.py/targeting.py (Paso 5) -- ningun calculo de KPI ni
# de oportunidades ocurre en este archivo. NUNCA crea, modifica ni
# ejecuta nada en Meta: administra unicamente el plan que vive en
# nuestra base de datos.

def _serializar_proyecto_estrategico(proyecto):
    return {
        "id": proyecto.id,
        "nombre": proyecto.nombre,
        "objetivo": proyecto.objetivo,
        "kpi_principal": proyecto.kpi_principal,
        "kpi_secundarios": proyecto.kpi_secundarios,
        "presupuesto_total": proyecto.presupuesto_total,
        "moneda": proyecto.moneda,
        "fecha_inicio": proyecto.fecha_inicio.isoformat(),
        "fecha_fin": proyecto.fecha_fin.isoformat(),
        "resultado_objetivo": proyecto.resultado_objetivo,
        "restricciones": proyecto.restricciones,
        "cuenta_publicitaria_id": proyecto.cuenta_publicitaria_id,
        "estado": proyecto.estado,
    }


def _serializar_fase_estrategica(fase):
    return {
        "id": fase.id,
        "nombre": fase.nombre,
        "objetivo": fase.objetivo,
        "presupuesto": fase.presupuesto,
        "fecha_inicio": fase.fecha_inicio.isoformat() if fase.fecha_inicio else None,
        "fecha_fin": fase.fecha_fin.isoformat() if fase.fecha_fin else None,
        "kpi_esperado": fase.kpi_esperado,
        "audiencia_tipo": fase.audiencia_tipo,
        "audiencia_descripcion": fase.audiencia_descripcion,
        "audiencia_entidad_id": fase.audiencia_entidad_id,
        # Si audiencia_entidad_id es None, esta fase todavia NO tiene una
        # audiencia real vinculada en Meta -- la interfaz debe indicarlo
        # explicitamente (Paso 9, punto 5), nunca asumir que existe.
        "audiencia_entidad_nombre": (
            (fase.audiencia_entidad.nombre or fase.audiencia_entidad.id_externo) if fase.audiencia_entidad else None
        ),
        "resultado_esperado": fase.resultado_esperado,
        "orden": fase.orden,
    }


def _serializar_paso_secuencia(paso):
    return {
        "id": paso.id,
        "contenido": paso.contenido,
        "audiencia_descripcion": paso.audiencia_descripcion,
        "objetivo": paso.objetivo,
        "duracion_dias": paso.duracion_dias,
        "kpi": paso.kpi,
        "orden": paso.orden,
    }


def _serializar_seguimiento(seguimiento):
    return {
        "tiene_cuenta_vinculada": seguimiento["tiene_cuenta_vinculada"],
        "periodo": {
            "fecha_inicio": seguimiento["periodo"]["fecha_inicio"].isoformat(),
            "fecha_fin": seguimiento["periodo"]["fecha_fin"].isoformat(),
        },
        "presupuesto": seguimiento["presupuesto"],
        "kpi_principal": seguimiento["kpi_principal"],
    }


def _serializar_paquete_proyecto_estrategico(proyecto, diagnostico, error_diagnostico, audiencias_disponibles, seguimiento, periodo):
    return {
        "proyecto": _serializar_proyecto_estrategico(proyecto),
        "presupuesto": resumen_presupuesto_proyecto_estrategico(proyecto),
        "fases": [_serializar_fase_estrategica(f) for f in proyecto.fases],
        "secuencia": [_serializar_paso_secuencia(p) for p in proyecto.secuencia],
        "audiencias_disponibles": audiencias_disponibles,
        "seguimiento": _serializar_seguimiento(seguimiento),
        "diagnostico": _serializar_inteligencia(diagnostico, proyecto.cuenta_publicitaria_id, periodo) if diagnostico else None,
        "error_diagnostico": error_diagnostico,
        "claves_kpi": CLAVES_KPI,
        "etiquetas_kpi": ETIQUETAS_KPI,
        "tipos_audiencia": TIPOS_AUDIENCIA_ESTRATEGICA,
        "estados": ESTADOS_PROYECTO_ESTRATEGICO,
    }


@datos_meta_bp.get("/proyectos-estrategicos")
@login_required
def proyectos_estrategicos_lista():
    empresa, _rol = _empresa_activa_o_404()
    proyectos = listar_proyectos_estrategicos_empresa(empresa.id)
    cuentas = listar_entidades_empresa(empresa.id, tipo="cuenta_publicitaria")

    return render_template(
        "datos_meta/proyectos_estrategicos_lista.html",
        empresa_activa=empresa,
        proyectos=proyectos,
        cuentas=cuentas,
        claves_kpi=CLAVES_KPI,
        etiquetas_kpi=ETIQUETAS_KPI,
    )


@datos_meta_bp.post("/proyectos-estrategicos/crear")
@login_required
def proyectos_estrategicos_crear():
    empresa, _rol = _empresa_activa_o_404()
    usuario = obtener_usuario_actual()

    datos = request.get_json(silent=True) or {}
    try:
        if datos.get("fecha_inicio"):
            datos["fecha_inicio"] = datetime.date.fromisoformat(datos["fecha_inicio"])
        if datos.get("fecha_fin"):
            datos["fecha_fin"] = datetime.date.fromisoformat(datos["fecha_fin"])
    except ValueError:
        return jsonify({"ok": False, "error": "Formato de fecha inválido."}), 400

    proyecto, error = crear_proyecto_estrategico(empresa.id, usuario["id"], datos)
    if error:
        return jsonify({"ok": False, "error": error}), 400
    return jsonify({"ok": True, "proyecto_id": proyecto.id}), 201


def _cargar_paquete_proyecto_estrategico(empresa, proyecto, periodo):
    diagnostico, error_diagnostico = construir_diagnostico_proyecto(proyecto, periodo["fecha_inicio"], periodo["fecha_fin"])
    audiencias_disponibles = (
        listar_audiencias_disponibles(empresa.id, proyecto.cuenta_publicitaria_id) if proyecto.cuenta_publicitaria_id else []
    )
    seguimiento = construir_seguimiento(proyecto)
    return _serializar_paquete_proyecto_estrategico(proyecto, diagnostico, error_diagnostico, audiencias_disponibles, seguimiento, periodo)


@datos_meta_bp.get("/proyectos-estrategicos/<int:proyecto_id>")
@login_required
def proyectos_estrategicos_detalle(proyecto_id):
    empresa, _rol = _empresa_activa_o_404()
    proyecto = obtener_proyecto_estrategico(empresa.id, proyecto_id)
    if proyecto is None:
        abort(404)

    periodo = _leer_periodo_y_comparar(request.args)
    datos = _cargar_paquete_proyecto_estrategico(empresa, proyecto, periodo)

    return render_template(
        "datos_meta/proyectos_estrategicos_detalle.html",
        empresa_activa=empresa,
        cuentas=listar_entidades_empresa(empresa.id, tipo="cuenta_publicitaria"),
        datos=datos,
        periodos=PERIODOS_PREDEFINIDOS,
        etiquetas_periodos=ETIQUETAS_PERIODOS,
        periodo_clave=periodo["periodo_clave"],
    )


@datos_meta_bp.get("/proyectos-estrategicos/<int:proyecto_id>/datos")
@login_required
def proyectos_estrategicos_datos(proyecto_id):
    empresa, _rol = _empresa_activa_o_404()
    proyecto = obtener_proyecto_estrategico(empresa.id, proyecto_id)
    if proyecto is None:
        return jsonify({"ok": False, "error": "El proyecto no existe o no pertenece a esta empresa."}), 404

    periodo = _leer_periodo_y_comparar(request.args)
    return jsonify(_cargar_paquete_proyecto_estrategico(empresa, proyecto, periodo))


@datos_meta_bp.post("/proyectos-estrategicos/<int:proyecto_id>/estado")
@login_required
def proyectos_estrategicos_cambiar_estado(proyecto_id):
    empresa, _rol = _empresa_activa_o_404()
    datos = request.get_json(silent=True) or {}

    proyecto, error = cambiar_estado_proyecto_estrategico(empresa.id, proyecto_id, datos.get("estado"))
    if error:
        return jsonify({"ok": False, "error": error}), 400
    return jsonify({"ok": True, "estado": proyecto.estado})


@datos_meta_bp.post("/proyectos-estrategicos/<int:proyecto_id>/fases")
@login_required
def proyectos_estrategicos_agregar_fase(proyecto_id):
    empresa, _rol = _empresa_activa_o_404()
    datos = request.get_json(silent=True) or {}
    try:
        if datos.get("fecha_inicio"):
            datos["fecha_inicio"] = datetime.date.fromisoformat(datos["fecha_inicio"])
        if datos.get("fecha_fin"):
            datos["fecha_fin"] = datetime.date.fromisoformat(datos["fecha_fin"])
    except ValueError:
        return jsonify({"ok": False, "error": "Formato de fecha inválido."}), 400

    fase, error = agregar_fase(empresa.id, proyecto_id, datos)
    if error:
        return jsonify({"ok": False, "error": error}), 400
    return jsonify({"ok": True, "fase_id": fase.id}), 201


@datos_meta_bp.post("/proyectos-estrategicos/<int:proyecto_id>/fases/<int:fase_id>/eliminar")
@login_required
def proyectos_estrategicos_eliminar_fase(proyecto_id, fase_id):
    empresa, _rol = _empresa_activa_o_404()
    ok, error = eliminar_fase(empresa.id, proyecto_id, fase_id)
    if not ok:
        return jsonify({"ok": False, "error": error}), 400
    return jsonify({"ok": True})


@datos_meta_bp.post("/proyectos-estrategicos/<int:proyecto_id>/secuencia")
@login_required
def proyectos_estrategicos_agregar_secuencia(proyecto_id):
    empresa, _rol = _empresa_activa_o_404()
    datos = request.get_json(silent=True) or {}

    paso, error = agregar_paso_secuencia(empresa.id, proyecto_id, datos)
    if error:
        return jsonify({"ok": False, "error": error}), 400
    return jsonify({"ok": True, "paso_id": paso.id}), 201


@datos_meta_bp.post("/proyectos-estrategicos/<int:proyecto_id>/secuencia/<int:paso_id>/eliminar")
@login_required
def proyectos_estrategicos_eliminar_secuencia(proyecto_id, paso_id):
    empresa, _rol = _empresa_activa_o_404()
    ok, error = eliminar_paso_secuencia(empresa.id, proyecto_id, paso_id)
    if not ok:
        return jsonify({"ok": False, "error": error}), 400
    return jsonify({"ok": True})
