"""Pruebas de la biblioteca profesional de presets (Paso 11): listar,
crear, editar, duplicar, eliminar (soft delete), favoritos, categorias,
aislamiento multiempresa, proteccion de presets de sistema, aplicar un
preset personalizado (individual y por sesion), snapshot inmutable de
preset_nombre/preset_version en los derivados, versionado, integridad
del original y proteccion facial.

El acceso a Storage se mockea aqui (rapido, sin red) -- la logica pura
de correccion ya se prueba a fondo en tests/test_procesamiento.py.
"""

import io
import struct
import zlib

import numpy as np
from PIL import Image, ImageFilter

from tests.conftest import iniciar_sesion_de_prueba


def _chunk(tipo, datos):
    return struct.pack(">I", len(datos)) + tipo + datos + struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF)


def _png_solido(ancho, alto, rgb):
    firma = b"\x89PNG\r\n\x1a\n"
    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", ancho, alto, 8, 2, 0, 0, 0))
    fila = bytes([0]) + bytes(rgb) * ancho
    idat = _chunk(b"IDAT", zlib.compress(fila * alto))
    return firma + ihdr + idat + _chunk(b"IEND", b"")


def _rostro_sintetico_png(ancho=400, alto=500):
    """Misma tecnica ya verificada en tests/test_sesiones.py: gradientes
    reales, no un bloque plano -- es lo unico que dispara una deteccion
    real del Haar Cascade."""
    yy, xx = np.mgrid[0:alto, 0:ancho]
    cx, cy = ancho / 2, alto / 2
    dist = ((xx - cx) / 140) ** 2 + ((yy - cy) / 180) ** 2
    base = np.clip(235 - dist * 90, 120, 235)
    for signo in (-1, 1):
        ex, ey = cx + signo * 55, cy - 20
        d = ((xx - ex) / 22) ** 2 + ((yy - ey) / 14) ** 2
        base = np.where(d < 1, base - 140 * np.exp(-d * 2), base)
        d_ceja = ((xx - ex) / 28) ** 2 + ((yy - (ey - 25)) / 7) ** 2
        base = np.where(d_ceja < 1, base - 90, base)
    d_nariz = ((xx - cx) / 10) ** 2 + ((yy - cy + 10) / 55) ** 2
    base = np.where((d_nariz < 1) & (xx > cx), base - 15, base)
    d_boca = ((xx - cx) / 38) ** 2 + ((yy - cy - 95) / 12) ** 2
    base = np.where(d_boca < 1, base - 60, base)
    gris = np.clip(base, 0, 255).astype(np.uint8)
    rgb = np.stack([gris, gris * 0.85, gris * 0.75], axis=-1).astype(np.uint8)
    imagen = Image.fromarray(rgb, mode="RGB").filter(ImageFilter.GaussianBlur(1.2))
    buf = io.BytesIO()
    imagen.save(buf, format="PNG")
    return buf.getvalue()


FOTO_A = _png_solido(300, 200, (90, 110, 130))
FOTO_ROSTRO = _rostro_sintetico_png()


def _mockear_storage(monkeypatch, almacen):
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


def _crear_proyecto_y_foto(client, monkeypatch, contenido=FOTO_A, nombre_archivo="foto.png"):
    almacen = {}
    _mockear_storage(monkeypatch, almacen)

    client.post("/photo-studio/proyectos/nuevo", data={"nombre": "Proyecto presets"})
    from app.services.fotografia import obtener_proyectos_empresa

    with client.session_transaction() as sess:
        empresa_id = sess.get("empresa_activa_id")

    with client.application.app_context():
        proyecto = obtener_proyectos_empresa(empresa_id)[0]

    client.post(
        f"/photo-studio/proyectos/{proyecto.id}/fotos",
        data={"archivo": (io.BytesIO(contenido), nombre_archivo)},
        content_type="multipart/form-data",
    )
    from app.services.fotografia import obtener_fotografias_proyecto

    with client.application.app_context():
        foto = obtener_fotografias_proyecto(proyecto.id)[0]

    return almacen, proyecto, foto


PARAMETROS_EJEMPLO = {
    "objetivo_brillo": 0.55,
    "intensidad_exposicion": 0.8,
    "objetivo_contraste": 0.3,
    "intensidad_contraste": 1.0,
    "sesgo_calidez": 0.4,
    "intensidad_calidez": 1.0,
    "objetivo_saturacion": 0.4,
    "factor_maximo_saturacion": 1.4,
    "intensidad_saturacion": 1.0,
    "intensidad_nitidez": 90,
}


