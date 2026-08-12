from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()
migrate = Migrate()


@event.listens_for(Engine, "connect")
def _configurar_sqlite(conexion_dbapi, _registro_conexion):
    """Solo afecta al fallback SQLite de desarrollo (Postgres no entra
    aqui). WAL permite lecturas concurrentes mientras hay una escritura
    en curso, y el timeout evita el error "database is locked" cuando
    el recargador de depuracion de Flask deja mas de un proceso con el
    archivo abierto a la vez.
    """
    if type(conexion_dbapi).__module__.startswith("sqlite3"):
        cursor = conexion_dbapi.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.close()
