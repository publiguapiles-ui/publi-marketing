from datetime import datetime, timezone

from app.extensions import db

ESTADOS_FOTOGRAFIA = ["original", "procesando", "procesada", "error"]


class Fotografia(db.Model):
    """Una fotografia original subida a un proyecto.

    Regla fundamental del modulo: el archivo original referenciado por
    `ruta_storage` NUNCA se modifica ni se sobreescribe. Los pasos
    futuros de procesamiento (Paso 7 en adelante) trabajaran sobre
    derivados nuevos, nunca sobre este archivo.
    """

    __tablename__ = "fotografias"

    id = db.Column(db.Integer, primary_key=True)
    # Denormalizado a proposito (igual que Logo.empresa_id): permite
    # validar aislamiento por empresa con una sola condicion, sin
    # depender de un JOIN a traves de proyectos_fotograficos.
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresas.id"), nullable=False, index=True)
    proyecto_id = db.Column(
        db.Integer, db.ForeignKey("proyectos_fotograficos.id"), nullable=False, index=True
    )

    nombre_archivo_original = db.Column(db.String(255), nullable=False)
    ruta_storage = db.Column(db.String(500), nullable=False)
    tipo_mime = db.Column(db.String(100), nullable=False)
    tamano_bytes = db.Column(db.Integer, nullable=False)

    estado = db.Column(db.String(20), nullable=False, default="original")
    # Soft-delete deliberado, igual que Logo: nunca se destruye el
    # archivo original ni el registro solo porque se "elimino" de la
    # galeria (deja la puerta abierta a una papelera futura).
    activo = db.Column(db.Boolean, default=True, nullable=False)

    subido_por = db.Column(db.String(36), db.ForeignKey("usuarios.id"), nullable=True)

    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    actualizado_en = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Preparado para metadatos futuros (no se completan en este paso,
    # ver Paso 7): dimensiones, orientacion, datos EXIF de camara y,
    # opcionalmente, ubicacion.
    ancho_px = db.Column(db.Integer)
    alto_px = db.Column(db.Integer)
    orientacion = db.Column(db.Integer)
    fecha_captura = db.Column(db.DateTime)
    camara = db.Column(db.String(255))
    lente = db.Column(db.String(255))
    iso = db.Column(db.Integer)
    apertura = db.Column(db.String(20))
    velocidad_obturacion = db.Column(db.String(20))
    latitud = db.Column(db.Float)
    longitud = db.Column(db.Float)

    empresa = db.relationship("Empresa")
    proyecto = db.relationship("ProyectoFotografico")

    def __repr__(self):
        return f"<Fotografia {self.nombre_archivo_original} proyecto={self.proyecto_id}>"
