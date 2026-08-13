"""Motor universal de metricas (Paso 1 de Datos de Meta).

Deliberadamente FUERA de app/services/meta/: este motor no sabe nada
de Meta en si -- guarda y consulta filas de `Metrica` identificadas
por una clave de `CatalogoMetrica`, sin importar que fuente las
origino. Es la pieza que, segun el punto 12 del enunciado, debe poder
reutilizarse tal cual cuando exista una segunda fuente (Google Ads,
TikTok Ads): esas fuentes solo necesitan su propio "conector" (un
services/google_ads/ equivalente a services/meta/) que llame a
registrar_metrica() con fuente="google_ads".

Ninguna funcion aqui valida permisos de usuario -- las rutas deben
llamar siempre con una empresa_id ya validada, mismo patron que el
resto del proyecto.
"""

# --- Catalogo inicial ---------------------------------------------------------
#
# Solo se siembran metricas verificadas como campos reales y
# documentados de la Graph API de Meta (Marketing API > Insights,
# https://developers.facebook.com/docs/marketing-api/insights):
#
#   NATIVAS  -- Meta las devuelve directamente en /insights: spend,
#               impressions, reach, clicks, frequency.
#   CALCULADAS -- Publi Marketing las deriva con una formula propia,
#               EN VEZ DE usar el ctr/cpc/cpm que Meta tambien incluye
#               en su respuesta: asi el numero es consistente sin
#               importar la fuente (Meta hoy, Google Ads/TikTok Ads
#               despues) y no depende del redondeo interno de cada
#               plataforma.
#
# Deliberadamente NO se siembran todavia: ROAS, costo por resultado,
# tasa de conversion -- requieren campos de "actions"/"action_values"
# de Meta que este Paso 1 no integra aun (ver informe, seccion
# Pendientes). Agregarlas despues es una fila nueva aqui, nunca una
# migracion.

CATALOGO_INICIAL = [
    {
        "clave": "spend", "nombre_mostrado": "Inversión", "fuente": "meta", "origen": "nativa",
        "tipo_valor": "moneda", "unidad": None,
        "descripcion": "Monto total gastado en el período, tal como lo reporta Meta.",
        "formula": None,
        "niveles_aplicables": ["cuenta_publicitaria", "campana", "conjunto_anuncios", "anuncio"],
        "categoria": "costo",
    },
    {
        "clave": "impressions", "nombre_mostrado": "Impresiones", "fuente": "meta", "origen": "nativa",
        "tipo_valor": "conteo", "unidad": None,
        "descripcion": "Número de veces que se mostró un anuncio.",
        "formula": None,
        "niveles_aplicables": ["cuenta_publicitaria", "campana", "conjunto_anuncios", "anuncio"],
        "categoria": "alcance",
    },
    {
        "clave": "reach", "nombre_mostrado": "Alcance", "fuente": "meta", "origen": "nativa",
        "tipo_valor": "conteo", "unidad": None,
        "descripcion": "Número de personas únicas que vieron un anuncio al menos una vez.",
        "formula": None,
        "niveles_aplicables": ["cuenta_publicitaria", "campana", "conjunto_anuncios", "anuncio"],
        "categoria": "alcance",
    },
    {
        "clave": "clicks", "nombre_mostrado": "Clics", "fuente": "meta", "origen": "nativa",
        "tipo_valor": "conteo", "unidad": None,
        "descripcion": "Número total de clics en un anuncio (todos los tipos de clic).",
        "formula": None,
        "niveles_aplicables": ["cuenta_publicitaria", "campana", "conjunto_anuncios", "anuncio"],
        "categoria": "rendimiento",
    },
    {
        "clave": "frequency", "nombre_mostrado": "Frecuencia", "fuente": "meta", "origen": "nativa",
        "tipo_valor": "numero", "unidad": None,
        "descripcion": "Promedio de veces que cada persona alcanzada vio el anuncio.",
        "formula": None,
        "niveles_aplicables": ["cuenta_publicitaria", "campana", "conjunto_anuncios", "anuncio"],
        "categoria": "alcance",
    },
    {
        "clave": "ctr", "nombre_mostrado": "CTR", "fuente": "meta", "origen": "calculada",
        "tipo_valor": "porcentaje", "unidad": "%",
        "descripcion": "Porcentaje de impresiones que resultaron en un clic.",
        "formula": "clicks / impressions * 100",
        "niveles_aplicables": ["cuenta_publicitaria", "campana", "conjunto_anuncios", "anuncio"],
        "categoria": "rendimiento",
    },
    {
        "clave": "cpc", "nombre_mostrado": "CPC", "fuente": "meta", "origen": "calculada",
        "tipo_valor": "moneda", "unidad": None,
        "descripcion": "Costo promedio por clic.",
        "formula": "spend / clicks",
        "niveles_aplicables": ["cuenta_publicitaria", "campana", "conjunto_anuncios", "anuncio"],
        "categoria": "costo",
    },
    {
        "clave": "cpm", "nombre_mostrado": "CPM", "fuente": "meta", "origen": "calculada",
        "tipo_valor": "moneda", "unidad": None,
        "descripcion": "Costo promedio por cada mil impresiones.",
        "formula": "spend / impressions * 1000",
        "niveles_aplicables": ["cuenta_publicitaria", "campana", "conjunto_anuncios", "anuncio"],
        "categoria": "costo",
    },
]

