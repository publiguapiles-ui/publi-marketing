"""Pruebas del Paso 2 de Datos de Meta: periodos, clasificacion de
errores, sincronizacion real de estructura (campanas/conjuntos/
anuncios) e insights contra un MetaClient mockeado, orquestador de
SincronizacionMeta con reintentos acotados, presupuesto de pauta
(estrategico vs gasto real calculado desde Metrica), y las rutas
nuevas con su aislamiento multiempresa.
"""

import datetime

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


# --- Periodos --------------------------------------------------------------------

def test_resolver_periodo_ultimos_7_dias():
    from app.services.periodos import resolver_periodo

    hoy = datetime.date(2026, 8, 15)
    inicio, fin = resolver_periodo("ultimos_7_dias", hoy=hoy)
    assert fin == hoy
    assert (fin - inicio).days == 6


def test_resolver_periodo_este_mes():
    from app.services.periodos import resolver_periodo

    hoy = datetime.date(2026, 8, 15)
    inicio, fin = resolver_periodo("este_mes", hoy=hoy)
    assert inicio == datetime.date(2026, 8, 1)
    assert fin == hoy


def test_resolver_periodo_mes_anterior():
    from app.services.periodos import resolver_periodo

    hoy = datetime.date(2026, 8, 15)
    inicio, fin = resolver_periodo("mes_anterior", hoy=hoy)
    assert inicio == datetime.date(2026, 7, 1)
    assert fin == datetime.date(2026, 7, 31)


def test_resolver_periodo_personalizado_requiere_fechas():
    from app.services.periodos import resolver_periodo

    try:
        resolver_periodo("personalizado")
        assert False, "debia lanzar ValueError"
    except ValueError:
        pass


def test_resolver_periodo_personalizado_fecha_fin_antes_de_inicio_falla():
    from app.services.periodos import resolver_periodo

    try:
        resolver_periodo("personalizado", fecha_inicio=datetime.date(2026, 1, 10), fecha_fin=datetime.date(2026, 1, 1))
        assert False
    except ValueError:
        pass


def test_periodo_anterior_equivalente():
    from app.services.periodos import periodo_anterior_equivalente

    inicio, fin = periodo_anterior_equivalente(datetime.date(2026, 8, 1), datetime.date(2026, 8, 30))  # 30 dias
    assert fin == datetime.date(2026, 7, 31)
    assert (fin - inicio).days == 29  # misma duracion (30 dias)


# --- Clasificacion de errores ------------------------------------------------------

def test_clasificar_error_token_expirado():
    from app.services.meta.client import MetaAPIError
    from app.services.meta.errores import clasificar_error_meta

    assert clasificar_error_meta(MetaAPIError("Invalid token", codigo=190)) == "token_expirado"


def test_clasificar_error_limite_api():
    from app.services.meta.client import MetaAPIError
    from app.services.meta.errores import clasificar_error_meta

    assert clasificar_error_meta(MetaAPIError("Rate limit", codigo=613)) == "limite_api"
    assert clasificar_error_meta(MetaAPIError("App limit", codigo=4)) == "limite_api"


def test_clasificar_error_permisos():
    from app.services.meta.client import MetaAPIError
    from app.services.meta.errores import clasificar_error_meta

    assert clasificar_error_meta(MetaAPIError("Permission denied", codigo=10)) == "permisos"


def test_clasificar_error_activo_inexistente():
    from app.services.meta.client import MetaAPIError
    from app.services.meta.errores import clasificar_error_meta

    assert clasificar_error_meta(MetaAPIError("Object does not exist", codigo=100)) == "activo_inexistente"


def test_clasificar_error_desconocido_es_interno():
    from app.services.meta.client import MetaAPIError
    from app.services.meta.errores import clasificar_error_meta

    assert clasificar_error_meta(MetaAPIError("Algo raro", codigo=999999)) == "interno"


def test_mensaje_para_usuario_nunca_expone_detalles_internos():
    from app.services.meta.errores import mensaje_para_usuario

    mensaje = mensaje_para_usuario("token_expirado")
    assert "reconectar" in mensaje.lower()


