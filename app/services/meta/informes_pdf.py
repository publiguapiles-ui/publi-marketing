"""Generación de PDF estructurado para los informes de pauta (Paso 15,
punto 16).

Usa reportlab (Platypus: párrafos, tablas y gráficos vectoriales reales
via reportlab.graphics) -- nunca una captura de pantalla del HTML. Lee
EXCLUSIVAMENTE el `contenido` ya calculado y persistido en
InformePauta (ver informes.py) -- este archivo no vuelve a calcular
ningún KPI ni a consultar la base de datos, solo da formato.

Se genera BAJO DEMANDA en cada descarga (no se pre-genera ni se sube a
Storage, ver informe_pauta.py) -- barato porque `contenido` ya es un
dict simple, sin ninguna llamada a Meta ni a Claude en este paso.
"""

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_ESTILOS = getSampleStyleSheet()
_ESTILO_MARCA = ParagraphStyle("Marca", parent=_ESTILOS["Normal"], fontSize=10, textColor=colors.HexColor("#6b7280"))
_ESTILO_TITULO = ParagraphStyle("TituloInforme", parent=_ESTILOS["Title"], fontSize=20, spaceAfter=4)
_ESTILO_SUBTITULO = ParagraphStyle("Subtitulo", parent=_ESTILOS["Normal"], fontSize=11, textColor=colors.HexColor("#374151"))
_ESTILO_SECCION = ParagraphStyle("Seccion", parent=_ESTILOS["Heading2"], spaceBefore=14, spaceAfter=6)
_ESTILO_SUBSECCION = ParagraphStyle("Subseccion", parent=_ESTILOS["Heading3"], spaceBefore=8, spaceAfter=4)
_ESTILO_CUERPO = _ESTILOS["Normal"]
_ESTILO_NOTA = ParagraphStyle("Nota", parent=_ESTILOS["Normal"], fontSize=9, textColor=colors.HexColor("#6b7280"))

_COLOR_CABECERA_TABLA = colors.HexColor("#1f2937")
_COLOR_FILA_ALT = colors.HexColor("#f3f4f6")


def _formatear_valor(valor):
    return "No disponible" if valor is None else str(valor)


def _p(texto, estilo=None):
    return Paragraph(texto, estilo or _ESTILO_CUERPO)


def _tabla(cabeceras, filas, anchos=None):
    datos = [cabeceras] + filas
    tabla = Table(datos, colWidths=anchos, repeatRows=1)
    estilo = [
        ("BACKGROUND", (0, 0), (-1, 0), _COLOR_CABECERA_TABLA),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _COLOR_FILA_ALT]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    tabla.setStyle(TableStyle(estilo))
    return tabla


# --- Gráficos vectoriales (reportlab.graphics, no una imagen) --------------------------

def _grafico_barras(titulo, etiquetas, valores, color="#2563eb"):
    """Dibuja las barras a mano con formas primitivas
    (reportlab.graphics.shapes: Drawing/Rect/String) -- deliberadamente
    NO usa reportlab.graphics.charts.barcharts (VerticalBarChart), cuyo
    subsistema de ejes/leyendas trae mucho mas codigo del que esta
    pantalla necesita y se observo inestable bajo el contenedor de
    produccion. La misma matematica ya usada en las versiones SVG del
    navegador (ver datos_meta_informes.js), aqui en coordenadas PDF."""
    from reportlab.graphics.shapes import Drawing, Rect, String

    valores_validos = [v for v in valores if v is not None]
    if not valores_validos or max(valores_validos) <= 0:
        return None

    ancho, alto = 480, 190
    margen_izq, margen_inf, margen_sup = 10, 34, 20
    alto_barras = alto - margen_inf - margen_sup
    ancho_barras = ancho - margen_izq * 2

    dibujo = Drawing(ancho, alto)
    dibujo.add(String(0, alto - 12, titulo, fontSize=10, fillColor=colors.HexColor("#1f2937")))

    n = len(valores)
    paso = ancho_barras / n if n else 0
    ancho_barra = max(paso * 0.6, 2)
    maximo = max(valores_validos)
    color_rl = colors.HexColor(color)

    for i, v in enumerate(valores):
        if v is None:
            continue
        alto_barra = (v / maximo) * alto_barras if maximo else 0
        x = margen_izq + i * paso + (paso - ancho_barra) / 2
        dibujo.add(Rect(x, margen_inf, ancho_barra, max(alto_barra, 1), fillColor=color_rl, strokeColor=None))
        if n <= 12:
            etiqueta = (etiquetas[i] or "")[:10]
            dibujo.add(String(x, margen_inf - 10, etiqueta, fontSize=6.5, fillColor=colors.HexColor("#6b7280")))

    return dibujo


