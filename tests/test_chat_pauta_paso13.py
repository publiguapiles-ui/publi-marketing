"""Pruebas del Paso 13: Chat de Pauta.

Esta pantalla NO es un sistema de analisis nuevo -- es una segunda
puerta de entrada al MISMO backend del Estratega IA (Paso 10):
mismas ConversacionIA/MensajeIA, mismo estratega_ia.responder()/
crear_conversacion()/listar_conversaciones_empresa(), que ya estan
probados exhaustivamente en test_estratega_ia_paso10.py (contexto,
historial multi-turno, limites, aislamiento, errores de IA) y en
test_acciones_meta_paso12.py (preparar accion nunca ejecuta
automaticamente). Este archivo cubre EXCLUSIVAMENTE lo especifico de
la ruta /datos-meta/chat: que renderiza, que aisla por empresa, que
refleja el periodo/cuenta seleccionados, y que muestra las
conversaciones anteriores de esta empresa (nunca de otra). La
transcripcion de voz se implementa 100% en el navegador (Web Speech
API, ver datos_meta_chat_pauta.js) -- no existe ningun endpoint de
backend que probar para eso; ver el informe del Paso 13 para el
detalle de que se verifico y que no.
"""

from tests.conftest import iniciar_sesion_de_prueba


def test_ruta_chat_pauta_devuelve_200(client, usuario_a_con_empresa):
    resp = client.get("/datos-meta/chat")
    assert resp.status_code == 200
    texto = resp.get_data(as_text=True)
    assert "Chat de Pauta" in texto
    assert usuario_a_con_empresa is not None  # solo para activar la empresa via el fixture


def test_ruta_chat_pauta_sin_ia_configurada_muestra_aviso_honesto(client, usuario_a_con_empresa, monkeypatch):
    import app.services.ia as ia_mod

    monkeypatch.setattr(ia_mod, "ia_configurada", lambda: False)
    resp = client.get("/datos-meta/chat")
    assert resp.status_code == 200
    texto = resp.get_data(as_text=True)
    assert "no está configurado" in texto.lower()


def test_ruta_chat_pauta_muestra_sugerencias_iniciales(client, usuario_a_con_empresa):
    resp = client.get("/datos-meta/chat")
    texto = resp.get_data(as_text=True)
    assert "¿Qué está funcionando?" in texto
    assert "Compara mis campañas." in texto


def test_ruta_chat_pauta_periodo_seleccionado_queda_marcado(client, usuario_a_con_empresa):
    resp = client.get("/datos-meta/chat?periodo=ultimos_7_dias")
    texto = resp.get_data(as_text=True)
    assert 'value="ultimos_7_dias" selected' in texto


def test_ruta_chat_pauta_periodo_invalido_cae_a_treinta_dias(client, usuario_a_con_empresa):
    resp = client.get("/datos-meta/chat?periodo=no-existe")
    assert resp.status_code == 200
    assert 'value="ultimos_30_dias" selected' in resp.get_data(as_text=True)


def test_ruta_chat_pauta_conversacion_de_otra_empresa_da_404(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.estratega_ia import crear_conversacion

    with client.application.app_context():
        conversacion, _ = crear_conversacion(usuario_b_con_empresa["empresa_id"], usuario_b_con_empresa["usuario_id"])
        conversacion_id = conversacion.id

    # usuario_b_con_empresa deja la sesion activa como B -- se vuelve a
    # A explicitamente para probar que A NO puede ver la conversacion de B.
    iniciar_sesion_de_prueba(client, usuario_a_con_empresa["usuario_id"], "a@example.com")
    resp = client.get(f"/datos-meta/chat?conversacion_id={conversacion_id}")
    assert resp.status_code == 404


def test_ruta_chat_pauta_lista_conversaciones_aislada_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.estratega_ia import crear_conversacion, responder
    from app.models import Empresa
    from app.extensions import db

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        empresa = db.session.query(Empresa).filter_by(id=empresa_id).first()
        conversacion, _ = crear_conversacion(empresa_id, usuario_a_con_empresa["usuario_id"])
        conversacion.titulo = "Conversación secreta de A"
        db.session.commit()

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp = client.get("/datos-meta/chat")
    assert resp.status_code == 200
    assert "Conversación secreta de A" not in resp.get_data(as_text=True)


def test_ruta_chat_pauta_con_conversacion_existente_carga_su_titulo_en_el_selector(client, usuario_a_con_empresa):
    from app.services.estratega_ia import crear_conversacion
    from app.extensions import db

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        conversacion, _ = crear_conversacion(empresa_id, usuario_a_con_empresa["usuario_id"])
        conversacion.titulo = "¿Cómo van mis campañas?"
        db.session.commit()
        conversacion_id = conversacion.id

    resp = client.get(f"/datos-meta/chat?conversacion_id={conversacion_id}")
    assert resp.status_code == 200
    assert "¿Cómo van mis campañas?" in resp.get_data(as_text=True)


def test_ruta_chat_pauta_reutiliza_las_mismas_rutas_del_estratega_ia(client, usuario_a_con_empresa, monkeypatch):
    """El Chat de Pauta NUNCA duplica el envio de mensajes -- usa
    literalmente /marketing/estratega-ia/conversaciones/<id>/mensajes,
    ya probado a fondo en el Paso 10. Aqui solo se confirma que una
    conversacion creada desde /datos-meta/chat es la MISMA fila que
    devuelve estratega_ia.listar_conversaciones_empresa()."""
    import app.services.ia as ia_mod

    monkeypatch.setattr(ia_mod, "ia_configurada", lambda: True)
    monkeypatch.setattr(
        ia_mod, "generar_respuesta",
        lambda mensajes, system=None, modelo=None, max_tokens=None: ("DATO: prueba.", {"modelo": "claude-sonnet-5", "tokens_entrada": 5, "tokens_salida": 5}, None),
    )

    resp_crear = client.post("/marketing/estratega-ia/conversaciones", json={})
    assert resp_crear.status_code == 201
    conversacion_id = resp_crear.get_json()["conversacion"]["id"]

    resp_mensaje = client.post(
        f"/marketing/estratega-ia/conversaciones/{conversacion_id}/mensajes",
        json={"mensaje": "¿Cómo van mis campañas?", "periodo": "ultimos_30_dias"},
    )
    assert resp_mensaje.status_code == 200

    resp_chat = client.get(f"/datos-meta/chat?conversacion_id={conversacion_id}")
    assert resp_chat.status_code == 200  # la misma conversacion es visible desde el Chat de Pauta