# --- Uso real de la cuota de Meta (headers x-*-usage) ---------------------------------

def test_extraer_uso_meta_lee_headers_documentados():
    from app.services.meta.client import _extraer_uso_meta

    class _RespuestaFalsa:
        headers = {
            "x-ad-account-usage": '{"acc_id_util_pct": 97.5}',
            "x-app-usage": '{"call_count": 40, "total_cputime": 10, "total_time": 12}',
        }

    uso = _extraer_uso_meta(_RespuestaFalsa())
    assert uso["cuenta_publicitaria"]["acc_id_util_pct"] == 97.5
    assert uso["app"]["call_count"] == 40


def test_extraer_uso_meta_devuelve_none_sin_headers():
    from app.services.meta.client import _extraer_uso_meta

    class _RespuestaFalsa:
        headers = {}

    assert _extraer_uso_meta(_RespuestaFalsa()) is None


def test_mensaje_para_usuario_incluye_porcentaje_real_de_cuenta_publicitaria():
    from app.services.meta.client import MetaAPIError
    from app.services.meta.errores import mensaje_para_usuario

    exc = MetaAPIError("Rate limit", codigo=613, uso_meta={"cuenta_publicitaria": {"acc_id_util_pct": 100}})
    mensaje = mensaje_para_usuario("limite_api", exc)
    assert "100%" in mensaje


def test_mensaje_para_usuario_incluye_estimacion_de_business_use_case():
    from app.services.meta.client import MetaAPIError
    from app.services.meta.errores import mensaje_para_usuario

    uso = {"business_use_case": {"123": [{"type": "ads_management", "estimated_time_to_regain_access": 45}]}}
    exc = MetaAPIError("Rate limit", codigo=613, uso_meta=uso)
    mensaje = mensaje_para_usuario("limite_api", exc)
    assert "45 minutos" in mensaje


def test_mensaje_para_usuario_sin_uso_meta_no_inventa_numeros():
    from app.services.meta.client import MetaAPIError
    from app.services.meta.errores import mensaje_para_usuario

    exc = MetaAPIError("Rate limit", codigo=613, uso_meta=None)
    mensaje = mensaje_para_usuario("limite_api", exc)
    assert mensaje == "Se alcanzó el límite de solicitudes de Meta. Intenta de nuevo en unos minutos."


def test_mensaje_para_usuario_sigue_funcionando_sin_excepcion():
    from app.services.meta.errores import mensaje_para_usuario

    assert mensaje_para_usuario("limite_api") == "Se alcanzó el límite de solicitudes de Meta. Intenta de nuevo en unos minutos."


# --- Sincronizacion de estructura (campanas/conjuntos/anuncios) -----------------

def _preparar_cuenta_vinculada(empresa_id, usuario_id):
    from app.services.meta.conexiones import crear_conexion
    from app.services.meta.cuentas_service import vincular_activos

    crear_conexion(empresa_id, usuario_id, "111", "A", "token-a")
    vincular_activos(empresa_id, [
        {"tipo": "cuenta_publicitaria", "id_externo": "act_123", "nombre": "Cuenta", "atributos": {"moneda": "USD"}},
    ])