def _grafico_lineas(titulo, etiquetas, valores, color="#ea580c"):
    """Misma logica que _grafico_barras: PolyLine a mano, sin el
    subsistema reportlab.graphics.charts.lineplots."""
    from reportlab.graphics.shapes import Drawing, PolyLine, String

    puntos = [(i, v) for i, v in enumerate(valores) if v is not None]
    if len(puntos) < 2:
        return None

    ancho, alto = 480, 190
    margen_izq, margen_inf, margen_sup = 10, 20, 20
    alto_disponible = alto - margen_inf - margen_sup
    ancho_disponible = ancho - margen_izq * 2

    dibujo = Drawing(ancho, alto)
    dibujo.add(String(0, alto - 12, titulo, fontSize=10, fillColor=colors.HexColor("#1f2937")))

    n = len(valores)
    paso = ancho_disponible / (n - 1) if n > 1 else 0
    valores_puntos = [v for _i, v in puntos]
    minimo, maximo = min(valores_puntos), max(valores_puntos)
    rango = (maximo - minimo) or 1

    coordenadas = []
    for i, v in puntos:
        x = margen_izq + i * paso
        y = margen_inf + ((v - minimo) / rango) * alto_disponible
        coordenadas.extend([x, y])

    dibujo.add(PolyLine(coordenadas, strokeColor=colors.HexColor(color), strokeWidth=2))
    return dibujo


# --- Secciones ----------------------------------------------------------------------

def _seccion_resumen(contenido):
    r = contenido["resumen"]
    bloques = [_p("Resumen ejecutivo", _ESTILO_SECCION)]
    bloques.append(_p(
        f"Durante el período analizado se invirtieron <b>{_formatear_valor(r['inversion'])} {r.get('moneda') or ''}</b> "
        f"y se obtuvieron <b>{_formatear_valor(r['resultados'])} resultados</b>, "
        f"a un costo promedio de <b>{_formatear_valor(r['costo_por_resultado'])} {r.get('moneda') or ''}</b> por resultado."
    ))
    if r.get("comparacion_texto"):
        bloques.append(_p(r["comparacion_texto"]))
    bloques.append(Spacer(1, 4))
    bloques.append(_p(f"<b>Conclusión:</b> {r['conclusion']}"))
    if r.get("aviso_claude"):
        bloques.append(_p(f"<i>Nota: no se pudo generar el resumen con Claude ({r['aviso_claude']}); se muestra el resumen generado automáticamente.</i>", _ESTILO_NOTA))
    return bloques


def _seccion_kpis(contenido):
    etiquetas = contenido["etiquetas_kpi"]
    filas = [[etiquetas.get(c, c), _formatear_valor(contenido["kpis"].get(c))] for c in contenido["claves_kpi"] if contenido["kpis"].get(c) is not None]
    if not filas:
        return [_p("KPI", _ESTILO_SECCION), _p("No hay KPI disponibles para este período.")]
    return [_p("KPI del período", _ESTILO_SECCION), _tabla(["KPI", "Valor"], filas, anchos=[9 * cm, 6 * cm])]


def _seccion_comparacion(contenido):
    comp = contenido.get("comparacion_periodos")
    if comp is None:
        return []
    etiquetas = contenido["etiquetas_kpi"]
    filas = []
    for clave in contenido["claves_kpi"]:
        actual = comp["periodo_actual"]["kpis"].get(clave)
        anterior = comp["periodo_anterior"]["kpis"].get(clave)
        variacion = comp["variacion_porcentual"].get(clave)
        if actual is None and anterior is None:
            continue
        variacion_texto = "—" if variacion is None else f"{'+' if variacion > 0 else ''}{variacion}%"
        filas.append([etiquetas.get(clave, clave), _formatear_valor(actual), _formatear_valor(anterior), variacion_texto])
    if not filas:
        return []
    return [
        _p("Comparación con el período de referencia", _ESTILO_SECCION),
        _tabla(["KPI", "Período actual", "Período comparado", "Variación"], filas, anchos=[5.5 * cm, 3.3 * cm, 3.3 * cm, 3 * cm]),
    ]


