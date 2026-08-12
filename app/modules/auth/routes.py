from flask import Blueprint, redirect, render_template, request, url_for
from supabase import AuthApiError

from app.core.auth import cerrar_sesion, iniciar_sesion, obtener_cliente_auth, obtener_usuario_actual
from app.core.decorators import login_required

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if obtener_usuario_actual() is not None:
        return redirect(url_for("dashboard.index"))

    error = None
    email_enviado = ""
    sesion_expirada = request.args.get("expirada") == "1"

    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        email_enviado = email

        cliente = obtener_cliente_auth()

        if not email or not password:
            error = "Ingresa tu correo y contraseña."
        elif cliente is None:
            error = "El servicio de autenticación no está disponible en este momento. Intenta más tarde."
        else:
            try:
                respuesta = cliente.auth.sign_in_with_password({"email": email, "password": password})
                iniciar_sesion(respuesta)
                return redirect(url_for("dashboard.index"))
            except AuthApiError:
                # Mensaje deliberadamente generico: no revela si el correo
                # existe, si el usuario esta deshabilitado, etc.
                error = "Correo o contraseña incorrectos."
            except Exception:
                error = "No se pudo conectar con el servicio de autenticación. Intenta de nuevo más tarde."

    return render_template(
        "auth/login.html",
        error=error,
        email=email_enviado,
        sesion_expirada=sesion_expirada and error is None,
    )


@auth_bp.post("/logout")
def logout():
    cliente = obtener_cliente_auth()
    if cliente is not None:
        try:
            cliente.auth.sign_out()
        except Exception:
            pass

    cerrar_sesion()

    respuesta = redirect(url_for("auth.login"))
    respuesta.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    respuesta.headers["Pragma"] = "no-cache"
    return respuesta


@auth_bp.get("/perfil")
@login_required
def perfil():
    return render_template("auth/perfil.html", usuario=obtener_usuario_actual())
