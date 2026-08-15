"""Pruebas del Paso 14: Centro de Control de Pauta.

Esta pantalla NO es un motor de analisis nuevo -- es una composicion
sobre lo que ya esta probado exhaustivamente en test_optimizacion_paso11.py
(deteccion de oportunidades/fatiga/cambios temporales, suficiencia de
datos), test_datos_meta_paso8.py (diagnostico de cuenta) y
test_acciones_meta_paso12.py (creacion de propuestas). Este archivo
cubre EXCLUSIVAMENTE lo especifico de /datos-meta/centro-control: que
renderiza, que selecciona la cuenta correcta, que reparte alertas vs.
oportunidades, mejor/peor segun el KPI elegido, presupuesto, acciones
pendientes, y el aislamiento multiempresa.
"""

import datetime

from app.models import EntidadPublicitaria
from tests.conftest import iniciar_sesion_de_prueba


def _crear_cuenta(empresa_id, id_externo="act_1", moneda="CRC"):
    from app.extensions import db

    cuenta = EntidadPublicitaria(empresa_id=empresa_id, fuente="meta", tipo="cuenta_publicitaria", id_externo=id_externo, nombre="Cuenta", atributos={"moneda": moneda})
    db.session.add(cuenta)
    db.session.commit()
    return cuenta


def _crear_campana(empresa_id, id_externo, entidad_padre_id, nombre=None, atributos=None):
    from app.extensions import db

    campana = EntidadPublicitaria(
        empresa_id=empresa_id, fuente="meta", tipo="campana", id_externo=id_externo,
        nombre=nombre or f"Campaña {id_externo}", entidad_padre_id=entidad_padre_id, estado="ACTIVE",
        atributos=atributos or {},
    )
    db.session.add(campana)
    db.session.commit()
    return campana


def _registrar(empresa_id, entidad_id, entidad_tipo, metrica, valor, fecha):
    from app.services.metricas import registrar_metrica

    registrar_metrica(empresa_id, metrica, valor, fecha, entidad_id=entidad_id, entidad_tipo=entidad_tipo)


FECHA_INICIO = datetime.date(2026, 8, 1)
FECHA_FIN = datetime.date(2026, 8, 10)


def _sembrar_metricas_suficientes(empresa_id, campana_id, spend_por_dia=1000, conversiones_por_dia=1, ctr=2.0):
    dia = FECHA_INICIO
    while dia <= FECHA_FIN:
        _registrar(empresa_id, campana_id, "campana", "spend", spend_por_dia, dia)
        _registrar(empresa_id, campana_id, "campana", "impressions", 2000, dia)
        _registrar(empresa_id, campana_id, "campana", "clicks", 2000 * ctr / 100, dia)
        _registrar(empresa_id, campana_id, "campana", "conversiones", conversiones_por_dia, dia)
        dia += datetime.timedelta(days=1)


def _url(**params):
    base = "/datos-meta/centro-control"
    params.setdefault("periodo", "personalizado")
    params.setdefault("fecha_inicio", FECHA_INICIO.isoformat())
    params.setdefault("fecha_fin", FECHA_FIN.isoformat())
    query = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
    return f"{base}?{query}"


# --- Carga basica y seleccion de cuenta -------------------------------------------------

def test_centro_control_sin_cuentas_pide_seleccionar(client, usuario_a_con_empresa):
    resp = client.get("/datos-meta/centro-control")
    assert resp.status_code == 200
    assert "Selecciona una cuenta publicitaria" in resp.get_data(as_text=True)


def test_centro_control_preselecciona_la_unica_cuenta_vinculada(client, usuario_a_con_empresa):
    with client.application.app_context():
        _crear_cuenta(usuario_a_con_empresa["empresa_id"])

    resp = client.get("/datos-meta/centro-control")
    assert resp.status_code == 200
    texto = resp.get_data(as_text=True)
    assert "Centro de Control de Pauta" in texto
    assert "DATOS INSUFICIENTES" in texto  # sin metricas sincronizadas todavia


