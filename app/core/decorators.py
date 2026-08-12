from functools import wraps

from flask import make_response, redirect, session, url_for

from app.core.auth import obtener_usuario_actual


def login_required(vista):
    @wraps(vista)
    def envoltura(*args, **kwargs):
        habia_sesion = "usuario_id" in session
        usuario = obtener_usuario_actual()

        if usuario is None:
            destino = (
                url_for("auth.login", expirada=1) if habia_sesion else url_for("auth.login")
            )
            return redirect(destino)

        respuesta = make_response(vista(*args, **kwargs))
        # Evita que el boton "Atras" del navegador muestre una pagina
        # privada cacheada despues de haber cerrado sesion.
        respuesta.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        respuesta.headers["Pragma"] = "no-cache"
        return respuesta

    return envoltura