def test_sincronizar_estructura_guarda_jerarquia_completa(client, usuario_a_con_empresa, monkeypatch):
    from app.services.meta.campanas_service import sincronizar_estructura
    from app.services.meta.cuentas_service import listar_entidades_empresa

    with client.application.app_context():
        _preparar_cuenta_vinculada(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])

    _mockear_get_meta(monkeypatch, {
        "act_123/campaigns": {"data": [{"id": "c1", "name": "Campaña 1", "objective": "OUTCOME_TRAFFIC", "status": "ACTIVE", "effective_status": "ACTIVE", "daily_budget": "5000"}]},
        "c1/adsets": {"data": [{"id": "as1", "name": "Conjunto 1", "campaign_id": "c1", "status": "ACTIVE", "effective_status": "ACTIVE", "daily_budget": "2500", "targeting": {"age_min": 18, "age_max": 45}}]},
        "as1/ads": {"data": [{"id": "ad1", "name": "Anuncio 1", "adset_id": "as1", "status": "ACTIVE", "effective_status": "ACTIVE", "creative": {"id": "cr1", "name": "Creativo 1"}}]},
    })

    with client.application.app_context():
        resumen, error = sincronizar_estructura(usuario_a_con_empresa["empresa_id"])
        assert error is None
        assert resumen == {"campanas": 1, "conjuntos_anuncios": 1, "anuncios": 1}

        campanas = listar_entidades_empresa(usuario_a_con_empresa["empresa_id"], tipo="campana")
        assert campanas[0].atributos["objetivo"] == "OUTCOME_TRAFFIC"

        conjuntos = listar_entidades_empresa(usuario_a_con_empresa["empresa_id"], tipo="conjunto_anuncios")
        assert conjuntos[0].atributos["targeting"]["age_min"] == 18
        assert conjuntos[0].entidad_padre_id == campanas[0].id

        anuncios = listar_entidades_empresa(usuario_a_con_empresa["empresa_id"], tipo="anuncio")
        assert anuncios[0].atributos["creativo"]["nombre"] == "Creativo 1"
        assert anuncios[0].entidad_padre_id == conjuntos[0].id


def test_sincronizar_estructura_sin_cuentas_vinculadas_falla(client, usuario_a_con_empresa):
    from app.services.meta.campanas_service import sincronizar_estructura
    from app.services.meta.conexiones import crear_conexion

    with client.application.app_context():
        crear_conexion(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "111", "A", "token-a")
        resumen, error = sincronizar_estructura(usuario_a_con_empresa["empresa_id"])
        assert resumen is None
        assert error is not None


def test_sincronizar_estructura_token_expirado_invalida_la_conexion(client, usuario_a_con_empresa, monkeypatch):
    """Un error de tipo token_expirado (codigo 190) SI debe invalidar
    la conexion -- el token en si ya no sirve, hay que reconectar."""
    from app.extensions import db
    from app.models import MetaConexion
    from app.services.meta.campanas_service import sincronizar_estructura
    from app.services.meta.client import MetaAPIError
    from app.services.meta.conexiones import obtener_conexion_activa

    with client.application.app_context():
        _preparar_cuenta_vinculada(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])

    _mockear_get_meta(monkeypatch, {"act_123/campaigns": MetaAPIError("Invalid token", codigo=190)})

    with client.application.app_context():
        resumen, error = sincronizar_estructura(usuario_a_con_empresa["empresa_id"])
        assert resumen is None
        assert "reconectar" in error.lower()

        # ya no es "la" conexion activa (el token no sirve)
        assert obtener_conexion_activa(usuario_a_con_empresa["empresa_id"]) is None
        conexion = db.session.query(MetaConexion).filter_by(empresa_id=usuario_a_con_empresa["empresa_id"]).first()
        assert conexion.estado == "error"
        assert conexion.ultimo_error is not None


def test_sincronizar_estructura_error_transitorio_no_invalida_la_conexion(client, usuario_a_con_empresa, monkeypatch):
    """Un error transitorio (limite de API, codigo 613) NO debe
    invalidar la conexion -- el token sigue siendo valido, el usuario
    solo necesita reintentar."""
    from app.services.meta.campanas_service import sincronizar_estructura
    from app.services.meta.client import MetaAPIError
    from app.services.meta.conexiones import obtener_conexion_activa

    with client.application.app_context():
        _preparar_cuenta_vinculada(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])

    _mockear_get_meta(monkeypatch, {"act_123/campaigns": MetaAPIError("Rate limited", codigo=613)})

    with client.application.app_context():
        resumen, error = sincronizar_estructura(usuario_a_con_empresa["empresa_id"])
        assert resumen is None
        assert error is not None

        conexion = obtener_conexion_activa(usuario_a_con_empresa["empresa_id"])
        assert conexion is not None  # sigue activa
        assert conexion.ultimo_error is not None  # pero el error queda registrado


