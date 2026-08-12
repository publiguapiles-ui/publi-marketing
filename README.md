# Publi Marketing

Plataforma integral de marketing digital, contenido, fotografía, diseño, clientes y analítica para Publi Guapiles.

Arquitectura: monolito modular en Flask (ver `docs/architecture.md`). Un único proyecto, un único deploy, módulos independientes (Blueprints) dentro del mismo backend — no hay aplicaciones separadas por módulo.

## Estado actual

Fundaciones de la arquitectura (Paso 2): `create_app()`, Blueprints, SQLAlchemy + Alembic, modelos core (`Usuario`, `Rol`, `Empresa`, `usuario_empresa_rol`), layout responsive con sidebar/navegación. La mayoría de los módulos (Fotografía, Diseño, IA, Calendario, Redes Sociales, Campañas, Analítica, Informes, Biblioteca, Configuración, Clientes, Empresas) todavía muestran una pantalla "Próximamente" — solo están reservados en la navegación, sin funcionalidad real todavía. El login con Supabase Auth aún no está implementado (siguiente paso).

Se conserva, sin eliminar, el prototipo anterior de "solicitudes/citas" (no forma parte del producto final), aislado bajo el prefijo `/legacy`.

## Correr localmente

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

La app queda disponible en `http://localhost:8000`.

## Variables de entorno

Copiar `.env.example` como `.env` y completar:

- `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_KEY`: credenciales del proyecto de Supabase (Project Settings → API).
- `DATABASE_URL`: cadena de conexión a PostgreSQL (Supabase → Project Settings → Database → Connection string → URI). **Si se deja vacía en desarrollo, la app usa automáticamente una base SQLite local (`instance/dev.db`)** para poder trabajar sin esas credenciales. En producción es obligatoria.
- `SECRET_KEY`: clave propia para firmar la sesión de Flask (no usar un valor de ejemplo en producción).
- `FLASK_ENV`: `development` o `production`.

## Migraciones (Alembic vía Flask-Migrate)

Los cambios de esquema de base de datos se manejan con migraciones versionadas, no editando tablas a mano en el dashboard de Supabase.

```bash
set FLASK_APP=run.py
flask db migrate -m "descripcion del cambio"
flask db upgrade
```

## Pruebas

Todavía no existe una suite de pruebas automatizadas en el proyecto.

## Estructura general

```
app/
├── config.py, extensions.py     # configuración y extensiones compartidas (db, migrate)
├── core/                        # auth, decoradores, manejo de errores
├── models/                      # Usuario, Rol, Empresa, usuario_empresa_rol
├── modules/                     # un Blueprint por módulo (dashboard, clientes, fotografia, ...)
├── templates/, static/          # layout base y estilos compartidos
migrations/                      # historial de migraciones (Alembic)
run.py                           # punto de entrada (desarrollo y Railway)
```

## Deploy

Cada push a `main` despliega automáticamente en Railway.
