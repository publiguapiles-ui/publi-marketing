(function () {
  const botonSincronizar = document.getElementById("boton-sincronizar");
  const mensaje = document.getElementById("sincronizar-mensaje");

  if (botonSincronizar) {
    botonSincronizar.addEventListener("click", async () => {
      botonSincronizar.disabled = true;
      botonSincronizar.textContent = "Sincronizando...";
      if (mensaje) {
        mensaje.hidden = true;
      }
      try {
        const resp = await fetch(window.DM_SINCRONIZAR_URL, { method: "POST" });
        const datos = await resp.json();
        if (datos.ok) {
          window.location.reload();
        } else if (mensaje) {
          mensaje.textContent = datos.error || "No se pudo sincronizar.";
          mensaje.hidden = false;
        }
      } catch (err) {
        if (mensaje) {
          mensaje.textContent = "Error de conexión al sincronizar.";
          mensaje.hidden = false;
        }
      }
      botonSincronizar.disabled = false;
      botonSincronizar.textContent = "Sincronizar ahora";
    });
  }

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
})();
