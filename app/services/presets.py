"""Presets de correccion fotografica (Paso 10) + biblioteca profesional
de presets, categorias, favoritos y personalizacion por empresa (Paso 11).

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

# Paso 11: categorias para organizar la biblioteca. None = sin
# categoria (uso general, como "Automatico" o "Natural" -- forzarles
# una categoria de sujeto/contexto seria enganoso).
CATEGORIAS_PRESET = [
    "personas",
    "eventos",
    "producto",
    "comida",
    "interior",
    "exterior",
    "comercial",
    "creativo",
    "personalizado",
]

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
        "categoria": None,
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
        "categoria": None,
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
        "categoria": None,
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
        "categoria": None,
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
        "categoria": "comercial",
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
        "categoria": None,
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
        "categoria": "creativo",
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
        "categoria": "eventos",
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
        "categoria": "producto",
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
        "categoria": "interior",
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
        "categoria": "exterior",
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


# Paso 11: rango valido (minimo, maximo, valor_por_defecto) de cada
# parametro del motor ACTIVO. Se usa tanto para normalizar entradas del
# editor (crear/editar preset) como para poblar los sliders en la
# plantilla -- una sola fuente de verdad para ambos.
CAMPOS_MOTOR = {
    "objetivo_brillo": (0.0, 1.0, 0.5),
    "intensidad_exposicion": (0.0, 1.0, 1.0),
    "objetivo_contraste": (0.0, 1.0, 0.22),
    "intensidad_contraste": (0.0, 1.0, 1.0),
    "sesgo_calidez": (-1.0, 1.0, 0.0),
    "intensidad_calidez": (0.0, 1.0, 1.0),
    "objetivo_saturacion": (0.0, 1.0, 0.35),
    "factor_maximo_saturacion": (1.0, 2.0, 1.35),
    "intensidad_saturacion": (0.0, 1.0, 1.0),
    "intensidad_nitidez": (0.0, 150.0, 80.0),
}

# Paso 11: campos "avanzados" que la ESTRUCTURA del preset ya puede
# almacenar (ver Paso 11, seccion "CONFIGURACION DEL PRESET": matiz,
# vibrance, sombras, luces, blancos, negros, reduccion de ruido) pero
# que app/services/procesamiento.py todavia NO lee -- quedan
# reservados para una etapa futura del motor, tal como pide el
# enunciado ("no es obligatorio implementar todos estos parametros en
# el motor todavia"). Se guardan bajo parametros["avanzado"], una
# clave que _resolver_parametros() de procesamiento.py ignora sin
# error (no esta en PARAMETROS_POR_DEFECTO), asi que no tiene ningun
# efecto en el resultado hasta que el motor los use explicitamente.
CAMPOS_AVANZADOS = {
    "matiz_ajuste": (-1.0, 1.0, 0.0),
    "matiz_intensidad": (0.0, 1.0, 0.0),
    "vibrance_intensidad": (0.0, 1.0, 0.0),
    "sombras_elevacion": (0.0, 1.0, 0.0),
    "sombras_limite": (0.0, 1.0, 0.0),
    "luces_reduccion": (0.0, 1.0, 0.0),
    "luces_limite": (0.0, 1.0, 0.0),
    "blancos_ajuste": (-1.0, 1.0, 0.0),
    "negros_ajuste": (-1.0, 1.0, 0.0),
    "reduccion_ruido_intensidad": (0.0, 1.0, 0.0),
}


def normalizar_parametros(entrada):
    """Convierte una entrada arbitraria (form/JSON del editor) en un
    dict de parametros completo y con todos los valores dentro de su
    rango valido -- nunca confia en los numeros que manda el cliente.
    Los campos ausentes toman su valor por defecto (el mismo que
    procesamiento.PARAMETROS_POR_DEFECTO para los campos activos).
    """
    entrada = entrada or {}
    resultado = {}
    for clave, (minimo, maximo, defecto) in CAMPOS_MOTOR.items():
        try:
            valor = float(entrada.get(clave, defecto))
        except (TypeError, ValueError):
            valor = defecto
        resultado[clave] = round(max(minimo, min(maximo, valor)), 4)

    avanzado_entrada = entrada.get("avanzado") or {}
    avanzado = {}
    for clave, (minimo, maximo, defecto) in CAMPOS_AVANZADOS.items():
        try:
            valor = float(avanzado_entrada.get(clave, defecto))
        except (TypeError, ValueError):
            valor = defecto
        avanzado[clave] = round(max(minimo, min(maximo, valor)), 4)
    resultado["avanzado"] = avanzado
    return resultado


def sembrar_presets_sistema():
    """Crea los presets de sistema si todavia no existen -- idempotente,
    segura de llamar en cada arranque de la app (ver create_app()).

    No se hizo con datos de la migracion (op.bulk_insert no persistia
    de forma confiable bajo el modo "non-transactional DDL" que
    Alembic usa aqui para SQLite); esta via funciona igual en SQLite y
    en Postgres, y usa la misma sesion/transaccion que el resto de la
    aplicacion.

    Tambien sincroniza `categoria` en presets de sistema YA existentes
    (Paso 11 agrego categorias que el Paso 10 no tenia) -- nunca toca
    `parametros` de un preset ya sembrado, eso rompería la garantia de
    compatibilidad total del Paso 10.
    """
    from app.extensions import db
    from app.models import Preset

    existentes = {p.slug: p for p in db.session.query(Preset).filter_by(es_sistema=True).all()}
    hubo_cambios = False

    for slug, datos in PARAMETROS_PRESETS_SISTEMA.items():
        if slug in existentes:
            preset = existentes[slug]
            if preset.categoria != datos.get("categoria"):
                preset.categoria = datos.get("categoria")
                hubo_cambios = True
            continue
        db.session.add(
            Preset(
                slug=slug,
                nombre=datos["nombre"],
                descripcion=datos["descripcion"],
                categoria=datos.get("categoria"),
                empresa_id=None,
                es_sistema=True,
                version=1,
                parametros=datos["parametros"],
                activo=True,
            )
        )
        hubo_cambios = True

    if hubo_cambios:
        db.session.commit()


def obtener_presets_disponibles(empresa_id):
    """Presets de sistema + los propios de esta empresa (personalizados)."""
    from app.extensions import db
    from app.models import Preset

    return (
        db.session.query(Preset)
        .filter(Preset.activo.is_(True))
        .filter((Preset.es_sistema.is_(True)) | (Preset.empresa_id == empresa_id))
        .order_by(Preset.es_sistema.desc(), Preset.nombre)
        .all()
    )


def obtener_presets_agrupados(empresa_id):
    """Agrupa los presets disponibles para la biblioteca (Paso 11):
    favoritos primero, luego presets de sistema, luego los propios de
    la empresa. Un preset favorito aparece SOLO en "favoritos" (no se
    duplica tambien en su grupo original) para que la biblioteca sea
    facil de leer.
    """
    disponibles = obtener_presets_disponibles(empresa_id)
    ids_favoritos = obtener_ids_favoritos(empresa_id)

    favoritos = [p for p in disponibles if p.id in ids_favoritos]
    sistema = [p for p in disponibles if p.es_sistema and p.id not in ids_favoritos]
    personalizados = [p for p in disponibles if not p.es_sistema and p.id not in ids_favoritos]

    return {"favoritos": favoritos, "sistema": sistema, "personalizados": personalizados}


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


def obtener_preset_propio(empresa_id, preset_id):
    """Como obtener_preset, pero SOLO si es un preset personalizado de
    esta empresa (nunca de sistema, nunca de otra empresa) -- usado
    para editar/eliminar, donde un preset de sistema nunca es valido
    sin importar la empresa activa.
    """
    from app.extensions import db
    from app.models import Preset

    return (
        db.session.query(Preset)
        .filter_by(id=preset_id, empresa_id=empresa_id, es_sistema=False, activo=True)
        .first()
    )


def obtener_preset_automatico():
    from app.extensions import db
    from app.models import Preset

    return db.session.query(Preset).filter_by(slug="automatico", es_sistema=True, activo=True).first()


def crear_preset_personalizado(empresa_id, usuario_id, nombre, descripcion, categoria, parametros_entrada):
    """Crea un preset personalizado nuevo para esta empresa. Devuelve
    (preset, error). El slug se deriva del nombre + empresa para que
    quede legible en logs/depuracion, nunca se usa para autorizar nada
    (eso siempre es empresa_id + es_sistema).
    """
    from app.extensions import db
    from app.models import Preset

    nombre = (nombre or "").strip()
    if not nombre:
        return None, "El nombre del preset es obligatorio."
    if categoria and categoria not in CATEGORIAS_PRESET:
        return None, "Categoría inválida."

    parametros = normalizar_parametros(parametros_entrada)
    slug = f"personalizado-{empresa_id}-{nombre.lower().strip().replace(' ', '-')[:30]}"

    preset = Preset(
        slug=slug,
        nombre=nombre,
        descripcion=(descripcion or "").strip() or None,
        categoria=categoria or "personalizado",
        empresa_id=empresa_id,
        es_sistema=False,
        version=1,
        parametros=parametros,
        activo=True,
        creado_por=usuario_id,
    )
    db.session.add(preset)
    db.session.commit()
    return preset, None


def editar_preset_personalizado(empresa_id, preset_id, nombre, descripcion, categoria, parametros_entrada):
    """Edita un preset personalizado EXISTENTE de esta empresa.
    Devuelve (preset, error). Nunca permite editar un preset de
    sistema (ni siquiera si el llamador es el admin de Publi
    Marketing) ni uno de otra empresa -- en ambos casos el error
    explica que hacer en su lugar (duplicar).

    Cada edicion incrementa `version`: los derivados ya generados
    guardan su propio snapshot (preset_nombre/preset_version) y por lo
    tanto NUNCA cambian de aspecto retroactivamente por esto.
    """
    from app.extensions import db
    from app.models import Preset

    preset = db.session.query(Preset).filter_by(id=preset_id, activo=True).first()
    if preset is None:
        return None, "El preset no existe."
    if preset.es_sistema:
        return None, "Los presets del sistema no se pueden editar. Crea una copia personalizada primero."
    if preset.empresa_id != empresa_id:
        return None, "Este preset no pertenece a tu empresa."

    nombre = (nombre or "").strip()
    if not nombre:
        return None, "El nombre del preset es obligatorio."
    if categoria and categoria not in CATEGORIAS_PRESET:
        return None, "Categoría inválida."

    preset.nombre = nombre
    preset.descripcion = (descripcion or "").strip() or None
    preset.categoria = categoria or "personalizado"
    preset.parametros = normalizar_parametros(parametros_entrada)
    preset.version += 1
    db.session.commit()
    return preset, None


def duplicar_preset(empresa_id, usuario_id, preset_id):
    """Duplica cualquier preset accesible (de sistema o de la propia
    empresa) en un preset NUEVO y personalizado de esta empresa.
    Nunca modifica el original -- "Cálido" sigue siendo "Cálido"; el
    duplicado nace como "Cálido — copia", version 1, editable.
    Devuelve (preset_nuevo, error).
    """
    origen = obtener_preset(empresa_id, preset_id)
    if origen is None:
        return None, "El preset no está disponible para esta empresa."

    nombre_nuevo = f"{origen.nombre} — copia"
    return crear_preset_personalizado(
        empresa_id, usuario_id, nombre_nuevo, origen.descripcion, origen.categoria, dict(origen.parametros or {})
    )


def eliminar_preset_personalizado(empresa_id, preset_id):
    """Soft delete (activo=False) de un preset personalizado propio.
    Nunca borra la fila ni toca los derivados que ya lo usaron: esos
    guardan su propio snapshot (preset_nombre/preset_version) y su
    preset_id puede seguir apuntando aqui sin que nada se rompa (el
    preset simplemente deja de ofrecerse para NUEVOS procesamientos).
    Devuelve (ok, error).
    """
    from app.extensions import db

    preset = obtener_preset_propio(empresa_id, preset_id)
    if preset is None:
        return False, "El preset no existe, no es tuyo, o es un preset del sistema (no se puede eliminar)."

    preset.activo = False
    db.session.commit()
    return True, None


# --- Favoritos (Paso 11) -----------------------------------------------------

def obtener_ids_favoritos(empresa_id):
    from app.extensions import db
    from app.models import PresetFavorito

    filas = db.session.query(PresetFavorito.preset_id).filter_by(empresa_id=empresa_id).all()
    return {preset_id for (preset_id,) in filas}


def es_favorito(empresa_id, preset_id):
    from app.extensions import db
    from app.models import PresetFavorito

    return (
        db.session.query(PresetFavorito)
        .filter_by(empresa_id=empresa_id, preset_id=preset_id)
        .first()
        is not None
    )


def alternar_favorito(empresa_id, preset_id):
    """Marca/desmarca un preset como favorito para esta empresa.
    Devuelve el nuevo estado (True = ahora es favorito).
    """
    from app.extensions import db
    from app.models import PresetFavorito

    existente = db.session.query(PresetFavorito).filter_by(empresa_id=empresa_id, preset_id=preset_id).first()
    if existente is not None:
        db.session.delete(existente)
        db.session.commit()
        return False

    db.session.add(PresetFavorito(empresa_id=empresa_id, preset_id=preset_id))
    db.session.commit()
    return True
