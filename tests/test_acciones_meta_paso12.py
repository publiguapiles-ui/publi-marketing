"""Pruebas del Paso 12: acciones controladas sobre Meta.

Cubre exclusivamente lo nuevo de este paso -- creacion de propuesta,
aprobacion/rechazo/cancelacion, doble confirmacion (a nivel de
SERVICIO, no solo de interfaz), verificacion de permisos (incluye el
permiso ads_management agregado en este mismo paso), validacion de
recurso, ejecucion real contra un MetaClient mockeado (pausar/activar/
modificar presupuesto), deteccion de cambio de valor desde que se creo
la propuesta, verificacion posterior tras escribir, auditoria completa,
manejo de errores de Meta sin marcar como ejecutada, preparacion de
reversion, y aislamiento multiempresa. NUNCA se hace una llamada real a
Meta -- MetaClient.get/post siempre estan mockeados.
"""

import datetime

from app.models import EntidadPublicitaria
from tests.conftest import iniciar_sesion_de_prueba


def _crear_conexion(app_client, empresa_id, usuario_id, con_ads_management=True):
    from app.services.meta.conexiones import crear_conexion

    scopes = ["ads_read", "business_management"]
    if con_ads_management:
        scopes.append("ads_management")
    return crear_conexion(empresa_id, usuario_id, "111", "Usuario Meta", "token-de-prueba", scopes=scopes)


def _crear_cuenta(empresa_id, id_externo="act_1"):
    from app.extensions import db

    cuenta = EntidadPublicitaria(empresa_id=empresa_id, fuente="meta", tipo="cuenta_publicitaria", id_externo=id_externo, nombre="Cuenta", atributos={"moneda": "CRC"})
    db.session.add(cuenta)
    db.session.commit()
    return cuenta


def _crear_campana(empresa_id, id_externo, cuenta_id, estado="ACTIVE", presupuesto_diario=None, nombre=None):
    from app.extensions import db

    atributos = {"presupuesto_diario": presupuesto_diario} if presupuesto_diario is not None else {}
    campana = EntidadPublicitaria(
        empresa_id=empresa_id, fuente="meta", tipo="campana", id_externo=id_externo,
        nombre=nombre or f"Campaña {id_externo}", entidad_padre_id=cuenta_id, estado=estado, atributos=atributos,
    )
    db.session.add(campana)
    db.session.commit()
    return campana


def _crear_anuncio(empresa_id, id_externo, conjunto_id, estado="ACTIVE"):
    from app.extensions import db

    anuncio = EntidadPublicitaria(
        empresa_id=empresa_id, fuente="meta", tipo="anuncio", id_externo=id_externo,
        nombre=f"Anuncio {id_externo}", entidad_padre_id=conjunto_id, estado=estado,
    )
    db.session.add(anuncio)
    db.session.commit()
    return anuncio


def _mockear_meta(monkeypatch, respuestas_get=None, respuesta_post=None):
    """`respuestas_get`: lista de valores devueltos EN ORDEN por
    llamadas sucesivas a MetaClient.get() (cada uno un dict o una
    Exception) -- ejecutar_accion llama a .get() dos veces (pre-chequeo
    y verificacion posterior), en ese orden. `respuesta_post`: lo que
    devuelve MetaClient.post() (o una Exception)."""
    import app.services.meta.client as client_mod

    respuestas_get = list(respuestas_get or [])
    estado = {"i": 0}

    def _get(self, ruta, params=None, access_token=None):
        idx = min(estado["i"], len(respuestas_get) - 1) if respuestas_get else 0
        estado["i"] += 1
        resp = respuestas_get[idx] if respuestas_get else {}
        if isinstance(resp, Exception):
            raise resp
        return resp

    def _post(self, ruta, data=None, access_token=None):
        if isinstance(respuesta_post, Exception):
            raise respuesta_post
        return respuesta_post if respuesta_post is not None else {}

    monkeypatch.setattr(client_mod.MetaClient, "get", _get)
    monkeypatch.setattr(client_mod.MetaClient, "post", _post)


