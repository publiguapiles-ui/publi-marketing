(function () {
  const boton = document.getElementById("boton-mejorar");
  if (!boton || !window.PS_MEJORAR_URL) return;

  const zonaConfirmar = document.getElementById("zona-confirmar");
  const zonaProcesando = document.getElementById("zona-procesando");
  const zonaResultado = document.getElementById("zona-resultado");
  const textoResultado = document.getElementById("texto-resultado");
  const enlaceResultado = document.getElementById("enlace-resultado");

  boton.addEventListener("click", () => {
    zonaConfirmar.hidden = true;
    zonaProcesando.hidden = false;

    fetch(window.PS_MEJORAR_URL, { method: "POST" })
      .then((r) => r.json())
      .then((datos) => {
        zonaProcesando.hidden = true;
        zonaResultado.hidden = false;
        if (datos.ok) {
          textoResultado.textContent = "Fotografía mejorada.";
          enlaceResultado.href = datos.url_resultado;
          enlaceResultado.hidden = false;
        } else {
          textoResultado.textContent = "Error al procesar: " + (datos.error || "intenta de nuevo.");
        }
      })
      .catch(() => {
        zonaProcesando.hidden = true;
        zonaResultado.hidden = false;
        textoResultado.textContent = "Error de conexión. Intenta de nuevo.";
      });
  });
})();
