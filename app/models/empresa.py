from datetime import datetime, timezone

from app.extensions import db


class Empresa(db.Model):
    __tablename__ = "empresas"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), unique=True, nullable=False)
    activo = db.Column(db.Boolean, default=True, nullable=False)
    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    actualizado_en = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Preparado para el Paso 5 (identidad de marca): logo_id, colores,
    # telefono, correo, direccion, redes sociales, etc. se agregaran
    # como columnas/relaciones nuevas sin romper esta tabla base.

    def __repr__(self):
        return f"<Empresa {self.nombre}>"
