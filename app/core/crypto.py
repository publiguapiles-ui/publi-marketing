"""Cifrado en reposo para credenciales sensibles guardadas en base de
datos (Datos de Meta, Paso 1) -- pensado para reutilizarse con
cualquier integracion futura que necesite guardar un token de larga
duracion (Google Ads, TikTok Ads, etc.), no solo Meta.

Nunca se guarda un token de una plataforma externa en texto plano en
la base de datos. La clave de cifrado (Fernet, AES128 simetrico) vive
en la variable de entorno META_TOKEN_ENCRYPTION_KEY -- deliberadamente
SEPARADA de SECRET_KEY (que firma la cookie de sesion): son secretos
con proposito y ciclo de vida distintos, y comprometer uno no debe
comprometer el otro.
"""

import base64
import os

from cryptography.fernet import Fernet, InvalidToken


class ErrorCifrado(RuntimeError):
    """La clave de cifrado falta o es invalida."""


_fernet = None


def _clave_desde_entorno():
    clave = os.environ.get("META_TOKEN_ENCRYPTION_KEY")
    if not clave:
        return None
    try:
        # Valida que sea una clave Fernet real (32 bytes url-safe
        # base64) antes de usarla -- un valor mal copiado en Railway
        # debe fallar aqui, explicito, no al primer intento de cifrar.
        base64.urlsafe_b64decode(clave)
        return clave.encode() if isinstance(clave, str) else clave
    except Exception as exc:
        raise ErrorCifrado(
            "META_TOKEN_ENCRYPTION_KEY no es una clave Fernet valida. "
            "Genera una con: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        ) from exc


def _obtener_fernet():
    global _fernet
    if _fernet is not None:
        return _fernet

    clave = _clave_desde_entorno()
    if clave is None:
        entorno = os.environ.get("FLASK_ENV", "development")
        if entorno == "production":
            raise ErrorCifrado(
                "Falta META_TOKEN_ENCRYPTION_KEY en produccion. La aplicacion no debe "
                "guardar tokens de Meta sin cifrar. Configura esta variable en Railway "
                "con una clave Fernet (ver ErrorCifrado mas arriba para generarla)."
            )
        # Desarrollo/tests: clave efimera generada en memoria -- nunca
        # persiste entre reinicios, asi que un token guardado en la
        # base de datos local deja de poder descifrarse tras reiniciar
        # el proceso. Aceptable para desarrollo (no hay datos reales de
        # produccion en juego); nunca ocurre en produccion (ver arriba).
        clave = Fernet.generate_key()

    _fernet = Fernet(clave)
    return _fernet


def cifrar(texto_plano):
    """Cifra una cadena (ej. un access_token de Meta). Devuelve una
    cadena de texto lista para guardar en una columna Text/String."""
    if texto_plano is None:
        return None
    return _obtener_fernet().encrypt(texto_plano.encode("utf-8")).decode("ascii")


def descifrar(texto_cifrado):
    """Descifra un valor guardado con `cifrar`. Devuelve None si el
    valor esta vacio o si la clave actual no puede descifrarlo (ej. se
    guardo con una clave efimera de desarrollo de un proceso anterior)
    -- nunca lanza una excepcion por esto, el llamador decide que hacer
    con un token ilegible (tipicamente: pedir reconexion)."""
    if not texto_cifrado:
        return None
    try:
        return _obtener_fernet().decrypt(texto_cifrado.encode("ascii")).decode("utf-8")
    except InvalidToken:
        return None
