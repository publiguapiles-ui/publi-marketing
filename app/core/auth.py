import os
import time

from flask import session
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")

_cliente_auth = None


def obtener_cliente_auth():
    """Cliente de Supabase para autenticacion de usuarios finales.

    Usa siempre la anon key, nunca la service_role key (esa se reserva
    para operaciones administrativas server-side, como en el modulo
    legacy_solicitudes).
    """
    global _cliente_auth
    if _cliente_auth is None and SUPABASE_URL and SUPABASE_ANON_KEY:
        _cliente_auth = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    return _cliente_auth


def _sincronizar_usuario_local(usuario_supabase, nombre):
    """Crea o actualiza la fila local en `usuarios` para el usuario ya
    autenticado por Supabase Auth. Solo guarda id/nombre/email: nunca
    contrasenas, y nunca duplica lo que Supabase Auth ya administra.
    """
    from app.extensions import db
    from app.models import Usuario

    registro = db.session.get(Usuario, usuario_supabase.id)
    if registro is None:
        registro = Usuario(id=usuario_supabase.id, nombre=nombre or usuario_supabase.email, email=usuario_supabase.email)
        db.session.add(registro)
    else:
        registro.email = usuario_supabase.email
        if nombre:
            registro.nombre = nombre
    db.session.commit()


def iniciar_sesion(auth_response):
    """Guarda en la sesion de Flask (cookie firmada) los datos minimos
    del usuario ya autenticado por Supabase Auth. No se guarda la
    contrasena en ningun momento: solo pasa por memoria durante la
    llamada a Supabase y nunca se persiste.
    """
    usuario = auth_response.user
    datos_sesion = auth_response.session
    nombre = (usuario.user_metadata or {}).get("nombre")

    _sincronizar_usuario_local(usuario, nombre)

    session.clear()
    session["usuario_id"] = usuario.id
    session["usuario_email"] = usuario.email
    session["usuario_nombre"] = nombre
    session["expires_at"] = datos_sesion.expires_at
    session["access_token"] = datos_sesion.access_token
    session["refresh_token"] = datos_sesion.refresh_token


def cerrar_sesion():
    session.clear()


def _sesion_expirada():
    expira = session.get("expires_at")
    if expira is None:
        return False
    return time.time() >= expira


def obtener_usuario_actual():
    """Devuelve un dict {id, email, nombre} del usuario autenticado en
    la sesion actual, o None si no hay sesion valida (incluye el caso
    de sesion expirada, que se limpia automaticamente aqui).
    """
    if "usuario_id" not in session:
        return None

    if _sesion_expirada():
        cerrar_sesion()
        return None

    return {
        "id": session["usuario_id"],
        "email": session.get("usuario_email"),
        "nombre": session.get("usuario_nombre"),
    }
