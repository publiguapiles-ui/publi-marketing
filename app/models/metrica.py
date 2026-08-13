from datetime import datetime, timezone

from app.extensions import db

# Motor universal de metricas (Paso 1 de Datos de Meta). Deliberadamente
# NO hay columnas fijas como "impressions" o "ctr": cualquier metrica
# que una fuente entregue (o que Publi Marketing calcule) se guarda
# como una fila de `Metrica`, identificada por `metrica_nombre` contra
# el catalogo (`CatalogoMetrica`). Agregar una metrica nueva nunca
# requiere una migracion.

TIPOS_VALOR_METRICA = ["numero", "moneda", "porcentaje", "ratio", "conteo"]

# La distincion mas importante del punto 6 del enunciado: una metrica
# "nativa" es un dato que la fuente (Meta) entrego tal cual; una
# "calculada" es un dato que PUBLI MARKETING deriva de una o mas
# metricas nativas con una formula propia (ver
# CatalogoMetrica.formula) -- nunca se confunden entre si, ni siquiera
# cuando Meta tambien devuelve su propia version del mismo numero (ej.
# Meta incluye "ctr" en sus respuestas de insights, pero Publi
# Marketing lo recalcula igual para tener una formula consistente y
# propia, reutilizable con futuras fuentes que definan el CTR distinto).
ORIGENES_METRICA = ["nativa", "calculada"]


class CatalogoMetrica(db.Model):
    """Catalogo de metricas conocidas por el sistema (Paso 1, punto 7).

    Se siembra de forma idempotente (ver
    app/services/metricas.py::sembrar_catalogo_metricas), mismo patron
    que app/services/presets.py::sembrar_presets_sistema -- nunca se
    inventan metricas que Meta no entregue realmente; cada entrada
    sembrada aqui esta documentada en el informe del Paso 1 con su
    origen verificado.
    """

    __tablename__ = "catalogo_metricas"

    id = db.Column(db.Integer, primary_key=True)
    clave = db.Column(db.String(60), nullable=False, unique=True, index=True)  # "spend", "ctr"...
    nombre_mostrado = db.Column(db.String(120), nullable=False)  # "Inversión"

    fuente = db.Column(db.String(30), nullable=False, default="meta", index=True)
    origen = db.Column(db.String(20), nullable=False)  # uno de ORIGENES_METRICA
    tipo_valor = db.Column(db.String(20), nullable=False)  # uno de TIPOS_VALOR_METRICA
    unidad = db.Column(db.String(20), nullable=True)  # "USD", "%", None si no aplica

    descripcion = db.Column(db.String(500))
    formula = db.Column(db.String(255), nullable=True)  # solo si origen="calculada", ej "spend / clicks"

    niveles_aplicables = db.Column(db.JSON, nullable=False, default=list)  # ej ["campana","conjunto_anuncios","anuncio"]
    categoria = db.Column(db.String(40))  # "rendimiento", "costo", "alcance", "conversion"...

    disponible = db.Column(db.Boolean, default=True, nullable=False)

    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    actualizado_en = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self):
        return f"<CatalogoMetrica {self.clave} ({self.origen})>"


class Metrica(db.Model):
    """Un valor de metrica para una entidad, fecha y desglose
    concretos. La fila EAV central del motor universal de metricas.

    `entidad_id` es nullable a proposito: permite guardar metricas a
    nivel de conexion/cuenta (agregadas) que no pertenecen a una sola
    campana/anuncio. `entidad_tipo` esta denormalizado desde
    EntidadPublicitaria.tipo para poder filtrar/agregar por nivel sin
    JOIN (ej. "todas las metricas de nivel campana de esta empresa").
    """

    __tablename__ = "metricas"
    __table_args__ = (
        db.Index("ix_metricas_empresa_entidad_metrica_fecha", "empresa_id", "entidad_id", "metrica_nombre", "fecha"),
    )

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresas.id"), nullable=False, index=True)
    entidad_id = db.Column(db.Integer, db.ForeignKey("entidades_publicitarias.id", ondelete="CASCADE"), nullable=True, index=True)
    entidad_tipo = db.Column(db.String(30), nullable=True, index=True)

    metrica_nombre = db.Column(db.String(60), nullable=False, index=True)  # clave de CatalogoMetrica
    valor = db.Column(db.Float, nullable=True)
    valor_texto = db.Column(db.String(255), nullable=True)  # para datos no numericos si algun dia hace falta
    tipo_valor = db.Column(db.String(20), nullable=False)  # snapshot de CatalogoMetrica.tipo_valor al momento de guardar
    origen = db.Column(db.String(20), nullable=False)  # snapshot de CatalogoMetrica.origen -- nunca ambiguo por fila

    fuente = db.Column(db.String(30), nullable=False, default="meta")
    fecha = db.Column(db.Date, nullable=False, index=True)
    fecha_fin = db.Column(db.Date, nullable=True)  # None = dato diario; con valor = metrica de rango (ej. "lifetime")

    # Dimensiones/breakdowns (Paso 1, punto 8): dict libre, ej
    # {"platform": "instagram", "age": "25-34"} -- que combinaciones
    # son validas lo decide el codigo que llama a la API de Meta
    # (services/meta/insights_service.py, Paso 2), no el modelo.
    breakdown = db.Column(db.JSON, nullable=True)

    moneda = db.Column(db.String(10), nullable=True)  # solo si tipo_valor="moneda"
    metadata_extra = db.Column(db.JSON, nullable=True)  # info adicional sin forzar una columna nueva

    sincronizacion_id = db.Column(db.Integer, db.ForeignKey("sincronizaciones_meta.id", ondelete="SET NULL"), nullable=True)

    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    empresa = db.relationship("Empresa")
    entidad = db.relationship("EntidadPublicitaria")
    sincronizacion = db.relationship("SincronizacionMeta")

    def __repr__(self):
        return f"<Metrica {self.metrica_nombre}={self.valor} entidad={self.entidad_id} fecha={self.fecha}>"
