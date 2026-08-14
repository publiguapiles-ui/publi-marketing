from datetime import datetime, timezone

from app.extensions import db

# Paso 9: ciclo de vida completo de un proyecto estrategico -- mas rico
# que el borrador/plan_aprobado del Planificador (Paso 7, ver
# ProyectoPauta) porque este SI se espera que se siga hasta ejecucion y
# cierre real. Un cambio de estado es SIEMPRE una marca manual del
# equipo -- nunca dispara ninguna accion en Meta.
ESTADOS_PROYECTO_ESTRATEGICO = [
    "borrador",
    "planificado",
    "aprobado",
    "en_ejecucion",
    "finalizado",
    "pausado",
]

# Tipos de audiencia sugeridos en el enunciado del Paso 9 -- una lista
# de REFERENCIA para el selector de la interfaz, nunca un enum que
# bloquee al usuario: `audiencia_tipo` se guarda como texto libre para
# no impedir describir una estrategia de audiencia que no encaje
# exactamente en esta lista.
TIPOS_AUDIENCIA_ESTRATEGICA = [
    "publico_frio",
    "interactuaron",
    "espectadores_video",
    "visitantes",
    "clientes",
    "personalizada",
    "lookalike",
]


class ProyectoEstrategico(db.Model):
    """Proyecto estrategico de campaña (Paso 9): convierte el
    diagnostico/oportunidades del Paso 8 en un plan de fases concreto,
    con audiencias, secuencia de contenido y seguimiento planificado vs
    real. Nunca crea, modifica ni ejecuta nada en Meta -- administra
    unicamente el plan, que vive enteramente en nuestra base de datos.
    """

    __tablename__ = "proyectos_estrategicos"

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresas.id"), nullable=False, index=True)
    # Cuenta publicitaria de la que se toma el diagnostico (Paso 8) y el
    # seguimiento real (Paso 9, punto 10) -- opcional: un proyecto puede
    # crearse antes de tener una cuenta vinculada, ver
    # proyectos_estrategicos.py.
    cuenta_publicitaria_id = db.Column(
        db.Integer, db.ForeignKey("entidades_publicitarias.id", ondelete="SET NULL"), nullable=True
    )

    nombre = db.Column(db.String(160), nullable=False)
    objetivo = db.Column(db.String(120), nullable=False)  # texto libre, ej "conversiones" -- no es un enum de Meta
    kpi_principal = db.Column(db.String(60), nullable=False)  # una clave de kpi.CLAVES_KPI, validada por el servicio
    kpi_secundarios = db.Column(db.JSON, nullable=False, default=list)  # lista de claves de kpi.CLAVES_KPI

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
    fases = db.relationship(
        "FaseEstrategica",
        backref="proyecto",
        cascade="all, delete-orphan",
        order_by="FaseEstrategica.orden",
    )
    secuencia = db.relationship(
        "PasoSecuenciaEstrategica",
        backref="proyecto",
        cascade="all, delete-orphan",
        order_by="PasoSecuenciaEstrategica.orden",
    )

    def __repr__(self):
        return f"<ProyectoEstrategico {self.nombre!r} empresa={self.empresa_id} estado={self.estado}>"


class FaseEstrategica(db.Model):
    """Una fase configurable del proyecto (Paso 9, puntos 3-5) -- el
    numero de fases y sus nombres son libres, nunca una plantilla fija
    de "Reconocimiento/Interaccion/Retargeting/Conversion" impuesta por
    el sistema (el enunciado la da solo como ejemplo).

    `audiencia_entidad_id` vincula la fase a un conjunto de anuncios
    REAL ya sincronizado de Meta cuando el usuario elige uno existente;
    si es None, la audiencia es puramente planeada y AUN NO existe en
    Meta -- la interfaz debe indicarlo explicitamente (Paso 9, punto 5),
    nunca asumir que existe.
    """

    __tablename__ = "fases_estrategicas"

    id = db.Column(db.Integer, primary_key=True)
    proyecto_id = db.Column(db.Integer, db.ForeignKey("proyectos_estrategicos.id", ondelete="CASCADE"), nullable=False, index=True)

    nombre = db.Column(db.String(120), nullable=False)
    objetivo = db.Column(db.String(120), nullable=True)
    presupuesto = db.Column(db.Float, nullable=False)
    fecha_inicio = db.Column(db.Date, nullable=True)
    fecha_fin = db.Column(db.Date, nullable=True)
    kpi_esperado = db.Column(db.String(60), nullable=True)

    audiencia_tipo = db.Column(db.String(40), nullable=True)  # ver TIPOS_AUDIENCIA_ESTRATEGICA, texto libre
    audiencia_descripcion = db.Column(db.String(200), nullable=True)
    audiencia_entidad_id = db.Column(
        db.Integer, db.ForeignKey("entidades_publicitarias.id", ondelete="SET NULL"), nullable=True
    )

    resultado_esperado = db.Column(db.String(200), nullable=True)
    orden = db.Column(db.Integer, nullable=False, default=0)

    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    audiencia_entidad = db.relationship("EntidadPublicitaria")

    def __repr__(self):
        return f"<FaseEstrategica {self.nombre!r} proyecto={self.proyecto_id} presupuesto={self.presupuesto}>"


class PasoSecuenciaEstrategica(db.Model):
    """Un paso de la secuencia estrategica del proyecto (Paso 9, punto
    6) -- ej. "VIDEO 1 -> Personas que interactuan -> VIDEO 2 -> Oferta
    -> Retargeting -> Conversion". Es informacion para que Marketing
    genere contenidos despues; nunca crea ni programa nada en Meta."""

    __tablename__ = "pasos_secuencia_estrategica"

    id = db.Column(db.Integer, primary_key=True)
    proyecto_id = db.Column(db.Integer, db.ForeignKey("proyectos_estrategicos.id", ondelete="CASCADE"), nullable=False, index=True)

    contenido = db.Column(db.String(200), nullable=False)  # ej. "VIDEO 1", "Oferta especial"
    audiencia_descripcion = db.Column(db.String(200), nullable=True)
    objetivo = db.Column(db.String(120), nullable=True)
    duracion_dias = db.Column(db.Integer, nullable=True)
    kpi = db.Column(db.String(60), nullable=True)
    orden = db.Column(db.Integer, nullable=False, default=0)

    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def __repr__(self):
        return f"<PasoSecuenciaEstrategica {self.contenido!r} proyecto={self.proyecto_id} orden={self.orden}>"
