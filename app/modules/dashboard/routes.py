from flask import Blueprint, render_template

from app.core.decorators import login_required
from app.core.empresas import obtener_empresa_activa

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@dashboard_bp.get("/")
@login_required
def index():
    empresa_activa, rol_activo = obtener_empresa_activa()
    return render_template("dashboard/index.html", empresa_activa=empresa_activa, rol_activo=rol_activo)