# --- Creacion de propuesta ---------------------------------------------------------------

def test_crear_propuesta_exitosa_pausar(client, usuario_a_con_empresa):
    from app.services.meta.acciones import crear_propuesta

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id, estado="ACTIVE")

        accion, error = crear_propuesta(
            empresa_id, usuario_a_con_empresa["usuario_id"], campana.id, "pausar", "PAUSED",
            motivo="Costo por resultado muy alto.",
        )
        assert error is None
        assert accion.estado == "pendiente_de_aprobacion"
        assert accion.valor_actual == "ACTIVE"
        assert accion.valor_propuesto == "PAUSED"
        assert accion.propuesto_por == usuario_a_con_empresa["usuario_id"]


def test_crear_propuesta_captura_presupuesto_actual_real(client, usuario_a_con_empresa):
    from app.services.meta.acciones import crear_propuesta

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id, presupuesto_diario="500000")

        accion, error = crear_propuesta(
            empresa_id, usuario_a_con_empresa["usuario_id"], campana.id, "modificar_presupuesto", "650000",
            motivo="El costo por resultado está por debajo del promedio histórico.",
        )
        assert error is None
        assert accion.valor_actual == "500000"
        assert accion.valor_propuesto == "650000"


def test_crear_propuesta_entidad_de_otra_empresa_rechazada(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.meta.acciones import crear_propuesta

    with client.application.app_context():
        cuenta_b = _crear_cuenta(usuario_b_con_empresa["empresa_id"])
        campana_b = _crear_campana(usuario_b_con_empresa["empresa_id"], "cb", cuenta_b.id)

        accion, error = crear_propuesta(
            usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], campana_b.id, "pausar", "PAUSED",
            motivo="x",
        )
        assert accion is None
        assert "empresa" in error.lower()


def test_crear_propuesta_presupuesto_en_anuncio_rechazado(client, usuario_a_con_empresa):
    """Un anuncio no tiene presupuesto propio en Meta -- validacion de
    recurso (Paso 12, punto 2)."""
    from app.services.meta.acciones import crear_propuesta

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        anuncio = _crear_anuncio(empresa_id, "a1", campana.id)  # conjunto omitido a proposito, solo se prueba el tipo

        accion, error = crear_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], anuncio.id, "modificar_presupuesto", "1000", motivo="x")
        assert accion is None
        assert "presupuesto propio" in error.lower()


def test_crear_propuesta_motivo_obligatorio(client, usuario_a_con_empresa):
    from app.services.meta.acciones import crear_propuesta

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)

        accion, error = crear_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], campana.id, "pausar", "PAUSED", motivo="")
        assert accion is None
        assert "motivo" in error.lower()


def test_crear_propuesta_presupuesto_no_numerico_rechazado(client, usuario_a_con_empresa):
    from app.services.meta.acciones import crear_propuesta

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)

        accion, error = crear_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], campana.id, "modificar_presupuesto", "no-es-un-numero", motivo="x")
        assert accion is None
        assert "número" in error.lower()


# --- Aprobacion / rechazo / cancelacion ---------------------------------------------------

def test_aprobar_propuesta_exitosa(client, usuario_a_con_empresa):
    from app.services.meta.acciones import aprobar_propuesta, crear_propuesta

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        accion, _ = crear_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], campana.id, "pausar", "PAUSED", motivo="x")

        aprobada, error = aprobar_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], accion.id)
        assert error is None
        assert aprobada.estado == "aprobada"
        assert aprobada.aprobado_por == usuario_a_con_empresa["usuario_id"]
        assert aprobada.aprobado_en is not None


def test_aprobar_propuesta_ya_aprobada_rechazado(client, usuario_a_con_empresa):
    from app.services.meta.acciones import aprobar_propuesta, crear_propuesta

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        accion, _ = crear_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], campana.id, "pausar", "PAUSED", motivo="x")
        aprobar_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], accion.id)

        resultado, error = aprobar_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], accion.id)
        assert resultado is None
        assert "aprobada" in error.lower()


