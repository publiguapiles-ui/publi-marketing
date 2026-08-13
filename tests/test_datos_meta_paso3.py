"""Pruebas del Paso 3 de Datos de Meta: motor de KPI (agregacion
correcta -- nunca promedio de ratios, nunca doble conteo entre
niveles), comparacion de periodos con variacion porcentual,
comparacion entre entidades con deteccion de mejor/peor, valores NULL
cuando Meta no entrego una metrica, aislamiento multiempresa, y la
extraccion de los campos nuevos de Meta Insights (actions/
action_values/video_play_actions/purchase_roas) hacia el motor
universal.
"""

import datetime

from app.models import EntidadPublicitaria
from tests.conftest import iniciar_sesion_de_prueba


def _mockear_get_meta(monkeypatch, mapa_respuestas):
    import app.services.meta.client as client_mod

    def _resolver(ruta):
        for prefijo, respuesta in mapa_respuestas.items():
            if ruta == prefijo or ruta.startswith(prefijo):
                if isinstance(respuesta, Exception):
                    raise respuesta
                return respuesta
        raise AssertionError(f"ruta inesperada en el mock: {ruta}")

    monkeypatch.setattr(client_mod.MetaClient, "get", lambda self, ruta, params=None, access_token=None: _resolver(ruta))
    monkeypatch.setattr(client_mod.MetaClient, "get_todas_las_paginas", lambda self, ruta, params=None, limite_paginas=20: _resolver(ruta).get("data", []))


def _preparar_cuenta_vinculada(empresa_id, usuario_id):
    from app.services.meta.conexiones import crear_conexion
    from app.services.meta.cuentas_service import vincular_activos

    crear_conexion(empresa_id, usuario_id, "111", "A", "token-a")
    vincular_activos(empresa_id, [
        {"tipo": "cuenta_publicitaria", "id_externo": "act_123", "nombre": "Cuenta", "atributos": {"moneda": "USD"}},
    ])


def _crear_campana(empresa_id, conexion_id, id_externo, nombre="Campaña", entidad_padre_id=None):
    from app.extensions import db

    campana = EntidadPublicitaria(
        empresa_id=empresa_id, conexion_id=conexion_id, fuente="meta", tipo="campana",
        id_externo=id_externo, nombre=nombre, entidad_padre_id=entidad_padre_id,
    )
    db.session.add(campana)
    db.session.commit()
    return campana


# --- Calculo de KPI: agregacion aditiva + formulas derivadas ---------------------

def test_calcular_kpis_suma_metricas_aditivas_de_una_entidad(client, usuario_a_con_empresa):
    from app.services.meta.kpi import calcular_kpis
    from app.services.metricas import registrar_metrica

    with client.application.app_context():
        campana = _crear_campana(usuario_a_con_empresa["empresa_id"], None, "c1")
        registrar_metrica(usuario_a_con_empresa["empresa_id"], "spend", 10.0, datetime.date(2026, 8, 1), entidad_id=campana.id, entidad_tipo="campana")
        registrar_metrica(usuario_a_con_empresa["empresa_id"], "spend", 15.0, datetime.date(2026, 8, 2), entidad_id=campana.id, entidad_tipo="campana")
        registrar_metrica(usuario_a_con_empresa["empresa_id"], "impressions", 1000.0, datetime.date(2026, 8, 1), entidad_id=campana.id, entidad_tipo="campana")
        registrar_metrica(usuario_a_con_empresa["empresa_id"], "impressions", 2000.0, datetime.date(2026, 8, 2), entidad_id=campana.id, entidad_tipo="campana")

        kpis = calcular_kpis(usuario_a_con_empresa["empresa_id"], [campana.id], datetime.date(2026, 8, 1), datetime.date(2026, 8, 2))
        assert kpis["spend"] == 25.0
        assert kpis["impressions"] == 3000


