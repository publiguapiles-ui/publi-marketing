"""Pruebas del Paso 9: proyectos estrategicos de campaña.

Cubre exclusivamente lo nuevo de este paso -- creacion de proyecto,
reglas de presupuesto por fase (la suma nunca supera el total, sin
porcentajes hardcodeados), fechas, KPI/objetivo, audiencias reales vs.
planeadas, secuencia, estados (los 6 del Paso 9), diagnostico
(reutiliza inteligencia.py del Paso 8 sin recalcular nada), seguimiento
planificado vs. real (correctamente acotado a la cuenta publicitaria
del proyecto) y aislamiento multiempresa. El motor de KPI y el de
inteligencia YA estan probados en test_datos_meta_paso3.py y
test_datos_meta_paso8.py -- aqui nunca se reimplementa ese calculo.
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


def _crear_conjunto(empresa_id, id_externo, campana_id, nombre=None):
    from app.extensions import db

    conjunto = EntidadPublicitaria(
        empresa_id=empresa_id, fuente="meta", tipo="conjunto_anuncios", id_externo=id_externo,
        nombre=nombre or f"Conjunto {id_externo}", entidad_padre_id=campana_id, estado="ACTIVE",
    )
    db.session.add(conjunto)
    db.session.commit()
    return conjunto


def _registrar(empresa_id, entidad_id, entidad_tipo, metrica, valor, fecha):
    from app.services.metricas import registrar_metrica

    registrar_metrica(empresa_id, metrica, valor, fecha, entidad_id=entidad_id, entidad_tipo=entidad_tipo)


def _datos_proyecto(**overrides):
    datos = {
        "nombre": "Captación de nuevos clientes",
        "objetivo": "conversiones",
        "kpi_principal": "costo_por_resultado",
        "kpi_secundarios": ["ctr", "cpc"],
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
    from app.services.meta.proyectos_estrategicos import crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, error = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        assert error is None
        assert proyecto.id is not None
        assert proyecto.estado == "borrador"
        assert proyecto.presupuesto_total == 100000
        assert proyecto.kpi_secundarios == ["ctr", "cpc"]


def test_crear_proyecto_requiere_nombre(client, usuario_a_con_empresa):
    from app.services.meta.proyectos_estrategicos import crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, error = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto(nombre=""))
        assert proyecto is None
        assert "nombre" in error.lower()


def test_crear_proyecto_requiere_kpi_principal_valido(client, usuario_a_con_empresa):
    from app.services.meta.proyectos_estrategicos import crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, error = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto(kpi_principal="no_existe"))
        assert proyecto is None
        assert "kpi" in error.lower()


def test_crear_proyecto_kpi_secundarios_invalidos_rechazado(client, usuario_a_con_empresa):
    from app.services.meta.proyectos_estrategicos import crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, error = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto(kpi_secundarios=["no_existe"]))
        assert proyecto is None
        assert "kpi" in error.lower()


def test_crear_proyecto_presupuesto_debe_ser_positivo(client, usuario_a_con_empresa):
    from app.services.meta.proyectos_estrategicos import crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, error = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto(presupuesto_total=0))
        assert proyecto is None
        assert "presupuesto" in error.lower()


def test_crear_proyecto_fecha_fin_antes_de_inicio_falla(client, usuario_a_con_empresa):
    from app.services.meta.proyectos_estrategicos import crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, error = crear_proyecto(
            empresa_id, usuario_a_con_empresa["usuario_id"],
            _datos_proyecto(fecha_inicio=datetime.date(2026, 9, 30), fecha_fin=datetime.date(2026, 9, 1)),
        )
        assert proyecto is None
        assert "fecha" in error.lower()


def test_crear_proyecto_cuenta_de_otra_empresa_rechazada(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.meta.proyectos_estrategicos import crear_proyecto

    with client.application.app_context():
        cuenta_b = _crear_cuenta(usuario_b_con_empresa["empresa_id"])
        proyecto, error = crear_proyecto(
            usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"],
            _datos_proyecto(cuenta_publicitaria_id=cuenta_b.id),
        )
        assert proyecto is None
        assert "empresa" in error.lower()


# --- Fases: presupuesto nunca supera el total, sin porcentajes fijos ------------------

def test_agregar_fase_exitosa_no_hardcodea_porcentaje(client, usuario_a_con_empresa):
    from app.services.meta.proyectos_estrategicos import agregar_fase, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto(presupuesto_total=100000))

        fase, error = agregar_fase(empresa_id, proyecto.id, {"nombre": "Reconocimiento", "presupuesto": 37500})
        assert error is None
        assert fase.presupuesto == 37500  # exactamente lo pedido, no un 25%/33% impuesto


def test_suma_de_fases_no_puede_superar_presupuesto_total(client, usuario_a_con_empresa):
    from app.services.meta.proyectos_estrategicos import agregar_fase, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto(presupuesto_total=100000))

        fase1, error1 = agregar_fase(empresa_id, proyecto.id, {"nombre": "Fase 1", "presupuesto": 70000})
        assert error1 is None

        fase2, error2 = agregar_fase(empresa_id, proyecto.id, {"nombre": "Fase 2", "presupuesto": 40000})
        assert fase2 is None
        assert "presupuesto total" in error2.lower()


def test_agregar_fase_presupuesto_debe_ser_positivo(client, usuario_a_con_empresa):
    from app.services.meta.proyectos_estrategicos import agregar_fase, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        fase, error = agregar_fase(empresa_id, proyecto.id, {"nombre": "Fase 1", "presupuesto": -10})
        assert fase is None
        assert "presupuesto" in error.lower()


def test_agregar_fase_fecha_fin_antes_de_inicio_falla(client, usuario_a_con_empresa):
    from app.services.meta.proyectos_estrategicos import agregar_fase, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        fase, error = agregar_fase(empresa_id, proyecto.id, {
            "nombre": "Fase 1", "presupuesto": 1000,
            "fecha_inicio": datetime.date(2026, 9, 10), "fecha_fin": datetime.date(2026, 9, 1),
        })
        assert fase is None
        assert "fecha" in error.lower()


def test_agregar_fase_kpi_esperado_invalido_rechazado(client, usuario_a_con_empresa):
    from app.services.meta.proyectos_estrategicos import agregar_fase, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        fase, error = agregar_fase(empresa_id, proyecto.id, {"nombre": "Fase 1", "presupuesto": 1000, "kpi_esperado": "no_existe"})
        assert fase is None
        assert "kpi" in error.lower()


def test_agregar_fase_con_audiencia_real_la_vincula(client, usuario_a_con_empresa):
    """Si el usuario elige un conjunto de anuncios YA sincronizado, la
    fase queda vinculada a una audiencia REAL de Meta (Paso 9, punto 5)."""
    from app.services.meta.proyectos_estrategicos import agregar_fase, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        conjunto = _crear_conjunto(empresa_id, "cj1", campana.id, nombre="Interactuaron 90 días")

        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto(cuenta_publicitaria_id=cuenta.id))
        fase, error = agregar_fase(empresa_id, proyecto.id, {"nombre": "Fase 1", "presupuesto": 1000, "audiencia_entidad_id": conjunto.id})
        assert error is None
        assert fase.audiencia_entidad_id == conjunto.id


def test_agregar_fase_con_audiencia_de_otra_empresa_rechazada(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.meta.proyectos_estrategicos import agregar_fase, crear_proyecto

    with client.application.app_context():
        cuenta_b = _crear_cuenta(usuario_b_con_empresa["empresa_id"])
        campana_b = _crear_campana(usuario_b_con_empresa["empresa_id"], "c1", cuenta_b.id)
        conjunto_b = _crear_conjunto(usuario_b_con_empresa["empresa_id"], "cj1", campana_b.id)

        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        fase, error = agregar_fase(empresa_id, proyecto.id, {"nombre": "Fase 1", "presupuesto": 1000, "audiencia_entidad_id": conjunto_b.id})
        assert fase is None
        assert "audiencia" in error.lower()


def test_agregar_fase_sin_audiencia_real_queda_solo_planeada(client, usuario_a_con_empresa):
    from app.services.meta.proyectos_estrategicos import agregar_fase, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        fase, error = agregar_fase(empresa_id, proyecto.id, {
            "nombre": "Fase 1", "presupuesto": 1000, "audiencia_tipo": "publico_frio",
            "audiencia_descripcion": "Público frío de la zona metropolitana",
        })
        assert error is None
        assert fase.audiencia_entidad_id is None  # nunca se inventa un vinculo con Meta


def test_resumen_presupuesto_calcula_asignado_disponible_y_porcentaje(client, usuario_a_con_empresa):
    from app.services.meta.proyectos_estrategicos import agregar_fase, crear_proyecto, resumen_presupuesto_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto(presupuesto_total=100000))
        agregar_fase(empresa_id, proyecto.id, {"nombre": "Fase 1", "presupuesto": 30000})

        from app.extensions import db
        db.session.refresh(proyecto)

        resumen = resumen_presupuesto_proyecto(proyecto)
        assert resumen["presupuesto_total"] == 100000
        assert resumen["asignado"] == 30000
        assert resumen["disponible"] == 70000
        assert resumen["porcentaje_asignado"] == 30.0


def test_eliminar_fase_libera_presupuesto(client, usuario_a_con_empresa):
    from app.services.meta.proyectos_estrategicos import agregar_fase, crear_proyecto, eliminar_fase, resumen_presupuesto_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto(presupuesto_total=100000))
        fase, _ = agregar_fase(empresa_id, proyecto.id, {"nombre": "Fase 1", "presupuesto": 90000})

        ok, error = eliminar_fase(empresa_id, proyecto.id, fase.id)
        assert ok is True
        assert error is None

        from app.extensions import db
        db.session.refresh(proyecto)
        assert resumen_presupuesto_proyecto(proyecto)["asignado"] == 0


# --- Secuencia estrategica -----------------------------------------------------------

def test_agregar_paso_secuencia_exitoso(client, usuario_a_con_empresa):
    from app.services.meta.proyectos_estrategicos import agregar_paso_secuencia, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        paso, error = agregar_paso_secuencia(empresa_id, proyecto.id, {
            "contenido": "VIDEO 1", "audiencia_descripcion": "Público frío", "objetivo": "Reconocimiento",
            "duracion_dias": 7, "kpi": "ctr",
        })
        assert error is None
        assert paso.orden == 0

        paso2, error2 = agregar_paso_secuencia(empresa_id, proyecto.id, {"contenido": "VIDEO 2"})
        assert error2 is None
        assert paso2.orden == 1


def test_agregar_paso_secuencia_requiere_contenido(client, usuario_a_con_empresa):
    from app.services.meta.proyectos_estrategicos import agregar_paso_secuencia, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        paso, error = agregar_paso_secuencia(empresa_id, proyecto.id, {"contenido": ""})
        assert paso is None
        assert "contenido" in error.lower()


def test_agregar_paso_secuencia_kpi_invalido_rechazado(client, usuario_a_con_empresa):
    from app.services.meta.proyectos_estrategicos import agregar_paso_secuencia, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        paso, error = agregar_paso_secuencia(empresa_id, proyecto.id, {"contenido": "VIDEO 1", "kpi": "no_existe"})
        assert paso is None
        assert "kpi" in error.lower()


def test_eliminar_paso_secuencia(client, usuario_a_con_empresa):
    from app.services.meta.proyectos_estrategicos import agregar_paso_secuencia, crear_proyecto, eliminar_paso_secuencia

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        paso, _ = agregar_paso_secuencia(empresa_id, proyecto.id, {"contenido": "VIDEO 1"})

        ok, error = eliminar_paso_secuencia(empresa_id, proyecto.id, paso.id)
        assert ok is True
        assert error is None


# --- Estados: los 6 del Paso 9 ---------------------------------------------------------

def test_cambiar_estado_recorre_todos_los_estados(client, usuario_a_con_empresa):
    from app.services.meta.proyectos_estrategicos import cambiar_estado_proyecto, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        assert proyecto.estado == "borrador"

        # "en_revision" (Paso 3: Inteligencia de Marketing) se suma a
        # los seis estados originales del Paso 9.
        for estado in ["planificado", "aprobado", "en_ejecucion", "en_revision", "pausado", "finalizado"]:
            actualizado, error = cambiar_estado_proyecto(empresa_id, proyecto.id, estado)
            assert error is None
            assert actualizado.estado == estado


def test_cambiar_estado_invalido_rechazado(client, usuario_a_con_empresa):
    from app.services.meta.proyectos_estrategicos import cambiar_estado_proyecto, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        actualizado, error = cambiar_estado_proyecto(empresa_id, proyecto.id, "ejecutando_en_meta")
        assert actualizado is None
        assert error is not None


# --- Diagnostico: reutiliza inteligencia.py, nunca recalcula ---------------------------

def test_diagnostico_sin_cuenta_indica_que_falta_vincular(client, usuario_a_con_empresa):
    from app.services.meta.proyectos_estrategicos import construir_diagnostico_proyecto, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        diagnostico, error = construir_diagnostico_proyecto(proyecto)
        assert diagnostico is None
        assert "cuenta" in error.lower()


def test_diagnostico_con_cuenta_reutiliza_inteligencia(client, usuario_a_con_empresa):
    from app.services.meta.proyectos_estrategicos import construir_diagnostico_proyecto, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        _registrar(empresa_id, campana.id, "campana", "spend", 100.0, datetime.date(2026, 8, 1))

        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto(cuenta_publicitaria_id=cuenta.id))
        diagnostico, error = construir_diagnostico_proyecto(proyecto, datetime.date(2026, 8, 1), datetime.date(2026, 8, 10))
        assert error is None
        # Misma forma exacta que construir_inteligencia() del Paso 8 -- no se recalcula nada.
        for clave in ("diagnostico", "campanas", "audiencias", "creativos", "presupuesto", "oportunidades", "alertas"):
            assert clave in diagnostico


# --- Seguimiento: planificado vs. real, acotado a la cuenta del proyecto ----------------

def test_seguimiento_sin_cuenta_vinculada_es_honesto(client, usuario_a_con_empresa):
    from app.services.meta.proyectos_estrategicos import construir_seguimiento, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        seguimiento = construir_seguimiento(proyecto)
        assert seguimiento["tiene_cuenta_vinculada"] is False
        assert seguimiento["presupuesto"]["real"] is None
        assert seguimiento["kpi_principal"]["valor_real"] is None


def test_seguimiento_gasto_real_acotado_a_la_cuenta_del_proyecto(client, usuario_a_con_empresa):
    """Bug real detectado y corregido durante el desarrollo: el gasto
    real NUNCA debe sumar el de otra cuenta publicitaria de la misma
    empresa, solo el de la cuenta vinculada a este proyecto."""
    from app.services.meta.proyectos_estrategicos import construir_seguimiento, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta_proyecto = _crear_cuenta(empresa_id, id_externo="act_1")
        cuenta_otra = _crear_cuenta(empresa_id, id_externo="act_2")
        campana_proyecto = _crear_campana(empresa_id, "c1", cuenta_proyecto.id)
        campana_otra = _crear_campana(empresa_id, "c2", cuenta_otra.id)

        fecha = datetime.date(2026, 9, 5)
        _registrar(empresa_id, campana_proyecto.id, "campana", "spend", 1000.0, fecha)
        _registrar(empresa_id, campana_proyecto.id, "campana", "conversiones", 10.0, fecha)
        _registrar(empresa_id, campana_otra.id, "campana", "spend", 99999.0, fecha)  # NO debe contarse

        proyecto, _ = crear_proyecto(
            empresa_id, usuario_a_con_empresa["usuario_id"],
            _datos_proyecto(cuenta_publicitaria_id=cuenta_proyecto.id, fecha_inicio=fecha, fecha_fin=fecha),
        )
        seguimiento = construir_seguimiento(proyecto)
        assert seguimiento["tiene_cuenta_vinculada"] is True
        assert seguimiento["presupuesto"]["real"] == 1000.0
        assert seguimiento["kpi_principal"]["valor_real"] == 100.0  # costo_por_resultado = 1000/10


# --- Informe estructurado (punto 11) ----------------------------------------------------

def test_informe_estructurado_incluye_todas_las_secciones(client, usuario_a_con_empresa):
    from app.services.meta.proyectos_estrategicos import (
        agregar_fase, agregar_paso_secuencia, construir_informe_estructurado, crear_proyecto,
    )

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        agregar_fase(empresa_id, proyecto.id, {"nombre": "Fase 1", "presupuesto": 1000})
        agregar_paso_secuencia(empresa_id, proyecto.id, {"contenido": "VIDEO 1"})

        from app.extensions import db
        db.session.refresh(proyecto)

        informe = construir_informe_estructurado(proyecto)
        for clave in ("empresa", "objetivo", "presupuesto", "periodo", "diagnostico", "oportunidades", "alertas",
                      "fases", "audiencias_disponibles", "secuencia", "kpi", "metas", "contenido_requerido", "resultados_reales",
                      "decisiones_clave"):
            assert clave in informe
        assert informe["empresa"]["id"] == empresa_id
        assert len(informe["fases"]) == 1
        assert informe["contenido_requerido"] == ["VIDEO 1"]


# --- Multiempresa: aislamiento total -----------------------------------------------------

def test_obtener_proyecto_aislado_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.meta.proyectos_estrategicos import crear_proyecto, obtener_proyecto

    with client.application.app_context():
        proyecto, _ = crear_proyecto(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        assert obtener_proyecto(usuario_b_con_empresa["empresa_id"], proyecto.id) is None


def test_listar_proyectos_aislado_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.meta.proyectos_estrategicos import crear_proyecto, listar_proyectos_empresa

    with client.application.app_context():
        crear_proyecto(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        assert listar_proyectos_empresa(usuario_b_con_empresa["empresa_id"]) == []


def test_agregar_fase_a_proyecto_de_otra_empresa_rechazado(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.meta.proyectos_estrategicos import agregar_fase, crear_proyecto

    with client.application.app_context():
        proyecto, _ = crear_proyecto(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        fase, error = agregar_fase(usuario_b_con_empresa["empresa_id"], proyecto.id, {"nombre": "Fase 1", "presupuesto": 1000})
        assert fase is None
        assert "empresa" in error.lower()


def test_ruta_proyectos_lista_aislada_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.meta.proyectos_estrategicos import crear_proyecto

    with client.application.app_context():
        crear_proyecto(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], _datos_proyecto(nombre="Proyecto secreto de A"))

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp = client.get("/datos-meta/proyectos-estrategicos")
    assert resp.status_code == 200
    assert "Proyecto secreto de A" not in resp.get_data(as_text=True)


def test_ruta_proyecto_detalle_de_otra_empresa_da_404(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.meta.proyectos_estrategicos import crear_proyecto

    with client.application.app_context():
        proyecto, _ = crear_proyecto(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        proyecto_id = proyecto.id

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp = client.get(f"/datos-meta/proyectos-estrategicos/{proyecto_id}")
    assert resp.status_code == 404


# --- Ruta completa: creacion end-to-end (Paso 9, "DONE WHEN") --------------------------

def test_ruta_crear_proyecto_end_to_end(client, usuario_a_con_empresa):
    """'Captación de clientes — 30 días — ₡100.000', tal como lo pide
    el enunciado como criterio de exito."""
    resp = client.post(
        "/datos-meta/proyectos-estrategicos/crear",
        json={
            "nombre": "Captación de clientes",
            "objetivo": "conversiones",
            "kpi_principal": "costo_por_resultado",
            "kpi_secundarios": ["ctr", "cpc", "cpm", "roas"],
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
    proyecto_id = datos["proyecto_id"]

    resp_detalle = client.get(f"/datos-meta/proyectos-estrategicos/{proyecto_id}")
    assert resp_detalle.status_code == 200
    texto = resp_detalle.get_data(as_text=True)
    assert "Captación de clientes" in texto
    assert "borrador" in texto

    resp_fase = client.post(
        f"/datos-meta/proyectos-estrategicos/{proyecto_id}/fases",
        json={"nombre": "Reconocimiento", "presupuesto": 40000, "audiencia_tipo": "publico_frio"},
    )
    assert resp_fase.status_code == 201

    resp_secuencia = client.post(
        f"/datos-meta/proyectos-estrategicos/{proyecto_id}/secuencia",
        json={"contenido": "VIDEO 1", "objetivo": "Reconocimiento"},
    )
    assert resp_secuencia.status_code == 201

    resp_estado = client.post(f"/datos-meta/proyectos-estrategicos/{proyecto_id}/estado", json={"estado": "planificado"})
    assert resp_estado.status_code == 200
    assert resp_estado.get_json()["estado"] == "planificado"

    resp_decision = client.post(
        f"/datos-meta/proyectos-estrategicos/{proyecto_id}/decisiones",
        json={"texto": "Priorizar mensajes iniciados sobre alcance."},
    )
    assert resp_decision.status_code == 201
    datos_decision = resp_decision.get_json()
    assert datos_decision["ok"] is True
    assert datos_decision["decisiones_clave"][0]["texto"] == "Priorizar mensajes iniciados sobre alcance."

    resp_detalle_2 = client.get(f"/datos-meta/proyectos-estrategicos/{proyecto_id}")
    texto2 = resp_detalle_2.get_data(as_text=True)
    assert "Reconocimiento" in texto2
    assert "VIDEO 1" in texto2
    assert "Priorizar mensajes iniciados sobre alcance." in texto2


# --- Memoria estrategica (Paso 3: Inteligencia de Marketing) -------------------------

def test_agregar_decision_clave_exitosa(client, usuario_a_con_empresa):
    from app.services.meta.proyectos_estrategicos import agregar_decision_clave, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto())

        actualizado, error = agregar_decision_clave(empresa_id, proyecto.id, "Se decidió priorizar ventas sobre alcance.", usuario_a_con_empresa["usuario_id"])
        assert error is None
        assert len(actualizado.decisiones_clave) == 1
        assert actualizado.decisiones_clave[0]["texto"] == "Se decidió priorizar ventas sobre alcance."
        assert actualizado.decisiones_clave[0]["usuario_id"] == usuario_a_con_empresa["usuario_id"]
        assert actualizado.decisiones_clave[0]["creado_en"]  # se registra cuando se tomo la decision


def test_agregar_decision_clave_con_contexto_motivo_y_estado(client, usuario_a_con_empresa):
    """Cierre del Paso 3: la memoria estrategica debe poder guardar
    contexto, motivo y estado -- no solo el texto de la decision."""
    from app.services.meta.proyectos_estrategicos import agregar_decision_clave, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto())

        actualizado, error = agregar_decision_clave(
            empresa_id, proyecto.id, "Se aprobó presupuesto de ₡100.000.",
            usuario_a_con_empresa["usuario_id"],
            contexto="Tras revisar el diagnóstico de la cuenta.",
            motivo="Para probar remarketing antes de escalar.",
        )
        assert error is None
        decision = actualizado.decisiones_clave[0]
        assert decision["contexto"] == "Tras revisar el diagnóstico de la cuenta."
        assert decision["motivo"] == "Para probar remarketing antes de escalar."
        assert decision["estado"] == "activa"  # por defecto
        # auditable por si sola, aunque ya viva dentro del proyecto:
        assert decision["proyecto_id"] == proyecto.id
        assert decision["empresa_id"] == empresa_id


def test_agregar_decision_clave_estado_invalido_rechazado(client, usuario_a_con_empresa):
    from app.services.meta.proyectos_estrategicos import agregar_decision_clave, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto())

        actualizado, error = agregar_decision_clave(empresa_id, proyecto.id, "Texto", estado="no_existe")
        assert actualizado is None
        assert error is not None


def test_agregar_decision_clave_sin_contexto_ni_motivo_es_compatible(client, usuario_a_con_empresa):
    """Compatibilidad con proyectos existentes: seguir permitiendo
    registrar una decision solo con texto, igual que antes de este
    cierre -- contexto/motivo quedan en None, no en string vacio."""
    from app.services.meta.proyectos_estrategicos import agregar_decision_clave, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto())

        actualizado, error = agregar_decision_clave(empresa_id, proyecto.id, "Solo el texto.")
        assert error is None
        decision = actualizado.decisiones_clave[0]
        assert decision["contexto"] is None
        assert decision["motivo"] is None


def test_agregar_decision_clave_vacia_rechazada(client, usuario_a_con_empresa):
    from app.services.meta.proyectos_estrategicos import agregar_decision_clave, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto())

        actualizado, error = agregar_decision_clave(empresa_id, proyecto.id, "   ", usuario_a_con_empresa["usuario_id"])
        assert actualizado is None
        assert error is not None


def test_agregar_decision_clave_de_otra_empresa_rechazada(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.meta.proyectos_estrategicos import agregar_decision_clave, crear_proyecto

    with client.application.app_context():
        proyecto, _ = crear_proyecto(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], _datos_proyecto())

        actualizado, error = agregar_decision_clave(usuario_b_con_empresa["empresa_id"], proyecto.id, "Intento cruzado.", usuario_b_con_empresa["usuario_id"])
        assert actualizado is None
        assert error is not None


def test_ruta_agregar_decision_vacia_da_400(client, usuario_a_con_empresa):
    from app.services.meta.proyectos_estrategicos import crear_proyecto

    with client.application.app_context():
        proyecto, _ = crear_proyecto(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        proyecto_id = proyecto.id

    resp = client.post(f"/datos-meta/proyectos-estrategicos/{proyecto_id}/decisiones", json={"texto": "   "})
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_ruta_agregar_decision_a_proyecto_de_otra_empresa_da_400(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.meta.proyectos_estrategicos import crear_proyecto

    with client.application.app_context():
        proyecto, _ = crear_proyecto(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        proyecto_id = proyecto.id

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp = client.post(f"/datos-meta/proyectos-estrategicos/{proyecto_id}/decisiones", json={"texto": "Intento cruzado."})
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_listar_decisiones_clave_preserva_orden(client, usuario_a_con_empresa):
    from app.services.meta.proyectos_estrategicos import agregar_decision_clave, crear_proyecto, listar_decisiones_clave

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        agregar_decision_clave(empresa_id, proyecto.id, "Primera decisión.")
        agregar_decision_clave(empresa_id, proyecto.id, "Segunda decisión.")

        decisiones = listar_decisiones_clave(empresa_id, proyecto.id)
        assert [d["texto"] for d in decisiones] == ["Primera decisión.", "Segunda decisión."]


def test_listar_decisiones_clave_proyecto_inexistente_es_none(client, usuario_a_con_empresa):
    from app.services.meta.proyectos_estrategicos import listar_decisiones_clave

    with client.application.app_context():
        assert listar_decisiones_clave(usuario_a_con_empresa["empresa_id"], 999999) is None


def test_decisiones_clave_aparecen_en_el_informe_estructurado(client, usuario_a_con_empresa):
    from app.services.meta.proyectos_estrategicos import agregar_decision_clave, construir_informe_estructurado, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        agregar_decision_clave(empresa_id, proyecto.id, "Probar remarketing primero.")

        from app.extensions import db
        db.session.refresh(proyecto)

        informe = construir_informe_estructurado(proyecto)
        assert informe["decisiones_clave"][0]["texto"] == "Probar remarketing primero."


def test_decisiones_clave_se_incluyen_en_el_contexto_de_claude(client, usuario_a_con_empresa):
    """El texto que se le envia al modelo (estratega_ia.py) debe
    mencionar las decisiones ya tomadas del proyecto -- para que una
    conversacion nueva no las ignore (Paso 3, memoria estrategica)."""
    from app.services.estratega_ia import construir_contexto
    from app.services.meta.proyectos_estrategicos import agregar_decision_clave, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        empresa = db_query_empresa(empresa_id)
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        agregar_decision_clave(empresa_id, proyecto.id, "Se aprobó un presupuesto de prueba de ₡100.000.")

        from app.extensions import db
        db.session.refresh(proyecto)

        informe, resumen, error = construir_contexto(empresa, proyecto=proyecto)
        assert error is None

        from app.services.estratega_ia import _formatear_contexto_para_prompt

        texto = _formatear_contexto_para_prompt(informe, resumen["fuente"], proyecto=proyecto)
        assert "Se aprobó un presupuesto de prueba de ₡100.000." in texto
        assert "DECISIONES CLAVE" in texto


def test_contexto_de_claude_incluye_motivo_y_contexto_de_la_decision(client, usuario_a_con_empresa):
    """Cierre del Paso 3: Claude debe poder consultar tambien el motivo
    y el contexto de cada decision, no solo el texto -- para que su
    analisis futuro entienda POR QUE se decidio algo."""
    from app.services.estratega_ia import _formatear_contexto_para_prompt, construir_contexto
    from app.services.meta.proyectos_estrategicos import agregar_decision_clave, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        empresa = db_query_empresa(empresa_id)
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        agregar_decision_clave(
            empresa_id, proyecto.id, "Probar remarketing.",
            contexto="Tras detectar audiencia fría con bajo rendimiento.",
            motivo="Para reducir el costo por resultado.",
        )

        from app.extensions import db
        db.session.refresh(proyecto)

        informe, resumen, _error = construir_contexto(empresa, proyecto=proyecto)
        texto = _formatear_contexto_para_prompt(informe, resumen["fuente"], proyecto=proyecto)
        assert "Para reducir el costo por resultado" in texto
        assert "Tras detectar audiencia fría con bajo rendimiento" in texto


def test_decision_reemplazada_no_aparece_en_contexto_de_claude(client, usuario_a_con_empresa):
    """Una decision marcada 'reemplazada' ya no debe presentarse a
    Claude como vigente -- evita que respete una decision que el
    equipo ya dejo sin efecto."""
    from app.services.estratega_ia import _formatear_contexto_para_prompt, construir_contexto
    from app.services.meta.proyectos_estrategicos import agregar_decision_clave, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        empresa = db_query_empresa(empresa_id)
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], _datos_proyecto())
        agregar_decision_clave(empresa_id, proyecto.id, "Decisión ya reemplazada.", estado="reemplazada")
        agregar_decision_clave(empresa_id, proyecto.id, "Decisión vigente.")

        from app.extensions import db
        db.session.refresh(proyecto)

        informe, resumen, _error = construir_contexto(empresa, proyecto=proyecto)
        texto = _formatear_contexto_para_prompt(informe, resumen["fuente"], proyecto=proyecto)
        assert "Decisión vigente." in texto
        assert "Decisión ya reemplazada." not in texto


def db_query_empresa(empresa_id):
    from app.extensions import db
    from app.models import Empresa

    return db.session.query(Empresa).filter_by(id=empresa_id).first()
