"""Proyectos fotograficos y fotografias de Photo Studio.

Regla fundamental: el archivo original nunca se modifica (ver
app/models/fotografia.py). Ninguna funcion aqui valida permisos de
usuario -- eso es responsabilidad de las rutas, que deben llamar a
estas funciones solo con una empresa ya validada (normalmente la
empresa activa, via app.core.empresas).
"""


def obtener_proyectos_empresa(empresa_id):
    from app.extensions import db
    from app.models import ProyectoFotografico

    return (
        db.session.query(ProyectoFotografico)
        .filter_by(empresa_id=empresa_id)
        .order_by(ProyectoFotografico.creado_en.desc())
        .all()
    )


def obtener_proyecto(empresa_id, proyecto_id):
    """Devuelve el proyecto solo si pertenece a la empresa indicada."""
    from app.extensions import db
    from app.models import ProyectoFotografico

    return (
        db.session.query(ProyectoFotografico)
        .filter_by(id=proyecto_id, empresa_id=empresa_id)
        .first()
    )


def crear_proyecto(empresa_id, nombre, descripcion, usuario_id):
    from app.extensions import db
    from app.models import ProyectoFotografico

    proyecto = ProyectoFotografico(
        empresa_id=empresa_id,
        nombre=nombre,
        descripcion=descripcion or None,
        creado_por=usuario_id,
    )
    db.session.add(proyecto)
    db.session.commit()
    return proyecto


def contar_fotografias(proyecto_id):
    from app.extensions import db
    from app.models import Fotografia

    return db.session.query(Fotografia).filter_by(proyecto_id=proyecto_id, activo=True).count()


def obtener_fotografias_proyecto(proyecto_id):
    from app.extensions import db
    from app.models import Fotografia

    return (
        db.session.query(Fotografia)
        .filter_by(proyecto_id=proyecto_id, activo=True)
        .order_by(Fotografia.creado_en.desc())
        .all()
    )


def obtener_fotografias_recientes_empresa(empresa_id, limite=30):
    """Fotografias mas recientes de la empresa, sin importar el
    proyecto -- Paso 11: sirve para elegir una "foto de muestra" al
    previsualizar un preset desde la biblioteca (que no esta atada a
    un proyecto en particular, los presets son de toda la empresa).
    """
    from app.extensions import db
    from app.models import Fotografia

    return (
        db.session.query(Fotografia)
        .filter_by(empresa_id=empresa_id, activo=True)
        .order_by(Fotografia.creado_en.desc())
        .limit(limite)
        .all()
    )


def obtener_fotografia(empresa_id, fotografia_id):
    """Devuelve la fotografia solo si pertenece a la empresa indicada."""
    from app.extensions import db
    from app.models import Fotografia

    return (
        db.session.query(Fotografia)
        .filter_by(id=fotografia_id, empresa_id=empresa_id)
        .first()
    )


def crear_fotografia(empresa_id, proyecto_id, nombre_archivo_original, ruta_storage, tipo_mime, tamano_bytes, subido_por):
    from app.extensions import db
    from app.models import Fotografia

    fotografia = Fotografia(
        empresa_id=empresa_id,
        proyecto_id=proyecto_id,
        nombre_archivo_original=nombre_archivo_original,
        ruta_storage=ruta_storage,
        tipo_mime=tipo_mime,
        tamano_bytes=tamano_bytes,
        subido_por=subido_por,
        estado="original",
    )
    db.session.add(fotografia)
    db.session.commit()
    return fotografia


def eliminar_fotografia(empresa_id, fotografia_id):
    """Elimina (soft-delete) una fotografia. El archivo original
    permanece intacto en Storage y el registro permanece en la base de
    datos (activo=False) -- nunca se destruye de verdad, dejando la
    puerta abierta a una papelera futura.
    """
    fotografia = obtener_fotografia(empresa_id, fotografia_id)
    if fotografia is None or not fotografia.activo:
        return False

    from app.extensions import db

    fotografia.activo = False
    db.session.commit()
    return True
