from datetime import datetime, timezone

from app.extensions import db

TIPOS_LOGO = ["principal", "secundario", "blanco", "oscuro", "marca_agua"]


class Logo(db.Model):
    """Un archivo de logo perteneciente a una empresa.

    El archivo real vive en Supabase Storage (bucket privado `logos`);
    aqui solo se guarda la referencia y los metadatos, nunca el binario.

    `es_principal` y `es_marca_agua` son banderas independientes del
    `tipo`: como maximo un logo activo por empresa puede tener cada una
    en True (lo garantiza app/services/marca.py, nunca se confia en
    esto a nivel de UI/navegador).
    """

    __tablename__ = "logos"

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresas.id"), nullable=False, index=True)

    tipo = db.Column(db.String(20), nullable=False)
    nombre_archivo_original = db.Column(db.String(255), nullable=False)
    ruta_storage = db.Column(db.String(500), nullable=False)
    tipo_mime = db.Column(db.String(100), nullable=False)
    tamano_bytes = db.Column(db.Integer, nullable=False)

    es_principal = db.Column(db.Boolean, default=False, nullable=False)
    es_marca_agua = db.Column(db.Boolean, default=False, nullable=False)
    # Soft-delete deliberado: nunca se destruye el archivo original ni
    # el registro solo porque el usuario lo "elimino" de la biblioteca.
    activo = db.Column(db.Boolean, default=True, nullable=False)

    subido_por = db.Column(db.String(36), db.ForeignKey("usuarios.id"), nullable=True)

    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    actualizado_en = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    empresa = db.relationship("Empresa")

    def __repr__(self):
        return f"<Logo {self.tipo} empresa={self.empresa_id}>"
