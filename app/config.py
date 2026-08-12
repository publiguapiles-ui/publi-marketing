import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")


def _normalizar_url_postgres(url):
    """Normaliza una cadena de conexion a PostgreSQL para SQLAlchemy.

    Algunos proveedores (Railway/Heroku historicamente) entregan la URL
    con el esquema 'postgres://', que SQLAlchemy 1.4+ ya no acepta
    (exige 'postgresql://'). Tambien se asegura sslmode=require si no
    viene incluido, ya que tanto Supabase como Railway requieren TLS
    para conexiones externas a Postgres.
    """
    if not url:
        return url

    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]

    if url.startswith("postgresql://") and "sslmode=" not in url:
        separador = "&" if "?" in url else "?"
        url = f"{url}{separador}sslmode=require"

    return url


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-cambiar-en-produccion")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # pool_pre_ping evita errores por conexiones caidas/reiniciadas por el
    # proveedor (comun en poolers como el de Supabase); sin costo real
    # cuando la base es SQLite.
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

    # La sesion (usuario_id, tokens de Supabase) vive en la cookie de
    # Flask, firmada con SECRET_KEY. HttpOnly evita que JavaScript la lea;
    # SameSite=Lax mitiga CSRF basico.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # Limite global de tamano de request (ademas de la validacion propia
    # de app/services/storage.py) para rechazar subidas enormes antes de
    # que lleguen siquiera a la logica de la aplicacion.
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB


class DevelopmentConfig(Config):
    DEBUG = True
    # DATABASE_URL es recomendable tambien en desarrollo (por ejemplo
    # apuntando al mismo Postgres de Supabase), pero si no esta definida
    # se usa SQLite local como fallback -- una decision explicita y
    # documentada aqui mismo, exclusiva de este entorno. En produccion
    # este fallback NO existe (ver ProductionConfig).
    SQLALCHEMY_DATABASE_URI = _normalizar_url_postgres(
        os.environ.get("DATABASE_URL")
    ) or ("sqlite:///" + os.path.join(INSTANCE_DIR, "dev.db"))
    # False en desarrollo porque localhost normalmente no usa HTTPS.
    SESSION_COOKIE_SECURE = False


class ProductionConfig(Config):
    DEBUG = False
    # Sin fallback: si DATABASE_URL falta, esto queda en None a
    # proposito. create_app() valida esto explicitamente y se niega a
    # arrancar en vez de caer en SQLite en silencio.
    SQLALCHEMY_DATABASE_URI = _normalizar_url_postgres(os.environ.get("DATABASE_URL"))
    # La cookie de sesion solo viaja por HTTPS en produccion.
    SESSION_COOKIE_SECURE = True


config_por_nombre = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
}
