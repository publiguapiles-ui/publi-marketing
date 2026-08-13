"""Pruebas del Paso 4 de Datos de Meta: dashboard visual -- filtros
(cuenta, campaña, estado, período, comparar), que las tarjetas de KPI
mostradas provienen tal cual del motor del Paso 3 (nunca recalculadas
aquí), la serie diaria para gráficos, la comparación de períodos, el
presupuesto (planificado/gastado/disponible/% ejecutado) y el
aislamiento multiempresa. Todo se verifica contra el endpoint JSON
/datos-meta/dashboard/datos -- es la forma robusta de probar un
dashboard cuyo renderizado real ocurre en JavaScript.
"""

import datetime

from app.models import EntidadPublicitaria


def _crear_cuenta(empresa_id, id_externo, moneda="USD"):
    from app.extensions import db

    cuenta = EntidadPublicitaria(
        empresa_id=empresa_id, fuente="meta", tipo="cuenta_publicitaria",
        id_externo=id_externo, nombre=f"Cuenta {id_externo}", atributos={"moneda": moneda},
    )
    db.session.add(cuenta)
    db.session.commit()
    return cuenta


def _crear_campana(empresa_id, id_externo, entidad_padre_id=None, nombre=None, estado="ACTIVE", objetivo=None):
    from app.extensions import db

    campana = EntidadPublicitaria(
        empresa_id=empresa_id, fuente="meta", tipo="campana", id_externo=id_externo,
        nombre=nombre or f"Campaña {id_externo}", entidad_padre_id=entidad_padre_id,
        estado=estado, atributos={"objetivo": objetivo} if objetivo else {},
    )
    db.session.add(campana)
    db.session.commit()
    return campana


def _registrar(empresa_id, campana, metrica, valor, fecha):
    from app.services.metricas import registrar_metrica

    registrar_metrica(empresa_id, metrica, valor, fecha, entidad_id=campana.id, entidad_tipo="campana")


# --- Filtros: sin cuenta (toda la empresa) ------------------------------------------

def test_dashboard_datos_sin_filtros_agrega_toda_la_empresa(client, usuario_a_con_empresa):
    with client.application.app_context():
        campana = _crear_campana(usuario_a_con_empresa["empresa_id"], "c1")
        _registrar(usuario_a_con_empresa["empresa_id"], campana, "spend", 50.0, datetime.date(2026, 8, 1))
        _registrar(usuario_a_con_empresa["empresa_id"], campana, "impressions", 1000.0, datetime.date(2026, 8, 1))

    resp = client.get("/datos-meta/dashboard/datos?periodo=personalizado&fecha_inicio=2026-08-01&fecha_fin=2026-08-01")
    assert resp.status_code == 200
    datos = resp.get_json()
    assert datos["kpis"]["spend"] == 50.0
    assert datos["kpis"]["impressions"] == 1000


def test_dashboard_datos_kpi_no_disponible_es_null_no_cero(client, usuario_a_con_empresa):
    with client.application.app_context():
        campana = _crear_campana(usuario_a_con_empresa["empresa_id"], "c1")
        _registrar(usuario_a_con_empresa["empresa_id"], campana, "spend", 10.0, datetime.date(2026, 8, 1))

    resp = client.get("/datos-meta/dashboard/datos?periodo=personalizado&fecha_inicio=2026-08-01&fecha_fin=2026-08-01")
    datos = resp.get_json()
    assert datos["kpis"]["roas"] is None
    assert datos["kpis"]["conversiones"] is None


# --- Filtro por cuenta publicitaria --------------------------------------------------

def test_dashboard_datos_filtra_por_cuenta(client, usuario_a_con_empresa):
    with client.application.app_context():
        cuenta_1 = _crear_cuenta(usuario_a_con_empresa["empresa_id"], "act_1")
        cuenta_2 = _crear_cuenta(usuario_a_con_empresa["empresa_id"], "act_2")
        c1 = _crear_campana(usuario_a_con_empresa["empresa_id"], "c1", entidad_padre_id=cuenta_1.id)
        c2 = _crear_campana(usuario_a_con_empresa["empresa_id"], "c2", entidad_padre_id=cuenta_2.id)
        _registrar(usuario_a_con_empresa["empresa_id"], c1, "spend", 100.0, datetime.date(2026, 8, 1))
        _registrar(usuario_a_con_empresa["empresa_id"], c2, "spend", 999.0, datetime.date(2026, 8, 1))
        cuenta_1_id = cuenta_1.id

    resp = client.get(f"/datos-meta/dashboard/datos?cuenta_id={cuenta_1_id}&periodo=personalizado&fecha_inicio=2026-08-01&fecha_fin=2026-08-01")
    datos = resp.get_json()
    assert datos["kpis"]["spend"] == 100.0  # nunca 1099.0 (no mezcla la otra cuenta)


