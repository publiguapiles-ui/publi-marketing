from datetime import datetime, timezone

from app.extensions import db

ESTADOS_CONEXION_WHATSAPP = ["conectada", "desconectada"]
DIRECCIONES_MENSAJE_WHATSAPP = ["entrante", "saliente"]

# Estados de referencia (Paso 1 de API WhatsApp, punto 8) -- NINGUNO de
# estos es una columna de base de datos: Meta no entrega "conversacion
# abierta/cerrada" ni "mensaje leido/no leido" para mensajes entrantes,
# asi que se calculan en app/services/whatsapp/panel.py a partir de lo
# que si tenemos (direccion + WhatsAppConversation.leida_en), nunca se
# inventan ni se persisten como si vinieran de Meta.
ESTADOS_CONVERSACION_WHATSAPP = ["pendiente_respuesta", "abierta", "respondida", "cerrada"]
ESTADOS_MENSAJE_WHATSAPP = ["recibido", "enviado", "leido", "no_leido"]


class WhatsAppConnection(db.Model):
    """Conexion de una empresa con WhatsApp Business Platform (Cloud
    API de Meta) -- NUNCA WhatsApp personal. Una fila por empresa (se
    sobreescribe al reconfigurar, no se guarda historico de tokens
    viejos, a diferencia de MetaConexion que si conserva historico
    porque ahi la reconexion es mas frecuente). access_token/
    verify_token viajan cifrados (Fernet, ver app/core/crypto.py,
    reutilizando la MISMA clave/funciones que Datos de Meta) -- nunca
    se exponen en template/JSON/logs.
    """

    __tablename__ = "whatsapp_conexiones"

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresas.id"), unique=True, nullable=False, index=True)

    phone_number_id = db.Column(db.String(60), nullable=False)
    whatsapp_business_account_id = db.Column(db.String(60), nullable=False)
    access_token_cifrado = db.Column(db.Text, nullable=False)
    verify_token_cifrado = db.Column(db.Text, nullable=False)

    estado = db.Column(db.String(20), nullable=False, default="conectada")
    ultima_sincronizacion_en = db.Column(db.DateTime, nullable=True)

    configurado_por = db.Column(db.String(36), db.ForeignKey("usuarios.id"), nullable=True)
    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    actualizado_en = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    empresa = db.relationship("Empresa")

    def __repr__(self):
        return f"<WhatsAppConnection empresa={self.empresa_id} estado={self.estado}>"


class WhatsAppContact(db.Model):
    """Un contacto de WhatsApp (numero + nombre de perfil, si Meta lo
    entrega) de una empresa. Aislado por empresa_id -- el mismo numero
    de telefono en dos empresas distintas son dos contactos distintos,
    nunca compartidos entre empresas."""

    __tablename__ = "whatsapp_contactos"
    __table_args__ = (db.UniqueConstraint("empresa_id", "telefono", name="uq_whatsapp_contacto_empresa_telefono"),)

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresas.id"), nullable=False, index=True)
    conexion_id = db.Column(db.Integer, db.ForeignKey("whatsapp_conexiones.id", ondelete="CASCADE"), nullable=False)

    telefono = db.Column(db.String(30), nullable=False)  # wa_id de Meta
    nombre = db.Column(db.String(160), nullable=True)  # profile.name de Meta, si lo entrega

    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    actualizado_en = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    empresa = db.relationship("Empresa")

    def __repr__(self):
        return f"<WhatsAppContact {self.telefono} empresa={self.empresa_id}>"


class WhatsAppConversation(db.Model):
    """Una conversacion con un contacto -- agrupa varios mensajes
    entrantes consecutivos como UNA sola conversacion pendiente (punto
    5 del enunciado de API WhatsApp), nunca cuenta mensajes sueltos.

    `leida_en` es None mientras nadie la marco como vista dentro del
    sistema -- "sin abrir"/UNREAD (punto 6): WhatsApp Cloud API no
    expone exactamente este concepto para el negocio (solo estados de
    entrega para mensajes SALIENTES), asi que se modela como un estado
    interno, documentado aqui como la diferencia explicita que pide el
    enunciado."""

    __tablename__ = "whatsapp_conversaciones"

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresas.id"), nullable=False, index=True)
    contacto_id = db.Column(db.Integer, db.ForeignKey("whatsapp_contactos.id", ondelete="CASCADE"), nullable=False, index=True)

    leida_en = db.Column(db.DateTime, nullable=True)

    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    actualizado_en = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    empresa = db.relationship("Empresa")
    contacto = db.relationship("WhatsAppContact")
    mensajes = db.relationship(
        "WhatsAppMessage", backref="conversacion", cascade="all, delete-orphan", order_by="WhatsAppMessage.creado_en"
    )

    def __repr__(self):
        return f"<WhatsAppConversation contacto={self.contacto_id} empresa={self.empresa_id}>"


class WhatsAppMessage(db.Model):
    """Un mensaje individual de una conversacion. `id_externo` es el
    wamid que asigna Meta -- evita guardar duplicados si Meta reintenta
    la entrega del mismo webhook (comportamiento documentado de Cloud
    API: reintenta si no recibe 200 a tiempo)."""

    __tablename__ = "whatsapp_mensajes"

    id = db.Column(db.Integer, primary_key=True)
    conversacion_id = db.Column(db.Integer, db.ForeignKey("whatsapp_conversaciones.id", ondelete="CASCADE"), nullable=False, index=True)

    direccion = db.Column(db.String(10), nullable=False)  # ver DIRECCIONES_MENSAJE_WHATSAPP -- solo "entrante" se crea por ahora
    contenido = db.Column(db.Text, nullable=False)
    id_externo = db.Column(db.String(120), nullable=True, unique=True)  # wamid de Meta

    creado_en = db.Column(db.DateTime, nullable=False)  # timestamp real del mensaje (de Meta), no el de insercion en la BD

    def __repr__(self):
        return f"<WhatsAppMessage {self.direccion} conversacion={self.conversacion_id}>"
