(function () {
  const form = document.getElementById("form-preparar");
  if (!form || !window.PS_PREPARAR_URL) return;

  const campoLogo = document.getElementById("campo-logo");
  const campoPosicion = document.getElementById("campo-posicion");
  const campoOpacidad = document.getElementById("campo-opacidad");
  const valorOpacidad = document.getElementById("valor-opacidad");
  const advertenciaLogo = document.getElementById("advertencia-logo");
  const previewContenedor = document.getElementById("preview-contenedor");
  const previewImagen = document.getElementById("preview-imagen");
  const previewOverlay = document.getElementById("preview-overlay");
  const previewFoco = document.getElementById("preview-foco");
  const previewTexto = document.getElementById("preview-texto");
  const botonGenerar = document.getElementById("boton-generar");
  const zonaResultados = document.getElementById("zona-resultados");
  const listaResultados = document.getElementById("lista-resultados");

  const camposModo = document.querySelectorAll('input[name="crop_mode"]');
  const campoFormatoEncuadre = document.getElementById("campo-formato-encuadre");
  const campoZoomContenedor = document.getElementById("campo-zoom-contenedor");
  const campoZoom = document.getElementById("campo-zoom");
  const valorZoom = document.getElementById("valor-zoom");
  const botonRestablecer = document.getElementById("boton-restablecer-encuadre");
  const advertenciaEncuadre = document.getElementById("advertencia-encuadre");

  // --- Estado del encuadre (Paso 9) -------------------------------------------
  const encuadre = { modo: "auto", focusX: null, focusY: null, zoom: 1.0 };

  function modoSeleccionado() {
    const marcado = document.querySelector('input[name="crop_mode"]:checked');
    return marcado ? marcado.value : "auto";
  }

  function aplicacionSeleccionada() {
    const marcada = form.querySelector('input[name="aplicacion"]:checked');
    return marcada ? marcada.value : "sin_logo";
  }

  function formatosSeleccionados() {
    return Array.from(form.querySelectorAll('input[name="formatos"]:checked')).map((c) => c.value);
  }

  function parametrosLogo() {
    return {
      logo_id: campoLogo.value || null,
      aplicacion: aplicacionSeleccionada(),
      posicion: campoPosicion.value,
      opacidad: Number(campoOpacidad.value) / 100,
    };
  }

  function parametrosEncuadre() {
    return {
      crop_mode: encuadre.modo,
      focus_x: encuadre.modo === "manual" ? encuadre.focusX : null,
      focus_y: encuadre.modo === "manual" ? encuadre.focusY : null,
      zoom: encuadre.zoom,
    };
  }

  // --- Overlay (calculo liviano, sin renderizar imagen) -----------------------

  function posicionarOverlay(x0, y0, x1, y1, focusX, focusY) {
    const rectImg = previewImagen.getBoundingClientRect();
    const rectCont = previewContenedor.getBoundingClientRect();
    const left = rectImg.left - rectCont.left;
    const top = rectImg.top - rectCont.top;
    const w = rectImg.width;
    const h = rectImg.height;

    previewOverlay.style.left = `${left + x0 * w}px`;
    previewOverlay.style.top = `${top + y0 * h}px`;
    previewOverlay.style.width = `${(x1 - x0) * w}px`;
    previewOverlay.style.height = `${(y1 - y0) * h}px`;
    previewOverlay.hidden = false;

    if (focusX !== null && focusY !== null) {
      previewFoco.style.left = `${left + focusX * w}px`;
      previewFoco.style.top = `${top + focusY * h}px`;
      previewFoco.hidden = false;
    } else {
      previewFoco.hidden = true;
    }
  }

  let ultimaPeticionOverlay = 0;

  async function actualizarOverlay() {
    const idPeticion = ++ultimaPeticionOverlay;
    try {
      const resp = await fetch(window.PS_ENCUADRE_CALCULAR_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...parametrosEncuadre(), formato: campoFormatoEncuadre.value }),
      });
      if (idPeticion !== ultimaPeticionOverlay) return;
      const datos = await resp.json();
      if (!datos.ok) return;
      posicionarOverlay(datos.crop_x0, datos.crop_y0, datos.crop_x1, datos.crop_y1, datos.focus_x, datos.focus_y);
      if (datos.advertencia) {
        advertenciaEncuadre.textContent = datos.advertencia;
        advertenciaEncuadre.hidden = false;
      } else {
        advertenciaEncuadre.hidden = true;
      }
    } catch (err) {
      /* el overlay es solo una ayuda visual; un fallo aqui no debe romper el resto */
    }
  }

  // --- Vista previa real (mismo algoritmo que el resultado final) -------------

  let ultimaPeticionPreview = 0;
  let temporizadorPreview = null;

  function programarVistaPreviaReal(demoraMs) {
    if (temporizadorPreview) clearTimeout(temporizadorPreview);
    temporizadorPreview = setTimeout(actualizarVistaPreviaReal, demoraMs);
  }

  async function actualizarVistaPreviaReal() {
    const logo = parametrosLogo();
    if (logo.aplicacion !== "sin_logo" && !logo.logo_id) {
      previewTexto.textContent = "Selecciona un logo para previsualizarlo.";
      return;
    }

    const idPeticion = ++ultimaPeticionPreview;
    previewTexto.textContent = "Actualizando vista previa...";

    try {
      const resp = await fetch(window.PS_PREPARAR_VISTA_PREVIA_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...logo, ...parametrosEncuadre(), formato: campoFormatoEncuadre.value }),
      });
      if (idPeticion !== ultimaPeticionPreview) return; // respuesta obsoleta

      if (resp.ok) {
        const blob = await resp.blob();
        previewImagen.src = URL.createObjectURL(blob);
        previewImagen.onload = actualizarOverlay; // el tamano visible cambio, reposicionar overlay
        previewTexto.textContent = "Vista previa en vivo";
        advertenciaLogo.hidden = true;
      } else {
        const datos = await resp.json();
        previewTexto.textContent = "No se pudo generar la vista previa.";
        advertenciaLogo.textContent = datos.error || "No se pudo generar la vista previa.";
        advertenciaLogo.hidden = false;
      }
    } catch (err) {
      if (idPeticion === ultimaPeticionPreview) previewTexto.textContent = "Error de conexión al generar la vista previa.";
    }
  }

  function actualizarTodo() {
    actualizarOverlay();
    programarVistaPreviaReal(400);
  }

  // --- Interaccion: click/touch para fijar el punto de enfoque -----------------

  function coordenadasNormalizadas(evento) {
    const rect = previewImagen.getBoundingClientRect();
    const x = (evento.clientX - rect.left) / rect.width;
    const y = (evento.clientY - rect.top) / rect.height;
    return [Math.min(Math.max(x, 0), 1), Math.min(Math.max(y, 0), 1)];
  }

  function fijarModoManual() {
    const radioManual = document.querySelector('input[name="crop_mode"][value="manual"]');
    if (radioManual && !radioManual.checked) {
      radioManual.checked = true;
      encuadre.modo = "manual";
      campoZoomContenedor.hidden = false;
    }
  }

  let arrastrando = false;

  previewImagen.addEventListener("pointerdown", (e) => {
    arrastrando = true;
    fijarModoManual();
    const [x, y] = coordenadasNormalizadas(e);
    encuadre.focusX = x;
    encuadre.focusY = y;
    actualizarOverlay();
  });
  previewImagen.addEventListener("pointermove", (e) => {
    if (!arrastrando) return;
    const [x, y] = coordenadasNormalizadas(e);
    encuadre.focusX = x;
    encuadre.focusY = y;
    actualizarOverlay();
  });
  ["pointerup", "pointerleave", "pointercancel"].forEach((evento) => {
    previewImagen.addEventListener(evento, () => {
      if (arrastrando) {
        arrastrando = false;
        programarVistaPreviaReal(200);
      }
    });
  });

  // --- Controles de encuadre -----------------------------------------------------

  camposModo.forEach((radio) =>
    radio.addEventListener("change", () => {
      encuadre.modo = modoSeleccionado();
      campoZoomContenedor.hidden = encuadre.modo !== "manual";
      if (encuadre.modo === "auto") {
        encuadre.focusX = null;
        encuadre.focusY = null;
      } else if (encuadre.focusX === null) {
        encuadre.focusX = 0.5;
        encuadre.focusY = 0.5;
      }
      actualizarTodo();
    })
  );

  campoFormatoEncuadre.addEventListener("change", actualizarTodo);

  campoZoom.addEventListener("input", () => {
    encuadre.zoom = Number(campoZoom.value) / 100;
    valorZoom.textContent = `${encuadre.zoom.toFixed(1)}x`;
    actualizarOverlay();
  });
  campoZoom.addEventListener("change", () => programarVistaPreviaReal(100));

  botonRestablecer.addEventListener("click", () => {
    encuadre.modo = "auto";
    encuadre.focusX = null;
    encuadre.focusY = null;
    encuadre.zoom = 1.0;
    document.querySelector('input[name="crop_mode"][value="auto"]').checked = true;
    campoZoom.value = 100;
    valorZoom.textContent = "1.0x";
    campoZoomContenedor.hidden = true;
    actualizarTodo();
  });

  campoOpacidad.addEventListener("input", () => {
    valorOpacidad.textContent = `${campoOpacidad.value}%`;
  });
  campoOpacidad.addEventListener("change", () => programarVistaPreviaReal(100));
  campoLogo.addEventListener("change", () => programarVistaPreviaReal(100));
  campoPosicion.addEventListener("change", () => programarVistaPreviaReal(100));
  form.querySelectorAll('input[name="aplicacion"]').forEach((r) => r.addEventListener("change", () => programarVistaPreviaReal(100)));

  // --- Generar formatos (persistido) -------------------------------------------

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const formatos = formatosSeleccionados();
    if (!formatos.length) {
      alert("Selecciona al menos un formato.");
      return;
    }

    botonGenerar.disabled = true;
    botonGenerar.textContent = "Generando...";
    zonaResultados.hidden = false;
    listaResultados.innerHTML = "";

    try {
      const resp = await fetch(window.PS_PREPARAR_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...parametrosLogo(), ...parametrosEncuadre(), formatos }),
      });
      const datos = await resp.json();
      (datos.resultados || []).forEach((r) => {
        const li = document.createElement("li");
        if (r.ok) {
          const a = document.createElement("a");
          a.href = r.url_resultado;
          a.textContent = r.tipo.replace("formato_", "");
          li.appendChild(a);
          const meta = document.createElement("span");
          meta.className = "tarjeta-foto-meta";
          meta.textContent = r.advertencia ? `completado (${r.advertencia})` : "completado";
          li.appendChild(meta);
        } else {
          li.textContent = `${r.tipo.replace("formato_", "")}: ${r.error || "error"}`;
        }
        listaResultados.appendChild(li);
      });
    } catch (err) {
      listaResultados.innerHTML = "<li>Error de conexión.</li>";
    }

    botonGenerar.disabled = false;
    botonGenerar.textContent = "Generar formatos";
  });

  // Estado inicial: overlay del encuadre automatico ya calculado.
  if (previewImagen.complete) {
    actualizarOverlay();
  } else {
    previewImagen.addEventListener("load", actualizarOverlay, { once: true });
  }
})();
