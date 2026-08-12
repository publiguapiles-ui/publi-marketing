import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-cambiar-en-produccion")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY")


class DevelopmentConfig(Config):
    DEBUG = True
    # Si DATABASE_URL no esta configurada, se usa SQLite local como fallback
    # de desarrollo (no requiere credenciales de Supabase para trabajar).
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(INSTANCE_DIR, "dev.db")
    )


class ProductionConfig(Config):
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")


config_por_nombre = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
}