def _crear_preset_personalizado(client, **overrides):
    cuerpo = {
        "nombre": "Carnicería LG — Comercial",
        "descripcion": "Estilo comercial cálido",
        "categoria": "comercial",
    }
    cuerpo.update(PARAMETROS_EJEMPLO)
    cuerpo.update(overrides)
    resp = client.post("/photo-studio/presets/nuevo", json=cuerpo)
    return resp


# --- 1/2. Listar presets de sistema y de empresa ------------------------------

def test_listar_presets_incluye_los_11_de_sistema(client, usuario_a_con_empresa):
    resp = client.get("/photo-studio/presets")
    assert resp.status_code == 200
    texto = resp.get_data(as_text=True)
    for nombre in ["Automático", "Natural", "Cálido", "Frío", "Comercial", "Vibrante", "Cinemático", "Evento", "Producto", "Interior", "Exterior"]:
        assert nombre in texto


def test_biblioteca_agrupa_favoritos_sistema_y_personalizados(client, usuario_a_con_empresa):
    _crear_preset_personalizado(client)
    resp = client.get("/photo-studio/presets")
    texto = resp.get_data(as_text=True)
    assert "Mis presets" in texto
    assert "Carnicería LG — Comercial" in texto


# --- 3. Crear preset personalizado --------------------------------------------

def test_crear_preset_personalizado(client, usuario_a_con_empresa):
    resp = _crear_preset_personalizado(client)
    assert resp.status_code == 201
    datos = resp.get_json()
    assert datos["ok"] is True

    from app.extensions import db
    from app.models import Preset

    with client.application.app_context():
        preset = db.session.get(Preset, datos["preset_id"])
        assert preset.nombre == "Carnicería LG — Comercial"
        assert preset.categoria == "comercial"
        assert preset.es_sistema is False
        assert preset.empresa_id == usuario_a_con_empresa["empresa_id"]
        assert preset.version == 1
        assert preset.parametros["sesgo_calidez"] == 0.4


def test_crear_preset_sin_nombre_falla(client, usuario_a_con_empresa):
    resp = _crear_preset_personalizado(client, nombre="")
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


# --- 4/12. Editar preset personalizado + versionado ---------------------------

def test_editar_preset_personalizado_incrementa_version(client, usuario_a_con_empresa):
    preset_id = _crear_preset_personalizado(client).get_json()["preset_id"]

    cuerpo = dict(PARAMETROS_EJEMPLO, nombre="Carnicería LG — Comercial", descripcion="v2", categoria="comercial", intensidad_nitidez=120)
    resp = client.post(f"/photo-studio/presets/{preset_id}/editar", json=cuerpo)
    assert resp.status_code == 200
    assert resp.get_json()["version"] == 2

    from app.extensions import db
    from app.models import Preset

    with client.application.app_context():
        preset = db.session.get(Preset, preset_id)
        assert preset.version == 2
        assert preset.parametros["intensidad_nitidez"] == 120


# --- 9. Presets del sistema protegidos -----------------------------------------

def test_no_se_puede_editar_preset_de_sistema(client, usuario_a_con_empresa):
    from app.extensions import db
    from app.models import Preset

    with client.application.app_context():
        preset_automatico_id = db.session.query(Preset).filter_by(slug="automatico").first().id

    resp = client.post(f"/photo-studio/presets/{preset_automatico_id}/editar", json=dict(PARAMETROS_EJEMPLO, nombre="Hackeado"))
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False

    with client.application.app_context():
        preset = db.session.get(Preset, preset_automatico_id)
        assert preset.nombre == "Automático"  # no cambio ni un poco


def test_no_se_puede_eliminar_preset_de_sistema(client, usuario_a_con_empresa):
    from app.extensions import db
    from app.models import Preset

    with client.application.app_context():
        preset_id = db.session.query(Preset).filter_by(slug="natural").first().id

    resp = client.post(f"/photo-studio/presets/{preset_id}/eliminar")
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False

    with client.application.app_context():
        preset = db.session.get(Preset, preset_id)
        assert preset.activo is True


