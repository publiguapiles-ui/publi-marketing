(function () {
  // Proyectos estrategicos de campaña (Paso 9). No calcula ningun KPI
  // ni detecta ninguna oportunidad -- solo administra el plan (crear
  // proyecto/fases/secuencia/estado) y muestra el diagnostico que ya
  // devuelve app/services/meta/inteligencia.py (Paso 8) via
  // /datos-meta/proyectos-estrategicos/<id>/datos. Nunca crea ni
  // modifica nada en Meta.

  function crear(etiqueta, clases, texto) {
    const el = document.createElement(etiqueta);
    if (clases) el.className = clases;
    if (texto !== undefined) el.textContent = texto;
    return el;
  }

  const ETIQUETAS_CLASIFICACION = { bueno: "Bueno", atencion: "Atención", critico: "Crítico", sin_datos: "Sin datos" };
  const ETIQUETAS_CONFIANZA = { alta: "Confianza alta", media: "Confianza media", baja: "Confianza baja" };

  function badgeConfianza(nivel) {
    return crear("span", `dm-confianza dm-confianza-${nivel}`, ETIQUETAS_CONFIANZA[nivel] || nivel);
  }

  // --- Pagina de lista: creacion de proyecto ---------------------------------------

  function inicializarLista() {
    const form = document.getElementById("form-nuevo-proyecto");
    if (!form) return;

    form.addEventListener("submit", async (evento) => {
      evento.preventDefault();
      const datosForm = new FormData(form);
      const kpiSecundarios = Array.from(form.querySelector('select[name="kpi_secundarios"]').selectedOptions).map((o) => o.value);
      const payload = {
        nombre: datosForm.get("nombre"),
        objetivo: datosForm.get("objetivo"),
        kpi_principal: datosForm.get("kpi_principal"),
        kpi_secundarios: kpiSecundarios,
        presupuesto_total: datosForm.get("presupuesto_total"),
        moneda: datosForm.get("moneda"),
        fecha_inicio: datosForm.get("fecha_inicio"),
        fecha_fin: datosForm.get("fecha_fin"),
        resultado_objetivo: datosForm.get("resultado_objetivo"),
        cuenta_publicitaria_id: datosForm.get("cuenta_publicitaria_id") || null,
        restricciones: datosForm.get("restricciones"),
      };

      const mensaje = document.getElementById("nuevo-proyecto-mensaje");
      const boton = form.querySelector('button[type="submit"]');
      boton.disabled = true;
      try {
        const resp = await fetch(window.DM_PROYECTOS_CREAR_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const datos = await resp.json();
        if (!datos.ok) {
          mensaje.hidden = false;
          mensaje.textContent = datos.error;
          boton.disabled = false;
          return;
        }
        window.location.href = window.DM_PROYECTOS_DETALLE_URL_BASE.replace("__ID__", datos.proyecto_id);
      } catch (err) {
        mensaje.hidden = false;
        mensaje.textContent = "Error de conexión al crear el proyecto.";
        boton.disabled = false;
      }
    });
  }

  // --- Pagina de detalle: diagnostico -----------------------------------------------

  function formatearNumero(valor, decimales) {
    return Number(valor).toLocaleString("es-CR", { minimumFractionDigits: decimales, maximumFractionDigits: decimales });
  }

  const MONEDA_CLAVES = ["spend", "cpc", "cpm", "valor_conversion", "costo_por_resultado"];
  const PORCENTAJE_CLAVES = ["ctr", "tasa_conversion"];

  function formatearKpi(clave, valor) {
    if (valor === null || valor === undefined) return "No disponible";
    if (MONEDA_CLAVES.indexOf(clave) !== -1) return formatearNumero(valor, 2);
    if (PORCENTAJE_CLAVES.indexOf(clave) !== -1) return `${formatearNumero(valor, 2)}%`;
    if (clave === "roas") return `${formatearNumero(valor, 2)}x`;
    return formatearNumero(valor, 0);
  }

  function renderDiagnosticoAreas(diagnostico, etiquetasKpi) {
    const cont = document.getElementById("pe-diagnostico-areas");
    if (!cont) return;
    cont.innerHTML = "";
    if (!diagnostico) return;

    const tabla = crear("table", "dm-tabla-kpi");
    const thead = crear("thead");
    const filaCab = crear("tr");
    ["Área", "Valor actual", "Clasificación", "Confianza"].forEach((t) => filaCab.appendChild(crear("th", null, t)));
    thead.appendChild(filaCab);
    tabla.appendChild(thead);

    const tbody = crear("tbody");
    Object.keys(diagnostico.areas).forEach((clave) => {
      const area = diagnostico.areas[clave];
      const tr = crear("tr");
      tr.appendChild(crear("td", null, etiquetasKpi[clave] || clave));
      tr.appendChild(crear("td", null, formatearKpi(clave, area.valor)));
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

  function renderOportunidades(oportunidades, proyecto) {
    const cont = document.getElementById("pe-oportunidades");
    if (!cont) return;
    cont.innerHTML = "";
    if (!oportunidades || !oportunidades.length) {
      cont.appendChild(crear("p", "perfil-nota", "No se detectó ninguna oportunidad estratégica para este período."));
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

      const boton = crear("button", "boton-enlace", "Usar en proyecto");
      boton.type = "button";
      boton.addEventListener("click", () => usarOportunidadEnFase(o, proyecto));
      card.appendChild(boton);

      lista.appendChild(card);
    });
    cont.appendChild(lista);
  }

  function renderAlertas(alertas) {
    const cont = document.getElementById("pe-alertas");
    if (!cont) return;
    cont.innerHTML = "";
    if (!alertas || !alertas.length) {
      cont.appendChild(crear("p", "perfil-nota", "No se detectó ninguna alerta para este período."));
      return;
    }
    const lista = crear("div", "dm-lista-alertas");
    alertas.forEach((a) => {
      const card = crear("div", `dm-alerta dm-alerta-${a.severidad}`);
      const cab = crear("div", "dm-alerta-cabecera");
      cab.appendChild(crear("strong", null, a.entidad_nombre || "Cuenta"));
      cab.appendChild(crear("span", `dm-badge-nivel dm-badge-nivel-${a.severidad === "critico" ? "alto" : a.severidad}`, a.severidad));
      card.appendChild(cab);
      card.appendChild(crear("p", null, a.que_ocurrio));
      lista.appendChild(card);
    });
    cont.appendChild(lista);
  }

  function renderDiagnosticoCompleto(datos) {
    if (!datos.diagnostico) return;
    renderDiagnosticoAreas(datos.diagnostico.diagnostico, datos.etiquetas_kpi);
    renderOportunidades(datos.diagnostico.oportunidades, datos.proyecto);
    renderAlertas(datos.diagnostico.alertas);
  }

  // "Usar en proyecto" (Paso 9, punto 8): prellena el formulario de
  // nueva fase con lo que la oportunidad ya demostro -- el usuario
  // sigue teniendo que definir el presupuesto y confirmar, nunca se
  // crea ni asigna nada automaticamente.
  function usarOportunidadEnFase(oportunidad, proyecto) {
    const form = document.getElementById("form-nueva-fase");
    if (!form) return;
    form.querySelector('[name="nombre"]').value = oportunidad.titulo;
    form.querySelector('[name="objetivo"]').value = proyecto.objetivo || "";
    form.querySelector('[name="audiencia_descripcion"]').value = oportunidad.entidad_nombre || "";
    const kpiSelect = form.querySelector('[name="kpi_esperado"]');
    if (oportunidad.kpi_relacionado && Array.from(kpiSelect.options).some((o) => o.value === oportunidad.kpi_relacionado)) {
      kpiSelect.value = oportunidad.kpi_relacionado;
    }
    document.getElementById("pe-nueva-fase").scrollIntoView({ behavior: "smooth" });
  }

  async function aplicarFiltroDiagnostico() {
    const form = document.getElementById("pe-filtro-diagnostico");
    const periodo = form.querySelector('[name="periodo"]').value;
    const params = new URLSearchParams({ periodo });

    const boton = form.querySelector('button[type="submit"]');
    boton.disabled = true;
    try {
      const resp = await fetch(`${window.DM_PROYECTO_DATOS_URL}?${params.toString()}`);
      const datos = await resp.json();
      renderDiagnosticoCompleto(datos);
      history.replaceState(null, "", `${window.DM_PROYECTO_URL}?${params.toString()}`);
    } catch (err) {
      alert("Error de conexión al actualizar el diagnóstico.");
    }
    boton.disabled = false;
  }

  // --- Pagina de detalle: decisiones clave (memoria estrategica, Paso 3) ------------

  function formatearFecha(iso) {
    try {
      return new Date(iso).toLocaleString("es-CR", { dateStyle: "medium", timeStyle: "short" });
    } catch (err) {
      return iso;
    }
  }

  function renderDecisiones(decisiones) {
    const cont = document.getElementById("pe-lista-decisiones");
    if (!cont) return;
    cont.innerHTML = "";
    if (!decisiones || !decisiones.length) {
      cont.appendChild(crear("p", "perfil-nota", "Todavía no se ha registrado ninguna decisión clave para este proyecto."));
      return;
    }
    const lista = crear("ul", "pe-lista-decisiones-clave");
    decisiones.forEach((d) => {
      const item = crear("li");
      item.appendChild(crear("p", null, d.texto));
      if (d.motivo) item.appendChild(crear("p", "perfil-nota", `Motivo: ${d.motivo}`));
      if (d.contexto) item.appendChild(crear("p", "perfil-nota", `Contexto: ${d.contexto}`));
      item.appendChild(crear("p", "perfil-nota", formatearFecha(d.creado_en)));
      lista.appendChild(item);
    });
    cont.appendChild(lista);
  }

  async function agregarDecision(evento) {
    evento.preventDefault();
    const form = evento.target;
    const texto = form.querySelector('[name="texto"]').value;
    const motivo = form.querySelector('[name="motivo"]').value;
    const contexto = form.querySelector('[name="contexto"]').value;

    const mensaje = document.getElementById("nueva-decision-mensaje");
    try {
      const resp = await fetch(window.DM_PROYECTO_DECISIONES_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ texto, motivo, contexto }),
      });
      const datos = await resp.json();
      if (!datos.ok) {
        mensaje.hidden = false;
        mensaje.textContent = datos.error;
        return;
      }
      mensaje.hidden = true;
      form.reset();
      renderDecisiones(datos.decisiones_clave);
    } catch (err) {
      mensaje.hidden = false;
      mensaje.textContent = "Error de conexión al registrar la decisión.";
    }
  }

  // --- Pagina de detalle: estado, fases, secuencia -----------------------------------

  async function cambiarEstado() {
    const select = document.getElementById("pe-selector-estado");
    const mensaje = document.getElementById("pe-estado-mensaje");
    try {
      const resp = await fetch(window.DM_PROYECTO_ESTADO_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ estado: select.value }),
      });
      const datos = await resp.json();
      if (!datos.ok) {
        mensaje.hidden = false;
        mensaje.textContent = datos.error;
        return;
      }
      const badge = document.getElementById("pe-estado-badge");
      badge.className = `estado-badge dm-estado-proyecto-${datos.estado}`;
      badge.textContent = datos.estado.replace("_", " ");
      mensaje.hidden = true;
    } catch (err) {
      mensaje.hidden = false;
      mensaje.textContent = "Error de conexión al cambiar el estado.";
    }
  }

  async function agregarFase(evento) {
    evento.preventDefault();
    const form = evento.target;
    const datosForm = new FormData(form);
    const payload = Object.fromEntries(datosForm.entries());
    Object.keys(payload).forEach((k) => { if (payload[k] === "") delete payload[k]; });

    const mensaje = document.getElementById("nueva-fase-mensaje");
    try {
      const resp = await fetch(window.DM_PROYECTO_FASES_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const datos = await resp.json();
      if (!datos.ok) {
        mensaje.hidden = false;
        mensaje.textContent = datos.error;
        return;
      }
      window.location.reload();
    } catch (err) {
      mensaje.hidden = false;
      mensaje.textContent = "Error de conexión al agregar la fase.";
    }
  }

  async function eliminarFase(faseId) {
    const url = window.DM_PROYECTO_FASE_ELIMINAR_URL_BASE.replace("__ID__", faseId);
    try {
      const resp = await fetch(url, { method: "POST" });
      const datos = await resp.json();
      if (!datos.ok) { alert(datos.error); return; }
      window.location.reload();
    } catch (err) {
      alert("Error de conexión al eliminar la fase.");
    }
  }

  async function agregarPasoSecuencia(evento) {
    evento.preventDefault();
    const form = evento.target;
    const datosForm = new FormData(form);
    const payload = Object.fromEntries(datosForm.entries());
    Object.keys(payload).forEach((k) => { if (payload[k] === "") delete payload[k]; });

    const mensaje = document.getElementById("nuevo-paso-secuencia-mensaje");
    try {
      const resp = await fetch(window.DM_PROYECTO_SECUENCIA_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const datos = await resp.json();
      if (!datos.ok) {
        mensaje.hidden = false;
        mensaje.textContent = datos.error;
        return;
      }
      window.location.reload();
    } catch (err) {
      mensaje.hidden = false;
      mensaje.textContent = "Error de conexión al agregar el paso.";
    }
  }

  async function eliminarPasoSecuencia(pasoId) {
    const url = window.DM_PROYECTO_SECUENCIA_ELIMINAR_URL_BASE.replace("__ID__", pasoId);
    try {
      const resp = await fetch(url, { method: "POST" });
      const datos = await resp.json();
      if (!datos.ok) { alert(datos.error); return; }
      window.location.reload();
    } catch (err) {
      alert("Error de conexión al eliminar el paso.");
    }
  }

  function inicializarDetalle() {
    renderDiagnosticoCompleto(window.DM_PROYECTO_DATOS);
    renderDecisiones(window.DM_PROYECTO_DATOS.proyecto.decisiones_clave);

    const formDecision = document.getElementById("form-nueva-decision");
    if (formDecision) formDecision.addEventListener("submit", agregarDecision);

    const selectorEstado = document.getElementById("pe-selector-estado");
    if (selectorEstado) selectorEstado.addEventListener("change", cambiarEstado);

    const formFase = document.getElementById("form-nueva-fase");
    if (formFase) formFase.addEventListener("submit", agregarFase);

    document.querySelectorAll(".pe-boton-eliminar-fase").forEach((btn) => {
      btn.addEventListener("click", () => eliminarFase(btn.dataset.faseId));
    });

    const formSecuencia = document.getElementById("form-nuevo-paso-secuencia");
    if (formSecuencia) formSecuencia.addEventListener("submit", agregarPasoSecuencia);

    document.querySelectorAll(".pe-boton-eliminar-secuencia").forEach((btn) => {
      btn.addEventListener("click", () => eliminarPasoSecuencia(btn.dataset.pasoId));
    });

    const formDiagnostico = document.getElementById("pe-filtro-diagnostico");
    if (formDiagnostico) {
      formDiagnostico.addEventListener("submit", (evento) => {
        evento.preventDefault();
        aplicarFiltroDiagnostico();
      });
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (window.DM_PROYECTOS_CREAR_URL) inicializarLista();
    if (window.DM_PROYECTO_ID) inicializarDetalle();
  });
})();
