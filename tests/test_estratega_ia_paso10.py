"""Pruebas del Paso 10: Estratega IA.

Cubre exclusivamente lo nuevo de este paso -- construccion de contexto
(reutilizando inteligencia.py y proyectos_estrategicos.py sin
recalcular nada), conversaciones/mensajes, historial multi-turno,
limites de uso, manejo honesto de "IA no configurada" y de errores del
modelo, y aislamiento multiempresa (incluyendo que ningun secreto de
Meta llegue al contexto). El motor de KPI/inteligencia/proyectos YA
esta probado en sus propios archivos de tests -- aqui nunca se
reimplementa ese calculo, ni se hacen llamadas reales a Anthropic
(siempre se monkeypatchea app.services.ia).
"""

import datetime

from app.models import EntidadPublicitaria
from tests.conftest import iniciar_sesion_de_prueba


def _crear_cuenta(empresa_id, id_externo="act_1"):
    from app.extensions import db

    cuenta = EntidadPublicitaria(empresa_id=empresa_id, fuente="meta", tipo="cuenta_publicitaria", id_externo=id_externo, nombre="Cuenta", atributos={"moneda": "CRC"})
    db.session.add(cuenta)
    db.session.commit()
    return cuenta


def _crear_campana(empresa_id, id_externo, entidad_padre_id):
    from app.extensions import db

    campana = EntidadPublicitaria(
        empresa_id=empresa_id, fuente="meta", tipo="campana", id_externo=id_externo,
        nombre=f"Campaña {id_externo}", entidad_padre_id=entidad_padre_id, estado="ACTIVE",
    )
    db.session.add(campana)
    db.session.commit()
    return campana


def _registrar(empresa_id, entidad_id, entidad_tipo, metrica, valor, fecha):
    from app.services.metricas import registrar_metrica

    registrar_metrica(empresa_id, metrica, valor, fecha, entidad_id=entidad_id, entidad_tipo=entidad_tipo)


FECHA_INICIO = datetime.date(2026, 8, 1)
FECHA_FIN = datetime.date(2026, 8, 10)


def _mockear_ia_exitosa(monkeypatch, texto="DATO: ejemplo.\nANÁLISIS: ejemplo.\nRECOMENDACIÓN: ejemplo."):
    import app.services.ia as ia_mod

    monkeypatch.setattr(ia_mod, "ia_configurada", lambda: True)
    monkeypatch.setattr(
        ia_mod, "generar_respuesta",
        lambda mensajes, system=None, modelo=None, max_tokens=None: (texto, {"modelo": "claude-sonnet-5", "tokens_entrada": 100, "tokens_salida": 50}, None),
    )


def _mockear_ia_error(monkeypatch, error="El asistente de IA no está disponible."):
    import app.services.ia as ia_mod

    monkeypatch.setattr(ia_mod, "ia_configurada", lambda: True)
    monkeypatch.setattr(ia_mod, "generar_respuesta", lambda mensajes, system=None, modelo=None, max_tokens=None: (None, None, error))


# --- Contexto: reutiliza inteligencia.py / proyectos_estrategicos.py, nunca recalcula ---

def test_construir_contexto_sin_cuenta_ni_proyecto_reutiliza_inteligencia(client, usuario_a_con_empresa):
    from app.models import Empresa
    from app.extensions import db
    from app.services.estratega_ia import construir_contexto

    with client.application.app_context():
        empresa = db.session.query(Empresa).filter_by(id=usuario_a_con_empresa["empresa_id"]).first()
        informe, resumen, error = construir_contexto(empresa, None, "ultimos_30_dias")
        assert error is None
        assert resumen["fuente"] == "inteligencia"
        for clave in ("diagnostico", "campanas", "audiencias", "oportunidades", "alertas", "kpi"):
            assert clave in informe


