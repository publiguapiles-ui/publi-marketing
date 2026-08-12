from datetime import datetime, timezone

from app.extensions import db

TIPOS_DERIVADO = ["mejora_automatica"]  # mas tipos se agregaran en pasos futuros (formatos, etc.)
ESTADOS_DERIVADO = ["pendiente", "procesando", "completada", "error"]


class FotografiaDerivada(db.Model):
    """Version derivada de una fotografia original (nunca la reemplaza).

    Puede existir mas de un derivado por fotografia y tipo (version 1,
    2, 3...) -- nunca se sobreescribe uno existente en silencio. El
    campo `estado` es del PROCESO de este derivado, no de la
    fotografia original (que permanece "original" para siempre).
    """

    __tablename__ = "fotografias_derivadas"

    id = db.Column(db.Integer, primary_key=True)
    # Denormalizado (mismo patron que Fotografia.empresa_id): permite
    # validar aislamiento por empresa sin JOIN.
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresas.id"), nullable=False, index=True)
    fotografia_id = db.Column(db.Integer, db.ForeignKey("fotografias.id"), nullable=False, index=True)

    tipo = db.Column(db.String(30), nullable=False, default="mejora_automatica")
    version = db.Column(db.Integer, nullable=False, default=1)
    estado = db.Column(db.String(20), nullable=False, default="pendiente")
    error_mensaje = db.Column(db.String(500))

    ruta_storage = db.Column(db.String(500))
    tipo_mime = db.Column(db.String(100))
    tamano_bytes = db.Column(db.Integer)

    # Resultado del analisis/clasificacion (ver app/services/procesamiento.py).
    # Nunca se guarda aqui informacion biometrica ni de identidad: solo
    # cuantos rostros se detectaron y si la mascara de proteccion se aplico.
    categoria_detectada = db.Column(db.String(30))
    confianza_categoria = db.Column(db.Float)
    rostros_detectados = db.Column(db.Integer, default=0)
    rostros_protegidos = db.Column(db.Boolean, default=False)
    correcciones_aplicadas = db.Column(db.String(255))  # lista separada por comas
    duracion_segundos = db.Column(db.Float)

    creado_por = db.Column(db.String(36), db.ForeignKey("usuarios.id"), nullable=True)

    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    actualizado_en = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    fotografia = db.relationship("Fotografia")
    empresa = db.relationship("Empresa")

    def __repr__(self):
        return f"<FotografiaDerivada {self.tipo} v{self.version} foto={self.fotografia_id} estado={self.estado}>"
