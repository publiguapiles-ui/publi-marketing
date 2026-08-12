import os

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, url_for

from app.config import INSTANCE_DIR, config_por_nombre
from app.core.auth import obtener_usuario_actual
from app.core.empresas import obtener_empresa_activa, obtener_empresas_usuario
from app.core.errors import registrar_manejadores_error
from app.extensions import db, migrate

load_dotenv()


def create_app(nombre_config=None):
    os.makedirs(INSTANCE_DIR, exist_ok=True)

    app = Flask(__name__)

    nombre_config = nombre_config or os.environ.get("FLASK_ENV", "development")
    app.config.from_object(config_por_nombre[nombre_config])

    db.init_app(app)
    migrate.init_app(app, db)

    from app import models  # noqa: F401  registra los modelos en SQLAlchemy/Alembic

    registrar_manejadores_error(app)
    registrar_blueprints(app)

    @app.context_processor
    def inyectar_contexto_global():
        usuario = obtener_usuario_actual()
        empresa_activa, rol_activo = (None, None)
        empresas_usuario = []
        if usuario is not None:
            empresa_activa, rol_activo = obtener_empresa_activa()
            empresas_usuario = obtener_empresas_usuario(usuario["id"])
        return {
            "usuario_actual": usuario,
            "empresa_activa": empresa_activa,
            "rol_activo": rol_activo,
            "empresas_usuario": empresas_usuario,
        }

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.get("/")
    def index():
        return redirect(url_for("dashboard.index"))

    return app


def registrar_blueprints(app):
    from app.modules.auth.routes import auth_bp
    from app.modules.dashboard.routes import dashboard_bp
    from app.modules.clientes.routes import clientes_bp
    from app.modules.empresas.routes import empresas_bp
    from app.modules.contenido.routes import contenido_bp
    from app.modules.fotografia.routes import fotografia_bp
    from app.modules.diseno.routes import diseno_bp
    from app.modules.ia.routes import ia_bp
    from app.modules.calendario.routes import calendario_bp
    from app.modules.redes_sociales.routes import redes_sociales_bp
    from app.modules.campanas.routes import campanas_bp
    from app.modules.analitica.routes import analitica_bp
    from app.modules.informes.routes import informes_bp
    from app.modules.biblioteca.routes import biblioteca_bp
    from app.modules.configuracion.routes import configuracion_bp
    from app.modules.legacy_solicitudes.routes import legacy_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(clientes_bp)
    app.register_blueprint(empresas_bp)
    app.register_blueprint(contenido_bp)
    app.register_blueprint(fotografia_bp)
    app.register_blueprint(diseno_bp)
    app.register_blueprint(ia_bp)
    app.register_blueprint(calendario_bp)
    app.register_blueprint(redes_sociales_bp)
    app.register_blueprint(campanas_bp)
    app.register_blueprint(analitica_bp)
    app.register_blueprint(informes_bp)
    app.register_blueprint(biblioteca_bp)
    app.register_blueprint(configuracion_bp)
    app.register_blueprint(legacy_bp)
