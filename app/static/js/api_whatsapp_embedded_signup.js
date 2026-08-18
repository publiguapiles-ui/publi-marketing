// Registro insertado de WhatsApp (Embedded Signup), incluida
// Coexistencia -- ver la documentacion oficial:
// https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/implementation
//
// featureType: "whatsapp_business_app_onboarding" es lo que hace que
// Meta ofrezca "conectar tu cuenta existente" (Coexistencia) cuando
// detecta que el numero ya esta activo en la app de WhatsApp Business
// normal, en vez de rechazarlo con "este numero ya esta registrado".
(function () {
  let datosSesion = null; // { phone_number_id, waba_id } -- llega por window.message
  let codigoIntercambiable = null; // llega por el callback de FB.login

  function mostrarEstado(mensaje, esError) {
    const el = document.getElementById("ww-es-estado");
    if (!el) return;
    el.textContent = mensaje;
    el.hidden = false;
    el.classList.toggle("estado-error", !!esError);
  }

  async function completarEnServidor() {
    if (!codigoIntercambiable || !datosSesion || !datosSesion.phone_number_id || !datosSesion.waba_id) return;

    mostrarEstado("Conectando con WhatsApp…", false);
    try {
      const resp = await fetch(window.WW_EMBEDDED_SIGNUP_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          code: codigoIntercambiable,
          phone_number_id: datosSesion.phone_number_id,
          waba_id: datosSesion.waba_id,
        }),
      });
      const datos = await resp.json();
      if (datos.ok) {
        mostrarEstado("¡Conectado! Recargando…", false);
        window.location.reload();
      } else {
        mostrarEstado(datos.error || "No se pudo completar la conexión.", true);
      }
    } catch (err) {
      mostrarEstado("No se pudo contactar al servidor. Intenta de nuevo.", true);
    }
  }

  window.fbAsyncInit = function () {
    FB.init({ appId: window.WW_META_APP_ID, autoLogAppEvents: true, xfbml: true, version: window.WW_META_API_VERSION });
  };

  window.addEventListener("message", (event) => {
    if (!event.origin.endsWith("facebook.com")) return;
    try {
      const datos = JSON.parse(event.data);
      if (datos.type !== "WA_EMBEDDED_SIGNUP") return;
      if (datos.event === "CANCEL") {
        if (datos.data && datos.data.error_message) mostrarEstado(datos.data.error_message, true);
        return;
      }
      if (datos.data) {
        datosSesion = { phone_number_id: datos.data.phone_number_id, waba_id: datos.data.waba_id };
        completarEnServidor();
      }
    } catch (err) {
      // Mensajes que no son JSON (p.ej. de otros scripts en la pagina) -- se ignoran.
    }
  });

  window.launchWhatsAppSignup = function () {
    if (typeof FB === "undefined") {
      mostrarEstado("El SDK de Facebook todavía no cargó. Intenta de nuevo en unos segundos.", true);
      return;
    }
    FB.login(
      (respuesta) => {
        if (respuesta.authResponse) {
          codigoIntercambiable = respuesta.authResponse.code;
          completarEnServidor();
        }
      },
      {
        config_id: window.WW_META_WHATSAPP_CONFIG_ID,
        response_type: "code",
        override_default_response_type: true,
        extras: { setup: {}, featureType: "whatsapp_business_app_onboarding", sessionInfoVersion: "3" },
      }
    );
  };
})();
