"""Pruebas del Paso 8: motor de inteligencia estrategica.

Cubre exclusivamente lo nuevo de este paso -- diagnostico por area
(BUENO/ATENCION/CRITICO/SIN_DATOS), deteccion de cambios temporales por
campaña, analisis de creativos (señal de video real, nunca inventada),
presupuesto relacionado con rendimiento, enriquecimiento de
oportunidades estrategicas, alertas y niveles de confianza, ademas del
aislamiento multiempresa. El motor de KPI y el motor de oportunidades
por grupo YA estan probados en test_datos_meta_paso3.py y
test_datos_meta_paso5.py -- aqui nunca se reimplementa ese calculo,
solo se prueba lo que este paso agrega."""

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
        atributos={"objetivo": "OUTCOME_SALES"},
    )
    db.session.add(campana)
    db.session.commit()
    return campana


def _crear_conjunto(empresa_id, id_externo, campana_id):
    from app.extensions import db

    conjunto = EntidadPublicitaria(
        empresa_id=empresa_id, fuente="meta", tipo="conjunto_anuncios", id_externo=id_externo,
        nombre=f"Conjunto {id_externo}", entidad_padre_id=campana_id, estado="ACTIVE",
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
# periodo_anterior_equivalente(FECHA_INICIO, FECHA_FIN) -- 10 dias, ver periodos.py
FECHA_INICIO_ANTERIOR = datetime.date(2026, 7, 22)
FECHA_FIN_ANTERIOR = datetime.date(2026, 7, 31)


# --- Confianza (punto 9) ---------------------------------------------------------------

def test_calcular_confianza_baja_sin_dias_suficientes():
    from app.services.meta.inteligencia import calcular_confianza

    assert calcular_confianza(0) == "baja"
    assert calcular_confianza(None) == "baja"
    assert calcular_confianza(1) == "baja"


def test_calcular_confianza_media_con_dias_moderados():
    from app.services.meta.inteligencia import calcular_confianza

    assert calcular_confianza(7) == "media"


def test_calcular_confianza_alta_requiere_dias_y_entidades():
    from app.services.meta.inteligencia import calcular_confianza

    assert calcular_confianza(20, cantidad_entidades=2) == "alta"
    # Muchos dias pero una sola entidad -- no es suficiente para "alta".
    assert calcular_confianza(20, cantidad_entidades=1) == "media"


# --- Clasificacion de variacion (punto 1) -----------------------------------------------

def test_clasificar_variacion_sin_datos_cuando_no_hay_periodo_anterior():
    from app.services.meta.inteligencia import clasificar_variacion

    assert clasificar_variacion("ctr", None) == "sin_datos"


def test_clasificar_variacion_ctr_cae_es_deterioro_no_mejora():
    """CTR (mayor es mejor): una CAIDA (variacion negativa) es el
    deterioro -- la clasificacion se degrada con una baja de CTR."""
    from app.services.meta.inteligencia import clasificar_variacion

    assert clasificar_variacion("ctr", -5) == "bueno"       # caida leve
    assert clasificar_variacion("ctr", -20) == "atencion"    # caida moderada
    assert clasificar_variacion("ctr", -50) == "critico"     # caida fuerte
    assert clasificar_variacion("ctr", 50) == "bueno"        # subida de CTR nunca es deterioro


def test_clasificar_variacion_costo_por_resultado_sube_es_deterioro():
    """costo_por_resultado (menor es mejor): un AUMENTO (variacion
    positiva) es el deterioro -- lo opuesto a CTR."""
    from app.services.meta.inteligencia import clasificar_variacion

    assert clasificar_variacion("costo_por_resultado", 5) == "bueno"
    assert clasificar_variacion("costo_por_resultado", 20) == "atencion"
    assert clasificar_variacion("costo_por_resultado", 50) == "critico"
    assert clasificar_variacion("costo_por_resultado", -50) == "bueno"  # bajar el costo nunca es deterioro


# --- Diagnostico de cuenta (punto 1) -----------------------------------------------------

def test_diagnostico_clasifica_deterioro_real_de_costo_por_resultado(client, usuario_a_con_empresa):
    from app.services.meta.inteligencia import construir_diagnostico_cuenta

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)

        # Periodo actual: costo por resultado = 1000/10 = 100
        _registrar(empresa_id, campana.id, "campana", "spend", 1000.0, FECHA_INICIO)
        _registrar(empresa_id, campana.id, "campana", "conversiones", 10.0, FECHA_INICIO)
        # Periodo anterior: costo por resultado = 500/10 = 50 -- el costo SUBIO 100%
        _registrar(empresa_id, campana.id, "campana", "spend", 500.0, FECHA_INICIO_ANTERIOR)
        _registrar(empresa_id, campana.id, "campana", "conversiones", 10.0, FECHA_INICIO_ANTERIOR)

        diagnostico, error = construir_diagnostico_cuenta(empresa_id, cuenta.id, FECHA_INICIO, FECHA_FIN)
        assert error is None
        area = diagnostico["areas"]["costo_por_resultado"]
        assert area["valor"] == 100.0
        assert area["variacion_pct"] == 100.0
        assert area["clasificacion"] == "critico"
        assert diagnostico["dias_con_datos"] == 1