def test_calcular_kpis_no_promedia_ratios_calcula_desde_totales(client, usuario_a_con_empresa):
    """Dia 1: 100 clics / 1000 impresiones (CTR 10%). Dia 2: 10 clics /
    1000 impresiones (CTR 1%). El promedio simple de esos dos CTR
    seria 5.5% -- el CTR correcto agregado es 110/2000*100 = 5.5%...
    se usan numeros distintos a proposito para que un promedio simple
    de porcentajes de un resultado DIFERENTE al correcto y la prueba
    solo pase si se calcula desde los totales."""
    from app.services.meta.kpi import calcular_kpis
    from app.services.metricas import registrar_metrica

    with client.application.app_context():
        campana = _crear_campana(usuario_a_con_empresa["empresa_id"], None, "c1")
        registrar_metrica(usuario_a_con_empresa["empresa_id"], "clicks", 100.0, datetime.date(2026, 8, 1), entidad_id=campana.id, entidad_tipo="campana")
        registrar_metrica(usuario_a_con_empresa["empresa_id"], "impressions", 500.0, datetime.date(2026, 8, 1), entidad_id=campana.id, entidad_tipo="campana")
        registrar_metrica(usuario_a_con_empresa["empresa_id"], "clicks", 10.0, datetime.date(2026, 8, 2), entidad_id=campana.id, entidad_tipo="campana")
        registrar_metrica(usuario_a_con_empresa["empresa_id"], "impressions", 1500.0, datetime.date(2026, 8, 2), entidad_id=campana.id, entidad_tipo="campana")

        kpis = calcular_kpis(usuario_a_con_empresa["empresa_id"], [campana.id], datetime.date(2026, 8, 1), datetime.date(2026, 8, 2))
        # promedio simple de (20% + 0.67%) / 2 = 10.3% -- el correcto es 110/2000*100 = 5.5%
        assert kpis["ctr"] == 5.5


def test_calcular_kpis_metrica_no_disponible_devuelve_none(client, usuario_a_con_empresa):
    from app.services.meta.kpi import calcular_kpis
    from app.services.metricas import registrar_metrica

    with client.application.app_context():
        campana = _crear_campana(usuario_a_con_empresa["empresa_id"], None, "c1")
        registrar_metrica(usuario_a_con_empresa["empresa_id"], "spend", 10.0, datetime.date(2026, 8, 1), entidad_id=campana.id, entidad_tipo="campana")

        kpis = calcular_kpis(usuario_a_con_empresa["empresa_id"], [campana.id], datetime.date(2026, 8, 1), datetime.date(2026, 8, 1))
        assert kpis["roas"] is None
        assert kpis["conversiones"] is None
        assert kpis["resultados"] is None
        assert kpis["video_plays"] is None


def test_calcular_kpis_empresa_nivel_evita_doble_conteo(client, usuario_a_con_empresa):
    """Si se agregaran TODOS los niveles (cuenta+campana+conjunto+
    anuncio) a la vez, el gasto quedaria multiplicado. El nivel
    "empresa" (entidad_ids=None) debe sumar SOLO el nivel campana."""
    from app.services.meta.kpi import calcular_kpis
    from app.services.metricas import registrar_metrica

    with client.application.app_context():
        campana = _crear_campana(usuario_a_con_empresa["empresa_id"], None, "c1")
        conjunto = EntidadPublicitaria(
            empresa_id=usuario_a_con_empresa["empresa_id"], fuente="meta", tipo="conjunto_anuncios",
            id_externo="as1", nombre="Conjunto", entidad_padre_id=campana.id,
        )
        from app.extensions import db

        db.session.add(conjunto)
        db.session.commit()

        registrar_metrica(usuario_a_con_empresa["empresa_id"], "spend", 100.0, datetime.date(2026, 8, 1), entidad_id=campana.id, entidad_tipo="campana")
        registrar_metrica(usuario_a_con_empresa["empresa_id"], "spend", 100.0, datetime.date(2026, 8, 1), entidad_id=conjunto.id, entidad_tipo="conjunto_anuncios")

        kpis = calcular_kpis(usuario_a_con_empresa["empresa_id"], None, datetime.date(2026, 8, 1), datetime.date(2026, 8, 1))
        assert kpis["spend"] == 100.0  # no 200.0


# --- resolver_entidades_para_kpi ---------------------------------------------------

