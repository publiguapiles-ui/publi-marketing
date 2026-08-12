"""Pruebas de sesiones de procesamiento masivo (Paso 10): creacion,
analisis, seleccion de preset, procesamiento por lote con progreso
real, proteccion facial, formatos, logo, aislamiento multiempresa,
error individual sin detener la sesion, versionado y los dos estados
finales (completada / completada_con_errores).

El acceso a Storage se mockea aqui (rapido, sin red) -- la logica pura
de correccion/recorte/logo ya se prueba a fondo en
tests/test_procesamiento.py, tests/test_formatos.py y
tests/test_encuadre.py.
"""

import hashlib
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
    """Identico en tecnica al helper ya probado de
    tests/test_procesamiento.py: gradientes, no vectores planos -- es
    lo unico que dispara una deteccion real del Haar Cascade.
    """
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
FOTO_B = _png_solido(300, 200, (40, 60, 200))  # bien distinta de FOTO_A, para variar el promedio
FOTO_ROSTRO = _rostro_sintetico_png()
LOGO_PNG = _png_solido(120, 60, (200, 30, 30))


def _mockear_storage(monkeypatch, almacen):
    """Igual patron que tests/test_preparar.py: `almacen` simula
    Supabase Storage en memoria; se parchea tanto el modulo de rutas
    (imports directos, usados por la vista previa) como
    app.services.storage (imports perezosos de services/derivados.py
    y services/sesiones.py).
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


def _crear_proyecto_con_fotos(client, monkeypatch, empresa_id, archivos):
    """Sube cada bytes de `archivos` como una fotografia nueva en un
    proyecto nuevo. Devuelve (almacen, proyecto, [fotos], logo_id).
    """
    almacen = {}
    _mockear_storage(monkeypatch, almacen)

    client.post("/photo-studio/proyectos/nuevo", data={"nombre": "Proyecto sesiones"})
    from app.services.fotografia import obtener_proyectos_empresa

    with client.session_transaction() as sess:
        empresa_id = sess.get("empresa_activa_id")

    with client.application.app_context():
        proyecto = obtener_proyectos_empresa(empresa_id)[0]

    for i, contenido in enumerate(archivos):
        client.post(
            f"/photo-studio/proyectos/{proyecto.id}/fotos",
            data={"archivo": (io.BytesIO(contenido), f"foto{i}.png")},
            content_type="multipart/form-data",
        )

    from app.services.fotografia import obtener_fotografias_proyecto

    with client.application.app_context():
        fotos = list(reversed(obtener_fotografias_proyecto(proyecto.id)))  # orden de subida

    from app.services.marca import crear_logo

    ruta_logo = "empresas/logo-sesion.png"
    almacen[ruta_logo] = LOGO_PNG
    with client.application.app_context():
        logo = crear_logo(empresa_id, "principal", "logo.png", ruta_logo, "image/png", len(LOGO_PNG), None)
        logo_id = logo.id

    return almacen, proyecto, fotos, logo_id


def _obtener_preset_automatico_id(client):
    from app.extensions import db
    from app.models import Preset

    with client.application.app_context():
        return db.session.query(Preset).filter_by(slug="automatico").first().id


def _procesar_sesion_completa(client, sesion_id, limite=50):
    """Llama a /procesar-uno repetidamente hasta que la sesion termine
    -- igual que hace el bucle real en el navegador, una peticion por
    fotografia."""
    for _ in range(limite):
        resp = client.post(f"/photo-studio/sesiones/{sesion_id}/procesar-uno")
        datos = resp.get_json()
        if datos["sesion_terminada"]:
            return datos
    raise AssertionError("La sesion no termino dentro del limite de iteraciones de la prueba.")


# --- Crear sesion, cargar varias fotos, seleccionar preset ---------------------

def test_crear_sesion_con_varias_fotografias_y_preset(client, usuario_a_con_empresa, monkeypatch):
    empresa_id = usuario_a_con_empresa["empresa_id"]
    _almacen, proyecto, fotos, _logo_id = _crear_proyecto_con_fotos(client, monkeypatch, empresa_id, [FOTO_A, FOTO_B, FOTO_A])
    assert len(fotos) == 3

    preset_id = _obtener_preset_automatico_id(client)
    resp = client.post(
        f"/photo-studio/proyectos/{proyecto.id}/sesiones",
        json={
            "nombre": "Sesion de prueba",
            "fotografia_ids": [f.id for f in fotos],
            "preset_id": preset_id,
            "aplicacion": "sin_logo",
            "formatos": ["mejora_automatica"],
        },
    )
    assert resp.status_code == 201
    sesion_id = resp.get_json()["sesion_id"]

    from app.services.sesiones import obtener_sesion, obtener_items_sesion

    with client.application.app_context():
        sesion = obtener_sesion(empresa_id, sesion_id)
        assert sesion.total_fotografias == 3
        assert sesion.preset_id == preset_id
        assert sesion.estado == "pendiente"
        items = obtener_items_sesion(sesion_id)
        assert len(items) == 3
        assert all(i.estado == "pendiente" for i in items)


# --- Analizar sesion -------------------------------------------------------------

def test_analizar_sesion_calcula_promedios_de_todas_las_fotos(client, usuario_a_con_empresa, monkeypatch):
    empresa_id = usuario_a_con_empresa["empresa_id"]
    _almacen, proyecto, fotos, _logo_id = _crear_proyecto_con_fotos(client, monkeypatch, empresa_id, [FOTO_A, FOTO_B])
    preset_id = _obtener_preset_automatico_id(client)

    resp = client.post(
        f"/photo-studio/proyectos/{proyecto.id}/sesiones",
        json={"fotografia_ids": [f.id for f in fotos], "preset_id": preset_id, "formatos": ["mejora_automatica"]},
    )
    sesion_id = resp.get_json()["sesion_id"]

    resp = client.post(f"/photo-studio/sesiones/{sesion_id}/analizar")
    assert resp.status_code == 200
    datos = resp.get_json()
    assert datos["ok"] is True
    assert datos["analisis"]["brillo_promedio"] is not None
    assert datos["analisis"]["duracion_segundos"] is not None
    assert datos["estado"] == "pendiente"  # analizada, lista para procesar


# --- Procesar el lote completo: progreso real, resultados, sesion completada ----

def test_procesar_sesion_completa_todas_las_fotos_y_reporta_progreso_real(client, usuario_a_con_empresa, monkeypatch):
    empresa_id = usuario_a_con_empresa["empresa_id"]
    _almacen, proyecto, fotos, _logo_id = _crear_proyecto_con_fotos(client, monkeypatch, empresa_id, [FOTO_A, FOTO_B, FOTO_A])
    preset_id = _obtener_preset_automatico_id(client)

    resp = client.post(
        f"/photo-studio/proyectos/{proyecto.id}/sesiones",
        json={"fotografia_ids": [f.id for f in fotos], "preset_id": preset_id, "formatos": ["mejora_automatica", "formato_cuadrado"]},
    )
    sesion_id = resp.get_json()["sesion_id"]

    vistos = []
    for _ in range(10):
        resp = client.post(f"/photo-studio/sesiones/{sesion_id}/procesar-uno")
        datos = resp.get_json()
        vistos.append(datos["completadas"] + datos["errores"])
        if datos["sesion_terminada"]:
            break

    # El progreso reportado en cada respuesta debe ser real y creciente
    # (nunca una barra simulada): 1, 2, 3... nunca saltos ni retrocesos.
    assert vistos == sorted(set(vistos))
    assert vistos[-1] == 3

    from app.services.sesiones import obtener_sesion, obtener_items_sesion

    with client.application.app_context():
        sesion = obtener_sesion(empresa_id, sesion_id)
        assert sesion.estado == "completada"
        assert sesion.completadas == 3
        assert sesion.errores == 0
        items = obtener_items_sesion(sesion_id)
        assert all(i.estado == "completada" for i in items)


# --- Original intacto -------------------------------------------------------------

def test_originales_no_cambian_durante_el_procesamiento_de_sesion(client, usuario_a_con_empresa, monkeypatch):
    empresa_id = usuario_a_con_empresa["empresa_id"]
    almacen, proyecto, fotos, _logo_id = _crear_proyecto_con_fotos(client, monkeypatch, empresa_id, [FOTO_A, FOTO_B])
    hashes_antes = {f.ruta_storage: hashlib.sha256(almacen[f.ruta_storage]).hexdigest() for f in fotos}

    preset_id = _obtener_preset_automatico_id(client)
    resp = client.post(
        f"/photo-studio/proyectos/{proyecto.id}/sesiones",
        json={"fotografia_ids": [f.id for f in fotos], "preset_id": preset_id, "formatos": ["mejora_automatica", "formato_vertical"]},
    )
    sesion_id = resp.get_json()["sesion_id"]
    _procesar_sesion_completa(client, sesion_id)

    for ruta, hash_antes in hashes_antes.items():
        assert hashlib.sha256(almacen[ruta]).hexdigest() == hash_antes, "Un original cambio durante el procesamiento de la sesion."


# --- Proteccion facial -------------------------------------------------------------

def test_proteccion_facial_se_mantiene_en_procesamiento_de_sesion(client, usuario_a_con_empresa, monkeypatch):
    empresa_id = usuario_a_con_empresa["empresa_id"]
    _almacen, proyecto, fotos, _logo_id = _crear_proyecto_con_fotos(client, monkeypatch, empresa_id, [FOTO_ROSTRO])
    preset_id = _obtener_preset_automatico_id(client)

    resp = client.post(
        f"/photo-studio/proyectos/{proyecto.id}/sesiones",
        json={"fotografia_ids": [fotos[0].id], "preset_id": preset_id, "formatos": ["mejora_automatica"]},
    )
    sesion_id = resp.get_json()["sesion_id"]
    _procesar_sesion_completa(client, sesion_id)

    from app.services.derivados import obtener_derivados_fotografia

    with client.application.app_context():
        derivados = obtener_derivados_fotografia(fotos[0].id)
        mejora = next(d for d in derivados if d.tipo == "mejora_automatica")
        assert mejora.estado == "completada"
        assert mejora.rostros_detectados >= 1
        assert mejora.rostros_protegidos is True


# --- Formatos: dimensiones exactas -------------------------------------------------

def test_sesion_genera_los_tres_formatos_con_dimensiones_exactas(client, usuario_a_con_empresa, monkeypatch):
    empresa_id = usuario_a_con_empresa["empresa_id"]
    _almacen, proyecto, fotos, _logo_id = _crear_proyecto_con_fotos(client, monkeypatch, empresa_id, [FOTO_A])
    preset_id = _obtener_preset_automatico_id(client)

    resp = client.post(
        f"/photo-studio/proyectos/{proyecto.id}/sesiones",
        json={
            "fotografia_ids": [fotos[0].id], "preset_id": preset_id,
            "formatos": ["formato_cuadrado", "formato_vertical", "formato_historia"],
        },
    )
    sesion_id = resp.get_json()["sesion_id"]
    _procesar_sesion_completa(client, sesion_id)

    from app.services.derivados import obtener_derivados_fotografia

    with client.application.app_context():
        derivados = {d.tipo: d for d in obtener_derivados_fotografia(fotos[0].id)}
        assert (derivados["formato_cuadrado"].ancho_px, derivados["formato_cuadrado"].alto_px) == (1080, 1080)
        assert (derivados["formato_vertical"].ancho_px, derivados["formato_vertical"].alto_px) == (1080, 1350)
        assert (derivados["formato_historia"].ancho_px, derivados["formato_historia"].alto_px) == (1080, 1920)


# --- Logo ---------------------------------------------------------------------------

def test_sesion_aplica_el_logo_seleccionado(client, usuario_a_con_empresa, monkeypatch):
    empresa_id = usuario_a_con_empresa["empresa_id"]
    _almacen, proyecto, fotos, logo_id = _crear_proyecto_con_fotos(client, monkeypatch, empresa_id, [FOTO_A])
    preset_id = _obtener_preset_automatico_id(client)

    resp = client.post(
        f"/photo-studio/proyectos/{proyecto.id}/sesiones",
        json={
            "fotografia_ids": [fotos[0].id], "preset_id": preset_id, "logo_id": logo_id,
            "aplicacion": "marca_agua", "posicion": "centro", "opacidad": 0.5,
            "formatos": ["formato_cuadrado"],
        },
    )
    sesion_id = resp.get_json()["sesion_id"]
    _procesar_sesion_completa(client, sesion_id)

    from app.services.derivados import obtener_derivados_fotografia

    with client.application.app_context():
        derivado = obtener_derivados_fotografia(fotos[0].id)[0]
        assert derivado.logo_id == logo_id
        assert derivado.aplicacion_logo == "marca_agua"
        assert derivado.posicion_logo == "centro"
        assert derivado.opacidad_logo == 0.5


# --- Aislamiento multiempresa --------------------------------------------------------

def test_sesion_de_otra_empresa_no_es_accesible(client, usuario_a_con_empresa, usuario_b_con_empresa, monkeypatch):
    iniciar_sesion_de_prueba(client, usuario_a_con_empresa["usuario_id"], "a@example.com")
    empresa_a_id = usuario_a_con_empresa["empresa_id"]
    _almacen, proyecto, fotos, _logo_id = _crear_proyecto_con_fotos(client, monkeypatch, empresa_a_id, [FOTO_A])
    preset_id = _obtener_preset_automatico_id(client)

    resp = client.post(
        f"/photo-studio/proyectos/{proyecto.id}/sesiones",
        json={"fotografia_ids": [fotos[0].id], "preset_id": preset_id, "formatos": ["mejora_automatica"]},
    )
    sesion_id = resp.get_json()["sesion_id"]

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    assert client.get(f"/photo-studio/sesiones/{sesion_id}").status_code == 404
    assert client.post(f"/photo-studio/sesiones/{sesion_id}/procesar-uno").status_code == 404
    assert client.post(f"/photo-studio/sesiones/{sesion_id}/analizar").status_code == 404
    assert client.post(f"/photo-studio/sesiones/{sesion_id}/cancelar").status_code == 404


def test_no_se_puede_crear_sesion_con_fotografia_de_otra_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa, monkeypatch):
    iniciar_sesion_de_prueba(client, usuario_a_con_empresa["usuario_id"], "a@example.com")
    _almacen_a, _proyecto_a, fotos_a, _logo_a = _crear_proyecto_con_fotos(client, monkeypatch, usuario_a_con_empresa["empresa_id"], [FOTO_A])

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    _almacen_b, proyecto_b, _fotos_b, _logo_b = _crear_proyecto_con_fotos(client, monkeypatch, usuario_b_con_empresa["empresa_id"], [FOTO_B])
    preset_id = _obtener_preset_automatico_id(client)

    resp = client.post(
        f"/photo-studio/proyectos/{proyecto_b.id}/sesiones",
        json={"fotografia_ids": [fotos_a[0].id], "preset_id": preset_id, "formatos": ["mejora_automatica"]},
    )
    assert resp.status_code == 400


# --- Error individual no detiene la sesion; completada_con_errores --------------

def test_error_individual_no_detiene_la_sesion_y_queda_completada_con_errores(client, usuario_a_con_empresa, monkeypatch):
    empresa_id = usuario_a_con_empresa["empresa_id"]
    almacen, proyecto, fotos, _logo_id = _crear_proyecto_con_fotos(client, monkeypatch, empresa_id, [FOTO_A])

    from app.services.fotografia import crear_fotografia

    with client.application.app_context():
        foto_mala = crear_fotografia(
            empresa_id, proyecto.id, "mala.png", "ruta/inexistente.png", "image/png", 10, usuario_a_con_empresa["usuario_id"]
        )
        foto_mala_id = foto_mala.id
    # No se sube nada a `almacen` para esta ruta -> fallara al descargarla.

    preset_id = _obtener_preset_automatico_id(client)
    resp = client.post(
        f"/photo-studio/proyectos/{proyecto.id}/sesiones",
        json={"fotografia_ids": [fotos[0].id, foto_mala_id], "preset_id": preset_id, "formatos": ["mejora_automatica"]},
    )
    sesion_id = resp.get_json()["sesion_id"]
    resultado = _procesar_sesion_completa(client, sesion_id)

    assert resultado["completadas"] == 1
    assert resultado["errores"] == 1
    assert resultado["sesion_estado"] == "completada_con_errores"

    from app.services.sesiones import obtener_items_sesion

    with client.application.app_context():
        items = {i.fotografia_id: i for i in obtener_items_sesion(sesion_id)}
        assert items[fotos[0].id].estado == "completada"
        assert items[foto_mala_id].estado == "error"
        assert items[foto_mala_id].error_mensaje


# --- Versionado: nunca sobrescribe -------------------------------------------------

def test_reprocesar_la_misma_foto_en_otra_sesion_crea_nueva_version(client, usuario_a_con_empresa, monkeypatch):
    empresa_id = usuario_a_con_empresa["empresa_id"]
    _almacen, proyecto, fotos, _logo_id = _crear_proyecto_con_fotos(client, monkeypatch, empresa_id, [FOTO_A])
    preset_id = _obtener_preset_automatico_id(client)

    resp1 = client.post(
        f"/photo-studio/proyectos/{proyecto.id}/sesiones",
        json={"fotografia_ids": [fotos[0].id], "preset_id": preset_id, "formatos": ["mejora_automatica"]},
    )
    _procesar_sesion_completa(client, resp1.get_json()["sesion_id"])

    resp2 = client.post(
        f"/photo-studio/proyectos/{proyecto.id}/sesiones",
        json={"fotografia_ids": [fotos[0].id], "preset_id": preset_id, "formatos": ["mejora_automatica"]},
    )
    _procesar_sesion_completa(client, resp2.get_json()["sesion_id"])

    from app.services.derivados import obtener_derivados_fotografia

    with client.application.app_context():
        derivados = obtener_derivados_fotografia(fotos[0].id)
        assert len(derivados) == 2
        versiones = sorted(d.version for d in derivados)
        assert versiones == [1, 2]
        rutas = {d.ruta_storage for d in derivados}
        assert len(rutas) == 2  # dos archivos distintos, ninguno sobreescribio al otro
