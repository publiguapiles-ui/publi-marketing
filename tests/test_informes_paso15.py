"""Pruebas del Paso 15: Informes ejecutivos de pauta.

Esta pantalla NO es un motor de metricas nuevo -- test_centro_control_paso14.py
y test_optimizacion_paso11.py ya prueban a fondo el motor que
informes.py reutiliza (construir_centro_control -> construir_centro_
optimizacion). Este archivo cubre EXCLUSIVAMENTE lo especifico del
Paso 15: creacion de informes, tipos, periodos/comparacion, filtros
opcionales, version automatica al regenerar, snapshot persistente,
generacion de PDF, historial, permisos y aislamiento multiempresa.
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


def _cuerpo_crear(cuenta_id, tipo="ejecutivo", periodo="personalizado", tipo_comparacion="periodo_anterior", **extra):
    cuerpo = {
        "cuenta_id": cuenta_id, "tipo": tipo, "periodo": periodo,
        "fecha_inicio": FECHA_INICIO.isoformat(), "fecha_fin": FECHA_FIN.isoformat(),
        "tipo_comparacion": tipo_comparacion,
    }
    cuerpo.update(extra)
    return cuerpo


# --- Creacion basica, tipos y permisos ---------------------------------------------------

def test_crear_informe_ejecutivo_con_datos_reales(client, usuario_a_con_empresa):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id, nombre="Campaña Bendetto")
        _sembrar_metricas_suficientes(empresa_id, campana.id)
        cuenta_id = cuenta.id

    resp = client.post("/datos-meta/informes/crear", json=_cuerpo_crear(cuenta_id))
    assert resp.status_code == 201
    datos = resp.get_json()
    assert datos["ok"] is True
    assert datos["estado"] == "listo"
    assert datos["version"] == 1


def test_crear_informe_tipo_invalido_rechaza(client, usuario_a_con_empresa):
    with client.application.app_context():
        cuenta_id = _crear_cuenta(usuario_a_con_empresa["empresa_id"]).id

    resp = client.post("/datos-meta/informes/crear", json=_cuerpo_crear(cuenta_id, tipo="no-existe"))
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_crear_informe_cuenta_de_otra_empresa_rechaza(client, usuario_a_con_empresa, usuario_b_con_empresa):
    with client.application.app_context():
        cuenta_b_id = _crear_cuenta(usuario_b_con_empresa["empresa_id"], id_externo="act_b").id

    iniciar_sesion_de_prueba(client, usuario_a_con_empresa["usuario_id"], "a@example.com")
    resp = client.post("/datos-meta/informes/crear", json=_cuerpo_crear(cuenta_b_id))
    assert resp.status_code == 400
    assert "no pertenece" in resp.get_json()["error"]


def test_crear_informe_periodo_invalido_rechaza(client, usuario_a_con_empresa):
    with client.application.app_context():
        cuenta_id = _crear_cuenta(usuario_a_con_empresa["empresa_id"]).id

    resp = client.post("/datos-meta/informes/crear", json=_cuerpo_crear(cuenta_id, periodo="no-existe"))
    assert resp.status_code == 400


# --- Los 5 tipos comparten el mismo contenido, distintas secciones -----------------------

def test_los_cinco_tipos_de_informe_se_pueden_crear(client, usuario_a_con_empresa):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        _sembrar_metricas_suficientes(empresa_id, campana.id)
        cuenta_id = cuenta.id

    for tipo in ("rendimiento", "campanas", "audiencias", "optimizacion", "ejecutivo"):
        resp = client.post("/datos-meta/informes/crear", json=_cuerpo_crear(cuenta_id, tipo=tipo))
        assert resp.status_code == 201, tipo
        assert resp.get_json()["estado"] == "listo"


def test_informe_optimizacion_no_incluye_seccion_de_campanas(client, usuario_a_con_empresa):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id, nombre="Campaña Única")
        _sembrar_metricas_suficientes(empresa_id, campana.id)
        cuenta_id = cuenta.id

    resp_crear = client.post("/datos-meta/informes/crear", json=_cuerpo_crear(cuenta_id, tipo="optimizacion"))
    informe_id = resp_crear.get_json()["informe_id"]

    resp = client.get(f"/datos-meta/informes/{informe_id}")
    assert resp.status_code == 200
    texto = resp.get_data(as_text=True)
    assert "Plan de acción" in texto or "Diagnóstico" in texto
    assert "Campañas" not in texto  # el tipo "optimizacion" no incluye la tabla de campañas


# --- Comparacion: periodo anterior / mismo periodo año anterior / sin comparacion ----------

def test_informe_sin_comparacion_no_muestra_variacion(client, usuario_a_con_empresa):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        _sembrar_metricas_suficientes(empresa_id, campana.id)
        cuenta_id = cuenta.id

    resp_crear = client.post("/datos-meta/informes/crear", json=_cuerpo_crear(cuenta_id, tipo_comparacion="sin_comparacion"))
    informe_id = resp_crear.get_json()["informe_id"]

    resp = client.get(f"/datos-meta/informes/{informe_id}")
    assert resp.status_code == 200
    assert "Comparación con el período de referencia" not in resp.get_data(as_text=True)


def test_informe_mismo_periodo_anio_anterior_se_acepta(client, usuario_a_con_empresa):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        _sembrar_metricas_suficientes(empresa_id, campana.id)
        cuenta_id = cuenta.id

    resp = client.post("/datos-meta/informes/crear", json=_cuerpo_crear(cuenta_id, tipo_comparacion="mismo_periodo_anio_anterior"))
    assert resp.status_code == 201
    assert resp.get_json()["estado"] == "listo"


# --- KPI, campañas, audiencias, diagnostico, recomendaciones ------------------------------

def test_informe_incluye_kpis_campanas_y_diagnostico_reales(client, usuario_a_con_empresa):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id, nombre="Campaña Visible")
        _sembrar_metricas_suficientes(empresa_id, campana.id)
        cuenta_id = cuenta.id

    resp_crear = client.post("/datos-meta/informes/crear", json=_cuerpo_crear(cuenta_id))
    informe_id = resp_crear.get_json()["informe_id"]

    with client.application.app_context():
        from app.services.meta.informes import obtener_informe

        informe = obtener_informe(empresa_id, informe_id)
        assert informe.contenido["kpis"]["spend"] == 10000.0
        assert informe.contenido["campanas"][0]["nombre"] == "Campaña Visible"
        assert informe.contenido["diagnostico"]["dias_con_datos"] == 10


def test_informe_audiencias_con_oportunidad_detectada(client, usuario_a_con_empresa):
    from app.models import EntidadPublicitaria as _E

    with client.application.app_context():
        from app.extensions import db

        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        conjunto_alto = _E(empresa_id=empresa_id, fuente="meta", tipo="conjunto_anuncios", id_externo="ca", nombre="Audiencia Alta", entidad_padre_id=campana.id, estado="ACTIVE")
        conjunto_bajo = _E(empresa_id=empresa_id, fuente="meta", tipo="conjunto_anuncios", id_externo="cb", nombre="Audiencia Baja", entidad_padre_id=campana.id, estado="ACTIVE")
        db.session.add_all([conjunto_alto, conjunto_bajo])
        db.session.commit()
        _sembrar_metricas_suficientes(empresa_id, conjunto_alto.id, ctr=10.0)
        _sembrar_metricas_suficientes(empresa_id, conjunto_bajo.id, ctr=0.5)
        cuenta_id = cuenta.id

    resp_crear = client.post("/datos-meta/informes/crear", json=_cuerpo_crear(cuenta_id, tipo="audiencias"))
    informe_id = resp_crear.get_json()["informe_id"]

    resp = client.get(f"/datos-meta/informes/{informe_id}")
    assert resp.status_code == 200
    texto = resp.get_data(as_text=True)
    assert "Audiencia Alta" in texto
    assert "Audiencias" in texto


def test_informe_recomendaciones_no_estan_vacias_con_oportunidades(client, usuario_a_con_empresa):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        alta = _crear_campana(empresa_id, "alta", cuenta.id, nombre="CTR Alto")
        baja = _crear_campana(empresa_id, "baja", cuenta.id, nombre="CTR Bajo")
        _sembrar_metricas_suficientes(empresa_id, alta.id, ctr=10.0)
        _sembrar_metricas_suficientes(empresa_id, baja.id, ctr=0.5)
        cuenta_id = cuenta.id

    resp_crear = client.post("/datos-meta/informes/crear", json=_cuerpo_crear(cuenta_id))
    informe_id = resp_crear.get_json()["informe_id"]

    with client.application.app_context():
        from app.services.meta.informes import obtener_informe

        informe = obtener_informe(empresa_id, informe_id)
        assert len(informe.contenido["recomendaciones"]) > 0
        assert len(informe.contenido["oportunidades"]) > 0
        assert len(informe.contenido["plan_accion"]) > 0


# --- Filtros opcionales: campanas ----------------------------------------------------------

def test_filtro_de_campanas_acota_la_tabla(client, usuario_a_con_empresa):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        incluida = _crear_campana(empresa_id, "inc", cuenta.id, nombre="Incluida")
        excluida = _crear_campana(empresa_id, "exc", cuenta.id, nombre="Excluida")
        _sembrar_metricas_suficientes(empresa_id, incluida.id)
        _sembrar_metricas_suficientes(empresa_id, excluida.id)
        cuenta_id, incluida_id = cuenta.id, incluida.id

    resp_crear = client.post("/datos-meta/informes/crear", json=_cuerpo_crear(cuenta_id, campana_ids=[incluida_id]))
    informe_id = resp_crear.get_json()["informe_id"]

    with client.application.app_context():
        from app.services.meta.informes import obtener_informe

        informe = obtener_informe(usuario_a_con_empresa["empresa_id"], informe_id)
        nombres = [c["nombre"] for c in informe.contenido["campanas"]]
        assert nombres == ["Incluida"]


# --- Datos insuficientes ------------------------------------------------------------------

def test_informe_sin_datos_indica_limitacion_honesta(client, usuario_a_con_empresa):
    with client.application.app_context():
        cuenta_id = _crear_cuenta(usuario_a_con_empresa["empresa_id"]).id

    resp_crear = client.post("/datos-meta/informes/crear", json=_cuerpo_crear(cuenta_id))
    assert resp_crear.status_code == 201
    informe_id = resp_crear.get_json()["informe_id"]

    resp = client.get(f"/datos-meta/informes/{informe_id}")
    assert resp.status_code == 200
    texto = resp.get_data(as_text=True)
    assert "período contiene pocos resultados" in texto or "DATOS INSUFICIENTES" in texto.upper()


# --- Versiones: nunca sobrescribe -----------------------------------------------------------

def test_regenerar_el_mismo_informe_crea_una_nueva_version(client, usuario_a_con_empresa):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        _sembrar_metricas_suficientes(empresa_id, campana.id)
        cuenta_id = cuenta.id

    resp1 = client.post("/datos-meta/informes/crear", json=_cuerpo_crear(cuenta_id))
    resp2 = client.post("/datos-meta/informes/crear", json=_cuerpo_crear(cuenta_id))
    assert resp1.get_json()["version"] == 1
    assert resp2.get_json()["version"] == 2
    assert resp1.get_json()["informe_id"] != resp2.get_json()["informe_id"]


def test_informes_con_filtros_distintos_versionan_por_separado(client, usuario_a_con_empresa):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        _sembrar_metricas_suficientes(empresa_id, campana.id)
        cuenta_id, campana_id = cuenta.id, campana.id

    resp_sin_filtro = client.post("/datos-meta/informes/crear", json=_cuerpo_crear(cuenta_id))
    resp_con_filtro = client.post("/datos-meta/informes/crear", json=_cuerpo_crear(cuenta_id, campana_ids=[campana_id]))
    assert resp_sin_filtro.get_json()["version"] == 1
    assert resp_con_filtro.get_json()["version"] == 1  # grupo distinto (filtros distintos) -> version propia


# --- Historial --------------------------------------------------------------------------

def test_historial_lista_informes_de_la_empresa(client, usuario_a_con_empresa):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        _sembrar_metricas_suficientes(empresa_id, campana.id)
        cuenta_id = cuenta.id

    client.post("/datos-meta/informes/crear", json=_cuerpo_crear(cuenta_id, tipo="rendimiento"))

    resp = client.get("/datos-meta/informes")
    assert resp.status_code == 200
    texto = resp.get_data(as_text=True)
    assert "Informe de Rendimiento" in texto
    assert "#1" in texto


# --- PDF -----------------------------------------------------------------------------------

def test_descargar_pdf_devuelve_documento_valido(client, usuario_a_con_empresa):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id, nombre="Campaña PDF")
        _sembrar_metricas_suficientes(empresa_id, campana.id)
        cuenta_id = cuenta.id

    resp_crear = client.post("/datos-meta/informes/crear", json=_cuerpo_crear(cuenta_id))
    informe_id = resp_crear.get_json()["informe_id"]

    resp = client.get(f"/datos-meta/informes/{informe_id}/descargar")
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data[:5] == b"%PDF-"
    assert len(resp.data) > 1000
    assert "attachment" in resp.headers.get("Content-Disposition", "")


def test_descargar_pdf_modo_cliente_tambien_genera(client, usuario_a_con_empresa):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        _sembrar_metricas_suficientes(empresa_id, campana.id)
        cuenta_id = cuenta.id

    resp_crear = client.post("/datos-meta/informes/crear", json=_cuerpo_crear(cuenta_id))
    informe_id = resp_crear.get_json()["informe_id"]

    resp = client.get(f"/datos-meta/informes/{informe_id}/descargar?modo=cliente")
    assert resp.status_code == 200
    assert resp.data[:5] == b"%PDF-"


def test_ver_informe_modo_cliente_oculta_diagnostico_tecnico(client, usuario_a_con_empresa):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        _sembrar_metricas_suficientes(empresa_id, campana.id)
        cuenta_id = cuenta.id

    resp_crear = client.post("/datos-meta/informes/crear", json=_cuerpo_crear(cuenta_id))
    informe_id = resp_crear.get_json()["informe_id"]

    resp = client.get(f"/datos-meta/informes/{informe_id}?modo=cliente")
    assert resp.status_code == 200
    texto = resp.get_data(as_text=True)
    assert "Plan de acción" not in texto
    assert "Resumen" in texto


# --- Permisos y aislamiento multiempresa ---------------------------------------------------

def test_ver_informe_de_otra_empresa_da_404(client, usuario_a_con_empresa, usuario_b_con_empresa):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        _sembrar_metricas_suficientes(empresa_id, campana.id)
        cuenta_id = cuenta.id

    # usuario_b_con_empresa deja la sesion activa como B -- se vuelve a
    # A explicitamente para crear el informe como A (mismo patron ya
    # usado en test_chat_pauta_paso13.py).
    iniciar_sesion_de_prueba(client, usuario_a_con_empresa["usuario_id"], "a@example.com")
    resp_crear = client.post("/datos-meta/informes/crear", json=_cuerpo_crear(cuenta_id))
    informe_id = resp_crear.get_json()["informe_id"]

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp = client.get(f"/datos-meta/informes/{informe_id}")
    assert resp.status_code == 404


def test_descargar_pdf_de_otra_empresa_da_404(client, usuario_a_con_empresa, usuario_b_con_empresa):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        _sembrar_metricas_suficientes(empresa_id, campana.id)
        cuenta_id = cuenta.id

    iniciar_sesion_de_prueba(client, usuario_a_con_empresa["usuario_id"], "a@example.com")
    resp_crear = client.post("/datos-meta/informes/crear", json=_cuerpo_crear(cuenta_id))
    informe_id = resp_crear.get_json()["informe_id"]

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp = client.get(f"/datos-meta/informes/{informe_id}/descargar")
    assert resp.status_code == 404


def test_historial_no_mezcla_informes_entre_empresas(client, usuario_a_con_empresa, usuario_b_con_empresa):
    with client.application.app_context():
        empresa_a = usuario_a_con_empresa["empresa_id"]
        cuenta_a = _crear_cuenta(empresa_a, id_externo="act_a")
        campana_a = _crear_campana(empresa_a, "ca", cuenta_a.id)
        _sembrar_metricas_suficientes(empresa_a, campana_a.id)
        cuenta_a_id = cuenta_a.id

    iniciar_sesion_de_prueba(client, usuario_a_con_empresa["usuario_id"], "a@example.com")
    client.post("/datos-meta/informes/crear", json=_cuerpo_crear(cuenta_a_id, tipo="ejecutivo"))

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp = client.get("/datos-meta/informes")
    assert resp.status_code == 200
    # "Informe Ejecutivo" aparece siempre en el <select> de tipos (opcion
    # fija) -- lo que nunca debe aparecer es el informe REAL de A en la
    # tabla de resultados, que se confirma con el estado vacio.
    assert "Todavía no se ha generado ningún informe" in resp.get_data(as_text=True)


# --- Nav -----------------------------------------------------------------------------------

def test_conexiones_enlaza_a_informes(client, usuario_a_con_empresa):
    from app.services.meta.conexiones import crear_conexion

    with client.application.app_context():
        crear_conexion(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "111", "A", "token-x")

    resp = client.get("/datos-meta/conexiones")
    assert resp.status_code == 200
    assert 'href="/datos-meta/informes"' in resp.get_data(as_text=True)


def test_pantalla_nuevo_informe_carga(client, usuario_a_con_empresa):
    with client.application.app_context():
        _crear_cuenta(usuario_a_con_empresa["empresa_id"])

    resp = client.get("/datos-meta/informes/nuevo")
    assert resp.status_code == 200
    assert "Nuevo informe" in resp.get_data(as_text=True)
