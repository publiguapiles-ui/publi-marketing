from functools import wraps

from flask import redirect, url_for

from app.core.auth import obtener_usuario_actual

# Definido y listo para usarse, pero deliberadamente NO aplicado todavia
# a las rutas de los modulos: el login real se construye en el siguiente
# paso, y aplicarlo ahora dejaria toda la navegacion inaccesible sin
# forma de autenticarse. Se conecta a las rutas cuando el login exista.


def login_required(vista):
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if obtener_usuario_actual() is None:
            return redirect(url_for("auth.login"))
        return vista(*args, **kwargs)

    return envoltura
