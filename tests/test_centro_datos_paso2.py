"""Pruebas del Paso 2: Centro de Datos de Marketing.

Cubre la capa de servicio unificadora (app/services/centro_datos.py):
fuentes reconocidas (conectadas o no), Meta como unica fuente real
derivada en vivo de MetaConexion (nunca duplicada), identificacion
interna/externa, calidad del dato, ausencia honesta de ventas/CRM,
consulta por periodo, contexto para el Paso 3, aislamiento
multiempresa, y que las pantallas existentes de Datos de Meta sigan
funcionando igual.
"""

import datetime

from app.models import EntidadPublicitaria
from tests.conftest import iniciar_sesion_de_prueba


def _preparar_cuenta_vinculada(empresa_id, usuario_id):
    from app.services.meta.conexiones import crear_conexion
    from app.services.meta.cuentas_service import vincular_activos

    crear_conexion(empresa_id, usuario_id, "111", "A", "token-a")
    vincular_activos(empresa_id, [
        {"tipo": "cuenta_publicitaria", "id_externo": "act_123", "nombre": "Cuenta", "atributos": {"moneda": "USD"}},
    ])


def _crear_campana(empresa_id, id_externo, nombre="Campaña", entidad_padre_id=None):
    from app.extensions import db

    campana = EntidadPublicitaria(
        empresa_id=empresa_id, fuente="meta", tipo="campana",
        id_externo=id_externo, nombre=nombre, entidad_padre_id=entidad_padre_id,
    )
    db.session.add(campana)
    db.session.commit()
    return campana


# --- Fuentes reconocidas -----------------------------------------------------------

def test_tipos_fuente_datos_incluye_conectores_preparados_para_el_futuro():
    """Punto 11: la lista de tipos conocidos ya incluye CRM/WhatsApp/
    Ventas, aunque ninguno este implementado -- preparacion, no
    conexion ficticia."""
    from app.models import TIPOS_FUENTE_DATOS

    assert "meta" in TIPOS_FUENTE_DATOS
    assert "crm" in TIPOS_FUENTE_DATOS
    assert "whatsapp" in TIPOS_FUENTE_DATOS
    assert "ventas" in TIPOS_FUENTE_DATOS


def test_obtener_fuentes_empresa_sin_ninguna_conexion(client, usuario_a_con_empresa):
    """Punto 2: nunca se crea una conexion falsa -- sin conectar nada,
    todas las fuentes aparecen honestamente como no conectadas."""
    from app.services.centro_datos import obtener_fuentes_empresa

    with client.application.app_context():
        fuentes = obtener_fuentes_empresa(usuario_a_con_empresa["empresa_id"])
        assert len(fuentes) == 4
        assert all(f["conectada"] is False for f in fuentes)
        assert all(f["estado"] == "no_conectada" for f in fuentes)


def test_obtener_fuentes_empresa_meta_conectada_se_deriva_de_metaconexion(client, usuario_a_con_empresa):
    """Meta nunca duplica su estado en una fila aparte -- se lee en
    vivo de MetaConexion, la unica fuente de verdad."""
    from app.services.centro_datos import obtener_fuentes_empresa

    with client.application.app_context():
        _preparar_cuenta_vinculada(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])

        fuentes = obtener_fuentes_empresa(usuario_a_con_empresa["empresa_id"])
        meta = next(f for f in fuentes if f["tipo"] == "meta")
        assert meta["conectada"] is True
        assert meta["estado"] == "conectada"

        otras = [f for f in fuentes if f["tipo"] != "meta"]
        assert all(f["conectada"] is False for f in otras)


def test_obtener_fuentes_empresa_aislada_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    """Aislamiento multiempresa (punto 12): la conexion de Meta de la
    empresa A nunca aparece como conectada para la empresa B."""
    from app.services.centro_datos import obtener_fuentes_empresa

    with client.application.app_context():
        _preparar_cuenta_vinculada(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])

        fuentes_b = obtener_fuentes_empresa(usuario_b_con_empresa["empresa_id"])
        meta_b = next(f for f in fuentes_b if f["tipo"] == "meta")
        assert meta_b["conectada"] is False


def test_fuente_datos_no_conectada_para_conectores_futuros_no_crea_fila(client, usuario_a_con_empresa):
    """Punto 2: mientras CRM/WhatsApp/Ventas no tengan una conexion
    real, no debe existir ninguna fila en la tabla FuenteDatos para
    ellos -- se leen como "no_conectada" sin necesidad de persistir
    nada."""
    from app.extensions import db
    from app.models import FuenteDatos
    from app.services.centro_datos import obtener_fuentes_empresa

    with client.application.app_context():
        obtener_fuentes_empresa(usuario_a_con_empresa["empresa_id"])
        assert db.session.query(FuenteDatos).count() == 0