def test_diagnostico_sin_periodo_anterior_es_sin_datos(client, usuario_a_con_empresa):
    from app.services.meta.inteligencia import construir_diagnostico_cuenta

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        _registrar(empresa_id, campana.id, "campana", "spend", 1000.0, FECHA_INICIO)
        _registrar(empresa_id, campana.id, "campana", "conversiones", 10.0, FECHA_INICIO)

        diagnostico, error = construir_diagnostico_cuenta(empresa_id, cuenta.id, FECHA_INICIO, FECHA_FIN)
        assert error is None
        assert diagnostico["areas"]["costo_por_resultado"]["clasificacion"] == "sin_datos"
        assert diagnostico["areas"]["reach"]["clasificacion"] == "sin_datos"  # sin ningun dato


def test_diagnostico_cuenta_de_otra_empresa_rechazado(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.meta.inteligencia import construir_diagnostico_cuenta

    with client.application.app_context():
        cuenta_b = _crear_cuenta(usuario_b_con_empresa["empresa_id"])
        diagnostico, error = construir_diagnostico_cuenta(usuario_a_con_empresa["empresa_id"], cuenta_b.id, FECHA_INICIO, FECHA_FIN)
        assert diagnostico is None
        assert "empresa" in error.lower()


# --- Cambios temporales por campaña (punto 2) --------------------------------------------

def test_detectar_cambios_temporales_detecta_mejora_y_deterioro(client, usuario_a_con_empresa):
    from app.services.meta.inteligencia import detectar_cambios_temporales

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        mejora = _crear_campana(empresa_id, "mejora", cuenta.id, nombre="Campaña que mejoró")
        deterioro = _crear_campana(empresa_id, "deterioro", cuenta.id, nombre="Campaña que empeoró")

        # "mejora": costo bajo de 100 a 50 (mejor)
        _registrar(empresa_id, mejora.id, "campana", "spend", 500.0, FECHA_INICIO)
        _registrar(empresa_id, mejora.id, "campana", "conversiones", 10.0, FECHA_INICIO)
        _registrar(empresa_id, mejora.id, "campana", "spend", 1000.0, FECHA_INICIO_ANTERIOR)
        _registrar(empresa_id, mejora.id, "campana", "conversiones", 10.0, FECHA_INICIO_ANTERIOR)

        # "deterioro": costo subio de 50 a 100 (peor)
        _registrar(empresa_id, deterioro.id, "campana", "spend", 1000.0, FECHA_INICIO)
        _registrar(empresa_id, deterioro.id, "campana", "conversiones", 10.0, FECHA_INICIO)
        _registrar(empresa_id, deterioro.id, "campana", "spend", 500.0, FECHA_INICIO_ANTERIOR)
        _registrar(empresa_id, deterioro.id, "campana", "conversiones", 10.0, FECHA_INICIO_ANTERIOR)

        cambios = detectar_cambios_temporales(empresa_id, [mejora, deterioro], FECHA_INICIO, FECHA_FIN)
        tipos_por_entidad = {c["entidad_id"]: c["tipo"] for c in cambios}
        assert tipos_por_entidad[mejora.id] == "mejora_significativa"
        assert tipos_por_entidad[deterioro.id] == "deterioro"


# --- Analisis de campañas (punto 2) -------------------------------------------------------

def test_construir_analisis_campanas_incluye_oportunidades_y_cambios(client, usuario_a_con_empresa):
    from app.services.meta.inteligencia import construir_analisis_campanas

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        c1 = _crear_campana(empresa_id, "c1", cuenta.id)
        c2 = _crear_campana(empresa_id, "c2", cuenta.id)

        # c1 gasta mucho sin ninguna conversion -- debe detectarse como oportunidad.
        _registrar(empresa_id, c1.id, "campana", "spend", 5000.0, FECHA_INICIO)
        _registrar(empresa_id, c2.id, "campana", "spend", 100.0, FECHA_INICIO)
        _registrar(empresa_id, c2.id, "campana", "conversiones", 5.0, FECHA_INICIO)

        analisis, error = construir_analisis_campanas(empresa_id, cuenta.id, FECHA_INICIO, FECHA_FIN)
        assert error is None
        assert len(analisis["campanas"]) == 2
        tipos = {o["tipo"] for o in analisis["oportunidades"]}
        assert "gasto_alto_sin_resultados" in tipos
        assert isinstance(analisis["cambios_temporales"], list)


def test_construir_analisis_campanas_sin_cuenta_devuelve_vacio(client, usuario_a_con_empresa):
    from app.services.meta.inteligencia import construir_analisis_campanas

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        analisis, error = construir_analisis_campanas(empresa_id, None, FECHA_INICIO, FECHA_FIN)
        assert error is None
        assert analisis["campanas"] == []


# --- Analisis de creativos (punto 4) ------------------------------------------------------

def test_analisis_creativos_usa_video_plays_como_senal_real(client, usuario_a_con_empresa):
    """El 'patron de video' debe basarse EXCLUSIVAMENTE en video_plays
    (metrica real ya sincronizada), nunca en un campo de tipo de
    creativo inventado -- campanas_service.py no sincroniza ese campo."""
    from app.services.meta.inteligencia import construir_analisis_creativos

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        conjunto = _crear_conjunto(empresa_id, "cj1", campana.id)
        anuncio_video = _crear_anuncio(empresa_id, "a1", conjunto.id, nombre="Anuncio de video")
        anuncio_imagen = _crear_anuncio(empresa_id, "a2", conjunto.id, nombre="Anuncio de imagen")

        _registrar(empresa_id, anuncio_video.id, "anuncio", "clicks", 50.0, FECHA_INICIO)
        _registrar(empresa_id, anuncio_video.id, "anuncio", "impressions", 1000.0, FECHA_INICIO)
        _registrar(empresa_id, anuncio_video.id, "anuncio", "video_plays", 20.0, FECHA_INICIO)

        _registrar(empresa_id, anuncio_imagen.id, "anuncio", "clicks", 10.0, FECHA_INICIO)
        _registrar(empresa_id, anuncio_imagen.id, "anuncio", "impressions", 1000.0, FECHA_INICIO)

        analisis, error = construir_analisis_creativos(empresa_id, cuenta.id, FECHA_INICIO, FECHA_FIN)
        assert error is None
        assert len(analisis["anuncios"]) == 2
        assert analisis["patron_video"] is not None
        assert analisis["patron_video"]["promedio_ctr_con_video"] == 5.0
        assert analisis["patron_video"]["promedio_ctr_sin_video"] == 1.0
        assert "superior" in analisis["patron_video"]["mensaje"]


def test_analisis_creativos_sin_anuncios_no_genera_patron(client, usuario_a_con_empresa):
    from app.services.meta.inteligencia import construir_analisis_creativos

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        analisis, error = construir_analisis_creativos(empresa_id, cuenta.id, FECHA_INICIO, FECHA_FIN)
        assert error is None
        assert analisis["anuncios"] == []
        assert analisis["patron_video"] is None


# --- Presupuesto (punto 5) ------------------------------------------------------------------

def test_analisis_presupuesto_relaciona_gasto_real_sin_modificarlo(client, usuario_a_con_empresa):
    from app.services.meta.inteligencia import construir_analisis_presupuesto
    from app.services.presupuestos import crear_presupuesto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        _registrar(empresa_id, campana.id, "campana", "spend", 850.0, FECHA_INICIO)

        presupuesto, _ = crear_presupuesto(
            empresa_id, usuario_a_con_empresa["usuario_id"], "Estratégico agosto", "estrategico", 1000,
            fecha_inicio=FECHA_INICIO, fecha_fin=FECHA_FIN,
        )
        monto_original = presupuesto.monto

        analisis, error = construir_analisis_presupuesto(empresa_id, cuenta.id, FECHA_INICIO, FECHA_FIN)
        assert error is None
        assert len(analisis["presupuestos"]) == 1
        assert analisis["presupuestos"][0]["gasto_real"] == 850.0
        assert analisis["presupuestos"][0]["porcentaje_usado"] == 85.0
        assert presupuesto.monto == monto_original  # nunca se modifica


def test_analisis_presupuesto_detecta_concentracion_de_gasto(client, usuario_a_con_empresa):
    from app.services.meta.inteligencia import construir_analisis_presupuesto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        c1 = _crear_campana(empresa_id, "c1", cuenta.id)
        c2 = _crear_campana(empresa_id, "c2", cuenta.id)
        _registrar(empresa_id, c1.id, "campana", "spend", 9000.0, FECHA_INICIO)
        _registrar(empresa_id, c2.id, "campana", "spend", 1000.0, FECHA_INICIO)

        analisis, error = construir_analisis_presupuesto(empresa_id, cuenta.id, FECHA_INICIO, FECHA_FIN)
        assert error is None
        assert len(analisis["concentracion"]) == 1
        assert analisis["concentracion"][0]["porcentaje_del_gasto_total"] == 90.0


# --- Oportunidades estrategicas (punto 6) ---------------------------------------------------

def test_oportunidades_estrategicas_tienen_formato_completo(client, usuario_a_con_empresa):
    from app.services.meta.inteligencia import construir_analisis_campanas, construir_oportunidades_estrategicas

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        c1 = _crear_campana(empresa_id, "c1", cuenta.id)
        c2 = _crear_campana(empresa_id, "c2", cuenta.id)
        _registrar(empresa_id, c1.id, "campana", "spend", 5000.0, FECHA_INICIO)
        _registrar(empresa_id, c2.id, "campana", "spend", 100.0, FECHA_INICIO)
        _registrar(empresa_id, c2.id, "campana", "conversiones", 5.0, FECHA_INICIO)

        analisis_campanas, _ = construir_analisis_campanas(empresa_id, cuenta.id, FECHA_INICIO, FECHA_FIN)
        oportunidades = construir_oportunidades_estrategicas(analisis_campanas, None, dias_con_datos=1)

        assert oportunidades
        for op in oportunidades:
            assert set(["titulo", "descripcion", "evidencia", "kpi_relacionado", "nivel_confianza", "impacto_potencial", "datos_utilizados"]).issubset(op.keys())
            assert op["nivel_confianza"] in ("alta", "media", "baja")
            assert op["evidencia"]  # nunca vacio -- siempre hay un dato que respalda


# --- Alertas (punto 7) -------------------------------------------------------------------------

def test_alertas_detecta_deterioro_de_kpi(client, usuario_a_con_empresa):
    from app.services.meta.inteligencia import construir_alertas, construir_diagnostico_cuenta

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        _registrar(empresa_id, campana.id, "campana", "spend", 1000.0, FECHA_INICIO)
        _registrar(empresa_id, campana.id, "campana", "conversiones", 10.0, FECHA_INICIO)
        _registrar(empresa_id, campana.id, "campana", "spend", 500.0, FECHA_INICIO_ANTERIOR)
        _registrar(empresa_id, campana.id, "campana", "conversiones", 10.0, FECHA_INICIO_ANTERIOR)

        diagnostico, _ = construir_diagnostico_cuenta(empresa_id, cuenta.id, FECHA_INICIO, FECHA_FIN)
        alertas = construir_alertas(diagnostico, {"oportunidades": [], "cambios_temporales": []}, {"presupuestos": []})

        tipos = {a["tipo"] for a in alertas}
        assert "deterioro_costo_por_resultado" in tipos


def test_alertas_detecta_presupuesto_agotandose(client, usuario_a_con_empresa):
    from app.services.meta.inteligencia import construir_alertas, construir_diagnostico_cuenta
    from app.services.presupuestos import calcular_resumen_presupuesto, crear_presupuesto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        _registrar(empresa_id, campana.id, "campana", "spend", 950.0, FECHA_INICIO)

        presupuesto, _ = crear_presupuesto(
            empresa_id, usuario_a_con_empresa["usuario_id"], "Estratégico", "estrategico", 1000,
            fecha_inicio=FECHA_INICIO, fecha_fin=FECHA_FIN,
        )
        resumen = calcular_resumen_presupuesto(presupuesto)

        diagnostico, _ = construir_diagnostico_cuenta(empresa_id, cuenta.id, FECHA_INICIO, FECHA_FIN)
        alertas = construir_alertas(diagnostico, {"oportunidades": [], "cambios_temporales": []}, {"presupuestos": [resumen]})

        tipos = {a["tipo"] for a in alertas}
        assert "presupuesto_agotandose" in tipos


def test_alertas_sin_problemas_devuelve_lista_vacia(client, usuario_a_con_empresa):
    from app.services.meta.inteligencia import construir_alertas, construir_diagnostico_cuenta

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        diagnostico, _ = construir_diagnostico_cuenta(empresa_id, cuenta.id, FECHA_INICIO, FECHA_FIN)
        alertas = construir_alertas(diagnostico, {"oportunidades": [], "cambios_temporales": []}, {"presupuestos": []})
        assert alertas == []


# --- Informe estructurado para futuro Claude (punto 8) ---------------------------------------

def test_informe_estructurado_incluye_todas_las_secciones(client, usuario_a_con_empresa):
    from app.extensions import db
    from app.models import Empresa
    from app.services.meta.inteligencia import construir_informe_estructurado

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        _registrar(empresa_id, campana.id, "campana", "spend", 100.0, FECHA_INICIO)

        empresa = db.session.query(Empresa).filter_by(id=empresa_id).first()

        informe, error = construir_informe_estructurado(empresa, cuenta.id, FECHA_INICIO, FECHA_FIN, objetivo="conversiones", presupuesto_total=100000)
        assert error is None
        for clave in ("empresa", "objetivo", "presupuesto_total", "periodo", "diagnostico", "campanas", "audiencias", "creativos", "kpi", "oportunidades", "alertas", "historico"):
            assert clave in informe
        assert informe["empresa"]["id"] == empresa_id


# --- Multiempresa: aislamiento total -----------------------------------------------------------

def test_construir_inteligencia_aislado_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.meta.inteligencia import construir_inteligencia

    with client.application.app_context():
        cuenta_b = _crear_cuenta(usuario_b_con_empresa["empresa_id"])
        paquete, error = construir_inteligencia(usuario_a_con_empresa["empresa_id"], cuenta_b.id, FECHA_INICIO, FECHA_FIN)
        assert paquete is None
        assert "empresa" in error.lower()


def test_ruta_inteligencia_aislada_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id, nombre="Campaña secreta de A")
        _registrar(empresa_id, campana.id, "campana", "spend", 100.0, FECHA_INICIO)

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp = client.get("/datos-meta/inteligencia")
    assert resp.status_code == 200
    assert "Campaña secreta de A" not in resp.get_data(as_text=True)


def test_ruta_inteligencia_devuelve_200_y_json(client, usuario_a_con_empresa):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        _registrar(empresa_id, campana.id, "campana", "spend", 100.0, FECHA_INICIO)
        _registrar(empresa_id, campana.id, "campana", "conversiones", 2.0, FECHA_INICIO)
        cuenta_id = cuenta.id

    resp = client.get(f"/datos-meta/inteligencia?cuenta_id={cuenta_id}&periodo=personalizado&fecha_inicio={FECHA_INICIO.isoformat()}&fecha_fin={FECHA_FIN.isoformat()}")
    assert resp.status_code == 200

    resp_json = client.get(f"/datos-meta/inteligencia/datos?cuenta_id={cuenta_id}&periodo=personalizado&fecha_inicio={FECHA_INICIO.isoformat()}&fecha_fin={FECHA_FIN.isoformat()}")
    assert resp_json.status_code == 200
    datos = resp_json.get_json()
    assert datos["ok"] is True
    assert "diagnostico" in datos
    assert "oportunidades" in datos
    assert "alertas" in datos
