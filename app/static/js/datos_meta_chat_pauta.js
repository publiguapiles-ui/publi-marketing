(function () {
  // Chat de Pauta (Paso 13). NO es un motor de analisis nuevo -- habla
  // con las MISMAS rutas del Estratega IA (Paso 10) que ya construyen
  // el contexto reutilizando inteligencia.py/proyectos_estrategicos.py
  // y llaman al modelo via app/services/ia.py. Lo unico nuevo aqui es
  // la interfaz (sugerencias, encabezado de pauta) y la transcripcion
  // de voz, hecha 100% en el navegador con la Web Speech API -- nunca
  // se sube ni se guarda un archivo de audio, solo el texto ya
  // transcrito, como cualquier otro mensaje escrito.

  let conversacionActualId = window.DM_CP_CONVERSACION_INICIAL_ID || null;
  let reconocimiento = null;
  let grabando = false;

  function crear(etiqueta, clases, texto) {
    const el = document.createElement(etiqueta);
    if (clases) el.className = clases;
    if (texto !== undefined) el.textContent = texto;
    return el;
  }

  function formatearFecha(iso) {
    return new Date(iso).toLocaleString("es-CR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  }

  function mostrarErrorChat(mensaje) {
    const el = document.getElementById("cp-mensaje-error");
    el.hidden = !mensaje;
    el.textContent = mensaje || "";
  }

  function mostrarErrorAudio(mensaje) {
    const el = document.getElementById("cp-error-audio");
    el.hidden = !mensaje;
    el.textContent = mensaje || "";
  }

  // --- Mensajes -------------------------------------------------------------------------

  function construirFuente(contexto) {
    if (!contexto || contexto.fuente === "sin_datos") return null;
    const periodoEtiqueta = window.DM_CP_ETIQUETAS_PERIODOS[contexto.periodo] || contexto.periodo || "";
    return `Fuente: Meta Ads — ${contexto.empresa || window.DM_CP_EMPRESA_NOMBRE} — ${periodoEtiqueta}`;
  }

  function construirBurbujaMensaje(m) {
    const burbuja = crear("div", `ia-burbuja ia-burbuja-${m.rol}`);
    const contenido = crear("div", "ia-burbuja-contenido");
    contenido.style.whiteSpace = "pre-wrap";
    contenido.textContent = m.contenido;
    burbuja.appendChild(contenido);

    if (m.rol === "asistente") {
      const fuenteTexto = construirFuente(m.contexto_utilizado);
      if (fuenteTexto) burbuja.appendChild(crear("div", "perfil-nota cp-fuente", fuenteTexto));

      const acciones = crear("div", "cp-acciones-mensaje");
      const cuentaId = document.getElementById("cp-cuenta").value;
      const periodo = document.getElementById("cp-periodo").value;

      const params = new URLSearchParams();
      if (cuentaId) params.set("cuenta_id", cuentaId);
      params.set("periodo", periodo);

      const enlaceGrafico = crear("a", "boton-enlace", "Ver gráfico");
      enlaceGrafico.href = `${window.DM_CP_URLS.dashboard}?${params.toString()}`;
      acciones.appendChild(enlaceGrafico);

      const enlaceAccion = crear("a", "boton-enlace", "Preparar acción");
      const paramsAccion = new URLSearchParams();
      if (cuentaId) paramsAccion.set("cuenta_id", cuentaId);
      enlaceAccion.href = paramsAccion.toString() ? `${window.DM_CP_URLS.accionesLista}?${paramsAccion.toString()}` : window.DM_CP_URLS.accionesLista;
      acciones.appendChild(enlaceAccion);

      burbuja.appendChild(acciones);
    }

    burbuja.appendChild(crear("div", "perfil-nota ia-burbuja-meta", formatearFecha(m.creado_en)));
    return burbuja;
  }

  function renderMensajes(mensajes) {
    const cont = document.getElementById("cp-mensajes");
    cont.innerHTML = "";
    const sugerencias = document.getElementById("cp-sugerencias");
    if (!mensajes.length) {
      sugerencias.hidden = false;
      return;
    }
    sugerencias.hidden = true;
    mensajes.forEach((m) => cont.appendChild(construirBurbujaMensaje(m)));
    cont.scrollTop = cont.scrollHeight;
  }

  async function abrirConversacion(id) {
    conversacionActualId = id;
    const url = window.DM_CP_URLS.conversacionDetalleBase.replace("__ID__", id);
    const resp = await fetch(url);
    const datos = await resp.json();
    if (!datos.ok) { mostrarErrorChat(datos.error); return; }
    renderMensajes(datos.mensajes);
  }

  async function crearNuevaConversacion() {
    const resp = await fetch(window.DM_CP_URLS.conversacionesCrear, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}),
    });
    const datos = await resp.json();
    if (!datos.ok) { mostrarErrorChat(datos.error); return null; }
    conversacionActualId = datos.conversacion.id;
    renderMensajes([]);
    return conversacionActualId;
  }

  async function enviarTexto(texto) {
    mostrarErrorChat(null);
    texto = (texto || "").trim();
    if (!texto) return;

    if (!conversacionActualId) {
      const id = await crearNuevaConversacion();
      if (!id) return;
    }

    const cont = document.getElementById("cp-mensajes");
    document.getElementById("cp-sugerencias").hidden = true;
    cont.appendChild(construirBurbujaMensaje({ rol: "usuario", contenido: texto, creado_en: new Date().toISOString() }));
    cont.scrollTop = cont.scrollHeight;

    const indicador = crear("div", "ia-burbuja ia-burbuja-asistente ia-burbuja-cargando", "Consultando los datos reales…");
    cont.appendChild(indicador);
    cont.scrollTop = cont.scrollHeight;

    const boton = document.getElementById("cp-boton-enviar");
    boton.disabled = true;

    const cuentaId = document.getElementById("cp-cuenta").value || null;
    const periodo = document.getElementById("cp-periodo").value;

    try {
      const url = window.DM_CP_URLS.mensajeEnviarBase.replace("__ID__", conversacionActualId);
      const resp = await fetch(url, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mensaje: texto, cuenta_publicitaria_id: cuentaId, periodo }),
      });
      const datos = await resp.json();
      indicador.remove();
      if (!datos.ok) { mostrarErrorChat(datos.error); boton.disabled = false; return; }
      cont.appendChild(construirBurbujaMensaje(datos.mensaje));
      cont.scrollTop = cont.scrollHeight;
    } catch (err) {
      indicador.remove();
      mostrarErrorChat("Meta no respondió correctamente. No puedo completar este análisis ahora.");
    }
    boton.disabled = false;
  }

  // --- Microfono: transcripcion real via la Web Speech API del navegador ----------------

  function actualizarBotonMic() {
    const boton = document.getElementById("cp-boton-mic");
    boton.classList.toggle("cp-boton-mic-grabando", grabando);
    boton.textContent = grabando ? "⏹" : "🎤";
    boton.title = grabando ? "Detener grabación" : "Grabar pregunta por voz";
  }

  function iniciarODetenerGrabacion() {
    mostrarErrorAudio(null);
    if (grabando) {
      if (reconocimiento) reconocimiento.stop();
      return;
    }

    const Reconocedor = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Reconocedor) {
      mostrarErrorAudio("Tu navegador no soporta grabación de voz. Escribe tu mensaje.");
      return;
    }

    reconocimiento = new Reconocedor();
    reconocimiento.lang = "es-CR";
    reconocimiento.interimResults = true;
    reconocimiento.continuous = false;

    reconocimiento.onresult = (evento) => {
      let texto = "";
      for (let i = 0; i < evento.results.length; i++) texto += evento.results[i][0].transcript;
      document.getElementById("cp-input-mensaje").value = texto;
    };
    reconocimiento.onerror = () => {
      mostrarErrorAudio("No pude transcribir el audio. Puedes intentarlo nuevamente o escribir el mensaje.");
      grabando = false;
      actualizarBotonMic();
    };
    reconocimiento.onend = () => {
      grabando = false;
      actualizarBotonMic();
    };

    try {
      reconocimiento.start();
      grabando = true;
      actualizarBotonMic();
    } catch (err) {
      mostrarErrorAudio("No pude iniciar la grabación. Puedes escribir el mensaje directamente.");
    }
  }

  // --- Inicializacion ---------------------------------------------------------------------

  document.addEventListener("DOMContentLoaded", () => {
    if (conversacionActualId) {
      abrirConversacion(conversacionActualId);
    } else {
      renderMensajes([]);
    }

    document.getElementById("cp-boton-mic").addEventListener("click", iniciarODetenerGrabacion);

    document.getElementById("cp-form-mensaje").addEventListener("submit", (evento) => {
      evento.preventDefault();
      const input = document.getElementById("cp-input-mensaje");
      const texto = input.value;
      input.value = "";
      enviarTexto(texto);
    });

    document.getElementById("cp-input-mensaje").addEventListener("keydown", (evento) => {
      if (evento.key === "Enter" && !evento.shiftKey) {
        evento.preventDefault();
        document.getElementById("cp-form-mensaje").requestSubmit();
      }
    });

    document.querySelectorAll(".cp-sugerencia").forEach((boton) => {
      boton.addEventListener("click", () => enviarTexto(boton.textContent));
    });

    // Cambiar cuenta/periodo recarga la pagina (nueva empresa/periodo =
    // nuevo contexto, Paso 13 puntos 12 y 13) -- mismo patron ya usado
    // en Optimizacion (auto-submit del formulario de filtros).
    const form = document.getElementById("cp-filtros");
    document.getElementById("cp-cuenta").addEventListener("change", () => form.submit());
    document.getElementById("cp-periodo").addEventListener("change", () => form.submit());

    document.getElementById("cp-conversaciones").addEventListener("change", (evento) => {
      const params = new URLSearchParams(window.location.search);
      if (evento.target.value) {
        params.set("conversacion_id", evento.target.value);
      } else {
        params.delete("conversacion_id");
      }
      window.location.search = params.toString();
    });
  });
})();
