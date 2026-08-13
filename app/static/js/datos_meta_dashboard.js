(function () {
  // Dashboard visual de Datos de Meta (Paso 4). Este archivo NUNCA
  // calcula un KPI -- solo formatea y dibuja lo que ya vino calculado
  // del servidor (app/services/meta/kpi.py via /datos-meta/dashboard y
  // /datos-meta/dashboard/datos). Cambiar un filtro vuelve a pedir el
  // JSON y re-renderiza esta misma pantalla, sin recargar la app.

  const MONEDA_CLAVES = ["spend", "cpc", "cpm", "valor_conversion", "costo_por_resultado"];
  const PORCENTAJE_CLAVES = ["ctr", "tasa_conversion"];

  const TARJETAS_KPI = [
    "spend", "reach", "impressions", "frequency", "resultados", "costo_por_resultado",
    "ctr", "cpc", "cpm", "conversiones", "roas",
  ];

  const GRAFICOS_CONFIG = [
    { claves: ["spend"], titulo: "Inversión por día", tipo: "barra", color: "#2563eb" },
    { claves: ["resultados"], titulo: "Resultados por día", tipo: "barra", color: "#16a34a" },
    { claves: ["reach", "impressions"], titulo: "Alcance e impresiones", tipo: "linea", colores: ["#2563eb", "#f59e0b"] },
    { claves: ["ctr"], titulo: "CTR", tipo: "linea", colores: ["#2563eb"] },
    { claves: ["cpm"], titulo: "CPM", tipo: "linea", colores: ["#7c3aed"] },
    { claves: ["cpc"], titulo: "CPC", tipo: "linea", colores: ["#db2777"] },
    { claves: ["costo_por_resultado"], titulo: "Costo por resultado", tipo: "linea", colores: ["#ea580c"] },
    { claves: ["conversiones"], titulo: "Evolución de conversiones", tipo: "barra", color: "#16a34a" },
  ];

  const COLUMNAS_TABLA = [
    { clave: "spend", etiqueta: "Inversión" },
    { clave: "reach", etiqueta: "Alcance" },
    { clave: "impressions", etiqueta: "Impresiones" },
    { clave: "ctr", etiqueta: "CTR" },
    { clave: "cpc", etiqueta: "CPC" },
    { clave: "cpm", etiqueta: "CPM" },
    { clave: "resultados", etiqueta: "Resultados" },
    { clave: "costo_por_resultado", etiqueta: "Costo por resultado" },
    { clave: "roas", etiqueta: "ROAS" },
  ];

  let datosActuales = null;
  let ordenTabla = { clave: null, asc: false };

  function formatearNumero(valor, decimales) {
    return Number(valor).toLocaleString("es-CR", { minimumFractionDigits: decimales, maximumFractionDigits: decimales });
  }

  function formatearKpi(clave, valor, moneda) {
    if (valor === null || valor === undefined) return "No disponible";
    if (MONEDA_CLAVES.indexOf(clave) !== -1) {
      const numero = formatearNumero(valor, 2);
      return moneda ? `${numero} ${moneda}` : numero;
    }
    if (PORCENTAJE_CLAVES.indexOf(clave) !== -1) {
      return `${formatearNumero(valor, 2)}%`;
    }
    if (clave === "roas") {
      return `${formatearNumero(valor, 2)}x`;
    }
    if (clave === "frequency") {
      return formatearNumero(valor, 2);
    }
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

  // --- Tarjetas de KPI ---------------------------------------------------------

  function renderTarjetas(datos) {
    const cont = document.getElementById("dm-tarjetas-kpi");
    cont.innerHTML = "";
    const etiquetas = datos.etiquetas_kpi || {};
    const comparar = datos.filtros.comparar && datos.comparacion;

    TARJETAS_KPI.forEach((clave) => {
      const valor = datos.kpis[clave];
      const card = crear("div", "dm-card-kpi");
      card.appendChild(crear("div", "dm-card-kpi-etiqueta", etiquetas[clave] || clave));
      const valorTexto = formatearKpi(clave, valor, datos.moneda_cuenta);
      card.appendChild(crear("div", `dm-card-kpi-valor${valor === null || valor === undefined ? " dm-sin-dato" : ""}`, valorTexto));

      if (comparar) {
        const anterior = datos.comparacion.periodo_anterior.kpis[clave];
        const variacion = formatearVariacion(datos.comparacion.variacion_porcentual[clave]);
        const linea = crear("div", "dm-card-kpi-comparacion");
        linea.appendChild(document.createTextNode(`Anterior: ${formatearKpi(clave, anterior, datos.moneda_cuenta)} · `));
        const span = crear("span", variacion.clase, variacion.texto);
        linea.appendChild(span);
        card.appendChild(linea);
      }
      cont.appendChild(card);
    });

    // Presupuesto utilizado / restante (usa el presupuesto ESTRATEGICO
    // principal de la empresa, si existe -- nunca se inventa uno).
    const presupuesto = datos.presupuesto_principal;
    const cardUtilizado = crear("div", "dm-card-kpi");
    cardUtilizado.appendChild(crear("div", "dm-card-kpi-etiqueta", "Presupuesto utilizado"));
    const textoUtilizado = presupuesto && presupuesto.porcentaje_usado !== null ? `${formatearNumero(presupuesto.porcentaje_usado, 1)}%` : "No disponible";
    cardUtilizado.appendChild(crear("div", `dm-card-kpi-valor${presupuesto ? "" : " dm-sin-dato"}`, textoUtilizado));
    cont.appendChild(cardUtilizado);

    const cardRestante = crear("div", "dm-card-kpi");
    cardRestante.appendChild(crear("div", "dm-card-kpi-etiqueta", "Presupuesto restante"));
    const textoRestante = presupuesto ? `${formatearNumero(presupuesto.disponible, 2)} ${presupuesto.moneda}` : "No disponible";
    cardRestante.appendChild(crear("div", `dm-card-kpi-valor${presupuesto ? "" : " dm-sin-dato"}${presupuesto && presupuesto.excedido ? " dm-excedido" : ""}`, textoRestante));
    cont.appendChild(cardRestante);
  }

  // --- Comparación de periodos --------------------------------------------------

  function renderComparacion(datos) {
    const seccion = document.getElementById("dm-seccion-comparacion");
    const cont = document.getElementById("dm-tabla-comparacion");
    const activa = datos.filtros.comparar && datos.comparacion;
    seccion.hidden = !activa;
    if (!activa) {
      cont.innerHTML = "";
      return;
    }

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
      fila.appendChild(crear("td", null, formatearKpi(clave, actual, datos.moneda_cuenta)));
      fila.appendChild(crear("td", null, formatearKpi(clave, anterior, datos.moneda_cuenta)));
      const tdVar = crear("td");
      tdVar.appendChild(crear("span", variacion.clase, variacion.texto));
      fila.appendChild(tdVar);
      tbody.appendChild(fila);
    });
    tabla.appendChild(tbody);

    cont.innerHTML = "";
    const envoltorio = crear("div", "dm-tabla-scroll");
    envoltorio.appendChild(tabla);
    cont.appendChild(envoltorio);
  }

  // --- Gráficos SVG (livianos, sin librerías nuevas) ----------------------------

  function construirEjeSerie(serie) {
    return serie.map((dia, i) => ({ fecha: dia.fecha, i, valor: dia.valor }));
  }

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
        circulo.setAttribute("class", "dm-grafico-svg-punto");
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
      rect.setAttribute("class", "dm-grafico-svg-barra");
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
    const etiquetas = datos.etiquetas_kpi || {};

    GRAFICOS_CONFIG.forEach((cfg) => {
      const card = crear("div", "dm-grafico-card");
      card.appendChild(crear("h3", null, cfg.titulo));

      const series = cfg.claves.map((clave) => construirEjeSerie(serieDiaria.map((dia) => ({ fecha: dia.fecha, valor: dia[clave] }))));
      const hayDatos = series.some((s) => s.some((p) => p.valor !== null && p.valor !== undefined));

      if (!hayDatos) {
        card.appendChild(crear("p", "perfil-nota", "Sin datos disponibles para este gráfico en el período seleccionado."));
      } else if (cfg.tipo === "barra") {
        card.appendChild(construirBarras(series[0], cfg.color));
      } else {
        card.appendChild(construirLineas(series, cfg.colores));
        if (cfg.claves.length > 1) {
          const leyenda = crear("div", "dm-grafico-leyenda");
          cfg.claves.forEach((clave, i) => {
            const span = crear("span", null, etiquetas[clave] || clave);
            span.style.setProperty("--color-leyenda", cfg.colores[i]);
            leyenda.appendChild(span);
          });
          card.appendChild(leyenda);
        }
      }
      cont.appendChild(card);
    });
  }

  // --- Tabla de campañas (ordenable) --------------------------------------------

  function ordenarFilas(filas, orden) {
    if (!orden.clave) return filas;
    const conDato = filas.filter((f) => f.kpis[orden.clave] !== null && f.kpis[orden.clave] !== undefined);
    const sinDato = filas.filter((f) => f.kpis[orden.clave] === null || f.kpis[orden.clave] === undefined);
    conDato.sort((a, b) => (a.kpis[orden.clave] - b.kpis[orden.clave]) * (orden.asc ? 1 : -1));
    return conDato.concat(sinDato);
  }

  function renderTablaCampanas(datos) {
    const cont = document.getElementById("dm-tabla-campanas");
    const filas = datos.tabla_campanas || [];
    cont.innerHTML = "";

    if (!filas.length) {
      cont.appendChild(crear("p", "perfil-nota", "No hay campañas para los filtros seleccionados."));
      return;
    }

    const filasOrdenadas = ordenarFilas(filas.slice(), ordenTabla);

    const tabla = crear("table", "dm-tabla-kpi");
    const thead = crear("thead");
    const filaCab = crear("tr");
    filaCab.appendChild(crear("th", null, "Campaña"));
    filaCab.appendChild(crear("th", null, "Estado"));
    filaCab.appendChild(crear("th", null, "Objetivo"));
    COLUMNAS_TABLA.forEach((col) => {
      const indicador = ordenTabla.clave === col.clave ? (ordenTabla.asc ? " ▲" : " ▼") : "";
      const th = crear("th", null, col.etiqueta + indicador);
      th.setAttribute("data-ordenable", "");
      th.dataset.clave = col.clave;
      th.addEventListener("click", () => {
        if (ordenTabla.clave === col.clave) {
          ordenTabla = { clave: col.clave, asc: !ordenTabla.asc };
        } else {
          ordenTabla = { clave: col.clave, asc: false };
        }
        renderTablaCampanas(datosActuales);
      });
      filaCab.appendChild(th);
    });
    filaCab.appendChild(crear("th", null, "Rendimiento"));
    thead.appendChild(filaCab);
    tabla.appendChild(thead);

    const tbody = crear("tbody");
    filasOrdenadas.forEach((fila) => {
      const tr = crear("tr");
      tr.appendChild(crear("td", null, fila.nombre));
      tr.appendChild(crear("td", null, fila.estado || "—"));
      tr.appendChild(crear("td", null, fila.objetivo || "—"));
      COLUMNAS_TABLA.forEach((col) => {
        tr.appendChild(crear("td", null, formatearKpi(col.clave, fila.kpis[col.clave], datos.moneda_cuenta)));
      });
      const tdRendimiento = crear("td");
      if (fila.es_mejor) tdRendimiento.appendChild(crear("span", "dm-badge-mejor", "Mejor"));
      if (fila.es_peor) tdRendimiento.appendChild(crear("span", "dm-badge-peor", "Peor"));
      tr.appendChild(tdRendimiento);
      tbody.appendChild(tr);
    });
    tabla.appendChild(tbody);

    const envoltorio = crear("div", "dm-tabla-scroll");
    envoltorio.appendChild(tabla);
    cont.appendChild(envoltorio);
  }

  // --- Presupuesto de pauta ------------------------------------------------------

  function renderPresupuesto(datos) {
    const cont = document.getElementById("dm-presupuesto");
    cont.innerHTML = "";
    const presupuestos = datos.presupuestos || [];
    if (!presupuestos.length) {
      cont.appendChild(crear("p", "perfil-nota", "Ningún presupuesto de pauta definido todavía."));
      return;
    }
    const lista = crear("ul", "lista-simple dm-lista-presupuestos");
    presupuestos.forEach((r) => {
      const li = crear("li");
      li.appendChild(crear("strong", null, r.nombre));
      li.appendChild(document.createTextNode(` (${r.tipo === "estrategico" ? "Estratégico" : "Asignado"}) — planificado: ${formatearNumero(r.monto, 2)} ${r.moneda} · gastado: ${formatearNumero(r.gasto_real, 2)} ${r.moneda} · `));
      const spanDisponible = crear("span", r.excedido ? "dm-excedido" : "", `disponible: ${formatearNumero(r.disponible, 2)} ${r.moneda}`);
      li.appendChild(spanDisponible);
      if (r.porcentaje_usado !== null) {
        li.appendChild(document.createTextNode(` (${formatearNumero(r.porcentaje_usado, 1)}% ejecutado)`));
      }
      lista.appendChild(li);
    });
    cont.appendChild(lista);
  }

  // --- Orquestación ----------------------------------------------------------------

  function renderDashboard(datos) {
    const mensaje = document.getElementById("dm-dashboard-mensaje");
    mensaje.hidden = !datos.error_cuenta;
    mensaje.textContent = datos.error_cuenta || "";

    renderTarjetas(datos);
    renderComparacion(datos);
    renderGraficos(datos);
    renderTablaCampanas(datos);
    renderPresupuesto(datos);
  }

  function actualizarSelectCampanas(datos) {
    const select = document.getElementById("dm-filtro-campana");
    const actual = select.value;
    select.innerHTML = "";
    select.appendChild(crear("option", null, "Todas")).setAttribute("value", "");
    (datos.campanas_filtro || []).forEach((c) => {
      const opt = crear("option", null, c.nombre);
      opt.value = c.id;
      if (String(c.id) === actual) opt.selected = true;
      select.appendChild(opt);
    });
  }

  async function aplicarFiltros() {
    const params = new URLSearchParams();
    const cuentaId = document.getElementById("dm-filtro-cuenta").value;
    if (cuentaId) params.set("cuenta_id", cuentaId);
    const campanaId = document.getElementById("dm-filtro-campana").value;
    if (campanaId) params.set("campana_id", campanaId);
    const estado = document.getElementById("dm-filtro-estado").value;
    if (estado) params.set("estado", estado);
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
      const resp = await fetch(`${window.DM_DASHBOARD_DATOS_URL}?${params.toString()}`);
      const datos = await resp.json();
      datosActuales = datos;
      ordenTabla = { clave: null, asc: false };
      actualizarSelectCampanas(datos);
      renderDashboard(datos);
      history.replaceState(null, "", `${window.DM_DASHBOARD_URL}?${params.toString()}`);
    } catch (err) {
      alert("Error de conexión al actualizar el dashboard.");
    }
    if (boton) { boton.disabled = false; boton.textContent = "Aplicar filtros"; }
  }

  document.addEventListener("DOMContentLoaded", () => {
    datosActuales = window.DM_DASHBOARD_INICIAL;
    if (!datosActuales) return;
    renderDashboard(datosActuales);

    const form = document.getElementById("dm-filtros");
    form.addEventListener("submit", (evento) => {
      evento.preventDefault();
      aplicarFiltros();
    });

    const selectPeriodo = document.getElementById("dm-filtro-periodo");
    const bloquePersonalizado = document.getElementById("dm-filtro-personalizado");
    selectPeriodo.addEventListener("change", () => {
      bloquePersonalizado.hidden = selectPeriodo.value !== "personalizado";
      if (selectPeriodo.value !== "personalizado") aplicarFiltros();
    });

    ["dm-filtro-cuenta", "dm-filtro-campana", "dm-filtro-estado"].forEach((id) => {
      document.getElementById(id).addEventListener("change", aplicarFiltros);
    });
    document.getElementById("dm-filtro-comparar").addEventListener("change", aplicarFiltros);
  });
})();
