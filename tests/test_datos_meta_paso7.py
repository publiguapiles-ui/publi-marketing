"""Pruebas del Paso 7: planificador estrategico de pauta.

Cubre exclusivamente lo nuevo de este paso -- creacion de proyectos,
reglas de presupuesto (la suma de fases nunca supera el total, sin
porcentajes hardcodeados), fechas, KPI/objetivo, estados (borrador/plan
aprobado), advertencia de distribucion, analisis historico (reutiliza
kpi.py y analisis.py, nunca inventa datos cuando no hay historial) y
aislamiento multiempresa. El motor de KPI en si ya esta probado en
test_datos_meta_paso3.py -- aqui nunca se reimplementa ese calculo.
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


def _crear_campana(empresa_id, id_externo, entidad_padre_id):
    from app.extensions import db

    campana = EntidadPublicitaria(
        empresa_id=empresa_id, fuente="meta", tipo="campana", id_externo=id_externo,
        nombre=f"Campaña {id_externo}", entidad_padre_id=entidad_padre_id, estado="ACTIVE",
        atributos={"objetivo": "OUTCOME_SALES"},
    )
    db.session.add(campana)
    db.session.commit()
    return campana


def _registrar(empresa_id, entidad_id, entidad_tipo, metrica, valor, fecha):
    from app.services.metricas import registrar_metrica

    registrar_metrica(empresa_id, metrica, valor, fecha, entidad_id=entidad_id, entidad_tipo=entidad_tipo)


def _datos_proyecto(**overrides):
    datos = {
        "nombre": "Captación de nuevos clientes",
        "objetivo": "conversiones",
        "kpi_principal": "costo_por_resultado",
        "presupuesto_total": 100000,
        "moneda": "CRC",
        "fecha_inicio": datetime.date(2026, 9, 1),
        "fecha_fin": datetime.date(2026, 9, 30),
        "resultado_objetivo": "50 conversiones",
    }
    datos.update(overrides)
    return datos


# --- Creacion de proyecto: campos obligatorios y validaciones -------------------------

def test_crear_proyecto_exitoso(client, usuario_a_con_empresa):
    from app.services.meta.planificador import crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, error = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        assert error is None
        assert proyecto.id is not None
        assert proyecto.estado == "borrador"
        assert proyecto.presupuesto_total == 100000


def test_crear_proyecto_requiere_nombre(client, usuario_a_con_empresa):
    from app.services.meta.planificador import crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, error = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto(nombre=""))
        assert proyecto is None
        assert "nombre" in error.lower()


def test_crear_proyecto_requiere_kpi_valido(client, usuario_a_con_empresa):
    from app.services.meta.planificador import crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, error = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto(kpi_principal="no_existe"))
        assert proyecto is None
        assert "kpi" in error.lower()


def test_crear_proyecto_presupuesto_debe_ser_positivo(client, usuario_a_con_empresa):
    from app.services.meta.planificador import crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, error = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto(presupuesto_total=0))
        assert proyecto is None
        assert "presupuesto" in error.lower()


def test_crear_proyecto_fecha_fin_antes_de_inicio_falla(client, usuario_a_con_empresa):
    from app.services.meta.planificador import crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, error = crear_proyecto(
            empresa_id, usuario_a_con_empresa["usuario_id"],
            _datos_proyecto(fecha_inicio=datetime.date(2026, 9, 30), fecha_fin=datetime.date(2026, 9, 1)),
        )
        assert proyecto is None
        assert "fecha" in error.lower()


def test_crear_proyecto_cuenta_de_otra_empresa_rechazada(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.meta.planificador import crear_proyecto

    with client.application.app_context():
        cuenta_b = _crear_cuenta(usuario_b_con_empresa["empresa_id"])
        proyecto, error = crear_proyecto(
            usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"],
            _datos_proyecto(cuenta_publicitaria_id=cuenta_b.id),
        )
        assert proyecto is None
        assert "empresa" in error.lower()


# --- Presupuesto y fases: la suma nunca supera el total, sin porcentajes fijos --------

def test_agregar_etapa_exitosa_no_hardcodea_porcentaje(client, usuario_a_con_empresa):
    """El presupuesto de la fase es EXACTAMENTE el que el usuario
    definio -- el sistema nunca le impone un porcentaje calculado."""
    from app.services.meta.planificador import agregar_etapa, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto(presupuesto_total=100000))

        etapa, error = agregar_etapa(empresa_id, proyecto.id, {"nombre": "Reconocimiento", "presupuesto": 37500})
        assert error is None
        assert etapa.presupuesto == 37500  # exactamente lo pedido, no un 25%/33% impuesto


def test_suma_de_fases_no_puede_superar_presupuesto_total(client, usuario_a_con_empresa):
    from app.services.meta.planificador import agregar_etapa, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto(presupuesto_total=100000))

        etapa1, error1 = agregar_etapa(empresa_id, proyecto.id, {"nombre": "Fase 1", "presupuesto": 70000})
        assert error1 is None

        etapa2, error2 = agregar_etapa(empresa_id, proyecto.id, {"nombre": "Fase 2", "presupuesto": 40000})
        assert etapa2 is None
        assert "presupuesto total" in error2.lower()


def test_resumen_presupuesto_calcula_asignado_disponible_y_porcentaje(client, usuario_a_con_empresa):
    from app.services.meta.planificador import agregar_etapa, crear_proyecto, resumen_presupuesto_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto(presupuesto_total=100000))
        agregar_etapa(empresa_id, proyecto.id, {"nombre": "Fase 1", "presupuesto": 30000})

        from app.extensions import db
        db.session.refresh(proyecto)

        resumen = resumen_presupuesto_proyecto(proyecto)
        assert resumen["presupuesto_total"] == 100000
        assert resumen["asignado"] == 30000
        assert resumen["disponible"] == 70000
        assert resumen["porcentaje_asignado"] == 30.0


def test_eliminar_etapa_libera_presupuesto(client, usuario_a_con_empresa):
    from app.services.meta.planificador import agregar_etapa, crear_proyecto, eliminar_etapa, resumen_presupuesto_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto(presupuesto_total=100000))
        etapa, _ = agregar_etapa(empresa_id, proyecto.id, {"nombre": "Fase 1", "presupuesto": 90000})

        ok, error = eliminar_etapa(empresa_id, proyecto.id, etapa.id)
        assert ok is True
        assert error is None

        from app.extensions import db
        db.session.refresh(proyecto)
        resumen = resumen_presupuesto_proyecto(proyecto)
        assert resumen["asignado"] == 0


def test_agregar_etapa_presupuesto_debe_ser_positivo(client, usuario_a_con_empresa):
    from app.services.meta.planificador import agregar_etapa, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        etapa, error = agregar_etapa(empresa_id, proyecto.id, {"nombre": "Fase 1", "presupuesto": -10})
        assert etapa is None
        assert "presupuesto" in error.lower()


def test_advertencia_distribucion_cuando_gasto_diario_es_muy_bajo(client, usuario_a_con_empresa):
    """Verificacion real del ejemplo del enunciado: presupuesto
    pequeño repartido en varias fases con gasto diario por debajo del
    umbral documentado (CRC) genera la advertencia."""
    from app.services.meta.planificador import agregar_etapa, construir_paquete_planificador, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto(presupuesto_total=8000))
        agregar_etapa(empresa_id, proyecto.id, {"nombre": "Fase 1", "presupuesto": 4000, "duracion_dias": 30})
        agregar_etapa(empresa_id, proyecto.id, {"nombre": "Fase 2", "presupuesto": 4000, "duracion_dias": 30})

        from app.extensions import db
        db.session.refresh(proyecto)

        paquete = construir_paquete_planificador(proyecto)
        assert paquete["advertencia_distribucion"] is not None
        assert "concentrar la inversión" in paquete["advertencia_distribucion"]


def test_sin_advertencia_cuando_el_gasto_diario_es_suficiente(client, usuario_a_con_empresa):
    from app.services.meta.planificador import agregar_etapa, construir_paquete_planificador, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto(presupuesto_total=600000))
        agregar_etapa(empresa_id, proyecto.id, {"nombre": "Fase 1", "presupuesto": 300000, "duracion_dias": 30})
        agregar_etapa(empresa_id, proyecto.id, {"nombre": "Fase 2", "presupuesto": 300000, "duracion_dias": 30})

        from app.extensions import db
        db.session.refresh(proyecto)

        paquete = construir_paquete_planificador(proyecto)
        assert paquete["advertencia_distribucion"] is None


# --- Estados: borrador <-> plan aprobado -----------------------------------------------

def test_cambiar_estado_a_plan_aprobado(client, usuario_a_con_empresa):
    from app.services.meta.planificador import cambiar_estado_proyecto, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        assert proyecto.estado == "borrador"

        actualizado, error = cambiar_estado_proyecto(empresa_id, proyecto.id, "plan_aprobado")
        assert error is None
        assert actualizado.estado == "plan_aprobado"


def test_cambiar_estado_invalido_rechazado(client, usuario_a_con_empresa):
    from app.services.meta.planificador import cambiar_estado_proyecto, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        actualizado, error = cambiar_estado_proyecto(empresa_id, proyecto.id, "ejecutando_en_meta")
        assert actualizado is None
        assert error is not None


# --- Analisis historico: nunca inventa datos que no existen ---------------------------

def test_analisis_historico_sin_cuenta_indica_datos_insuficientes(client, usuario_a_con_empresa):
    from app.services.meta.planificador import construir_analisis_historico

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        resultado = construir_analisis_historico(empresa_id, None, datetime.date(2026, 8, 1), datetime.date(2026, 8, 30))
        assert resultado["datos_suficientes"] is False
        assert resultado["campanas"] == []


def test_analisis_historico_sin_campanas_sincronizadas_indica_datos_insuficientes(client, usuario_a_con_empresa):
    from app.services.meta.planificador import construir_analisis_historico

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        resultado = construir_analisis_historico(empresa_id, cuenta.id, datetime.date(2026, 8, 1), datetime.date(2026, 8, 30))
        assert resultado["datos_suficientes"] is False
        assert "no existe información histórica suficiente" in resultado["mensaje"].lower()


def test_analisis_historico_con_datos_reales_los_reutiliza_sin_recalcular(client, usuario_a_con_empresa):
    """No debe inventar ni recalcular KPI -- los numeros deben coincidir
    exactamente con lo que kpi.py ya calcula (Paso 3), solo se reutiliza."""
    from app.services.meta.planificador import construir_analisis_historico

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        fecha = datetime.date(2026, 8, 5)
        _registrar(empresa_id, campana.id, "campana", "spend", 500.0, fecha)
        _registrar(empresa_id, campana.id, "campana", "conversiones", 10.0, fecha)

        resultado = construir_analisis_historico(empresa_id, cuenta.id, datetime.date(2026, 8, 1), datetime.date(2026, 8, 30))
        assert resultado["datos_suficientes"] is True
        assert len(resultado["campanas"]) == 1
        assert resultado["campanas"][0]["kpis"]["spend"] == 500.0
        assert resultado["campanas"][0]["kpis"]["costo_por_resultado"] == 50.0
        assert resultado["mejor_dia"]["fecha"] == fecha


# --- Multiempresa: aislamiento total ---------------------------------------------------

def test_obtener_proyecto_aislado_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.meta.planificador import crear_proyecto, obtener_proyecto

    with client.application.app_context():
        proyecto, _ = crear_proyecto(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        assert obtener_proyecto(usuario_b_con_empresa["empresa_id"], proyecto.id) is None


def test_listar_proyectos_aislado_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.meta.planificador import crear_proyecto, listar_proyectos_empresa

    with client.application.app_context():
        crear_proyecto(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        assert listar_proyectos_empresa(usuario_b_con_empresa["empresa_id"]) == []


def test_agregar_etapa_a_proyecto_de_otra_empresa_rechazado(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.meta.planificador import agregar_etapa, crear_proyecto

    with client.application.app_context():
        proyecto, _ = crear_proyecto(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        etapa, error = agregar_etapa(usuario_b_con_empresa["empresa_id"], proyecto.id, {"nombre": "Fase 1", "presupuesto": 1000})
        assert etapa is None
        assert "empresa" in error.lower()


def test_ruta_planificador_lista_aislada_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.meta.planificador import crear_proyecto

    with client.application.app_context():
        crear_proyecto(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], _datos_proyecto(nombre="Proyecto de A"))

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp = client.get("/datos-meta/planificador")
    assert resp.status_code == 200
    assert "Proyecto de A" not in resp.get_data(as_text=True)


def test_ruta_planificador_detalle_de_otra_empresa_da_404(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.meta.planificador import crear_proyecto

    with client.application.app_context():
        proyecto, _ = crear_proyecto(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        proyecto_id = proyecto.id

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp = client.get(f"/datos-meta/planificador/{proyecto_id}")
    assert resp.status_code == 404


# --- Ruta completa: creacion end-to-end (Paso 7, "DONE WHEN") --------------------------

def test_ruta_crear_proyecto_end_to_end(client, usuario_a_con_empresa):
    """'Panadería Bendetto — ₡100.000 — 30 días — conversiones', tal
    como lo pide el enunciado como criterio de exito."""
    resp = client.post(
        "/datos-meta/planificador/crear",
        json={
            "nombre": "Captación de clientes",
            "objetivo": "conversiones",
            "kpi_principal": "costo_por_resultado",
            "presupuesto_total": 100000,
            "moneda": "CRC",
            "fecha_inicio": "2026-09-01",
            "fecha_fin": "2026-10-01",
            "resultado_objetivo": "50 conversiones",
        },
    )
    assert resp.status_code == 201
    datos = resp.get_json()
    assert datos["ok"] is True

    resp_detalle = client.get(f"/datos-meta/planificador/{datos['proyecto_id']}")
    assert resp_detalle.status_code == 200
    texto = resp_detalle.get_data(as_text=True)
    assert "Captación de clientes" in texto
    assert "Borrador" in texto