def test_dashboard_datos_incluye_moneda_solo_con_cuenta_especifica(client, usuario_a_con_empresa):
    with client.application.app_context():
        cuenta = _crear_cuenta(usuario_a_con_empresa["empresa_id"], "act_1", moneda="EUR")
        cuenta_id = cuenta.id

    resp_toda = client.get("/datos-meta/dashboard/datos")
    assert resp_toda.get_json()["moneda_cuenta"] is None

    resp_cuenta = client.get(f"/datos-meta/dashboard/datos?cuenta_id={cuenta_id}")
    assert resp_cuenta.get_json()["moneda_cuenta"] == "EUR"


# --- Filtro por campaña especifica (drill-down) --------------------------------------

def test_dashboard_datos_filtra_por_campana_especifica(client, usuario_a_con_empresa):
    with client.application.app_context():
        cuenta = _crear_cuenta(usuario_a_con_empresa["empresa_id"], "act_1")
        c1 = _crear_campana(usuario_a_con_empresa["empresa_id"], "c1", entidad_padre_id=cuenta.id)
        c2 = _crear_campana(usuario_a_con_empresa["empresa_id"], "c2", entidad_padre_id=cuenta.id)
        _registrar(usuario_a_con_empresa["empresa_id"], c1, "spend", 30.0, datetime.date(2026, 8, 1))
        _registrar(usuario_a_con_empresa["empresa_id"], c2, "spend", 70.0, datetime.date(2026, 8, 1))
        cuenta_id, c1_id = cuenta.id, c1.id

    resp = client.get(f"/datos-meta/dashboard/datos?cuenta_id={cuenta_id}&campana_id={c1_id}&periodo=personalizado&fecha_inicio=2026-08-01&fecha_fin=2026-08-01")
    datos = resp.get_json()
    assert datos["kpis"]["spend"] == 30.0


def test_dashboard_datos_campana_ajena_no_filtra_nada_indebido(client, usuario_a_con_empresa, usuario_b_con_empresa):
    """Un campana_id de otra empresa nunca debe filtrar hacia datos de
    esa otra empresa -- como minimo debe ser ignorado con seguridad."""
    from tests.conftest import iniciar_sesion_de_prueba

    with client.application.app_context():
        cuenta_b = _crear_cuenta(usuario_b_con_empresa["empresa_id"], "act_b")
        campana_b = _crear_campana(usuario_b_con_empresa["empresa_id"], "cb", entidad_padre_id=cuenta_b.id)
        _registrar(usuario_b_con_empresa["empresa_id"], campana_b, "spend", 500.0, datetime.date(2026, 8, 1))
        campana_b_id = campana_b.id

        cuenta_a = _crear_cuenta(usuario_a_con_empresa["empresa_id"], "act_a")
        campana_a = _crear_campana(usuario_a_con_empresa["empresa_id"], "ca", entidad_padre_id=cuenta_a.id)
        _registrar(usuario_a_con_empresa["empresa_id"], campana_a, "spend", 20.0, datetime.date(2026, 8, 1))
        cuenta_a_id = campana_a.entidad_padre_id

    iniciar_sesion_de_prueba(client, usuario_a_con_empresa["usuario_id"], "a@example.com")
    resp = client.get(f"/datos-meta/dashboard/datos?cuenta_id={cuenta_a_id}&campana_id={campana_b_id}&periodo=personalizado&fecha_inicio=2026-08-01&fecha_fin=2026-08-01")
    datos = resp.get_json()
    assert datos["kpis"]["spend"] == 20.0  # nunca 500.0 de la otra empresa


# --- Filtro por estado ------------------------------------------------------------

