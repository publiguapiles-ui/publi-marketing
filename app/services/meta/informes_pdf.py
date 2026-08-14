"""Generación de PDF estructurado para los informes de pauta (Paso 15,
punto 16).

Usa reportlab (Platypus: párrafos, tablas y "gráficos" de barras
horizontales dibujados con Table/celdas de color) -- nunca una captura
de pantalla del HTML. Deliberadamente NUNCA usa reportlab.graphics
(Drawing/Rect/PolyLine ni los charts de alto nivel como
VerticalBarChart/LinePlot): se observó que su importación perezosa
causaba caídas intermitentes (503) del proceso en el contenedor de
producción -- ver _grafico_barras()/_grafico_lineas() para el detalle.
Lee EXCLUSIVAMENTE el `contenido` ya calculado y persistido en
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


# --- Gráficos vectoriales (SOLO reportlab.platypus.Table, nunca reportlab.graphics) -----
#
# Barras horizontales dibujadas como celdas de tabla con ancho
# proporcional al valor y fondo de color -- sigue siendo un grafico
# vectorial estructurado (nunca una imagen/captura), pero usa
# EXCLUSIVAMENTE Table/Paragraph, que ya son estables en produccion
# (las tablas de KPI/campañas de este mismo archivo las usan sin
# problema). reportlab.graphics (Drawing/Rect/PolyLine/los charts de
# alto nivel) se evita deliberadamente en todo este archivo: se
# observo que su importacion perezosa causaba caidas intermitentes
# del proceso en el contenedor de produccion (memoria/tiempo de carga
# de metricas de fuentes) -- un riesgo que no vale la pena para un
# grafico de barras simple.

_ANCHO_BARRA_MAXIMO = 8 * cm


def _grafico_barras(titulo, etiquetas, valores, color="#2563eb", max_filas=12):
    pares = [(e, v) for e, v in zip(etiquetas, valores) if v is not None]
    if not pares:
        return None
    pares = pares[:max_filas]
    maximo = max(v for _e, v in pares) or 1

    filas = []
    for etiqueta, valor in pares:
        ancho_barra = max((valor / maximo) * _ANCHO_BARRA_MAXIMO, 0.15 * cm)
        barra = Table([[""]], colWidths=[ancho_barra], rowHeights=[0.4 * cm])
        barra.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(color))]))
        filas.append([_p((etiqueta or "")[:26], _ESTILO_NOTA), barra, _p(_formatear_valor(round(valor, 2)), _ESTILO_NOTA)])

    tabla = Table(filas, colWidths=[4 * cm, _ANCHO_BARRA_MAXIMO + 0.3 * cm, 2.5 * cm])
    tabla.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    return [_p(titulo, _ESTILO_SUBSECCION), tabla]


def _grafico_lineas(titulo, etiquetas, valores, color="#ea580c", max_filas=15):
    """Misma tecnica de barras horizontales que _grafico_barras --
    para una serie diaria larga, muestra como maximo `max_filas` puntos
    espaciados uniformemente (nunca todos los dias a la vez, para que
    la tabla siga siendo legible)."""
    pares = [(e, v) for e, v in zip(etiquetas, valores) if v is not None]
    if len(pares) < 2:
        return None
    if len(pares) > max_filas:
        paso = len(pares) / max_filas
        pares = [pares[int(i * paso)] for i in range(max_filas)]
    return _grafico_barras(titulo, [p[0] for p in pares], [p[1] for p in pares], color=color, max_filas=max_filas)


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
            bloques.extend(grafico)
            bloques.append(Spacer(1, 10))
            hubo_grafico = True

    serie = contenido.get("serie_diaria") or []
    if serie:
        grafico = _grafico_lineas("Evolución del costo por resultado", [d["fecha"] for d in serie], [d.get("costo_por_resultado") for d in serie])
        if grafico:
            bloques.extend(grafico)
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
