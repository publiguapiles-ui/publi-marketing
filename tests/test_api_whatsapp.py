"""Pruebas de API WhatsApp: conexion, webhook, panel de conversaciones
pendientes. Solo lectura -- no envia mensajes, no procesa IA, no es un
CRM. Cubre los 14 puntos del enunciado: conexion, webhook, recepcion
de mensaje, creacion de contacto, creacion de conversacion, contador
sin responder, contador sin abrir, ultimos 3 mensajes, aislamiento
entre empresas y seguridad de credenciales.
"""

from tests.conftest import iniciar_sesion_de_prueba


def _payload_mensaje_entrante(phone_number_id, wa_id, texto, wamid, nombre=None, timestamp=1700000000):
    contacto = {"wa_id": wa_id}
    if nombre:
        contacto["profile"] = {"name": nombre}
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "waba-id-de-prueba",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "50600000000", "phone_number_id": phone_number_id},
                    "contacts": [contacto],
                    "messages": [{
                        "from": wa_id, "id": wamid, "timestamp": str(timestamp),
                        "type": "text", "text": {"body": texto},
                    }],
                },
            }],
        }],
    }


def _conectar(empresa_id, usuario_id, phone_number_id="pn-1", access_token="token-secreto-123", verify_token="verify-secreto-456"):
    from app.services.whatsapp.conexion import guardar_conexion

    conexion, error = guardar_conexion(
        empresa_id, usuario_id, phone_number_id=phone_number_id, whatsapp_business_account_id="waba-1",
        access_token=access_token, verify_token=verify_token,
    )
    assert error is None, error
    return conexion


# --- 1. Conexion -------------------------------------------------------------------------

def test_guardar_conexion_exitosa(client, usuario_a_con_empresa):
    with client.application.app_context():
        conexion = _conectar(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])
        assert conexion.estado == "conectada"
        assert conexion.phone_number_id == "pn-1"


def test_guardar_conexion_requiere_phone_number_id(client, usuario_a_con_empresa):
    from app.services.whatsapp.conexion import guardar_conexion

    with client.application.app_context():
        conexion, error = guardar_conexion(
            usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"],
            phone_number_id="", whatsapp_business_account_id="waba-1", access_token="t", verify_token="v",
        )
        assert conexion is None
        assert "phone number id" in error.lower()


def test_guardar_conexion_requiere_access_token_la_primera_vez(client, usuario_a_con_empresa):
    from app.services.whatsapp.conexion import guardar_conexion

    with client.application.app_context():
        conexion, error = guardar_conexion(
            usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"],
            phone_number_id="pn-1", whatsapp_business_account_id="waba-1", access_token="", verify_token="v",
        )
        assert conexion is None
        assert "access token" in error.lower()


def test_reconfigurar_sin_token_conserva_el_anterior(client, usuario_a_con_empresa):
    """Editar otros campos sin volver a pegar el token no debe borrar
    la conexion -- nunca se muestra el token para poder copiarlo de
    vuelta (punto 12)."""
    from app.core.crypto import descifrar
    from app.services.whatsapp.conexion import guardar_conexion

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        _conectar(empresa_id, usuario_a_con_empresa["usuario_id"], access_token="token-original")

        conexion, error = guardar_conexion(
            empresa_id, usuario_a_con_empresa["usuario_id"],
            phone_number_id="pn-1-editado", whatsapp_business_account_id="waba-1", access_token="", verify_token="",
        )
        assert error is None
        assert conexion.phone_number_id == "pn-1-editado"
        assert descifrar(conexion.access_token_cifrado) == "token-original"


def test_estado_conexion_desconectada_sin_configurar(client, usuario_a_con_empresa):
    from app.services.whatsapp.conexion import estado_conexion

    with client.application.app_context():
        conectada, ultima_sync = estado_conexion(usuario_a_con_empresa["empresa_id"])
        assert conectada is False
        assert ultima_sync is None


# --- 2. Webhook: verificacion (handshake GET) -------------------------------------------

