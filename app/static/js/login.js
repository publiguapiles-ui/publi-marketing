const formulario = document.getElementById("form-login");
const boton = document.getElementById("boton-login");

if (formulario && boton) {
  formulario.addEventListener("submit", () => {
    boton.disabled = true;
    boton.textContent = "Iniciando sesión...";
  });
}
