"""Pruebas de Photo Studio: proyectos, fotografias, storage y seguridad.

Las llamadas reales a Supabase Storage se mockean (unitarias, rapidas,
sin depender de la red); la integracion real contra Supabase se probo
manualmente y se documenta en el informe del Paso 6.
"""

import io

from tests.conftest import iniciar_sesion_de_prueba

PNG_MINIMO = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
    b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0fIDATx\x9cc\xf8\xcf\xc0\xf0\x1f\x00\x05"
    b"\x00\x01\xffI\x19\xc4D\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _mockear_storage(monkeypatch, rutas_subidas):
    """Reemplaza las llamadas reales a Supabase Storage por dobles de
    prueba: no hay red, no hace falta SUPABASE_KEY en el entorno de test.
    """
    import app.modules.fotografia.routes as rutas_mod

    monkeypatch.setattr(rutas_mod, "storage_configurado", lambda: True)

    def _subir_falso(bucket, ruta, contenido, tipo_mime):
        rutas_subidas.append((bucket, ruta, tipo_mime, len(contenido)))

    monkeypatch.setattr(rutas_mod, "subir_archivo", _subir_falso)
    monkeypatch.setattr(rutas_mod, "url_firmada", lambda *a, **k: "https://ejemplo.supabase.co/firmada")


# --- Seguridad -----------------------------------------------------------

def test_photo_studio_sin_autenticar_redirige_a_login(client):
    resp = client.get("/photo-studio/")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_crear_proyecto_sin_autenticar_redirige_a_login(client):
    resp = client.post("/photo-studio/proyectos/nuevo", data={"nombre": "X"})
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_usuario_autenticado_con_empresa_activa_accede(client, usuario_a_con_empresa):
    resp = client.get("/photo-studio/")
    assert resp.status_code == 200
    assert "Photo Studio".encode() in resp.data


# --- Proyectos -------------------------------------------------------------