# --- 5. Duplicar preset --------------------------------------------------------

def test_duplicar_preset_de_sistema_no_modifica_el_original(client, usuario_a_con_empresa):
    from app.extensions import db
    from app.models import Preset

    with client.application.app_context():
        original = db.session.query(Preset).filter_by(slug="calido").first()
        original_id = original.id
        parametros_originales = dict(original.parametros)

    resp = client.post(f"/photo-studio/presets/{original_id}/duplicar")
    assert resp.status_code == 201
    datos = resp.get_json()
    nuevo_id = datos["preset_id"]
    assert nuevo_id != original_id

    with client.application.app_context():
        original_despues = db.session.get(Preset, original_id)
        assert original_despues.parametros == parametros_originales  # intacto
        assert original_despues.es_sistema is True

        copia = db.session.get(Preset, nuevo_id)
        assert copia.es_sistema is False
        assert "copia" in copia.nombre.lower()
        assert copia.empresa_id == usuario_a_con_empresa["empresa_id"]
        # La copia pasa por normalizar_parametros() (completa "avanzado"
        # e "intensidad_*" con sus valores por defecto neutros) -- el
        # original de sistema no tiene esas claves porque nunca se
        # normalizo. Lo que debe coincidir EXACTO son los valores que
        # ambos si comparten (los 6 objetivos historicos del Paso 10).
        for clave in ("objetivo_brillo", "objetivo_contraste", "objetivo_saturacion", "factor_maximo_saturacion", "sesgo_calidez", "intensidad_nitidez"):
            assert copia.parametros[clave] == parametros_originales[clave]
        assert copia.version == 1


def test_duplicar_preset_personalizado(client, usuario_a_con_empresa):
    preset_id = _crear_preset_personalizado(client).get_json()["preset_id"]
    resp = client.post(f"/photo-studio/presets/{preset_id}/duplicar")
    assert resp.status_code == 201
    assert resp.get_json()["preset_id"] != preset_id


# --- 6/13. Eliminar preset (soft delete) ---------------------------------------

def test_eliminar_preset_personalizado_es_soft_delete(client, usuario_a_con_empresa):
    preset_id = _crear_preset_personalizado(client).get_json()["preset_id"]

    resp = client.post(f"/photo-studio/presets/{preset_id}/eliminar")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    from app.extensions import db
    from app.models import Preset

    with client.application.app_context():
        preset = db.session.get(Preset, preset_id)
        assert preset is not None  # la fila sigue existiendo
        assert preset.activo is False  # solo se desactivo

    # Ya no aparece entre los presets disponibles para nuevas sesiones/derivados:
    resp = client.get("/photo-studio/presets")
    assert "Carnicería LG — Comercial" not in resp.get_data(as_text=True)


# --- 7. Favoritos ---------------------------------------------------------------

def test_marcar_y_desmarcar_favorito(client, usuario_a_con_empresa):
    from app.extensions import db
    from app.models import Preset

    with client.application.app_context():
        preset_id = db.session.query(Preset).filter_by(slug="vibrante").first().id

    resp1 = client.post(f"/photo-studio/presets/{preset_id}/favorito")
    assert resp1.get_json() == {"ok": True, "favorito": True}

    resp2 = client.post(f"/photo-studio/presets/{preset_id}/favorito")
    assert resp2.get_json() == {"ok": True, "favorito": False}


