(function () {
  // Configuracion de API WhatsApp: probar conexion real contra Meta y
  // regenerar el Verify Token. Nunca envia ni muestra el Access Token.

  async function probarConexion() {
    const boton = document.getElementById("ww-boton-probar");
    const resultado = document.getElementById("ww-resultado-prueba");
    boton.disabled = true;
    resultado.hidden = false;
    resultado.textContent = "Probando…";
    try {
      const resp = await fetch(window.WW_PROBAR_CONEXION_URL, { method: "POST" });
      const datos = await resp.json();
      resultado.textContent = datos.ok ? "CONEXIÓN CORRECTA" : `ERROR DE CONEXIÓN — ${datos.mensaje}`;
    } catch (err) {
      resultado.textContent = "ERROR DE CONEXIÓN — no se pudo contactar al servidor.";
    }
    boton.disabled = false;
  }

  async function regenerarToken() {
    if (!confirm("Esto invalida el Verify Token actual de inmediato. Tendrás que actualizarlo también en Meta App Dashboard antes de que el webhook vuelva a validar. ¿Continuar?")) return;
    try {
      const resp = await fetch(window.WW_REGENERAR_TOKEN_URL, { method: "POST" });
      const datos = await resp.json();
      if (datos.ok) {
        window.location.reload();
      } else {
        alert(datos.error);
      }
    } catch (err) {
      alert("Error de conexión al regenerar el token.");
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const botonProbar = document.getElementById("ww-boton-probar");
    if (botonProbar) botonProbar.addEventListener("click", probarConexion);

    const botonRegenerar = document.getElementById("ww-boton-regenerar");
    if (botonRegenerar) botonRegenerar.addEventListener("click", regenerarToken);
  });
})();
