from datetime import datetime, timezone

from app.extensions import db

ESTADOS_SESION = [
    "pendiente",
    "analizando",
    "procesando",
    "completada",
    "completada_con_errores",
    "error",
    "cancelada",
]
ESTADOS_SESION_TERMINALES = ["completada", "completada_con_errores", "error", "cancelada"]


class SesionFotografica(db.Model):
    """Un lote de procesamiento masivo sobre fotografias ya existentes
    en un proyecto (Paso 10). No es una segunda galeria ni un segundo
    sistema de derivados: agrupa y da seguimiento a un conjunto de
    ejecuciones de app/services/derivados.py sobre fotografias que ya
    viven en app.models.Fotografia.

    El progreso (`completadas` / `errores` sobre `total_fotografias`)
    es siempre el conteo real de SesionItem en cada estado -- nunca una
    barra de progreso simulada.
    """

    __tablename__ = "sesiones_fotograficas"

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresas.id"), nullable=False, index=True)
    proyecto_id = db.Column(db.Integer, db.ForeignKey("proyectos_fotograficos.id"), nullable=False, index=True)
    nombre = db.Column(db.String(120), nullable=False)

    preset_id = db.Column(db.Integer, db.ForeignKey("presets.id"), nullable=False)

    # Configuracion de marca (mismo sistema del Paso 8, nunca uno nuevo).
    logo_id = db.Column(db.Integer, db.ForeignKey("logos.id", ondelete="SET NULL"), nullable=True)
    aplicacion_logo = db.Column(db.String(20), default="sin_logo")
    posicion_logo = db.Column(db.String(30))
    opacidad_logo = db.Column(db.Float)

    # Lista separada por comas de tipos de derivado a generar por foto,
    # ej. "mejora_automatica,formato_cuadrado,formato_vertical" -- mismo
    # patron que FotografiaDerivada.correcciones_aplicadas.
    formatos_seleccionados = db.Column(db.String(255), nullable=False)

    estado = db.Column(db.String(30), nullable=False, default="pendiente")

    total_fotografias = db.Column(db.Integer, nullable=False, default=0)
    completadas = db.Column(db.Integer, nullable=False, default=0)
    errores = db.Column(db.Integer, nullable=False, default=0)

    # Estadisticas agregadas de la sesion (analisis previo, ver Paso 10
    # "Consistencia entre fotografias"). Se calculan sobre TODAS las
    # fotografias de la sesion antes de procesar ninguna.
    analisis_brillo_promedio = db.Column(db.Float)
    analisis_contraste_promedio = db.Column(db.Float)
    analisis_saturacion_promedio = db.Column(db.Float)
    analisis_temperatura_predominante = db.Column(db.String(20))
    analisis_duracion_segundos = db.Column(db.Float)

    creado_por = db.Column(db.String(36), db.ForeignKey("usuarios.id"), nullable=True)

    iniciado_en = db.Column(db.DateTime)
    finalizado_en = db.Column(db.DateTime)
    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    actualizado_en = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    empresa = db.relationship("Empresa")
    proyecto = db.relationship("ProyectoFotografico")
    preset = db.relationship("Preset")
    logo = db.relationship("Logo")

    def __repr__(self):
        return f"<SesionFotografica {self.nombre} estado={self.estado} {self.completadas}/{self.total_fotografias}>"


class SesionItem(db.Model):
    """Una fotografia dentro de una SesionFotografica y su progreso
    individual. Una foto puede generar varios derivados (mejora +
    varios formatos); este registro es sobre la FOTO, no sobre cada
    derivado -- por eso el progreso reportado son "fotos", no salidas.
    """

    __tablename__ = "sesion_items"

    id = db.Column(db.Integer, primary_key=True)
    sesion_id = db.Column(db.Integer, db.ForeignKey("sesiones_fotograficas.id"), nullable=False, index=True)
    fotografia_id = db.Column(db.Integer, db.ForeignKey("fotografias.id"), nullable=False, index=True)

    estado = db.Column(db.String(20), nullable=False, default="pendiente")
    error_mensaje = db.Column(db.String(500))

    iniciado_en = db.Column(db.DateTime)
    finalizado_en = db.Column(db.DateTime)
    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    sesion = db.relationship("SesionFotografica")
    fotografia = db.relationship("Fotografia")

    def __repr__(self):
        return f"<SesionItem sesion={self.sesion_id} foto={self.fotografia_id} estado={self.estado}>"
