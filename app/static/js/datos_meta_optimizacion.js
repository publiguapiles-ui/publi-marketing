(function () {
  // Centro de optimizacion de pauta (Paso 11). No calcula ningun KPI ni
  // detecta ninguna señal -- solo administra los filtros (recarga de
  // pagina, mismo patron que el selector de empresa de base.html) y la
  // comparacion manual de 2 filas ya renderizadas por el servidor.

  document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("opt-filtros");
    if (!form) return;

    const selectCuenta = document.getElementById("opt-cuenta");
    const selectCampana = document.getElementById("opt-campana");
    const selectConjunto = document.getElementById("opt-conjunto");
    const selectPeriodo = document.getElementById("opt-periodo");

    if (selectCuenta) {
      selectCuenta.addEventListener("change", () => {
        if (selectCampana) selectCampana.value = "";
        if (selectConjunto) selectConjunto.value = "";
        form.submit();
      });
    }
    if (selectCampana) {
      selectCampana.addEventListener("change", () => {
        if (selectConjunto) selectConjunto.value = "";
        form.submit();
      });
    }
    if (selectConjunto) selectConjunto.addEventListener("change", () => form.submit());
    if (selectPeriodo) selectPeriodo.addEventListener("change", () => form.submit());

    const botonComparar = document.getElementById("opt-boton-comparar");
    if (botonComparar) {
      botonComparar.addEventListener("click", () => {
        const marcadas = Array.from(document.querySelectorAll(".opt-check-comparar:checked"));
        const resultado = document.getElementById("opt-resultado-comparar");
        if (marcadas.length !== 2) {
          resultado.hidden = false;
          resultado.textContent = "Selecciona exactamente 2 filas para comparar.";
          return;
        }
        const [a, b] = marcadas.map((el) => ({ nombre: el.dataset.nombre, costo: el.dataset.costo === "" ? null : Number(el.dataset.costo) }));
        resultado.hidden = false;
        if (a.costo === null || b.costo === null) {
          resultado.textContent = "No hay costo por resultado disponible para una de las dos entidades seleccionadas -- no se puede comparar.";
          return;
        }
        const menor = a.costo <= b.costo ? a : b;
        const mayor = a.costo <= b.costo ? b : a;
        resultado.textContent = `Conclusión: ${menor.nombre} presenta menor costo por resultado (${menor.costo}) que ${mayor.nombre} (${mayor.costo}).`;
      });
    }
  });
})();