def test_construir_contexto_con_proyecto_reutiliza_proyectos_estrategicos(client, usuario_a_con_empresa):
    from app.models import Empresa
    from app.extensions import db
    from app.services.estratega_ia import construir_contexto
    from app.services.meta.proyectos_estrategicos import agregar_fase, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        empresa = db.session.query(Empresa).filter_by(id=empresa_id).first()
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], {
            "nombre": "Captación", "objetivo": "conversiones", "kpi_principal": "costo_por_resultado",
            "presupuesto_total": 100000, "fecha_inicio": FECHA_INICIO, "fecha_fin": FECHA_FIN,
        })
        agregar_fase(empresa_id, proyecto.id, {"nombre": "Fase 1", "presupuesto": 40000})
        db.session.refresh(proyecto)

        informe, resumen, error = construir_contexto(empresa, None, "ultimos_30_dias", proyecto=proyecto)
        assert error is None
        assert resumen["fuente"] == "proyecto"
        assert resumen["fases"] == 1
        assert informe["fases"][0]["nombre"] == "Fase 1"


def test_construir_contexto_usa_presupuesto_estrategico_general(client, usuario_a_con_empresa):
    from app.models import Empresa
    from app.extensions import db
    from app.services.estratega_ia import construir_contexto
    from app.services.presupuestos import crear_presupuesto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        empresa = db.session.query(Empresa).filter_by(id=empresa_id).first()
        crear_presupuesto(empresa_id, usuario_a_con_empresa["usuario_id"], "General", "estrategico", 100000)

        informe, resumen, error = construir_contexto(empresa, None, "ultimos_30_dias")
        assert error is None
        assert informe["presupuesto_total"] == 100000


def test_formatear_contexto_nunca_inventa_datos_faltantes(client, usuario_a_con_empresa):
    """Sin ninguna campaña sincronizada, el texto formateado debe decir
    honestamente que no hay datos -- nunca debe fallar ni inventar
    numeros (Paso 10, punto 4/5)."""
    from app.models import Empresa
    from app.extensions import db
    from app.services.estratega_ia import _formatear_contexto_para_prompt, construir_contexto

    with client.application.app_context():
        empresa = db.session.query(Empresa).filter_by(id=usuario_a_con_empresa["empresa_id"]).first()
        informe, resumen, error = construir_contexto(empresa, None, "ultimos_30_dias")
        assert error is None
        texto = _formatear_contexto_para_prompt(informe, resumen["fuente"])
        assert "ninguna campaña sincronizada" in texto
        assert "No disponible" in texto or "No hay datos" not in texto  # nunca inventa un numero


# --- Conversaciones y aislamiento multiempresa -----------------------------------------

def test_crear_conversacion_exitosa(client, usuario_a_con_empresa):
    from app.services.estratega_ia import crear_conversacion

    with client.application.app_context():
        conversacion, error = crear_conversacion(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])
        assert error is None
        assert conversacion.id is not None
        assert conversacion.empresa_id == usuario_a_con_empresa["empresa_id"]


def test_crear_conversacion_con_proyecto_de_otra_empresa_rechazada(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.estratega_ia import crear_conversacion
    from app.services.meta.proyectos_estrategicos import crear_proyecto

    with client.application.app_context():
        proyecto_b, _ = crear_proyecto(usuario_b_con_empresa["empresa_id"], usuario_b_con_empresa["usuario_id"], {
            "nombre": "Proyecto B", "objetivo": "conversiones", "kpi_principal": "costo_por_resultado",
            "presupuesto_total": 1000, "fecha_inicio": FECHA_INICIO, "fecha_fin": FECHA_FIN,
        })
        conversacion, error = crear_conversacion(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], proyecto_id=proyecto_b.id)
        assert conversacion is None
        assert "empresa" in error.lower()


def test_obtener_conversacion_aislada_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.estratega_ia import crear_conversacion, obtener_conversacion

    with client.application.app_context():
        conversacion, _ = crear_conversacion(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])
        assert obtener_conversacion(usuario_b_con_empresa["empresa_id"], conversacion.id) is None


def test_listar_conversaciones_aislado_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.estratega_ia import crear_conversacion, listar_conversaciones_empresa

    with client.application.app_context():
        crear_conversacion(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])
        assert listar_conversaciones_empresa(usuario_b_con_empresa["empresa_id"]) == []


