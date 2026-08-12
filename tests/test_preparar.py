"""Pruebas de las rutas de "preparar para redes": logo, marca de agua,
formatos, aislamiento multiempresa e integridad del original.

El acceso a Storage se mockea aqui (rapido, sin red); la logica pura
de composicion/recorte ya se prueba a fondo en
tests/test_formatos.py.
"""

import hashlib
import io
import struct
import zlib

from tests.conftest import iniciar_sesion_de_prueba


def _chunk(tipo, datos):
    return struct.pack(">I", len(datos)) + tipo + datos + struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF)


def _png_solido(ancho, alto, rgb):
    firma = b"\x89PNG\r\n\x1a\n"
    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", ancho, alto, 8, 2, 0, 0, 0))
    fila = bytes([0]) + bytes(rgb) * ancho
    idat = _chunk(b"IDAT", zlib.compress(fila * alto))
    return firma + ihdr + idat + _chunk(b"IEND", b"")


FOTO_PNG = _png_solido(400, 300, (90, 110, 130))
LOGO_PNG = _png_solido(120, 60, (200, 30, 30))


def _mockear_storage(monkeypatch, almacen):
    """`almacen` es un dict {ruta: bytes} que simula Supabase Storage en
    memoria (bucket de fotografias y de logos comparten el mismo dict:
    las rutas nunca chocan entre si en la practica).

    routes.py importa descargar_archivo/subir_archivo directamente a
    nivel de modulo (para la vista previa), y services/derivados.py lo
    hace de forma perezosa dentro de cada funcion -- hay que parchear
    ambos puntos.
    """
    import app.modules.fotografia.routes as rutas_mod
    import app.services.storage as storage_mod

    monkeypatch.setattr(rutas_mod, "storage_configurado", lambda: True)

    def _subir_falso(bucket, ruta, contenido, tipo_mime):
        almacen[ruta] = contenido

    def _descargar_falso(bucket, ruta):
        return almacen[ruta]

    monkeypatch.setattr(rutas_mod, "subir_archivo", _subir_falso)
    monkeypatch.setattr(rutas_mod, "descargar_archivo", _descargar_falso)
    monkeypatch.setattr(rutas_mod, "url_firmada", lambda *a, **k: "https://ejemplo.supabase.co/firmada")
    monkeypatch.setattr(storage_mod, "subir_archivo", _subir_falso)
    monkeypatch.setattr(storage_mod, "descargar_archivo", _descargar_falso)


def _crear_proyecto_foto_y_logo(client, monkeypatch, empresa_id):
    almacen = {}
    _mockear_storage(monkeypatch, almacen)

    client.post("/photo-studio/proyectos/nuevo", data={"nombre": "Proyecto formatos"})
    from app.services.fotografia import obtener_proyectos_empresa

    with client.session_transaction() as sess:
        empresa_id = sess.get("empresa_activa_id")

    with client.application.app_context():
        proyecto = obtener_proyectos_empresa(empresa_id)[0]

    client.post(
        f"/photo-studio/proyectos/{proyecto.id}/fotos",
        data={"archivo": (io.BytesIO(FOTO_PNG), "foto.png")},
        content_type="multipart/form-data",
    )
    from app.services.fotografia import obtener_fotografias_proyecto

    with client.application.app_context():
        foto = obtener_fotografias_proyecto(proyecto.id)[0]

    from app.services.marca import crear_logo

    ruta_logo = "empresas/logo-de-prueba.png"
    almacen[ruta_logo] = LOGO_PNG
    with client.application.app_context():
        logo = crear_logo(empresa_id, "principal", "logo.png", ruta_logo, "image/png", len(LOGO_PNG), None)
        logo_id = logo.id

    return almacen, proyecto, foto, logo_id


# --- Flujo normal --------------------------------------------------------------

def test_formato_cuadrado_crea_derivado_completado_con_dimensiones_exactas(client, usuario_a_con_empresa, monkeypatch):
    empresa_id = usuario_a_con_empresa["empresa_id"]
    _almacen, _proyecto, foto, _logo_id = _crear_proyecto_foto_y_logo(client, monkeypatch, empresa_id)

    resp = client.post(
        f"/photo-studio/fotos/{foto.id}/preparar",
        json={"aplicacion": "sin_logo", "formatos": ["formato_cuadrado"]},
    )
    assert resp.status_code == 201
    cuerpo = resp.get_json()
    assert cuerpo["ok"] is True
    assert cuerpo["resultados"][0]["ok"] is True

    from app.services.derivados import obtener_derivados_fotografia

    with client.application.app_context():
        derivados = obtener_derivados_fotografia(foto.id)
        assert len(derivados) == 1
        derivado = derivados[0]
        assert derivado.tipo == "formato_cuadrado"
        assert derivado.ancho_px == 1080
        assert derivado.alto_px == 1080
        assert derivado.ruta_storage != foto.ruta_storage


