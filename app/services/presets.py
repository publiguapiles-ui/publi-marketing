"""Presets de correccion fotografica (Paso 10).

Un preset NUNCA es un filtro fijo ni un segundo motor de correccion:
es un conjunto de objetivos que sesga los mismos calculos adaptativos
que ya existen en app/services/procesamiento.py. "Automatico" es,
literalmente, el preset cuyos parametros reproducen el comportamiento
que procesamiento.py ya tenia antes de este paso -- no esta
hardcodeado aparte, usa el mismo mecanismo de datos que los demas, así
que mejorarlo despues es cuestion de ajustar sus parametros (o
extender el motor), nunca de tocar un caso especial en el codigo.

Ninguna funcion aqui valida permisos de usuario -- eso es
responsabilidad de las rutas, igual que en app/services/marca.py.
"""

# Objetivos moderados y profesionales -- ver Paso 10: se evita
# deliberadamente sobresaturacion, contraste excesivo, pieles
# anaranjadas, perdida de detalle y quemado de altas luces. Los
# valores de "automatico" son EXACTAMENTE los que procesamiento.py
# usaba como constantes fijas antes de este paso (compatibilidad
# total con el comportamiento ya verificado en el Paso 7).
PARAMETROS_PRESETS_SISTEMA = {
    "automatico": {
        "nombre": "Automático",
        "descripcion": "Analiza cada fotografía y corrige solo lo necesario. Punto de partida conservador.",
        "parametros": {
            "objetivo_brillo": 0.5,
            "objetivo_contraste": 0.22,
            "objetivo_saturacion": 0.35,
            "factor_maximo_saturacion": 1.35,
            "sesgo_calidez": 0.0,
            "intensidad_nitidez": 80,
        },
    },
    "natural": {
        "nombre": "Natural",
        "descripcion": "Correcciones mínimas, fiel al color original.",
        "parametros": {
            "objetivo_brillo": 0.5,
            "objetivo_contraste": 0.20,
            "objetivo_saturacion": 0.32,
            "factor_maximo_saturacion": 1.20,
            "sesgo_calidez": 0.0,
            "intensidad_nitidez": 70,
        },
    },
    "calido": {
        "nombre": "Cálido",
        "descripcion": "Tonos ligeramente más cálidos, sin perder naturalidad.",
        "parametros": {
            "objetivo_brillo": 0.5,
            "objetivo_contraste": 0.22,
            "objetivo_saturacion": 0.35,
            "factor_maximo_saturacion": 1.30,
            "sesgo_calidez": 0.35,
            "intensidad_nitidez": 80,
        },
    },
    "frio": {
        "nombre": "Frío",
        "descripcion": "Tonos ligeramente más fríos, sin perder naturalidad.",
        "parametros": {
            "objetivo_brillo": 0.5,
            "objetivo_contraste": 0.22,
            "objetivo_saturacion": 0.35,
            "factor_maximo_saturacion": 1.30,
            "sesgo_calidez": -0.35,
            "intensidad_nitidez": 80,
        },
    },
    "comercial": {
        "nombre": "Comercial",
        "descripcion": "Contraste y nitidez con más presencia, ideal para catálogos.",
        "parametros": {
            "objetivo_brillo": 0.52,
            "objetivo_contraste": 0.26,
            "objetivo_saturacion": 0.38,
            "factor_maximo_saturacion": 1.30,
            "sesgo_calidez": 0.0,
            "intensidad_nitidez": 90,
        },
    },
    "vibrante": {
        "nombre": "Vibrante",
        "descripcion": "Colores más vivos, con techo para evitar irrealismo.",
        "parametros": {
            "objetivo_brillo": 0.5,
            "objetivo_contraste": 0.25,
            "objetivo_saturacion": 0.42,
            "factor_maximo_saturacion": 1.45,
            "sesgo_calidez": 0.0,
            "intensidad_nitidez": 80,
        },
    },
    "cinematico": {
        "nombre": "Cinemático",
        "descripcion": "Más contraste, saturación contenida, atmósfera de cine.",
        "parametros": {
            "objetivo_brillo": 0.48,
            "objetivo_contraste": 0.28,
            "objetivo_saturacion": 0.30,
            "factor_maximo_saturacion": 1.25,
            "sesgo_calidez": 0.10,
            "intensidad_nitidez": 70,
        },
    },
    "evento": {
        "nombre": "Evento",
        "descripcion": "Pensado para interiores con luz variable y muchas personas.",
        "parametros": {
            "objetivo_brillo": 0.52,
            "objetivo_contraste": 0.24,
            "objetivo_saturacion": 0.36,
            "factor_maximo_saturacion": 1.30,
            "sesgo_calidez": 0.0,
            "intensidad_nitidez": 85,
        },
    },
    "producto": {
        "nombre": "Producto",
        "descripcion": "Color fiel y nitidez alta para catálogo de productos.",
        "parametros": {
            "objetivo_brillo": 0.5,
            "objetivo_contraste": 0.26,
            "objetivo_saturacion": 0.34,
            "factor_maximo_saturacion": 1.25,
            "sesgo_calidez": 0.0,
            "intensidad_nitidez": 100,
        },
    },
    "interior": {
        "nombre": "Interior",
        "descripcion": "Corrige el sesgo cálido típico de luz artificial de interiores.",
        "parametros": {
            "objetivo_brillo": 0.53,
            "objetivo_contraste": 0.22,
            "objetivo_saturacion": 0.34,
            "factor_maximo_saturacion": 1.25,
            "sesgo_calidez": -0.15,
            "intensidad_nitidez": 80,
        },
    },
    "exterior": {
        "nombre": "Exterior",
        "descripcion": "Pensado para luz natural, con un toque cálido de hora dorada.",
        "parametros": {
            "objetivo_brillo": 0.48,
            "objetivo_contraste": 0.24,
            "objetivo_saturacion": 0.36,
            "factor_maximo_saturacion": 1.30,
            "sesgo_calidez": 0.05,
            "intensidad_nitidez": 80,
        },
    },
}