def test_rechazar_propuesta_exitosa(client, usuario_a_con_empresa):
    from app.services.meta.acciones import crear_propuesta, rechazar_propuesta

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        accion, _ = crear_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], campana.id, "pausar", "PAUSED", motivo="x")

        rechazada, error = rechazar_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], accion.id, motivo_rechazo="No es prioridad ahora.")
        assert error is None
        assert rechazada.estado == "rechazada"
        assert "No es prioridad" in rechazada.riesgo


def test_cancelar_propuesta_no_permite_si_ya_ejecutada(client, usuario_a_con_empresa, monkeypatch):
    from app.services.meta.acciones import aprobar_propuesta, cancelar_propuesta, crear_propuesta, ejecutar_accion

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        _crear_conexion(client, empresa_id, usuario_a_con_empresa["usuario_id"])
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id, estado="ACTIVE")
        accion, _ = crear_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], campana.id, "pausar", "PAUSED", motivo="x")
        aprobar_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], accion.id)
        accion_id = accion.id

    _mockear_meta(monkeypatch, respuestas_get=[{"status": "ACTIVE"}, {"status": "PAUSED"}])
    with client.application.app_context():
        ejecutar_accion(empresa_id, usuario_a_con_empresa["usuario_id"], accion_id, confirmacion=True)

        resultado, error = cancelar_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], accion_id)
        assert resultado is None
        assert "ejecutada" in error.lower()


# --- Permisos y doble confirmacion (ejecutar_accion) --------------------------------------

def test_ejecutar_accion_requiere_estado_aprobada(client, usuario_a_con_empresa):
    from app.services.meta.acciones import crear_propuesta, ejecutar_accion

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        accion, _ = crear_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], campana.id, "pausar", "PAUSED", motivo="x")

        resultado, error = ejecutar_accion(empresa_id, usuario_a_con_empresa["usuario_id"], accion.id, confirmacion=True)
        assert resultado is None
        assert "aprobada" in error.lower()


def test_ejecutar_accion_requiere_confirmacion_explicita(client, usuario_a_con_empresa, monkeypatch):
    """Segunda confirmacion (Paso 12, punto 5) -- estar "aprobada" NO
    basta, hace falta ademas confirmacion=True explicito. Sin ella,
    Meta NUNCA debe ser contactado."""
    from app.services.meta.acciones import aprobar_propuesta, crear_propuesta, ejecutar_accion

    def _get_que_nunca_deberia_llamarse(self, ruta, params=None, access_token=None):
        raise AssertionError("no debia llamarse a Meta sin confirmacion explicita")

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        _crear_conexion(client, empresa_id, usuario_a_con_empresa["usuario_id"])
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        accion, _ = crear_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], campana.id, "pausar", "PAUSED", motivo="x")
        aprobar_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], accion.id)

        import app.services.meta.client as client_mod
        monkeypatch.setattr(client_mod.MetaClient, "get", _get_que_nunca_deberia_llamarse)

        resultado, error = ejecutar_accion(empresa_id, usuario_a_con_empresa["usuario_id"], accion.id, confirmacion=False)
        assert resultado is None
        assert "confirmación" in error.lower()

        from app.extensions import db
        db.session.refresh(accion)
        assert accion.estado == "aprobada"  # nunca paso a "ejecutando"


def test_ejecutar_accion_sin_conexion_activa_no_ejecuta(client, usuario_a_con_empresa):
    from app.services.meta.acciones import aprobar_propuesta, crear_propuesta, ejecutar_accion

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        accion, _ = crear_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], campana.id, "pausar", "PAUSED", motivo="x")
        aprobar_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], accion.id)

        resultado, error = ejecutar_accion(empresa_id, usuario_a_con_empresa["usuario_id"], accion.id, confirmacion=True)
        assert resultado is None
        assert "conexión" in error.lower()

        from app.extensions import db
        db.session.refresh(accion)
        assert accion.estado == "error"