def test_resolver_entidades_para_kpi_cuenta_publicitaria_devuelve_campanas_hijas(client, usuario_a_con_empresa):
    from app.extensions import db
    from app.services.meta.kpi import resolver_entidades_para_kpi

    with client.application.app_context():
        cuenta = EntidadPublicitaria(empresa_id=usuario_a_con_empresa["empresa_id"], fuente="meta", tipo="cuenta_publicitaria", id_externo="act_1", nombre="Cuenta")
        db.session.add(cuenta)
        db.session.commit()

        c1 = _crear_campana(usuario_a_con_empresa["empresa_id"], None, "c1", entidad_padre_id=cuenta.id)
        c2 = _crear_campana(usuario_a_con_empresa["empresa_id"], None, "c2", entidad_padre_id=cuenta.id)
        conjunto = EntidadPublicitaria(empresa_id=usuario_a_con_empresa["empresa_id"], fuente="meta", tipo="conjunto_anuncios", id_externo="as1", entidad_padre_id=c1.id)
        db.session.add(conjunto)
        db.session.commit()

        entidad_ids, error = resolver_entidades_para_kpi(usuario_a_con_empresa["empresa_id"], cuenta.id)
        assert error is None
        assert set(entidad_ids) == {c1.id, c2.id}


def test_resolver_entidades_para_kpi_entidad_ajena_falla(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.extensions import db
    from app.services.meta.kpi import resolver_entidades_para_kpi

    with client.application.app_context():
        cuenta_b = EntidadPublicitaria(empresa_id=usuario_b_con_empresa["empresa_id"], fuente="meta", tipo="cuenta_publicitaria", id_externo="act_b")
        db.session.add(cuenta_b)
        db.session.commit()

        entidad_ids, error = resolver_entidades_para_kpi(usuario_a_con_empresa["empresa_id"], cuenta_b.id)
        assert entidad_ids is None
        assert error is not None


def test_resolver_entidades_para_kpi_pagina_devuelve_lista_vacia(client, usuario_a_con_empresa):
    from app.extensions import db
    from app.services.meta.kpi import resolver_entidades_para_kpi

    with client.application.app_context():
        pagina = EntidadPublicitaria(empresa_id=usuario_a_con_empresa["empresa_id"], fuente="meta", tipo="pagina", id_externo="p1")
        db.session.add(pagina)
        db.session.commit()

        entidad_ids, error = resolver_entidades_para_kpi(usuario_a_con_empresa["empresa_id"], pagina.id)
        assert error is None
        assert entidad_ids == []


# --- Variacion porcentual y comparacion de periodos ---------------------------------

def test_calcular_variacion_porcentual_basico():
    from app.services.meta.kpi import calcular_variacion_porcentual

    assert calcular_variacion_porcentual(100, 150) == 50.0
    assert calcular_variacion_porcentual(100, 50) == -50.0
    assert calcular_variacion_porcentual(0, 50) is None
    assert calcular_variacion_porcentual(None, 50) is None
    assert calcular_variacion_porcentual(50, None) is None


def test_comparar_periodos_calcula_variacion_por_clave(client, usuario_a_con_empresa):
    from app.services.meta.kpi import comparar_periodos
    from app.services.metricas import registrar_metrica

    with client.application.app_context():
        campana = _crear_campana(usuario_a_con_empresa["empresa_id"], None, "c1")
        # periodo actual: 10-10 ago (1 dia)
        registrar_metrica(usuario_a_con_empresa["empresa_id"], "spend", 200.0, datetime.date(2026, 8, 10), entidad_id=campana.id, entidad_tipo="campana")
        # periodo anterior equivalente (mismo largo, 1 dia): 9 ago
        registrar_metrica(usuario_a_con_empresa["empresa_id"], "spend", 100.0, datetime.date(2026, 8, 9), entidad_id=campana.id, entidad_tipo="campana")

        resultado = comparar_periodos(usuario_a_con_empresa["empresa_id"], [campana.id], datetime.date(2026, 8, 10), datetime.date(2026, 8, 10))
        assert resultado["periodo_actual"]["kpis"]["spend"] == 200.0
        assert resultado["periodo_anterior"]["kpis"]["spend"] == 100.0
        assert resultado["periodo_anterior"]["fecha_inicio"] == datetime.date(2026, 8, 9)
        assert resultado["variacion_porcentual"]["spend"] == 100.0


# --- Comparacion entre entidades: mejor/peor -----------------------------------------

def test_comparar_entidades_detecta_mejor_y_peor_por_gasto(client, usuario_a_con_empresa):
    from app.services.meta.kpi import comparar_entidades
    from app.services.metricas import registrar_metrica

    with client.application.app_context():
        alta = _crear_campana(usuario_a_con_empresa["empresa_id"], None, "alta", nombre="Alta inversión")
        media = _crear_campana(usuario_a_con_empresa["empresa_id"], None, "media", nombre="Media inversión")
        baja = _crear_campana(usuario_a_con_empresa["empresa_id"], None, "baja", nombre="Baja inversión")
        registrar_metrica(usuario_a_con_empresa["empresa_id"], "spend", 300.0, datetime.date(2026, 8, 1), entidad_id=alta.id, entidad_tipo="campana")
        registrar_metrica(usuario_a_con_empresa["empresa_id"], "spend", 150.0, datetime.date(2026, 8, 1), entidad_id=media.id, entidad_tipo="campana")
        registrar_metrica(usuario_a_con_empresa["empresa_id"], "spend", 50.0, datetime.date(2026, 8, 1), entidad_id=baja.id, entidad_tipo="campana")

        resultado = comparar_entidades(
            usuario_a_con_empresa["empresa_id"], [alta.id, media.id, baja.id],
            datetime.date(2026, 8, 1), datetime.date(2026, 8, 1), metrica_orden="spend",
        )
        assert resultado[0]["entidad"].id == alta.id
        assert resultado[0]["es_mejor"] is True
        assert resultado[-1]["entidad"].id == baja.id
        assert resultado[-1]["es_peor"] is True
        assert resultado[1]["es_mejor"] is False
        assert resultado[1]["es_peor"] is False


def test_comparar_entidades_menor_es_mejor_para_cpc(client, usuario_a_con_empresa):
    from app.services.meta.kpi import comparar_entidades
    from app.services.metricas import registrar_metrica

    with client.application.app_context():
        barata = _crear_campana(usuario_a_con_empresa["empresa_id"], None, "barata", nombre="CPC bajo")
        cara = _crear_campana(usuario_a_con_empresa["empresa_id"], None, "cara", nombre="CPC alto")
        # barata: 10 gasto / 10 clics = cpc 1.0 ; cara: 10 gasto / 2 clics = cpc 5.0
        registrar_metrica(usuario_a_con_empresa["empresa_id"], "spend", 10.0, datetime.date(2026, 8, 1), entidad_id=barata.id, entidad_tipo="campana")
        registrar_metrica(usuario_a_con_empresa["empresa_id"], "clicks", 10.0, datetime.date(2026, 8, 1), entidad_id=barata.id, entidad_tipo="campana")
        registrar_metrica(usuario_a_con_empresa["empresa_id"], "spend", 10.0, datetime.date(2026, 8, 1), entidad_id=cara.id, entidad_tipo="campana")
        registrar_metrica(usuario_a_con_empresa["empresa_id"], "clicks", 2.0, datetime.date(2026, 8, 1), entidad_id=cara.id, entidad_tipo="campana")

        resultado = comparar_entidades(
            usuario_a_con_empresa["empresa_id"], [barata.id, cara.id],
            datetime.date(2026, 8, 1), datetime.date(2026, 8, 1), metrica_orden="cpc",
        )
        assert resultado[0]["entidad"].id == barata.id
        assert resultado[0]["es_mejor"] is True
        assert resultado[-1]["entidad"].id == cara.id
        assert resultado[-1]["es_peor"] is True


def test_comparar_entidades_sin_dato_queda_al_final_sin_marcar(client, usuario_a_con_empresa):
    from app.services.meta.kpi import comparar_entidades
    from app.services.metricas import registrar_metrica

    with client.application.app_context():
        con_gasto = _crear_campana(usuario_a_con_empresa["empresa_id"], None, "con_gasto")
        sin_gasto = _crear_campana(usuario_a_con_empresa["empresa_id"], None, "sin_gasto")
        registrar_metrica(usuario_a_con_empresa["empresa_id"], "spend", 50.0, datetime.date(2026, 8, 1), entidad_id=con_gasto.id, entidad_tipo="campana")

        resultado = comparar_entidades(
            usuario_a_con_empresa["empresa_id"], [con_gasto.id, sin_gasto.id],
            datetime.date(2026, 8, 1), datetime.date(2026, 8, 1), metrica_orden="spend",
        )
        assert resultado[-1]["entidad"].id == sin_gasto.id
        assert resultado[-1]["es_mejor"] is False
        assert resultado[-1]["es_peor"] is False


# --- Aislamiento multiempresa ---------------------------------------------------------

def test_calcular_kpis_aislado_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.meta.kpi import calcular_kpis
    from app.services.metricas import registrar_metrica

    with client.application.app_context():
        campana_a = _crear_campana(usuario_a_con_empresa["empresa_id"], None, "c1")
        registrar_metrica(usuario_a_con_empresa["empresa_id"], "spend", 999.0, datetime.date(2026, 8, 1), entidad_id=campana_a.id, entidad_tipo="campana")

        kpis_b = calcular_kpis(usuario_b_con_empresa["empresa_id"], None, datetime.date(2026, 8, 1), datetime.date(2026, 8, 1))
        assert kpis_b["spend"] is None


# --- Extraccion de campos nuevos de Meta Insights (actions/action_values/video/roas) ---

def test_sincronizar_insights_extrae_conversiones_video_engagement_roas(client, usuario_a_con_empresa, monkeypatch):
    from app.services.meta.campanas_service import sincronizar_estructura
    from app.services.meta.insights_service import sincronizar_insights
    from app.services.meta.kpi import calcular_kpis
    from app.services.metricas import consultar_metricas

    with client.application.app_context():
        _preparar_cuenta_vinculada(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])

    _mockear_get_meta(monkeypatch, {
        "act_123/campaigns": {"data": [{"id": "c1", "name": "Campaña 1", "status": "ACTIVE", "effective_status": "ACTIVE"}]},
        "c1/adsets": {"data": []},
        "c1/insights": {"data": [{
            "spend": "100.0", "impressions": "5000", "reach": "4000", "clicks": "50", "frequency": "1.25",
            "actions": [{"action_type": "purchase", "value": "4"}, {"action_type": "link_click", "value": "50"}],
            "action_values": [{"action_type": "purchase", "value": "400.0"}],
            "video_play_actions": [{"action_type": "video_view", "value": "30"}],
            "video_thruplay_watched_actions": [{"action_type": "video_view", "value": "12"}],
            "inline_post_engagement": "22",
            "purchase_roas": [{"action_type": "omni_purchase", "value": "4.0"}],
            "date_start": "2026-08-01", "date_stop": "2026-08-01",
        }]},
    })

    with client.application.app_context():
        sincronizar_estructura(usuario_a_con_empresa["empresa_id"])
        resumen, error = sincronizar_insights(usuario_a_con_empresa["empresa_id"], datetime.date(2026, 8, 1), datetime.date(2026, 8, 1))
        assert error is None

        assert consultar_metricas(usuario_a_con_empresa["empresa_id"], metrica_nombre="conversiones")[0].valor == 4.0
        assert consultar_metricas(usuario_a_con_empresa["empresa_id"], metrica_nombre="valor_conversion")[0].valor == 400.0
        assert consultar_metricas(usuario_a_con_empresa["empresa_id"], metrica_nombre="video_plays")[0].valor == 30.0
        assert consultar_metricas(usuario_a_con_empresa["empresa_id"], metrica_nombre="thruplays")[0].valor == 12.0
        assert consultar_metricas(usuario_a_con_empresa["empresa_id"], metrica_nombre="engagement")[0].valor == 22.0
        assert consultar_metricas(usuario_a_con_empresa["empresa_id"], metrica_nombre="roas")[0].valor == 4.0

        costo_resultado = consultar_metricas(usuario_a_con_empresa["empresa_id"], metrica_nombre="costo_por_resultado")[0]
        assert costo_resultado.valor == 25.0  # 100 / 4
        assert costo_resultado.origen == "calculada"

        tasa = consultar_metricas(usuario_a_con_empresa["empresa_id"], metrica_nombre="tasa_conversion")[0]
        assert tasa.valor == 8.0  # 4 / 50 * 100

        campana = consultar_metricas(usuario_a_con_empresa["empresa_id"], metrica_nombre="spend")[0].entidad_id
        kpis = calcular_kpis(usuario_a_con_empresa["empresa_id"], [campana], datetime.date(2026, 8, 1), datetime.date(2026, 8, 1))
        assert kpis["resultados"] == 4.0
        assert kpis["roas"] == 4.0