def test_formato_vertical_y_historia_dimensiones_exactas(client, usuario_a_con_empresa, monkeypatch):
    empresa_id = usuario_a_con_empresa["empresa_id"]
    _almacen, _proyecto, foto, _logo_id = _crear_proyecto_foto_y_logo(client, monkeypatch, empresa_id)

    resp = client.post(
        f"/photo-studio/fotos/{foto.id}/preparar",
        json={"aplicacion": "sin_logo", "formatos": ["formato_vertical", "formato_historia"]},
    )
    assert resp.status_code == 201

    from app.services.derivados import obtener_derivados_fotografia

    with client.application.app_context():
        derivados = {d.tipo: d for d in obtener_derivados_fotografia(foto.id)}
        assert (derivados["formato_vertical"].ancho_px, derivados["formato_vertical"].alto_px) == (1080, 1350)
        assert (derivados["formato_historia"].ancho_px, derivados["formato_historia"].alto_px) == (1080, 1920)


def test_logo_valido_se_aplica_como_marca_de_agua(client, usuario_a_con_empresa, monkeypatch):
    empresa_id = usuario_a_con_empresa["empresa_id"]
    _almacen, _proyecto, foto, logo_id = _crear_proyecto_foto_y_logo(client, monkeypatch, empresa_id)

    resp = client.post(
        f"/photo-studio/fotos/{foto.id}/preparar",
        json={
            "logo_id": logo_id,
            "aplicacion": "marca_agua",
            "posicion": "inferior_izquierda",
            "opacidad": 0.5,
            "formatos": ["formato_cuadrado"],
        },
    )
    assert resp.status_code == 201

    from app.services.derivados import obtener_derivados_fotografia

    with client.application.app_context():
        derivado = obtener_derivados_fotografia(foto.id)[0]
        assert derivado.logo_id == logo_id
        assert derivado.aplicacion_logo == "marca_agua"
        assert derivado.posicion_logo == "inferior_izquierda"
        assert derivado.opacidad_logo == 0.5


def test_original_no_cambia_al_generar_formato(client, usuario_a_con_empresa, monkeypatch):
    empresa_id = usuario_a_con_empresa["empresa_id"]
    almacen, _proyecto, foto, _logo_id = _crear_proyecto_foto_y_logo(client, monkeypatch, empresa_id)
    hash_antes = hashlib.sha256(almacen[foto.ruta_storage]).hexdigest()

    resp = client.post(
        f"/photo-studio/fotos/{foto.id}/preparar",
        json={"aplicacion": "sin_logo", "formatos": ["formato_cuadrado"]},
    )
    assert resp.get_json()["ok"] is True

    hash_despues = hashlib.sha256(almacen[foto.ruta_storage]).hexdigest()
    assert hash_antes == hash_despues, "El archivo original cambio en Storage: esto NUNCA debe pasar."


def test_vista_previa_devuelve_imagen_sin_persistir_nada(client, usuario_a_con_empresa, monkeypatch):
    empresa_id = usuario_a_con_empresa["empresa_id"]
    _almacen, _proyecto, foto, logo_id = _crear_proyecto_foto_y_logo(client, monkeypatch, empresa_id)

    resp = client.post(
        f"/photo-studio/fotos/{foto.id}/preparar/vista-previa",
        json={"logo_id": logo_id, "aplicacion": "logo", "formato": "formato_cuadrado"},
    )
    assert resp.status_code == 200
    assert resp.content_type == "image/jpeg"
    assert len(resp.data) > 0

    from app.services.derivados import obtener_derivados_fotografia

    with client.application.app_context():
        assert obtener_derivados_fotografia(foto.id) == []


# --- Seguridad y aislamiento -----------------------------------------------------

