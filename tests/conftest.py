import os
import tempfile
import time

import pytest


@pytest.fixture()
def app():
    """Aplicacion Flask de pruebas con una base SQLite temporal propia
    (nunca la de desarrollo ni la de produccion) y las migraciones
    desactivadas -- las tablas se crean directo con create_all() y se
    siembran solo los roles minimos, igual que hace la migracion real.
    """
    fd, ruta_db = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    variables_originales = {
        "DATABASE_URL": os.environ.get("DATABASE_URL"),
        "APLICAR_MIGRACIONES_AL_INICIAR": os.environ.get("APLICAR_MIGRACIONES_AL_INICIAR"),
        "SECRET_KEY": os.environ.get("SECRET_KEY"),
    }
    os.environ["DATABASE_URL"] = f"sqlite:///{ruta_db}"
    os.environ["APLICAR_MIGRACIONES_AL_INICIAR"] = "0"
    os.environ.setdefault("SECRET_KEY", "clave-de-pruebas-no-usar-en-produccion")

    from app import create_app
    from app.extensions import db as _db
    from app.models import Rol
    from app.services.presets import sembrar_presets_sistema
    from app.services.metricas import sembrar_catalogo_metricas

    aplicacion = create_app("development")
    aplicacion.config["TESTING"] = True

    with aplicacion.app_context():
        _db.create_all()
        for nombre in ["Administrador", "Editor", "Cliente"]:
            _db.session.add(Rol(nombre=nombre))
        _db.session.commit()
        sembrar_presets_sistema()
        sembrar_catalogo_metricas()

        yield aplicacion

        _db.session.remove()
        _db.drop_all()
        _db.engine.dispose()  # libera el archivo antes de borrarlo (necesario en Windows)

    os.remove(ruta_db)
    for clave, valor in variables_originales.items():
        if valor is None:
            os.environ.pop(clave, None)
        else:
            os.environ[clave] = valor


@pytest.fixture()
def client(app):
    return app.test_client()


def _crear_usuario(app, id_usuario, email):
    from app.extensions import db as _db
    from app.models import Usuario

    with app.app_context():
        usuario = Usuario(id=id_usuario, nombre=email.split("@")[0], email=email)
        _db.session.add(usuario)
        _db.session.commit()
    return id_usuario


def _crear_empresa_con_rol(app, usuario_id, nombre_empresa, slug_empresa, rol="Administrador"):
    from app.extensions import db as _db
    from app.models import Empresa, Rol, UsuarioEmpresaRol

    with app.app_context():
        empresa = Empresa(nombre=nombre_empresa, slug=slug_empresa)
        _db.session.add(empresa)
        _db.session.flush()
        rol_obj = _db.session.query(Rol).filter_by(nombre=rol).first()
        _db.session.add(UsuarioEmpresaRol(usuario_id=usuario_id, empresa_id=empresa.id, rol_id=rol_obj.id))
        _db.session.commit()
        return empresa.id


def iniciar_sesion_de_prueba(client, usuario_id, email):
    with client.session_transaction() as sess:
        sess["usuario_id"] = usuario_id
        sess["usuario_email"] = email
        sess["usuario_nombre"] = email.split("@")[0]
        sess["expires_at"] = int(time.time()) + 3600


@pytest.fixture()
def usuario_a_con_empresa(app, client):
    """Usuario A, autenticado, con una empresa propia (unica -> se
    activa automaticamente)."""
    usuario_id = _crear_usuario(app, "aaaaaaaa-1111-1111-1111-111111111111", "a@example.com")
    empresa_id = _crear_empresa_con_rol(app, usuario_id, "Empresa A", "empresa-a")
    iniciar_sesion_de_prueba(client, usuario_id, "a@example.com")
    return {"usuario_id": usuario_id, "empresa_id": empresa_id}


@pytest.fixture()
def usuario_b_con_empresa(app, client):
    """Usuario B, con su PROPIA empresa (distinta de la de A)."""
    usuario_id = _crear_usuario(app, "bbbbbbbb-2222-2222-2222-222222222222", "b@example.com")
    empresa_id = _crear_empresa_con_rol(app, usuario_id, "Empresa B", "empresa-b")
    iniciar_sesion_de_prueba(client, usuario_id, "b@example.com")
    return {"usuario_id": usuario_id, "empresa_id": empresa_id}