def _seccion_campanas(contenido):
    bloques = [_p("Campañas", _ESTILO_SECCION)]
    filas = [
        [c["nombre"], c["estado"] or "—", _formatear_valor(c["kpis"].get("spend")), _formatear_valor(c["kpis"].get("resultados")),
         _formatear_valor(c["kpis"].get("costo_por_resultado")), _formatear_valor(c["kpis"].get("ctr")), _formatear_valor(c["kpis"].get("roas"))]
        for c in contenido["campanas"]
    ]
    if filas:
        bloques.append(_tabla(
            ["Campaña", "Estado", "Inversión", "Resultados", "Costo/Resultado", "CTR", "ROAS"], filas,
            anchos=[3.6 * cm, 1.8 * cm, 2 * cm, 1.8 * cm, 2.4 * cm, 1.5 * cm, 1.5 * cm],
        ))
    else:
        bloques.append(_p("No hay campañas sincronizadas para este período."))

    if contenido.get("mejores_campanas"):
        bloques.append(_p("Mejores campañas", _ESTILO_SUBSECCION))
        bloques.append(_p(", ".join(c["nombre"] for c in contenido["mejores_campanas"])))
    if contenido.get("campanas_atencion"):
        bloques.append(_p("Campañas que necesitan atención", _ESTILO_SUBSECCION))
        bloques.append(_p(", ".join(c["nombre"] for c in contenido["campanas_atencion"])))
    return bloques


def _seccion_audiencias(contenido):
    audiencias = contenido.get("audiencias")
    if not audiencias:
        return []
    filas = [
        [s["nombre"], s.get("campana_nombre") or "—", _formatear_valor(s["kpis"].get("spend")),
         _formatear_valor(s["kpis"].get("resultados")), _formatear_valor(s["kpis"].get("costo_por_resultado")), _formatear_valor(s["kpis"].get("ctr"))]
        for s in audiencias["segmentos"]
    ]
    bloques = [_p("Audiencias", _ESTILO_SECCION)]
    bloques.append(_tabla(["Audiencia", "Campaña", "Inversión", "Resultados", "Costo/Resultado", "CTR"], filas, anchos=[3.5 * cm, 3 * cm, 2 * cm, 2 * cm, 2.5 * cm, 1.7 * cm]))
    return bloques


def _seccion_diagnostico(contenido):
    diag = contenido.get("diagnostico")
    if not diag:
        return []
    bloques = [_p("Diagnóstico", _ESTILO_SECCION)]
    for titulo, clave in [("Qué funcionó", "que_funciono"), ("Qué empeoró", "que_empeoro"), ("Qué cambió", "que_cambio"), ("Qué requiere atención", "que_requiere_atencion")]:
        items = diag.get(clave) or []
        bloques.append(_p(titulo, _ESTILO_SUBSECCION))
        bloques.append(_p("<br/>".join(f"• {i}" for i in items) if items else "(nada destacable con los datos y umbrales actuales)"))
    return bloques


def _seccion_oportunidades(contenido):
    oportunidades = contenido.get("oportunidades") or []
    bloques = [_p("Oportunidades", _ESTILO_SECCION)]
    if not oportunidades:
        bloques.append(_p("No se detectó ninguna oportunidad con los datos y umbrales actuales para este período."))
        return bloques
    for o in oportunidades:
        bloques.append(_p(f"<b>{o['entidad_nombre']}</b> — {o['prioridad'].upper()}", _ESTILO_SUBSECCION))
        bloques.append(_p(f"<b>Qué detectamos:</b> {o['que_paso']}"))
        bloques.append(_p(f"<b>Evidencia:</b> {o['evidencia']}"))
        bloques.append(_p(f"<b>Recomendación:</b> {o['recomendacion']}"))
        bloques.append(_p(f"<b>Riesgo:</b> {o['riesgo']}"))
        bloques.append(Spacer(1, 4))
    return bloques


