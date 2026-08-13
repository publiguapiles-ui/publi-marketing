"""Pruebas del Paso 1 de Datos de Meta: cifrado de tokens, aislamiento
multiempresa en conexiones/entidades/metricas, motor universal de
metricas (catalogo, nativa vs calculada), flujo de conexion (estado
"no configurado", validacion CSRF del callback) y descubrimiento de
cuentas contra un MetaClient mockeado (sin red real).
"""

import datetime

from tests.conftest import iniciar_sesion_de_prueba


# --- Cifrado de tokens --------------------------------------------------------

def test_cifrar_y_descifrar_token():
    from app.core.crypto import cifrar, descifrar

    original = "EAABtoken-de-prueba-1234567890"
    cifrado = cifrar(original)
    assert cifrado != original
    assert descifrar(cifrado) == original


def test_descifrar_valor_invalido_devuelve_none():
    from app.core.crypto import descifrar

    assert descifrar("esto-no-es-un-token-fernet-valido") is None


# --- Conexiones: aislamiento multiempresa ---------------------------------------

def test_crear_conexion_cifra_el_token_en_la_base_de_datos(client, usuario_a_con_empresa):
    from app.services.meta.conexiones import crear_conexion

    with client.application.app_context():
        conexion = crear_conexion(
            usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"],
            "1234567890", "Usuario de Prueba", "token-secreto-real", expira_en_segundos=3600,
            scopes=["ads_read"],
        )
        assert conexion.access_token_cifrado != "token-secreto-real"

        from app.services.meta.conexiones import obtener_token_descifrado
        assert obtener_token_descifrado(conexion) == "token-secreto-real"


def test_obtener_conexion_activa_no_ve_conexion_de_otra_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.meta.conexiones import crear_conexion, obtener_conexion_activa

    with client.application.app_context():
        crear_conexion(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "111", "A", "token-a")

        conexion_b = obtener_conexion_activa(usuario_b_con_empresa["empresa_id"])
        assert conexion_b is None

        conexion_a = obtener_conexion_activa(usuario_a_con_empresa["empresa_id"])
        assert conexion_a is not None
        assert conexion_a.empresa_id == usuario_a_con_empresa["empresa_id"]


def test_reconectar_marca_la_conexion_anterior_como_revocada(client, usuario_a_con_empresa):
    from app.services.meta.conexiones import crear_conexion, obtener_conexion_activa

    with client.application.app_context():
        primera = crear_conexion(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "111", "A", "token-1")
        segunda = crear_conexion(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "111", "A", "token-2")

        from app.extensions import db
        from app.models import MetaConexion

        primera_recargada = db.session.get(MetaConexion, primera.id)
        assert primera_recargada.estado == "revocada"

        activa = obtener_conexion_activa(usuario_a_con_empresa["empresa_id"])
        assert activa.id == segunda.id


def test_no_se_puede_desconectar_conexion_de_otra_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.meta.conexiones import crear_conexion, desconectar

    with client.application.app_context():
        conexion = crear_conexion(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "111", "A", "token-a")
        conexion_id = conexion.id

    ok, error = desconectar(usuario_b_con_empresa["empresa_id"], conexion_id)
    assert ok is False
    assert error is not None

    from app.services.meta.conexiones import obtener_conexion_activa
    with client.application.app_context():
        assert obtener_conexion_activa(usuario_a_con_empresa["empresa_id"]) is not None  # sigue activa


# --- EntidadPublicitaria: aislamiento multiempresa -------------------------------

def test_entidades_publicitarias_aisladas_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.extensions import db
    from app.models import EntidadPublicitaria
    from app.services.meta.conexiones import crear_conexion
    from app.services.meta.cuentas_service import listar_entidades_empresa

    with client.application.app_context():
        conexion_a = crear_conexion(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "111", "A", "token-a")
        db.session.add(EntidadPublicitaria(
            empresa_id=usuario_a_con_empresa["empresa_id"], conexion_id=conexion_a.id,
            fuente="meta", tipo="cuenta_publicitaria", id_externo="act_123", nombre="Cuenta A",
        ))
        db.session.commit()

        entidades_b = listar_entidades_empresa(usuario_b_con_empresa["empresa_id"])
        assert entidades_b == []

        entidades_a = listar_entidades_empresa(usuario_a_con_empresa["empresa_id"])
        assert len(entidades_a) == 1
        assert entidades_a[0].nombre == "Cuenta A"


