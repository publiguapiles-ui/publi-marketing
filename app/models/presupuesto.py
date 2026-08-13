from datetime import datetime, timezone

from app.extensions import db

# Paso 2, punto 9: PRESUPUESTO ESTRATEGICO (lo que el cliente esta
# dispuesto a invertir) y PRESUPUESTO ASIGNADO (una porcion de ese
# capital destinada a una campana/conjunto concreto) son DOS FILAS
# DISTINTAS de esta misma tabla, nunca un numero de Meta. El GASTO
# REAL nunca se guarda aqui -- se calcula leyendo Metrica (spend
# nativo, ya sincronizado de Meta) para no duplicar ni desincronizar
# la fuente de verdad. Ver app/services/presupuestos.py.
TIPOS_PRESUPUESTO = ["estrategico", "asignado"]
PERIODOS_PRESUPUESTO = ["mensual", "unico", "personalizado"]


class PresupuestoPauta(db.Model):
    """Capital disponible para pauta publicitaria (Paso 2, puntos 9 y
    10) -- la pieza que permite que una futura capa de optimizacion
    trabaje SIEMPRE dentro del capital real del cliente, nunca
    proponiendo una estrategia que lo exceda.

    `entidad_id` es None para un presupuesto "estrategico" a nivel de
    empresa (el capital general); con valor, es un presupuesto
    "asignado" a una campana/conjunto especifico (debe ser una
    EntidadPublicitaria de tipo campana o conjunto_anuncios, validado
    por el servicio, no por el modelo).

    El "presupuesto recomendado" (punto 9.5) NO se implementa todavia
    -- requiere el motor de optimizacion (fuera de alcance del Paso 2,
    ver informe). No hay columna para el, para no fingir un calculo
    que no existe.
    """

    __tablename__ = "presupuestos_pauta"

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresas.id"), nullable=False, index=True)
    entidad_id = db.Column(db.Integer, db.ForeignKey("entidades_publicitarias.id", ondelete="SET NULL"), nullable=True, index=True)

    nombre = db.Column(db.String(120), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)  # uno de TIPOS_PRESUPUESTO

    monto = db.Column(db.Float, nullable=False)
    moneda = db.Column(db.String(10), nullable=False, default="CRC")

    periodo_tipo = db.Column(db.String(20), nullable=False, default="mensual")  # uno de PERIODOS_PRESUPUESTO
    fecha_inicio = db.Column(db.Date, nullable=True)
    fecha_fin = db.Column(db.Date, nullable=True)  # None + periodo_tipo="mensual" = se renueva cada mes, sin fecha fija

    objetivo = db.Column(db.String(120), nullable=True)  # texto libre, ej "conversiones"
    notas = db.Column(db.Text, nullable=True)

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
    entidad = db.relationship("EntidadPublicitaria")

    def __repr__(self):
        return f"<PresupuestoPauta {self.tipo} {self.monto}{self.moneda} empresa={self.empresa_id}>"