def test_verificar_challenge_token_valido(client, usuario_a_con_empresa):
    from app.services.whatsapp.webhook import verificar_challenge

    with client.application.app_context():
        _conectar(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], verify_token="mi-verify-token")
        assert verificar_challenge("subscribe", "mi-verify-token", "challenge-123") == "challenge-123"


def test_verificar_challenge_token_invalido(client, usuario_a_con_empresa):
    from app.services.whatsapp.webhook import verificar_challenge

    with client.application.app_context():
        _conectar(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], verify_token="mi-verify-token")
        assert verificar_challenge("subscribe", "token-incorrecto", "challenge-123") is None


def test_ruta_webhook_get_responde_challenge(client, usuario_a_con_empresa):
    with client.application.app_context():
        _conectar(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], verify_token="mi-verify-token")

    resp = client.get("/api-whatsapp/webhook?hub.mode=subscribe&hub.verify_token=mi-verify-token&hub.challenge=abc123")
    assert resp.status_code == 200
    assert resp.get_data(as_text=True) == "abc123"


def test_ruta_webhook_get_token_invalido_da_403(client, usuario_a_con_empresa):
    with client.application.app_context():
        _conectar(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], verify_token="mi-verify-token")

    resp = client.get("/api-whatsapp/webhook?hub.mode=subscribe&hub.verify_token=incorrecto&hub.challenge=abc123")
    assert resp.status_code == 403


def test_ruta_webhook_no_requiere_sesion(client, usuario_a_con_empresa):
    """El webhook lo llama Meta directamente -- nunca debe redirigir a
    login como el resto de las rutas del sistema."""
    with client.application.app_context():
        _conectar(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], verify_token="mi-verify-token")

    with client.session_transaction() as sess:
        sess.clear()  # nadie autenticado

    resp = client.get("/api-whatsapp/webhook?hub.mode=subscribe&hub.verify_token=mi-verify-token&hub.challenge=xyz")
    assert resp.status_code == 200
    assert resp.get_data(as_text=True) == "xyz"


# --- 3. Recepcion de mensaje / creacion de contacto / conversacion ----------------------

def test_procesar_evento_guarda_mensaje_y_crea_contacto(client, usuario_a_con_empresa):
    from app.extensions import db
    from app.models import WhatsAppContact, WhatsAppConversation, WhatsAppMessage
    from app.services.whatsapp.webhook import procesar_evento

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        _conectar(empresa_id, usuario_a_con_empresa["usuario_id"], phone_number_id="pn-1")

        resultado = procesar_evento(_payload_mensaje_entrante("pn-1", "50688887777", "Hola, quisiera información sobre los precios.", "wamid.1", nombre="María López"))
        assert resultado["mensajes_guardados"] == 1

        contacto = db.session.query(WhatsAppContact).filter_by(empresa_id=empresa_id, telefono="50688887777").first()
        assert contacto is not None
        assert contacto.nombre == "María López"

        conversacion = db.session.query(WhatsAppConversation).filter_by(empresa_id=empresa_id, contacto_id=contacto.id).first()
        assert conversacion is not None

        mensaje = db.session.query(WhatsAppMessage).filter_by(conversacion_id=conversacion.id).first()
        assert mensaje.contenido == "Hola, quisiera información sobre los precios."
        assert mensaje.direccion == "entrante"


def test_procesar_evento_de_phone_number_id_desconocido_no_falla(client, usuario_a_con_empresa):
    from app.services.whatsapp.webhook import procesar_evento

    with client.application.app_context():
        resultado = procesar_evento(_payload_mensaje_entrante("pn-inexistente", "50688887777", "Hola", "wamid.x"))
        assert resultado["entradas_no_reconocidas"] == 1
        assert resultado["mensajes_guardados"] == 0


def test_procesar_evento_payload_vacio_no_falla(client, usuario_a_con_empresa):
    from app.services.whatsapp.webhook import procesar_evento

    with client.application.app_context():
        resultado = procesar_evento({})
        assert resultado["mensajes_guardados"] == 0


