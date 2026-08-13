"""Pruebas del Paso 5 de Datos de Meta: interpretacion de targeting
(audiencia configurada, sin inventar campos que Meta no devuelve),
motor de reglas de oportunidades (sin IA, comparando cada entidad
contra el promedio de su propio grupo), el servicio estructurado de
analisis de campaña (conjuntos + anuncios + presupuesto +
oportunidades) y de audiencias (configurada vs. resultado real), y las
rutas nuevas con su aislamiento multiempresa.
"""

import datetime
from types import SimpleNamespace

from app.models import EntidadPublicitaria
from tests.conftest import iniciar_sesion_de_prueba


# --- targeting.py --------------------------------------------------------------------

def test_interpretar_targeting_none_devuelve_none():
    from app.services.meta.targeting import interpretar_targeting

    assert interpretar_targeting(None) is None
    assert interpretar_targeting({}) is None


def test_interpretar_targeting_edades_y_sexo():
    from app.services.meta.targeting import interpretar_targeting

    resultado = interpretar_targeting({"age_min": 25, "age_max": 45, "genders": [2]})
    assert resultado["edades"] == "25-45"
    assert resultado["sexo"] == "Mujeres"
    assert resultado["sin_datos"] is False


def test_interpretar_targeting_generos_vacio_es_todos():
    """Meta omite valores en `genders` cuando el conjunto apunta a
    todos los generos -- eso es un hecho real y documentado, no un
    valor inventado."""
    from app.services.meta.targeting import interpretar_targeting

    resultado = interpretar_targeting({"genders": []})
    assert resultado["sexo"] == "Todos"


def test_interpretar_targeting_ubicaciones_placements_dispositivos():
    from app.services.meta.targeting import interpretar_targeting

    resultado = interpretar_targeting({
        "geo_locations": {"countries": ["CR"], "cities": [{"name": "San José"}]},
        "publisher_platforms": ["facebook", "instagram"],
        "device_platforms": ["mobile"],
    })
    assert "países" in resultado["ubicaciones"]
    assert "San José" in resultado["ubicaciones"]
    assert "Plataformas" in resultado["placements"]
    assert resultado["dispositivos"] == "mobile"


def test_interpretar_targeting_publicos_personalizados_e_intereses():
    from app.services.meta.targeting import interpretar_targeting

    resultado = interpretar_targeting({
        "custom_audiences": [{"id": "123", "name": "Compradores web"}],
        "flexible_spec": [{"interests": [{"id": "1", "name": "Fotografía"}]}],
    })
    assert resultado["publicos_personalizados"] == [{"id": "123", "nombre": "Compradores web"}]
    assert resultado["intereses"] == ["Fotografía"]


def test_interpretar_targeting_sin_ningun_campo_conocido_marca_sin_datos():
    from app.services.meta.targeting import interpretar_targeting

    resultado = interpretar_targeting({"campo_desconocido": "x"})
    assert resultado["sin_datos"] is True
    assert resultado["edades"] is None


# --- oportunidades.py -----------------------------------------------------------------

def _fila(nombre, **kpis):
    entidad = SimpleNamespace(id=abs(hash(nombre)) % 100000, nombre=nombre, id_externo=nombre)
    base = {
        "spend": None, "ctr": None, "cpm": None, "costo_por_resultado": None,
        "frequency": None, "resultados": None,
    }
    base.update(kpis)
    return {"entidad": entidad, "kpis": base, "es_mejor": False, "es_peor": False}


def test_detectar_oportunidades_grupo_vacio():
    from app.services.meta.oportunidades import detectar_oportunidades_grupo

    assert detectar_oportunidades_grupo([]) == []


def test_detectar_oportunidades_un_solo_elemento_no_detecta_nada():
    """Con una sola entidad, esa entidad ES el promedio -- diferencia
    relativa 0, ninguna oportunidad (comportamiento seguro, no un caso
    especial)."""
    from app.services.meta.oportunidades import detectar_oportunidades_grupo

    filas = [_fila("Única", ctr=5.0, spend=100.0)]
    assert detectar_oportunidades_grupo(filas) == []


def test_detectar_ctr_alto_y_bajo():
    from app.services.meta.oportunidades import detectar_oportunidades_grupo

    filas = [_fila("Alto CTR", ctr=10.0), _fila("Bajo CTR", ctr=1.0)]
    oportunidades = detectar_oportunidades_grupo(filas)
    tipos_alto = {o["tipo"] for o in oportunidades if o["entidad_nombre"] == "Alto CTR"}
    tipos_bajo = {o["tipo"] for o in oportunidades if o["entidad_nombre"] == "Bajo CTR"}
    assert "ctr_alto" in tipos_alto
    assert "ctr_bajo" in tipos_bajo


