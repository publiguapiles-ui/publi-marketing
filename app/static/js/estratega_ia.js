(function () {
  // Estratega IA (Paso 10). No calcula ningun KPI ni analisis --
  // solo administra la conversacion y muestra lo que
  // app/services/estratega_ia.py ya devuelve via
  // /marketing/estratega-ia/*. Nunca crea ni modifica nada en Meta.

  let conversacionActualId = window.DM_IA_CONVERSACION_INICIAL_ID || null;

  function crear(etiqueta, clases, texto) {
    const el = document.createElement(etiqueta);
    if (clases) el.className = clases;
    if (texto !== undefined) el.textContent = texto;
    return el;
  }

  function formatearFecha(iso) {
    return new Date(iso).toLocaleString("es-CR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  }

  // --- Lista de conversaciones ------------------------------------------------------

  function renderConversaciones(conversaciones) {
    const cont = document.getElementById("ia-lista-conversaciones");
    cont.innerHTML = "";
    if (!conversaciones.length) {
      cont.appendChild(crear("p", "perfil-nota", "Todavía no hay ninguna conversación."));
      return;
    }
    conversaciones.forEach((c) => {
      const item = crear("button", "ia-item-conversacion" + (c.id === conversacionActualId ? " ia-item-conversacion-activa" : ""));
      item.type = "button";
      item.appendChild(crear("strong", null, c.titulo));
      if (c.proyecto_nombre) item.appendChild(crear("div", "perfil-nota", `Proyecto: ${c.proyecto_nombre}`));
      item.appendChild(crear("div", "perfil-nota", formatearFecha(c.actualizado_en)));
      item.addEventListener("click", () => abrirConversacion(c.id));
      cont.appendChild(item);
    });
  }

  async function cargarListaConversaciones() {
    const resp = await fetch(window.DM_IA_URLS.conversaciones);
    const datos = await resp.json();
    renderConversaciones(datos.conversaciones || []);
  }

  // --- Mensajes ----------------------------------------------------------------------

  function renderMensajes(mensajes) {
    const cont = document.getElementById("ia-mensajes");
    cont.innerHTML = "";
    if (!mensajes.length) {
      cont.appendChild(crear("p", "perfil-nota", "Escribe tu primera pregunta abajo."));
      return;
    }
    mensajes.forEach((m) => cont.appendChild(construirBurbujaMensaje(m)));
    cont.scrollTop = cont.scrollHeight;
  }

  function construirBurbujaMensaje(m) {
    const burbuja = crear("div", `ia-burbuja ia-burbuja-${m.rol}`);
    const contenido = crear("div", "ia-burbuja-contenido");
    // El contenido puede incluir saltos de linea (DATO/ANALISIS/RECOMENDACION) -- se preservan sin interpretar HTML.
    contenido.style.whiteSpace = "pre-wrap";
    contenido.textContent = m.contenido;
    burbuja.appendChild(contenido);
    burbuja.appendChild(crear("div", "perfil-nota ia-burbuja-meta", formatearFecha(m.creado_en)));
    return burbuja;
  }

  async function abrirConversacion(id) {
    conversacionActualId = id;
    const url = window.DM_IA_URLS.conversacionDetalleBase.replace("__ID__", id);
    const resp = await fetch(url);
    const datos = await resp.json();
    if (!datos.ok) {
      mostrarError(datos.error);
      return;
    }
    renderMensajes(datos.mensajes);
    if (datos.conversacion.proyecto_id) {
      document.getElementById("ia-selector-proyecto").value = datos.conversacion.proyecto_id;
    }
    cargarListaConversaciones();
    cargarContexto();
  }

  async function crearNuevaConversacion() {
    const proyectoId = document.getElementById("ia-selector-proyecto").value || null;
    const resp = await fetch(window.DM_IA_URLS.conversacionesCrear, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ proyecto_id: proyectoId }),
    });
    const datos = await resp.json();
    if (!datos.ok) {
      mostrarError(datos.error);
      return;
    }
    conversacionActualId = datos.conversacion.id;
    renderMensajes([]);
    await cargarListaConversaciones();
  }

  function mostrarError(mensaje) {
    const el = document.getElementById("ia-mensaje-error");
    el.hidden = !mensaje;
    el.textContent = mensaje || "";
  }

  async function enviarMensaje(evento) {
    evento.preventDefault();
    mostrarError(null);

    if (!conversacionActualId) {
      await crearNuevaConversacion();
    }
    if (!conversacionActualId) return;

    const input = document.getElementById("ia-input-mensaje");
    const texto = input.value.trim();
    if (!texto) return;

    const cuentaId = document.getElementById("ia-selector-cuenta").value || null;
    const periodo = document.getElementById("ia-selector-periodo").value;

    // Optimista: se muestra la pregunta del usuario de inmediato.
    const cont = document.getElementById("ia-mensajes");
    const vacio = cont.querySelector("p");
    if (vacio) vacio.remove();
    cont.appendChild(construirBurbujaMensaje({ rol: "usuario", contenido: texto, creado_en: new Date().toISOString() }));
    cont.scrollTop = cont.scrollHeight;
    input.value = "";

    const indicador = crear("div", "ia-burbuja ia-burbuja-asistente ia-burbuja-cargando", "Analizando el contexto real…");
    cont.appendChild(indicador);
    cont.scrollTop = cont.scrollHeight;

    const boton = document.getElementById("ia-boton-enviar");
    boton.disabled = true;

    try {
      const url = window.DM_IA_URLS.mensajeEnviarBase.replace("__ID__", conversacionActualId);
      const resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mensaje: texto, cuenta_publicitaria_id: cuentaId, periodo }),
      });
      const datos = await resp.json();
      indicador.remove();
      if (!datos.ok) {
        mostrarError(datos.error);
        boton.disabled = false;
        return;
      }
      cont.appendChild(construirBurbujaMensaje(datos.mensaje));
      cont.scrollTop = cont.scrollHeight;
      cargarListaConversaciones();
    } catch (err) {
      indicador.remove();
      mostrarError("Error de conexión al hablar con el asistente.");
    }
    boton.disabled = false;
  }

  // --- Contexto (panel derecho) --------------------------------------------------------

  function renderContexto(datos) {
    const cont = document.getElementById("ia-datos-utilizados");
    cont.innerHTML = "";
    if (datos.error) {
      cont.textContent = datos.error;
      return;
    }
    const c = datos.contexto;
    if (!c) {
      cont.textContent = "Sin datos todavía.";
      return;
    }
    const lista = crear("ul", "lista-simple");
    if (c.fuente === "proyecto") {
      lista.appendChild(crear("li", null, `Proyecto: ${c.proyecto}`));
      lista.appendChild(crear("li", null, `Fases: ${c.fases}`));
      lista.appendChild(crear("li", null, `Presupuesto total: ${c.presupuesto_total}`));
    } else {
      lista.appendChild(crear("li", null, `Período: ${c.fecha_inicio} a ${c.fecha_fin}`));
      lista.appendChild(crear("li", null, `Campañas analizadas: ${c.campanas_analizadas}`));
      lista.appendChild(crear("li", null, `Audiencias analizadas: ${c.audiencias_analizadas}`));
      lista.appendChild(crear("li", null, `Invertido: ${c.gasto_invertido !== null && c.gasto_invertido !== undefined ? c.gasto_invertido : "No disponible"}`));
    }
    lista.appendChild(crear("li", null, `Oportunidades: ${c.oportunidades_detectadas}`));
    lista.appendChild(crear("li", null, `Alertas: ${c.alertas_detectadas}`));
    cont.appendChild(lista);
  }

  async function cargarContexto() {
    const params = new URLSearchParams();
    const cuentaId = document.getElementById("ia-selector-cuenta").value;
    const proyectoId = document.getElementById("ia-selector-proyecto").value;
    const periodo = document.getElementById("ia-selector-periodo").value;
    if (cuentaId) params.set("cuenta_id", cuentaId);
    if (proyectoId) params.set("proyecto_id", proyectoId);
    params.set("periodo", periodo);

    const resp = await fetch(`${window.DM_IA_URLS.contexto}?${params.toString()}`);
    const datos = await resp.json();
    renderContexto(datos);

    // El enlace "Preparar accion" (Paso 12) sigue el mismo recurso que
    // el panel de contexto -- nunca crea nada por su cuenta, solo abre
    // el Centro de Acciones con la cuenta ya seleccionada.
    const enlaceAccion = document.getElementById("ia-link-preparar-accion");
    if (enlaceAccion && window.DM_IA_URLS.accionesLista) {
      const paramsAccion = new URLSearchParams();
      if (cuentaId) paramsAccion.set("cuenta_id", cuentaId);
      enlaceAccion.href = paramsAccion.toString()
        ? `${window.DM_IA_URLS.accionesLista}?${paramsAccion.toString()}`
        : window.DM_IA_URLS.accionesLista;
    }
  }

  // --- Movil: paneles desplegables -----------------------------------------------------

  function inicializarTogglesMovil() {
    const panelConversaciones = document.getElementById("ia-panel-conversaciones");
    const panelContexto = document.getElementById("ia-panel-contexto");
    document.getElementById("ia-toggle-conversaciones").addEventListener("click", () => {
      panelConversaciones.classList.toggle("ia-panel-visible");
      panelContexto.classList.remove("ia-panel-visible");
    });
    document.getElementById("ia-toggle-contexto").addEventListener("click", () => {
      panelContexto.classList.toggle("ia-panel-visible");
      panelConversaciones.classList.remove("ia-panel-visible");
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    renderConversaciones(window.DM_IA_CONVERSACIONES_INICIALES || []);
    inicializarTogglesMovil();

    document.getElementById("ia-boton-nueva-conversacion").addEventListener("click", crearNuevaConversacion);
    document.getElementById("ia-form-mensaje").addEventListener("submit", enviarMensaje);
    document.getElementById("ia-input-mensaje").addEventListener("keydown", (evento) => {
      if (evento.key === "Enter" && !evento.shiftKey) {
        evento.preventDefault();
        document.getElementById("ia-form-mensaje").requestSubmit();
      }
    });

    ["ia-selector-cuenta", "ia-selector-periodo"].forEach((id) => {
      document.getElementById(id).addEventListener("change", cargarContexto);
    });
    document.getElementById("ia-selector-proyecto").addEventListener("change", cargarContexto);

    if (conversacionActualId) {
      abrirConversacion(conversacionActualId);
    } else {
      renderMensajes([]);
    }
    cargarContexto();
  });
})();
