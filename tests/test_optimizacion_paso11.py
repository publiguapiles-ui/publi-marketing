"""Pruebas del Paso 11: centro de optimizacion de pauta.

Cubre exclusivamente lo nuevo de este paso -- deteccion de fatiga
(combinacion de 4 señales, nunca una sola), el "gate" de suficiencia
de datos antes de cualquier recomendacion, ritmo de consumo de
presupuesto, la escala de prioridad, el formato de recomendacion
explicable, el veredicto MEJOR/PEOR/CAMBIÓ de la comparacion, y el
aislamiento multiempresa a los 3 niveles (cuenta/campaña/conjunto). El
motor de KPI/oportunidades/inteligencia YA esta probado en sus propios
archivos de tests -- aqui nunca se reimplementa ese calculo.
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


def _crear_campana(empresa_id, id_externo, entidad_padre_id, nombre=None):
    from app.extensions import db

    campana = EntidadPublicitaria(
        empresa_id=empresa_id, fuente="meta", tipo="campana", id_externo=id_externo,
        nombre=nombre or f"Campaña {id_externo}", entidad_padre_id=entidad_padre_id, estado="ACTIVE",
    )
    db.session.add(campana)
    db.session.commit()
    return campana


def _crear_conjunto(empresa_id, id_externo, campana_id, nombre=None):
    from app.extensions import db

    conjunto = EntidadPublicitaria(
        empresa_id=empresa_id, fuente="meta", tipo="conjunto_anuncios", id_externo=id_externo,
        nombre=nombre or f"Conjunto {id_externo}", entidad_padre_id=campana_id, estado="ACTIVE",
    )
    db.session.add(conjunto)
    db.session.commit()
    return conjunto


def _crear_anuncio(empresa_id, id_externo, conjunto_id, nombre=None):
    from app.extensions import db

    anuncio = EntidadPublicitaria(
        empresa_id=empresa_id, fuente="meta", tipo="anuncio", id_externo=id_externo,
        nombre=nombre or f"Anuncio {id_externo}", entidad_padre_id=conjunto_id, estado="ACTIVE",
    )
    db.session.add(anuncio)
    db.session.commit()
    return anuncio


def _registrar(empresa_id, entidad_id, entidad_tipo, metrica, valor, fecha):
    from app.services.metricas import registrar_metrica

    registrar_metrica(empresa_id, metrica, valor, fecha, entidad_id=entidad_id, entidad_tipo=entidad_tipo)


FECHA_INICIO = datetime.date(2026, 8, 1)
FECHA_FIN = datetime.date(2026, 8, 10)
# periodo_anterior_equivalente(FECHA_INICIO, FECHA_FIN) -- 10 dias, igual que en test_datos_meta_paso8.py
FECHA_INICIO_ANTERIOR = datetime.date(2026, 7, 22)
FECHA_FIN_ANTERIOR = datetime.date(2026, 7, 31)


# --- Suficiencia de datos (punto 4) -----------------------------------------------------

def test_evaluar_suficiencia_datos_pocos_dias():
    from app.services.meta.optimizacion import evaluar_suficiencia_datos

    suficiente, motivo = evaluar_suficiencia_datos(1, {"impressions": 5000, "spend": 10000})
    assert suficiente is False
    assert "día" in motivo


def test_evaluar_suficiencia_datos_pocas_impresiones():
    from app.services.meta.optimizacion import evaluar_suficiencia_datos

    suficiente, motivo = evaluar_suficiencia_datos(10, {"impressions": 100, "spend": 10000})
    assert suficiente is False
    assert "impresiones" in motivo


def test_evaluar_suficiencia_datos_poco_gasto():
    from app.services.meta.optimizacion import evaluar_suficiencia_datos

    suficiente, motivo = evaluar_suficiencia_datos(10, {"impressions": 5000, "spend": 100}, moneda="CRC")
    assert suficiente is False
    assert "invertido" in motivo


def test_evaluar_suficiencia_datos_todo_suficiente():
    from app.services.meta.optimizacion import evaluar_suficiencia_datos

    suficiente, motivo = evaluar_suficiencia_datos(10, {"impressions": 5000, "spend": 10000}, moneda="CRC")
    assert suficiente is True
    assert motivo is None


# --- Fatiga (punto 5): combinacion de 4 señales, nunca una sola -------------------------

def test_detectar_fatiga_detecta_las_cuatro_senales_juntas(client, usuario_a_con_empresa):
    from app.services.meta.optimizacion import detectar_fatiga

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)

        # Periodo anterior: frequency=2.0, ctr=5%, cpc=2.0, resultados=10
        _registrar(empresa_id, campana.id, "campana", "impressions", 1000.0, FECHA_INICIO_ANTERIOR)
        _registrar(empresa_id, campana.id, "campana", "reach", 500.0, FECHA_INICIO_ANTERIOR)
        _registrar(empresa_id, campana.id, "campana", "clicks", 50.0, FECHA_INICIO_ANTERIOR)
        _registrar(empresa_id, campana.id, "campana", "spend", 100.0, FECHA_INICIO_ANTERIOR)
        _registrar(empresa_id, campana.id, "campana", "conversiones", 10.0, FECHA_INICIO_ANTERIOR)

        # Periodo actual: frequency=2.5 (+), ctr=2% (-), cpc=6.0 (+), resultados=5 (-)
        _registrar(empresa_id, campana.id, "campana", "impressions", 1000.0, FECHA_INICIO)
        _registrar(empresa_id, campana.id, "campana", "reach", 400.0, FECHA_INICIO)
        _registrar(empresa_id, campana.id, "campana", "clicks", 20.0, FECHA_INICIO)
        _registrar(empresa_id, campana.id, "campana", "spend", 120.0, FECHA_INICIO)
        _registrar(empresa_id, campana.id, "campana", "conversiones", 5.0, FECHA_INICIO)

        fatiga = detectar_fatiga(empresa_id, [campana], FECHA_INICIO, FECHA_FIN)
        assert len(fatiga) == 1
        assert fatiga[0]["entidad_id"] == campana.id
        assert fatiga[0]["evidencia"]["frecuencia_variacion_pct"] > 0
        assert fatiga[0]["evidencia"]["ctr_variacion_pct"] < 0
        assert fatiga[0]["evidencia"]["cpc_variacion_pct"] > 0
        assert fatiga[0]["evidencia"]["resultados_variacion_pct"] < 0


def test_detectar_fatiga_no_marca_si_falta_una_senal(client, usuario_a_con_empresa):
    """Sin 'reach' registrado, la frecuencia queda en None -- nunca se
    adivina, y por lo tanto no se marca fatiga aunque las otras 3
    señales sí apunten a fatiga."""
    from app.services.meta.optimizacion import detectar_fatiga

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)

        _registrar(empresa_id, campana.id, "campana", "clicks", 50.0, FECHA_INICIO_ANTERIOR)
        _registrar(empresa_id, campana.id, "campana", "impressions", 1000.0, FECHA_INICIO_ANTERIOR)
        _registrar(empresa_id, campana.id, "campana", "spend", 100.0, FECHA_INICIO_ANTERIOR)
        _registrar(empresa_id, campana.id, "campana", "conversiones", 10.0, FECHA_INICIO_ANTERIOR)

        _registrar(empresa_id, campana.id, "campana", "clicks", 20.0, FECHA_INICIO)
        _registrar(empresa_id, campana.id, "campana", "impressions", 1000.0, FECHA_INICIO)
        _registrar(empresa_id, campana.id, "campana", "spend", 120.0, FECHA_INICIO)
        _registrar(empresa_id, campana.id, "campana", "conversiones", 5.0, FECHA_INICIO)

        fatiga = detectar_fatiga(empresa_id, [campana], FECHA_INICIO, FECHA_FIN)
        assert fatiga == []


# --- Ritmo de presupuesto (punto 3) ------------------------------------------------------

def test_evaluar_ritmo_presupuesto_detecta_consumo_acelerado():
    from app.services.meta.optimizacion import evaluar_ritmo_presupuesto

    resumen = {"fecha_inicio": datetime.date(2026, 8, 1), "fecha_fin": datetime.date(2026, 8, 10), "porcentaje_usado": 80.0}
    ritmo = evaluar_ritmo_presupuesto(resumen, hoy=datetime.date(2026, 8, 3))  # 30% del tiempo transcurrido
    assert ritmo["consumiendose_rapido"] is True
    assert ritmo["porcentaje_tiempo_transcurrido"] == 30.0


def test_evaluar_ritmo_presupuesto_normal():
    from app.services.meta.optimizacion import evaluar_ritmo_presupuesto

    resumen = {"fecha_inicio": datetime.date(2026, 8, 1), "fecha_fin": datetime.date(2026, 8, 10), "porcentaje_usado": 30.0}
    ritmo = evaluar_ritmo_presupuesto(resumen, hoy=datetime.date(2026, 8, 3))
    assert ritmo["consumiendose_rapido"] is False


def test_evaluar_ritmo_presupuesto_sin_fechas_devuelve_none():
    from app.services.meta.optimizacion import evaluar_ritmo_presupuesto

    assert evaluar_ritmo_presupuesto({"fecha_inicio": None, "fecha_fin": None, "porcentaje_usado": 50}) is None


# --- Recomendacion de accion de presupuesto (punto 7) -----------------------------------

def test_recomendar_accion_presupuesto_reducir():
    from app.services.meta.optimizacion import recomendar_accion_presupuesto

    assert recomendar_accion_presupuesto(50, True) == "Reducir"


def test_recomendar_accion_presupuesto_evaluar_aumento():
    from app.services.meta.optimizacion import recomendar_accion_presupuesto

    assert recomendar_accion_presupuesto(-20, True) == "Evaluar aumento"


def test_recomendar_accion_presupuesto_mantener():
    from app.services.meta.optimizacion import recomendar_accion_presupuesto

    assert recomendar_accion_presupuesto(5, True) == "Mantener"


def test_recomendar_accion_presupuesto_esperar_mas_datos_sin_suficientes_datos():
    from app.services.meta.optimizacion import recomendar_accion_presupuesto

    assert recomendar_accion_presupuesto(50, False) == "Esperar más datos"


def test_recomendar_accion_presupuesto_esperar_mas_datos_sin_variacion():
    from app.services.meta.optimizacion import recomendar_accion_presupuesto

    assert recomendar_accion_presupuesto(None, True) == "Esperar más datos"


# --- Prioridad (punto 8) ------------------------------------------------------------------

def test_clasificar_prioridad_desde_diagnostico():
    from app.services.meta.optimizacion import clasificar_prioridad_desde_diagnostico

    assert clasificar_prioridad_desde_diagnostico("critico") == "critico"
    assert clasificar_prioridad_desde_diagnostico("atencion") == "alto"
    assert clasificar_prioridad_desde_diagnostico("bueno") == "informativo"
    assert clasificar_prioridad_desde_diagnostico("sin_datos") == "informativo"


def test_clasificar_prioridad_desde_nivel_oportunidad():
    from app.services.meta.optimizacion import clasificar_prioridad_desde_nivel_oportunidad

    assert clasificar_prioridad_desde_nivel_oportunidad("alto") == "alto"
    assert clasificar_prioridad_desde_nivel_oportunidad("medio") == "medio"
    assert clasificar_prioridad_desde_nivel_oportunidad("bajo") == "bajo"


# --- Recomendacion explicable (punto 9) --------------------------------------------------

def test_construir_recomendacion_explicable_completa():
    from app.services.meta.optimizacion import construir_recomendacion_explicable

    r = construir_recomendacion_explicable(
        tipo="deterioro", entidad_id=1, entidad_nombre="Campaña X",
        que_paso="El costo por resultado aumentó 42%.", por_que_importa="Cuesta más conseguir resultados.",
        evidencia="₡850 → ₡1.207.", recomendacion="Revisar el conjunto con mayor deterioro.",
        prioridad="critico", confianza="media",
    )
    assert r["que_paso"] == "El costo por resultado aumentó 42%."
    assert r["recomendacion"] == "Revisar el conjunto con mayor deterioro."
    assert r["prioridad"] == "critico"
    assert "media" in r["riesgo"]


def test_construir_recomendacion_explicable_datos_insuficientes_nunca_sugiere_accion():
    from app.services.meta.optimizacion import construir_recomendacion_explicable

    r = construir_recomendacion_explicable(
        tipo="deterioro", entidad_id=1, entidad_nombre="Campaña nueva",
        que_paso="El costo por resultado subió.", por_que_importa="x", evidencia="x",
        recomendacion="Reducir presupuesto ya", prioridad="critico", confianza="baja",
        suficiente_datos=False, motivo_insuficiencia="Solo 1 día con datos.",
    )
    assert r["recomendacion"] == "Datos insuficientes para recomendar un cambio."
    assert r["prioridad"] == "informativo"
    assert "1 día" in r["riesgo"]


# --- Centro de optimizacion: los 3 niveles (punto 1) --------------------------------------

def test_construir_centro_optimizacion_nivel_cuenta_compara_campanas(client, usuario_a_con_empresa):
    from app.services.meta.optimizacion import construir_centro_optimizacion

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        c1 = _crear_campana(empresa_id, "c1", cuenta.id, nombre="Campaña barata")
        c2 = _crear_campana(empresa_id, "c2", cuenta.id, nombre="Campaña cara")
        _registrar(empresa_id, c1.id, "campana", "spend", 500.0, FECHA_INICIO)
        _registrar(empresa_id, c1.id, "campana", "conversiones", 10.0, FECHA_INICIO)
        _registrar(empresa_id, c2.id, "campana", "spend", 500.0, FECHA_INICIO)
        _registrar(empresa_id, c2.id, "campana", "conversiones", 2.0, FECHA_INICIO)

        paquete, error = construir_centro_optimizacion(empresa_id, cuenta.id, FECHA_INICIO, FECHA_FIN)
        assert error is None
        assert paquete["nivel"] == "cuenta"
        assert len(paquete["comparacion"]) == 2
        assert paquete["diagnostico_cuenta"] is not None  # solo a nivel cuenta


def test_construir_centro_optimizacion_nivel_campana_compara_conjuntos(client, usuario_a_con_empresa):
    from app.services.meta.optimizacion import construir_centro_optimizacion

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        cj1 = _crear_conjunto(empresa_id, "cj1", campana.id)
        cj2 = _crear_conjunto(empresa_id, "cj2", campana.id)
        _registrar(empresa_id, cj1.id, "conjunto_anuncios", "spend", 200.0, FECHA_INICIO)
        _registrar(empresa_id, cj2.id, "conjunto_anuncios", "spend", 300.0, FECHA_INICIO)

        paquete, error = construir_centro_optimizacion(empresa_id, cuenta.id, FECHA_INICIO, FECHA_FIN, campana_id=campana.id)
        assert error is None
        assert paquete["nivel"] == "campana"
        assert len(paquete["comparacion"]) == 2
        assert paquete["diagnostico_cuenta"] is None  # no aplica a este nivel


def test_construir_centro_optimizacion_nivel_conjunto_compara_anuncios(client, usuario_a_con_empresa):
    from app.services.meta.optimizacion import construir_centro_optimizacion

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        conjunto = _crear_conjunto(empresa_id, "cj1", campana.id)
        a1 = _crear_anuncio(empresa_id, "a1", conjunto.id)
        a2 = _crear_anuncio(empresa_id, "a2", conjunto.id)
        _registrar(empresa_id, a1.id, "anuncio", "spend", 100.0, FECHA_INICIO)
        _registrar(empresa_id, a2.id, "anuncio", "spend", 150.0, FECHA_INICIO)

        paquete, error = construir_centro_optimizacion(empresa_id, cuenta.id, FECHA_INICIO, FECHA_FIN, conjunto_id=conjunto.id)
        assert error is None
        assert paquete["nivel"] == "conjunto"
        assert len(paquete["comparacion"]) == 2


def test_construir_centro_optimizacion_veredicto_temporal_mejora_y_deterioro(client, usuario_a_con_empresa):
    from app.services.meta.optimizacion import construir_centro_optimizacion

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        mejora = _crear_campana(empresa_id, "mejora", cuenta.id, nombre="Mejoró")
        deterioro = _crear_campana(empresa_id, "deterioro", cuenta.id, nombre="Empeoró")

        _registrar(empresa_id, mejora.id, "campana", "spend", 500.0, FECHA_INICIO)
        _registrar(empresa_id, mejora.id, "campana", "conversiones", 10.0, FECHA_INICIO)
        _registrar(empresa_id, mejora.id, "campana", "spend", 1000.0, FECHA_INICIO_ANTERIOR)
        _registrar(empresa_id, mejora.id, "campana", "conversiones", 10.0, FECHA_INICIO_ANTERIOR)

        _registrar(empresa_id, deterioro.id, "campana", "spend", 1000.0, FECHA_INICIO)
        _registrar(empresa_id, deterioro.id, "campana", "conversiones", 10.0, FECHA_INICIO)
        _registrar(empresa_id, deterioro.id, "campana", "spend", 500.0, FECHA_INICIO_ANTERIOR)
        _registrar(empresa_id, deterioro.id, "campana", "conversiones", 10.0, FECHA_INICIO_ANTERIOR)

        paquete, error = construir_centro_optimizacion(empresa_id, cuenta.id, FECHA_INICIO, FECHA_FIN)
        assert error is None
        veredictos = {f["entidad"].id: f["veredicto_temporal"] for f in paquete["comparacion"]}
        assert veredictos[mejora.id] == "mejora_significativa"
        assert veredictos[deterioro.id] == "deterioro"


# --- Recomendaciones priorizadas y orden ---------------------------------------------------

def test_recomendaciones_incluyen_oportunidades_y_estan_ordenadas_por_prioridad(client, usuario_a_con_empresa):
    from app.services.meta.optimizacion import construir_centro_optimizacion, NIVELES_PRIORIDAD

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        c1 = _crear_campana(empresa_id, "c1", cuenta.id)
        c2 = _crear_campana(empresa_id, "c2", cuenta.id)
        # c1 gasta mucho sin resultados -- oportunidad tipo gasto_alto_sin_resultados
        _registrar(empresa_id, c1.id, "campana", "spend", 5000.0, FECHA_INICIO)
        _registrar(empresa_id, c2.id, "campana", "spend", 100.0, FECHA_INICIO)
        _registrar(empresa_id, c2.id, "campana", "conversiones", 5.0, FECHA_INICIO)

        paquete, error = construir_centro_optimizacion(empresa_id, cuenta.id, FECHA_INICIO, FECHA_FIN)
        assert error is None
        assert len(paquete["recomendaciones"]) > 0

        ordenes = [NIVELES_PRIORIDAD.index(r["prioridad"]) for r in paquete["recomendaciones"]]
        assert ordenes == sorted(ordenes)  # nunca una prioridad baja antes que una alta


# --- Aislamiento multiempresa (punto 12) ---------------------------------------------------

def test_construir_centro_optimizacion_cuenta_de_otra_empresa_rechazada(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.meta.optimizacion import construir_centro_optimizacion

    with client.application.app_context():
        cuenta_b = _crear_cuenta(usuario_b_con_empresa["empresa_id"])
        paquete, error = construir_centro_optimizacion(usuario_a_con_empresa["empresa_id"], cuenta_b.id, FECHA_INICIO, FECHA_FIN)
        assert paquete is None
        assert "empresa" in error.lower()


def test_construir_centro_optimizacion_campana_de_otra_empresa_rechazada(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.meta.optimizacion import construir_centro_optimizacion

    with client.application.app_context():
        cuenta_a = _crear_cuenta(usuario_a_con_empresa["empresa_id"])
        cuenta_b = _crear_cuenta(usuario_b_con_empresa["empresa_id"], id_externo="act_b")
        campana_b = _crear_campana(usuario_b_con_empresa["empresa_id"], "cb", cuenta_b.id)

        paquete, error = construir_centro_optimizacion(usuario_a_con_empresa["empresa_id"], cuenta_a.id, FECHA_INICIO, FECHA_FIN, campana_id=campana_b.id)
        assert paquete is None
        assert "empresa" in error.lower()


def test_ruta_optimizacion_aislada_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id, nombre="Campaña secreta de A")
        _registrar(empresa_id, campana.id, "campana", "spend", 100.0, FECHA_INICIO)
        cuenta_a_id = cuenta.id

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp = client.get(f"/datos-meta/optimizacion?cuenta_id={cuenta_a_id}")
    assert resp.status_code == 200
    assert "Campaña secreta de A" not in resp.get_data(as_text=True)


# --- Rutas ------------------------------------------------------------------------------

def test_ruta_optimizacion_sin_cuenta_muestra_estado_vacio(client, usuario_a_con_empresa):
    resp = client.get("/datos-meta/optimizacion")
    assert resp.status_code == 200
    assert "Selecciona una cuenta" in resp.get_data(as_text=True)


def test_ruta_optimizacion_con_cuenta_devuelve_200(client, usuario_a_con_empresa):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        _registrar(empresa_id, campana.id, "campana", "spend", 100.0, FECHA_INICIO)
        cuenta_id = cuenta.id

    resp = client.get(f"/datos-meta/optimizacion?cuenta_id={cuenta_id}&periodo=personalizado&fecha_inicio={FECHA_INICIO.isoformat()}&fecha_fin={FECHA_FIN.isoformat()}")
    assert resp.status_code == 200


def test_ruta_optimizacion_datos_json(client, usuario_a_con_empresa):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        cuenta_id = cuenta.id

    resp = client.get(f"/datos-meta/optimizacion/datos?cuenta_id={cuenta_id}&periodo=ultimos_30_dias")
    assert resp.status_code == 200
    datos = resp.get_json()
    assert datos["ok"] is True
    assert datos["nivel"] == "cuenta"


def test_ruta_optimizacion_conjuntos_aislada_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    with client.application.app_context():
        cuenta_a = _crear_cuenta(usuario_a_con_empresa["empresa_id"])
        campana_a = _crear_campana(usuario_a_con_empresa["empresa_id"], "c1", cuenta_a.id)
        _crear_conjunto(usuario_a_con_empresa["empresa_id"], "cj1", campana_a.id, nombre="Conjunto secreto de A")
        campana_a_id = campana_a.id

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp = client.get(f"/datos-meta/optimizacion/conjuntos?campana_id={campana_a_id}")
    assert resp.status_code == 200
    assert resp.get_json()["conjuntos"] == []


# --- Integracion con Claude (punto 10) ----------------------------------------------------

def test_construir_prioridades_para_claude_devuelve_lineas_priorizadas(client, usuario_a_con_empresa):
    from app.services.meta.optimizacion import construir_prioridades_para_claude

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        c1 = _crear_campana(empresa_id, "c1", cuenta.id, nombre="Campaña sin resultados")
        _registrar(empresa_id, c1.id, "campana", "spend", 5000.0, FECHA_INICIO)
        c2 = _crear_campana(empresa_id, "c2", cuenta.id)
        _registrar(empresa_id, c2.id, "campana", "spend", 100.0, FECHA_INICIO)
        _registrar(empresa_id, c2.id, "campana", "conversiones", 5.0, FECHA_INICIO)

        lineas, error = construir_prioridades_para_claude(empresa_id, cuenta.id, FECHA_INICIO, FECHA_FIN)
        assert error is None
        assert isinstance(lineas, list)
        assert len(lineas) > 0
        assert any("Campaña sin resultados" in linea for linea in lineas)


def test_estratega_ia_incluye_prioridades_de_optimizacion_en_el_contexto(client, usuario_a_con_empresa):
    """El Estratega IA (Paso 10) debe poder usar este motor -- se
    verifica que construir_contexto() (sin proyecto) trae las
    prioridades de optimizacion ya calculadas, listas para el prompt."""
    from app.models import Empresa
    from app.extensions import db
    from app.services.estratega_ia import construir_contexto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        empresa = db.session.query(Empresa).filter_by(id=empresa_id).first()
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id, nombre="Campaña a revisar")
        _registrar(empresa_id, campana.id, "campana", "spend", 5000.0, FECHA_INICIO)

        informe, resumen, error = construir_contexto(empresa, cuenta.id, "ultimos_30_dias")
        assert error is None
        assert "prioridades_optimizacion" in informe
        assert isinstance(informe["prioridades_optimizacion"], list)