def test_ejecutar_accion_sin_permiso_ads_management_no_ejecuta(client, usuario_a_con_empresa, monkeypatch):
    """Hallazgo real del Paso 12: una conexion creada ANTES de este
    paso (o sin reconectar) no tiene ads_management concedido -- debe
    bloquear la ejecucion con un motivo exacto, nunca fallar a ciegas."""
    from app.services.meta.acciones import aprobar_propuesta, crear_propuesta, ejecutar_accion

    def _get_que_nunca_deberia_llamarse(self, ruta, params=None, access_token=None):
        raise AssertionError("no debia llamarse a Meta sin el permiso ads_management")

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        _crear_conexion(client, empresa_id, usuario_a_con_empresa["usuario_id"], con_ads_management=False)
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        accion, _ = crear_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], campana.id, "pausar", "PAUSED", motivo="x")
        aprobar_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], accion.id)

        import app.services.meta.client as client_mod
        monkeypatch.setattr(client_mod.MetaClient, "get", _get_que_nunca_deberia_llamarse)

        resultado, error = ejecutar_accion(empresa_id, usuario_a_con_empresa["usuario_id"], accion.id, confirmacion=True)
        assert resultado is None
        assert "ads_management" in error.lower()


# --- Ejecucion real (mockeada): pausar / activar / presupuesto ---------------------------

def test_ejecutar_accion_pausar_exitosa_verifica_y_actualiza_local(client, usuario_a_con_empresa, monkeypatch):
    from app.extensions import db
    from app.services.meta.acciones import aprobar_propuesta, crear_propuesta, ejecutar_accion

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        _crear_conexion(client, empresa_id, usuario_a_con_empresa["usuario_id"])
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id, estado="ACTIVE")
        accion, _ = crear_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], campana.id, "pausar", "PAUSED", motivo="x")
        aprobar_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], accion.id)
        accion_id, campana_id = accion.id, campana.id

    # Primer .get() = pre-chequeo (valor real actual = "ACTIVE", coincide con valor_actual capturado).
    # Segundo .get() = verificacion posterior (ya "PAUSED", como se pidio).
    _mockear_meta(monkeypatch, respuestas_get=[{"status": "ACTIVE"}, {"status": "PAUSED"}], respuesta_post={})

    with client.application.app_context():
        resultado, error = ejecutar_accion(empresa_id, usuario_a_con_empresa["usuario_id"], accion_id, confirmacion=True)
        assert error is None
        assert resultado.estado == "ejecutada"
        assert resultado.ejecutado_en is not None
        assert resultado.resultado_meta["valor_confirmado"] == "PAUSED"

        campana_actualizada = db.session.get(EntidadPublicitaria, campana_id)
        assert campana_actualizada.estado == "PAUSED"  # Publi Marketing se actualiza sin esperar la proxima sync


def test_ejecutar_accion_activar_exitosa(client, usuario_a_con_empresa, monkeypatch):
    from app.services.meta.acciones import aprobar_propuesta, crear_propuesta, ejecutar_accion

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        _crear_conexion(client, empresa_id, usuario_a_con_empresa["usuario_id"])
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id, estado="PAUSED")
        accion, _ = crear_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], campana.id, "activar", "ACTIVE", motivo="x")
        aprobar_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], accion.id)
        accion_id = accion.id

    _mockear_meta(monkeypatch, respuestas_get=[{"status": "PAUSED"}, {"status": "ACTIVE"}])
    with client.application.app_context():
        resultado, error = ejecutar_accion(empresa_id, usuario_a_con_empresa["usuario_id"], accion_id, confirmacion=True)
        assert error is None
        assert resultado.estado == "ejecutada"


