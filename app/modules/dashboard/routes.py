from flask import Blueprint, render_template

from app.core.decorators import login_required
from app.core.empresas import obtener_empresa_activa
from app.services.marca import obtener_identidad, obtener_logo_principal

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@dashboard_bp.get("/")
@login_required
def index():
    empresa_activa, rol_activo = obtener_empresa_activa()

    identidad = None
    logo_principal = None
    if empresa_activa is not None:
        identidad = obtener_identidad(empresa_activa.id)
        logo_principal = obtener_logo_principal(empresa_activa.id)

    return render_template(
        "dashboard/index.html",
        empresa_activa=empresa_activa,
        rol_activo=rol_activo,
        identidad=identidad,
        logo_principal=logo_principal,
    )