def test_detectar_costo_resultado_bajo_y_buen_rendimiento_poco_presupuesto():
    from app.services.meta.oportunidades import detectar_oportunidades_grupo

    filas = [
        _fila("Eficiente", costo_por_resultado=5.0, spend=50.0),
        _fila("Cara", costo_por_resultado=20.0, spend=200.0),
    ]
    oportunidades = detectar_oportunidades_grupo(filas)
    tipos_eficiente = {o["tipo"] for o in oportunidades if o["entidad_nombre"] == "Eficiente"}
    assert "costo_resultado_bajo" in tipos_eficiente
    assert "buen_rendimiento_poco_presupuesto" in tipos_eficiente

    tipos_cara = {o["tipo"] for o in oportunidades if o["entidad_nombre"] == "Cara"}
    assert "costo_resultado_alto" in tipos_cara


def test_detectar_frecuencia_elevada():
    from app.services.meta.oportunidades import detectar_oportunidades_grupo

    filas = [_fila("Fatigada", frequency=6.0), _fila("Normal", frequency=1.5)]
    oportunidades = detectar_oportunidades_grupo(filas)
    fatigada = [o for o in oportunidades if o["entidad_nombre"] == "Fatigada" and o["tipo"] == "frecuencia_elevada"]
    assert fatigada and fatigada[0]["nivel"] == "alto"
    assert not [o for o in oportunidades if o["entidad_nombre"] == "Normal" and o["tipo"] == "frecuencia_elevada"]


def test_detectar_gasto_alto_sin_resultados():
    from app.services.meta.oportunidades import detectar_oportunidades_grupo

    filas = [
        _fila("Gasta sin convertir", spend=500.0, resultados=None),
        _fila("Normal", spend=50.0, resultados=5.0),
    ]
    oportunidades = detectar_oportunidades_grupo(filas)
    tipos = {o["tipo"] for o in oportunidades if o["entidad_nombre"] == "Gasta sin convertir"}
    assert "gasto_alto_sin_resultados" in tipos


def test_detectar_gasto_alto_bajo_resultado():
    from app.services.meta.oportunidades import detectar_oportunidades_grupo

    filas = [
        _fila("Ineficiente", spend=500.0, resultados=1.0),
        _fila("Normal", spend=50.0, resultados=20.0),
    ]
    oportunidades = detectar_oportunidades_grupo(filas)
    tipos = {o["tipo"] for o in oportunidades if o["entidad_nombre"] == "Ineficiente"}
    assert "gasto_alto_bajo_resultado" in tipos


# --- analisis.py: construir_analisis_campana -------------------------------------------

def _crear_cuenta(empresa_id, id_externo="act_1", moneda="USD"):
    from app.extensions import db

    cuenta = EntidadPublicitaria(empresa_id=empresa_id, fuente="meta", tipo="cuenta_publicitaria", id_externo=id_externo, nombre="Cuenta", atributos={"moneda": moneda})
    db.session.add(cuenta)
    db.session.commit()
    return cuenta


def _crear_campana(empresa_id, id_externo, entidad_padre_id=None, estado="ACTIVE", objetivo="OUTCOME_SALES"):
    from app.extensions import db

    campana = EntidadPublicitaria(
        empresa_id=empresa_id, fuente="meta", tipo="campana", id_externo=id_externo,
        nombre=f"Campaña {id_externo}", entidad_padre_id=entidad_padre_id, estado=estado,
        atributos={"objetivo": objetivo, "fecha_inicio": "2026-08-01T00:00:00-0600", "presupuesto_diario": "5000"},
    )
    db.session.add(campana)
    db.session.commit()
    return campana


def _crear_conjunto(empresa_id, id_externo, campana_id, targeting=None, estado="ACTIVE"):
    from app.extensions import db

    conjunto = EntidadPublicitaria(
        empresa_id=empresa_id, fuente="meta", tipo="conjunto_anuncios", id_externo=id_externo,
        nombre=f"Conjunto {id_externo}", entidad_padre_id=campana_id, estado=estado,
        atributos={"targeting": targeting or {}, "presupuesto_diario": "1000"},
    )
    db.session.add(conjunto)
    db.session.commit()
    return conjunto


