(function () {
  // Centro de Control de Pauta (Paso 14). La pantalla es 100%
  // renderizada por el servidor (Jinja, igual que Optimizacion) --
  // este archivo hace: (1) recarga la pagina cuando cambia un filtro
  // (mismo patron que Optimizacion/Chat de Pauta) y (2) dibuja los
  // graficos de evolucion/por campana del KPI elegido en el selector,
  // reutilizando la MISMA tecnica SVG liviana ya usada en
  // datos_meta_dashboard.js (Paso 4) -- no se agrega ninguna libreria
  // grafica nueva. Todos los KPI ya venian en window.CC_DATOS
  // (serie_diaria y campanas traen el dict completo de KPI por dia/
  // entidad); el selector solo elige cual de esas claves graficar, sin
  // pedir datos nuevos al servidor.

  let kpiSeleccionado = null;

  function crear(etiqueta, clases) {
    const el = document.createElement(etiqueta);
    if (clases) el.className = clases;
    return el;
  }

  function construirEjeSerie(serie) {
    return serie.map((punto, i) => ({ etiqueta: punto.etiqueta, i, valor: punto.valor }));
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
        titulo.textContent = `${p.etiqueta}: ${p.valor}`;
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
      titulo.textContent = `${p.etiqueta}: ${p.valor}`;
      rect.appendChild(titulo);
      svg.appendChild(rect);
    });
    return svg;
  }

  function tarjetaGrafico(titulo, contenidoONulo) {
    const card = crear("div", "dm-grafico-card");
    card.appendChild(Object.assign(document.createElement("h3"), { textContent: titulo }));
    if (contenidoONulo) {
      card.appendChild(contenidoONulo);
    } else {
      const p = crear("p", "perfil-nota");
      p.textContent = "Sin datos disponibles para este gráfico en el período seleccionado.";
      card.appendChild(p);
    }
    return card;
  }

  function kpisConDatos(datos) {
    const claves = datos.claves_kpi || [];
    const serieDiaria = datos.serie_diaria || [];
    const campanas = datos.campanas || [];
    return claves.filter((clave) => {
      const enSerie = serieDiaria.some((d) => d[clave] !== null && d[clave] !== undefined);
      const enCampanas = campanas.some((c) => c.kpis && c.kpis[clave] !== null && c.kpis[clave] !== undefined);
      return enSerie || enCampanas;
    });
  }

  function etiquetaKpi(datos, clave) {
    const sencillas = datos.etiquetas_kpi_sencillas || {};
    const tecnicas = datos.etiquetas_kpi || {};
    return sencillas[clave] || tecnicas[clave] || clave;
  }

  function renderSelector(datos, disponibles) {
    const nav = document.getElementById("cc-grafico-selector");
    if (!nav) return;
    nav.innerHTML = "";
    disponibles.forEach((clave) => {
      const boton = crear("button", "cc-grafico-selector-item");
      boton.type = "button";
      boton.textContent = etiquetaKpi(datos, clave);
      if (clave === kpiSeleccionado) boton.classList.add("cc-grafico-activo");
      boton.addEventListener("click", () => {
        kpiSeleccionado = clave;
        renderSelector(datos, disponibles);
        renderPanel(datos, clave);
      });
      nav.appendChild(boton);
    });
  }

  function renderPanel(datos, clave) {
    const cont = document.getElementById("cc-graficos");
    if (!cont) return;
    cont.innerHTML = "";

    const etiqueta = etiquetaKpi(datos, clave);
    const serieDiaria = (datos.serie_diaria || []).map((d) => ({ etiqueta: d.fecha, valor: d[clave] }));
    const serieEvolucion = construirEjeSerie(serieDiaria);
    const hayEvolucion = serieEvolucion.some((p) => p.valor !== null && p.valor !== undefined);
    cont.appendChild(tarjetaGrafico(`${etiqueta} -- evolución diaria`, hayEvolucion ? construirLineas([serieEvolucion], ["#2563eb"]) : null));

    const campanas = datos.campanas || [];
    const seriePorCampana = construirEjeSerie(campanas.map((c) => ({ etiqueta: c.nombre, valor: c.kpis ? c.kpis[clave] : null })));
    const hayPorCampana = seriePorCampana.some((p) => p.valor !== null && p.valor !== undefined);
    cont.appendChild(tarjetaGrafico(`${etiqueta} -- por campaña`, hayPorCampana ? construirBarras(seriePorCampana, "#7c3aed") : null));
  }

  function renderGraficos(datos) {
    const disponibles = kpisConDatos(datos);
    if (!disponibles.length) {
      const nav = document.getElementById("cc-grafico-selector");
      if (nav) nav.innerHTML = "";
      const cont = document.getElementById("cc-graficos");
      if (cont) {
        cont.innerHTML = "";
        cont.appendChild(tarjetaGrafico("Gráficos", null));
      }
      return;
    }
    if (!kpiSeleccionado || disponibles.indexOf(kpiSeleccionado) === -1) {
      kpiSeleccionado = disponibles.indexOf("spend") !== -1 ? "spend" : disponibles[0];
    }
    renderSelector(datos, disponibles);
    renderPanel(datos, kpiSeleccionado);
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (window.CC_DATOS) renderGraficos(window.CC_DATOS);

    const form = document.getElementById("cc-filtros");
    if (!form) return;
    ["cc-cuenta", "cc-periodo", "cc-comparar-con", "cc-kpi-mejor-peor"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.addEventListener("change", () => form.submit());
    });
  });
})();