def test_fuente_datos_modelo_aislado_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    """Si alguna vez se crea una fila real de FuenteDatos (ej. cuando
    se implemente un conector), sigue aislada por empresa como todo lo
    demas en el proyecto."""
    from app.extensions import db
    from app.models import FuenteDatos
    from app.services.centro_datos import _fuente_datos_de_empresa

    with client.application.app_context():
        fila = FuenteDatos(empresa_id=usuario_a_con_empresa["empresa_id"], tipo="crm", estado="conectada")
        db.session.add(fila)
        db.session.commit()

        assert _fuente_datos_de_empresa(usuario_a_con_empresa["empresa_id"], "crm") is not None
        assert _fuente_datos_de_empresa(usuario_b_con_empresa["empresa_id"], "crm") is None


# --- Identificacion externa/interna -------------------------------------------------

def test_obtener_campanas_expone_id_interno_y_externo_por_separado(client, usuario_a_con_empresa):
    """Punto 4: nunca depender solo del ID de Meta -- el id interno de
    Publi Marketing y el id_externo de Meta se exponen como campos
    distintos."""
    from app.services.centro_datos import obtener_campanas

    with client.application.app_context():
        campana = _crear_campana(usuario_a_con_empresa["empresa_id"], "meta_c_999")

        campanas = obtener_campanas(usuario_a_con_empresa["empresa_id"])
        assert len(campanas) == 1
        assert campanas[0]["id_interno"] == campana.id
        assert campanas[0]["id_externo"] == "meta_c_999"
        assert campanas[0]["id_interno"] != campanas[0]["id_externo"]
        assert campanas[0]["fuente"] == "meta"


# --- Servicios normalizados y calidad del dato ---------------------------------------

def test_obtener_resultados_delega_en_kpi_sin_recalcular(client, usuario_a_con_empresa):
    """Punto 9/13: obtener_resultados() debe dar EXACTAMENTE lo mismo
    que calcular_kpis() ya calculado -- nunca un segundo motor."""
    from app.services.centro_datos import CONFIANZA_SINCRONIZADO, obtener_resultados
    from app.services.meta.kpi import calcular_kpis
    from app.services.metricas import registrar_metrica

    with client.application.app_context():
        campana = _crear_campana(usuario_a_con_empresa["empresa_id"], "c1")
        registrar_metrica(usuario_a_con_empresa["empresa_id"], "spend", 50.0, datetime.date(2026, 8, 1), entidad_id=campana.id, entidad_tipo="campana")

        directo = calcular_kpis(usuario_a_con_empresa["empresa_id"], [campana.id], datetime.date(2026, 8, 1), datetime.date(2026, 8, 1))
        resultado, error = obtener_resultados(usuario_a_con_empresa["empresa_id"], campana.id, datetime.date(2026, 8, 1), datetime.date(2026, 8, 1))

        assert error is None
        assert resultado["kpis"] == directo
        assert resultado["confianza"] == CONFIANZA_SINCRONIZADO
        assert resultado["fuente"] == "meta"


def test_obtener_resultados_periodo_sin_datos_confianza_no_disponible(client, usuario_a_con_empresa):
    """Consulta por periodo (punto 6) sin ninguna fila sincronizada
    para esas fechas: se marca honestamente no_disponible, no se
    inventa un cero."""
    from app.services.centro_datos import CONFIANZA_NO_DISPONIBLE, obtener_resultados

    with client.application.app_context():
        campana = _crear_campana(usuario_a_con_empresa["empresa_id"], "c1")

        resultado, error = obtener_resultados(usuario_a_con_empresa["empresa_id"], campana.id, datetime.date(2026, 8, 1), datetime.date(2026, 8, 1))
        assert error is None
        assert resultado["confianza"] == CONFIANZA_NO_DISPONIBLE
        assert resultado["kpis"]["spend"] is None


def test_obtener_resultados_roas_real_nunca_se_confunde_con_el_reportado(client, usuario_a_con_empresa):
    """Punto 15: ROAS reportado por Meta (atribucion propia de Meta)
    nunca se presenta como si fuera el ROAS real del negocio -- ese
    campo queda en None con una razon explicita, jamas calculado."""
    from app.services.centro_datos import obtener_resultados
    from app.services.metricas import registrar_metrica

    with client.application.app_context():
        campana = _crear_campana(usuario_a_con_empresa["empresa_id"], "c1")
        registrar_metrica(usuario_a_con_empresa["empresa_id"], "spend", 100.0, datetime.date(2026, 8, 1), entidad_id=campana.id, entidad_tipo="campana")
        registrar_metrica(usuario_a_con_empresa["empresa_id"], "valor_conversion", 400.0, datetime.date(2026, 8, 1), entidad_id=campana.id, entidad_tipo="campana")

        resultado, error = obtener_resultados(usuario_a_con_empresa["empresa_id"], campana.id, datetime.date(2026, 8, 1), datetime.date(2026, 8, 1))
        assert error is None
        assert resultado["roas_reportado"] == 4.0
        assert resultado["roas_real"] is None
        assert "ventas" in resultado["roas_real_razon"].lower()