def test_dashboard_datos_filtra_por_estado(client, usuario_a_con_empresa):
    with client.application.app_context():
        cuenta = _crear_cuenta(usuario_a_con_empresa["empresa_id"], "act_1")
        activa = _crear_campana(usuario_a_con_empresa["empresa_id"], "activa", entidad_padre_id=cuenta.id, estado="ACTIVE")
        pausada = _crear_campana(usuario_a_con_empresa["empresa_id"], "pausada", entidad_padre_id=cuenta.id, estado="PAUSED")
        _registrar(usuario_a_con_empresa["empresa_id"], activa, "spend", 40.0, datetime.date(2026, 8, 1))
        _registrar(usuario_a_con_empresa["empresa_id"], pausada, "spend", 60.0, datetime.date(2026, 8, 1))
        cuenta_id = cuenta.id

    resp_activas = client.get(f"/datos-meta/dashboard/datos?cuenta_id={cuenta_id}&estado=activas&periodo=personalizado&fecha_inicio=2026-08-01&fecha_fin=2026-08-01")
    datos_activas = resp_activas.get_json()
    assert datos_activas["kpis"]["spend"] == 40.0
    assert len(datos_activas["tabla_campanas"]) == 1
    assert datos_activas["tabla_campanas"][0]["estado"] == "ACTIVE"

    resp_todas = client.get(f"/datos-meta/dashboard/datos?cuenta_id={cuenta_id}&estado=todas&periodo=personalizado&fecha_inicio=2026-08-01&fecha_fin=2026-08-01")
    assert resp_todas.get_json()["kpis"]["spend"] == 100.0
    assert len(resp_todas.get_json()["tabla_campanas"]) == 2


def test_dashboard_datos_estado_invalido_se_ignora(client, usuario_a_con_empresa):
    resp = client.get("/datos-meta/dashboard/datos?estado=no_existe")
    assert resp.status_code == 200
    assert resp.get_json()["filtros"]["estado"] == "todas"


# --- Serie diaria (graficos) ---------------------------------------------------------

def test_dashboard_datos_serie_diaria_cubre_todo_el_rango(client, usuario_a_con_empresa):
    with client.application.app_context():
        campana = _crear_campana(usuario_a_con_empresa["empresa_id"], "c1")
        _registrar(usuario_a_con_empresa["empresa_id"], campana, "spend", 10.0, datetime.date(2026, 8, 1))
        _registrar(usuario_a_con_empresa["empresa_id"], campana, "spend", 20.0, datetime.date(2026, 8, 3))

    resp = client.get("/datos-meta/dashboard/datos?periodo=personalizado&fecha_inicio=2026-08-01&fecha_fin=2026-08-03")
    serie = resp.get_json()["serie_diaria"]
    assert [d["fecha"] for d in serie] == ["2026-08-01", "2026-08-02", "2026-08-03"]
    assert serie[0]["spend"] == 10.0
    assert serie[1]["spend"] is None  # dia sin sincronizar -- nunca 0 inventado
    assert serie[2]["spend"] == 20.0


# --- Comparacion con periodo anterior --------------------------------------------------

def test_dashboard_datos_sin_comparar_no_incluye_comparacion(client, usuario_a_con_empresa):
    resp = client.get("/datos-meta/dashboard/datos?periodo=personalizado&fecha_inicio=2026-08-01&fecha_fin=2026-08-01")
    assert resp.get_json()["comparacion"] is None


def test_dashboard_datos_comparar_incluye_variacion(client, usuario_a_con_empresa):
    with client.application.app_context():
        campana = _crear_campana(usuario_a_con_empresa["empresa_id"], "c1")
        _registrar(usuario_a_con_empresa["empresa_id"], campana, "spend", 150.0, datetime.date(2026, 8, 10))
        _registrar(usuario_a_con_empresa["empresa_id"], campana, "spend", 100.0, datetime.date(2026, 8, 9))

    resp = client.get("/datos-meta/dashboard/datos?comparar=1&periodo=personalizado&fecha_inicio=2026-08-10&fecha_fin=2026-08-10")
    datos = resp.get_json()
    assert datos["comparacion"]["periodo_actual"]["kpis"]["spend"] == 150.0
    assert datos["comparacion"]["periodo_anterior"]["kpis"]["spend"] == 100.0
    assert datos["comparacion"]["variacion_porcentual"]["spend"] == 50.0
    assert datos["filtros"]["comparar"] is True


# --- Tabla de campañas: mejor/peor -------------------------------------------------

