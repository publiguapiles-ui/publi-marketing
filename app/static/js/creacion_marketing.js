(function () {
  // Creacion de Marketing (Paso 4). Solo administra objetivo + brief --
  // nunca conecta con Meta ni genera contenido. El "wizard" son
  // preguntas numeradas en una sola pantalla con guardado del brief
  // completo y resumen automatico, en vez de pasos ocultos uno a uno
  // (no existia ningun patron de wizard en el resto del sistema).

  function crear(etiqueta, clases, texto) {
    const el = document.createElement(etiqueta);
    if (clases) el.className = clases;
    if (texto !== undefined) el.textContent = texto;
    return el;
  }

  // --- Pagina de lista: creacion de proyecto -----------------------------------------

  function inicializarLista() {
    const form = document.getElementById("form-nuevo-proyecto-marketing");
    if (!form) return;

    form.addEventListener("submit", async (evento) => {
      evento.preventDefault();
      const nombre = form.querySelector('[name="nombre"]').value;
      const mensaje = document.getElementById("nuevo-proyecto-marketing-mensaje");
      const boton = form.querySelector('button[type="submit"]');
      boton.disabled = true;
      try {
        const resp = await fetch(window.CM_PROYECTOS_CREAR_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ nombre }),
        });
        const datos = await resp.json();
        if (!datos.ok) {
          mensaje.hidden = false;
          mensaje.textContent = datos.error;
          boton.disabled = false;
          return;
        }
        window.location.href = window.CM_PROYECTOS_DETALLE_URL_BASE.replace("__ID__", datos.proyecto_id);
      } catch (err) {
        mensaje.hidden = false;
        mensaje.textContent = "Error de conexión al crear el proyecto.";
        boton.disabled = false;
      }
    });
  }

  // --- Pagina de detalle: brief -------------------------------------------------------

  // Convierte los campos "publico.ubicacion", "oferta.producto", etc.
  // en los sub-objetos que espera el servicio (actualizar_brief).
  function recolectarBrief(form) {
    const datosForm = new FormData(form);
    const payload = { publico: {}, oferta: {}, identidad_marca_brief: {} };
    for (const [clave, valor] of datosForm.entries()) {
      if (clave.includes(".")) {
        const [grupo, subclave] = clave.split(".");
        payload[grupo][subclave] = valor;
      } else {
        payload[clave] = valor;
      }
    }
    payload.sin_fecha_definida = form.querySelector('[name="sin_fecha_definida"]').checked;
    if (payload.presupuesto_produccion === "") payload.presupuesto_produccion = null;
    if (payload.presupuesto_pauta === "") payload.presupuesto_pauta = null;
    if (payload.fecha_inicio === "") payload.fecha_inicio = null;
    if (payload.fecha_fin === "") payload.fecha_fin = null;
    return payload;
  }

  async function guardarBrief(evento) {
    evento.preventDefault();
    const form = evento.target;
    const payload = recolectarBrief(form);

    const mensaje = document.getElementById("brief-mensaje");
    try {
      const resp = await fetch(window.CM_PROYECTO_BRIEF_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const datos = await resp.json();
      if (!datos.ok) {
        mensaje.hidden = false;
        mensaje.textContent = datos.error;
        return;
      }
      mensaje.hidden = true;
      cargarResumen();
    } catch (err) {
      mensaje.hidden = false;
      mensaje.textContent = "Error de conexión al guardar el brief.";
    }
  }

  const ETIQUETAS_MARCA = { nombre_comercial: "Nombre comercial", color_principal: "Color principal", color_secundario: "Color secundario", tono: "Tono", estilo: "Estilo", personalidad: "Personalidad", restricciones: "Restricciones" };
  const ETIQUETAS_PUBLICO = { ubicacion: "Ubicación", edad: "Edad", genero: "Género", tipo_cliente: "Tipo de cliente", intereses: "Intereses", necesidades: "Necesidades", problema: "Problema", comportamiento: "Comportamiento", relacion_marca: "Relación con la marca" };
  const ETIQUETAS_OFERTA = { producto: "Producto", servicio: "Servicio", oferta: "Oferta", precio: "Precio", promocion: "Promoción", beneficio_principal: "Beneficio principal", diferenciador: "Diferenciador" };

  function renderSubcampos(obj, etiquetas) {
    const entradas = Object.entries(obj || {}).filter(([, v]) => v);
    if (!entradas.length) return "Sin definir";
    return entradas.map(([clave, valor]) => `${etiquetas[clave] || clave}: ${valor}`).join(" · ");
  }

  function agregarFila(dl, titulo, valor) {
    dl.appendChild(crear("dt", null, titulo));
    dl.appendChild(crear("dd", null, valor || "Sin definir"));
  }

  function renderResumen(resumen) {
    const dl = document.getElementById("cm-resumen");
    if (!dl) return;
    dl.innerHTML = "";
    agregarFila(dl, "Objetivo", resumen.objetivo.etiqueta ? `${resumen.objetivo.etiqueta}${resumen.objetivo.detalle ? " — " + resumen.objetivo.detalle : ""}` : null);
    agregarFila(dl, "Público", renderSubcampos(resumen.publico, ETIQUETAS_PUBLICO));
    agregarFila(dl, "Oferta", renderSubcampos(resumen.oferta, ETIQUETAS_OFERTA));
    agregarFila(dl, "Mensaje principal", resumen.mensaje_principal);
    agregarFila(dl, "Acción deseada", resumen.accion_deseada.etiqueta ? `${resumen.accion_deseada.etiqueta}${resumen.accion_deseada.detalle ? " — " + resumen.accion_deseada.detalle : ""}` : null);
    agregarFila(dl, "Presupuesto de producción", resumen.presupuesto.produccion);
    agregarFila(dl, "Presupuesto de pauta", resumen.presupuesto.pauta);
    agregarFila(dl, "Plazo", resumen.plazo);
    agregarFila(dl, "Marca", renderSubcampos(resumen.marca, ETIQUETAS_MARCA));
    agregarFila(dl, "Información adicional", resumen.informacion_adicional);
  }

  function renderCamposFaltantes(faltantes) {
    const cont = document.getElementById("cm-campos-faltantes");
    if (!cont) return;
    cont.innerHTML = "";
    if (!faltantes || !faltantes.length) return;
    const lista = crear("ul", "perfil-nota");
    faltantes.forEach((f) => lista.appendChild(crear("li", null, f)));
    cont.appendChild(lista);
  }

  async function cargarResumen() {
    try {
      const resp = await fetch(window.CM_PROYECTO_RESUMEN_URL);
      const datos = await resp.json();
      if (!datos.ok) return;
      renderResumen(datos.resumen);
      renderCamposFaltantes(datos.campos_faltantes);
    } catch (err) {
      // El formulario ya se guardo; el resumen se puede recargar despues.
    }
  }

  async function confirmarBrief() {
    const mensaje = document.getElementById("cm-confirmar-mensaje");
    try {
      const resp = await fetch(window.CM_PROYECTO_CONFIRMAR_URL, { method: "POST" });
      const datos = await resp.json();
      if (!datos.ok) {
        mensaje.hidden = false;
        mensaje.textContent = datos.error;
        return;
      }
      mensaje.hidden = true;
      const badge = document.getElementById("cm-estado-badge");
      badge.className = `estado-badge cm-estado-proyecto-${datos.proyecto.estado}`;
      badge.textContent = datos.proyecto.estado;
    } catch (err) {
      mensaje.hidden = false;
      mensaje.textContent = "Error de conexión al confirmar el brief.";
    }
  }

  async function pedirAyudaIA() {
    const boton = document.getElementById("cm-boton-ayuda-ia");
    const cont = document.getElementById("cm-sugerencia-ia");
    boton.disabled = true;
    try {
      const resp = await fetch(window.CM_PROYECTO_IA_AYUDA_URL, { method: "POST" });
      const datos = await resp.json();
      cont.hidden = false;
      cont.textContent = datos.ok ? datos.sugerencia : datos.error;
    } catch (err) {
      cont.hidden = false;
      cont.textContent = "Error de conexión al pedir ayuda a la IA.";
    }
    boton.disabled = false;
  }

  function inicializarDetalle() {
    const formBrief = document.getElementById("form-brief");
    if (formBrief) formBrief.addEventListener("submit", guardarBrief);

    const botonConfirmar = document.getElementById("cm-boton-confirmar");
    if (botonConfirmar) botonConfirmar.addEventListener("click", confirmarBrief);

    const botonAyudaIA = document.getElementById("cm-boton-ayuda-ia");
    if (botonAyudaIA) botonAyudaIA.addEventListener("click", pedirAyudaIA);

    cargarResumen();
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (window.CM_PROYECTOS_CREAR_URL) inicializarLista();
    if (window.CM_PROYECTO_ID) inicializarDetalle();
  });
})();
