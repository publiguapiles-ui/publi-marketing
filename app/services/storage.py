"""Acceso a Supabase Storage para archivos de la plataforma.

Buckets privados (nunca publicos): solo se accede via URLs firmadas de
corta duracion, generadas server-side despues de validar que el
usuario tiene acceso a la empresa duena del archivo. La `service_role
key` que esto usa nunca sale del backend.

Un unico sistema de almacenamiento para toda la plataforma -- logos
(Paso 5) y fotografias (Photo Studio) usan estas mismas funciones,
cada uno en su propio bucket, en vez de duplicar la logica.

Formatos permitidos: PNG, JPEG y WebP. SVG y RAW quedan deshabilitados
deliberadamente: SVG puede contener <script> embebido y ejecutarse si
el navegador lo abre directamente (no solo via <img>); RAW (CR2, NEF,
ARW, DNG, ...) comparte firmas de bytes con TIFF generico entre
fabricantes, por lo que no se puede distinguir con confianza solo por
los primeros bytes, y ademas todavia no hay nada en la plataforma que
sepa procesarlo. Ambos quedan como trabajo futuro documentado, no como
un descuido.
"""

import os
import time
import uuid

from supabase import create_client

BUCKET_LOGOS = "logos"
BUCKET_FOTOGRAFIAS = "fotografias"

TAMANO_MAXIMO_BYTES = 15 * 1024 * 1024  # 15 MB (logos)
TAMANO_MAXIMO_FOTO_BYTES = 30 * 1024 * 1024  # 30 MB (fotografias originales)

EXTENSIONES_PERMITIDAS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

_cliente_admin = None


def _cliente():
    global _cliente_admin
    if _cliente_admin is None and SUPABASE_URL and SUPABASE_KEY:
        _cliente_admin = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _cliente_admin


def storage_configurado():
    return _cliente() is not None


def detectar_tipo_mime_real(cabecera_bytes):
    """Detecta el formato real por los primeros bytes del archivo (no
    confia en el nombre/extension ni en el content-type que manda el
    navegador, que se pueden falsificar facilmente).
    """
    if cabecera_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if cabecera_bytes[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if cabecera_bytes[:4] == b"RIFF" and cabecera_bytes[8:12] == b"WEBP":
        return "image/webp"
    return None


def ruta_logo(empresa_id, tipo, tipo_mime):
    extension = EXTENSIONES_PERMITIDAS.get(tipo_mime, "bin")
    sufijo = uuid.uuid4().hex[:8]
    return f"empresas/{empresa_id}/branding/logos/{tipo}/{int(time.time())}-{sufijo}.{extension}"


def ruta_fotografia_original(empresa_id, proyecto_id, tipo_mime):
    extension = EXTENSIONES_PERMITIDAS.get(tipo_mime, "bin")
    sufijo = uuid.uuid4().hex[:8]
    return (
        f"empresas/{empresa_id}/fotografia/proyectos/{proyecto_id}/originales/"
        f"{int(time.time())}-{sufijo}.{extension}"
    )


_SUBCARPETA_FORMATO = {
    "formato_cuadrado": "square",
    "formato_vertical": "portrait",
    "formato_historia": "story",
    "formato_horizontal": "horizontal",
}


def ruta_derivado_formato(empresa_id, proyecto_id, tipo_formato):
    """Los formatos para redes (Paso 8) se guardan como JPEG de alta
    calidad (el lienzo final siempre es opaco, ver
    app/services/formatos.py), en su propia subcarpeta por tipo de
    formato, y nunca reemplazan un archivo existente.
    """
    subcarpeta = _SUBCARPETA_FORMATO.get(tipo_formato, "otros")
    sufijo = uuid.uuid4().hex[:8]
    return (
        f"empresas/{empresa_id}/fotografia/proyectos/{proyecto_id}/derivados/formatos/{subcarpeta}/"
        f"{int(time.time())}-{sufijo}.jpg"
    )


def ruta_derivado_mejora(empresa_id, proyecto_id):
    """Los derivados de mejora automatica siempre se guardan como PNG
    (sin perdida -- ver services/procesamiento.py), en su propia
    subcarpeta -- nunca en originales/, y nunca reemplazan un archivo
    existente (nombre unico por sufijo aleatorio + timestamp).
    """
    sufijo = uuid.uuid4().hex[:8]
    return (
        f"empresas/{empresa_id}/fotografia/proyectos/{proyecto_id}/derivados/mejoras/"
        f"{int(time.time())}-{sufijo}.png"
    )


def subir_archivo(bucket, ruta, contenido, tipo_mime):
    cliente = _cliente()
    if cliente is None:
        raise RuntimeError("Supabase Storage no esta configurado")
    cliente.storage.from_(bucket).upload(ruta, contenido, {"content-type": tipo_mime})


def descargar_archivo(bucket, ruta):
    """Descarga los bytes de un archivo (usado por el motor de
    procesamiento para leer el original -- nunca lo escribe de vuelta
    en esta misma ruta).
    """
    cliente = _cliente()
    if cliente is None:
        raise RuntimeError("Supabase Storage no esta configurado")
    return cliente.storage.from_(bucket).download(ruta)


def eliminar_archivo(bucket, ruta):
    """Borrado best-effort: si falla, no debe romper el flujo principal
    (el registro en la base de datos es la fuente de verdad; un
    archivo huerfano en Storage no es un problema critico, pero un
    error aqui no debe impedir que el usuario complete su accion).
    """
    cliente = _cliente()
    if cliente is None:
        return
    try:
        cliente.storage.from_(bucket).remove([ruta])
    except Exception:
        pass


def url_firmada(bucket, ruta, segundos=3600, nombre_descarga=None):
    cliente = _cliente()
    if cliente is None:
        return None
    try:
        opciones = {"download": nombre_descarga} if nombre_descarga else None
        resultado = cliente.storage.from_(bucket).create_signed_url(ruta, segundos, opciones)
        return resultado.get("signedURL") or resultado.get("signedUrl")
    except Exception:
        return None
