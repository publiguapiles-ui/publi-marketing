(function () {
  // Analisis de campana (Paso 5). Igual que el dashboard del Paso 4:
  // este archivo NUNCA calcula un KPI, solo formatea y dibuja lo que
  // ya vino de app/services/meta/analisis.py via /datos-meta/campanas/
  // <id> y /datos-meta/campanas/<id>/datos. Archivo independiente del
  // dashboard.js del Paso 4 -- no se toca ese archivo en este paso.

  const MONEDA_CLAVES = ["spend", "cpc", "cpm", "valor_conversion", "costo_por_resultado"];
  const PORCENTAJE_CLAVES = ["ctr", "tasa_conversion"];

  const TARJETAS_KPI = [
    "spend", "resultados", "costo_por_resultado", "reach", "impressions", "frequency",
    "ctr", "cpc", "cpm", "conversiones", "roas",
  ];

  const GRAFICOS_CONFIG = [
    { claves: ["spend"], titulo: "Inversión por día", tipo: "barra", color: "#2563eb" },
    { claves: ["resultados"], titulo: "Resultados por día", tipo: "barra", color: "#16a34a" },
    { claves: ["ctr"], titulo: "CTR", tipo: "linea", colores: ["#2563eb"] },
    { claves: ["cpm"], titulo: "CPM", tipo: "linea", colores: ["#7c3aed"] },
  ];

  const COLUMNAS_CONJUNTO = [
    { clave: "spend", etiqueta: "Gasto" },
    { clave: "resultados", etiqueta: "Resultados" },
    { clave: "costo_por_resultado", etiqueta: "Costo por resultado" },
    { clave: "ctr", etiqueta: "CTR" },
    { clave: "cpm", etiqueta: "CPM" },
    { clave: "cpc", etiqueta: "CPC" },
    { clave: "frequency", etiqueta: "Frecuencia" },
  ];

  const COLUMNAS_ANUNCIO = [
    { clave: "spend", etiqueta: "Gasto" },
    { clave: "reach", etiqueta: "Alcance" },
    { clave: "impressions", etiqueta: "Impresiones" },
    { clave: "ctr", etiqueta: "CTR" },
    { clave: "cpc", etiqueta: "CPC" },
    { clave: "cpm", etiqueta: "CPM" },
    { clave: "resultados", etiqueta: "Resultados" },
    { clave: "costo_por_resultado", etiqueta: "Costo por resultado" },
    { clave: "conversiones", etiqueta: "Conversiones" },
    { clave: "video_plays", etiqueta: "Reproducciones de video" },
    { clave: "thruplays", etiqueta: "ThruPlays" },
  ];

  let datosActuales = null;

  function formatearNumero(valor, decimales) {
    return Number(valor).toLocaleString("es-CR", { minimumFractionDigits: decimales, maximumFractionDigits: decimales });
  }

  function formatearKpi(clave, valor, moneda) {
    if (valor === null || valor === undefined) return "No disponible";
    if (MONEDA_CLAVES.indexOf(clave) !== -1) {
      const numero = formatearNumero(valor, 2);
      return moneda ? `${numero} ${moneda}` : numero;
    }
    if (PORCENTAJE_CLAVES.indexOf(clave) !== -1) return `${formatearNumero(valor, 2)}%`;
    if (clave === "roas") return `${formatearNumero(valor, 2)}x`;
    if (clave === "frequency" || clave === "frecuencia") return formatearNumero(valor, 2);
    return formatearNumero(valor, 0);
  }

  function formatearVariacion(variacion) {
    if (variacion === null || variacion === undefined) return { texto: "—", clase: "" };
    const signo = variacion > 0 ? "+" : "";
    const clase = variacion > 0 ? "dm-variacion-positiva" : (variacion < 0 ? "dm-variacion-negativa" : "");
    return { texto: `${signo}${formatearNumero(variacion, 1)}%`, clase };
  }

  function crear(etiqueta, clases, texto) {
    const el = document.createElement(etiqueta);
    if (clases) el.className = clases;
    if (texto !== undefined) el.textContent = texto;
    return el;
  }

  function agregarFila(dl, etiqueta, valor) {
    dl.appendChild(crear("dt", null, etiqueta));
    dl.appendChild(crear("dd", null, valor === null || valor === undefined || valor === "" ? "—" : String(valor)));
  }

  // --- Metadatos de la campaña ---------------------------------------------------

  function renderMetadata(datos) {
    document.getElementById("dm-campana-nombre").textContent = datos.campana.nombre;
    document.getElementById("dm-campana-subtitulo").textContent = `Análisis de campaña — ${datos.campana.estado || "estado desconocido"}`;

    const dl = document.getElementById("dm-campana-metadata");
    dl.innerHTML = "";
    agregarFila(dl, "Objetivo", datos.campana.objetivo);
    agregarFila(dl, "Estado", datos.campana.estado);
    agregarFila(dl, "Fecha de inicio (Meta)", datos.campana.fecha_inicio);
    agregarFila(dl, "Fecha de fin (Meta)", datos.campana.fecha_fin);
    agregarFila(dl, "Presupuesto diario (Meta)", datos.campana.presupuesto_diario_meta);
    agregarFila(dl, "Presupuesto total (Meta)", datos.campana.presupuesto_total_meta);
    agregarFila(dl, "Presupuesto restante (Meta)", datos.campana.presupuesto_restante_meta);
  }

  // --- Tarjetas de KPI + comparacion -----------------------------------------------

  function renderTarjetas(datos) {
    const cont = document.getElementById("dm-tarjetas-kpi");
    cont.innerHTML = "";
    const etiquetas = datos.etiquetas_kpi || {};
    const comparar = datos.filtros.comparar && datos.comparacion;

    TARJETAS_KPI.forEach((clave) => {
      const valor = datos.kpis[clave];
      const card = crear("div", "dm-card-kpi");
      card.appendChild(crear("div", "dm-card-kpi-etiqueta", etiquetas[clave] || clave));
      card.appendChild(crear("div", `dm-card-kpi-valor${valor === null || valor === undefined ? " dm-sin-dato" : ""}`, formatearKpi(clave, valor)));
      if (comparar) {
        const anterior = datos.comparacion.periodo_anterior.kpis[clave];
        const variacion = formatearVariacion(datos.comparacion.variacion_porcentual[clave]);
        const linea = crear("div", "dm-card-kpi-comparacion");
        linea.appendChild(document.createTextNode(`Anterior: ${formatearKpi(clave, anterior)} · `));
        linea.appendChild(crear("span", variacion.clase, variacion.texto));
        card.appendChild(linea);
      }
      cont.appendChild(card);
    });
  }

  function renderComparacion(datos) {
    const seccion = document.getElementById("dm-seccion-comparacion");
    const cont = document.getElementById("dm-tabla-comparacion");
    const activa = datos.filtros.comparar && datos.comparacion;
    seccion.hidden = !activa;
    cont.innerHTML = "";
    if (!activa) return;

    const etiquetas = datos.etiquetas_kpi || {};
    const tabla = crear("table", "dm-tabla-kpi");
    const thead = crear("thead");
    const filaCab = crear("tr");
    ["KPI", "Período actual", "Período anterior", "Variación"].forEach((t) => filaCab.appendChild(crear("th", null, t)));
    thead.appendChild(filaCab);
    tabla.appendChild(thead);

    const tbody = crear("tbody");
    (datos.claves_kpi || []).forEach((clave) => {
      const actual = datos.comparacion.periodo_actual.kpis[clave];
      const anterior = datos.comparacion.periodo_anterior.kpis[clave];
      const variacion = formatearVariacion(datos.comparacion.variacion_porcentual[clave]);
      const fila = crear("tr");
      fila.appendChild(crear("td", null, etiquetas[clave] || clave));
      fila.appendChild(crear("td", null, formatearKpi(clave, actual)));
      fila.appendChild(crear("td", null, formatearKpi(clave, anterior)));
      const tdVar = crear("td");
      tdVar.appendChild(crear("span", variacion.clase, variacion.texto));
      fila.appendChild(tdVar);
      tbody.appendChild(fila);
    });
    tabla.appendChild(tbody);
    const envoltorio = crear("div", "dm-tabla-scroll");
    envoltorio.appendChild(tabla);
    cont.appendChild(envoltorio);
  }

  // --- Graficos SVG (mismo enfoque liviano que el dashboard) -----------------------

  function construirLineas(series, colores) {
    const ancho = 600, alto = 160, margen = 24;
    const todos = series.flat().filter((p) => p.valor !== null && p.valor !== undefined).map((p) => p.valor);
    const max = Math.max(...todos, 0);
    const min = Math.min(...todos, 0);
    const rango = (max - min) || 1;
    const n = series[0].length;
    const paso = n > 1 ? (ancho - margen * 2) / (n - 1) : 0;
    const coordX = (i) => margen + i * paso;
    const coordY = (v) => alto - margen - ((v - min) / rango) * (alto - margen * 2);

    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${ancho} ${alto}`);
    svg.setAttribute("preserveAspectRatio", "none");

    series.forEach((serie, si) => {
      const color = colores[si % colores.length];
      const validos = serie.filter((p) => p.valor !== null && p.valor !== undefined);
      if (!validos.length) return;
      const polyline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
      polyline.setAttribute("class", "dm-grafico-svg-linea");
      polyline.setAttribute("stroke", color);
      polyline.setAttribute("points", validos.map((p) => `${coordX(p.i)},${coordY(p.valor)}`).join(" "));
      svg.appendChild(polyline);
      validos.forEach((p) => {
        const circulo = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        circulo.setAttribute("cx", coordX(p.i));
        circulo.setAttribute("cy", coordY(p.valor));
        circulo.setAttribute("r", 3);
        circulo.setAttribute("fill", color);
        const titulo = document.createElementNS("http://www.w3.org/2000/svg", "title");
        titulo.textContent = `${p.fecha}: ${p.valor}`;
        circulo.appendChild(titulo);
        svg.appendChild(circulo);
      });
    });
    return svg;
  }

  function construirBarras(serie, color) {
    const ancho = 600, alto = 160, margen = 24;
    const n = serie.length;
    const paso = n > 0 ? (ancho - margen * 2) / n : 0;
    const anchoBarra = paso * 0.7;
    const validos = serie.filter((p) => p.valor !== null && p.valor !== undefined);
    const max = Math.max(...validos.map((p) => p.valor), 0);

    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${ancho} ${alto}`);
    svg.setAttribute("preserveAspectRatio", "none");

    validos.forEach((p) => {
      const alturaBarra = max > 0 ? (p.valor / max) * (alto - margen * 2) : 0;
      const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      rect.setAttribute("x", margen + p.i * paso + (paso - anchoBarra) / 2);
      rect.setAttribute("y", alto - margen - alturaBarra);
      rect.setAttribute("width", Math.max(anchoBarra, 1));
      rect.setAttribute("height", Math.max(alturaBarra, 1));
      rect.setAttribute("fill", color);
      const titulo = document.createElementNS("http://www.w3.org/2000/svg", "title");
      titulo.textContent = `${p.fecha}: ${p.valor}`;
      rect.appendChild(titulo);
      svg.appendChild(rect);
    });
    return svg;
  }

  function renderGraficos(datos) {
    const cont = document.getElementById("dm-graficos");
    cont.innerHTML = "";
    const serieDiaria = datos.serie_diaria || [];

    GRAFICOS_CONFIG.forEach((cfg) => {
      const card = crear("div", "dm-grafico-card");
      card.appendChild(crear("h3", null, cfg.titulo));
      const series = cfg.claves.map((clave) => serieDiaria.map((dia, i) => ({ fecha: dia.fecha, i, valor: dia[clave] })));
      const hayDatos = series.some((s) => s.some((p) => p.valor !== null && p.valor !== undefined));
      if (!hayDatos) {
        card.appendChild(crear("p", "perfil-nota", "Sin datos disponibles para este gráfico en el período seleccionado."));
      } else if (cfg.tipo === "barra") {
        card.appendChild(construirBarras(series[0], cfg.color));
      } else {
        card.appendChild(construirLineas(series, cfg.colores));
      }
      cont.appendChild(card);
    });
  }

  // --- Presupuesto ----------------------------------------------------------------

  function renderPresupuesto(datos) {
    const cont = document.getElementById("dm-presupuesto-campana");
    cont.innerHTML = "";
    const p = crear("p");
    p.appendChild(document.createTextNode("Gasto real de esta campaña (calculado desde las métricas sincronizadas de Meta): "));
    p.appendChild(crear("strong", null, formatearKpi("spend", datos.gasto_real)));
    cont.appendChild(p);

    if (!datos.presupuestos_asignados.length) {
      cont.appendChild(crear("p", "perfil-nota", "Ningún presupuesto propio (\"asignado\") vinculado a esta campaña todavía -- ver \"Presupuesto diario/total (Meta)\" arriba para lo que Meta reporta."));
      return;
    }
    const lista = crear("ul", "lista-simple dm-lista-presupuestos");
    datos.presupuestos_asignados.forEach((r) => {
      const li = crear("li");
      li.appendChild(crear("strong", null, r.nombre));
      li.appendChild(document.createTextNode(` — planificado: ${formatearNumero(r.monto, 2)} ${r.moneda} · gastado: ${formatearNumero(r.gasto_real, 2)} ${r.moneda} · `));
      li.appendChild(crear("span", r.excedido ? "dm-excedido" : "", `disponible: ${formatearNumero(r.disponible, 2)} ${r.moneda}`));
      if (r.porcentaje_usado !== null) li.appendChild(document.createTextNode(` (${formatearNumero(r.porcentaje_usado, 1)}% ejecutado)`));
      lista.appendChild(li);
    });
    cont.appendChild(lista);
  }

  // --- Tablas de conjuntos / anuncios ----------------------------------------------

  function renderTablaEntidades(contenedorId, filas, columnas, colDescripcion) {
    const cont = document.getElementById(contenedorId);
    cont.innerHTML = "";
    if (!filas.length) {
      cont.appendChild(crear("p", "perfil-nota", "No hay datos sincronizados en este nivel todavía."));
      return;
    }
    const tabla = crear("table", "dm-tabla-kpi");
    const thead = crear("thead");
    const filaCab = crear("tr");
    filaCab.appendChild(crear("th", null, "Nombre"));
    filaCab.appendChild(crear("th", null, "Estado"));
    if (colDescripcion) filaCab.appendChild(crear("th", null, colDescripcion));
    columnas.forEach((c) => filaCab.appendChild(crear("th", null, c.etiqueta)));
    filaCab.appendChild(crear("th", null, "Rendimiento"));
    thead.appendChild(filaCab);
    tabla.appendChild(thead);

    const tbody = crear("tbody");
    filas.forEach((fila) => {
      const tr = crear("tr");
      tr.appendChild(crear("td", null, fila.nombre));
      tr.appendChild(crear("td", null, fila.estado || "—"));
      if (colDescripcion) tr.appendChild(crear("td", null, fila._descripcion || "—"));
      columnas.forEach((c) => tr.appendChild(crear("td", null, formatearKpi(c.clave, fila.kpis[c.clave]))));
      const tdRend = crear("td");
      if (fila.es_mejor) tdRend.appendChild(crear("span", "dm-badge-mejor", "Mejor"));
      if (fila.es_peor) tdRend.appendChild(crear("span", "dm-badge-peor", "Peor"));
      tr.appendChild(tdRend);
      tbody.appendChild(tr);
    });
    tabla.appendChild(tbody);
    const envoltorio = crear("div", "dm-tabla-scroll");
    envoltorio.appendChild(tabla);
    cont.appendChild(envoltorio);
  }

  function describirTargeting(t) {
    if (!t || t.sin_datos) return "Meta no devolvió segmentación para este conjunto.";
    const partes = [];
    if (t.edades) partes.push(`Edades: ${t.edades}`);
    if (t.sexo) partes.push(`Sexo: ${t.sexo}`);
    if (t.ubicaciones) partes.push(t.ubicaciones);
    if (t.placements) partes.push(t.placements);
    if (t.dispositivos) partes.push(`Dispositivos: ${t.dispositivos}`);
    if (t.publicos_personalizados && t.publicos_personalizados.length) {
      partes.push(`Públicos personalizados: ${t.publicos_personalizados.map((p) => p.nombre).join(", ")}`);
    }
    if (t.intereses && t.intereses.length) partes.push(`Intereses: ${t.intereses.join(", ")}`);
    return partes.join(" | ");
  }

  function renderConjuntos(datos) {
    const filas = (datos.conjuntos || []).map((f) => ({ ...f, _descripcion: describirTargeting(f.targeting) }));
    renderTablaEntidades("dm-tabla-conjuntos", filas, COLUMNAS_CONJUNTO, "Audiencia configurada");
  }

  function renderAnuncios(datos) {
    renderTablaEntidades("dm-tabla-anuncios", datos.anuncios || [], COLUMNAS_ANUNCIO, null);
  }

  // --- Oportunidades ----------------------------------------------------------------

  function renderOportunidades(datos) {
    const cont = document.getElementById("dm-oportunidades");
    cont.innerHTML = "";
    const todas = [].concat(datos.oportunidades_campana || [], datos.oportunidades_conjuntos || [], datos.oportunidades_anuncios || []);
    if (!todas.length) {
      cont.appendChild(crear("p", "perfil-nota", "No se detectó ninguna oportunidad con los umbrales actuales para este período."));
      return;
    }
    const lista = crear("div", "dm-lista-oportunidades");
    todas.forEach((o) => {
      const card = crear("div", `dm-oportunidad dm-oportunidad-${o.nivel}`);
      const cab = crear("div", "dm-oportunidad-cabecera");
      cab.appendChild(crear("strong", null, o.entidad_nombre));
      cab.appendChild(crear("span", `dm-badge-nivel dm-badge-nivel-${o.nivel}`, o.nivel));
      card.appendChild(cab);
      card.appendChild(crear("p", null, o.que_detectamos));
      lista.appendChild(card);
    });
    cont.appendChild(lista);
  }

  // --- Orquestacion + filtros -------------------------------------------------------

  function renderTodo(datos) {
    renderMetadata(datos);
    renderTarjetas(datos);
    renderComparacion(datos);
    renderGraficos(datos);
    renderPresupuesto(datos);
    renderConjuntos(datos);
    renderAnuncios(datos);
    renderOportunidades(datos);
  }

  async function aplicarFiltros() {
    const params = new URLSearchParams();
    const periodo = document.getElementById("dm-filtro-periodo").value;
    params.set("periodo", periodo);
    if (periodo === "personalizado") {
      const fi = document.getElementById("dm-filtro-fecha-inicio").value;
      const ff = document.getElementById("dm-filtro-fecha-fin").value;
      if (!fi || !ff) return;
      params.set("fecha_inicio", fi);
      params.set("fecha_fin", ff);
    }
    if (document.getElementById("dm-filtro-comparar").checked) params.set("comparar", "1");

    const boton = document.querySelector('#dm-filtros button[type="submit"]');
    if (boton) { boton.disabled = true; boton.textContent = "Cargando..."; }
    try {
      const resp = await fetch(`${window.DM_CAMPANA_DATOS_URL}?${params.toString()}`);
      const datos = await resp.json();
      if (datos.ok === false) {
        alert(datos.error || "No se pudo cargar el análisis.");
      } else {
        datosActuales = datos;
        renderTodo(datos);
        history.replaceState(null, "", `${window.DM_CAMPANA_URL}?${params.toString()}`);
      }
    } catch (err) {
      alert("Error de conexión al actualizar el análisis.");
    }
    if (boton) { boton.disabled = false; boton.textContent = "Aplicar filtros"; }
  }

  document.addEventListener("DOMContentLoaded", () => {
    datosActuales = window.DM_CAMPANA_INICIAL;
    if (!datosActuales) return;
    renderTodo(datosActuales);

    document.getElementById("dm-filtros").addEventListener("submit", (evento) => {
      evento.preventDefault();
      aplicarFiltros();
    });

    const selectPeriodo = document.getElementById("dm-filtro-periodo");
    const bloquePersonalizado = document.getElementById("dm-filtro-personalizado");
    selectPeriodo.addEventListener("change", () => {
      bloquePersonalizado.hidden = selectPeriodo.value !== "personalizado";
      if (selectPeriodo.value !== "personalizado") aplicarFiltros();
    });
    document.getElementById("dm-filtro-comparar").addEventListener("change", aplicarFiltros);
  });
})();