# --- Motor universal de metricas -------------------------------------------------

def test_catalogo_distingue_nativa_de_calculada(client, usuario_a_con_empresa):
    from app.services.metricas import obtener_catalogo

    with client.application.app_context():
        catalogo = obtener_catalogo()
        por_clave = {c.clave: c for c in catalogo}
        assert por_clave["spend"].origen == "nativa"
        assert por_clave["impressions"].origen == "nativa"
        assert por_clave["ctr"].origen == "calculada"
        assert por_clave["ctr"].formula is not None
        assert por_clave["cpc"].origen == "calculada"
        assert por_clave["cpm"].origen == "calculada"


def test_registrar_metrica_desconocida_falla(client, usuario_a_con_empresa):
    from app.services.metricas import registrar_metrica

    with client.application.app_context():
        try:
            registrar_metrica(usuario_a_con_empresa["empresa_id"], "metrica_inventada_que_no_existe", 1.0, datetime.date.today())
            assert False, "debia lanzar ValueError"
        except ValueError:
            pass


def test_registrar_metricas_nativas_y_calculadas_produce_los_valores_correctos(client, usuario_a_con_empresa):
    from app.services.metricas import registrar_metricas_nativas_y_calculadas

    with client.application.app_context():
        filas = registrar_metricas_nativas_y_calculadas(
            usuario_a_con_empresa["empresa_id"], entidad_id=None, entidad_tipo="campana",
            valores_nativos={"spend": 100.0, "impressions": 20000, "clicks": 250},
            fecha=datetime.date.today(),
        )
        por_nombre = {f.metrica_nombre: f for f in filas}
        assert por_nombre["spend"].origen == "nativa"
        assert por_nombre["ctr"].origen == "calculada"
        assert round(por_nombre["ctr"].valor, 2) == 1.25  # 250/20000*100
        assert round(por_nombre["cpc"].valor, 2) == 0.40  # 100/250
        assert round(por_nombre["cpm"].valor, 2) == 5.0   # 100/20000*1000


def test_consultar_metricas_aislado_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.metricas import consultar_metricas, registrar_metrica

    with client.application.app_context():
        registrar_metrica(usuario_a_con_empresa["empresa_id"], "spend", 50.0, datetime.date.today())

        assert len(consultar_metricas(usuario_a_con_empresa["empresa_id"])) == 1
        assert len(consultar_metricas(usuario_b_con_empresa["empresa_id"])) == 0


def test_metrica_guarda_snapshot_de_tipo_valor_y_origen(client, usuario_a_con_empresa):
    """Aunque el catalogo cambie despues, una fila de Metrica ya
    guardada no debe cambiar de significado -- mismo principio que
    FotografiaDerivada.preset_version en Photo Studio."""
    from app.extensions import db
    from app.models import CatalogoMetrica
    from app.services.metricas import registrar_metrica

    with client.application.app_context():
        fila = registrar_metrica(usuario_a_con_empresa["empresa_id"], "ctr", 2.5, datetime.date.today())
        assert fila.origen == "calculada"
        assert fila.tipo_valor == "porcentaje"

        # cambiar el catalogo despues no debe afectar la fila ya guardada
        catalogo = db.session.query(CatalogoMetrica).filter_by(clave="ctr").first()
        catalogo.tipo_valor = "numero"
        db.session.commit()

        fila_recargada = db.session.get(type(fila), fila.id)
        assert fila_recargada.tipo_valor == "porcentaje"  # sin cambios


# --- Rutas: pantalla de Conexiones -----------------------------------------------

def test_conexiones_requiere_login(client):
    resp = client.get("/datos-meta/conexiones")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_conexiones_muestra_no_configurado_sin_variables_de_entorno(client, usuario_a_con_empresa, monkeypatch):
    monkeypatch.delenv("META_APP_ID", raising=False)
    monkeypatch.delenv("META_APP_SECRET", raising=False)
    monkeypatch.delenv("META_REDIRECT_URI", raising=False)

    resp = client.get("/datos-meta/conexiones")
    assert resp.status_code == 200
    assert "no está configurado" in resp.get_data(as_text=True)


