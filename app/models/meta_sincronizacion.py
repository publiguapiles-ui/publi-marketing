from datetime import datetime, timezone

from app.extensions import db

TIPOS_SINCRONIZACION = ["inicial", "incremental"]
ESTADOS_SINCRONIZACION = ["pendiente", "en_progreso", "completada", "error"]
ESTADOS_SINCRONIZACION_TERMINALES = ["completada", "error"]


class SincronizacionMeta(db.Model):
    """Un intento de sincronizacion (entidades y/o metricas) contra
    Meta para una conexion (Paso 1: arquitectura solamente -- ver
    informe, no hay todavia un job real que dispare esto en segundo
    plano).

    Deja preparados los campos que una cola real necesitaria despues
    (intentos, error_mensaje, periodo consultado) sin construir esa
    cola todavia -- mismo criterio que ya se aplico a
    app/services/tareas.py en Photo Studio.
    """

    __tablename__ = "sincronizaciones_meta"

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresas.id"), nullable=False, index=True)
    conexion_id = db.Column(db.Integer, db.ForeignKey("meta_conexiones.id", ondelete="CASCADE"), nullable=False, index=True)

    tipo = db.Column(db.String(20), nullable=False)  # uno de TIPOS_SINCRONIZACION
    entidad_tipo = db.Column(db.String(30), nullable=True)  # None = todo; o uno de TIPOS_ENTIDAD_META / "metricas"
    estado = db.Column(db.String(20), nullable=False, default="pendiente")

    fecha_inicio_periodo = db.Column(db.Date, nullable=True)
    fecha_fin_periodo = db.Column(db.Date, nullable=True)

    registros_procesados = db.Column(db.Integer, default=0, nullable=False)
    intentos = db.Column(db.Integer, default=0, nullable=False)
    error_mensaje = db.Column(db.String(500), nullable=True)

    iniciada_en = db.Column(db.DateTime, nullable=True)
    finalizada_en = db.Column(db.DateTime, nullable=True)
    creado_por = db.Column(db.String(36), db.ForeignKey("usuarios.id"), nullable=True)

    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    empresa = db.relationship("Empresa")
    conexion = db.relationship("MetaConexion")

    def __repr__(self):
        return f"<SincronizacionMeta {self.tipo} estado={self.estado} empresa={self.empresa_id}>"
