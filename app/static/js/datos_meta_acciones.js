(function () {
  // Acciones controladas sobre Meta (Paso 12). No calcula ningun KPI ni
  // decide nada por su cuenta -- solo administra el formulario de
  // propuesta y el flujo de doble confirmacion antes de llamar a
  // /datos-meta/acciones/<id>/ejecutar, que es la UNICA ruta que
  // realmente escribe en Meta (via app/services/meta/acciones.py).

  function crear(etiqueta, clases, texto) {
    const el = document.createElement(etiqueta);
    if (clases) el.className = clases;
    if (texto !== undefined) el.textContent = texto;
    return el;
  }

  // --- Pagina de lista: selectores en cascada + crear propuesta ------------------------

  function inicializarLista() {
    const form = document.getElementById("acc-form-crear");
    if (!form) return;

    if (!window.DM_ACCIONES_TIENE_PREFILL) {
      const selectCuenta = document.getElementById("acc-cuenta");
      const selectCampana = document.getElementById("acc-campana");
      const selectConjunto = document.getElementById("acc-conjunto");
      const selectAnuncio = document.getElementById("acc-anuncio");
      const inputEntidadId = document.getElementById("acc-entidad-id");

      function actualizarEntidadSeleccionada() {
        // La entidad objetivo es la mas especifica que este elegida:
        // anuncio > conjunto > campaña.
        inputEntidadId.value = selectAnuncio.value || selectConjunto.value || selectCampana.value || "";
      }

      selectCuenta.addEventListener("change", async () => {
        selectCampana.innerHTML = '<option value="">Selecciona una campaña</option>';
        selectConjunto.innerHTML = '<option value="">Ninguno — acción sobre la campaña</option>';
        selectAnuncio.innerHTML = '<option value="">Ninguno — acción sobre el conjunto</option>';
        selectConjunto.disabled = true;
        selectAnuncio.disabled = true;
        actualizarEntidadSeleccionada();
        if (!selectCuenta.value) { selectCampana.disabled = true; return; }
        const resp = await fetch(`${window.DM_ACCIONES_CAMPANAS_URL}?cuenta_id=${selectCuenta.value}`);
        const datos = await resp.json();
        selectCampana.disabled = false;
        (datos.campanas || []).forEach((c) => {
          const opt = document.createElement("option");
          opt.value = c.id; opt.textContent = c.nombre;
          selectCampana.appendChild(opt);
        });
      });

      selectCampana.addEventListener("change", async () => {
        selectConjunto.innerHTML = '<option value="">Ninguno — acción sobre la campaña</option>';
        selectAnuncio.innerHTML = '<option value="">Ninguno — acción sobre el conjunto</option>';
        selectAnuncio.disabled = true;
        actualizarEntidadSeleccionada();
        if (!selectCampana.value) { selectConjunto.disabled = true; return; }
        const resp = await fetch(`${window.DM_ACCIONES_CONJUNTOS_URL}?campana_id=${selectCampana.value}`);
        const datos = await resp.json();
        selectConjunto.disabled = false;
        (datos.conjuntos || []).forEach((c) => {
          const opt = document.createElement("option");
          opt.value = c.id; opt.textContent = c.nombre;
          selectConjunto.appendChild(opt);
        });
      });

      selectConjunto.addEventListener("change", async () => {
        selectAnuncio.innerHTML = '<option value="">Ninguno — acción sobre el conjunto</option>';
        actualizarEntidadSeleccionada();
        if (!selectConjunto.value) { selectAnuncio.disabled = true; return; }
        const resp = await fetch(`${window.DM_ACCIONES_ANUNCIOS_URL}?conjunto_id=${selectConjunto.value}`);
        const datos = await resp.json();
        selectAnuncio.disabled = false;
        (datos.anuncios || []).forEach((a) => {
          const opt = document.createElement("option");
          opt.value = a.id; opt.textContent = a.nombre;
          selectAnuncio.appendChild(opt);
        });
      });

      selectAnuncio.addEventListener("change", actualizarEntidadSeleccionada);
    }

    form.addEventListener("submit", async (evento) => {
      evento.preventDefault();
      const datosForm = new FormData(form);
      const entidadId = form.querySelector('[name="entidad_id"]').value;
      const mensaje = document.getElementById("acc-crear-mensaje");
      if (!entidadId) {
        mensaje.hidden = false;
        mensaje.textContent = "Selecciona el recurso sobre el que quieres proponer la acción.";
        return;
      }
      const payload = {
        entidad_id: Number(entidadId),
        tipo_accion: datosForm.get("tipo_accion"),
        valor_propuesto: datosForm.get("valor_propuesto"),
        motivo: datosForm.get("motivo"),
        evidencia: datosForm.get("evidencia"),
        riesgo: datosForm.get("riesgo"),
      };
      try {
        const resp = await fetch(window.DM_ACCIONES_CREAR_URL, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
        });
        const datos = await resp.json();
        if (!datos.ok) {
          mensaje.hidden = false;
          mensaje.textContent = datos.error;
          return;
        }
        window.location.href = window.DM_ACCIONES_DETALLE_URL_BASE.replace("__ID__", datos.accion_id);
      } catch (err) {
        mensaje.hidden = false;
        mensaje.textContent = "Error de conexión al crear la propuesta.";
      }
    });
  }

  // --- Pagina de detalle: aprobar / rechazar / doble confirmacion / reversion ----------

  function mostrarErrorDetalle(mensaje) {
    const el = document.getElementById("acc-mensaje-error");
    if (!el) return;
    el.hidden = !mensaje;
    el.textContent = mensaje || "";
  }

  function calcularCambioPorcentual(actual, propuesto) {
    const a = Number(actual);
    const p = Number(propuesto);
    if (Number.isNaN(a) || Number.isNaN(p) || a === 0) return null;
    return Math.round(((p - a) / Math.abs(a)) * 1000) / 10;
  }

  function inicializarDetalle() {
    const accion = window.DM_ACCION;
    if (!accion) return;

    if (accion.tipo_accion === "modificar_presupuesto") {
      const cambio = calcularCambioPorcentual(accion.valor_actual, accion.valor_propuesto);
      if (cambio !== null) {
        document.getElementById("acc-cambio-pct-dt").hidden = false;
        const dd = document.getElementById("acc-cambio-pct");
        dd.hidden = false;
        dd.textContent = `${cambio > 0 ? "+" : ""}${cambio}%`;
      }
    }

    const botonAprobar = document.getElementById("acc-boton-aprobar");
    if (botonAprobar) {
      botonAprobar.addEventListener("click", async () => {
        botonAprobar.disabled = true;
        try {
          const resp = await fetch(window.DM_ACCION_APROBAR_URL, { method: "POST" });
          const datos = await resp.json();
          if (!datos.ok) { mostrarErrorDetalle(datos.error); botonAprobar.disabled = false; return; }
          window.location.reload();
        } catch (err) {
          mostrarErrorDetalle("Error de conexión al aprobar.");
          botonAprobar.disabled = false;
        }
      });
    }

    const botonRechazar = document.getElementById("acc-boton-rechazar");
    if (botonRechazar) {
      botonRechazar.addEventListener("click", async () => {
        botonRechazar.disabled = true;
        try {
          const resp = await fetch(window.DM_ACCION_RECHAZAR_URL, { method: "POST" });
          const datos = await resp.json();
          if (!datos.ok) { mostrarErrorDetalle(datos.error); botonRechazar.disabled = false; return; }
          window.location.reload();
        } catch (err) {
          mostrarErrorDetalle("Error de conexión al rechazar.");
          botonRechazar.disabled = false;
        }
      });
    }

    // Primer paso de la doble confirmacion (Paso 12, punto 5): solo
    // REVELA el texto de confirmacion, no llama a ninguna ruta todavia.
    const botonRevisar = document.getElementById("acc-boton-revisar-cambio");
    if (botonRevisar) {
      botonRevisar.addEventListener("click", () => {
        const texto = accion.tipo_accion === "modificar_presupuesto"
          ? `Vas a cambiar el presupuesto de "${accion.valor_actual}" a "${accion.valor_propuesto}".`
          : `Vas a ${accion.tipo_accion === "pausar" ? "pausar" : "activar"} "${accion.entidad_nombre}".`;
        document.getElementById("acc-texto-confirmacion").textContent = texto;
        document.getElementById("acc-panel-ejecutar").hidden = true;
        document.getElementById("acc-panel-confirmacion").hidden = false;
      });
    }

    const botonNoEjecutar = document.getElementById("acc-boton-no-ejecutar");
    if (botonNoEjecutar) {
      botonNoEjecutar.addEventListener("click", () => {
        document.getElementById("acc-panel-confirmacion").hidden = true;
        document.getElementById("acc-panel-ejecutar").hidden = false;
      });
    }

    // Segundo paso: AHORA si se llama a ejecutar, con confirmacion:true
    // explicito -- acciones.py rechaza la llamada si esto falta.
    const botonConfirmarEjecutar = document.getElementById("acc-boton-confirmar-ejecutar");
    if (botonConfirmarEjecutar) {
      botonConfirmarEjecutar.addEventListener("click", async () => {
        botonConfirmarEjecutar.disabled = true;
        try {
          const resp = await fetch(window.DM_ACCION_EJECUTAR_URL, {
            method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirmacion: true }),
          });
          const datos = await resp.json();
          if (!datos.ok) { mostrarErrorDetalle(datos.error); botonConfirmarEjecutar.disabled = false; window.location.reload(); return; }
          window.location.reload();
        } catch (err) {
          mostrarErrorDetalle("Error de conexión al ejecutar.");
          botonConfirmarEjecutar.disabled = false;
        }
      });
    }

    const botonPrepararReversion = document.getElementById("acc-boton-preparar-reversion");
    if (botonPrepararReversion) {
      botonPrepararReversion.addEventListener("click", async () => {
        botonPrepararReversion.disabled = true;
        const mensaje = document.getElementById("acc-reversion-mensaje");
        try {
          const resp = await fetch(window.DM_ACCION_PREPARAR_REVERSION_URL, { method: "POST" });
          const datos = await resp.json();
          if (!datos.ok) {
            mensaje.hidden = false; mensaje.textContent = datos.error; botonPrepararReversion.disabled = false; return;
          }
          window.location.href = window.location.pathname.replace(/\/\d+$/, `/${datos.accion_id}`);
        } catch (err) {
          mensaje.hidden = false; mensaje.textContent = "Error de conexión al preparar la reversión.";
          botonPrepararReversion.disabled = false;
        }
      });
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    inicializarLista();
    inicializarDetalle();
  });
})();