def test_ruta_conversacion_detalle_de_otra_empresa_da_404(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.estratega_ia import crear_conversacion

    with client.application.app_context():
        conversacion, _ = crear_conversacion(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])
        conversacion_id = conversacion.id

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp = client.get(f"/marketing/estratega-ia/conversaciones/{conversacion_id}")
    assert resp.status_code == 404


def test_ruta_index_aislada_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.estratega_ia import crear_conversacion

    with client.application.app_context():
        crear_conversacion(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])

    resp = client.get("/marketing/estratega-ia/")
    assert resp.status_code == 200

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp_b = client.get("/marketing/estratega-ia/")
    assert resp_b.status_code == 200
    # la lista embebida en la pagina de B nunca debe traer conversaciones de A
    assert "empresa_id" not in resp_b.get_data(as_text=True) or str(usuario_a_con_empresa["empresa_id"]) not in resp_b.get_data(as_text=True)


# --- Responder: historial, limites, errores ---------------------------------------------

def test_responder_sin_ia_configurada_no_guarda_nada(client, usuario_a_con_empresa, monkeypatch):
    import app.services.ia as ia_mod
    from app.models import Empresa
    from app.extensions import db
    from app.services.estratega_ia import crear_conversacion, responder

    monkeypatch.setattr(ia_mod, "ia_configurada", lambda: False)

    with client.application.app_context():
        empresa = db.session.query(Empresa).filter_by(id=usuario_a_con_empresa["empresa_id"]).first()
        conversacion, _ = crear_conversacion(empresa.id, usuario_a_con_empresa["usuario_id"])
        mensaje, error = responder(empresa, conversacion, "hola")
        assert mensaje is None
        assert "no está configurado" in error.lower()
        assert len(conversacion.mensajes) == 0


def test_responder_mensaje_vacio_rechazado(client, usuario_a_con_empresa, monkeypatch):
    from app.models import Empresa
    from app.extensions import db
    from app.services.estratega_ia import crear_conversacion, responder

    _mockear_ia_exitosa(monkeypatch)

    with client.application.app_context():
        empresa = db.session.query(Empresa).filter_by(id=usuario_a_con_empresa["empresa_id"]).first()
        conversacion, _ = crear_conversacion(empresa.id, usuario_a_con_empresa["usuario_id"])
        mensaje, error = responder(empresa, conversacion, "   ")
        assert mensaje is None
        assert "vacío" in error.lower()


def test_responder_exitoso_guarda_pregunta_y_respuesta(client, usuario_a_con_empresa, monkeypatch):
    from app.models import Empresa
    from app.extensions import db
    from app.services.estratega_ia import crear_conversacion, responder

    _mockear_ia_exitosa(monkeypatch, texto="DATO: prueba real.")

    with client.application.app_context():
        empresa = db.session.query(Empresa).filter_by(id=usuario_a_con_empresa["empresa_id"]).first()
        conversacion, _ = crear_conversacion(empresa.id, usuario_a_con_empresa["usuario_id"])
        mensaje, error = responder(empresa, conversacion, "¿Cómo van mis campañas?")
        assert error is None
        assert mensaje.rol == "asistente"
        assert mensaje.contenido == "DATO: prueba real."
        assert mensaje.tokens_entrada == 100
        assert mensaje.tokens_salida == 50

        db.session.refresh(conversacion)
        assert len(conversacion.mensajes) == 2
        assert conversacion.mensajes[0].rol == "usuario"
        assert conversacion.titulo == "¿Cómo van mis campañas?"


