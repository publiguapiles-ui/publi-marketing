(function () {
  // Analisis de audiencias (Paso 5). No calcula ningun KPI -- solo
  // formatea y muestra lo que devuelve app/services/meta/analisis.py
  // via /datos-meta/audiencias y /datos-meta/audiencias/datos.

  const MONEDA_CLAVES = ["spend", "cpc", "cpm", "valor_conversion", "costo_por_resultado"];
  const PORCENTAJE_CLAVES = ["ctr", "tasa_conversion"];

  const COLUMNAS = [
    { clave: "spend", etiqueta: "Gasto" },
    { clave: "resultados", etiqueta: "Resultados" },
    { clave: "costo_por_resultado", etiqueta: "Costo por resultado" },
    { clave: "ctr", etiqueta: "CTR" },
    { clave: "cpm", etiqueta: "CPM" },
    { clave: "roas", etiqueta: "ROAS" },
  ];

  function formatearNumero(valor, decimales) {
    return Number(valor).toLocaleString("es-CR", { minimumFractionDigits: decimales, maximumFractionDigits: decimales });
  }

  function formatearKpi(clave, valor) {
    if (valor === null || valor === undefined) return "No disponible";
    if (MONEDA_CLAVES.indexOf(clave) !== -1) return formatearNumero(valor, 2);
    if (PORCENTAJE_CLAVES.indexOf(clave) !== -1) return `${formatearNumero(valor, 2)}%`;
    if (clave === "roas") return `${formatearNumero(valor, 2)}x`;
    return formatearNumero(valor, 0);
  }

  function crear(etiqueta, clases, texto) {
    const el = document.createElement(etiqueta);
    if (clases) el.className = clases;
    if (texto !== undefined) el.textContent = texto;
    return el;
  }

  function describirConfiguracion(t) {
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

  function renderSegmentos(datos) {
    const cont = document.getElementById("dm-tabla-segmentos");
    cont.innerHTML = "";
    const segmentos = datos.segmentos || [];
    if (!segmentos.length) {
      cont.appendChild(crear("p", "perfil-nota", "No hay conjuntos de anuncios sincronizados para este filtro."));
      return;
    }

    const tabla = crear("table", "dm-tabla-kpi");
    const thead = crear("thead");
    const filaCab = crear("tr");
    ["Conjunto", "Campaña", "Audiencia configurada", ...COLUMNAS.map((c) => c.etiqueta), "Resultado"].forEach((t) => filaCab.appendChild(crear("th", null, t)));
    thead.appendChild(filaCab);
    tabla.appendChild(thead);

    const tbody = crear("tbody");
    segmentos.forEach((fila) => {
      const tr = crear("tr");
      tr.appendChild(crear("td", null, fila.nombre));
      tr.appendChild(crear("td", null, fila.campana_nombre || "—"));
      tr.appendChild(crear("td", null, describirConfiguracion(fila.targeting)));
      COLUMNAS.forEach((c) => tr.appendChild(crear("td", null, formatearKpi(c.clave, fila.kpis[c.clave]))));
      const tdRend = crear("td");
      if (fila.es_mejor) tdRend.appendChild(crear("span", "dm-badge-mejor", "Mejor resultado"));
      if (fila.es_peor) tdRend.appendChild(crear("span", "dm-badge-peor", "Peor resultado"));
      tr.appendChild(tdRend);
      tbody.appendChild(tr);
    });
    tabla.appendChild(tbody);
    const envoltorio = crear("div", "dm-tabla-scroll");
    envoltorio.appendChild(tabla);
    cont.appendChild(envoltorio);
  }

  function renderOportunidades(datos) {
    const cont = document.getElementById("dm-oportunidades");
    cont.innerHTML = "";
    const oportunidades = datos.oportunidades || [];
    if (!oportunidades.length) {
      cont.appendChild(crear("p", "perfil-nota", "No se detectó ninguna oportunidad con los umbrales actuales para este período."));
      return;
    }
    const lista = crear("div", "dm-lista-oportunidades");
    oportunidades.forEach((o) => {
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

  function renderTodo(datos) {
    const mensaje = document.getElementById("dm-mensaje-error");
    mensaje.hidden = !datos.error;
    mensaje.textContent = datos.error || "";
    renderSegmentos(datos);
    renderOportunidades(datos);
  }

  async function aplicarFiltros() {
    const params = new URLSearchParams();
    const cuentaId = document.getElementById("dm-filtro-cuenta").value;
    if (cuentaId) params.set("cuenta_id", cuentaId);
    const periodo = document.getElementById("dm-filtro-periodo").value;
    params.set("periodo", periodo);
    if (periodo === "personalizado") {
      const fi = document.getElementById("dm-filtro-fecha-inicio").value;
      const ff = document.getElementById("dm-filtro-fecha-fin").value;
      if (!fi || !ff) return;
      params.set("fecha_inicio", fi);
      params.set("fecha_fin", ff);
    }

    const boton = document.querySelector('#dm-filtros button[type="submit"]');
    if (boton) { boton.disabled = true; boton.textContent = "Cargando..."; }
    try {
      const resp = await fetch(`${window.DM_AUDIENCIAS_DATOS_URL}?${params.toString()}`);
      const datos = await resp.json();
      renderTodo(datos);
      history.replaceState(null, "", `${window.DM_AUDIENCIAS_URL}?${params.toString()}`);
    } catch (err) {
      alert("Error de conexión al actualizar audiencias.");
    }
    if (boton) { boton.disabled = false; boton.textContent = "Aplicar filtros"; }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const datosIniciales = window.DM_AUDIENCIAS_INICIAL;
    if (!datosIniciales) return;
    renderTodo(datosIniciales);

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
    document.getElementById("dm-filtro-cuenta").addEventListener("change", aplicarFiltros);
  });
})();
