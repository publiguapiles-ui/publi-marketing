"""Herramienta de DESARROLLO: crea (o restablece) un usuario
administrador temporal para revisar Publi Marketing manualmente
mientras se construye.

No es parte de la aplicacion Flask: no se registra como Blueprint, no
expone ninguna ruta HTTP, y no debe ejecutarse desde produccion salvo
que sea explicitamente lo que quieres (usa las mismas variables de
entorno SUPABASE_URL/SUPABASE_KEY/DATABASE_URL que la app -- apunta a
la base de datos que tengas configurada al ejecutarlo).

Uso:
    python scripts/crear_admin_dev.py

Que hace:
    1. Crea (o si ya existe, le restablece la contrasena a) el usuario
       admin@publimarketing.local en Supabase Auth, usando una
       contrasena generada aleatoriamente en este mismo momento
       (nunca elegida por una persona, nunca escrita en este archivo).
    2. Guarda esa contrasena UNICAMENTE en un archivo local ignorado
       por git (.admin_dev_credenciales.local.txt, en la raiz del
       proyecto) -- nunca se imprime en la salida de este script ni
       queda en ningun otro lado.
    3. Sincroniza el usuario con el sistema interno (tabla `usuarios`)
       y lo vincula con el rol Administrador en todas las empresas que
       existan en la base de datos conectada, usando exactamente el
       mismo mecanismo usuario/empresa/rol que cualquier otro usuario
       -- no hay ningun bypass ni ruta especial.

Nada de esto queda expuesto como ruta publica de la aplicacion.
"""

import os
import secrets
import sys

RAIZ_PROYECTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ_PROYECTO)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(dotenv_path=os.path.join(RAIZ_PROYECTO, ".env"))

from supabase import create_client  # noqa: E402

ADMIN_EMAIL = "admin@publimarketing.local"
ARCHIVO_CREDENCIALES = os.path.join(RAIZ_PROYECTO, ".admin_dev_credenciales.local.txt")


def obtener_o_crear_usuario_supabase(cliente_admin, password):
    usuarios = cliente_admin.auth.admin.list_users()
    existente = next((u for u in usuarios if u.email == ADMIN_EMAIL), None)

    if existente is None:
        respuesta = cliente_admin.auth.admin.create_user(
            {
                "email": ADMIN_EMAIL,
                "password": password,
                "email_confirm": True,
                "user_metadata": {"nombre": "Administrador Publi Marketing"},
            }
        )
        return respuesta.user, True

    cliente_admin.auth.admin.update_user_by_id(existente.id, {"password": password})
    return existente, False


def main():
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        print("Faltan SUPABASE_URL / SUPABASE_KEY en el entorno (.env). Abortando.")
        sys.exit(1)

    cliente_admin = create_client(supabase_url, supabase_key)
    password_temporal = secrets.token_urlsafe(18)

    usuario_supabase, fue_creado = obtener_o_crear_usuario_supabase(cliente_admin, password_temporal)
    print(f"Usuario en Supabase Auth: {'creado' if fue_creado else 'ya existia, contrasena restablecida'} ({usuario_supabase.id})")

    with open(ARCHIVO_CREDENCIALES, "w", encoding="utf-8") as f:
        f.write(f"Correo: {ADMIN_EMAIL}\n")
        f.write(f"Contrasena temporal: {password_temporal}\n")
        f.write("\nEste archivo NUNCA se sube a git (ver .gitignore). Cambia esta\n")
        f.write("contrasena despues de iniciar sesion la primera vez.\n")
    try:
        os.chmod(ARCHIVO_CREDENCIALES, 0o600)
    except OSError:
        pass  # chmod no aplica igual en todos los sistemas de archivos de Windows

    # --- Sincronizar con el sistema interno de usuarios/roles/empresas ---
    from app import create_app  # noqa: E402
    from app.extensions import db  # noqa: E402
    from app.models import Empresa, Rol, Usuario, UsuarioEmpresaRol  # noqa: E402

    app = create_app()
    with app.app_context():
        usuario_local = db.session.get(Usuario, usuario_supabase.id)
        if usuario_local is None:
            usuario_local = Usuario(
                id=usuario_supabase.id, nombre="Administrador Publi Marketing", email=ADMIN_EMAIL
            )
            db.session.add(usuario_local)
        else:
            usuario_local.email = ADMIN_EMAIL

        rol_admin = db.session.query(Rol).filter_by(nombre="Administrador").first()
        if rol_admin is None:
            print("No existe el rol 'Administrador' en la base de datos conectada (deberia venir de las migraciones).")
            sys.exit(1)

        empresas = db.session.query(Empresa).all()
        nuevas = 0
        for empresa in empresas:
            relacion = (
                db.session.query(UsuarioEmpresaRol)
                .filter_by(usuario_id=usuario_local.id, empresa_id=empresa.id)
                .first()
            )
            if relacion is None:
                db.session.add(
                    UsuarioEmpresaRol(usuario_id=usuario_local.id, empresa_id=empresa.id, rol_id=rol_admin.id)
                )
                nuevas += 1
            elif relacion.rol_id != rol_admin.id:
                relacion.rol_id = rol_admin.id

        db.session.commit()
        print(f"Vinculado como Administrador a {len(empresas)} empresa(s) en esta base de datos ({nuevas} nuevas).")

    print(f"\nCredenciales guardadas localmente en: {ARCHIVO_CREDENCIALES}")
    print("(no se imprimieron aqui ni se guardaron en ningun otro lugar)")


if __name__ == "__main__":
    main()