def _crear_anuncio(empresa_id, id_externo, conjunto_id, estado="ACTIVE"):
    from app.extensions import db

    anuncio = EntidadPublicitaria(
        empresa_id=empresa_id, fuente="meta", tipo="anuncio", id_externo=id_externo,
        nombre=f"Anuncio {id_externo}", entidad_padre_id=conjunto_id, estado=estado,
        atributos={"creativo": {"titulo": "Prueba"}},
    )
    db.session.add(anuncio)
    db.session.commit()
    return anuncio


def _registrar(empresa_id, entidad_id, entidad_tipo, metrica, valor, fecha):
    from app.services.metricas import registrar_metrica

    registrar_metrica(empresa_id, metrica, valor, fecha, entidad_id=entidad_id, entidad_tipo=entidad_tipo)


def test_construir_analisis_campana_no_existe(client, usuario_a_con_empresa):
    from app.services.meta.analisis import construir_analisis_campana

    with client.application.app_context():
        paquete, error = construir_analisis_campana(usuario_a_con_empresa["empresa_id"], 999999, datetime.date(2026, 8, 1), datetime.date(2026, 8, 1))
        assert paquete is None
        assert error is not None


def test_construir_analisis_campana_incluye_conjuntos_con_targeting_y_anuncios(client, usuario_a_con_empresa):
    from app.services.meta.analisis import construir_analisis_campana

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", entidad_padre_id=cuenta.id)
        conjunto = _crear_conjunto(empresa_id, "as1", campana.id, targeting={"age_min": 18, "age_max": 34, "genders": [1]})
        anuncio = _crear_anuncio(empresa_id, "ad1", conjunto.id)

        fecha = datetime.date(2026, 8, 1)
        _registrar(empresa_id, campana.id, "campana", "spend", 100.0, fecha)
        _registrar(empresa_id, conjunto.id, "conjunto_anuncios", "spend", 100.0, fecha)
        _registrar(empresa_id, conjunto.id, "conjunto_anuncios", "clicks", 20.0, fecha)
        _registrar(empresa_id, anuncio.id, "anuncio", "spend", 100.0, fecha)
        _registrar(empresa_id, anuncio.id, "anuncio", "video_plays", 40.0, fecha)

        paquete, error = construir_analisis_campana(empresa_id, campana.id, fecha, fecha)
        assert error is None
        assert paquete["kpis"]["spend"] == 100.0

        assert len(paquete["conjuntos"]) == 1
        fila_conjunto = paquete["conjuntos"][0]
        assert fila_conjunto["targeting"]["edades"] == "18-34"
        assert fila_conjunto["targeting"]["sexo"] == "Hombres"
        assert fila_conjunto["kpis"]["spend"] == 100.0

        assert len(paquete["anuncios"]) == 1
        assert paquete["anuncios"][0]["kpis"]["video_plays"] == 40.0

        assert paquete["gasto_real"] == 100.0


def test_construir_analisis_campana_comparar_incluye_periodo_anterior(client, usuario_a_con_empresa):
    from app.services.meta.analisis import construir_analisis_campana

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        campana = _crear_campana(empresa_id, "c1")
        _registrar(empresa_id, campana.id, "campana", "spend", 100.0, datetime.date(2026, 8, 10))
        _registrar(empresa_id, campana.id, "campana", "spend", 50.0, datetime.date(2026, 8, 9))

        paquete, error = construir_analisis_campana(empresa_id, campana.id, datetime.date(2026, 8, 10), datetime.date(2026, 8, 10), comparar=True)
        assert error is None
        assert paquete["comparacion"]["periodo_actual"]["kpis"]["spend"] == 100.0
        assert paquete["comparacion"]["periodo_anterior"]["kpis"]["spend"] == 50.0
        assert paquete["comparacion"]["variacion_porcentual"]["spend"] == 100.0


def test_construir_analisis_campana_presupuesto_asignado(client, usuario_a_con_empresa):
    from app.services.meta.analisis import construir_analisis_campana
    from app.services.presupuestos import crear_presupuesto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        campana = _crear_campana(empresa_id, "c1")
        crear_presupuesto(
            empresa_id, usuario_a_con_empresa["usuario_id"], "Presupuesto de campaña", "asignado", 500.0,
            entidad_id=campana.id, periodo_tipo="personalizado", fecha_inicio=datetime.date(2026, 8, 1), fecha_fin=datetime.date(2026, 8, 31),
        )
        _registrar(empresa_id, campana.id, "campana", "spend", 200.0, datetime.date(2026, 8, 5))

        paquete, error = construir_analisis_campana(empresa_id, campana.id, datetime.date(2026, 8, 1), datetime.date(2026, 8, 31))
        assert error is None
        assert len(paquete["presupuestos_asignados"]) == 1
        assert paquete["presupuestos_asignados"][0].monto == 500.0


