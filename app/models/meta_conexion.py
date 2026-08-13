from datetime import datetime, timezone

from app.extensions import db

# Estados posibles de una conexion. "activa" es la unica que el resto
# del sistema debe usar para leer datos -- las demas existen para que
# la pantalla de Conexiones pueda explicarle al usuario que paso
# (nunca solo desaparece un boton sin explicacion).
ESTADOS_CONEXION_META = ["activa", "expirada", "revocada", "error"]


class MetaConexion(db.Model):
    """Una autorizacion OAuth de un usuario de Meta hacia Publi
    Marketing, en nombre de una empresa concreta (Paso 1 de Datos de
    Meta).

    Una empresa puede tener varias filas a lo largo del tiempo (si se
    reconecta, o si revocamos y vuelve a autorizar) -- se identifica
    "la" conexion vigente por estado="activa" (ver
    app/services/meta/conexiones.py::obtener_conexion_activa), nunca
    borrando el historial de conexiones anteriores.

    `access_token_cifrado` NUNCA se expone a rutas/templates/JSON
    directamente -- solo se descifra dentro de
    app/services/meta/conexiones.py para pasarlo a MetaClient. Ver
    app/core/crypto.py.
    """

    __tablename__ = "meta_conexiones"

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresas.id"), nullable=False, index=True)

    meta_user_id = db.Column(db.String(64), nullable=False)
    nombre_usuario_meta = db.Column(db.String(255))

    access_token_cifrado = db.Column(db.Text, nullable=False)
    token_expira_en = db.Column(db.DateTime, nullable=True)  # Meta: tokens de larga duracion, ~60 dias
    scopes_concedidos = db.Column(db.String(500))  # csv, ej "ads_read,pages_show_list"

    estado = db.Column(db.String(20), nullable=False, default="activa")
    ultimo_error = db.Column(db.String(500))

    ultima_sincronizacion_en = db.Column(db.DateTime, nullable=True)

    conectado_por = db.Column(db.String(36), db.ForeignKey("usuarios.id"), nullable=True)

    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    actualizado_en = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    empresa = db.relationship("Empresa")

    def __repr__(self):
        return f"<MetaConexion empresa={self.empresa_id} estado={self.estado}>"