def test_dashboard_datos_tabla_marca_mejor_y_peor(client, usuario_a_con_empresa):
    with client.application.app_context():
        cuenta = _crear_cuenta(usuario_a_con_empresa["empresa_id"], "act_1")
        alta = _crear_campana(usuario_a_con_empresa["empresa_id"], "alta", entidad_padre_id=cuenta.id, objetivo="OUTCOME_SALES")
        baja = _crear_campana(usuario_a_con_empresa["empresa_id"], "baja", entidad_padre_id=cuenta.id, objetivo="OUTCOME_TRAFFIC")
        _registrar(usuario_a_con_empresa["empresa_id"], alta, "spend", 500.0, datetime.date(2026, 8, 1))
        _registrar(usuario_a_con_empresa["empresa_id"], baja, "spend", 10.0, datetime.date(2026, 8, 1))
        cuenta_id = cuenta.id

    resp = client.get(f"/datos-meta/dashboard/datos?cuenta_id={cuenta_id}&periodo=personalizado&fecha_inicio=2026-08-01&fecha_fin=2026-08-01")
    tabla = resp.get_json()["tabla_campanas"]
    por_nombre = {f["nombre"]: f for f in tabla}
    assert por_nombre["Campaña alta"]["es_mejor"] is True
    assert por_nombre["Campaña baja"]["es_peor"] is True
    assert por_nombre["Campaña alta"]["objetivo"] == "OUTCOME_SALES"


# --- Presupuesto -------------------------------------------------------------------

def test_dashboard_datos_presupuesto_principal_refleja_gasto_real(client, usuario_a_con_empresa):
    from app.services.presupuestos import crear_presupuesto

    with client.application.app_context():
        crear_presupuesto(
            usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"],
            "Presupuesto mensual", "estrategico", 1000.0, moneda="CRC",
            periodo_tipo="personalizado", fecha_inicio=datetime.date(2026, 8, 1), fecha_fin=datetime.date(2026, 8, 31),
        )
        campana = _crear_campana(usuario_a_con_empresa["empresa_id"], "c1")
        _registrar(usuario_a_con_empresa["empresa_id"], campana, "spend", 250.0, datetime.date(2026, 8, 5))

    resp = client.get("/datos-meta/dashboard/datos")
    principal = resp.get_json()["presupuesto_principal"]
    assert principal["monto"] == 1000.0
    assert principal["gasto_real"] == 250.0
    assert principal["disponible"] == 750.0
    assert principal["porcentaje_usado"] == 25.0


def test_dashboard_datos_sin_presupuesto_principal_es_null(client, usuario_a_con_empresa):
    resp = client.get("/datos-meta/dashboard/datos")
    assert resp.get_json()["presupuesto_principal"] is None


# --- Aislamiento multiempresa --------------------------------------------------------

def test_dashboard_datos_aislado_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from tests.conftest import iniciar_sesion_de_prueba

    with client.application.app_context():
        campana_a = _crear_campana(usuario_a_con_empresa["empresa_id"], "c1")
        _registrar(usuario_a_con_empresa["empresa_id"], campana_a, "spend", 777.0, datetime.date(2026, 8, 1))

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp = client.get("/datos-meta/dashboard/datos?periodo=personalizado&fecha_inicio=2026-08-01&fecha_fin=2026-08-01")
    assert resp.get_json()["kpis"]["spend"] is None


def test_dashboard_datos_cuenta_de_otra_empresa_da_error_sin_filtrar_datos(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from tests.conftest import iniciar_sesion_de_prueba

    with client.application.app_context():
        cuenta_b = _crear_cuenta(usuario_b_con_empresa["empresa_id"], "act_b")
        cuenta_b_id = cuenta_b.id

    iniciar_sesion_de_prueba(client, usuario_a_con_empresa["usuario_id"], "a@example.com")
    resp = client.get(f"/datos-meta/dashboard/datos?cuenta_id={cuenta_b_id}")
    datos = resp.get_json()
    assert datos["error_cuenta"] is not None
    assert datos["kpis"]["spend"] is None


# --- Ruta HTML (carga inicial) -------------------------------------------------------

def test_ruta_dashboard_html_carga_y_embebe_json(client, usuario_a_con_empresa):
    resp = client.get("/datos-meta/dashboard")
    assert resp.status_code == 200
    texto = resp.get_data(as_text=True)
    assert "DM_DASHBOARD_INICIAL" in texto
    assert "Aplicar filtros" in texto


def test_ruta_dashboard_periodo_personalizado_sin_fechas_usa_respaldo(client, usuario_a_con_empresa):
    resp = client.get("/datos-meta/dashboard?periodo=personalizado")
    assert resp.status_code == 200  # nunca 500 -- cae de vuelta a ultimos_30_dias
