from flask import render_template


def registrar_manejadores_error(app):
    @app.errorhandler(404)
    def no_encontrado(error):
        return render_template("errores/404.html"), 404

    @app.errorhandler(500)
    def error_interno(error):
        return render_template("errores/500.html"), 500