def test_conectar_sin_configuracion_no_llama_a_meta_y_redirige(client, usuario_a_con_empresa, monkeypatch):
    monkeypatch.delenv("META_APP_ID", raising=False)
    resp = client.get("/datos-meta/conexiones/conectar")
    assert resp.status_code == 302
    assert "/datos-meta/conexiones" in resp.headers["Location"]


def test_callback_rechaza_state_invalido(client, usuario_a_con_empresa):
    with client.session_transaction() as sess:
        sess["meta_oauth_estado"] = "estado-real"
        sess["meta_oauth_empresa_id"] = usuario_a_con_empresa["empresa_id"]

    resp = client.get("/datos-meta/conexiones/callback?state=estado-falso&code=abc")
    assert resp.status_code == 200
    assert "no es válida o expiró" in resp.get_data(as_text=True)

    from app.services.meta.conexiones import obtener_conexion_activa
    with client.application.app_context():
        assert obtener_conexion_activa(usuario_a_con_empresa["empresa_id"]) is None


def test_callback_sin_state_previo_en_sesion_es_rechazado(client, usuario_a_con_empresa):
    resp = client.get("/datos-meta/conexiones/callback?state=cualquiera&code=abc")
    assert resp.status_code == 200
    assert "no es válida o expiró" in resp.get_data(as_text=True)


def test_callback_con_error_de_meta_se_muestra_sin_crashear(client, usuario_a_con_empresa):
    resp = client.get("/datos-meta/conexiones/callback?error=access_denied&error_description=El+usuario+cancelo")
    assert resp.status_code == 200
    assert "El usuario cancelo" in resp.get_data(as_text=True)