def test_ejecutar_accion_modificar_presupuesto_exitosa(client, usuario_a_con_empresa, monkeypatch):
    from app.extensions import db
    from app.services.meta.acciones import aprobar_propuesta, crear_propuesta, ejecutar_accion

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        _crear_conexion(client, empresa_id, usuario_a_con_empresa["usuario_id"])
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id, presupuesto_diario="500000")
        accion, _ = crear_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], campana.id, "modificar_presupuesto", "650000", motivo="x")
        aprobar_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], accion.id)
        accion_id, campana_id = accion.id, campana.id

    _mockear_meta(monkeypatch, respuestas_get=[{"daily_budget": "500000"}, {"daily_budget": "650000"}])
    with client.application.app_context():
        resultado, error = ejecutar_accion(empresa_id, usuario_a_con_empresa["usuario_id"], accion_id, confirmacion=True)
        assert error is None
        assert resultado.estado == "ejecutada"

        campana_actualizada = db.session.get(EntidadPublicitaria, campana_id)
        assert campana_actualizada.atributos["presupuesto_diario"] == "650000"


def test_ejecutar_accion_valor_actual_cambio_desde_propuesta_no_ejecuta(client, usuario_a_con_empresa, monkeypatch):
    """Si el valor real en Meta ya no coincide con el capturado al
    crear la propuesta (alguien mas lo cambio mientras tanto), nunca se
    sobreescribe a ciegas."""
    from app.services.meta.acciones import aprobar_propuesta, crear_propuesta, ejecutar_accion

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        _crear_conexion(client, empresa_id, usuario_a_con_empresa["usuario_id"])
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id, estado="ACTIVE")
        accion, _ = crear_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], campana.id, "pausar", "PAUSED", motivo="x")
        aprobar_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], accion.id)
        accion_id = accion.id

    # El pre-chequeo ahora encuentra "PAUSED" (alguien mas ya lo pauso).
    _mockear_meta(monkeypatch, respuestas_get=[{"status": "PAUSED"}])
    with client.application.app_context():
        resultado, error = ejecutar_accion(empresa_id, usuario_a_con_empresa["usuario_id"], accion_id, confirmacion=True)
        assert resultado is None
        assert "cambió" in error.lower()

        from app.services.meta.acciones import obtener_accion

        assert obtener_accion(empresa_id, accion_id).estado == "error"


def test_ejecutar_accion_error_de_meta_en_escritura_no_marca_ejecutada(client, usuario_a_con_empresa, monkeypatch):
    from app.services.meta.acciones import aprobar_propuesta, crear_propuesta, ejecutar_accion
    from app.services.meta.client import MetaAPIError

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        _crear_conexion(client, empresa_id, usuario_a_con_empresa["usuario_id"])
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id, estado="ACTIVE")
        accion, _ = crear_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], campana.id, "pausar", "PAUSED", motivo="x")
        aprobar_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], accion.id)
        accion_id = accion.id

    _mockear_meta(monkeypatch, respuestas_get=[{"status": "ACTIVE"}], respuesta_post=MetaAPIError("Insufficient permission", codigo=200))
    with client.application.app_context():
        resultado, error = ejecutar_accion(empresa_id, usuario_a_con_empresa["usuario_id"], accion_id, confirmacion=True)
        assert resultado is None
        assert error is not None

        from app.services.meta.acciones import obtener_accion

        accion_final = obtener_accion(empresa_id, accion_id)
        assert accion_final.estado == "error"
        assert accion_final.error_mensaje is not None
        assert "code=200" in accion_final.error_mensaje  # detalle tecnico completo, no solo el mensaje generico


