(function () {
  // Motor de inteligencia estrategica (Paso 8). No calcula ningun KPI --
  // solo formatea y muestra lo que devuelve app/services/meta/
  // inteligencia.py via /datos-meta/inteligencia y
  // /datos-meta/inteligencia/datos. Sin Claude/IA generativa.

  const MONEDA_CLAVES = ["spend", "cpc", "cpm", "valor_conversion", "costo_por_resultado"];
  const PORCENTAJE_CLAVES = ["ctr", "tasa_conversion"];

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

  function formatearVariacion(valor) {
    if (valor === null || valor === undefined) return "Sin período anterior comparable";
    const signo = valor > 0 ? "+" : "";
    return `${signo}${formatearNumero(valor, 1)}% vs. período anterior`;
  }

  const ETIQUETAS_CLASIFICACION = { bueno: "Bueno", atencion: "Atención", critico: "Crítico", sin_datos: "Sin datos" };
  const ETIQUETAS_CONFIANZA = { alta: "Confianza alta", media: "Confianza media", baja: "Confianza baja" };

  function crear(etiqueta, clases, texto) {
    const el = document.createElement(etiqueta);
    if (clases) el.className = clases;
    if (texto !== undefined) el.textContent = texto;
    return el;
  }

  function badgeConfianza(nivel) {
    return crear("span", `dm-confianza dm-confianza-${nivel}`, ETIQUETAS_CONFIANZA[nivel] || nivel);
  }

  function renderDiagnostico(datos) {
    const cont = document.getElementById("dm-diagnostico");
    cont.innerHTML = "";
    const diagnostico = datos.diagnostico;
    if (!diagnostico) {
      cont.appendChild(crear("p", "perfil-nota", "No hay diagnóstico disponible para este filtro."));
      return;
    }

    const resumen = crear("p", "perfil-nota", `${diagnostico.dias_con_datos} día(s) con datos reales en el período` + (diagnostico.cantidad_campanas ? ` · ${diagnostico.cantidad_campanas} campaña(s) analizadas` : "") + ".");
    cont.appendChild(resumen);

    const etiquetasKpi = datos.etiquetas_kpi || {};
    const claves = datos.claves_kpi || Object.keys(diagnostico.areas);

    const tabla = crear("table", "dm-tabla-kpi");
    const thead = crear("thead");
    const filaCab = crear("tr");
    ["Área", "Valor actual", "Variación", "Promedio de campañas", "Clasificación", "Confianza"].forEach((t) => filaCab.appendChild(crear("th", null, t)));
    thead.appendChild(filaCab);
    tabla.appendChild(thead);

    const tbody = crear("tbody");
    claves.forEach((clave) => {
      const area = diagnostico.areas[clave];
      if (!area) return;
      const tr = crear("tr");
      tr.appendChild(crear("td", null, etiquetasKpi[clave] || clave));
      tr.appendChild(crear("td", null, formatearKpi(clave, area.valor)));
      tr.appendChild(crear("td", null, formatearVariacion(area.variacion_pct)));
      tr.appendChild(crear("td", null, area.promedio_campanas === null || area.promedio_campanas === undefined ? "No disponible" : formatearKpi(clave, area.promedio_campanas)));
      const tdClas = crear("td");
      tdClas.appendChild(crear("span", `estado-badge estado-badge-${area.clasificacion}`, ETIQUETAS_CLASIFICACION[area.clasificacion] || area.clasificacion));
      tr.appendChild(tdClas);
      const tdConf = crear("td");
      tdConf.appendChild(badgeConfianza(area.confianza));
      tr.appendChild(tdConf);
      tbody.appendChild(tr);
    });
    tabla.appendChild(tbody);
    const envoltorio = crear("div", "dm-tabla-scroll");
    envoltorio.appendChild(tabla);
    cont.appendChild(envoltorio);
  }

  function renderOportunidades(datos) {
    const cont = document.getElementById("dm-oportunidades-estrategicas");
    cont.innerHTML = "";
    const oportunidades = datos.oportunidades || [];
    if (!oportunidades.length) {
      cont.appendChild(crear("p", "perfil-nota", "No se detectó ninguna oportunidad estratégica con los datos y umbrales actuales para este período."));
      return;
    }
    const lista = crear("div", "dm-lista-oportunidades");
    oportunidades.forEach((o) => {
      const card = crear("div", `dm-oportunidad dm-oportunidad-${o.impacto_potencial}`);
      const cab = crear("div", "dm-oportunidad-cabecera");
      const tituloCont = crear("div");
      tituloCont.appendChild(crear("strong", null, o.titulo));
      if (o.entidad_nombre) tituloCont.appendChild(crear("div", "perfil-nota", o.entidad_nombre));
      cab.appendChild(tituloCont);
      cab.appendChild(badgeConfianza(o.nivel_confianza));
      card.appendChild(cab);
      card.appendChild(crear("p", null, o.descripcion));
      card.appendChild(crear("p", "perfil-nota", `Evidencia: ${o.evidencia}`));
      lista.appendChild(card);
    });
    cont.appendChild(lista);
  }

  function renderAlertas(datos) {
    const cont = document.getElementById("dm-alertas");
    cont.innerHTML = "";
    const alertas = datos.alertas || [];
    if (!alertas.length) {
      cont.appendChild(crear("p", "perfil-nota", "No se detectó ninguna alerta para este período."));
      return;
    }
    const lista = crear("div", "dm-lista-alertas");
    alertas.forEach((a) => {
      const card = crear("div", `dm-alerta dm-alerta-${a.severidad}`);
      const cab = crear("div", "dm-alerta-cabecera");
      const tituloCont = crear("div");
      tituloCont.appendChild(crear("strong", null, a.entidad_nombre || "Cuenta"));
      cab.appendChild(tituloCont);
      cab.appendChild(crear("span", `dm-badge-nivel dm-badge-nivel-${a.severidad === "critico" ? "alto" : a.severidad}`, a.severidad));
      card.appendChild(cab);
      card.appendChild(crear("p", null, a.que_ocurrio));
      lista.appendChild(card);
    });
    cont.appendChild(lista);
  }

  function renderTodo(datos) {
    const mensaje = document.getElementById("dm-mensaje-error");
    mensaje.hidden = !datos.error;
    mensaje.textContent = datos.error || "";
    if (datos.error) {
      document.getElementById("dm-diagnostico").innerHTML = "";
      document.getElementById("dm-oportunidades-estrategicas").innerHTML = "";
      document.getElementById("dm-alertas").innerHTML = "";
      return;
    }
    renderDiagnostico(datos);
    renderOportunidades(datos);
    renderAlertas(datos);
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
      const resp = await fetch(`${window.DM_INTELIGENCIA_DATOS_URL}?${params.toString()}`);
      const datos = await resp.json();
      renderTodo(datos);
      history.replaceState(null, "", `${window.DM_INTELIGENCIA_URL}?${params.toString()}`);
    } catch (err) {
      alert("Error de conexión al actualizar la inteligencia de cuenta.");
    }
    if (boton) { boton.disabled = false; boton.textContent = "Aplicar filtros"; }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const datosIniciales = window.DM_INTELIGENCIA_INICIAL;
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
