from datetime import datetime, timezone

from app.extensions import db

# Paso 7: el planificador SOLO administra el plan (nunca ejecuta nada en
# Meta). "Borrador" es el estado inicial y editable; "plan_aprobado" es
# una marca del propio equipo de que el plan esta listo para pasar a
# ejecucion manual -- no dispara ninguna accion automatica.
ESTADOS_PROYECTO_PAUTA = ["borrador", "plan_aprobado"]


class ProyectoPauta(db.Model):
    """Proyecto estrategico de pauta (Paso 7): capital + periodo +
    objetivo definidos por el usuario, con una propuesta de distribucion
    por fases fundamentada en datos historicos reales cuando existen.
    Nunca crea, modifica ni programa nada en Meta -- es una herramienta
    de planificacion interna.
    """

    __tablename__ = "proyectos_pauta"

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresas.id"), nullable=False, index=True)
    # Cuenta publicitaria de la que se toma el analisis historico (Paso 7,
    # punto 2) -- opcional: un proyecto puede crearse antes de tener
    # datos historicos que analizar, ver planificador.py.
    cuenta_publicitaria_id = db.Column(
        db.Integer, db.ForeignKey("entidades_publicitarias.id", ondelete="SET NULL"), nullable=True
    )

    nombre = db.Column(db.String(160), nullable=False)
    objetivo = db.Column(db.String(120), nullable=False)  # texto libre, ej "conversiones" -- no es un enum de Meta
    kpi_principal = db.Column(db.String(60), nullable=False)  # una clave de kpi.CLAVES_KPI, validada por el servicio

    presupuesto_total = db.Column(db.Float, nullable=False)
    moneda = db.Column(db.String(10), nullable=False, default="CRC")

    fecha_inicio = db.Column(db.Date, nullable=False)
    fecha_fin = db.Column(db.Date, nullable=False)

    resultado_objetivo = db.Column(db.String(200), nullable=True)  # texto libre, ej "50 conversiones" -- META, nunca REAL
    restricciones = db.Column(db.Text, nullable=True)

    estado = db.Column(db.String(20), nullable=False, default="borrador")

    creado_por = db.Column(db.String(36), db.ForeignKey("usuarios.id"), nullable=True)
    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    actualizado_en = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    empresa = db.relationship("Empresa")
    cuenta_publicitaria = db.relationship("EntidadPublicitaria")
    etapas = db.relationship(
        "EtapaProyectoPauta",
        backref="proyecto",
        cascade="all, delete-orphan",
        order_by="EtapaProyectoPauta.orden",
    )

    def __repr__(self):
        return f"<ProyectoPauta {self.nombre!r} empresa={self.empresa_id} estado={self.estado}>"


class EtapaProyectoPauta(db.Model):
    """Una fase configurable del proyecto (Paso 7, punto 3) -- el
    numero de fases y sus nombres son libres, nunca una plantilla fija
    de "Reconocimiento/Consideracion/Conversion/Retargeting" impuesta
    por el sistema. `audiencia_descripcion` es texto libre que registra
    la ESTRATEGIA de audiencia (ej. "Personas que interactuaron en los
    ultimos 90 dias") -- nunca crea ni referencia un ID real de audiencia
    en Meta, ver planificador.py.
    """

    __tablename__ = "etapas_proyecto_pauta"

    id = db.Column(db.Integer, primary_key=True)
    proyecto_id = db.Column(db.Integer, db.ForeignKey("proyectos_pauta.id", ondelete="CASCADE"), nullable=False, index=True)

    nombre = db.Column(db.String(120), nullable=False)
    objetivo = db.Column(db.String(120), nullable=True)
    presupuesto = db.Column(db.Float, nullable=False)
    kpi_esperado = db.Column(db.String(60), nullable=True)
    audiencia_descripcion = db.Column(db.String(200), nullable=True)
    duracion_dias = db.Column(db.Integer, nullable=True)
    orden = db.Column(db.Integer, nullable=False, default=0)

    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def __repr__(self):
        return f"<EtapaProyectoPauta {self.nombre!r} proyecto={self.proyecto_id} presupuesto={self.presupuesto}>"
