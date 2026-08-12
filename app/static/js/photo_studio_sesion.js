(function () {
  if (!window.PS_SESION_ID) return;

  const botonAnalizar = document.getElementById("boton-analizar");
  const botonProcesar = document.getElementById("boton-procesar");
  const botonCancelar = document.getElementById("boton-cancelar");
  const cajaAnalisis = document.getElementById("ps-analisis-caja");
  const badgeEstado = document.getElementById("sesion-estado-badge");

  const contador = document.getElementById("ps-progreso-contador");
  const barraRelleno = document.getElementById("ps-barra-relleno");
  const progresoActual = document.getElementById("ps-progreso-actual");
  const resumenCompletadas = document.getElementById("ps-resumen-completadas");
  const resumenErrores = document.getElementById("ps-resumen-errores");
  const resumenPendientes = document.getElementById("ps-resumen-pendientes");
  const listaItems = document.getElementById("ps-lista-items");

  let cancelando = false;

  function actualizarBadge(estado) {
    badgeEstado.dataset.estado = estado;
    badgeEstado.textContent = estado.replace(/_/g, " ");
  }

  function actualizarItem(item) {
    if (!item) return;
    const li = listaItems.querySelector(`li[data-item-id="${item.id}"]`);
    if (li) {
      li.dataset.estado = item.estado;
      li.querySelector(".ps-item-estado").textContent = item.error ? `${item.estado}: ${item.error}` : item.estado;
    }
  }

  function actualizarProgreso(datos) {
    const total = datos.total;
    const hechas = datos.completadas + datos.errores;
    contador.textContent = `${hechas} / ${total}`;
    barraRelleno.style.width = total ? `${Math.round((hechas / total) * 100)}%` : "0%";
    resumenCompletadas.textContent = datos.completadas;
    resumenErrores.textContent = datos.errores;
    resumenPendientes.textContent = Math.max(0, total - hechas);
    actualizarBadge(datos.sesion_estado);
  }

  botonAnalizar.addEventListener("click", async () => {
    botonAnalizar.disabled = true;
    botonAnalizar.textContent = "Analizando...";
    try {
      const resp = await fetch(window.PS_SESION_ANALIZAR_URL, { method: "POST" });
      const datos = await resp.json();
      if (datos.ok) {
        cajaAnalisis.hidden = false;
        document.getElementById("analisis-brillo").textContent = datos.analisis.brillo_promedio !== null ? datos.analisis.brillo_promedio.toFixed(3) : "-";
        document.getElementById("analisis-contraste").textContent = datos.analisis.contraste_promedio !== null ? datos.analisis.contraste_promedio.toFixed(3) : "-";
        document.getElementById("analisis-saturacion").textContent = datos.analisis.saturacion_promedio !== null ? datos.analisis.saturacion_promedio.toFixed(3) : "-";
        document.getElementById("analisis-temperatura").textContent = datos.analisis.temperatura_predominante || "-";
        document.getElementById("analisis-duracion").textContent = `${datos.analisis.duracion_segundos} s`;
        actualizarBadge(datos.estado);
        botonProcesar.disabled = false;
        botonAnalizar.textContent = "Analizar de nuevo";
      } else {
        alert(datos.error || "No se pudo analizar la sesión.");
        botonAnalizar.textContent = "Analizar sesión";
      }
    } catch (err) {
      alert("Error de conexión al analizar la sesión.");
      botonAnalizar.textContent = "Analizar sesión";
    }
    botonAnalizar.disabled = false;
  });

  async function procesarSiguiente() {
    if (cancelando) return;
    try {
      const resp = await fetch(window.PS_SESION_PROCESAR_URL, { method: "POST" });
      const datos = await resp.json();
      if (!datos.ok) {
        alert(datos.error || "Error al procesar la sesión.");
        return;
      }
      if (datos.item) {
        progresoActual.textContent = `Fotografía actual: ${datos.item.nombre_archivo}`;
        actualizarItem(datos.item);
      }
      actualizarProgreso(datos);

      if (datos.sesion_terminada) {
        progresoActual.textContent = "Procesamiento terminado.";
        botonProcesar.disabled = true;
        botonProcesar.textContent = "Procesado";
        botonCancelar.hidden = true;
        botonAnalizar.disabled = true;
        return;
      }
      setTimeout(procesarSiguiente, 0);
    } catch (err) {
      alert("Error de conexión durante el procesamiento. Puedes reintentar con 'Procesar sesión'.");
      botonProcesar.disabled = false;
      botonProcesar.textContent = "Reanudar procesamiento";
    }
  }

  botonProcesar.addEventListener("click", () => {
    botonProcesar.disabled = true;
    botonProcesar.textContent = "Procesando...";
    botonAnalizar.disabled = true;
    botonCancelar.hidden = false;
    cancelando = false;
    procesarSiguiente();
  });

  botonCancelar.addEventListener("click", async () => {
    cancelando = true;
    botonCancelar.disabled = true;
    botonCancelar.textContent = "Cancelando...";
    try {
      const resp = await fetch(window.PS_SESION_CANCELAR_URL, { method: "POST" });
      const datos = await resp.json();
      actualizarBadge(datos.estado);
      progresoActual.textContent = "Sesión cancelada. Los resultados ya generados se conservan.";
      botonProcesar.disabled = true;
      botonProcesar.textContent = "Cancelada";
      botonCancelar.hidden = true;
    } catch (err) {
      alert("No se pudo cancelar (error de conexión). La fotografía en curso terminará de todas formas.");
    }
  });

  if (window.PS_SESION_ANALIZADA) {
    botonProcesar.disabled = false;
  }
  if (["completada", "completada_con_errores", "cancelada", "error"].includes(window.PS_SESION_ESTADO_INICIAL)) {
    botonProcesar.disabled = true;
    botonProcesar.textContent = "Procesado";
  }
})();