# --- Insights (metricas reales) ---------------------------------------------------

def test_sincronizar_insights_guarda_metricas_via_motor_universal(client, usuario_a_con_empresa, monkeypatch):
    from app.services.meta.campanas_service import sincronizar_estructura
    from app.services.meta.insights_service import sincronizar_insights
    from app.services.metricas import consultar_metricas

    with client.application.app_context():
        _preparar_cuenta_vinculada(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])

    _mockear_get_meta(monkeypatch, {
        "act_123/campaigns": {"data": [{"id": "c1", "name": "Campaña 1", "status": "ACTIVE", "effective_status": "ACTIVE"}]},
        "c1/adsets": {"data": []},
        "c1/insights": {"data": [
            {"spend": "10.5", "impressions": "1000", "reach": "800", "clicks": "12", "frequency": "1.25", "date_start": "2026-08-01", "date_stop": "2026-08-01"},
            {"spend": "8.0", "impressions": "900", "reach": "700", "clicks": "9", "frequency": "1.1", "date_start": "2026-08-02", "date_stop": "2026-08-02"},
        ]},
    })

    with client.application.app_context():
        sincronizar_estructura(usuario_a_con_empresa["empresa_id"])
        resumen, error = sincronizar_insights(usuario_a_con_empresa["empresa_id"], datetime.date(2026, 8, 1), datetime.date(2026, 8, 2))
        assert error is None
        assert resumen["entidades_con_datos"] == 1

        filas = consultar_metricas(usuario_a_con_empresa["empresa_id"], metrica_nombre="spend")
        assert len(filas) == 2
        assert round(sum(f.valor for f in filas), 2) == 18.5

        ctr = consultar_metricas(usuario_a_con_empresa["empresa_id"], metrica_nombre="ctr")
        assert len(ctr) == 2  # una fila calculada por dia, no vacio (ver Paso 3: bug de string/float corregido)
        assert all(f.origen == "calculada" for f in ctr)


def test_sincronizar_insights_reemplaza_el_mismo_dia_sin_duplicar(client, usuario_a_con_empresa, monkeypatch):
    from app.services.meta.campanas_service import sincronizar_estructura
    from app.services.meta.insights_service import sincronizar_insights
    from app.services.metricas import consultar_metricas

    with client.application.app_context():
        _preparar_cuenta_vinculada(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])

    _mockear_get_meta(monkeypatch, {
        "act_123/campaigns": {"data": [{"id": "c1", "name": "Campaña 1", "status": "ACTIVE", "effective_status": "ACTIVE"}]},
        "c1/adsets": {"data": []},
        "c1/insights": {"data": [{"spend": "10.0", "impressions": "1000", "reach": "800", "clicks": "10", "frequency": "1.0", "date_start": "2026-08-01", "date_stop": "2026-08-01"}]},
    })

    with client.application.app_context():
        sincronizar_estructura(usuario_a_con_empresa["empresa_id"])
        sincronizar_insights(usuario_a_con_empresa["empresa_id"], datetime.date(2026, 8, 1), datetime.date(2026, 8, 1))
        sincronizar_insights(usuario_a_con_empresa["empresa_id"], datetime.date(2026, 8, 1), datetime.date(2026, 8, 1))  # re-sincroniza el mismo dia

        filas = consultar_metricas(usuario_a_con_empresa["empresa_id"], metrica_nombre="spend")
        assert len(filas) == 1  # no se duplico


# --- Orquestador de sincronizacion ------------------------------------------------