def test_sincronizar_insights_sin_datos_de_conversion_deja_metricas_en_none(client, usuario_a_con_empresa, monkeypatch):
    """Si Meta NO devuelve actions/action_values/purchase_roas/video
    para una cuenta (ej. sin pixel de compras configurado), esas
    metricas nunca se inventan -- no se guarda fila y el KPI queda en
    None."""
    from app.services.meta.campanas_service import sincronizar_estructura
    from app.services.meta.insights_service import sincronizar_insights
    from app.services.meta.kpi import calcular_kpis
    from app.services.metricas import consultar_metricas

    with client.application.app_context():
        _preparar_cuenta_vinculada(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])

    _mockear_get_meta(monkeypatch, {
        "act_123/campaigns": {"data": [{"id": "c1", "name": "Campaña 1", "status": "ACTIVE", "effective_status": "ACTIVE"}]},
        "c1/adsets": {"data": []},
        "c1/insights": {"data": [{"spend": "20.0", "impressions": "800", "reach": "700", "clicks": "8", "frequency": "1.1", "date_start": "2026-08-01", "date_stop": "2026-08-01"}]},
    })

    with client.application.app_context():
        sincronizar_estructura(usuario_a_con_empresa["empresa_id"])
        sincronizar_insights(usuario_a_con_empresa["empresa_id"], datetime.date(2026, 8, 1), datetime.date(2026, 8, 1))

        assert consultar_metricas(usuario_a_con_empresa["empresa_id"], metrica_nombre="conversiones") == []
        assert consultar_metricas(usuario_a_con_empresa["empresa_id"], metrica_nombre="roas") == []

        campana_id = consultar_metricas(usuario_a_con_empresa["empresa_id"], metrica_nombre="spend")[0].entidad_id
        kpis = calcular_kpis(usuario_a_con_empresa["empresa_id"], [campana_id], datetime.date(2026, 8, 1), datetime.date(2026, 8, 1))
        assert kpis["conversiones"] is None
        assert kpis["roas"] is None
        assert kpis["costo_por_resultado"] is None
        assert kpis["spend"] == 20.0  # lo que si vino se guarda normalmente