def test_procesar_evento_mensajes_multiples_reutiliza_el_mismo_contacto_y_conversacion(client, usuario_a_con_empresa):
    """Punto 5: varios mensajes del mismo contacto son la MISMA
    conversacion, no una nueva cada vez."""
    from app.extensions import db
    from app.models import WhatsAppContact, WhatsAppConversation
    from app.services.whatsapp.webhook import procesar_evento

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        _conectar(empresa_id, usuario_a_con_empresa["usuario_id"], phone_number_id="pn-1")

        procesar_evento(_payload_mensaje_entrante("pn-1", "50688887777", "Mensaje 1", "wamid.1", timestamp=1700000000))
        procesar_evento(_payload_mensaje_entrante("pn-1", "50688887777", "Mensaje 2", "wamid.2", timestamp=1700000010))
        procesar_evento(_payload_mensaje_entrante("pn-1", "50688887777", "Mensaje 3", "wamid.3", timestamp=1700000020))

        assert db.session.query(WhatsAppContact).filter_by(empresa_id=empresa_id).count() == 1
        assert db.session.query(WhatsAppConversation).filter_by(empresa_id=empresa_id).count() == 1


def test_procesar_evento_es_idempotente_ante_reintentos_de_meta(client, usuario_a_con_empresa):
    from app.extensions import db
    from app.models import WhatsAppMessage
    from app.services.whatsapp.webhook import procesar_evento

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        _conectar(empresa_id, usuario_a_con_empresa["usuario_id"], phone_number_id="pn-1")
        payload = _payload_mensaje_entrante("pn-1", "50688887777", "Hola", "wamid.duplicado")

        r1 = procesar_evento(payload)
        r2 = procesar_evento(payload)  # Meta reintento el mismo webhook
        assert r1["mensajes_guardados"] == 1
        assert r2["mensajes_duplicados"] == 1
        assert db.session.query(WhatsAppMessage).filter_by(id_externo="wamid.duplicado").count() == 1


def test_procesar_evento_actualiza_ultima_sincronizacion(client, usuario_a_con_empresa):
    from app.services.whatsapp.conexion import estado_conexion
    from app.services.whatsapp.webhook import procesar_evento

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        _conectar(empresa_id, usuario_a_con_empresa["usuario_id"], phone_number_id="pn-1")
        assert estado_conexion(empresa_id)[1] is None

        procesar_evento(_payload_mensaje_entrante("pn-1", "50688887777", "Hola", "wamid.1"))
        assert estado_conexion(empresa_id)[1] is not None


def test_panel_ultima_sincronizacion_texto_formateado(client, usuario_a_con_empresa):
    from app.services.whatsapp.panel import construir_panel
    from app.services.whatsapp.webhook import procesar_evento

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        _conectar(empresa_id, usuario_a_con_empresa["usuario_id"], phone_number_id="pn-1")
        procesar_evento(_payload_mensaje_entrante("pn-1", "50688887777", "Hola", "wamid.1"))

        panel = construir_panel(empresa_id)
        assert panel["ultima_sincronizacion_texto"] is not None
        assert panel["ultima_sincronizacion_texto"] != panel["ultima_sincronizacion"]  # nunca el ISO crudo
        assert "/" in panel["ultima_sincronizacion_texto"]


def test_procesar_evento_mensaje_no_texto_usa_placeholder_honesto(client, usuario_a_con_empresa):
    from app.extensions import db
    from app.models import WhatsAppMessage
    from app.services.whatsapp.webhook import procesar_evento

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        _conectar(empresa_id, usuario_a_con_empresa["usuario_id"], phone_number_id="pn-1")

        payload = {
            "object": "whatsapp_business_account",
            "entry": [{"id": "waba-1", "changes": [{"field": "messages", "value": {
                "metadata": {"phone_number_id": "pn-1"},
                "contacts": [{"wa_id": "50688887777"}],
                "messages": [{"from": "50688887777", "id": "wamid.img", "timestamp": "1700000000", "type": "image"}],
            }}]}],
        }
        procesar_evento(payload)
        mensaje = db.session.query(WhatsAppMessage).filter_by(id_externo="wamid.img").first()
        assert mensaje.contenido == "[Imagen]"


