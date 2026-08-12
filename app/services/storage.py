"""Acceso a Supabase Storage para archivos de la plataforma.

Bucket privado (nunca publico): solo se accede via URLs firmadas de
corta duracion, generadas server-side despues de validar que el
usuario tiene acceso a la empresa duena del archivo. La `service_role
key` que esto usa nunca sale del backend.

Formatos de logo permitidos: PNG, JPEG y WebP. SVG queda deshabilitado
deliberadamente por ahora: un SVG puede contener <script> embebido y
ejecutarse si el navegador lo abre directamente (no solo via <img>),
y sanitizarlo correctamente requeriria una libreria adicional que no
se justifica en este paso.
"""

import os
import time
import uuid

from supabase import create_client

BUCKET_LOGOS = "logos"

TAMANO_MAXIMO_BYTES = 15 * 1024 * 1024  # 15 MB

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


def subir_archivo(ruta, contenido, tipo_mime):
    cliente = _cliente()
    if cliente is None:
        raise RuntimeError("Supabase Storage no esta configurado")
    cliente.storage.from_(BUCKET_LOGOS).upload(ruta, contenido, {"content-type": tipo_mime})


def eliminar_archivo(ruta):
    """Borrado best-effort: si falla, no debe romper el flujo principal
    (el registro en la base de datos es la fuente de verdad de la
    biblioteca; un archivo huerfano en Storage no es un problema
    critico, pero un error aqui no debe impedir que el usuario complete
    su accion en la app).
    """
    cliente = _cliente()
    if cliente is None:
        return
    try:
        cliente.storage.from_(BUCKET_LOGOS).remove([ruta])
    except Exception:
        pass


def url_firmada(ruta, segundos=3600):
    cliente = _cliente()
    if cliente is None:
        return None
    try:
        resultado = cliente.storage.from_(BUCKET_LOGOS).create_signed_url(ruta, segundos)
        return resultado.get("signedURL") or resultado.get("signedUrl")
    except Exception:
        return None