def test_favoritos_son_por_empresa_no_globales(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.extensions import db
    from app.models import Preset

    with client.application.app_context():
        preset_id = db.session.query(Preset).filter_by(slug="vibrante").first().id

    iniciar_sesion_de_prueba(client, usuario_a_con_empresa["usuario_id"], "a@example.com")
    client.post(f"/photo-studio/presets/{preset_id}/favorito")

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp = client.get("/photo-studio/presets")
    # Empresa B no marco nada como favorito: "Vibrante" debe seguir en
    # la seccion de sistema, no en la de favoritos (que ni deberia existir).
    assert "★ Favoritos" not in resp.get_data(as_text=True)


# --- 8. Aislamiento entre empresas -----------------------------------------------

def test_preset_personalizado_no_es_visible_para_otra_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    iniciar_sesion_de_prueba(client, usuario_a_con_empresa["usuario_id"], "a@example.com")
    preset_id = _crear_preset_personalizado(client).get_json()["preset_id"]

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp = client.get("/photo-studio/presets")
    assert "Carnicería LG — Comercial" not in resp.get_data(as_text=True)

    resp_editar = client.get(f"/photo-studio/presets/{preset_id}/editar")
    assert resp_editar.status_code == 404


def test_no_se_puede_editar_preset_de_otra_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    iniciar_sesion_de_prueba(client, usuario_a_con_empresa["usuario_id"], "a@example.com")
    preset_id = _crear_preset_personalizado(client).get_json()["preset_id"]

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp = client.post(f"/photo-studio/presets/{preset_id}/editar", json=dict(PARAMETROS_EJEMPLO, nombre="Robado"))
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_no_se_puede_eliminar_preset_de_otra_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    iniciar_sesion_de_prueba(client, usuario_a_con_empresa["usuario_id"], "a@example.com")
    preset_id = _crear_preset_personalizado(client).get_json()["preset_id"]

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp = client.post(f"/photo-studio/presets/{preset_id}/eliminar")
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


# --- 10/11/14/15. Aplicar preset a una fotografia --------------------------------

def test_aplicar_preset_personalizado_a_una_fotografia(client, usuario_a_con_empresa, monkeypatch):
    almacen, _proyecto, foto = _crear_proyecto_y_foto(client, monkeypatch)
    preset_id = _crear_preset_personalizado(client).get_json()["preset_id"]

    resp = client.post(f"/photo-studio/fotos/{foto.id}/mejorar", json={"preset_id": preset_id})
    assert resp.status_code == 201
    assert resp.get_json()["ok"] is True


def test_derivado_guarda_snapshot_de_preset_nombre_y_version(client, usuario_a_con_empresa, monkeypatch):
    almacen, _proyecto, foto = _crear_proyecto_y_foto(client, monkeypatch)
    preset_id = _crear_preset_personalizado(client).get_json()["preset_id"]

    resp = client.post(f"/photo-studio/fotos/{foto.id}/mejorar", json={"preset_id": preset_id})
    derivado_id = resp.get_json()["derivado_id"]

    from app.extensions import db
    from app.models import FotografiaDerivada

    with client.application.app_context():
        derivado = db.session.get(FotografiaDerivada, derivado_id)
        assert derivado.preset_id == preset_id
        assert derivado.preset_nombre == "Carnicería LG — Comercial"
        assert derivado.preset_version == 1


def test_editar_preset_no_cambia_snapshot_de_derivados_ya_generados(client, usuario_a_con_empresa, monkeypatch):
    """El nucleo de la seccion HISTORIAL/VERSIONADO: un preset editado
    despues nunca cambia retroactivamente como se ve un derivado ya
    generado con la version anterior."""
    almacen, _proyecto, foto = _crear_proyecto_y_foto(client, monkeypatch)
    preset_id = _crear_preset_personalizado(client).get_json()["preset_id"]

    derivado_id = client.post(f"/photo-studio/fotos/{foto.id}/mejorar", json={"preset_id": preset_id}).get_json()["derivado_id"]

    # Editar el preset dos veces (v2, v3) despues de generar el derivado:
    client.post(f"/photo-studio/presets/{preset_id}/editar", json=dict(PARAMETROS_EJEMPLO, nombre="Carnicería LG — Comercial v2", categoria="comercial"))
    client.post(f"/photo-studio/presets/{preset_id}/editar", json=dict(PARAMETROS_EJEMPLO, nombre="Carnicería LG — Comercial v3", categoria="comercial"))

    from app.extensions import db
    from app.models import FotografiaDerivada, Preset

    with client.application.app_context():
        preset = db.session.get(Preset, preset_id)
        assert preset.version == 3
        assert preset.nombre == "Carnicería LG — Comercial v3"

        derivado = db.session.get(FotografiaDerivada, derivado_id)
        assert derivado.preset_nombre == "Carnicería LG — Comercial"  # snapshot original, sin "v2"/"v3"
        assert derivado.preset_version == 1  # nunca cambia retroactivamente


def test_original_no_cambia_al_aplicar_preset_personalizado(client, usuario_a_con_empresa, monkeypatch):
    import hashlib

    almacen, _proyecto, foto = _crear_proyecto_y_foto(client, monkeypatch)
    hash_antes = hashlib.sha256(almacen[foto.ruta_storage]).hexdigest()
    preset_id = _crear_preset_personalizado(client).get_json()["preset_id"]

    client.post(f"/photo-studio/fotos/{foto.id}/mejorar", json={"preset_id": preset_id})

    hash_despues = hashlib.sha256(almacen[foto.ruta_storage]).hexdigest()
    assert hash_antes == hash_despues


def test_proteccion_facial_se_mantiene_con_preset_personalizado(client, usuario_a_con_empresa, monkeypatch):
    almacen, _proyecto, foto = _crear_proyecto_y_foto(client, monkeypatch, contenido=FOTO_ROSTRO, nombre_archivo="rostro.png")
    preset_id = _crear_preset_personalizado(client, sesgo_calidez=0.9, objetivo_contraste=0.9, objetivo_saturacion=0.9).get_json()["preset_id"]

    resp = client.post(f"/photo-studio/fotos/{foto.id}/mejorar", json={"preset_id": preset_id})
    derivado_id = resp.get_json()["derivado_id"]

    from app.extensions import db
    from app.models import FotografiaDerivada

    with client.application.app_context():
        derivado = db.session.get(FotografiaDerivada, derivado_id)
        assert derivado.rostros_detectados >= 1
        assert derivado.rostros_protegidos is True


# --- 16. Procesamiento de sesion con preset personalizado -----------------------

def test_sesion_con_preset_personalizado_completa_correctamente(client, usuario_a_con_empresa, monkeypatch):
    almacen, proyecto, foto = _crear_proyecto_y_foto(client, monkeypatch)
    preset_id = _crear_preset_personalizado(client).get_json()["preset_id"]

    resp = client.post(
        f"/photo-studio/proyectos/{proyecto.id}/sesiones",
        json={
            "nombre": "Sesion con preset propio",
            "fotografia_ids": [foto.id],
            "preset_id": preset_id,
            "aplicacion": "sin_logo",
            "formatos": ["mejora_automatica"],
        },
    )
    assert resp.status_code == 201
    sesion_id = resp.get_json()["sesion_id"]

    datos = client.post(f"/photo-studio/sesiones/{sesion_id}/procesar-uno").get_json()
    assert datos["sesion_terminada"] is True
    assert datos["completadas"] == 1
    assert datos["errores"] == 0

    from app.extensions import db
    from app.models import FotografiaDerivada

    with client.application.app_context():
        derivado = (
            db.session.query(FotografiaDerivada)
            .filter_by(fotografia_id=foto.id, tipo="mejora_automatica")
            .first()
        )
        assert derivado.preset_id == preset_id
        assert derivado.preset_nombre == "Carnicería LG — Comercial"


# --- Vista previa: usa el motor real, nunca persiste nada -----------------------

def test_vista_previa_preset_usa_motor_real_y_no_persiste_nada(client, usuario_a_con_empresa, monkeypatch):
    almacen, _proyecto, foto = _crear_proyecto_y_foto(client, monkeypatch)

    from app.extensions import db
    from app.models import FotografiaDerivada

    with client.application.app_context():
        conteo_antes = db.session.query(FotografiaDerivada).count()

    resp = client.post(
        f"/photo-studio/fotos/{foto.id}/preset-vista-previa",
        json={"parametros": PARAMETROS_EJEMPLO},
    )
    assert resp.status_code == 200
    assert resp.mimetype == "image/png"
    assert len(resp.data) > 0

    with client.application.app_context():
        conteo_despues = db.session.query(FotografiaDerivada).count()
    assert conteo_antes == conteo_despues  # nada se guardo en la base de datos


def test_vista_previa_con_parametros_incompletos_no_falla(client, usuario_a_con_empresa, monkeypatch):
    """Regresion del bug real encontrado durante la verificacion manual:
    un preset de sistema en modo solo-lectura enviaba sliders
    deshabilitados (ausentes del formulario), lo que llegaba como None
    al motor y causaba un 500. La normalizacion en el servidor debe
    evitarlo sin importar que mande el cliente."""
    almacen, _proyecto, foto = _crear_proyecto_y_foto(client, monkeypatch)

    resp = client.post(
        f"/photo-studio/fotos/{foto.id}/preset-vista-previa",
        json={"parametros": {"objetivo_brillo": None, "intensidad_nitidez": None}},
    )
    assert resp.status_code == 200
    assert resp.mimetype == "image/png"
