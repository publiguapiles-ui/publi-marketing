from datetime import datetime, timezone

from app.extensions import db

# Paso 4 (Creacion de Marketing): lista de REFERENCIA para el selector de
# la interfaz -- igual que TIPOS_AUDIENCIA_ESTRATEGICA en proyecto_estrategico.py,
# nunca un enum que bloquee al usuario. objetivo_tipo se guarda como texto
# libre para permitir "otro" + objetivo_detalle.
OBJETIVOS_SUGERIDOS = [
    "dar_a_conocer",
    "conseguir_clientes",
    "aumentar_ventas",
    "lanzar_producto",
    "promocionar_producto",
    "mensajes_whatsapp",
    "visitas_local",
    "aumentar_seguidores",
    "crear_comunidad",
    "promocionar_evento",
    "otro",
]

ACCIONES_SUGERIDAS = [
    "comprar",
    "escribir_whatsapp",
    "visitar_negocio",
    "reservar",
    "llamar",
    "solicitar_informacion",
    "seguir_pagina",
    "compartir",
    "registrarse",
    "otro",
]

ESTADOS_PROYECTO_MARKETING = ["borrador", "confirmado"]


class ProyectoMarketing(db.Model):
    """Proyecto de Creacion de Marketing (Paso 4): el objetivo y brief
    estrategico de una campaña ANTES de pautar -- completamente
    independiente de Datos de Meta (pauta/analisis/optimizacion sobre
    datos reales). Este paso construye unicamente objetivo + brief;
    los campos de las etapas futuras (estrategia de contenido, conceptos,
    creativos, guiones, produccion, edicion, calendario, publicacion,
    pauta) se agregaran como columnas/tablas nuevas en pasos posteriores
    sin romper esta base, siguiendo el mismo `estado` como marca manual
    del equipo (nunca dispara nada automaticamente).
    """

    __tablename__ = "proyectos_marketing"

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresas.id"), nullable=False, index=True)

    nombre = db.Column(db.String(160), nullable=False)
    estado = db.Column(db.String(20), nullable=False, default="borrador")

    # --- Brief: que quiere lograr --------------------------------------
    objetivo_tipo = db.Column(db.String(40), nullable=True)  # ver OBJETIVOS_SUGERIDOS
    objetivo_detalle = db.Column(db.Text, nullable=True)  # texto libre, obligatorio si objetivo_tipo == "otro"

    # --- Brief: a quien queremos llegar --------------------------------
    # JSON en vez de columnas separadas: son preguntas en texto libre
    # (Paso 4, punto 4 pide explicitamente no obligar a terminos tecnicos),
    # claves: ubicacion, edad, genero, tipo_cliente, intereses, necesidades,
    # problema, comportamiento, relacion_marca.
    publico = db.Column(db.JSON, nullable=False, default=dict)

    # --- Brief: que estamos ofreciendo ---------------------------------
    # claves: producto, servicio, oferta, precio, promocion,
    # beneficio_principal, diferenciador.
    oferta = db.Column(db.JSON, nullable=False, default=dict)

    # --- Brief: que debe hacer la persona -------------------------------
    accion_deseada = db.Column(db.String(40), nullable=True)  # ver ACCIONES_SUGERIDAS
    accion_detalle = db.Column(db.Text, nullable=True)  # texto libre, obligatorio si accion_deseada == "otro"

    # --- Brief: presupuesto (produccion y pauta NUNCA se asumen iguales) --
    presupuesto_produccion = db.Column(db.Float, nullable=True)  # None = "Por definir"
    presupuesto_pauta = db.Column(db.Float, nullable=True)  # None = "Por definir"
    moneda = db.Column(db.String(10), nullable=False, default="CRC")

    # --- Brief: plazo ----------------------------------------------------
    fecha_inicio = db.Column(db.Date, nullable=True)
    fecha_fin = db.Column(db.Date, nullable=True)
    sin_fecha_definida = db.Column(db.Boolean, nullable=False, default=False)

    # --- Brief: identidad de marca ----------------------------------------
    # Solo lo que IdentidadMarca/Logo (app/services/marca.py) NO cubren
    # todavia -- nombre comercial, colores y logo se leen en vivo de ahi
    # (Paso 4, punto 9: nunca repetir informacion que ya exista en Publi
    # Marketing) y nunca se duplican aqui. Claves: tono, estilo,
    # personalidad, restricciones.
    identidad_marca_brief = db.Column(db.JSON, nullable=False, default=dict)

    # --- Brief: informacion adicional en texto libre -----------------------
    informacion_adicional = db.Column(db.Text, nullable=True)

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
        return f"<ProyectoMarketing {self.nombre!r} empresa={self.empresa_id} estado={self.estado}>"
