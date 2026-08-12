(function () {
  const zona = document.getElementById("zona-subida");
  const botonSeleccionar = document.getElementById("boton-seleccionar");
  const input = document.getElementById("input-fotos");
  const progreso = document.getElementById("progreso-subida");
  const progresoTexto = document.getElementById("progreso-texto");
  const progresoBarra = document.getElementById("barra-progreso-relleno");
  const progresoResumen = document.getElementById("progreso-resumen");

  if (!zona || !window.PS_SUBIR_URL) return;

  botonSeleccionar.addEventListener("click", () => input.click());
  input.addEventListener("change", () => subirArchivos(Array.from(input.files)));

  ["dragenter", "dragover"].forEach((evento) => {
    zona.addEventListener(evento, (e) => {
      e.preventDefault();
      zona.classList.add("zona-subida-activa");
    });
  });
  ["dragleave", "drop"].forEach((evento) => {
    zona.addEventListener(evento, (e) => {
      e.preventDefault();
      zona.classList.remove("zona-subida-activa");
    });
  });
  zona.addEventListener("drop", (e) => {
    const archivos = Array.from(e.dataTransfer.files || []);
    if (archivos.length) subirArchivos(archivos);
  });

  function subirUnArchivo(archivo) {
    return new Promise((resolve) => {
      const datos = new FormData();
      datos.append("archivo", archivo);

      const xhr = new XMLHttpRequest();
      xhr.open("POST", window.PS_SUBIR_URL);
      xhr.onload = () => {
        try {
          const respuesta = JSON.parse(xhr.responseText);
          if (xhr.status < 300 && respuesta.ok) {
            resolve({ ok: true, nombre: archivo.name });
          } else {
            resolve({ ok: false, nombre: archivo.name, error: respuesta.error || "Error desconocido." });
          }
        } catch (err) {
          resolve({ ok: false, nombre: archivo.name, error: "Respuesta inválida del servidor." });
        }
      };
      xhr.onerror = () => resolve({ ok: false, nombre: archivo.name, error: "Error de conexión." });
      xhr.send(datos);
    });
  }

  async function subirArchivos(archivos) {
    if (!archivos.length) return;

    progreso.hidden = false;
    progresoResumen.textContent = "";
    const total = archivos.length;
    let completados = 0;
    const fallidos = [];

    progresoTexto.textContent = `Subiendo fotografías... 0 de ${total}`;
    progresoBarra.style.width = "0%";

    for (const archivo of archivos) {
      const resultado = await subirUnArchivo(archivo);
      completados += 1;
      if (!resultado.ok) fallidos.push(resultado);

      progresoTexto.textContent = `Subiendo fotografías... ${completados} de ${total}`;
      progresoBarra.style.width = `${Math.round((completados / total) * 100)}%`;
    }

    if (fallidos.length === 0) {
      progresoTexto.textContent = "Listo";
      progresoResumen.textContent = `${total} fotografía${total === 1 ? "" : "s"} cargada${total === 1 ? "" : "s"} correctamente.`;
    } else {
      const exitosas = total - fallidos.length;
      progresoTexto.textContent = "Listo con errores";
      const detalle = fallidos.map((f) => `${f.nombre}: ${f.error}`).join(" · ");
      progresoResumen.textContent =
        `${exitosas} fotografía${exitosas === 1 ? "" : "s"} cargada${exitosas === 1 ? "" : "s"}. ` +
        `${fallidos.length} no pudo${fallidos.length === 1 ? "" : "ieron"} cargarse (${detalle}).`;
    }

    input.value = "";
    setTimeout(() => window.location.reload(), 1200);
  }

  // --- Seleccion multiple ---
  const barraSeleccion = document.getElementById("barra-seleccion");
  const textoSeleccion = document.getElementById("texto-seleccion");

  document.querySelectorAll(".check-foto").forEach((casilla) => {
    casilla.addEventListener("change", actualizarSeleccion);
  });

  function actualizarSeleccion() {
    const marcadas = document.querySelectorAll(".check-foto:checked");
    if (marcadas.length === 0) {
      barraSeleccion.hidden = true;
      return;
    }
    barraSeleccion.hidden = false;
    textoSeleccion.textContent = `${marcadas.length} fotografía${marcadas.length === 1 ? "" : "s"} seleccionada${marcadas.length === 1 ? "" : "s"}`;
  }

  // --- Mejorar por lote ---
  const botonMejorarSeleccion = document.getElementById("boton-mejorar-seleccion");

  if (botonMejorarSeleccion && window.PS_MEJORAR_URL_BASE) {
    botonMejorarSeleccion.addEventListener("click", async () => {
      const ids = Array.from(document.querySelectorAll(".check-foto:checked")).map((c) => c.value);
      if (!ids.length) return;

      botonMejorarSeleccion.disabled = true;
      progreso.hidden = false;
      progresoResumen.textContent = "";
      const total = ids.length;
      let completados = 0;
      const fallidos = [];

      progresoTexto.textContent = `Mejorando fotografías... 0 de ${total}`;
      progresoBarra.style.width = "0%";

      for (const id of ids) {
        const url = window.PS_MEJORAR_URL_BASE.replace("__ID__", id);
        try {
          const resp = await fetch(url, { method: "POST" });
          const datos = await resp.json();
          if (!datos.ok) fallidos.push({ id, error: datos.error || "Error desconocido." });
        } catch (err) {
          fallidos.push({ id, error: "Error de conexión." });
        }
        completados += 1;
        progresoTexto.textContent = `Mejorando fotografías... ${completados} de ${total}`;
        progresoBarra.style.width = `${Math.round((completados / total) * 100)}%`;
      }

      if (fallidos.length === 0) {
        progresoTexto.textContent = "Listo";
        progresoResumen.textContent = `${total} fotografía${total === 1 ? "" : "s"} mejorada${total === 1 ? "" : "s"} correctamente.`;
      } else {
        const exitosas = total - fallidos.length;
        progresoTexto.textContent = "Listo con errores";
        progresoResumen.textContent =
          `${exitosas} fotografía${exitosas === 1 ? "" : "s"} mejorada${exitosas === 1 ? "" : "s"}. ` +
          `${fallidos.length} no se ${fallidos.length === 1 ? "pudo" : "pudieron"} procesar.`;
      }

      botonMejorarSeleccion.disabled = false;
    });
  }

  // --- Generar formatos por lote (Paso 8) ---
  const botonAbrirFormatos = document.getElementById("boton-abrir-formatos");
  const panelFormatosLote = document.getElementById("panel-formatos-lote");
  const formPrepararLote = document.getElementById("form-preparar-lote");
  const botonCancelarLote = document.getElementById("boton-cancelar-lote");
  const loteCampoOpacidad = document.getElementById("lote-campo-opacidad");
  const loteValorOpacidad = document.getElementById("lote-valor-opacidad");

  if (botonAbrirFormatos && panelFormatosLote) {
    botonAbrirFormatos.addEventListener("click", () => {
      panelFormatosLote.hidden = !panelFormatosLote.hidden;
    });
  }
  if (botonCancelarLote && panelFormatosLote) {
    botonCancelarLote.addEventListener("click", () => {
      panelFormatosLote.hidden = true;
    });
  }
  if (loteCampoOpacidad && loteValorOpacidad) {
    loteCampoOpacidad.addEventListener("input", () => {
      loteValorOpacidad.textContent = `${loteCampoOpacidad.value}%`;
    });
  }

  if (formPrepararLote && window.PS_PREPARAR_URL_BASE) {
    formPrepararLote.addEventListener("submit", async (e) => {
      e.preventDefault();
      const ids = Array.from(document.querySelectorAll(".check-foto:checked")).map((c) => c.value);
      if (!ids.length) return;

      const formatos = Array.from(formPrepararLote.querySelectorAll('input[name="formatos"]:checked')).map((c) => c.value);
      if (!formatos.length) {
        alert("Selecciona al menos un formato.");
        return;
      }
      const aplicacionMarcada = formPrepararLote.querySelector('input[name="aplicacion"]:checked');
      const cuerpo = {
        logo_id: formPrepararLote.querySelector("#lote-campo-logo").value || null,
        aplicacion: aplicacionMarcada ? aplicacionMarcada.value : "sin_logo",
        posicion: formPrepararLote.querySelector("#lote-campo-posicion").value,
        opacidad: Number(loteCampoOpacidad.value) / 100,
        formatos,
      };

      const botonGenerarLote = document.getElementById("boton-generar-lote");
      botonGenerarLote.disabled = true;
      progreso.hidden = false;
      progresoResumen.textContent = "";
      const total = ids.length;
      let completados = 0;
      const fallidos = [];

      progresoTexto.textContent = `Generando formatos... 0 de ${total}`;
      progresoBarra.style.width = "0%";

      for (const id of ids) {
        const url = window.PS_PREPARAR_URL_BASE.replace("__ID__", id);
        try {
          const resp = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(cuerpo),
          });
          const datos = await resp.json();
          if (!datos.ok) fallidos.push({ id, error: "No se pudo generar ningún formato para esta fotografía." });
        } catch (err) {
          fallidos.push({ id, error: "Error de conexión." });
        }
        completados += 1;
        progresoTexto.textContent = `Generando formatos... ${completados} de ${total}`;
        progresoBarra.style.width = `${Math.round((completados / total) * 100)}%`;
      }

      if (fallidos.length === 0) {
        progresoTexto.textContent = "Listo";
        progresoResumen.textContent = `Formatos generados para ${total} fotografía${total === 1 ? "" : "s"}.`;
      } else {
        const exitosas = total - fallidos.length;
        progresoTexto.textContent = "Listo con errores";
        progresoResumen.textContent =
          `${exitosas} fotografía${exitosas === 1 ? "" : "s"} procesada${exitosas === 1 ? "" : "s"}. ` +
          `${fallidos.length} no se ${fallidos.length === 1 ? "pudo" : "pudieron"} procesar.`;
      }

      botonGenerarLote.disabled = false;
      panelFormatosLote.hidden = true;
    });
  }
})();