def test_ejecutar_accion_verificacion_posterior_detecta_discrepancia(client, usuario_a_con_empresa, monkeypatch):
    """Meta responde 200 al escribir, pero la relectura NO confirma el
    cambio esperado -- nunca se asume exito solo porque la escritura no
    lanzo un error (Paso 12, punto 10)."""
    from app.services.meta.acciones import aprobar_propuesta, crear_propuesta, ejecutar_accion

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        _crear_conexion(client, empresa_id, usuario_a_con_empresa["usuario_id"])
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id, estado="ACTIVE")
        accion, _ = crear_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], campana.id, "pausar", "PAUSED", motivo="x")
        aprobar_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], accion.id)
        accion_id = accion.id

    # Verificacion posterior sigue devolviendo "ACTIVE" -- el cambio NO se aplico de verdad.
    _mockear_meta(monkeypatch, respuestas_get=[{"status": "ACTIVE"}, {"status": "ACTIVE"}])
    with client.application.app_context():
        resultado, error = ejecutar_accion(empresa_id, usuario_a_con_empresa["usuario_id"], accion_id, confirmacion=True)
        assert resultado is None
        assert "no reportó" in error.lower()

        from app.services.meta.acciones import obtener_accion

        assert obtener_accion(empresa_id, accion_id).estado == "error"


# --- Auditoria completa -------------------------------------------------------------------

def test_auditoria_completa_tras_ejecucion(client, usuario_a_con_empresa, monkeypatch):
    """QUIEN / QUE / CUANDO / POR QUE / QUE PASO -- Paso 12, punto 9."""
    from app.services.meta.acciones import aprobar_propuesta, crear_propuesta, ejecutar_accion

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        usuario_id = usuario_a_con_empresa["usuario_id"]
        _crear_conexion(client, empresa_id, usuario_id)
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id, estado="ACTIVE")
        accion, _ = crear_propuesta(empresa_id, usuario_id, campana.id, "pausar", "PAUSED", motivo="Costo elevado.")
        aprobar_propuesta(empresa_id, usuario_id, accion.id)
        accion_id = accion.id

    _mockear_meta(monkeypatch, respuestas_get=[{"status": "ACTIVE"}, {"status": "PAUSED"}])
    with client.application.app_context():
        ejecutar_accion(empresa_id, usuario_id, accion_id, confirmacion=True)

        from app.services.meta.acciones import obtener_accion

        auditoria = obtener_accion(empresa_id, accion_id)
        assert auditoria.empresa_id == empresa_id  # empresa
        assert auditoria.propuesto_por == usuario_id  # quien
        assert auditoria.entidad_id is not None  # recurso
        assert auditoria.tipo_accion == "pausar"  # accion
        assert auditoria.valor_actual == "ACTIVE"  # valor anterior
        assert auditoria.valor_propuesto == "PAUSED"  # valor nuevo
        assert auditoria.motivo == "Costo elevado."  # por que
        assert auditoria.estado == "ejecutada"  # que paso
        assert auditoria.resultado_meta is not None  # respuesta resumida de Meta
        assert auditoria.ejecutado_en is not None  # cuando
        assert auditoria.error_mensaje is None


# --- Reversion (preparar, nunca ejecutar automaticamente) ---------------------------------

def test_preparar_reversion_solo_para_ejecutada(client, usuario_a_con_empresa):
    from app.services.meta.acciones import crear_propuesta, preparar_reversion

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        accion, _ = crear_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], campana.id, "pausar", "PAUSED", motivo="x")

        resultado, error = preparar_reversion(empresa_id, accion.id)
        assert resultado is None
        assert "ejecutada" in error.lower()


def test_preparar_reversion_devuelve_el_valor_anterior(client, usuario_a_con_empresa, monkeypatch):
    from app.services.meta.acciones import aprobar_propuesta, crear_propuesta, ejecutar_accion, preparar_reversion

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        _crear_conexion(client, empresa_id, usuario_a_con_empresa["usuario_id"])
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id, estado="ACTIVE")
        accion, _ = crear_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], campana.id, "pausar", "PAUSED", motivo="x")
        aprobar_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], accion.id)
        accion_id = accion.id

    _mockear_meta(monkeypatch, respuestas_get=[{"status": "ACTIVE"}, {"status": "PAUSED"}])
    with client.application.app_context():
        ejecutar_accion(empresa_id, usuario_a_con_empresa["usuario_id"], accion_id, confirmacion=True)

        propuesta_reversion, error = preparar_reversion(empresa_id, accion_id)
        assert error is None
        assert propuesta_reversion["valor_propuesto"] == "ACTIVE"  # el valor de ANTES de la accion original
        assert propuesta_reversion["tipo_accion"] == "pausar"