# --- 5/6. Contadores: sin responder / sin abrir -----------------------------------------

def test_panel_sin_responder_cuenta_conversaciones_no_mensajes(client, usuario_a_con_empresa):
    from app.services.whatsapp.panel import construir_panel
    from app.services.whatsapp.webhook import procesar_evento

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        _conectar(empresa_id, usuario_a_con_empresa["usuario_id"], phone_number_id="pn-1")

        procesar_evento(_payload_mensaje_entrante("pn-1", "50688887777", "Mensaje 1", "wamid.1", timestamp=1700000000))
        procesar_evento(_payload_mensaje_entrante("pn-1", "50688887777", "Mensaje 2", "wamid.2", timestamp=1700000010))
        procesar_evento(_payload_mensaje_entrante("pn-1", "50688887777", "Mensaje 3", "wamid.3", timestamp=1700000020))

        panel = construir_panel(empresa_id)
        assert panel["sin_responder"] == 1  # 3 mensajes, 1 sola conversacion pendiente


def test_panel_sin_abrir_hasta_marcar_como_vista(client, usuario_a_con_empresa):
    from app.extensions import db
    from app.models import WhatsAppConversation
    from app.services.whatsapp.panel import construir_panel, marcar_conversacion_vista
    from app.services.whatsapp.webhook import procesar_evento

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        _conectar(empresa_id, usuario_a_con_empresa["usuario_id"], phone_number_id="pn-1")
        procesar_evento(_payload_mensaje_entrante("pn-1", "50688887777", "Hola", "wamid.1"))

        assert construir_panel(empresa_id)["sin_abrir"] == 1

        conversacion = db.session.query(WhatsAppConversation).filter_by(empresa_id=empresa_id).first()
        assert marcar_conversacion_vista(empresa_id, conversacion.id) is True
        assert construir_panel(empresa_id)["sin_abrir"] == 0


def test_panel_nuevo_mensaje_vuelve_a_marcar_sin_abrir(client, usuario_a_con_empresa):
    """Si ya se marco como vista y llega un mensaje nuevo, vuelve a
    contar como "sin abrir" -- nunca queda oculto un mensaje nuevo."""
    from app.extensions import db
    from app.models import WhatsAppConversation
    from app.services.whatsapp.panel import construir_panel, marcar_conversacion_vista
    from app.services.whatsapp.webhook import procesar_evento

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        _conectar(empresa_id, usuario_a_con_empresa["usuario_id"], phone_number_id="pn-1")
        procesar_evento(_payload_mensaje_entrante("pn-1", "50688887777", "Hola", "wamid.1", timestamp=1700000000))

        conversacion = db.session.query(WhatsAppConversation).filter_by(empresa_id=empresa_id).first()
        marcar_conversacion_vista(empresa_id, conversacion.id)
        assert construir_panel(empresa_id)["sin_abrir"] == 0

        procesar_evento(_payload_mensaje_entrante("pn-1", "50688887777", "Mensaje nuevo", "wamid.2", timestamp=9999999999))
        assert construir_panel(empresa_id)["sin_abrir"] == 1