def test_preparar_sin_autenticar_redirige_a_login(client):
    resp = client.post("/photo-studio/fotos/1/preparar", json={"formatos": ["formato_cuadrado"]})
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_no_se_puede_generar_formato_de_fotografia_de_otra_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa, monkeypatch):
    iniciar_sesion_de_prueba(client, usuario_a_con_empresa["usuario_id"], "a@example.com")
    _almacen, _proyecto, foto, _logo_id = _crear_proyecto_foto_y_logo(client, monkeypatch, usuario_a_con_empresa["empresa_id"])

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp = client.post(
        f"/photo-studio/fotos/{foto.id}/preparar",
        json={"aplicacion": "sin_logo", "formatos": ["formato_cuadrado"]},
    )
    assert resp.status_code == 404

    from app.services.derivados import obtener_derivados_fotografia

    with client.application.app_context():
        assert obtener_derivados_fotografia(foto.id) == []


def test_logo_de_otra_empresa_es_rechazado(client, usuario_a_con_empresa, usuario_b_con_empresa, monkeypatch):
    """Empresa A no puede usar un logo de Empresa B, aunque la
    fotografia sea legitimamente de A. No debe crearse ningun derivado.
    """
    iniciar_sesion_de_prueba(client, usuario_a_con_empresa["usuario_id"], "a@example.com")
    _almacen_a, _proyecto_a, foto_a, _logo_a_id = _crear_proyecto_foto_y_logo(
        client, monkeypatch, usuario_a_con_empresa["empresa_id"]
    )

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    _almacen_b, _proyecto_b, _foto_b, logo_b_id = _crear_proyecto_foto_y_logo(
        client, monkeypatch, usuario_b_con_empresa["empresa_id"]
    )

    iniciar_sesion_de_prueba(client, usuario_a_con_empresa["usuario_id"], "a@example.com")
    resp = client.post(
        f"/photo-studio/fotos/{foto_a.id}/preparar",
        json={"logo_id": logo_b_id, "aplicacion": "logo", "formatos": ["formato_cuadrado"]},
    )
    assert resp.status_code == 400
    assert "no pertenece" in resp.get_json()["error"].lower()

    from app.services.derivados import obtener_derivados_fotografia

    with client.application.app_context():
        assert obtener_derivados_fotografia(foto_a.id) == []


def test_logo_inexistente_es_rechazado(client, usuario_a_con_empresa, monkeypatch):
    empresa_id = usuario_a_con_empresa["empresa_id"]
    _almacen, _proyecto, foto, _logo_id = _crear_proyecto_foto_y_logo(client, monkeypatch, empresa_id)

    resp = client.post(
        f"/photo-studio/fotos/{foto.id}/preparar",
        json={"logo_id": 999999, "aplicacion": "logo", "formatos": ["formato_cuadrado"]},
    )
    assert resp.status_code == 400


# --- Lote: un error no detiene a los demas --------------------------------------

def test_lote_continua_aunque_una_fotografia_falle(client, usuario_a_con_empresa, monkeypatch):
    empresa_id = usuario_a_con_empresa["empresa_id"]
    almacen, proyecto, foto_ok, _logo_id = _crear_proyecto_foto_y_logo(client, monkeypatch, empresa_id)

    from app.services.fotografia import crear_fotografia

    with client.application.app_context():
        foto_mala = crear_fotografia(
            empresa_id, proyecto.id, "mala.png", "ruta/inexistente.png", "image/png", 10, usuario_a_con_empresa["usuario_id"]
        )
        foto_mala_id = foto_mala.id
    # No se sube nada a `almacen` para esta ruta -> descargar_archivo fallara (KeyError)

    resp_mala = client.post(
        f"/photo-studio/fotos/{foto_mala_id}/preparar",
        json={"aplicacion": "sin_logo", "formatos": ["formato_cuadrado"]},
    )
    resp_buena = client.post(
        f"/photo-studio/fotos/{foto_ok.id}/preparar",
        json={"aplicacion": "sin_logo", "formatos": ["formato_cuadrado"]},
    )

    assert resp_mala.get_json()["ok"] is False
    assert resp_buena.status_code == 201
    assert resp_buena.get_json()["ok"] is True

    from app.services.derivados import obtener_derivados_fotografia

    with client.application.app_context():
        assert obtener_derivados_fotografia(foto_ok.id)[0].estado == "completada"
        derivados_malos = obtener_derivados_fotografia(foto_mala_id)
        assert len(derivados_malos) == 1
        assert derivados_malos[0].estado == "error"
        assert derivados_malos[0].error_mensaje
