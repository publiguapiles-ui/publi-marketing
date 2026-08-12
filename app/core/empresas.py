"""Empresa activa y control de acceso multiempresa.

Toda validacion de "este usuario puede ver esta empresa" pasa por aqui.
Ninguna otra parte del codigo debe confiar directamente en un
empresa_id que venga del navegador (formulario, query string, sesion)
sin pasar por estas funciones.
"""

from flask import session

from app.core.auth import obtener_usuario_actual


def obtener_empresas_usuario(usuario_id):
    """Lista de (Empresa, Rol) a las que el usuario tiene acceso, por nombre."""
    from app.extensions import db
    from app.models import Empresa, Rol, UsuarioEmpresaRol

    return (
        db.session.query(Empresa, Rol)
        .join(UsuarioEmpresaRol, UsuarioEmpresaRol.empresa_id == Empresa.id)
        .join(Rol, Rol.id == UsuarioEmpresaRol.rol_id)
        .filter(UsuarioEmpresaRol.usuario_id == usuario_id)
        .order_by(Empresa.nombre)
        .all()
    )


def usuario_tiene_acceso_a_empresa(usuario_id, empresa_id):
    """Verificacion de autorizacion real contra la base de datos."""
    from app.extensions import db
    from app.models import UsuarioEmpresaRol

    if usuario_id is None or empresa_id is None:
        return False

    return (
        db.session.query(UsuarioEmpresaRol)
        .filter_by(usuario_id=usuario_id, empresa_id=empresa_id)
        .first()
        is not None
    )


def obtener_rol_usuario_en_empresa(usuario_id, empresa_id):
    from app.extensions import db
    from app.models import Rol, UsuarioEmpresaRol

    return (
        db.session.query(Rol)
        .join(UsuarioEmpresaRol, UsuarioEmpresaRol.rol_id == Rol.id)
        .filter(UsuarioEmpresaRol.usuario_id == usuario_id, UsuarioEmpresaRol.empresa_id == empresa_id)
        .first()
    )


def obtener_empresa_activa():
    """Devuelve (Empresa, Rol) activos y ya validados para el usuario
    actual, o (None, None) si no aplica.

    La empresa activa vive en la sesion de Flask (cookie firmada, se
    limpia con el resto de la sesion en logout o al expirar), pero
    nunca se usa sin antes confirmar contra la base de datos que el
    usuario realmente tiene acceso a ella. Si el usuario tiene una
    unica empresa, se selecciona automaticamente.
    """
    usuario = obtener_usuario_actual()
    if usuario is None:
        return None, None

    empresas = obtener_empresas_usuario(usuario["id"])
    if not empresas:
        return None, None

    empresa_id_sesion = session.get("empresa_activa_id")
    if empresa_id_sesion is not None:
        for empresa, rol in empresas:
            if empresa.id == empresa_id_sesion:
                return empresa, rol
        # La empresa guardada en la cookie ya no es valida para este
        # usuario (removida, o la sesion fue manipulada): se descarta.
        session.pop("empresa_activa_id", None)

    if len(empresas) == 1:
        empresa, rol = empresas[0]
        session["empresa_activa_id"] = empresa.id
        return empresa, rol

    return None, None


def establecer_empresa_activa(empresa_id):
    """Fija la empresa activa solo si el usuario tiene acceso a ella.

    Devuelve True si se establecio, False si el usuario no esta
    autorizado (en cuyo caso no se cambia nada).
    """
    usuario = obtener_usuario_actual()
    if usuario is None:
        return False

    if not usuario_tiene_acceso_a_empresa(usuario["id"], empresa_id):
        return False

    session["empresa_activa_id"] = empresa_id
    return True