def test_iniciar_sincronizacion_completa_exitosamente(client, usuario_a_con_empresa, monkeypatch):
    from app.services.meta.sincronizacion import iniciar_sincronizacion

    with client.application.app_context():
        _preparar_cuenta_vinculada(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])

    _mockear_get_meta(monkeypatch, {
        "act_123/campaigns": {"data": [{"id": "c1", "name": "Campaña 1", "status": "ACTIVE", "effective_status": "ACTIVE"}]},
        "c1/adsets": {"data": []},
        "c1/insights": {"data": [{"spend": "5.0", "impressions": "500", "reach": "400", "clicks": "5", "frequency": "1.0", "date_start": "2026-08-01", "date_stop": "2026-08-01"}]},
    })

    with client.application.app_context():
        sincronizacion, error = iniciar_sincronizacion(
            usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "inicial",
            datetime.date(2026, 8, 1), datetime.date(2026, 8, 1),
        )
        assert error is None
        assert sincronizacion.estado == "completada"
        assert sincronizacion.registros_procesados > 0
        assert sincronizacion.finalizada_en is not None


def test_iniciar_sincronizacion_sin_conexion_falla_antes_de_crear_fila(client, usuario_a_con_empresa):
    from app.extensions import db
    from app.models import SincronizacionMeta
    from app.services.meta.sincronizacion import iniciar_sincronizacion

    with client.application.app_context():
        sincronizacion, error = iniciar_sincronizacion(
            usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "inicial",
            datetime.date(2026, 8, 1), datetime.date(2026, 8, 1),
        )
        assert sincronizacion is None
        assert error is not None
        assert db.session.query(SincronizacionMeta).count() == 0


def test_sincronizacion_marca_error_si_falla_la_estructura(client, usuario_a_con_empresa, monkeypatch):
    from app.services.meta.client import MetaAPIError
    from app.services.meta.sincronizacion import iniciar_sincronizacion

    with client.application.app_context():
        _preparar_cuenta_vinculada(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])

    _mockear_get_meta(monkeypatch, {"act_123/campaigns": MetaAPIError("Rate limited", codigo=613)})

    with client.application.app_context():
        sincronizacion, error = iniciar_sincronizacion(
            usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "inicial",
            datetime.date(2026, 8, 1), datetime.date(2026, 8, 1),
        )
        assert error is None  # la validacion previa paso; el error es del trabajo en si
        assert sincronizacion.estado == "error"
        assert "límite" in sincronizacion.error_mensaje.lower()
        assert sincronizacion.intentos == 1


def test_reintentar_respeta_el_maximo_de_intentos(client, usuario_a_con_empresa, monkeypatch):
    from app.services.meta.client import MetaAPIError
    from app.services.meta.sincronizacion import MAX_INTENTOS, iniciar_sincronizacion, reintentar_sincronizacion

    with client.application.app_context():
        _preparar_cuenta_vinculada(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])

    _mockear_get_meta(monkeypatch, {"act_123/campaigns": MetaAPIError("Interno", codigo=999999)})

    with client.application.app_context():
        sincronizacion, _ = iniciar_sincronizacion(
            usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "inicial",
            datetime.date(2026, 8, 1), datetime.date(2026, 8, 1),
        )
        assert sincronizacion.intentos == 1

        # reintentar hasta el limite
        for _ in range(MAX_INTENTOS - 1):
            sincronizacion, error = reintentar_sincronizacion(usuario_a_con_empresa["empresa_id"], sincronizacion.id)
            assert error is None

        assert sincronizacion.intentos == MAX_INTENTOS

        _, error_final = reintentar_sincronizacion(usuario_a_con_empresa["empresa_id"], sincronizacion.id)
        assert error_final is not None
        assert "máximo" in error_final.lower()


def test_reintentar_sincronizacion_aislada_entre_empresas(client, usuario_a_con_empresa, usuario_b_con_empresa, monkeypatch):
    from app.services.meta.client import MetaAPIError
    from app.services.meta.sincronizacion import iniciar_sincronizacion, reintentar_sincronizacion

    with client.application.app_context():
        _preparar_cuenta_vinculada(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])

    _mockear_get_meta(monkeypatch, {"act_123/campaigns": MetaAPIError("Interno", codigo=999999)})

    with client.application.app_context():
        sincronizacion, _ = iniciar_sincronizacion(
            usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "inicial",
            datetime.date(2026, 8, 1), datetime.date(2026, 8, 1),
        )
        sincronizacion_id = sincronizacion.id

        _, error = reintentar_sincronizacion(usuario_b_con_empresa["empresa_id"], sincronizacion_id)
        assert error is not None


