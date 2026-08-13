from datetime import datetime, timezone

from app.extensions import db

# Slugs de los 11 presets iniciales (Paso 10). El motor de correccion
# (app/services/procesamiento.py) es el mismo para todos -- un preset
# es solo un conjunto de objetivos que sesga esos calculos, nunca un
# filtro fijo ni un segundo motor.
SLUGS_PRESETS_SISTEMA = [
    "automatico",
    "natural",
    "calido",
    "frio",
    "comercial",
    "vibrante",
    "cinematico",
    "evento",
    "producto",
    "interior",
    "exterior",
]


class Preset(db.Model):
    """Un preset de correccion fotografica.

    Los presets "de sistema" (es_sistema=True, empresa_id=None) vienen
    sembrados por migracion y son de solo lectura desde la aplicacion.
    `empresa_id` queda preparado desde ya para presets personalizados
    por empresa (crear/editar/duplicar/eliminar) -- esa gestion no se
    construye en este paso, pero el modelo ya la soporta sin necesitar
    otro cambio de esquema despues.

    `parametros` son los objetivos que sesga el motor de
    app/services/procesamiento.py (ver `mejorar_fotografia`): nunca se
    interpretan como un filtro que se "aplica encima", siempre entran
    como sesgo de los mismos calculos adaptativos existentes.
    """

    __tablename__ = "presets"

    id = db.Column(db.Integer, primary_key=True)
    # Paso 11.1: 40 alcanzaba para los slugs cortos y fijos de los
    # presets de sistema (Paso 10, ej. "automatico"), pero el slug de
    # un preset PERSONALIZADO (Paso 11) es "personalizado-{empresa_id}-
    # {nombre}" y ese prefijo por si solo ya ocupa 16-18+ caracteres --
    # con 40 se truncaba el nombre a tan poco espacio que un nombre
    # normal ya superaba el limite. SQLite (usado en desarrollo/tests)
    # nunca aplico ese limite de columna, asi que el problema real solo
    # aparecio en produccion (Postgres, que si lo hace cumplir:
    # psycopg2.errors.StringDataRightTruncation). Ver
    # app/services/presets.py::_generar_slug_personalizado.
    slug = db.Column(db.String(160), nullable=False, index=True)
    nombre = db.Column(db.String(60), nullable=False)
    descripcion = db.Column(db.String(255))

    # None = preset de sistema, disponible para todas las empresas.
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresas.id"), nullable=True, index=True)
    es_sistema = db.Column(db.Boolean, default=False, nullable=False)

    # Paso 11: agrupacion visual en la biblioteca (ver CATEGORIAS_PRESET
    # en app/services/presets.py). None = sin categoria asignada.
    categoria = db.Column(db.String(30), nullable=True, index=True)

    # Paso 11: version del CONTENIDO de `parametros`. Se incrementa cada
    # vez que se edita un preset personalizado (nunca en presets de
    # sistema, que son de solo lectura). Un derivado guarda su propio
    # snapshot (FotografiaDerivada.preset_version) tomado en el momento
    # del procesamiento -- por eso un preset editado despues NUNCA
    # cambia retroactivamente como se ve un derivado ya generado.
    version = db.Column(db.Integer, nullable=False, default=1)

    parametros = db.Column(db.JSON, nullable=False, default=dict)

    activo = db.Column(db.Boolean, default=True, nullable=False)
    creado_por = db.Column(db.String(36), db.ForeignKey("usuarios.id"), nullable=True)

    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    actualizado_en = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    empresa = db.relationship("Empresa")

    def __repr__(self):
        return f"<Preset {self.slug} empresa={self.empresa_id}>"


class PresetFavorito(db.Model):
    """Marca "favorito" de un preset para una empresa (Paso 11).

    No es una columna booleana en Preset porque un preset de sistema es
    una unica fila compartida por TODAS las empresas -- si fuera una
    columna ahi, marcar "Cálido" como favorito en una empresa lo
    marcaria para todas. Con esta tabla intermedia, cada empresa tiene
    su propia lista de favoritos sin importar si el preset es de
    sistema o personalizado.
    """

    __tablename__ = "preset_favoritos"
    __table_args__ = (db.UniqueConstraint("empresa_id", "preset_id", name="uq_preset_favorito_empresa_preset"),)

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresas.id"), nullable=False, index=True)
    preset_id = db.Column(db.Integer, db.ForeignKey("presets.id"), nullable=False, index=True)
    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    empresa = db.relationship("Empresa")
    preset = db.relationship("Preset")
