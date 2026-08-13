(function () {
  const form = document.getElementById("form-seleccion-activos");
  if (!form) return;

  const boton = document.getElementById("boton-vincular");
  const mensaje = document.getElementById("seleccion-mensaje");

  function recolectarSeleccion() {
    const seleccion = [];

    form.querySelectorAll(".dm-check-cuenta:checked").forEach((chk) => {
      seleccion.push({
        tipo: "cuenta_publicitaria",
        id_externo: chk.value,
        nombre: chk.dataset.nombre,
        estado: chk.dataset.estado,
        atributos: { moneda: chk.dataset.moneda, zona_horaria: chk.dataset.zonaHoraria },
      });
    });

    form.querySelectorAll(".dm-check-pagina:checked").forEach((chk) => {
      seleccion.push({
        tipo: "pagina",
        id_externo: chk.value,
        nombre: chk.dataset.nombre,
        atributos: { categoria: chk.dataset.categoria },
      });
      if (chk.dataset.instagramId) {
        seleccion.push({
          tipo: "cuenta_instagram",
          id_externo: chk.dataset.instagramId,
          id_externo_padre: chk.value,
          atributos: {},
        });
      }
    });

    return seleccion;
  }

  form.addEventListener("submit", async (evento) => {
    evento.preventDefault();
    boton.disabled = true;
    boton.textContent = "Vinculando...";
    if (mensaje) mensaje.hidden = true;

    try {
      const resp = await fetch(window.DM_VINCULAR_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ seleccion: recolectarSeleccion() }),
      });
      const datos = await resp.json();
      if (datos.ok) {
        window.location.href = datos.url || window.DM_CONEXIONES_URL;
      } else {
        if (mensaje) {
          mensaje.textContent = datos.error || "No se pudo vincular la selección.";
          mensaje.hidden = false;
        }
        boton.disabled = false;
        boton.textContent = "Vincular seleccionados";
      }
    } catch (err) {
      if (mensaje) {
        mensaje.textContent = "Error de conexión.";
        mensaje.hidden = false;
      }
      boton.disabled = false;
      boton.textContent = "Vincular seleccionados";
    }
  });
})();