# --- Presupuesto de pauta -----------------------------------------------------------

def test_crear_presupuesto_estrategico(client, usuario_a_con_empresa):
    from app.services.presupuestos import crear_presupuesto

    with client.application.app_context():
        presupuesto, error = crear_presupuesto(
            usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"],
            "Presupuesto mensual", "estrategico", 100000, moneda="CRC",
        )
        assert error is None
        assert presupuesto.tipo == "estrategico"
        assert presupuesto.entidad_id is None


def test_crear_presupuesto_monto_invalido_falla(client, usuario_a_con_empresa):
    from app.services.presupuestos import crear_presupuesto

    with client.application.app_context():
        _, error = crear_presupuesto(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "X", "estrategico", -5)
        assert error is not None


def test_crear_presupuesto_asignado_requiere_entidad_de_tipo_correcto(client, usuario_a_con_empresa):
    from app.extensions import db
    from app.models import EntidadPublicitaria
    from app.services.presupuestos import crear_presupuesto

    with client.application.app_context():
        entidad_pagina = EntidadPublicitaria(empresa_id=usuario_a_con_empresa["empresa_id"], fuente="meta", tipo="pagina", id_externo="999")
        db.session.add(entidad_pagina)
        db.session.commit()

        _, error = crear_presupuesto(
            usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"],
            "Asignado", "asignado", 5000, entidad_id=entidad_pagina.id,
        )
        assert error is not None  # una pagina no es campana ni conjunto


def test_calcular_gasto_real_suma_spend_de_metrica(client, usuario_a_con_empresa):
    from app.services.metricas import registrar_metrica
    from app.services.presupuestos import calcular_gasto_real

    with client.application.app_context():
        registrar_metrica(usuario_a_con_empresa["empresa_id"], "spend", 100.0, datetime.date(2026, 8, 1))
        registrar_metrica(usuario_a_con_empresa["empresa_id"], "spend", 50.0, datetime.date(2026, 8, 2))

        gasto = calcular_gasto_real(usuario_a_con_empresa["empresa_id"], fecha_inicio=datetime.date(2026, 8, 1), fecha_fin=datetime.date(2026, 8, 2))
        assert gasto == 150.0


def test_calcular_resumen_presupuesto_disponible_y_excedido(client, usuario_a_con_empresa):
    from app.services.metricas import registrar_metrica
    from app.services.presupuestos import calcular_resumen_presupuesto, crear_presupuesto

    with client.application.app_context():
        presupuesto, _ = crear_presupuesto(
            usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"],
            "Mensual", "estrategico", 100.0, periodo_tipo="personalizado",
            fecha_inicio=datetime.date(2026, 8, 1), fecha_fin=datetime.date(2026, 8, 31),
        )
        registrar_metrica(usuario_a_con_empresa["empresa_id"], "spend", 40.0, datetime.date(2026, 8, 5))

        resumen = calcular_resumen_presupuesto(presupuesto)
        assert resumen["gasto_real"] == 40.0
        assert resumen["disponible"] == 60.0
        assert resumen["excedido"] is False

        registrar_metrica(usuario_a_con_empresa["empresa_id"], "spend", 80.0, datetime.date(2026, 8, 6))
        resumen2 = calcular_resumen_presupuesto(presupuesto)
        assert resumen2["gasto_real"] == 120.0
        assert resumen2["excedido"] is True


def test_eliminar_presupuesto_es_soft_delete(client, usuario_a_con_empresa):
    from app.services.presupuestos import crear_presupuesto, eliminar_presupuesto, obtener_presupuesto

    with client.application.app_context():
        presupuesto, _ = crear_presupuesto(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "X", "estrategico", 100)
        ok, error = eliminar_presupuesto(usuario_a_con_empresa["empresa_id"], presupuesto.id)
        assert ok is True

        recargado = obtener_presupuesto(usuario_a_con_empresa["empresa_id"], presupuesto.id)
        assert recargado is not None  # la fila sigue existiendo
        assert recargado.activo is False


