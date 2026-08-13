(function () {
  // --- Sincronizar -----------------------------------------------------------
  const botonSincronizar = document.getElementById("boton-sincronizar");
  const mensajeSync = document.getElementById("sincronizar-mensaje");
  const selectPeriodo = document.getElementById("sincronizar-periodo");
  const bloquePersonalizado = document.getElementById("sincronizar-personalizado");

  if (selectPeriodo && bloquePersonalizado) {
    selectPeriodo.addEventListener("change", () => {
      bloquePersonalizado.hidden = selectPeriodo.value !== "personalizado";
    });
  }

  if (botonSincronizar) {
    botonSincronizar.addEventListener("click", async () => {
      botonSincronizar.disabled = true;
      botonSincronizar.textContent = "Sincronizando...";
      if (mensajeSync) mensajeSync.hidden = true;

      const cuerpo = { periodo: selectPeriodo ? selectPeriodo.value : "ultimos_30_dias" };
      if (cuerpo.periodo === "personalizado") {
        cuerpo.fecha_inicio = document.getElementById("sincronizar-fecha-inicio").value;
        cuerpo.fecha_fin = document.getElementById("sincronizar-fecha-fin").value;
      }

      try {
        const resp = await fetch(window.DM_SINCRONIZAR_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(cuerpo),
        });
        const datos = await resp.json();
        if (datos.ok) {
          window.location.reload();
        } else if (mensajeSync) {
          mensajeSync.textContent = datos.error || "No se pudo sincronizar.";
          mensajeSync.hidden = false;
        }
      } catch (err) {
        if (mensajeSync) {
          mensajeSync.textContent = "Error de conexión al sincronizar.";
          mensajeSync.hidden = false;
        }
      }
      botonSincronizar.disabled = false;
      botonSincronizar.textContent = "Sincronizar ahora";
    });
  }

  // --- Reintentar --------------------------------------------------------------
  const botonReintentar = document.getElementById("boton-reintentar");
  if (botonReintentar) {
    botonReintentar.addEventListener("click", async () => {
      botonReintentar.disabled = true;
      botonReintentar.textContent = "Reintentando...";
      const url = window.DM_REINTENTAR_URL_BASE.replace("__ID__", botonReintentar.dataset.sincronizacionId);
      try {
        const resp = await fetch(url, { method: "POST" });
        const datos = await resp.json();
        if (datos.ok) {
          window.location.reload();
        } else {
          alert(datos.error || "No se pudo reintentar.");
          botonReintentar.disabled = false;
          botonReintentar.textContent = "Reintentar";
        }
      } catch (err) {
        alert("Error de conexión.");
        botonReintentar.disabled = false;
        botonReintentar.textContent = "Reintentar";
      }
    });
  }

  // --- Desconectar ---------------------------------------------------------------
  const botonDesconectar = document.getElementById("boton-desconectar");
  if (botonDesconectar) {
    botonDesconectar.addEventListener("click", async () => {
      if (!confirm("¿Desconectar Meta de esta empresa? Los datos ya sincronizados se conservan.")) {
        return;
      }
      const url = window.DM_DESCONECTAR_URL_BASE.replace("__ID__", botonDesconectar.dataset.conexionId);
      try {
        const resp = await fetch(url, { method: "POST" });
        const datos = await resp.json();
        if (datos.ok) {
          window.location.reload();
        } else {
          alert(datos.error || "No se pudo desconectar.");
        }
      } catch (err) {
        alert("Error de conexión al desconectar.");
      }
    });
  }

  // --- Presupuesto: crear ---------------------------------------------------------
  const formPresupuesto = document.getElementById("form-presupuesto");
  const mensajePresupuesto = document.getElementById("presupuesto-mensaje");
  if (formPresupuesto) {
    formPresupuesto.addEventListener("submit", async (evento) => {
      evento.preventDefault();
      const datosForm = new FormData(formPresupuesto);
      const cuerpo = Object.fromEntries(datosForm.entries());

      try {
        const resp = await fetch(window.DM_PRESUPUESTO_CREAR_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(cuerpo),
        });
        const datos = await resp.json();
        if (datos.ok) {
          window.location.reload();
        } else if (mensajePresupuesto) {
          mensajePresupuesto.textContent = datos.error || "No se pudo guardar el presupuesto.";
          mensajePresupuesto.hidden = false;
        }
      } catch (err) {
        if (mensajePresupuesto) {
          mensajePresupuesto.textContent = "Error de conexión.";
          mensajePresupuesto.hidden = false;
        }
      }
    });
  }

  // --- Presupuesto: eliminar -------------------------------------------------------
  document.querySelectorAll(".dm-boton-eliminar-presupuesto").forEach((boton) => {
    boton.addEventListener("click", async () => {
      if (!confirm("¿Eliminar este presupuesto?")) return;
      const url = window.DM_PRESUPUESTO_ELIMINAR_URL_BASE.replace("__ID__", boton.dataset.presupuestoId);
      try {
        const resp = await fetch(url, { method: "POST" });
        const datos = await resp.json();
        if (datos.ok) {
          window.location.reload();
        } else {
          alert(datos.error || "No se pudo eliminar.");
        }
      } catch (err) {
        alert("Error de conexión.");
      }
    });
  });
})();