def test_construir_analisis_campana_detecta_buen_rendimiento_vs_hermanas(client, usuario_a_con_empresa):
    from app.services.meta.analisis import construir_analisis_campana

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        barata = _crear_campana(empresa_id, "barata", entidad_padre_id=cuenta.id)
        cara = _crear_campana(empresa_id, "cara", entidad_padre_id=cuenta.id)
        fecha = datetime.date(2026, 8, 1)
        # barata: gasto bajo, 10 conversiones -> costo_por_resultado bajo
        _registrar(empresa_id, barata.id, "campana", "spend", 50.0, fecha)
        _registrar(empresa_id, barata.id, "campana", "conversiones", 10.0, fecha)
        # cara: gasto alto, 2 conversiones -> costo_por_resultado alto
        _registrar(empresa_id, cara.id, "campana", "spend", 400.0, fecha)
        _registrar(empresa_id, cara.id, "campana", "conversiones", 2.0, fecha)

        paquete, _ = construir_analisis_campana(empresa_id, barata.id, fecha, fecha)
        tipos = {o["tipo"] for o in paquete["oportunidades_campana"]}
        assert "buen_rendimiento_poco_presupuesto" in tipos or "costo_resultado_bajo" in tipos


# --- analisis.py: analizar_audiencias ---------------------------------------------------

def test_analizar_audiencias_separa_configuracion_de_resultado(client, usuario_a_con_empresa):
    from app.services.meta.analisis import analizar_audiencias

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", entidad_padre_id=cuenta.id)
        conjunto = _crear_conjunto(empresa_id, "as1", campana.id, targeting={"age_min": 25, "age_max": 34, "device_platforms": ["mobile"]})
        fecha = datetime.date(2026, 8, 1)
        _registrar(empresa_id, conjunto.id, "conjunto_anuncios", "spend", 80.0, fecha)
        _registrar(empresa_id, conjunto.id, "conjunto_anuncios", "conversiones", 4.0, fecha)

        paquete, error = analizar_audiencias(empresa_id, None, fecha, fecha)
        assert error is None
        assert len(paquete["segmentos"]) == 1
        segmento = paquete["segmentos"][0]
        # "configurado" viene de targeting, nunca se mezcla con kpis medidos
        assert segmento["targeting"]["edades"] == "25-34"
        assert segmento["targeting"]["dispositivos"] == "mobile"
        assert segmento["kpis"]["spend"] == 80.0
        assert segmento["kpis"]["conversiones"] == 4.0


def test_analizar_audiencias_incluye_nombre_de_campana_padre(client, usuario_a_con_empresa):
    from app.services.meta.analisis import analizar_audiencias

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        campana = _crear_campana(empresa_id, "c1")
        _crear_conjunto(empresa_id, "as1", campana.id, targeting={"age_min": 20, "age_max": 30})

        paquete, error = analizar_audiencias(empresa_id, None, datetime.date(2026, 8, 1), datetime.date(2026, 8, 1))
        assert error is None
        assert paquete["segmentos"][0]["campana_nombre"] == campana.nombre


def test_analizar_audiencias_conjunto_sin_targeting_no_inventa_configuracion(client, usuario_a_con_empresa):
    from app.services.meta.analisis import analizar_audiencias

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        campana = _crear_campana(empresa_id, "c1")
        _crear_conjunto(empresa_id, "as1", campana.id, targeting=None)

        paquete, error = analizar_audiencias(empresa_id, None, datetime.date(2026, 8, 1), datetime.date(2026, 8, 1))
        assert error is None
        assert paquete["segmentos"][0]["targeting"] is None