def test_presupuesto_aislado_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.presupuestos import crear_presupuesto, obtener_presupuestos_empresa

    with client.application.app_context():
        crear_presupuesto(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "De A", "estrategico", 100)

        assert len(obtener_presupuestos_empresa(usuario_a_con_empresa["empresa_id"])) == 1
        assert len(obtener_presupuestos_empresa(usuario_b_con_empresa["empresa_id"])) == 0


# --- Rutas -------------------------------------------------------------------------

def test_ruta_seleccionar_activos_sin_conexion_muestra_error(client, usuario_a_con_empresa):
    resp = client.get("/datos-meta/conexiones/seleccionar-activos")
    assert resp.status_code == 200
    assert "No se pudo" in resp.get_data(as_text=True) or "no está" in resp.get_data(as_text=True).lower() or "conexión" in resp.get_data(as_text=True).lower()


def test_ruta_vincular_activos_persiste_seleccion(client, usuario_a_con_empresa):
    from app.services.meta.conexiones import crear_conexion

    with client.application.app_context():
        crear_conexion(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "111", "A", "token-a")

    resp = client.post("/datos-meta/conexiones/vincular-activos", json={
        "seleccion": [{"tipo": "cuenta_publicitaria", "id_externo": "act_1", "nombre": "Uno", "atributos": {}}]
    })
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    from app.services.meta.cuentas_service import listar_entidades_empresa

    with client.application.app_context():
        assert len(listar_entidades_empresa(usuario_a_con_empresa["empresa_id"])) == 1


def test_ruta_sincronizar_con_periodo_invalido_da_400(client, usuario_a_con_empresa):
    from app.services.meta.conexiones import crear_conexion

    with client.application.app_context():
        crear_conexion(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "111", "A", "token-a")

    resp = client.post("/datos-meta/conexiones/sincronizar", json={"periodo": "periodo_que_no_existe"})
    assert resp.status_code == 400


def test_ruta_presupuesto_crear_y_eliminar(client, usuario_a_con_empresa):
    resp = client.post("/datos-meta/conexiones/presupuesto", json={"nombre": "Test", "tipo": "estrategico", "monto": "500"})
    assert resp.status_code == 201
    presupuesto_id = resp.get_json()["presupuesto_id"]

    resp2 = client.post(f"/datos-meta/conexiones/presupuesto/{presupuesto_id}/eliminar")
    assert resp2.status_code == 200
    assert resp2.get_json()["ok"] is True


def test_ruta_presupuesto_aislada_entre_empresas(client, usuario_a_con_empresa, usuario_b_con_empresa):
    iniciar_sesion_de_prueba(client, usuario_a_con_empresa["usuario_id"], "a@example.com")
    resp = client.post("/datos-meta/conexiones/presupuesto", json={"nombre": "De A", "tipo": "estrategico", "monto": "500"})
    presupuesto_id = resp.get_json()["presupuesto_id"]

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp2 = client.post(f"/datos-meta/conexiones/presupuesto/{presupuesto_id}/eliminar")
    assert resp2.status_code == 400
    assert resp2.get_json()["ok"] is False


def test_conexiones_muestra_conteos_de_estructura_reales(client, usuario_a_con_empresa, monkeypatch):
    from app.services.meta.sincronizacion import iniciar_sincronizacion

    with client.application.app_context():
        _preparar_cuenta_vinculada(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])

    _mockear_get_meta(monkeypatch, {
        "act_123/campaigns": {"data": [{"id": "c1", "name": "Campaña 1", "status": "ACTIVE", "effective_status": "ACTIVE"}]},
        "c1/adsets": {"data": []},
        "c1/insights": {"data": []},
    })

    with client.application.app_context():
        iniciar_sincronizacion(
            usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "inicial",
            datetime.date(2026, 8, 1), datetime.date(2026, 8, 1),
        )

    resp = client.get("/datos-meta/conexiones")
    texto = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "completada" in texto