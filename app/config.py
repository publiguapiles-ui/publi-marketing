import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-cambiar-en-produccion")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

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
    # Si DATABASE_URL no esta configurada, se usa SQLite local como fallback
    # de desarrollo (no requiere credenciales de Supabase para trabajar).
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(INSTANCE_DIR, "dev.db")
    )
    # False en desarrollo porque localhost normalmente no usa HTTPS.
    SESSION_COOKIE_SECURE = False


class ProductionConfig(Config):
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
    # La cookie de sesion solo viaja por HTTPS en produccion.
    SESSION_COOKIE_SECURE = True


config_por_nombre = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
}
