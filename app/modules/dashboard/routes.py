from flask import Blueprint, render_template

from app.core.decorators import login_required

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@dashboard_bp.get("/")
@login_required
def index():
    return render_template("dashboard/index.html")
