from datetime import datetime, timezone

from app.extensions import db

# Paso 2 (Centro de Datos de Marketing): tipos de fuente que el sistema
# reconoce, sin importar si estan conectadas todavia. Meta es la unica
# realmente implementada -- las demas existen aqui como concepto
# preparado (punto 11: "ConectorFuente"), nunca como una conexion
# ficticia. Agregar un tipo nuevo a esta lista NO conecta nada por si
# solo.
TIPOS_FUENTE_DATOS = ["meta", "crm", "whatsapp", "ventas"]

ETIQUETAS_FUENTE_DATOS = {
    "meta": "Meta",
    "crm": "CRM",
    "whatsapp": "WhatsApp",
    "ventas": "Ventas",
}

ESTADOS_FUENTE_DATOS = ["no_conectada", "conectada", "error"]


class FuenteDatos(db.Model):
    """Registro de una fuente de datos de marketing conectada para una
    empresa (Paso 2). Meta NO guarda una fila aqui -- su estado ya vive
    por completo en MetaConexion (estado/ultima_sincronizacion_en/
    ultimo_error/creado_en), y app/services/centro_datos.py lo expone
    con esta misma forma en tiempo de lectura en vez de duplicarlo
    (duplicar ese estado ya causo bugs de desincronizacion en pasos
    anteriores de este proyecto). Esta tabla existe para las fuentes
    que SI necesitan su propio registro persistente el dia que se
    conecten de verdad (CRM/WhatsApp/Ventas) -- hoy no tiene ninguna
    fila real, a proposito (punto 2: "no crear conexiones falsas")."""

    __tablename__ = "fuentes_datos"

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresas.id"), nullable=False, index=True)

    tipo = db.Column(db.String(30), nullable=False)  # uno de TIPOS_FUENTE_DATOS
    estado = db.Column(db.String(20), nullable=False, default="no_conectada")  # uno de ESTADOS_FUENTE_DATOS

    configuracion = db.Column(db.JSON, nullable=True)
    ultimo_error = db.Column(db.String(500), nullable=True)
    ultima_sincronizacion_en = db.Column(db.DateTime, nullable=True)
    metadata_extra = db.Column(db.JSON, nullable=True)

    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    actualizado_en = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    empresa = db.relationship("Empresa")

    __table_args__ = (db.UniqueConstraint("empresa_id", "tipo", name="uq_fuente_datos_empresa_tipo"),)

    def __repr__(self):
        return f"<FuenteDatos {self.tipo} empresa={self.empresa_id} estado={self.estado}>"
