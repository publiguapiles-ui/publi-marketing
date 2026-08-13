(function () {
  const form = document.getElementById("form-preset");
  if (!form) return;

  const sliders = Array.from(form.querySelectorAll('input[type="range"]'));
  const valoresIniciales = new Map(sliders.map((s) => [s.name, s.value]));

  const selectFoto = document.getElementById("preset-foto-muestra");
  const imgAntes = document.getElementById("preset-preview-antes");
  const imgDespues = document.getElementById("preset-preview-despues");
  const cargando = document.getElementById("preset-preview-cargando");

  function actualizarOutput(slider) {
    const output = slider.parentElement.querySelector("output");
    if (output) output.textContent = slider.value;
  }
  sliders.forEach((slider) => {
    slider.addEventListener("input", () => actualizarOutput(slider));
  });

  function recolectarParametros() {
    const datos = new FormData(form);
    const parametros = {};
    const avanzado = {};
    for (const slider of sliders) {
      const valor = parseFloat(datos.get(slider.name));
      if (slider.name.startsWith("avanzado_")) {
        avanzado[slider.name.replace("avanzado_", "")] = valor;
      } else {
        parametros[slider.name] = valor;
      }
    }
    parametros.avanzado = avanzado;
    return parametros;
  }

  let temporizadorPreview = null;
  function solicitarPreview() {
    if (!selectFoto || !imgAntes || !imgDespues) return;
    const fotoId = selectFoto.value;
    if (!fotoId) return;

    imgAntes.src = (window.PS_FOTOS_MUESTRA_URLS || {})[fotoId] || "";

    clearTimeout(temporizadorPreview);
    temporizadorPreview = setTimeout(async () => {
      if (cargando) cargando.hidden = false;
      try {
        const url = window.PS_PRESET_VISTA_PREVIA_URL_BASE.replace("__ID__", fotoId);
        const resp = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ parametros: recolectarParametros() }),
        });
        if (!resp.ok) throw new Error("preview_error");
        const blob = await resp.blob();
        imgDespues.src = URL.createObjectURL(blob);
      } catch (err) {
        // Vista previa fallida no debe bloquear el resto del editor.
      } finally {
        if (cargando) cargando.hidden = true;
      }
    }, 350);
  }

  sliders.forEach((slider) => slider.addEventListener("input", solicitarPreview));
  if (selectFoto) {
    selectFoto.addEventListener("change", solicitarPreview);
    solicitarPreview();
  }

  const botonRestablecer = document.getElementById("boton-restablecer-preset");
  if (botonRestablecer) {
    botonRestablecer.addEventListener("click", () => {
      sliders.forEach((slider) => {
        slider.value = valoresIniciales.get(slider.name);
        actualizarOutput(slider);
      });
      solicitarPreview();
    });
  }

  form.addEventListener("submit", async (evento) => {
    evento.preventDefault();
    if (form.dataset.soloLectura) return;

    const boton = document.getElementById("boton-guardar-preset");
    boton.disabled = true;
    boton.textContent = "Guardando...";

    const datosForm = new FormData(form);
    const cuerpo = {
      nombre: datosForm.get("nombre"),
      descripcion: datosForm.get("descripcion"),
      categoria: datosForm.get("categoria"),
      ...recolectarParametros(),
    };

    try {
      const resp = await fetch(window.PS_PRESET_GUARDAR_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(cuerpo),
      });
      const datos = await resp.json();
      if (datos.ok) {
        if (datos.url) {
          window.location.href = datos.url;
        } else {
          window.location.href = window.PS_PRESET_EDITAR_URL_BASE.replace("__ID__", datos.preset_id);
        }
      } else {
        alert(datos.error || "No se pudo guardar el preset.");
        boton.disabled = false;
        boton.textContent = "Guardar preset";
      }
    } catch (err) {
      alert("No se pudo guardar el preset (error de conexión).");
      boton.disabled = false;
      boton.textContent = "Guardar preset";
    }
  });

  async function duplicar(presetId) {
    try {
      const url = window.PS_PRESET_DUPLICAR_URL || `/photo-studio/presets/${presetId}/duplicar`;
      const resp = await fetch(url, { method: "POST" });
      const datos = await resp.json();
      if (datos.ok) {
        window.location.href = datos.url;
      } else {
        alert(datos.error || "No se pudo duplicar el preset.");
      }
    } catch (err) {
      alert("No se pudo duplicar el preset (error de conexión).");
    }
  }

  const botonCrearCopia = document.getElementById("boton-crear-copia");
  if (botonCrearCopia) {
    botonCrearCopia.addEventListener("click", () => duplicar(botonCrearCopia.dataset.presetId));
  }
  const botonDuplicar = document.getElementById("boton-duplicar-preset");
  if (botonDuplicar) {
    botonDuplicar.addEventListener("click", () => duplicar(botonDuplicar.dataset.presetId));
  }
})();