def test_crear_proyecto_lo_asocia_a_la_empresa_activa(client, usuario_a_con_empresa):
    resp = client.post(
        "/photo-studio/proyectos/nuevo",
        data={"nombre": "Sesion Agosto", "descripcion": "Fotos de productos"},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    from app.services.fotografia import obtener_proyectos_empresa

    with client.application.app_context():
        proyectos = obtener_proyectos_empresa(usuario_a_con_empresa["empresa_id"])
        assert len(proyectos) == 1
        assert proyectos[0].nombre == "Sesion Agosto"
        assert proyectos[0].empresa_id == usuario_a_con_empresa["empresa_id"]


def test_proyecto_de_otra_empresa_no_es_accesible(client, usuario_a_con_empresa, usuario_b_con_empresa):
    # Ambas fixtures inician sesion al crearse; nos aseguramos de que
    # la sesion activa sea la de A antes de que A cree su proyecto.
    iniciar_sesion_de_prueba(client, usuario_a_con_empresa["usuario_id"], "a@example.com")
    client.post("/photo-studio/proyectos/nuevo", data={"nombre": "Proyecto de A"})
    from app.services.fotografia import obtener_proyectos_empresa

    with client.application.app_context():
        proyecto_id = obtener_proyectos_empresa(usuario_a_con_empresa["empresa_id"])[0].id

    # Sesion pasa a ser la de B (su propia empresa, distinta de la de A).
    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")

    resp = client.get(f"/photo-studio/proyectos/{proyecto_id}")
    assert resp.status_code == 404


# --- Fotografias -----------------------------------------------------------

def test_subir_fotografia_la_asocia_al_proyecto_y_registra_metadata(client, usuario_a_con_empresa, monkeypatch):
    rutas_subidas = []
    _mockear_storage(monkeypatch, rutas_subidas)

    creado = client.post("/photo-studio/proyectos/nuevo", data={"nombre": "Proyecto Fotos"})
    from app.services.fotografia import obtener_proyectos_empresa

    with client.application.app_context():
        proyecto = obtener_proyectos_empresa(usuario_a_con_empresa["empresa_id"])[0]

    resp = client.post(
        f"/photo-studio/proyectos/{proyecto.id}/fotos",
        data={"archivo": (io.BytesIO(PNG_MINIMO), "foto.png")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201
    cuerpo = resp.get_json()
    assert cuerpo["ok"] is True

    from app.services.fotografia import obtener_fotografias_proyecto

    with client.application.app_context():
        fotos = obtener_fotografias_proyecto(proyecto.id)
        assert len(fotos) == 1
        foto = fotos[0]
        assert foto.proyecto_id == proyecto.id
        assert foto.empresa_id == usuario_a_con_empresa["empresa_id"]
        assert foto.nombre_archivo_original == "foto.png"
        assert foto.tipo_mime == "image/png"
        assert foto.tamano_bytes == len(PNG_MINIMO)
        assert foto.estado == "original"
        assert foto.subido_por == usuario_a_con_empresa["usuario_id"]

    # Se subio realmente al bucket de fotografias, con la ruta esperada.
    assert len(rutas_subidas) == 1
    bucket, ruta, tipo_mime, tamano = rutas_subidas[0]
    assert bucket == "fotografias"
    assert f"empresas/{usuario_a_con_empresa['empresa_id']}/fotografia/proyectos/{proyecto.id}/originales/" in ruta
    assert tipo_mime == "image/png"


def test_subir_fotografia_formato_no_soportado_es_rechazado(client, usuario_a_con_empresa, monkeypatch):
    rutas_subidas = []
    _mockear_storage(monkeypatch, rutas_subidas)

    client.post("/photo-studio/proyectos/nuevo", data={"nombre": "Proyecto Fotos"})
    from app.services.fotografia import obtener_proyectos_empresa

    with client.application.app_context():
        proyecto = obtener_proyectos_empresa(usuario_a_con_empresa["empresa_id"])[0]

    resp = client.post(
        f"/photo-studio/proyectos/{proyecto.id}/fotos",
        data={"archivo": (io.BytesIO(b"esto no es una imagen"), "falso.png")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False
    assert rutas_subidas == []  # nunca llego a "subirse"


def test_fotografia_de_otra_empresa_no_es_accesible(client, usuario_a_con_empresa, usuario_b_con_empresa, monkeypatch):
    rutas_subidas = []
    _mockear_storage(monkeypatch, rutas_subidas)

    iniciar_sesion_de_prueba(client, usuario_a_con_empresa["usuario_id"], "a@example.com")
    client.post("/photo-studio/proyectos/nuevo", data={"nombre": "Proyecto de A"})
    from app.services.fotografia import obtener_proyectos_empresa

    with client.application.app_context():
        proyecto = obtener_proyectos_empresa(usuario_a_con_empresa["empresa_id"])[0]

    client.post(
        f"/photo-studio/proyectos/{proyecto.id}/fotos",
        data={"archivo": (io.BytesIO(PNG_MINIMO), "foto.png")},
        content_type="multipart/form-data",
    )
    from app.services.fotografia import obtener_fotografias_proyecto

    with client.application.app_context():
        foto_id = obtener_fotografias_proyecto(proyecto.id)[0].id

    # B nunca tuvo acceso a la empresa de A.
    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")

    assert client.get(f"/photo-studio/fotos/{foto_id}").status_code == 404
    assert client.get(f"/photo-studio/fotos/{foto_id}/descargar").status_code == 404
    resp_eliminar = client.post(f"/photo-studio/fotos/{foto_id}/eliminar")
    assert resp_eliminar.status_code == 404

    # A si puede ver su propia fotografia.
    iniciar_sesion_de_prueba(client, usuario_a_con_empresa["usuario_id"], "a@example.com")
    assert client.get(f"/photo-studio/fotos/{foto_id}").status_code == 200


def test_eliminar_fotografia_es_soft_delete(client, usuario_a_con_empresa, monkeypatch):
    rutas_subidas = []
    _mockear_storage(monkeypatch, rutas_subidas)

    client.post("/photo-studio/proyectos/nuevo", data={"nombre": "Proyecto Fotos"})
    from app.services.fotografia import obtener_proyectos_empresa

    with client.application.app_context():
        proyecto = obtener_proyectos_empresa(usuario_a_con_empresa["empresa_id"])[0]

    client.post(
        f"/photo-studio/proyectos/{proyecto.id}/fotos",
        data={"archivo": (io.BytesIO(PNG_MINIMO), "foto.png")},
        content_type="multipart/form-data",
    )
    from app.services.fotografia import obtener_fotografia, obtener_fotografias_proyecto

    with client.application.app_context():
        foto_id = obtener_fotografias_proyecto(proyecto.id)[0].id

    resp = client.post(f"/photo-studio/fotos/{foto_id}/eliminar")
    assert resp.status_code == 302

    with client.application.app_context():
        # Ya no aparece en la galeria...
        assert obtener_fotografias_proyecto(proyecto.id) == []
        # ...pero el registro sigue existiendo (soft-delete, no destruido).
        foto = obtener_fotografia(usuario_a_con_empresa["empresa_id"], foto_id)
        assert foto is not None
        assert foto.activo is False
