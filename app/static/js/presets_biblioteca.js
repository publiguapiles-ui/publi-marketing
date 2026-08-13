(function () {
  document.querySelectorAll(".ps-boton-favorito").forEach((boton) => {
    boton.addEventListener("click", async () => {
      const id = boton.dataset.presetId;
      const url = window.PS_FAVORITO_URL_BASE.replace("__ID__", id);
      boton.disabled = true;
      try {
        const resp = await fetch(url, { method: "POST" });
        const datos = await resp.json();
        if (datos.ok) {
          // La tarjeta puede moverse de grupo (favoritos <-> sistema/mios)
          // -- mas simple y correcto recargar que reordenar en el cliente.
          window.location.reload();
        }
      } catch (err) {
        alert("No se pudo actualizar el favorito (error de conexión).");
        boton.disabled = false;
      }
    });
  });

  document.querySelectorAll(".ps-boton-eliminar-preset").forEach((boton) => {
    boton.addEventListener("click", async () => {
      const id = boton.dataset.presetId;
      const nombre = boton.dataset.presetNombre;
      if (!confirm(`¿Eliminar el preset "${nombre}"? Las fotografías ya procesadas con él no se ven afectadas.`)) {
        return;
      }
      const url = window.PS_ELIMINAR_URL_BASE.replace("__ID__", id);
      try {
        const resp = await fetch(url, { method: "POST" });
        const datos = await resp.json();
        if (datos.ok) {
          window.location.reload();
        } else {
          alert(datos.error || "No se pudo eliminar el preset.");
        }
      } catch (err) {
        alert("No se pudo eliminar el preset (error de conexión).");
      }
    });
  });
})();
