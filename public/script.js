document.getElementById("form-crear").addEventListener("submit", async (e) => {
  e.preventDefault();

  const nombre = document.getElementById("nombre").value;
  const contacto = document.getElementById("contacto").value;
  const fecha_hora = document.getElementById("fecha_hora").value;
  const resultado = document.getElementById("resultado-crear");

  resultado.textContent = "Creando...";

  try {
    const res = await fetch("/legacy/solicitudes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nombre, contacto, fecha_hora }),
    });
    const data = await res.json();

    if (!res.ok) {
      resultado.textContent = `Error: ${data.error || "no se pudo crear la solicitud"}`;
      return;
    }

    resultado.textContent = `Solicitud creada. Tu código de seguimiento es: ${data.codigo_seguimiento} (estado: ${data.estado})`;
  } catch (err) {
    resultado.textContent = `Error de conexión: ${err.message}`;
  }
});

document.getElementById("form-consultar").addEventListener("submit", async (e) => {
  e.preventDefault();

  const codigo = document.getElementById("codigo").value.trim();
  const resultado = document.getElementById("resultado-consultar");

  resultado.textContent = "Consultando...";

  try {
    const res = await fetch(`/legacy/solicitudes/${encodeURIComponent(codigo)}`);
    const data = await res.json();

    if (!res.ok) {
      resultado.textContent = `Error: ${data.error || "no se pudo consultar la solicitud"}`;
      return;
    }

    resultado.textContent =
      `Nombre: ${data.nombre}\n` +
      `Contacto: ${data.contacto}\n` +
      `Fecha y hora: ${data.fecha_hora}\n` +
      `Estado: ${data.estado}`;
  } catch (err) {
    resultado.textContent = `Error de conexión: ${err.message}`;
  }
});
