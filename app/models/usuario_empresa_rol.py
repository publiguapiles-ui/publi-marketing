from app.extensions import db


class UsuarioEmpresaRol(db.Model):
    """Que rol tiene cada usuario dentro de cada empresa (multi-tenant)."""

    __tablename__ = "usuario_empresa_rol"

    usuario_id = db.Column(db.String(36), db.ForeignKey("usuarios.id"), primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresas.id"), primary_key=True)
    rol_id = db.Column(db.Integer, db.ForeignKey("roles.id"), primary_key=True)

    usuario = db.relationship("Usuario", back_populates="empresas")
    empresa = db.relationship("Empresa")
    rol = db.relationship("Rol")
