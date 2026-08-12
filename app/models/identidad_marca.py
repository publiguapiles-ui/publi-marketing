from datetime import datetime, timezone

from app.extensions import db


class IdentidadMarca(db.Model):
    """Identidad de marca de una empresa (1:1). Los colores son opcionales
    y se validan como HEX (#RRGGBB) antes de guardarse.
    """

    __tablename__ = "identidad_marca"

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresas.id"), unique=True, nullable=False)

    nombre_comercial = db.Column(db.String(255))
    color_principal = db.Column(db.String(7))
    color_secundario = db.Column(db.String(7))
    color_texto = db.Column(db.String(7))
    color_fondo = db.Column(db.String(7))

    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    actualizado_en = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    empresa = db.relationship("Empresa")

    def tiene_colores(self):
        return any([self.color_principal, self.color_secundario, self.color_texto, self.color_fondo])