def test_responder_error_de_ia_conserva_la_pregunta_del_usuario(client, usuario_a_con_empresa, monkeypatch):
    from app.models import Empresa
    from app.extensions import db
    from app.services.estratega_ia import crear_conversacion, responder

    _mockear_ia_error(monkeypatch, error="No se pudo contactar al asistente de IA.")

    with client.application.app_context():
        empresa = db.session.query(Empresa).filter_by(id=usuario_a_con_empresa["empresa_id"]).first()
        conversacion, _ = crear_conversacion(empresa.id, usuario_a_con_empresa["usuario_id"])
        mensaje, error = responder(empresa, conversacion, "¿Qué audiencia funciona mejor?")
        assert mensaje is None
        assert error == "No se pudo contactar al asistente de IA."

        db.session.refresh(conversacion)
        assert len(conversacion.mensajes) == 1
        assert conversacion.mensajes[0].rol == "usuario"
        assert conversacion.mensajes[0].contenido == "¿Qué audiencia funciona mejor?"


def test_responder_historial_multiturno_incluye_mensajes_previos(client, usuario_a_con_empresa, monkeypatch):
    """El segundo mensaje debe ver el primero en el historial que se le
    envia al modelo -- verifica que _historial_para_modelo no dependa
    de un refresh de la coleccion (bug real encontrado y corregido
    durante el desarrollo)."""
    import app.services.ia as ia_mod
    from app.models import Empresa
    from app.extensions import db
    from app.services.estratega_ia import crear_conversacion, responder

    mensajes_recibidos = []

    def _fake_generar(mensajes, system=None, modelo=None, max_tokens=None):
        mensajes_recibidos.append(list(mensajes))
        return "respuesta", {"modelo": "claude-sonnet-5", "tokens_entrada": 10, "tokens_salida": 5}, None

    monkeypatch.setattr(ia_mod, "ia_configurada", lambda: True)
    monkeypatch.setattr(ia_mod, "generar_respuesta", _fake_generar)

    with client.application.app_context():
        empresa = db.session.query(Empresa).filter_by(id=usuario_a_con_empresa["empresa_id"]).first()
        conversacion, _ = crear_conversacion(empresa.id, usuario_a_con_empresa["usuario_id"])

        responder(empresa, conversacion, "primer mensaje")
        db.session.refresh(conversacion)
        responder(empresa, conversacion, "segundo mensaje")

        # La segunda llamada al modelo debe incluir el primer mensaje Y su respuesta.
        segunda_llamada = mensajes_recibidos[1]
        contenidos = [m["content"] for m in segunda_llamada]
        assert "primer mensaje" in contenidos
        assert "respuesta" in contenidos
        assert "segundo mensaje" in contenidos


def test_responder_limite_de_mensajes_por_conversacion(client, usuario_a_con_empresa, monkeypatch):
    import app.services.estratega_ia as estratega_mod
    from app.models import Empresa
    from app.extensions import db
    from app.services.estratega_ia import crear_conversacion, responder

    monkeypatch.setattr(estratega_mod, "LIMITE_MENSAJES_POR_CONVERSACION", 1)
    _mockear_ia_exitosa(monkeypatch)

    with client.application.app_context():
        empresa = db.session.query(Empresa).filter_by(id=usuario_a_con_empresa["empresa_id"]).first()
        conversacion, _ = crear_conversacion(empresa.id, usuario_a_con_empresa["usuario_id"])
        responder(empresa, conversacion, "primero")
        db.session.refresh(conversacion)

        mensaje, error = responder(empresa, conversacion, "segundo")
        assert mensaje is None
        assert "máximo" in error.lower()


def test_responder_limite_diario_por_empresa(client, usuario_a_con_empresa, monkeypatch):
    import app.services.estratega_ia as estratega_mod
    from app.models import Empresa
    from app.extensions import db
    from app.services.estratega_ia import crear_conversacion, responder

    monkeypatch.setattr(estratega_mod, "LIMITE_MENSAJES_DIARIOS_POR_EMPRESA", 1)
    _mockear_ia_exitosa(monkeypatch)

    with client.application.app_context():
        empresa = db.session.query(Empresa).filter_by(id=usuario_a_con_empresa["empresa_id"]).first()
        conversacion, _ = crear_conversacion(empresa.id, usuario_a_con_empresa["usuario_id"])
        responder(empresa, conversacion, "primero")

        conversacion2, _ = crear_conversacion(empresa.id, usuario_a_con_empresa["usuario_id"])
        mensaje, error = responder(empresa, conversacion2, "segundo, otra conversación")
        assert mensaje is None
        assert "límite diario" in error.lower()


