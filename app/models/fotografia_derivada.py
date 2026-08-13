from datetime import datetime, timezone

from app.extensions import db

TIPOS_DERIVADO = [
    "mejora_automatica",
    "formato_cuadrado",
    "formato_vertical",
    "formato_historia",
    "formato_horizontal",
]
ESTADOS_DERIVADO = ["pendiente", "procesando", "completada", "error"]

# Paso 8: aplicacion de logo/marca de agua sobre un formato generado.
APLICACIONES_LOGO = ["sin_logo", "logo", "marca_agua"]
POSICIONES_LOGO = ["superior_izquierda", "superior_derecha", "inferior_izquierda", "inferior_derecha", "centro"]
POSICION_LOGO_PREDETERMINADA = "inferior_derecha"

# Paso 9: modo de encuadre.
MODOS_RECORTE = ["auto", "manual"]
MODO_RECORTE_PREDETERMINADO = "auto"


class FotografiaDerivada(db.Model):
    """Version derivada de una fotografia original (nunca la reemplaza).

    Puede existir mas de un derivado por fotografia y tipo (version 1,
    2, 3...) -- nunca se sobreescribe uno existente en silencio. El
    campo `estado` es del PROCESO de este derivado, no de la
    fotografia original (que permanece "original" para siempre).
    """

    __tablename__ = "fotografias_derivadas"

    id = db.Column(db.Integer, primary_key=True)
    # Denormalizado (mismo patron que Fotografia.empresa_id): permite
    # validar aislamiento por empresa sin JOIN.
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresas.id"), nullable=False, index=True)
    fotografia_id = db.Column(db.Integer, db.ForeignKey("fotografias.id"), nullable=False, index=True)

    tipo = db.Column(db.String(30), nullable=False, default="mejora_automatica")
    version = db.Column(db.Integer, nullable=False, default=1)
    estado = db.Column(db.String(20), nullable=False, default="pendiente")
    error_mensaje = db.Column(db.String(500))

    ruta_storage = db.Column(db.String(500))
    tipo_mime = db.Column(db.String(100))
    tamano_bytes = db.Column(db.Integer)

    # Resultado del analisis/clasificacion (ver app/services/procesamiento.py).
    # Nunca se guarda aqui informacion biometrica ni de identidad: solo
    # cuantos rostros se detectaron y si la mascara de proteccion se aplico.
    categoria_detectada = db.Column(db.String(30))
    confianza_categoria = db.Column(db.Float)
    rostros_detectados = db.Column(db.Integer, default=0)
    rostros_protegidos = db.Column(db.Boolean, default=False)
    correcciones_aplicadas = db.Column(db.String(255))  # lista separada por comas
    duracion_segundos = db.Column(db.Float)

    # Paso 8: metadata de logo/marca de agua y del formato generado.
    # logo_id se deja SET NULL en cascada (no se borra el derivado si el
    # logo se elimina despues) porque el registro sigue siendo un
    # historial valido de lo que se genero en su momento.
    logo_id = db.Column(db.Integer, db.ForeignKey("logos.id", ondelete="SET NULL"), nullable=True)
    aplicacion_logo = db.Column(db.String(20))  # uno de APLICACIONES_LOGO
    posicion_logo = db.Column(db.String(30))  # uno de POSICIONES_LOGO
    opacidad_logo = db.Column(db.Float)
    ancho_px = db.Column(db.Integer)
    alto_px = db.Column(db.Integer)
    advertencia = db.Column(db.String(255))  # ej. encuadre imperfecto, logo de baja resolucion

    # Paso 9: encuadre inteligente/manual. Las coordenadas crop_* estan
    # en pixeles de la imagen ORIGEN usada (original o mejora), no del
    # resultado final -- describen de donde se tomo el recorte, util
    # para depurar o para un futuro "restablecer a este encuadre".
    crop_mode = db.Column(db.String(10))  # uno de MODOS_RECORTE
    focus_x = db.Column(db.Float)  # 0-1, normalizado; None si no se uso foco manual
    focus_y = db.Column(db.Float)
    crop_x = db.Column(db.Integer)
    crop_y = db.Column(db.Integer)
    crop_width = db.Column(db.Integer)
    crop_height = db.Column(db.Integer)
    algoritmo_recorte = db.Column(db.String(30))  # ej. "rostros", "saliencia", "manual"

    # Paso 10: si este derivado se genero como parte de un procesamiento
    # masivo, referencia a esa sesion (para poder listar/agrupar
    # "sesion_001 -> fotografia_001 -> mejorada_v1, cuadrado_v1..."). Un
    # derivado creado por las rutas individuales existentes (Paso 7/8)
    # simplemente deja esto en None -- no cambia su comportamiento.
    sesion_id = db.Column(db.Integer, db.ForeignKey("sesiones_fotograficas.id", ondelete="SET NULL"), nullable=True, index=True)
    preset_id = db.Column(db.Integer, db.ForeignKey("presets.id", ondelete="SET NULL"), nullable=True)

    # Paso 11: snapshot INMUTABLE de que preset se uso, tomado en el
    # momento del procesamiento -- independiente de `preset_id` (que es
    # una FK viva y puede quedar en NULL si el preset se elimina, o
    # seguir apuntando a un preset cuyo `parametros`/`version` cambio
    # despues). Un derivado ya generado debe seguir mostrando "Publi
    # Cálido v1" aunque el preset en si ya sea v2 o ya no exista.
    preset_nombre = db.Column(db.String(60), nullable=True)
    preset_version = db.Column(db.Integer, nullable=True)

    creado_por = db.Column(db.String(36), db.ForeignKey("usuarios.id"), nullable=True)

    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    actualizado_en = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    fotografia = db.relationship("Fotografia")
    empresa = db.relationship("Empresa")
    logo = db.relationship("Logo")
    sesion = db.relationship("SesionFotografica")
    preset = db.relationship("Preset")

    def __repr__(self):
        return f"<FotografiaDerivada {self.tipo} v{self.version} foto={self.fotografia_id} estado={self.estado}>"
