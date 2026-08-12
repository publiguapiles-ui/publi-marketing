from flask import Blueprint, render_template


def crear_modulo_proximamente(slug, nombre, icono="🔧"):
    """Crea un Blueprint minimo con una pantalla "Proximamente".

    Se usa para reservar el lugar de los modulos que la arquitectura ya
    contempla pero que todavia no tienen funcionalidad real, sin
    duplicar el mismo Blueprint 12 veces ni simular funciones que no
    existen.
    """
    bp = Blueprint(slug, __name__, url_prefix=f"/{slug}")

    @bp.route("/")
    def index():
        return render_template("modulo_proximamente.html", nombre=nombre, icono=icono)

    return bp