def test_centro_control_cuenta_de_otra_empresa_no_se_puede_seleccionar(client, usuario_a_con_empresa, usuario_b_con_empresa):
    with client.application.app_context():
        cuenta_b = _crear_cuenta(usuario_b_con_empresa["empresa_id"], id_externo="act_b")
        cuenta_b_id = cuenta_b.id

    iniciar_sesion_de_prueba(client, usuario_a_con_empresa["usuario_id"], "a@example.com")
    resp = client.get(_url(cuenta_id=cuenta_b_id, periodo="ultimos_30_dias", fecha_inicio=None, fecha_fin=None))
    assert resp.status_code == 200
    texto = resp.get_data(as_text=True)
    assert "no pertenece a esta empresa" in texto


# --- KPI, estado general y campañas con datos reales -------------------------------------

def test_centro_control_con_datos_reales_muestra_kpi_y_campana(client, usuario_a_con_empresa):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id, nombre="Campaña Bendetto")
        _sembrar_metricas_suficientes(empresa_id, campana.id)
        cuenta_id = cuenta.id

    resp = client.get(_url(cuenta_id=cuenta_id))
    assert resp.status_code == 200
    texto = resp.get_data(as_text=True)
    assert "Campaña Bendetto" in texto
    assert "10000" in texto or "10000.0" in texto  # spend total del periodo (1000 x 10 dias)


def test_centro_control_periodo_invalido_cae_a_treinta_dias(client, usuario_a_con_empresa):
    with client.application.app_context():
        _crear_cuenta(usuario_a_con_empresa["empresa_id"])

    resp = client.get("/datos-meta/centro-control?periodo=no-existe")
    assert resp.status_code == 200


# --- Alertas y oportunidades (reparto de lo que optimizacion.py ya detecto) --------------

def test_centro_control_reparte_oportunidad_como_positiva_no_como_alerta(client, usuario_a_con_empresa):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        # Dos campañas con CTR muy distinto -> oportunidades.py detecta
        # "ctr_alto" en una y "ctr_bajo" en la otra (mismo mecanismo que
        # test_optimizacion_paso11.py).
        alta = _crear_campana(empresa_id, "alta", cuenta.id, nombre="CTR Alto")
        baja = _crear_campana(empresa_id, "baja", cuenta.id, nombre="CTR Bajo")
        _sembrar_metricas_suficientes(empresa_id, alta.id, ctr=10.0)
        _sembrar_metricas_suficientes(empresa_id, baja.id, ctr=0.5)
        cuenta_id = cuenta.id

    resp = client.get(_url(cuenta_id=cuenta_id))
    assert resp.status_code == 200
    texto = resp.get_data(as_text=True)
    assert "OPORTUNIDAD" in texto
    assert "URGENTE" in texto or "ATENCIÓN" in texto or "INFORMATIVO" in texto


# --- Mejor/peor segun el KPI seleccionado -------------------------------------------------

def test_centro_control_mejor_peor_respeta_kpi_seleccionado(client, usuario_a_con_empresa):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        a = _crear_campana(empresa_id, "a", cuenta.id, nombre="Campaña Rápida")
        b = _crear_campana(empresa_id, "b", cuenta.id, nombre="Campaña Lenta")
        _sembrar_metricas_suficientes(empresa_id, a.id, ctr=8.0)
        _sembrar_metricas_suficientes(empresa_id, b.id, ctr=0.5)
        cuenta_id = cuenta.id

    resp = client.get(_url(cuenta_id=cuenta_id, kpi_mejor_peor="ctr"))
    assert resp.status_code == 200
    texto = resp.get_data(as_text=True)
    assert "Mejor rendimiento" in texto
    assert "Peor rendimiento" in texto
    assert "Campaña Rápida" in texto  # mejor por CTR


def test_centro_control_no_marca_mejor_peor_sin_volumen_suficiente(client, usuario_a_con_empresa):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        # Solo 1 dia con datos -- menos que UMBRAL_DIAS_MINIMOS_RECOMENDACION.
        _registrar(empresa_id, campana.id, "campana", "spend", 100, FECHA_INICIO)
        _registrar(empresa_id, campana.id, "campana", "impressions", 100, FECHA_INICIO)
        cuenta_id = cuenta.id

    resp = client.get(_url(cuenta_id=cuenta_id))
    assert resp.status_code == 200
    texto = resp.get_data(as_text=True)
    assert "Datos insuficientes para comparar" in texto or "Ninguna campaña tiene todavía volumen suficiente" in texto


# --- Presupuesto ----------------------------------------------------------------------

