(function () {
  document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("csv-form");
    if (!form) return;

    const mensaje = document.getElementById("csv-mensaje");
    const resultado = document.getElementById("csv-resultado");
    const resumen = document.getElementById("csv-resumen");
    const advertencias = document.getElementById("csv-advertencias");

    form.addEventListener("submit", async (evento) => {
      evento.preventDefault();

      const cuentaId = document.getElementById("csv-cuenta").value;
      const archivo = document.getElementById("csv-archivo").files[0];
      if (!cuentaId || !archivo) return;

      const datos = new FormData();
      datos.append("cuenta_id", cuentaId);
      datos.append("archivo", archivo);

      const boton = form.querySelector("button[type=submit]");
      boton.disabled = true;
      boton.textContent = "Importando...";
      mensaje.hidden = true;
      resultado.hidden = true;

      try {
        const resp = await fetch(window.DM_IMPORTAR_CSV_URL, { method: "POST", body: datos });
        const cuerpo = await resp.json();

        if (!cuerpo.ok) {
          mensaje.hidden = false;
          mensaje.textContent = cuerpo.error || "No se pudo importar el archivo.";
        } else {
          resumen.textContent = `${cuerpo.filas_guardadas} de ${cuerpo.filas_totales} filas guardadas (${cuerpo.filas_omitidas} omitidas).`;
          advertencias.innerHTML = "";
          if (cuerpo.advertencias && cuerpo.advertencias.length) {
            const lista = document.createElement("ul");
            lista.className = "lista-simple";
            cuerpo.advertencias.forEach((texto) => {
              const li = document.createElement("li");
              li.textContent = texto;
              lista.appendChild(li);
            });
            advertencias.appendChild(lista);
          }
          resultado.hidden = false;
        }
      } catch (err) {
        mensaje.hidden = false;
        mensaje.textContent = "Error de conexión al importar el archivo.";
      }

      boton.disabled = false;
      boton.textContent = "Importar";
    });
  });
})();