# Formulas de las metricas calculadas del catalogo inicial, como
# funciones puras -- separadas del catalogo (que es solo metadata)
# para que registrar_metricas_con_calculadas() pueda invocarlas sin
# tener que interpretar la cadena `formula` (que es solo documentacion
# legible para humanos, nunca se evalua como codigo).
_CALCULADORAS = {
    "ctr": lambda v: (v["clicks"] / v["impressions"] * 100) if v.get("impressions") else None,
    "cpc": lambda v: (v["spend"] / v["clicks"]) if v.get("clicks") else None,
    "cpm": lambda v: (v["spend"] / v["impressions"] * 1000) if v.get("impressions") else None,
}


def sembrar_catalogo_metricas():
    """Crea las entradas del catalogo inicial si todavia no existen --
    idempotente, mismo patron que
    app/services/presets.py::sembrar_presets_sistema. Nunca sobrescribe
    `formula`/`tipo_valor` de una entrada ya sembrada (evita que un
    reinicio de la app pise una correccion manual hecha directamente
    en la base de datos)."""
    from app.extensions import db
    from app.models import CatalogoMetrica

    existentes = {clave for (clave,) in db.session.query(CatalogoMetrica.clave).all()}
    faltantes = [m for m in CATALOGO_INICIAL if m["clave"] not in existentes]
    if not faltantes:
        return

    for datos in faltantes:
        db.session.add(CatalogoMetrica(**datos))
    db.session.commit()


def obtener_catalogo(fuente=None, categoria=None, solo_disponibles=True):
    from app.extensions import db
    from app.models import CatalogoMetrica

    consulta = db.session.query(CatalogoMetrica)
    if solo_disponibles:
        consulta = consulta.filter_by(disponible=True)
    if fuente:
        consulta = consulta.filter_by(fuente=fuente)
    if categoria:
        consulta = consulta.filter_by(categoria=categoria)
    return consulta.order_by(CatalogoMetrica.categoria, CatalogoMetrica.clave).all()


def obtener_metrica_catalogo(clave):
    from app.extensions import db
    from app.models import CatalogoMetrica

    return db.session.query(CatalogoMetrica).filter_by(clave=clave).first()


def registrar_metrica(empresa_id, metrica_nombre, valor, fecha, entidad_id=None, entidad_tipo=None,
                       fuente="meta", breakdown=None, fecha_fin=None, moneda=None,
                       metadata_extra=None, sincronizacion_id=None):
    """Guarda UNA fila de metrica. `metrica_nombre` debe existir en el
    catalogo -- de ahi se toman `tipo_valor`/`origen` como snapshot
    (para que una fila ya guardada nunca cambie de significado si el
    catalogo se edita despues, mismo principio que
    FotografiaDerivada.preset_version en Photo Studio).
    """
    from app.extensions import db
    from app.models import Metrica

    catalogo = obtener_metrica_catalogo(metrica_nombre)
    if catalogo is None:
        raise ValueError(f"'{metrica_nombre}' no está en el catálogo de métricas.")

    fila = Metrica(
        empresa_id=empresa_id,
        entidad_id=entidad_id,
        entidad_tipo=entidad_tipo,
        metrica_nombre=metrica_nombre,
        valor=valor,
        tipo_valor=catalogo.tipo_valor,
        origen=catalogo.origen,
        fuente=fuente,
        fecha=fecha,
        fecha_fin=fecha_fin,
        breakdown=breakdown,
        moneda=moneda,
        metadata_extra=metadata_extra,
        sincronizacion_id=sincronizacion_id,
    )
    db.session.add(fila)
    db.session.commit()
    return fila


def registrar_metricas_nativas_y_calculadas(empresa_id, entidad_id, entidad_tipo, valores_nativos, fecha, **kwargs):
    """Dado un dict de valores NATIVOS ya obtenidos de la fuente (ej.
    {"spend": 12.5, "impressions": 1000, "clicks": 15}), guarda esas
    filas nativas y ademas calcula y guarda las metricas derivadas del
    catalogo (ctr/cpc/cpm) usando _CALCULADORAS -- nunca usa un valor
    de ctr/cpc/cpm que la fuente haya entregado directamente, para que
    "calculada" signifique siempre "calculada por Publi Marketing".
    """
    guardadas = []
    for clave, valor in valores_nativos.items():
        if valor is None:
            continue
        guardadas.append(registrar_metrica(empresa_id, clave, float(valor), fecha, entidad_id=entidad_id, entidad_tipo=entidad_tipo, **kwargs))

    for clave, calculadora in _CALCULADORAS.items():
        try:
            derivado = calculadora(valores_nativos)
        except (KeyError, ZeroDivisionError, TypeError):
            derivado = None
        if derivado is not None:
            guardadas.append(registrar_metrica(empresa_id, clave, derivado, fecha, entidad_id=entidad_id, entidad_tipo=entidad_tipo, **kwargs))

    return guardadas


def consultar_metricas(empresa_id, entidad_id=None, entidad_tipo=None, metrica_nombre=None, fecha_desde=None, fecha_hasta=None):
    """Lectura de metricas ya guardadas -- SIEMPRE filtrada por
    empresa_id, nunca opcional (aislamiento multi-tenant)."""
    from app.extensions import db
    from app.models import Metrica

    consulta = db.session.query(Metrica).filter_by(empresa_id=empresa_id)
    if entidad_id is not None:
        consulta = consulta.filter_by(entidad_id=entidad_id)
    if entidad_tipo is not None:
        consulta = consulta.filter_by(entidad_tipo=entidad_tipo)
    if metrica_nombre is not None:
        consulta = consulta.filter_by(metrica_nombre=metrica_nombre)
    if fecha_desde is not None:
        consulta = consulta.filter(Metrica.fecha >= fecha_desde)
    if fecha_hasta is not None:
        consulta = consulta.filter(Metrica.fecha <= fecha_hasta)
    return consulta.order_by(Metrica.fecha.desc()).all()
