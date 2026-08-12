from datetime import datetime, timezone

from app.extensions import db

# Slugs de los 11 presets iniciales (Paso 10). El motor de correccion
# (app/services/procesamiento.py) es el mismo para todos -- un preset
# es solo un conjunto de objetivos que sesga esos calculos, nunca un
# filtro fijo ni un segundo motor.
SLUGS_PRESETS_SISTEMA = [
    "automatico",
    "natural",
    "calido",
    "frio",
    "comercial",
    "vibrante",
    "cinematico",
    "evento",
    "producto",
    "interior",
    "exterior",
]


class Preset(db.Model):
    """Un preset de correccion fotografica.

    Los presets "de sistema" (es_sistema=True, empresa_id=None) vienen
    sembrados por migracion y son de solo lectura desde la aplicacion.
    `empresa_id` queda preparado desde ya para presets personalizados
    por empresa (crear/editar/duplicar/eliminar) -- esa gestion no se
    construye en este paso, pero el modelo ya la soporta sin necesitar
    otro cambio de esquema despues.

    `parametros` son los objetivos que sesga el motor de
    app/services/procesamiento.py (ver `mejorar_fotografia`): nunca se
    interpretan como un filtro que se "aplica encima", siempre entran
    como sesgo de los mismos calculos adaptativos existentes.
    """

    __tablename__ = "presets"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(40), nullable=False, index=True)
    nombre = db.Column(db.String(60), nullable=False)
    descripcion = db.Column(db.String(255))

    # None = preset de sistema, disponible para todas las empresas.
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresas.id"), nullable=True, index=True)
    es_sistema = db.Column(db.Boolean, default=False, nullable=False)

    parametros = db.Column(db.JSON, nullable=False, default=dict)

    activo = db.Column(db.Boolean, default=True, nullable=False)
    creado_por = db.Column(db.String(36), db.ForeignKey("usuarios.id"), nullable=True)

    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    actualizado_en = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    empresa = db.relationship("Empresa")

    def __repr__(self):
        return f"<Preset {self.slug} empresa={self.empresa_id}>"
