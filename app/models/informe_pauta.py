from datetime import datetime, timezone

from app.extensions import db

# Paso 15: los 5 tipos de informe determinan solo que SECCIONES se
# incluyen (ver informes.py::SECCIONES_POR_TIPO) -- todos comparten el
# mismo contenido calculado, nunca un motor de metricas distinto por
# tipo.
TIPOS_INFORME_PAUTA = ["rendimiento", "campanas", "audiencias", "optimizacion", "ejecutivo"]

# "sin_comparacion" es exclusivo de informes.py (a diferencia de
# kpi.TIPOS_COMPARACION_PERIODO, que solo conoce los dos tipos que de
# verdad consultan un periodo de referencia) -- ver kpi.py, Paso 14.
TIPOS_COMPARACION_INFORME = ["periodo_anterior", "mismo_periodo_anio_anterior", "sin_comparacion"]

# Un informe se genera una sola vez de forma sincrona (nunca hay un
# estado "generando" persistido: no hay ninguna tarea en segundo plano
# todavia) -- "error" ocurre solo si la cuenta/entidades seleccionadas
# no pertenecen a la empresa o construir_informe() falla por falta de
# datos irrecuperable.
ESTADOS_INFORME_PAUTA = ["listo", "error"]

MODOS_INFORME_PAUTA = ["interno", "cliente"]


class InformePauta(db.Model):
    """Un informe generado (Paso 15) -- guarda un SNAPSHOT del contenido
    calculado en el momento de generarlo (`contenido`, JSON), nunca solo
    los filtros. Esto es deliberado: un informe historico debe seguir
    mostrando exactamente lo que mostraba cuando se genero, incluso si
    los datos de Meta cambian despues (nueva sincronizacion, campañas
    pausadas, etc.) -- igual que un reporte financiero no cambia
    retroactivamente. El PDF se genera BAJO DEMANDA a partir de este
    mismo `contenido` (ver informes.py::generar_pdf), nunca se
    pre-genera ni se sube a Storage -- asi una version vieja y una
    nueva se descargan exactamente igual, sin archivos huerfanos que
    limpiar.

    Reutiliza EXCLUSIVAMENTE los motores ya construidos para calcular
    `contenido` (kpi.py, inteligencia.py, optimizacion.py,
    centro_control.py) -- este modelo no calcula nada, solo persiste.
    """

    __tablename__ = "informes_pauta"

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresas.id"), nullable=False, index=True)
    usuario_id = db.Column(db.String(36), db.ForeignKey("usuarios.id"), nullable=True)
    cuenta_publicitaria_id = db.Column(db.Integer, db.ForeignKey("entidades_publicitarias.id"), nullable=False)

    tipo = db.Column(db.String(20), nullable=False)  # ver TIPOS_INFORME_PAUTA
    titulo = db.Column(db.String(200), nullable=True)

    periodo_clave = db.Column(db.String(30), nullable=False)
    fecha_inicio = db.Column(db.Date, nullable=False)
    fecha_fin = db.Column(db.Date, nullable=False)
    tipo_comparacion = db.Column(db.String(30), nullable=False, default="periodo_anterior")

    # campana_ids/audiencia_ids/objetivo -- filtros opcionales del Paso
    # 15 punto 2, guardados tal como se pidieron (nunca se reinfieren
    # despues).
    filtros = db.Column(db.JSON, nullable=True)

    # Version dentro del MISMO grupo (empresa+cuenta+tipo+fechas+
    # comparacion+filtros) -- ver informes.py::_siguiente_version.
    version = db.Column(db.Integer, nullable=False, default=1)

    contenido = db.Column(db.JSON, nullable=True)
    resumen_generado_por = db.Column(db.String(10), nullable=True)  # "claude" | "reglas"

    estado = db.Column(db.String(10), nullable=False, default="listo")
    error_mensaje = db.Column(db.Text, nullable=True)

    # Paso 16, punto 16: agrupar el historial en "Recientes" y
    # "Favoritos" -- un simple marcador manual, nunca una clasificacion
    # automatica ni un calculo nuevo.
    favorito = db.Column(db.Boolean, nullable=False, default=False)

    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    empresa = db.relationship("Empresa")
    cuenta_publicitaria = db.relationship("EntidadPublicitaria")

    def __repr__(self):
        return f"<InformePauta {self.id} {self.tipo} empresa={self.empresa_id} v{self.version}>"
