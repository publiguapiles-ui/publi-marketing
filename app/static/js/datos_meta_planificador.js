(function () {
  // --- Crear proyecto (lista) -----------------------------------------------------
  const formNuevoProyecto = document.getElementById("form-nuevo-proyecto");
  const nuevoProyectoMensaje = document.getElementById("nuevo-proyecto-mensaje");
  if (formNuevoProyecto) {
    formNuevoProyecto.addEventListener("submit", async (evento) => {
      evento.preventDefault();
      const datosForm = new FormData(formNuevoProyecto);
      const cuerpo = Object.fromEntries(datosForm.entries());
      if (!cuerpo.cuenta_publicitaria_id) delete cuerpo.cuenta_publicitaria_id;

      try {
        const resp = await fetch(window.DM_PLANIFICADOR_CREAR_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(cuerpo),
        });
        const datos = await resp.json();
        if (datos.ok) {
          window.location.href = window.DM_PLANIFICADOR_DETALLE_URL_BASE.replace("__ID__", datos.proyecto_id);
        } else if (nuevoProyectoMensaje) {
          nuevoProyectoMensaje.textContent = datos.error || "No se pudo crear el proyecto.";
          nuevoProyectoMensaje.hidden = false;
        }
      } catch (err) {
        if (nuevoProyectoMensaje) {
          nuevoProyectoMensaje.textContent = "Error de conexión.";
          nuevoProyectoMensaje.hidden = false;
        }
      }
    });
  }

  // --- Cambiar estado del proyecto (detalle) --------------------------------------
  const estadoMensaje = document.getElementById("estado-mensaje");

  async function cambiarEstado(nuevoEstado) {
    try {
      const resp = await fetch(window.DM_PLANIFICADOR_ESTADO_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ estado: nuevoEstado }),
      });
      const datos = await resp.json();
      if (datos.ok) {
        window.location.reload();
      } else if (estadoMensaje) {
        estadoMensaje.textContent = datos.error || "No se pudo cambiar el estado.";
        estadoMensaje.hidden = false;
      }
    } catch (err) {
      if (estadoMensaje) {
        estadoMensaje.textContent = "Error de conexión.";
        estadoMensaje.hidden = false;
      }
    }
  }

  const botonAprobar = document.getElementById("boton-aprobar-plan");
  if (botonAprobar) {
    botonAprobar.addEventListener("click", () => cambiarEstado("plan_aprobado"));
  }
  const botonVolverBorrador = document.getElementById("boton-volver-borrador");
  if (botonVolverBorrador) {
    botonVolverBorrador.addEventListener("click", () => cambiarEstado("borrador"));
  }

  // --- Agregar fase (detalle) ------------------------------------------------------
  const formNuevaEtapa = document.getElementById("form-nueva-etapa");
  const nuevaEtapaMensaje = document.getElementById("nueva-etapa-mensaje");
  if (formNuevaEtapa) {
    formNuevaEtapa.addEventListener("submit", async (evento) => {
      evento.preventDefault();
      const datosForm = new FormData(formNuevaEtapa);
      const cuerpo = Object.fromEntries(datosForm.entries());
      if (!cuerpo.kpi_esperado) delete cuerpo.kpi_esperado;
      if (!cuerpo.duracion_dias) delete cuerpo.duracion_dias;

      try {
        const resp = await fetch(window.DM_PLANIFICADOR_ETAPAS_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(cuerpo),
        });
        const datos = await resp.json();
        if (datos.ok) {
          window.location.reload();
        } else if (nuevaEtapaMensaje) {
          nuevaEtapaMensaje.textContent = datos.error || "No se pudo agregar la fase.";
          nuevaEtapaMensaje.hidden = false;
        }
      } catch (err) {
        if (nuevaEtapaMensaje) {
          nuevaEtapaMensaje.textContent = "Error de conexión.";
          nuevaEtapaMensaje.hidden = false;
        }
      }
    });
  }

  // --- Eliminar fase (detalle) -----------------------------------------------------
  document.querySelectorAll(".dm-boton-eliminar-etapa").forEach((boton) => {
    boton.addEventListener("click", async () => {
      if (!confirm("¿Eliminar esta fase?")) return;
      const url = window.DM_PLANIFICADOR_ETAPA_ELIMINAR_URL_BASE.replace("__ID__", boton.dataset.etapaId);
      try {
        const resp = await fetch(url, { method: "POST" });
        const datos = await resp.json();
        if (datos.ok) {
          window.location.reload();
        } else {
          alert(datos.error || "No se pudo eliminar la fase.");
        }
      } catch (err) {
        alert("Error de conexión.");
      }
    });
  });
})();