def test_marcar_vista_de_conversacion_de_otra_empresa_falla(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.extensions import db
    from app.models import WhatsAppConversation
    from app.services.whatsapp.panel import marcar_conversacion_vista
    from app.services.whatsapp.webhook import procesar_evento

    with client.application.app_context():
        empresa_a = usuario_a_con_empresa["empresa_id"]
        _conectar(empresa_a, usuario_a_con_empresa["usuario_id"], phone_number_id="pn-1")
        procesar_evento(_payload_mensaje_entrante("pn-1", "50688887777", "Hola", "wamid.1"))
        conversacion = db.session.query(WhatsAppConversation).filter_by(empresa_id=empresa_a).first()

        assert marcar_conversacion_vista(usuario_b_con_empresa["empresa_id"], conversacion.id) is False


# --- 7. Ultimos 3 mensajes ---------------------------------------------------------------

def test_panel_ultimos_3_mensajes_orden_y_limite(client, usuario_a_con_empresa):
    from app.services.whatsapp.panel import construir_panel
    from app.services.whatsapp.webhook import procesar_evento

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        _conectar(empresa_id, usuario_a_con_empresa["usuario_id"], phone_number_id="pn-1")

        for i in range(5):
            procesar_evento(_payload_mensaje_entrante("pn-1", f"5068888777{i}", f"Mensaje {i}", f"wamid.{i}", timestamp=1700000000 + i * 10))

        panel = construir_panel(empresa_id)
        assert len(panel["ultimos_mensajes"]) == 3
        assert panel["ultimos_mensajes"][0]["contenido"] == "Mensaje 4"  # el mas reciente primero
        assert panel["ultimos_mensajes"][2]["contenido"] == "Mensaje 2"


def test_panel_ultimos_mensajes_no_incluye_saliente(client, usuario_a_con_empresa):
    """Solo mensajes RECIBIDOS -- nunca mensajes enviados por la
    empresa en este bloque (punto 7). No hay endpoint para enviar
    mensajes todavia; se prueba insertando uno directo a la BD."""
    from app.extensions import db
    from app.models import WhatsAppConversation, WhatsAppMessage
    from app.services.whatsapp.panel import construir_panel
    from app.services.whatsapp.webhook import procesar_evento

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        _conectar(empresa_id, usuario_a_con_empresa["usuario_id"], phone_number_id="pn-1")
        procesar_evento(_payload_mensaje_entrante("pn-1", "50688887777", "Hola", "wamid.1", timestamp=1700000000))

        conversacion = db.session.query(WhatsAppConversation).filter_by(empresa_id=empresa_id).first()
        from datetime import datetime, timezone
        db.session.add(WhatsAppMessage(
            conversacion_id=conversacion.id, direccion="saliente", contenido="Respuesta de la empresa",
            creado_en=datetime.fromtimestamp(1700000100, tz=timezone.utc),
        ))
        db.session.commit()

        panel = construir_panel(empresa_id)
        assert len(panel["ultimos_mensajes"]) == 1
        assert panel["ultimos_mensajes"][0]["contenido"] == "Hola"


# --- 8/9. Aislamiento entre empresas -----------------------------------------------------

def test_procesar_evento_aisla_contactos_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.extensions import db
    from app.models import WhatsAppContact
    from app.services.whatsapp.webhook import procesar_evento

    with client.application.app_context():
        empresa_a = usuario_a_con_empresa["empresa_id"]
        empresa_b = usuario_b_con_empresa["empresa_id"]
        _conectar(empresa_a, usuario_a_con_empresa["usuario_id"], phone_number_id="pn-a")
        _conectar(empresa_b, usuario_b_con_empresa["usuario_id"], phone_number_id="pn-b")

        # el MISMO numero de telefono escribe a las dos empresas
        procesar_evento(_payload_mensaje_entrante("pn-a", "50688887777", "Hola A", "wamid.a"))
        procesar_evento(_payload_mensaje_entrante("pn-b", "50688887777", "Hola B", "wamid.b"))

        contactos_a = db.session.query(WhatsAppContact).filter_by(empresa_id=empresa_a).all()
        contactos_b = db.session.query(WhatsAppContact).filter_by(empresa_id=empresa_b).all()
        assert len(contactos_a) == 1 and len(contactos_b) == 1
        assert contactos_a[0].id != contactos_b[0].id  # nunca se comparte el contacto entre empresas


def test_panel_aislado_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.whatsapp.panel import construir_panel
    from app.services.whatsapp.webhook import procesar_evento

    with client.application.app_context():
        empresa_a = usuario_a_con_empresa["empresa_id"]
        empresa_b = usuario_b_con_empresa["empresa_id"]
        _conectar(empresa_a, usuario_a_con_empresa["usuario_id"], phone_number_id="pn-a")
        _conectar(empresa_b, usuario_b_con_empresa["usuario_id"], phone_number_id="pn-b")

        procesar_evento(_payload_mensaje_entrante("pn-a", "50688887777", "Hola A", "wamid.a"))

        assert construir_panel(empresa_a)["sin_responder"] == 1
        assert construir_panel(empresa_b)["sin_responder"] == 0
        assert construir_panel(empresa_b)["ultimos_mensajes"] == []


def test_ruta_index_aislada_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    with client.application.app_context():
        empresa_a = usuario_a_con_empresa["empresa_id"]
        _conectar(empresa_a, usuario_a_con_empresa["usuario_id"], phone_number_id="pn-a")

        from app.services.whatsapp.webhook import procesar_evento
        procesar_evento(_payload_mensaje_entrante("pn-a", "50688887777", "Mensaje confidencial de A", "wamid.a", nombre="María López"))

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp = client.get("/api-whatsapp/")
    assert resp.status_code == 200
    assert "Mensaje confidencial de A" not in resp.get_data(as_text=True)
    assert "María López" not in resp.get_data(as_text=True)


# --- 10. Seguridad de credenciales ---------------------------------------------------

def test_access_token_nunca_se_guarda_en_texto_plano(client, usuario_a_con_empresa):
    with client.application.app_context():
        conexion = _conectar(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], access_token="token-secreto-nunca-en-claro")
        assert "token-secreto-nunca-en-claro" not in conexion.access_token_cifrado


