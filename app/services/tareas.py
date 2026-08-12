"""Abstraccion de tareas en segundo plano.

Hoy ejecuta la funcion directamente y de forma sincrona (dentro del
mismo request) porque todavia no hay una cola real configurada. El
punto de esta capa es que cuando exista una (RQ/Celery + un worker
separado), solo hay que cambiar `encolar` -- ningun modulo que llama a
`encolar()` necesita cambiar.
"""


def encolar(funcion, *args, **kwargs):
    """Ejecuta `funcion(*args, **kwargs)`. Sincrono por ahora."""
    return funcion(*args, **kwargs)