def test_desconectar_ruta_aislada_entre_empresas(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.meta.conexiones import crear_conexion

    iniciar_sesion_de_prueba(client, usuario_a_con_empresa["usuario_id"], "a@example.com")
    with client.application.app_context():
        conexion = crear_conexion(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "111", "A", "token-a")
        conexion_id = conexion.id

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp = client.post(f"/datos-meta/conexiones/{conexion_id}/desconectar")
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


# --- Descubrimiento de cuentas (MetaClient mockeado, sin red real) --------------

def _mockear_get_meta(monkeypatch, mapa_respuestas):
    """`mapa_respuestas` es {ruta_o_prefijo: respuesta_dict}. No hace
    ninguna llamada de red real -- reemplaza MetaClient.get."""
    import app.services.meta.client as client_mod

    def _get_falso(self, ruta, params=None, access_token=None):
        for prefijo, respuesta in mapa_respuestas.items():
            if ruta == prefijo or ruta.startswith(prefijo):
                return respuesta
        raise AssertionError(f"ruta inesperada en el mock: {ruta}")

    monkeypatch.setattr(client_mod.MetaClient, "get", _get_falso)
    monkeypatch.setattr(client_mod.MetaClient, "get_todas_las_paginas", lambda self, ruta, params=None, limite_paginas=20: _get_falso(self, ruta, params).get("data", []))


def test_listar_activos_disponibles_no_persiste_nada(client, usuario_a_con_empresa, monkeypatch):
    """Paso 2, punto 4: descubrir NUNCA debe escribir en la base de
    datos por si solo -- solo devuelve la lista para elegir."""
    from app.extensions import db
    from app.models import EntidadPublicitaria
    from app.services.meta.conexiones import crear_conexion

    with client.application.app_context():
        crear_conexion(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "111", "A", "token-a")

    _mockear_get_meta(monkeypatch, {
        "me/adaccounts": {"data": [{"account_id": "123456", "name": "Cuenta Principal", "currency": "USD", "timezone_name": "America/Costa_Rica", "account_status": 1}]},
        "me/accounts": {"data": [{"id": "987654", "name": "Página de prueba", "category": "Restaurante", "instagram_business_account": {"id": "555111"}}]},
    })

    from app.services.meta.cuentas_service import listar_activos_disponibles, listar_entidades_empresa

    with client.application.app_context():
        disponibles, error = listar_activos_disponibles(usuario_a_con_empresa["empresa_id"])
        assert error is None
        assert len(disponibles["cuentas_publicitarias"]) == 1
        assert disponibles["cuentas_publicitarias"][0]["id_externo"] == "act_123456"
        assert len(disponibles["paginas"]) == 1
        assert disponibles["paginas"][0]["instagram"]["id_externo"] == "555111"

        assert listar_entidades_empresa(usuario_a_con_empresa["empresa_id"]) == []
        assert db.session.query(EntidadPublicitaria).count() == 0


def test_listar_activos_sin_conexion_devuelve_error_controlado(client, usuario_a_con_empresa):
    from app.services.meta.cuentas_service import listar_activos_disponibles

    with client.application.app_context():
        disponibles, error = listar_activos_disponibles(usuario_a_con_empresa["empresa_id"])
        assert disponibles is None
        assert error is not None


def test_vincular_activos_solo_persiste_lo_seleccionado(client, usuario_a_con_empresa):
    from app.services.meta.conexiones import crear_conexion
    from app.services.meta.cuentas_service import listar_entidades_empresa, vincular_activos

    with client.application.app_context():
        crear_conexion(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "111", "A", "token-a")

        seleccion = [
            {"tipo": "cuenta_publicitaria", "id_externo": "act_123456", "nombre": "Cuenta Principal", "atributos": {"moneda": "USD"}},
            {"tipo": "pagina", "id_externo": "987654", "nombre": "Página de prueba", "atributos": {"categoria": "Restaurante"}},
            {"tipo": "cuenta_instagram", "id_externo": "555111", "id_externo_padre": "987654", "atributos": {}},
        ]
        ok, error = vincular_activos(usuario_a_con_empresa["empresa_id"], seleccion)
        assert ok is True
        assert error is None

        cuentas = listar_entidades_empresa(usuario_a_con_empresa["empresa_id"], tipo="cuenta_publicitaria")
        assert len(cuentas) == 1
        assert cuentas[0].atributos["moneda"] == "USD"

        instagram = listar_entidades_empresa(usuario_a_con_empresa["empresa_id"], tipo="cuenta_instagram")
        paginas = listar_entidades_empresa(usuario_a_con_empresa["empresa_id"], tipo="pagina")
        assert instagram[0].entidad_padre_id == paginas[0].id


def test_vincular_activos_desmarcar_desactiva_sin_borrar(client, usuario_a_con_empresa):
    """Si el usuario vincula una cuenta y luego vuelve a vincular SIN
    incluirla, debe quedar desactivada (activo=False), nunca borrada."""
    from app.extensions import db
    from app.models import EntidadPublicitaria
    from app.services.meta.conexiones import crear_conexion
    from app.services.meta.cuentas_service import vincular_activos

    with client.application.app_context():
        crear_conexion(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "111", "A", "token-a")

        vincular_activos(usuario_a_con_empresa["empresa_id"], [
            {"tipo": "cuenta_publicitaria", "id_externo": "act_1", "nombre": "Uno", "atributos": {}},
            {"tipo": "cuenta_publicitaria", "id_externo": "act_2", "nombre": "Dos", "atributos": {}},
        ])
        vincular_activos(usuario_a_con_empresa["empresa_id"], [
            {"tipo": "cuenta_publicitaria", "id_externo": "act_1", "nombre": "Uno", "atributos": {}},
        ])

        todas = db.session.query(EntidadPublicitaria).filter_by(id_externo="act_2").all()
        assert len(todas) == 1  # la fila sigue existiendo
        assert todas[0].activo is False


def test_vincular_activos_sin_conexion_falla(client, usuario_a_con_empresa):
    from app.services.meta.cuentas_service import vincular_activos

    with client.application.app_context():
        ok, error = vincular_activos(usuario_a_con_empresa["empresa_id"], [{"tipo": "cuenta_publicitaria", "id_externo": "act_1", "atributos": {}}])
        assert ok is False
        assert error is not None