def sembrar_presets_sistema():
    """Crea los presets de sistema si todavia no existen -- idempotente,
    segura de llamar en cada arranque de la app (ver create_app()).

    No se hizo con datos de la migracion (op.bulk_insert no persistia
    de forma confiable bajo el modo "non-transactional DDL" que
    Alembic usa aqui para SQLite); esta via funciona igual en SQLite y
    en Postgres, y usa la misma sesion/transaccion que el resto de la
    aplicacion.
    """
    from app.extensions import db
    from app.models import Preset

    existentes = {slug for (slug,) in db.session.query(Preset.slug).filter_by(es_sistema=True)}
    faltantes = [slug for slug in PARAMETROS_PRESETS_SISTEMA if slug not in existentes]
    if not faltantes:
        return

    for slug in faltantes:
        datos = PARAMETROS_PRESETS_SISTEMA[slug]
        db.session.add(
            Preset(
                slug=slug,
                nombre=datos["nombre"],
                descripcion=datos["descripcion"],
                empresa_id=None,
                es_sistema=True,
                parametros=datos["parametros"],
                activo=True,
            )
        )
    db.session.commit()


def obtener_presets_disponibles(empresa_id):
    """Presets de sistema + los propios de esta empresa (personalizados
    -- todavia no hay forma de crearlos en la interfaz, pero la
    consulta ya los incluiria si existieran).
    """
    from app.extensions import db
    from app.models import Preset

    return (
        db.session.query(Preset)
        .filter(Preset.activo.is_(True))
        .filter((Preset.es_sistema.is_(True)) | (Preset.empresa_id == empresa_id))
        .order_by(Preset.es_sistema.desc(), Preset.nombre)
        .all()
    )


def obtener_preset(empresa_id, preset_id):
    """Devuelve el preset solo si es de sistema o pertenece a esta
    empresa -- mismo patron de aislamiento que obtener_logo en
    app/services/marca.py.
    """
    from app.extensions import db
    from app.models import Preset

    preset = db.session.query(Preset).filter_by(id=preset_id, activo=True).first()
    if preset is None:
        return None
    if preset.es_sistema or preset.empresa_id == empresa_id:
        return preset
    return None


def obtener_preset_automatico():
    from app.extensions import db
    from app.models import Preset

    return db.session.query(Preset).filter_by(slug="automatico", es_sistema=True, activo=True).first()
