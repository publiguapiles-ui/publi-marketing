from flask import render_template


def registrar_manejadores_error(app):
    @app.errorhandler(404)
    def no_encontrado(error):
        return render_template("errores/404.html"), 404

    @app.errorhandler(500)
    def error_interno(error):
        # Regla explicita (Paso 11.1): exito -> commit; error ->
        # rollback. No era la causa raiz del 500 real investigado (ver
        # informe: presets.slug excedia VARCHAR(40) en Postgres), pero
        # sin esto una sesion de SQLAlchemy que queda con una
        # transaccion fallida podria reutilizarse en una peticion
        # posterior que en si misma era valida.
        from app.extensions import db

        try:
            db.session.rollback()
        except Exception:
            app.logger.exception("Fallo el rollback tras un error 500")

        return render_template("errores/500.html"), 500
