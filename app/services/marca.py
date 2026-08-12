"""Identidad de marca y logos de una empresa.

Esta es la biblioteca oficial de Publi Marketing: Photo Studio (y
cualquier modulo futuro) debe consumir estas mismas funciones en vez
de crear su propio sistema de logos. El flujo que usaran es:

    empresa_activa -> obtener_identidad(empresa.id)
                    -> obtener_logo_principal(empresa.id)
                    -> obtener_logo_marca_agua(empresa.id)

Ninguna funcion aqui valida permisos de usuario: eso es
responsabilidad de las rutas (via app.core.empresas), que deben
llamar a estas funciones solo despues de confirmar que el usuario
tiene acceso a la empresa en cuestion.
"""

import re

PATRON_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def color_valido(valor):
    return not valor or bool(PATRON_HEX.match(valor))


def obtener_identidad(empresa_id):
    from app.extensions import db
    from app.models import IdentidadMarca

    return db.session.query(IdentidadMarca).filter_by(empresa_id=empresa_id).first()


def guardar_identidad(empresa_id, nombre_comercial, color_principal, color_secundario, color_texto, color_fondo):
    from app.extensions import db
    from app.models import IdentidadMarca

    identidad = obtener_identidad(empresa_id)
    if identidad is None:
        identidad = IdentidadMarca(empresa_id=empresa_id)
        db.session.add(identidad)

    identidad.nombre_comercial = nombre_comercial or None
    identidad.color_principal = color_principal or None
    identidad.color_secundario = color_secundario or None
    identidad.color_texto = color_texto or None
    identidad.color_fondo = color_fondo or None
    db.session.commit()
    return identidad


def obtener_logos_empresa(empresa_id, tipo=None):
    from app.extensions import db
    from app.models import Logo

    consulta = db.session.query(Logo).filter_by(empresa_id=empresa_id, activo=True)
    if tipo:
        consulta = consulta.filter_by(tipo=tipo)
    return consulta.order_by(Logo.creado_en.desc()).all()


def obtener_logo(empresa_id, logo_id):
    """Devuelve el logo solo si pertenece a la empresa indicada (o None)."""
    from app.extensions import db
    from app.models import Logo

    return db.session.query(Logo).filter_by(id=logo_id, empresa_id=empresa_id).first()


def obtener_logo_principal(empresa_id):
    from app.extensions import db
    from app.models import Logo

    return db.session.query(Logo).filter_by(empresa_id=empresa_id, es_principal=True, activo=True).first()


def obtener_logo_marca_agua(empresa_id):
    from app.extensions import db
    from app.models import Logo

    return db.session.query(Logo).filter_by(empresa_id=empresa_id, es_marca_agua=True, activo=True).first()


def crear_logo(empresa_id, tipo, nombre_archivo_original, ruta_storage, tipo_mime, tamano_bytes, subido_por):
    from app.extensions import db
    from app.models import Logo

    logo = Logo(
        empresa_id=empresa_id,
        tipo=tipo,
        nombre_archivo_original=nombre_archivo_original,
        ruta_storage=ruta_storage,
        tipo_mime=tipo_mime,
        tamano_bytes=tamano_bytes,
        subido_por=subido_por,
    )
    db.session.add(logo)
    db.session.commit()
    return logo


def marcar_logo_principal(empresa_id, logo_id):
    """Marca este logo como principal y desmarca cualquier otro de la
    misma empresa. Devuelve False si el logo no pertenece a la empresa.
    """
    from app.extensions import db
    from app.models import Logo

    logo = obtener_logo(empresa_id, logo_id)
    if logo is None or not logo.activo:
        return False

    db.session.query(Logo).filter(
        Logo.empresa_id == empresa_id, Logo.id != logo_id, Logo.es_principal.is_(True)
    ).update({"es_principal": False})

    logo.es_principal = True
    db.session.commit()
    return True


def marcar_logo_marca_agua(empresa_id, logo_id):
    from app.extensions import db
    from app.models import Logo

    logo = obtener_logo(empresa_id, logo_id)
    if logo is None or not logo.activo:
        return False

    db.session.query(Logo).filter(
        Logo.empresa_id == empresa_id, Logo.id != logo_id, Logo.es_marca_agua.is_(True)
    ).update({"es_marca_agua": False})

    logo.es_marca_agua = True
    db.session.commit()
    return True


def reemplazar_archivo_logo(empresa_id, logo_id, nombre_archivo_original, ruta_storage, tipo_mime, tamano_bytes):
    """Actualiza el archivo de un logo existente sin tocar su id, tipo
    ni banderas (es_principal/es_marca_agua), para no romper ninguna
    referencia que ya apunte a este logo. El archivo anterior en
    Storage no se toca aqui: queda huerfano mas que perdido, a
    proposito (ver services/storage.py).
    """
    logo = obtener_logo(empresa_id, logo_id)
    if logo is None or not logo.activo:
        return None

    from app.extensions import db

    logo.nombre_archivo_original = nombre_archivo_original
    logo.ruta_storage = ruta_storage
    logo.tipo_mime = tipo_mime
    logo.tamano_bytes = tamano_bytes
    db.session.commit()
    return logo


def eliminar_logo(empresa_id, logo_id):
    """Elimina (soft-delete) un logo de la biblioteca. El archivo
    original permanece en Storage y el registro permanece en la base
    de datos (activo=False), nunca se destruye: si estaba marcado como
    principal o marca de agua, se desmarca.
    """
    logo = obtener_logo(empresa_id, logo_id)
    if logo is None or not logo.activo:
        return False

    from app.extensions import db

    logo.activo = False
    logo.es_principal = False
    logo.es_marca_agua = False
    db.session.commit()
    return True