# --- Ruta de la pantalla de prueba de KPI ----------------------------------------------

def test_ruta_kpi_prueba_sin_cuenta_muestra_toda_la_empresa(client, usuario_a_con_empresa):
    resp = client.get("/datos-meta/kpi")
    assert resp.status_code == 200
    assert "No disponible" in resp.get_data(as_text=True)


def test_ruta_kpi_prueba_cuenta_ajena_da_404(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.extensions import db

    with client.application.app_context():
        cuenta_b = EntidadPublicitaria(empresa_id=usuario_b_con_empresa["empresa_id"], fuente="meta", tipo="cuenta_publicitaria", id_externo="act_b")
        db.session.add(cuenta_b)
        db.session.commit()
        cuenta_b_id = cuenta_b.id

    # usuario_b_con_empresa fue el ultimo fixture en iniciar sesion --
    # se vuelve a autenticar como A explicitamente para probar que A no
    # puede consultar KPI de una cuenta de B.
    iniciar_sesion_de_prueba(client, usuario_a_con_empresa["usuario_id"], "a@example.com")

    resp = client.get(f"/datos-meta/kpi?cuenta_id={cuenta_b_id}")
    assert resp.status_code == 404


def test_ruta_kpi_prueba_periodo_personalizado(client, usuario_a_con_empresa):
    resp = client.get("/datos-meta/kpi?periodo=personalizado&fecha_inicio=2026-08-01&fecha_fin=2026-08-05")
    assert resp.status_code == 200


def test_ruta_kpi_prueba_muestra_presupuesto(client, usuario_a_con_empresa):
    client.post("/datos-meta/conexiones/presupuesto", json={"nombre": "Presupuesto de prueba KPI", "tipo": "estrategico", "monto": "500"})

    resp = client.get("/datos-meta/kpi")
    assert resp.status_code == 200
    assert "Presupuesto de prueba KPI" in resp.get_data(as_text=True)
