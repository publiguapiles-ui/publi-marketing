from datetime import datetime, timezone

from app.extensions import db

ESTADOS_PROYECTO = ["activo", "archivado"]


class ProyectoFotografico(db.Model):
    """Un proyecto fotografico agrupa las fotografias de una sesion/
    encargo dentro de una empresa (ej. "Sesion Agosto"). Es el nivel
    intermedio entre la empresa y las fotografias individuales.
    """

    __tablename__ = "proyectos_fotograficos"

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresas.id"), nullable=False, index=True)

    nombre = db.Column(db.String(255), nullable=False)
    descripcion = db.Column(db.Text)
    estado = db.Column(db.String(20), nullable=False, default="activo")

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
        return f"<ProyectoFotografico {self.nombre} empresa={self.empresa_id}>"
