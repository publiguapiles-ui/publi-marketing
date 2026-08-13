from datetime import datetime, timezone

from app.extensions import db

# Paso 1: solo Meta. `fuente` ya existe como columna (no un Enum
# rigido) precisamente para que agregar Google Ads/TikTok Ads despues
# sea un valor nuevo en esta lista, nunca una tabla ni una migracion
# estructural nueva (ver punto 12 del enunciado).
FUENTES_ENTIDAD = ["meta"]

# Los 7 tipos de entidad que Meta expone y que este paso debe poder
# guardar. Una sola tabla polimorfica (en vez de 7 tablas) porque la
# jerarquia y los campos "especificos" de cada tipo son exactamente lo
# que MAS cambia entre plataformas publicitarias -- ahi es donde mas
# vale la flexibilidad de un `atributos` JSON en vez de columnas fijas.
TIPOS_ENTIDAD_META = [
    "cuenta_publicitaria",
    "pagina",
    "cuenta_instagram",
    "campana",
    "conjunto_anuncios",
    "anuncio",
    "creativo",
]


class EntidadPublicitaria(db.Model):
    """Cualquier entidad de la jerarquia publicitaria de una fuente
    externa (Meta en el Paso 1): cuenta publicitaria, pagina, cuenta de
    Instagram, campana, conjunto de anuncios, anuncio o creativo.

    Deliberadamente UNA sola tabla polimorfica (`tipo` +
    `entidad_padre_id` autorreferencial) en vez de 7 tablas -- evita
    que agregar un tipo de entidad nuevo (ej. "reel", o el equivalente
    de Google Ads) requiera una migracion estructural. Lo que varia
    entre tipos (moneda de una cuenta publicitaria, objetivo de una
    campana, url de un creativo...) vive en `atributos` (JSON), no en
    columnas -- mismo patron que `Preset.parametros`.

    `empresa_id` esta denormalizado (no solo via `conexion_id`) para
    poder validar aislamiento multiempresa con un solo filtro, igual
    que en Fotografia/FotografiaDerivada.
    """

    __tablename__ = "entidades_publicitarias"
    __table_args__ = (
        db.UniqueConstraint("fuente", "conexion_id", "id_externo", name="uq_entidad_publicitaria_fuente_conexion_externo"),
    )

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresas.id"), nullable=False, index=True)
    conexion_id = db.Column(db.Integer, db.ForeignKey("meta_conexiones.id", ondelete="SET NULL"), nullable=True, index=True)

    fuente = db.Column(db.String(30), nullable=False, default="meta", index=True)
    tipo = db.Column(db.String(30), nullable=False, index=True)
    entidad_padre_id = db.Column(db.Integer, db.ForeignKey("entidades_publicitarias.id", ondelete="SET NULL"), nullable=True, index=True)

    id_externo = db.Column(db.String(64), nullable=False)  # ej "act_123456789", "120211234567890"
    nombre = db.Column(db.String(255))
    estado = db.Column(db.String(30))  # el estado tal como lo reporta la fuente (ACTIVE, PAUSED, DELETED...)

    # Campos especificos del tipo. Ejemplos (no exhaustivo, ver informe):
    #   cuenta_publicitaria: {"moneda": "USD", "zona_horaria": "America/Costa_Rica"}
    #   campana: {"objetivo": "OUTCOME_TRAFFIC", "presupuesto_diario": 5000}
    #   creativo: {"url_imagen": "...", "cuerpo": "..."}
    atributos = db.Column(db.JSON, nullable=False, default=dict)

    activo = db.Column(db.Boolean, default=True, nullable=False)

    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    actualizado_en = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    sincronizado_en = db.Column(db.DateTime, nullable=True)  # ultima vez que se confirmo contra la fuente

    empresa = db.relationship("Empresa")
    conexion = db.relationship("MetaConexion")
    entidad_padre = db.relationship("EntidadPublicitaria", remote_side=[id])

    def __repr__(self):
        return f"<EntidadPublicitaria {self.tipo} {self.id_externo} empresa={self.empresa_id}>"