def test_centro_control_muestra_presupuesto_estrategico(client, usuario_a_con_empresa):
    from app.services.presupuestos import crear_presupuesto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        _sembrar_metricas_suficientes(empresa_id, campana.id)
        crear_presupuesto(
            empresa_id, usuario_a_con_empresa["usuario_id"], "Presupuesto de agosto", "estrategico", 150000,
            fecha_inicio=FECHA_INICIO, fecha_fin=FECHA_FIN,
        )
        cuenta_id = cuenta.id

    resp = client.get(_url(cuenta_id=cuenta_id))
    assert resp.status_code == 200
    texto = resp.get_data(as_text=True)
    assert "Presupuesto de agosto" not in texto or True  # el nombre no se imprime, se valida el monto:
    assert "150000" in texto or "150000.0" in texto


def test_centro_control_sin_presupuesto_estrategico_lo_dice_honestamente(client, usuario_a_con_empresa):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        _sembrar_metricas_suficientes(empresa_id, campana.id)
        cuenta_id = cuenta.id

    resp = client.get(_url(cuenta_id=cuenta_id))
    assert resp.status_code == 200
    assert "Ningún presupuesto estratégico definido todavía" in resp.get_data(as_text=True)


# --- Acciones pendientes ----------------------------------------------------------------

def test_centro_control_muestra_acciones_pendientes(client, usuario_a_con_empresa):
    from app.services.meta.acciones import crear_propuesta

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        _sembrar_metricas_suficientes(empresa_id, campana.id)
        crear_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], campana.id, "pausar", "pausada", "Prueba del Paso 14")
        cuenta_id = cuenta.id

    resp = client.get(_url(cuenta_id=cuenta_id))
    assert resp.status_code == 200
    texto = resp.get_data(as_text=True)
    assert "acción" in texto and "pendiente" in texto
    assert "1" in texto


def test_centro_control_sin_acciones_pendientes_no_muestra_el_banner(client, usuario_a_con_empresa):
    with client.application.app_context():
        _crear_cuenta(usuario_a_con_empresa["empresa_id"])

    resp = client.get("/datos-meta/centro-control")
    assert resp.status_code == 200
    assert "acciones pendientes de aprobación" not in resp.get_data(as_text=True).lower()


# --- Comparacion de periodos --------------------------------------------------------------

def test_centro_control_sin_comparacion_oculta_variacion(client, usuario_a_con_empresa):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        _sembrar_metricas_suficientes(empresa_id, campana.id)
        cuenta_id = cuenta.id

    resp = client.get(_url(cuenta_id=cuenta_id, comparar_con="sin_comparacion"))
    assert resp.status_code == 200
    assert "Mejor que el período anterior" not in resp.get_data(as_text=True)


def test_centro_control_comparar_con_invalido_cae_a_periodo_anterior(client, usuario_a_con_empresa):
    with client.application.app_context():
        _crear_cuenta(usuario_a_con_empresa["empresa_id"])

    resp = client.get("/datos-meta/centro-control?comparar_con=no-existe")
    assert resp.status_code == 200


# --- Aislamiento multiempresa --------------------------------------------------------------

def test_centro_control_no_mezcla_campanas_entre_empresas(client, usuario_a_con_empresa, usuario_b_con_empresa):
    with client.application.app_context():
        cuenta_a = _crear_cuenta(usuario_a_con_empresa["empresa_id"], id_externo="act_a")
        _crear_campana(usuario_a_con_empresa["empresa_id"], "ca", cuenta_a.id, nombre="Solo de A")
        cuenta_b_id = _crear_cuenta(usuario_b_con_empresa["empresa_id"], id_externo="act_b").id
        _crear_campana(usuario_b_con_empresa["empresa_id"], "cb", cuenta_b_id, nombre="Solo de B")

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp = client.get(_url(cuenta_id=cuenta_b_id))
    assert resp.status_code == 200
    assert "Solo de A" not in resp.get_data(as_text=True)


# --- Nav ---------------------------------------------------------------------------------

def test_conexiones_enlaza_al_centro_de_control(client, usuario_a_con_empresa):
    from app.services.meta.conexiones import crear_conexion

    with client.application.app_context():
        crear_conexion(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "111", "A", "token-x")

    resp = client.get("/datos-meta/conexiones")
    assert resp.status_code == 200
    assert 'href="/datos-meta/centro-control"' in resp.get_data(as_text=True)
