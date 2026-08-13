import traceback
from collections import deque
from datetime import datetime, timezone

from flask import jsonify, render_template, request

# Diagnostico TEMPORAL (Paso 11.1): captura en memoria de los ultimos
# errores 500 no controlados, con traceback completo, para poder
# investigar la causa raiz de un 500 real en produccion sin tener
# acceso al dashboard de logs de Railway. Se expone unicamente via
# /diagnostico/ultimo-error, protegido por sesion autenticada del
# usuario admin. Se debe retirar (este modulo completo vuelve a su
# version minima) una vez identificada y corregida la causa raiz --
# no es un mecanismo de logging permanente.
_ULTIMOS_ERRORES = deque(maxlen=5)

_PATRONES_SECRETOS = (
    "database_url", "postgresql://", "postgres://", "supabase",
    "sslmode", "service_role", "secret_key", "authorization",
    "bearer ", "password=", "apikey", "api_key",
)


def _redactar(texto):
    if not texto:
        return texto
    lineas = texto.splitlines()
    resultado = []
    for linea in lineas:
        if any(patron in linea.lower() for patron in _PATRONES_SECRETOS):
            resultado.append("[linea redactada: puede contener datos sensibles]")
        else:
            resultado.append(linea)
    return "\n".join(resultado)


def registrar_manejadores_error(app):
    @app.errorhandler(404)
    def no_encontrado(error):
        return render_template("errores/404.html"), 404

    @app.errorhandler(500)
    def error_interno(error):
        from app.extensions import db

        tb_texto = traceback.format_exc()
        _ULTIMOS_ERRORES.append(
            {
                "cuando": datetime.now(timezone.utc).isoformat(),
                "ruta": request.path,
                "metodo": request.method,
                "tipo": type(error).__name__,
                "mensaje": _redactar(str(error))[:1000],
                "traceback": _redactar(tb_texto)[:6000],
            }
        )
        app.logger.exception("Error no controlado en %s", request.path)

        # Regla explicita (Paso 11.1): exito -> commit; error -> rollback.
        # Sin esto, una sesion de SQLAlchemy que quedo con una
        # transaccion fallida podia reutilizarse (mismo proceso,
        # gunicorn con un solo worker sincrono) en la siguiente
        # peticion, arrastrando el error a peticiones que en si mismas
        # eran validas.
        try:
            db.session.rollback()
        except Exception:
            app.logger.exception("Fallo el rollback tras un error 500")

        return render_template("errores/500.html"), 500

    @app.get("/diagnostico/ultimo-error")
    def diagnostico_ultimo_error():
        from app.core.auth import obtener_usuario_actual

        usuario = obtener_usuario_actual()
        if usuario is None or usuario.get("email") != "admin@publimarketing.local":
            return no_encontrado(None)

        return jsonify(list(_ULTIMOS_ERRORES))
