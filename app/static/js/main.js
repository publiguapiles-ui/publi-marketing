const boton = document.getElementById("menu-toggle");
const sidebar = document.getElementById("sidebar");

if (boton && sidebar) {
  boton.addEventListener("click", () => {
    sidebar.classList.toggle("abierto");
  });
}
