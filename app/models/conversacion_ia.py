from datetime import datetime, timezone

from app.extensions import db

# Paso 10: el estratega IA nunca ejecuta nada en Meta -- una
# conversacion es solo texto guardado (usuario/asistente) mas un
# RESUMEN LIGERO del contexto usado (nunca el contexto completo ni
# ningun secreto). Ver estratega_ia.py::_resumen_contexto_para_auditoria.
ROLES_MENSAJE_IA = ["usuario", "asistente"]


class ConversacionIA(db.Model):
    """Una conversacion con el Estratega IA (Paso 10) -- pertenece a
    una empresa (aislamiento multi-tenant obligatorio, igual que el
    resto de Datos de Meta) y a un usuario (quien la inicio, para
    auditoria), con un proyecto estrategico opcional si la conversacion
    se abrio desde uno."""

    __tablename__ = "conversaciones_ia"

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresas.id"), nullable=False, index=True)
    usuario_id = db.Column(db.String(36), db.ForeignKey("usuarios.id"), nullable=True)
    proyecto_id = db.Column(
        db.Integer, db.ForeignKey("proyectos_estrategicos.id", ondelete="SET NULL"), nullable=True
    )

    titulo = db.Column(db.String(160), nullable=True)  # se autogenera del primer mensaje si no se indica

    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    actualizado_en = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    empresa = db.relationship("Empresa")
    proyecto = db.relationship("ProyectoEstrategico")
    mensajes = db.relationship(
        "MensajeIA", backref="conversacion", cascade="all, delete-orphan", order_by="MensajeIA.creado_en"
    )

    def __repr__(self):
        return f"<ConversacionIA {self.id} empresa={self.empresa_id}>"


class MensajeIA(db.Model):
    """Un mensaje dentro de una conversacion (Paso 10, punto 11).
    `contexto_utilizado` es SIEMPRE un resumen ligero (conteos y
    etiquetas, ej. '12 campañas, 8 audiencias, últimos 30 días') para
    auditoria -- NUNCA el contexto completo enviado al modelo, y NUNCA
    contiene tokens de Meta ni ningun otro secreto (ver
    estratega_ia.py). `acciones_propuestas` queda reservado sin usar en
    este paso (Paso 10, punto 10: preparar la arquitectura para
    acciones controladas futuras, nunca ejecutarlas todavia)."""

    __tablename__ = "mensajes_ia"

    id = db.Column(db.Integer, primary_key=True)
    conversacion_id = db.Column(
        db.Integer, db.ForeignKey("conversaciones_ia.id", ondelete="CASCADE"), nullable=False, index=True
    )

    rol = db.Column(db.String(20), nullable=False)  # ver ROLES_MENSAJE_IA
    contenido = db.Column(db.Text, nullable=False)
    contexto_utilizado = db.Column(db.JSON, nullable=True)
    acciones_propuestas = db.Column(db.JSON, nullable=True)  # reservado, no usado en el Paso 10

    modelo = db.Column(db.String(60), nullable=True)
    tokens_entrada = db.Column(db.Integer, nullable=True)
    tokens_salida = db.Column(db.Integer, nullable=True)
    costo_estimado_usd = db.Column(db.Float, nullable=True)  # solo si hay precios configurados, nunca inventado

    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def __repr__(self):
        return f"<MensajeIA {self.id} conversacion={self.conversacion_id} rol={self.rol}>"
