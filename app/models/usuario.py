from datetime import datetime, timezone

from app.extensions import db


class Usuario(db.Model):
    __tablename__ = "usuarios"

    # El id coincide con el id del usuario en Supabase Auth (UUID como
    # texto). No guardamos contrasenas: la autenticacion la resuelve
    # Supabase Auth, esta tabla solo guarda el perfil dentro de Publi
    # Marketing.
    id = db.Column(db.String(36), primary_key=True)
    nombre = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    activo = db.Column(db.Boolean, default=True, nullable=False)
    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    actualizado_en = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    empresas = db.relationship("UsuarioEmpresaRol", back_populates="usuario")

    def __repr__(self):
        return f"<Usuario {self.email}>"
