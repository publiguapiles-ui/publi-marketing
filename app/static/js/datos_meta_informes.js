(function () {
  // Informes de pauta (Paso 15). Reutiliza la MISMA tecnica de
  // graficos SVG livianos de datos_meta_dashboard.js/
  // datos_meta_centro_control.js (Pasos 4 y 14) -- no se agrega
  // ninguna libreria grafica nueva. El resto de este archivo solo
  // maneja filtros (recarga de pagina) y el envio del formulario de
  // creacion (fetch POST con JSON), igual que el resto de Datos de Meta.

  function crear(etiqueta, clases) {
    const el = document.createElement(etiqueta);
    if (clases) el.className = clases;
    return el;
  }

  // --- Lista: filtros auto-submit --------------------------------------------------

  const formLista = document.getElementById("inf-filtros");
  if (formLista) {
    ["inf-cuenta", "inf-tipo"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.addEventListener("change", () => formLista.submit());
    });
  }

  // --- Nuevo informe -----------------------------------------------------------------

  const formCuenta = document.getElementById("inf-form-cuenta");
  if (formCuenta) {
    document.getElementById("inf-nuevo-cuenta").addEventListener("change", () => formCuenta.submit());
  }

  const selectPeriodo = document.getElementById("inf-periodo-nuevo");
  if (selectPeriodo) {
    const bloquePersonalizado = document.getElementById("inf-personalizado");
    selectPeriodo.addEventListener("change", () => {
      bloquePersonalizado.hidden = selectPeriodo.value !== "personalizado";
    });
  }

  const formCrear = document.getElementById("inf-form-crear");
  if (formCrear) {
    formCrear.addEventListener("submit", async (evento) => {
      evento.preventDefault();
      const errorEl = document.getElementById("inf-error");
      errorEl.hidden = true;

      const periodo = document.getElementById("inf-periodo-nuevo").value;
      const cuerpo = {
        cuenta_id: Number(document.getElementById("inf-cuenta-id-form").value),
        tipo: document.getElementById("inf-tipo-nuevo").value,
        periodo,
        tipo_comparacion: document.getElementById("inf-comparar-nuevo").value,
        campana_ids: Array.from(document.querySelectorAll(".inf-campana-check:checked")).map((el) => Number(el.value)),
        audiencia_ids: Array.from(document.querySelectorAll(".inf-audiencia-check:checked")).map((el) => Number(el.value)),
      };

      const objetivoEl = document.getElementById("inf-objetivo-nuevo");
      if (objetivoEl && objetivoEl.value) cuerpo.objetivo = objetivoEl.value;

      if (periodo === "personalizado") {
        const fi = document.getElementById("inf-fecha-inicio").value;
        const ff = document.getElementById("inf-fecha-fin").value;
        if (!fi || !ff) {
          errorEl.hidden = false;
          errorEl.textContent = "Selecciona ambas fechas del período personalizado.";
          return;
        }
        cuerpo.fecha_inicio = fi;
        cuerpo.fecha_fin = ff;
      }

      const claudeEl = document.getElementById("inf-generar-claude");
      if (claudeEl && claudeEl.checked) cuerpo.generar_resumen_claude = true;

      const boton = document.getElementById("inf-boton-crear");
      boton.disabled = true;
      boton.textContent = "Generando…";

      try {
        const resp = await fetch("/datos-meta/informes/crear", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo),
        });
        const datos = await resp.json();
        if (!datos.ok) {
          errorEl.hidden = false;
          errorEl.textContent = datos.error;
          boton.disabled = false;
          boton.textContent = "Generar informe";
          return;
        }
        window.location.href = `/datos-meta/informes/${datos.informe_id}`;
      } catch (err) {
        errorEl.hidden = false;
        errorEl.textContent = "Error de conexión al generar el informe.";
        boton.disabled = false;
        boton.textContent = "Generar informe";
      }
    });
  }

  // --- Graficos del detalle (misma tecnica SVG del Paso 4/14) -----------------------

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

  function renderGraficos(datos) {
    const cont = document.getElementById("inf-graficos");
    if (!cont) return;
    cont.innerHTML = "";

    const serie = (datos.serie_diaria || []).map((d) => ({ etiqueta: d.fecha, spend: d.spend, resultados: d.resultados, costo_por_resultado: d.costo_por_resultado }));

    const serieSpend = construirEjeSerie(serie.map((d) => ({ etiqueta: d.etiqueta, valor: d.spend })));
    const serieResultados = construirEjeSerie(serie.map((d) => ({ etiqueta: d.etiqueta, valor: d.resultados })));
    const hayInvResultados = serieSpend.some((p) => p.valor != null) || serieResultados.some((p) => p.valor != null);
    let contenidoInv = null;
    if (hayInvResultados) {
      contenidoInv = crear("div");
      contenidoInv.appendChild(construirLineas([serieSpend, serieResultados], ["#2563eb", "#16a34a"]));
      const leyenda = crear("div", "dm-grafico-leyenda");
      [["Inversión", "#2563eb"], ["Resultados", "#16a34a"]].forEach(([texto, color]) => {
        const span = crear("span");
        span.textContent = texto;
        span.style.setProperty("--color-leyenda", color);
        leyenda.appendChild(span);
      });
      contenidoInv.appendChild(leyenda);
    }
    cont.appendChild(tarjetaGrafico("Inversión vs. resultados", contenidoInv));

    const serieCosto = construirEjeSerie(serie.map((d) => ({ etiqueta: d.etiqueta, valor: d.costo_por_resultado })));
    const hayCosto = serieCosto.some((p) => p.valor != null);
    cont.appendChild(tarjetaGrafico("Evolución del costo por resultado", hayCosto ? construirLineas([serieCosto], ["#ea580c"]) : null));

    const campanas = datos.campanas || [];
    const serieRendimiento = construirEjeSerie(campanas.map((c) => ({ etiqueta: c.nombre, valor: c.kpis.costo_por_resultado })));
    const hayRendimiento = serieRendimiento.some((p) => p.valor != null);
    cont.appendChild(tarjetaGrafico("Rendimiento por campaña (costo por resultado)", hayRendimiento ? construirBarras(serieRendimiento, "#7c3aed") : null));

    const serieInversionCampana = construirEjeSerie(campanas.map((c) => ({ etiqueta: c.nombre, valor: c.kpis.spend })));
    const hayInversionCampana = serieInversionCampana.some((p) => p.valor != null);
    cont.appendChild(tarjetaGrafico("Distribución de inversión por campaña", hayInversionCampana ? construirBarras(serieInversionCampana, "#2563eb") : null));
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (window.INF_DATOS) renderGraficos(window.INF_DATOS);
  });
})();
