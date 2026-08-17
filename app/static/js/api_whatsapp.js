(function () {
  // API WhatsApp: panel de SOLO LECTURA (3 bloques: sin responder, sin
  // abrir, ultimos 3 mensajes). Actualizacion por polling simple
  // (fetch cada 2s) -- sin WebSocket, sin Redis/Celery, compatible
  // con la arquitectura actual (punto 10 del enunciado).

  const INTERVALO_POLLING_MS = 2000;

  function crear(etiqueta, clases, texto) {
    const el = document.createElement(etiqueta);
    if (clases) el.className = clases;
    if (texto !== undefined) el.textContent = texto;
    return el;
  }

  function formatearFecha(iso) {
    try {
      return new Date(iso).toLocaleString("es-CR", { dateStyle: "medium", timeStyle: "short" });
    } catch (err) {
      return iso;
    }
  }

  const ETIQUETAS_ESTADO_MENSAJE = { leido: "Leído", no_leido: "No leído", enviado: "Enviado", recibido: "Recibido" };

  function renderUltimosMensajes(mensajes) {
    const cont = document.getElementById("ww-ultimos-mensajes");
    if (!cont) return;
    cont.innerHTML = "";
    if (!mensajes || !mensajes.length) {
      cont.appendChild(crear("p", "perfil-nota", "Todavía no se ha recibido ningún mensaje."));
      return;
    }
    mensajes.forEach((m) => {
      const card = crear("div", "ww-mensaje-card");
      const cabecera = crear("div", "ww-mensaje-cabecera");
      cabecera.appendChild(crear("strong", null, m.contacto_nombre || m.contacto_telefono || "Desconocido"));
      if (m.estado) cabecera.appendChild(crear("span", `estado-badge ww-estado-mensaje-${m.estado}`, ETIQUETAS_ESTADO_MENSAJE[m.estado] || m.estado));
      card.appendChild(cabecera);
      card.appendChild(crear("p", null, m.contenido));
      card.appendChild(crear("p", "perfil-nota", formatearFecha(m.creado_en)));
      const boton = crear("button", "boton-enlace", "Marcar como vista");
      boton.type = "button";
      boton.addEventListener("click", () => marcarVista(m.conversacion_id));
      card.appendChild(boton);
      cont.appendChild(card);
    });
  }

  function renderPanel(panel) {
    const elSinResponder = document.getElementById("ww-sin-responder");
    const elSinAbrir = document.getElementById("ww-sin-abrir");
    if (elSinResponder) elSinResponder.textContent = panel.sin_responder;
    if (elSinAbrir) elSinAbrir.textContent = panel.sin_abrir;
    renderUltimosMensajes(panel.ultimos_mensajes);
  }

  async function marcarVista(conversacionId) {
    try {
      await fetch(window.WW_MARCAR_VISTA_URL_BASE.replace("__ID__", conversacionId), { method: "POST" });
      actualizarPanel();
    } catch (err) {
      // silencioso -- el proximo poll vuelve a intentar
    }
  }

  async function actualizarPanel() {
    try {
      const resp = await fetch(window.WW_PANEL_URL);
      const datos = await resp.json();
      if (datos.ok) renderPanel(datos.panel);
    } catch (err) {
      // silencioso -- el proximo poll vuelve a intentar
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (!window.WW_PANEL_INICIAL || !window.WW_PANEL_INICIAL.conectada) return;
    renderUltimosMensajes(window.WW_PANEL_INICIAL.ultimos_mensajes);
    setInterval(actualizarPanel, INTERVALO_POLLING_MS);
  });
})();