def test_obtener_conversiones_nunca_se_llama_ventas(client, usuario_a_con_empresa):
    """Punto 15/19: obtener_conversiones() son conversiones REPORTADAS
    por Meta, con una nota explicita de que no son ventas verificadas."""
    from app.services.centro_datos import obtener_conversiones
    from app.services.metricas import registrar_metrica

    with client.application.app_context():
        campana = _crear_campana(usuario_a_con_empresa["empresa_id"], "c1")
        registrar_metrica(usuario_a_con_empresa["empresa_id"], "conversiones", 5.0, datetime.date(2026, 8, 1), entidad_id=campana.id, entidad_tipo="campana")

        resultado, error = obtener_conversiones(usuario_a_con_empresa["empresa_id"], campana.id, datetime.date(2026, 8, 1), datetime.date(2026, 8, 1))
        assert error is None
        assert resultado["conversiones_reportadas"] == 5.0
        assert "no" in resultado["nota"].lower()


def test_obtener_ventas_reales_siempre_no_disponible(client, usuario_a_con_empresa):
    """Punto 19: nunca se inventan ventas ni ingresos reales -- sin
    ninguna fuente de ventas conectada, es SIEMPRE no_disponible."""
    from app.services.centro_datos import CONFIANZA_NO_DISPONIBLE, obtener_ventas_reales

    with client.application.app_context():
        resultado = obtener_ventas_reales(usuario_a_con_empresa["empresa_id"])
        assert resultado["confianza"] == CONFIANZA_NO_DISPONIBLE
        assert resultado["valor"] is None
        assert resultado["razon"]


# --- Contexto para el Paso 3 (Inteligencia con Claude) -------------------------------

def test_construir_contexto_marketing_reutiliza_centro_control(client, usuario_a_con_empresa):
    """Punto 16: el contexto preparado para Claude reutiliza el motor
    del Centro de Control (Paso 14) en vez de recalcular un segundo
    resumen -- e incluye honestamente que no hay ventas reales."""
    from app.services.centro_datos import obtener_ventas_reales
    from app.services.meta.centro_control import construir_centro_control

    with client.application.app_context():
        _preparar_cuenta_vinculada(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])
        from app.services.meta.cuentas_service import listar_entidades_empresa
        cuenta = listar_entidades_empresa(usuario_a_con_empresa["empresa_id"], tipo="cuenta_publicitaria")[0]

        from app.services.centro_datos import construir_contexto_marketing

        contexto, error = construir_contexto_marketing(
            usuario_a_con_empresa["empresa_id"], cuenta.id, datetime.date(2026, 8, 1), datetime.date(2026, 8, 1),
        )
        directo, _ = construir_centro_control(
            usuario_a_con_empresa["empresa_id"], cuenta.id, datetime.date(2026, 8, 1), datetime.date(2026, 8, 1),
        )

        assert error is None
        assert contexto["kpis"] == directo["kpis"]
        assert contexto["alertas"] == directo["alertas"]
        assert contexto["ventas_reales"] == obtener_ventas_reales(usuario_a_con_empresa["empresa_id"])
        assert any(f["tipo"] == "meta" and f["conectada"] for f in contexto["fuentes"])


def test_construir_contexto_marketing_aislado_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    """El contexto de una cuenta de la empresa A nunca debe poder
    construirse pasando el empresa_id de B."""
    from app.services.centro_datos import construir_contexto_marketing

    with client.application.app_context():
        _preparar_cuenta_vinculada(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])
        from app.services.meta.cuentas_service import listar_entidades_empresa
        cuenta_a = listar_entidades_empresa(usuario_a_con_empresa["empresa_id"], tipo="cuenta_publicitaria")[0]

        contexto, error = construir_contexto_marketing(
            usuario_b_con_empresa["empresa_id"], cuenta_a.id, datetime.date(2026, 8, 1), datetime.date(2026, 8, 1),
        )
        assert contexto is None
        assert error is not None


# --- Compatibilidad con Datos de Meta existente ---------------------------------------

def test_pantalla_conexiones_sigue_funcionando_y_muestra_fuentes(client, usuario_a_con_empresa):
    """Punto 10/18: la pantalla de Conexiones de Datos de Meta sigue
    funcionando igual, y ahora ademas muestra el bloque informativo de
    fuentes conectadas del Centro de Datos."""
    with client.application.app_context():
        _preparar_cuenta_vinculada(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])

    resp = client.get("/datos-meta/conexiones")
    assert resp.status_code == 200
    texto = resp.get_data(as_text=True)
    assert "Fuentes conectadas" in texto
    assert "Meta" in texto
    assert "CRM" in texto
