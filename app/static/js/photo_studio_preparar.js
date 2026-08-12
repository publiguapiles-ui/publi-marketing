(function () {
  const form = document.getElementById("form-preparar");
  if (!form || !window.PS_PREPARAR_URL) return;

  const campoLogo = document.getElementById("campo-logo");
  const campoPosicion = document.getElementById("campo-posicion");
  const campoOpacidad = document.getElementById("campo-opacidad");
  const valorOpacidad = document.getElementById("valor-opacidad");
  const advertenciaLogo = document.getElementById("advertencia-logo");
  const previewImagen = document.getElementById("preview-imagen");
  const previewTexto = document.getElementById("preview-texto");
  const botonGenerar = document.getElementById("boton-generar");
  const zonaResultados = document.getElementById("zona-resultados");
  const listaResultados = document.getElementById("lista-resultados");

  function aplicacionSeleccionada() {
    const marcada = form.querySelector('input[name="aplicacion"]:checked');
    return marcada ? marcada.value : "sin_logo";
  }

  function formatosSeleccionados() {
    return Array.from(form.querySelectorAll('input[name="formatos"]:checked')).map((c) => c.value);
  }

  function parametrosActuales() {
    return {
      logo_id: campoLogo.value || null,
      aplicacion: aplicacionSeleccionada(),
      posicion: campoPosicion.value,
      opacidad: Number(campoOpacidad.value) / 100,
    };
  }

  campoOpacidad.addEventListener("input", () => {
    valorOpacidad.textContent = `${campoOpacidad.value}%`;
    actualizarVistaPrevia();
  });
  campoLogo.addEventListener("change", actualizarVistaPrevia);
  campoPosicion.addEventListener("change", actualizarVistaPrevia);
  form.querySelectorAll('input[name="aplicacion"]').forEach((r) => r.addEventListener("change", actualizarVistaPrevia));

  let ultimaPeticion = 0;

  async function actualizarVistaPrevia() {
    const parametros = parametrosActuales();
    if (parametros.aplicacion === "sin_logo") {
      previewImagen.src = window.PS_FOTO_URL_ORIGINAL;
      previewTexto.textContent = "Vista previa en vivo (sin logo)";
      advertenciaLogo.hidden = true;
      return;
    }
    if (!parametros.logo_id) {
      previewTexto.textContent = "Selecciona un logo para previsualizarlo.";
      return;
    }

    const idPeticion = ++ultimaPeticion;
    previewTexto.textContent = "Actualizando vista previa...";

    try {
      const resp = await fetch(window.PS_PREPARAR_VISTA_PREVIA_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...parametros, formato: "formato_cuadrado" }),
      });
      if (idPeticion !== ultimaPeticion) return; // respuesta obsoleta, ya se pidio otra

      if (resp.ok) {
        const blob = await resp.blob();
        previewImagen.src = URL.createObjectURL(blob);
        previewTexto.textContent = "Vista previa en vivo";
        advertenciaLogo.hidden = true;
      } else {
        const datos = await resp.json();
        previewTexto.textContent = "No se pudo generar la vista previa.";
        advertenciaLogo.textContent = datos.error || "No se pudo generar la vista previa.";
        advertenciaLogo.hidden = false;
      }
    } catch (err) {
      if (idPeticion === ultimaPeticion) previewTexto.textContent = "Error de conexión al generar la vista previa.";
    }
  }

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
        body: JSON.stringify({ ...parametrosActuales(), formatos }),
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
})();
