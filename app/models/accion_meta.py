from datetime import datetime, timezone

from app.extensions import db

# Paso 12: flujo obligatorio ANALIZAR -> PROPONER -> MOSTRAR CAMBIO ->
# CONFIRMAR -> EJECUTAR -> VERIFICAR. Una accion NUNCA se ejecuta
# automaticamente -- pasar de "pendiente_de_aprobacion" a "aprobada"
# requiere una decision humana explicita, y de "aprobada" a
# "ejecutando" requiere ademas una confirmacion explicita separada
# (doble confirmacion, ver acciones.py::ejecutar_accion).
ESTADOS_ACCION_META = [
    "borrador",
    "pendiente_de_aprobacion",
    "aprobada",
    "ejecutando",
    "ejecutada",
    "error",
    "rechazada",
    "cancelada",
]

# Tipos de accion soportados (Paso 12, punto 2) -- combinados con
# `entidad.tipo` (campana/conjunto_anuncios/anuncio, ver
# EntidadPublicitaria) para saber exactamente que se pausa/activa. Solo
# se implementan acciones seguras y ya soportadas por la integracion
# actual -- nunca creacion, publicacion ni generacion de contenido (ver
# acciones.py, punto 14 del enunciado).
TIPOS_ACCION_META = ["pausar", "activar", "modificar_presupuesto"]

# Quien/que origino la propuesta (Paso 12, punto 12: Claude puede
# proponer, nunca ejecutar).
ORIGENES_ACCION_META = ["manual", "optimizacion", "claude"]


class AccionMeta(db.Model):
    """Una accion propuesta sobre un recurso real de Meta (Paso 12).
    Esta misma fila ES el registro de auditoria completo de su propio
    ciclo de vida (quien la propuso, quien la aprobo, cuando se
    ejecuto, que devolvio Meta, que error hubo si lo hubo) -- nunca se
    duplica en una tabla de auditoria aparte.

    `valor_actual`/`valor_propuesto` se guardan EXACTAMENTE en la
    unidad nativa que Meta ya reporta (ver campanas_service.py,
    "unidad monetaria de Meta" documentada desde el Paso 5) -- nunca se
    inventa una conversion de moneda que no existe en el resto del
    sistema.

    `resultado_meta` es un resumen SANEADO de la respuesta de Meta
    (codigo, campos verificados) -- NUNCA el cuerpo crudo de la
    respuesta ni ningun token, aunque la respuesta de Meta nunca
    contendria uno para estas operaciones de escritura.
    """

    __tablename__ = "acciones_meta"

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresas.id"), nullable=False, index=True)
    entidad_id = db.Column(db.Integer, db.ForeignKey("entidades_publicitarias.id"), nullable=False, index=True)

    tipo_accion = db.Column(db.String(30), nullable=False)  # ver TIPOS_ACCION_META
    valor_actual = db.Column(db.String(60), nullable=True)
    valor_propuesto = db.Column(db.String(60), nullable=True)

    motivo = db.Column(db.Text, nullable=False)
    evidencia = db.Column(db.Text, nullable=True)
    riesgo = db.Column(db.Text, nullable=True)
    origen = db.Column(db.String(20), nullable=False, default="manual")

    estado = db.Column(db.String(30), nullable=False, default="pendiente_de_aprobacion")

    propuesto_por = db.Column(db.String(36), db.ForeignKey("usuarios.id"), nullable=True)
    aprobado_por = db.Column(db.String(36), db.ForeignKey("usuarios.id"), nullable=True)
    aprobado_en = db.Column(db.DateTime, nullable=True)
    ejecutado_en = db.Column(db.DateTime, nullable=True)

    resultado_meta = db.Column(db.JSON, nullable=True)
    error_mensaje = db.Column(db.Text, nullable=True)

    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    actualizado_en = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    empresa = db.relationship("Empresa")
    entidad = db.relationship("EntidadPublicitaria")

    def __repr__(self):
        return f"<AccionMeta {self.id} {self.tipo_accion} entidad={self.entidad_id} estado={self.estado}>"