def test_analizar_audiencias_cuenta_ajena_da_error(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.meta.analisis import analizar_audiencias

    with client.application.app_context():
        cuenta_b = _crear_cuenta(usuario_b_con_empresa["empresa_id"], id_externo="act_b")
        cuenta_b_id = cuenta_b.id

        paquete, error = analizar_audiencias(usuario_a_con_empresa["empresa_id"], cuenta_b_id, datetime.date(2026, 8, 1), datetime.date(2026, 8, 1))
        assert paquete is None
        assert error is not None


# --- Rutas -------------------------------------------------------------------------

def test_ruta_campanas_lista_carga(client, usuario_a_con_empresa):
    resp = client.get("/datos-meta/campanas")
    assert resp.status_code == 200


def test_ruta_campana_detalle_404_para_campana_ajena(client, usuario_a_con_empresa, usuario_b_con_empresa):
    with client.application.app_context():
        campana_b = _crear_campana(usuario_b_con_empresa["empresa_id"], "cb")
        campana_b_id = campana_b.id

    iniciar_sesion_de_prueba(client, usuario_a_con_empresa["usuario_id"], "a@example.com")
    resp = client.get(f"/datos-meta/campanas/{campana_b_id}")
    assert resp.status_code == 404


def test_ruta_campana_detalle_muestra_conjuntos_y_anuncios(client, usuario_a_con_empresa):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        campana = _crear_campana(empresa_id, "c1")
        conjunto = _crear_conjunto(empresa_id, "as1", campana.id, targeting={"age_min": 20, "age_max": 30})
        _crear_anuncio(empresa_id, "ad1", conjunto.id)
        fecha = datetime.date(2026, 8, 1)
        _registrar(empresa_id, campana.id, "campana", "spend", 75.0, fecha)
        campana_id = campana.id

    resp = client.get(f"/datos-meta/campanas/{campana_id}?periodo=personalizado&fecha_inicio=2026-08-01&fecha_fin=2026-08-01")
    assert resp.status_code == 200
    texto = resp.get_data(as_text=True)
    assert "DM_CAMPANA_INICIAL" in texto


def test_ruta_campana_datos_json_incluye_oportunidades_y_presupuesto(client, usuario_a_con_empresa):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        barata = _crear_campana(empresa_id, "barata", entidad_padre_id=cuenta.id)
        cara = _crear_campana(empresa_id, "cara", entidad_padre_id=cuenta.id)
        fecha = datetime.date(2026, 8, 1)
        _registrar(empresa_id, barata.id, "campana", "spend", 50.0, fecha)
        _registrar(empresa_id, barata.id, "campana", "conversiones", 10.0, fecha)
        _registrar(empresa_id, cara.id, "campana", "spend", 400.0, fecha)
        _registrar(empresa_id, cara.id, "campana", "conversiones", 2.0, fecha)
        barata_id = barata.id

    resp = client.get(f"/datos-meta/campanas/{barata_id}/datos?periodo=personalizado&fecha_inicio=2026-08-01&fecha_fin=2026-08-01")
    assert resp.status_code == 200
    datos = resp.get_json()
    assert datos["gasto_real"] == 50.0
    assert "oportunidades_campana" in datos
    assert isinstance(datos["oportunidades_campana"], list)


def test_ruta_audiencias_carga(client, usuario_a_con_empresa):
    resp = client.get("/datos-meta/audiencias")
    assert resp.status_code == 200
    assert "DM_AUDIENCIAS_INICIAL" in resp.get_data(as_text=True)


def test_ruta_audiencias_datos_aislada_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        campana = _crear_campana(empresa_id, "c1")
        conjunto = _crear_conjunto(empresa_id, "as1", campana.id, targeting={"age_min": 18, "age_max": 24})
        _registrar(empresa_id, conjunto.id, "conjunto_anuncios", "spend", 60.0, datetime.date(2026, 8, 1))

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp = client.get("/datos-meta/audiencias/datos?periodo=personalizado&fecha_inicio=2026-08-01&fecha_fin=2026-08-01")
    datos = resp.get_json()
    assert datos["segmentos"] == []  # nunca ve el conjunto de la empresa A


def test_ruta_audiencias_datos_cuenta_ajena_devuelve_error(client, usuario_a_con_empresa, usuario_b_con_empresa):
    with client.application.app_context():
        cuenta_b = _crear_cuenta(usuario_b_con_empresa["empresa_id"], id_externo="act_b")
        cuenta_b_id = cuenta_b.id

    iniciar_sesion_de_prueba(client, usuario_a_con_empresa["usuario_id"], "a@example.com")
    resp = client.get(f"/datos-meta/audiencias/datos?cuenta_id={cuenta_b_id}")
    assert resp.status_code == 200
    assert resp.get_json()["error"] is not None
