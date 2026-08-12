from flask import Blueprint, render_template

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

# Login/logout reales con Supabase Auth se implementan en el siguiente
# paso. Estas rutas existen ya para que la navegacion y el decorador
# login_required tengan un destino valido (url_for("auth.login")).


@auth_bp.get("/login")
def login():
    return render_template("auth/login.html")


@auth_bp.get("/logout")
def logout():
    return render_template("auth/login.html")
