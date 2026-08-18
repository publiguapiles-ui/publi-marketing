import os

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, url_for
from sqlalchemy import text
from werkzeug.middleware.proxy_fix import ProxyFix

from app.config import INSTANCE_DIR, config_por_nombre
from app.core.auth import obtener_usuario_actual
from app.core.empresas import obtener_empresa_activa, obtener_empresas_usuario
from app.core.errors import registrar_manejadores_error
from app.extensions import db, migrate

load_dotenv()


class ErrorConfiguracion(RuntimeError):
    """Falta una variable de entorno obligatoria para este entorno."""


# Clave arbitraria fija para el advisory lock de Postgres (ver
# _ejecutar_migraciones_con_bloqueo). Puede ser cualquier bigint; solo
# debe ser estable entre despliegues.
_CLAVE_BLOQUEO_MIGRACIONES = 727100


def _ejecutar_migraciones_con_bloqueo(upgrade):
    """Corre flask_migrate.upgrade() protegido por un advisory lock de
    Postgres cuando la base es Postgres (produccion) -- gunicorn arranca
    varios workers (--workers 2, Procfile) que importan run.py y llaman
    create_app() en paralelo, y cada uno intentaria correr las mismas
    migraciones Alembic al mismo tiempo sin este bloqueo. Causa raiz
    real de la caida en produccion del primer intento del Paso 3
    (memoria estrategica, revertido): dos workers ejecutando la misma
    ALTER TABLE ... ADD COLUMN a la vez, uno bloqueado esperando al otro
    hasta que el pooler de Supabase cerraba la conexion por inactividad,
    lanzando una excepcion que tumbaba el worker (gunicorn exit code 3,
    "Worker failed to boot", en bucle). Con el advisory lock, el segundo
    worker espera a que el primero termine y libere el lock -- para
    entonces Alembic ya ve la revision al dia y upgrade() no hace nada.
    En SQLite (desarrollo/tests) no hace falta: cada proceso de test usa
    su propia base, sin concurrencia real entre procesos.
    """
    if db.engine.dialect.name != "postgresql":
        upgrade()
        return

    conexion = db.engine.connect()
    try:
        conexion.execute(text("SELECT pg_advisory_lock(:clave)"), {"clave": _CLAVE_BLOQUEO_MIGRACIONES})
        try:
            upgrade()
        finally:
            conexion.execute(text("SELECT pg_advisory_unlock(:clave)"), {"clave": _CLAVE_BLOQUEO_MIGRACIONES})
    finally:
        conexion.close()


def create_app(nombre_config=None):
    os.makedirs(INSTANCE_DIR, exist_ok=True)

    app = Flask(__name__)
    # Railway termina TLS en su proxy y reenvia HTTP simple al contenedor,
    # asi que sin esto request.scheme (y por lo tanto url_for(_external=True),
    # usado por ejemplo para la URL del webhook de WhatsApp) queda en
    # "http://" en produccion aunque el sitio publico sea https. Confia en
    # un solo hop de proxy (el de Railway).
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

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

            _ejecutar_migraciones_con_bloqueo(upgrade)

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

    @app.get("/privacidad")
    def privacidad():
        from datetime import date

        from flask import render_template

        return render_template("legal/privacidad.html", fecha_actualizacion=date.today().strftime("%d/%m/%Y"))

    return app


def registrar_blueprints(app):
    from app.modules.auth.routes import auth_bp
    from app.modules.dashboard.routes import dashboard_bp
    from app.modules.vocero.routes import vocero_bp
    from app.modules.api_whatsapp.routes import api_whatsapp_bp
    from app.modules.clientes.routes import clientes_bp
    from app.modules.empresas.routes import empresas_bp
    from app.modules.contenido.routes import contenido_bp
    from app.modules.fotografia.routes import fotografia_bp
    from app.modules.diseno.routes import diseno_bp
    from app.modules.estratega_ia.routes import estratega_ia_bp
    from app.modules.calendario.routes import calendario_bp
    from app.modules.redes_sociales.routes import redes_sociales_bp
    from app.modules.creacion_marketing.routes import creacion_marketing_bp
    from app.modules.datos_meta.routes import datos_meta_bp
    from app.modules.biblioteca.routes import biblioteca_bp
    from app.modules.configuracion.routes import configuracion_bp
    from app.modules.legacy_solicitudes.routes import legacy_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(vocero_bp)
    app.register_blueprint(api_whatsapp_bp)
    app.register_blueprint(clientes_bp)
    app.register_blueprint(empresas_bp)
    app.register_blueprint(contenido_bp)
    app.register_blueprint(fotografia_bp)
    app.register_blueprint(diseno_bp)
    app.register_blueprint(estratega_ia_bp)
    app.register_blueprint(calendario_bp)
    app.register_blueprint(redes_sociales_bp)
    # Paso 4: Creacion de Marketing es independiente de Datos de Meta --
    # todo lo que ocurre ANTES de pautar (objetivo, brief, y en pasos
    # futuros estrategia/conceptos/creativos/produccion/calendario),
    # nunca conecta con campañas de Meta ni publica nada.
    app.register_blueprint(creacion_marketing_bp)
    # Campañas, Analítica e Informes (antes stubs "Próximamente"
    # independientes) se reorganizaron dentro de Datos de Meta: una
    # sola integración con Meta, reutilizada por todas las secciones
    # futuras, en vez de tres sistemas que se conectarían por separado.
    app.register_blueprint(datos_meta_bp)
    app.register_blueprint(biblioteca_bp)
    app.register_blueprint(configuracion_bp)
    app.register_blueprint(legacy_bp)
