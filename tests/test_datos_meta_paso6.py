"""Pruebas del Paso 6: conexion real con Meta, solo lectura.

Los flujos de OAuth, descubrimiento/vinculacion de activos y
sincronizacion de campanas/conjuntos/anuncios/insights ya se
construyeron y probaron en los Pasos 1 y 2 (ver test_datos_meta.py y
test_datos_meta_paso2.py) -- este archivo cubre exclusivamente lo
nuevo del Paso 6: deteccion PROACTIVA de expiracion de token (sin
esperar un error real de Meta), que una conexion no activa (expirada/
revocada/con error) siga siendo visible en la pantalla de Conexiones
en vez de confundirse con "nunca se conecto", y que los permisos
solicitados sigan siendo unicamente de lectura.
"""

import datetime

from tests.conftest import iniciar_sesion_de_prueba


# --- Permisos de solo lectura --------------------------------------------------------

def test_scopes_predeterminados_son_solo_lectura():
    from app.services.meta.auth_service import SCOPES_PREDETERMINADOS

    permisos_de_escritura = {"ads_management", "pages_manage_posts", "pages_manage_ads", "instagram_content_publish"}
    assert not (permisos_de_escritura & set(SCOPES_PREDETERMINADOS))
    assert "ads_read" in SCOPES_PREDETERMINADOS


# --- Deteccion proactiva de expiracion ------------------------------------------------

def test_obtener_cliente_detecta_token_expirado_sin_llamar_a_meta(client, usuario_a_con_empresa, monkeypatch):
    """No debe hacer NINGUNA llamada HTTP -- si se intentara, el mock
    de abajo lanzaria un AssertionError porque no hay ruta esperada."""
    import app.services.meta.client as client_mod
    from app.services.meta.conexiones import crear_conexion, obtener_cliente_para_empresa, obtener_conexion_activa

    def _get_no_deberia_llamarse(self, ruta, params=None, access_token=None):
        raise AssertionError("obtener_cliente_para_empresa no debe llamar a Meta si el token ya expiro localmente")

    monkeypatch.setattr(client_mod.MetaClient, "get", _get_no_deberia_llamarse)

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        crear_conexion(empresa_id, usuario_a_con_empresa["usuario_id"], "111", "A", "token-viejo", expira_en_segundos=-3600)

        cliente, error = obtener_cliente_para_empresa(empresa_id)
        assert cliente is None
        assert "expiró" in error.lower()

        # la conexion ya no es "la" activa -- exactamente igual que si
        # Meta hubiera devuelto un 190 real (ver marcar_error/Paso 2)
        assert obtener_conexion_activa(empresa_id) is None


def test_obtener_cliente_con_token_vigente_no_se_marca_como_expirado(client, usuario_a_con_empresa):
    from app.services.meta.conexiones import crear_conexion, obtener_conexion_activa

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        crear_conexion(empresa_id, usuario_a_con_empresa["usuario_id"], "111", "A", "token-nuevo", expira_en_segundos=3600)

        assert obtener_conexion_activa(empresa_id) is not None
        assert obtener_conexion_activa(empresa_id).estado == "activa"


def test_obtener_cliente_sin_fecha_de_expiracion_no_falla(client, usuario_a_con_empresa):
    """expira_en_segundos=None (Meta no siempre lo devuelve) nunca debe
    tratarse como "ya expiro"."""
    from app.services.meta.conexiones import crear_conexion, obtener_cliente_para_empresa

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        crear_conexion(empresa_id, usuario_a_con_empresa["usuario_id"], "111", "A", "token-sin-expiracion")

        cliente, error = obtener_cliente_para_empresa(empresa_id)
        assert cliente is not None
        assert error is None


# --- Conexion mas reciente (visible aunque no este activa) ---------------------------