def _seccion_recomendaciones(contenido):
    recomendaciones = contenido.get("recomendaciones") or []
    bloques = [_p("Recomendaciones para el siguiente período", _ESTILO_SECCION)]
    if not recomendaciones:
        bloques.append(_p("No hay recomendaciones adicionales con los datos actuales."))
        return bloques
    for i, texto in enumerate(recomendaciones, 1):
        bloques.append(_p(f"{i}. {texto}"))
    return bloques


def _seccion_plan_accion(contenido):
    plan = contenido.get("plan_accion") or []
    if not plan:
        return []
    filas = [[p["prioridad_etiqueta"], p["accion"], p["motivo"], p["responsable"], p["estado"]] for p in plan]
    return [
        _p("Plan de acción", _ESTILO_SECCION),
        _tabla(["Prioridad", "Acción", "Motivo", "Responsable", "Estado"], filas, anchos=[2 * cm, 4.5 * cm, 5 * cm, 2.5 * cm, 2 * cm]),
    ]


def _seccion_graficos(contenido):
    bloques = [_p("Gráficos", _ESTILO_SECCION)]
    hubo_grafico = False

    campanas = contenido.get("campanas") or []
    if campanas:
        grafico = _grafico_barras("Inversión por campaña", [c["nombre"] for c in campanas], [c["kpis"].get("spend") for c in campanas])
        if grafico:
            bloques.append(grafico)
            bloques.append(Spacer(1, 10))
            hubo_grafico = True

    serie = contenido.get("serie_diaria") or []
    if serie:
        grafico = _grafico_lineas("Evolución del costo por resultado", [d["fecha"] for d in serie], [d.get("costo_por_resultado") for d in serie])
        if grafico:
            bloques.append(grafico)
            hubo_grafico = True

    if not hubo_grafico:
        bloques.append(_p("Sin datos suficientes para generar gráficos en este período."))
    return bloques


_CONSTRUCTORES_SECCION = {
    "resumen": _seccion_resumen,
    "kpis": _seccion_kpis,
    "comparacion": _seccion_comparacion,
    "campanas": _seccion_campanas,
    "audiencias": _seccion_audiencias,
    "diagnostico": _seccion_diagnostico,
    "oportunidades": _seccion_oportunidades,
    "recomendaciones": _seccion_recomendaciones,
    "plan_accion": _seccion_plan_accion,
    "graficos": _seccion_graficos,
}


def generar_pdf(informe, contenido, empresa_nombre, modo="interno"):
    """Bytes del PDF, generado ESTRUCTURADAMENTE (Platypus: párrafos,
    tablas, gráficos vectoriales) a partir de `contenido` -- nunca una
    captura de pantalla. `contenido` ya viene recortado a las secciones
    del modo pedido (ver informes.py::contenido_para_modo)."""
    buffer = BytesIO()
    documento = SimpleDocTemplate(
        buffer, pagesize=letter,
        topMargin=1.8 * cm, bottomMargin=1.8 * cm, leftMargin=1.8 * cm, rightMargin=1.8 * cm,
        title=informe.titulo or contenido["titulo"], author="Publi Marketing",
    )

    historia = []
    historia.append(_p("PUBLI MARKETING", _ESTILO_MARCA))
    historia.append(_p(contenido["titulo"], _ESTILO_TITULO))
    historia.append(_p(f"Cliente: {empresa_nombre}", _ESTILO_SUBTITULO))
    historia.append(_p(f"Cuenta publicitaria: {informe.cuenta_publicitaria.nombre or informe.cuenta_publicitaria.id_externo}", _ESTILO_SUBTITULO))
    historia.append(_p(f"Período: {informe.fecha_inicio.isoformat()} a {informe.fecha_fin.isoformat()}", _ESTILO_SUBTITULO))
    historia.append(_p(f"Generado el {informe.creado_en.strftime('%d/%m/%Y %H:%M')} · Versión #{informe.version} · Modo {'cliente' if modo == 'cliente' else 'interno'}", _ESTILO_SUBTITULO))
    historia.append(Spacer(1, 10))

    for clave in contenido["secciones"]:
        constructor = _CONSTRUCTORES_SECCION.get(clave)
        if constructor:
            historia.extend(constructor(contenido))

    documento.build(historia)
    return buffer.getvalue()