# --- Aislamiento multiempresa (rutas) ------------------------------------------------------

def test_ruta_acciones_detalle_de_otra_empresa_da_404(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.meta.acciones import crear_propuesta

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id, nombre="Campaña secreta de A")
        accion, _ = crear_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], campana.id, "pausar", "PAUSED", motivo="x")
        accion_id = accion.id

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp = client.get(f"/datos-meta/acciones/{accion_id}")
    assert resp.status_code == 404


def test_ruta_acciones_lista_aislada_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.meta.acciones import crear_propuesta

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id, nombre="Campaña secreta de A")
        crear_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], campana.id, "pausar", "PAUSED", motivo="x")

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp = client.get("/datos-meta/acciones")
    assert resp.status_code == 200
    assert "Campaña secreta de A" not in resp.get_data(as_text=True)


def test_ruta_acciones_aprobar_de_otra_empresa_rechazada(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.meta.acciones import crear_propuesta

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id)
        accion, _ = crear_propuesta(empresa_id, usuario_a_con_empresa["usuario_id"], campana.id, "pausar", "PAUSED", motivo="x")
        accion_id = accion.id

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp = client.post(f"/datos-meta/acciones/{accion_id}/aprobar")
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


# --- Ruta completa: creacion -> aprobacion -> ejecucion end-to-end ------------------------

def test_ruta_crear_aprobar_y_ejecutar_end_to_end(client, usuario_a_con_empresa, monkeypatch):
    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        _crear_conexion(client, empresa_id, usuario_a_con_empresa["usuario_id"])
        cuenta = _crear_cuenta(empresa_id)
        campana = _crear_campana(empresa_id, "c1", cuenta.id, estado="ACTIVE", nombre="Bendetto — Conversiones")
        campana_id = campana.id

    resp_crear = client.post("/datos-meta/acciones/crear", json={
        "entidad_id": campana_id, "tipo_accion": "pausar", "valor_propuesto": "PAUSED", "motivo": "Costo por resultado muy alto.",
    })
    assert resp_crear.status_code == 201
    accion_id = resp_crear.get_json()["accion_id"]

    resp_detalle = client.get(f"/datos-meta/acciones/{accion_id}")
    assert resp_detalle.status_code == 200
    assert "Bendetto" in resp_detalle.get_data(as_text=True)
    assert "pendiente de aprobacion" in resp_detalle.get_data(as_text=True).lower()

    # Sin aprobar todavia, ejecutar debe fallar.
    resp_ejecutar_temprano = client.post(f"/datos-meta/acciones/{accion_id}/ejecutar", json={"confirmacion": True})
    assert resp_ejecutar_temprano.status_code == 400

    resp_aprobar = client.post(f"/datos-meta/acciones/{accion_id}/aprobar")
    assert resp_aprobar.status_code == 200
    assert resp_aprobar.get_json()["estado"] == "aprobada"

    # Sin confirmacion=true, tampoco ejecuta.
    resp_sin_confirmar = client.post(f"/datos-meta/acciones/{accion_id}/ejecutar", json={"confirmacion": False})
    assert resp_sin_confirmar.status_code == 400

    with client.application.app_context():
        _mockear_meta(monkeypatch, respuestas_get=[{"status": "ACTIVE"}, {"status": "PAUSED"}])

    resp_ejecutar = client.post(f"/datos-meta/acciones/{accion_id}/ejecutar", json={"confirmacion": True})
    assert resp_ejecutar.status_code == 200
    assert resp_ejecutar.get_json()["accion"]["estado"] == "ejecutada"