def test_obtener_conexion_mas_reciente_incluye_conexion_con_error(client, usuario_a_con_empresa):
    from app.services.meta.conexiones import crear_conexion, marcar_error, obtener_conexion_activa, obtener_conexion_mas_reciente

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        conexion = crear_conexion(empresa_id, usuario_a_con_empresa["usuario_id"], "111", "A", "token-x")
        marcar_error(conexion, "Token invalido", categoria="token_expirado")

        assert obtener_conexion_activa(empresa_id) is None  # ya no es "la" activa
        reciente = obtener_conexion_mas_reciente(empresa_id)
        assert reciente is not None
        assert reciente.estado == "error"


def test_obtener_conexion_mas_reciente_aislada_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.meta.conexiones import crear_conexion, obtener_conexion_mas_reciente

    with client.application.app_context():
        crear_conexion(usuario_b_con_empresa["empresa_id"], usuario_b_con_empresa["usuario_id"], "222", "B", "token-b")

        assert obtener_conexion_mas_reciente(usuario_a_con_empresa["empresa_id"]) is None


# --- Pantalla de Conexiones: aviso de reconexion --------------------------------------

def test_ruta_conexiones_conexion_expirada_muestra_aviso_de_reconexion(client, usuario_a_con_empresa):
    from app.services.meta.conexiones import crear_conexion, marcar_error

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        conexion = crear_conexion(empresa_id, usuario_a_con_empresa["usuario_id"], "111", "A", "token-x")
        marcar_error(conexion, "El token de acceso expiró.", categoria="token_expirado")

    resp = client.get("/datos-meta/conexiones")
    texto = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "no está activa" in texto
    assert "El token de acceso expiró." in texto


def test_ruta_conexiones_expirada_sigue_mostrando_activos_ya_sincronizados(client, usuario_a_con_empresa):
    """Una conexion expirada no debe borrar ni ocultar lo que ya se
    sincronizo mientras estuvo activa -- son datos historicos reales,
    no dependen de que el token siga funcionando."""
    from app.extensions import db
    from app.models import EntidadPublicitaria
    from app.services.meta.conexiones import crear_conexion, marcar_error

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        conexion = crear_conexion(empresa_id, usuario_a_con_empresa["usuario_id"], "111", "A", "token-x")
        cuenta = EntidadPublicitaria(
            empresa_id=empresa_id, conexion_id=conexion.id, fuente="meta", tipo="cuenta_publicitaria",
            id_externo="act_1", nombre="Cuenta ya vinculada",
        )
        db.session.add(cuenta)
        db.session.commit()
        marcar_error(conexion, "Revocado", categoria="autenticacion")

    resp = client.get("/datos-meta/conexiones")
    texto = resp.get_data(as_text=True)
    assert "Cuenta ya vinculada" in texto


def test_ruta_conexiones_activa_sigue_mostrando_boton_sincronizar(client, usuario_a_con_empresa):
    from app.services.meta.conexiones import crear_conexion

    with client.application.app_context():
        crear_conexion(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "111", "A", "token-x")

    resp = client.get("/datos-meta/conexiones")
    texto = resp.get_data(as_text=True)
    assert "Sincronizar ahora" in texto
    assert "no está activa" not in texto


def test_ruta_conexiones_sin_ninguna_conexion_muestra_estado_no_conectado(client, usuario_a_con_empresa):
    # Este entorno de pruebas no tiene META_APP_ID configurado, asi que
    # el mensaje exacto es "Meta no está configurado" en vez de
    # "Todavía no has conectado Meta" -- en ambos casos, sin conexion
    # nunca debe aparecer el panel "Estado de la conexión".
    resp = client.get("/datos-meta/conexiones")
    texto = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "estado-vacio" in texto
    assert "Estado de la conexión" not in texto


def test_ruta_conexiones_aislamiento_entre_empresas(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.meta.conexiones import crear_conexion

    with client.application.app_context():
        crear_conexion(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "111", "A", "token-a")

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp = client.get("/datos-meta/conexiones")
    texto = resp.get_data(as_text=True)
    assert "token-a" not in texto
    assert "Estado de la conexión" not in texto  # B nunca ve la conexion de A
