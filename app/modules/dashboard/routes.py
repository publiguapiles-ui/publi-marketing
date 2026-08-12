from flask import Blueprint, render_template

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@dashboard_bp.get("/")
def index():
    return render_template("dashboard/index.html")
