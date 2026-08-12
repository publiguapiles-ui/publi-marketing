"""Pruebas de las rutas de mejora automatica: orquestacion, seguridad,
integridad del original y comportamiento por lote.

El acceso a Storage se mockea aqui (rapido, sin red); la integridad
real del pipeline de imagen ya se prueba a fondo en
tests/test_procesamiento.py, y la integracion real contra Supabase se
verifico manualmente (ver informe del Paso 7).
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


PNG_1 = _png_solido(20, 20, (90, 110, 130))


def _mockear_storage(monkeypatch, almacen):
    """`almacen` es un dict {ruta: bytes} que simula Supabase Storage en
    memoria, para poder verificar de verdad que el original no cambia.

    services/derivados.py importa subir_archivo/descargar_archivo de
    forma perezosa (dentro de la funcion) desde app.services.storage,
    asi que el mock tiene que aplicarse ahi -- parchear el modulo
    app.services.derivados directamente no tiene efecto.
    """
    import app.modules.fotografia.routes as rutas_mod
    import app.services.storage as storage_mod

    monkeypatch.setattr(rutas_mod, "storage_configurado", lambda: True)

    def _subir_falso(bucket, ruta, contenido, tipo_mime):
        almacen[ruta] = contenido

    def _descargar_falso(bucket, ruta):
        return almacen[ruta]

    monkeypatch.setattr(rutas_mod, "subir_archivo", _subir_falso)
    monkeypatch.setattr(rutas_mod, "url_firmada", lambda *a, **k: "https://ejemplo.supabase.co/firmada")
    monkeypatch.setattr(storage_mod, "subir_archivo", _subir_falso)
    monkeypatch.setattr(storage_mod, "descargar_archivo", _descargar_falso)


def _crear_proyecto_y_foto(client, monkeypatch, nombre_archivo="foto.png"):
    almacen = {}
    _mockear_storage(monkeypatch, almacen)

    client.post("/photo-studio/proyectos/nuevo", data={"nombre": "Proyecto mejora"})
    from app.services.fotografia import obtener_proyectos_empresa

    with client.session_transaction() as sess:
        empresa_id = sess.get("empresa_activa_id")

    with client.application.app_context():
        proyecto = obtener_proyectos_empresa(empresa_id)[0]

    client.post(
        f"/photo-studio/proyectos/{proyecto.id}/fotos",
        data={"archivo": (io.BytesIO(PNG_1), nombre_archivo)},
        content_type="multipart/form-data",
    )
    from app.services.fotografia import obtener_fotografias_proyecto

    with client.application.app_context():
        foto = obtener_fotografias_proyecto(proyecto.id)[0]

    return almacen, proyecto, foto


# --- Flujo normal ------------------------------------------------------------

def test_mejorar_fotografia_crea_derivado_completado(client, usuario_a_con_empresa, monkeypatch):
    almacen, _proyecto, foto = _crear_proyecto_y_foto(client, monkeypatch)

    resp = client.post(f"/photo-studio/fotos/{foto.id}/mejorar")
    assert resp.status_code == 201
    cuerpo = resp.get_json()
    assert cuerpo["ok"] is True
    assert cuerpo["estado"] == "completada"

    from app.services.derivados import obtener_derivados_fotografia

    with client.application.app_context():
        derivados = obtener_derivados_fotografia(foto.id)
        assert len(derivados) == 1
        derivado = derivados[0]
        assert derivado.estado == "completada"
        assert derivado.ruta_storage is not None
        assert derivado.ruta_storage != foto.ruta_storage  # es un archivo NUEVO, no el original


def test_el_original_no_cambia_ni_un_byte(client, usuario_a_con_empresa, monkeypatch):
    almacen, _proyecto, foto = _crear_proyecto_y_foto(client, monkeypatch)
    hash_antes = hashlib.sha256(almacen[foto.ruta_storage]).hexdigest()

    resp = client.post(f"/photo-studio/fotos/{foto.id}/mejorar")
    assert resp.get_json()["ok"] is True

    hash_despues = hashlib.sha256(almacen[foto.ruta_storage]).hexdigest()
    assert hash_antes == hash_despues, "El archivo original cambio en Storage: esto NUNCA debe pasar."


def test_dos_mejoras_no_se_sobreescriben_y_versionan(client, usuario_a_con_empresa, monkeypatch):
    _almacen, _proyecto, foto = _crear_proyecto_y_foto(client, monkeypatch)

    r1 = client.post(f"/photo-studio/fotos/{foto.id}/mejorar").get_json()
    r2 = client.post(f"/photo-studio/fotos/{foto.id}/mejorar").get_json()

    from app.services.derivados import obtener_derivados_fotografia

    with client.application.app_context():
        derivados = obtener_derivados_fotografia(foto.id)
        assert len(derivados) == 2
        versiones = sorted(d.version for d in derivados)
        assert versiones == [1, 2]
        rutas = {d.ruta_storage for d in derivados}
        assert len(rutas) == 2  # cada version es un archivo distinto


# --- Seguridad y aislamiento -------------------------------------------------

def test_mejorar_sin_autenticar_redirige_a_login(client):
    resp = client.post("/photo-studio/fotos/1/mejorar")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_no_se_puede_mejorar_fotografia_de_otra_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa, monkeypatch):
    iniciar_sesion_de_prueba(client, usuario_a_con_empresa["usuario_id"], "a@example.com")
    _almacen, _proyecto, foto = _crear_proyecto_y_foto(client, monkeypatch)

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp = client.post(f"/photo-studio/fotos/{foto.id}/mejorar")
    assert resp.status_code == 404

    from app.services.derivados import obtener_derivados_fotografia

    with client.application.app_context():
        assert obtener_derivados_fotografia(foto.id) == []


# --- Lote: un error no detiene a los demas ----------------------------------

def test_lote_continua_aunque_una_fotografia_falle(client, usuario_a_con_empresa, monkeypatch):
    almacen, _proyecto, foto_ok = _crear_proyecto_y_foto(client, monkeypatch, "buena.png")

    # Segunda fotografia, cuyo archivo en el almacen simulado se
    # corrompe a proposito para forzar un error de procesamiento real.
    from app.services.fotografia import obtener_proyectos_empresa, crear_fotografia

    with client.session_transaction() as sess:
        empresa_id = sess.get("empresa_activa_id")

    with client.application.app_context():
        proyecto = obtener_proyectos_empresa(empresa_id)[0]
        foto_mala = crear_fotografia(
            empresa_id, proyecto.id, "mala.png", "ruta/inexistente.png", "image/png", 10, usuario_a_con_empresa["usuario_id"]
        )
        foto_mala_id = foto_mala.id
    # No se sube nada a `almacen` para esta ruta -> descargar_archivo fallara (KeyError)

    resp_mala = client.post(f"/photo-studio/fotos/{foto_mala_id}/mejorar")
    resp_buena = client.post(f"/photo-studio/fotos/{foto_ok.id}/mejorar")

    assert resp_mala.get_json()["ok"] is False
    assert resp_buena.status_code == 201
    assert resp_buena.get_json()["ok"] is True

    from app.services.derivados import obtener_derivados_fotografia

    with client.application.app_context():
        assert obtener_derivados_fotografia(foto_ok.id)[0].estado == "completada"
        derivados_malos = obtener_derivados_fotografia(foto_mala_id)
        assert len(derivados_malos) == 1
        assert derivados_malos[0].estado == "error"
        assert derivados_malos[0].error_mensaje  # el motivo quedo registrado, no se perdio en silencio
