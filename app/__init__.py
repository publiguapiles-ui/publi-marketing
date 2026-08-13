import os

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, url_for
from sqlalchemy import text

from app.config import INSTANCE_DIR, config_por_nombre
from app.core.auth import obtener_usuario_actual
from app.core.empresas import obtener_empresa_activa, obtener_empresas_usuario
from app.core.errors import registrar_manejadores_error
from app.extensions import db, migrate

load_dotenv()


class ErrorConfiguracion(RuntimeError):
    """Falta una variable de entorno obligatoria para este entorno."""


def create_app(nombre_config=None):
    os.makedirs(INSTANCE_DIR, exist_ok=True)

    app = Flask(__name__)

    nombre_config = nombre_config or os.environ.get("FLASK_ENV", "development")
    config_clase = config_por_nombre[nombre_config]
    app.config.from_object(config_clase)
    # Se resuelve aqui (no se deja el valor congelado del atributo de
    # clase) para que siempre use el DATABASE_URL vigente en el momento
    # de esta llamada -- ver DevelopmentConfig.resolver_database_uri().
    app.config["SQLALCHEMY_DATABASE_URI"] = config_clase.resolver_database_uri()

    if nombre_config == "production" and not app.config.get("SQLALCHEMY_DATABASE_URI"):
        raise ErrorConfiguracion(
            "Falta DATABASE_URL en produccion. La aplicacion no debe iniciar "
            "usando SQLite en produccion (el almacenamiento del contenedor es "
            "efimero). Configura DATABASE_URL con la cadena de conexion de "
            "PostgreSQL de Supabase en las variables de entorno de Railway."
        )

    db.init_app(app)
    migrate.init_app(app, db)

    from app import models  # noqa: F401  registra los modelos en SQLAlchemy/Alembic

    if os.environ.get("APLICAR_MIGRACIONES_AL_INICIAR", "1") == "1":
        with app.app_context():
            from flask_migrate import upgrade

            upgrade()

            # Idempotente: crea los 11 presets de sistema (Paso 10) si
            # todavia no existen. Va aqui (no en la migracion) porque
            # depende de la sesion normal de SQLAlchemy, no de Alembic.
            from app.services.presets import sembrar_presets_sistema

            sembrar_presets_sistema()

            # Idempotente: catalogo inicial de metricas (Datos de Meta,
            # Paso 1) -- mismo motivo que sembrar_presets_sistema.
            from app.services.metricas import sembrar_catalogo_metricas

            sembrar_catalogo_metricas()

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
        estado_bd = "ok"
        try:
            db.session.execute(text("SELECT 1"))
        except Exception:
            estado_bd = "error"

        codigo = 200 if estado_bd == "ok" else 503
        return jsonify({"application": "ok", "database": estado_bd}), codigo

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
    from app.modules.datos_meta.routes import datos_meta_bp
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
    # Campañas, Analítica e Informes (antes stubs "Próximamente"
    # independientes) se reorganizaron dentro de Datos de Meta: una
    # sola integración con Meta, reutilizada por todas las secciones
    # futuras, en vez de tres sistemas que se conectarían por separado.
    app.register_blueprint(datos_meta_bp)
    app.register_blueprint(biblioteca_bp)
    app.register_blueprint(configuracion_bp)
    app.register_blueprint(legacy_bp)