def test_verify_token_nunca_se_guarda_en_texto_plano(client, usuario_a_con_empresa):
    with client.application.app_context():
        conexion = _conectar(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], verify_token="verify-secreto-nunca-en-claro")
        assert "verify-secreto-nunca-en-claro" not in conexion.verify_token_cifrado


def test_pagina_configuracion_nunca_muestra_el_token(client, usuario_a_con_empresa):
    with client.application.app_context():
        _conectar(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], access_token="token-secreto-en-html", verify_token="verify-secreto-en-html")

    resp = client.get("/api-whatsapp/configuracion")
    assert resp.status_code == 200
    texto = resp.get_data(as_text=True)
    assert "token-secreto-en-html" not in texto
    assert "verify-secreto-en-html" not in texto


def test_panel_json_nunca_incluye_tokens(client, usuario_a_con_empresa):
    with client.application.app_context():
        _conectar(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], access_token="token-secreto-json", verify_token="verify-secreto-json")

    resp = client.get("/api-whatsapp/panel")
    assert resp.status_code == 200
    assert "token-secreto-json" not in resp.get_data(as_text=True)
    assert "verify-secreto-json" not in resp.get_data(as_text=True)


# --- Ruta completa: configuracion + panel end-to-end -------------------------------------

def test_ruta_configuracion_guardar_end_to_end(client, usuario_a_con_empresa):
    resp = client.post("/api-whatsapp/configuracion", data={
        "phone_number_id": "pn-e2e", "whatsapp_business_account_id": "waba-e2e",
        "access_token": "token-e2e", "verify_token": "verify-e2e",
    })
    assert resp.status_code == 302

    resp_index = client.get("/api-whatsapp/")
    assert resp_index.status_code == 200
    assert "CONECTADA" in resp_index.get_data(as_text=True)


def test_ruta_index_sin_conectar_muestra_boton_conectar(client, usuario_a_con_empresa):
    resp = client.get("/api-whatsapp/")
    assert resp.status_code == 200
    texto = resp.get_data(as_text=True)
    assert "todavía no está conectado" in texto.lower()
    assert "Conectar WhatsApp" in texto