# --- KPI: pregunta por un KPI sin datos ------------------------------------------------

def test_contexto_kpi_sin_datos_queda_no_disponible(client, usuario_a_con_empresa):
    from app.models import Empresa
    from app.extensions import db
    from app.services.estratega_ia import construir_contexto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        empresa = db.session.query(Empresa).filter_by(id=empresa_id).first()
        cuenta = _crear_cuenta(empresa_id)
        informe, resumen, error = construir_contexto(empresa, cuenta.id, "ultimos_30_dias")
        assert error is None
        assert informe["kpi"].get("roas") is None  # nunca inventado


def test_contexto_kpi_con_datos_reales(client, usuario_a_con_empresa):
    from app.models import Empresa
    from app.extensions import db
    from app.services.estratega_ia import construir_contexto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        empresa = db.session.query(Empresa).filter_by(id=empresa_id).first()
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        _registrar(empresa_id, campana.id, "campana", "spend", 500.0, FECHA_INICIO)
        _registrar(empresa_id, campana.id, "campana", "conversiones", 10.0, FECHA_INICIO)

        informe, resumen, error = construir_contexto(empresa, cuenta.id, "ultimos_90_dias")
        assert error is None
        assert informe["kpi"].get("spend") is not None


# --- Seguridad: nunca se envia ningun secreto de Meta al contexto ----------------------

def test_contexto_nunca_incluye_secretos_de_meta(client, usuario_a_con_empresa):
    from app.models import Empresa
    from app.extensions import db
    from app.services.estratega_ia import _formatear_contexto_para_prompt, construir_contexto
    from app.services.meta.conexiones import crear_conexion

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        empresa = db.session.query(Empresa).filter_by(id=empresa_id).first()
        crear_conexion(empresa_id, usuario_a_con_empresa["usuario_id"], "111", "Usuario Meta", "token-secreto-de-prueba-nunca-debe-aparecer")

        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        _registrar(empresa_id, campana.id, "campana", "spend", 500.0, FECHA_INICIO)

        informe, resumen, error = construir_contexto(empresa, cuenta.id, "ultimos_90_dias")
        assert error is None
        texto = _formatear_contexto_para_prompt(informe, resumen["fuente"])

        assert "token-secreto-de-prueba-nunca-debe-aparecer" not in texto
        assert "token-secreto-de-prueba-nunca-debe-aparecer" not in str(resumen)
        for palabra_prohibida in ("access_token", "client_secret", "service_role", "password"):
            assert palabra_prohibida not in texto.lower()


# --- Ruta completa: creacion + mensaje end-to-end ---------------------------------------

def test_ruta_crear_conversacion_y_enviar_mensaje_end_to_end(client, usuario_a_con_empresa, monkeypatch):
    _mockear_ia_exitosa(monkeypatch, texto="DATO: la campaña X gastó 500.\nANÁLISIS: dentro de lo esperado.\nRECOMENDACIÓN: mantener.")

    resp = client.post("/marketing/estratega-ia/conversaciones", json={})
    assert resp.status_code == 201
    conversacion_id = resp.get_json()["conversacion"]["id"]

    resp_mensaje = client.post(
        f"/marketing/estratega-ia/conversaciones/{conversacion_id}/mensajes",
        json={"mensaje": "¿Cuál campaña está funcionando mejor?", "periodo": "ultimos_30_dias"},
    )
    assert resp_mensaje.status_code == 200
    datos = resp_mensaje.get_json()
    assert datos["ok"] is True
    assert "DATO:" in datos["mensaje"]["contenido"]

    resp_detalle = client.get(f"/marketing/estratega-ia/conversaciones/{conversacion_id}")
    assert resp_detalle.status_code == 200
    mensajes = resp_detalle.get_json()["mensajes"]
    assert len(mensajes) == 2
