from flask import session

# La verificacion real de tokens de Supabase Auth (login/logout/sesion)
# se implementa en el siguiente paso. Por ahora este modulo solo expone
# el punto de acceso que usaran los decoradores y las plantillas, para
# que el resto de la arquitectura (layout, navegacion) ya pueda apoyarse
# en el sin tener que cambiar despues.


def obtener_usuario_actual():
    """Devuelve el id del usuario autenticado en la sesion actual, o None."""
    return session.get("usuario_id")
