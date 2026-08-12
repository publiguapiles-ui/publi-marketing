"""Procesamiento masivo de fotografias por sesion (Paso 10).

Una SesionFotografica NO es una segunda galeria ni un segundo sistema
de derivados: agrupa y da seguimiento a ejecuciones de
app/services/derivados.py (el mismo que ya usan las rutas individuales
de "Mejorar fotografia" y "Generar formatos") sobre fotografias que ya
viven en app.models.Fotografia, dentro de un ProyectoFotografico
existente.

Disciplina importante: TODO el trabajo real de una fotografia se
ejecuta exclusivamente a traves de `app.services.tareas.encolar()` --
nunca se llama directo. Hoy `encolar()` ejecuta de forma sincrona (ver
ese modulo), pero ninguna funcion de aqui asume eso: cada llamada a
`encolar()` recibe solo IDs (nunca objetos ORM ya cargados en closure),
exactamente como lo necesitaria un worker real que reciba la tarea por
separado. El dia que `encolar()` empuje a una cola de verdad, este
modulo no tiene que reescribirse -- solo dejaria de poder devolver el
resultado en el mismo request, y las rutas ya estan escritas para
releer el estado desde la base de datos en vez de confiar en un valor
de retorno.
"""

import time

ESTADOS_ITEM = ["pendiente", "procesando", "completada", "error"]


def crear_sesion(empresa_id, proyecto_id, nombre, fotografia_ids, preset_id, usuario_id, logo_id=None, aplicacion_logo="sin_logo", posicion_logo="inferior_derecha", opacidad_logo=0.8, formatos=None):
    """Crea la sesion y un SesionItem por cada fotografia (estado
    pendiente). No procesa nada todavia -- eso lo dispara
    `procesar_siguiente_item` explicitamente, una fotografia a la vez.
    """
    from app.extensions import db
    from app.models import SesionFotografica, SesionItem

    formatos = formatos or []
    sesion = SesionFotografica(
        empresa_id=empresa_id,
        proyecto_id=proyecto_id,
        nombre=nombre,
        preset_id=preset_id,
        logo_id=logo_id,
        aplicacion_logo=aplicacion_logo,
        posicion_logo=posicion_logo if aplicacion_logo != "sin_logo" else None,
        opacidad_logo=opacidad_logo if aplicacion_logo != "sin_logo" else None,
        formatos_seleccionados=",".join(formatos),
        estado="pendiente",
        total_fotografias=len(fotografia_ids),
        creado_por=usuario_id,
    )
    db.session.add(sesion)
    db.session.flush()  # asigna sesion.id sin cerrar la transaccion

    for fotografia_id in fotografia_ids:
        db.session.add(SesionItem(sesion_id=sesion.id, fotografia_id=fotografia_id, estado="pendiente"))
    db.session.commit()
    return sesion


def obtener_sesion(empresa_id, sesion_id):
    """Devuelve la sesion solo si pertenece a la empresa indicada --
    mismo patron de aislamiento que el resto de Photo Studio."""
    from app.extensions import db
    from app.models import SesionFotografica

    return db.session.query(SesionFotografica).filter_by(id=sesion_id, empresa_id=empresa_id).first()


def obtener_items_sesion(sesion_id):
    from app.extensions import db
    from app.models import SesionItem

    return db.session.query(SesionItem).filter_by(sesion_id=sesion_id).order_by(SesionItem.id).all()


def _siguiente_item_pendiente(sesion_id):
    from app.extensions import db
    from app.models import SesionItem

    return (
        db.session.query(SesionItem)
        .filter_by(sesion_id=sesion_id, estado="pendiente")
        .order_by(SesionItem.id)
        .first()
    )


def _contexto_sesion(sesion):
    """Dict de promedios de la sesion en el formato que
    app.services.procesamiento.mejorar_fotografia espera, o None si la
    sesion todavia no se analizo."""
    if sesion.analisis_brillo_promedio is None:
        return None
    return {
        "brillo_promedio": sesion.analisis_brillo_promedio,
        "contraste_promedio": sesion.analisis_contraste_promedio,
        "saturacion_promedio": sesion.analisis_saturacion_promedio,
    }


def analizar_sesion(sesion_id):
    """Analiza TODAS las fotografias de la sesion (Paso 10: sin muestreo
    en esta primera implementacion) para calcular las estadisticas
    agregadas de consistencia. Se invoca via encolar() -- una sola
    llamada hace todo el analisis; el tiempo real se mide y se reporta,
    no se oculta.
    """
    from app.extensions import db
    from app.models import SesionFotografica
    from app.services.procesamiento import analizar_imagen, cargar_imagen
    from app.services.storage import BUCKET_FOTOGRAFIAS, descargar_archivo

    def _tarea():
        sesion = db.session.get(SesionFotografica, sesion_id)
        if sesion is None:
            return None

        inicio = time.time()
        sesion.estado = "analizando"
        db.session.commit()

        items = obtener_items_sesion(sesion.id)
        brillos, contrastes, saturaciones, temperaturas = [], [], [], []

        for item in items:
            foto = item.fotografia
            try:
                bytes_originales = descargar_archivo(BUCKET_FOTOGRAFIAS, foto.ruta_storage)
                imagen = cargar_imagen(bytes_originales)
                # Copia reducida para el analisis (Paso 10: "usar una
                # version reducida... cuando sea posible") -- el
                # resultado final de cada foto siempre se procesa
                # despues desde el archivo original completo, nunca
                # desde esta miniatura.
                lado_mayor = max(imagen.size)
                if lado_mayor > 640:
                    escala = 640 / lado_mayor
                    imagen = imagen.resize((max(1, round(imagen.width * escala)), max(1, round(imagen.height * escala))))
                analisis = analizar_imagen(imagen)
                brillos.append(analisis["brillo_promedio"])
                contrastes.append(analisis["contraste"])
                saturaciones.append(analisis["saturacion_media"])
                temperaturas.append(analisis["temperatura"])
            except Exception:
                # Una foto que no se puede leer no debe tumbar el
                # analisis de toda la sesion -- simplemente no aporta
                # a los promedios; su propio procesamiento fallara mas
                # tarde y quedara registrado como error individual.
                continue

        if brillos:
            sesion.analisis_brillo_promedio = sum(brillos) / len(brillos)
            sesion.analisis_contraste_promedio = sum(contrastes) / len(contrastes)
            sesion.analisis_saturacion_promedio = sum(saturaciones) / len(saturaciones)
            sesion.analisis_temperatura_predominante = max(set(temperaturas), key=temperaturas.count)

        sesion.analisis_duracion_segundos = round(time.time() - inicio, 3)
        sesion.estado = "pendiente"
        db.session.commit()
        return sesion

    from app.services.tareas import encolar

    return encolar(_tarea)


def _generar_salidas_item(sesion, foto):
    """Genera todas las salidas seleccionadas para una fotografia
    (mejora automatica y/o formatos). Devuelve la lista de derivados
    creados. Reutiliza integramente app.services.derivados -- ningun
    sistema de derivados nuevo.
    """
    from app.services.derivados import crear_formato, crear_mejora_automatica

    tipos = [t for t in sesion.formatos_seleccionados.split(",") if t]
    derivados = []
    contexto = _contexto_sesion(sesion)

    if "mejora_automatica" in tipos:
        derivado = crear_mejora_automatica(
            sesion.empresa_id, sesion.proyecto_id, foto, sesion.creado_por,
            preset=sesion.preset, contexto_sesion=contexto, sesion_id=sesion.id,
        )
        derivados.append(derivado)

    for tipo in tipos:
        if tipo == "mejora_automatica":
            continue
        derivado = crear_formato(
            sesion.empresa_id, sesion.proyecto_id, foto, sesion.creado_por, tipo,
            logo=sesion.logo, aplicacion=sesion.aplicacion_logo or "sin_logo",
            posicion=sesion.posicion_logo or "inferior_derecha", opacidad=sesion.opacidad_logo or 0.8,
            modo="auto", sesion_id=sesion.id,
        )
        derivados.append(derivado)

    return derivados


def _procesar_item(sesion_id, item_id):
    """La unidad de trabajo real de una sesion: procesar UNA fotografia
    (todas sus salidas seleccionadas). Nunca se llama directo -- ver
    `procesar_siguiente_item`, que es quien la pasa a `encolar()`.
    """
    from app.extensions import db
    from datetime import datetime, timezone
    from app.models import SesionFotografica, SesionItem

    item = db.session.get(SesionItem, item_id)
    sesion = db.session.get(SesionFotografica, sesion_id)
    if item is None or sesion is None:
        return None

    item.estado = "procesando"
    item.iniciado_en = datetime.now(timezone.utc)
    db.session.commit()

    try:
        derivados = _generar_salidas_item(sesion, item.fotografia)
        fallidos = [d for d in derivados if d.estado == "error"]
        if fallidos:
            item.estado = "error"
            item.error_mensaje = "; ".join(sorted({d.error_mensaje or "error desconocido" for d in fallidos}))[:500]
            sesion.errores += 1
        else:
            item.estado = "completada"
            sesion.completadas += 1
    except Exception as exc:
        item.estado = "error"
        item.error_mensaje = str(exc)[:500]
        sesion.errores += 1

    item.finalizado_en = datetime.now(timezone.utc)
    db.session.commit()
    return item


def procesar_siguiente_item(sesion_id):
    """Procesa la siguiente fotografia pendiente de la sesion (una sola).
    Pensado para llamarse repetidamente -- hoy desde un bucle
    secuencial en el cliente (una peticion HTTP por foto, igual que ya
    hacen "Mejorar fotografias" y "Generar formatos"); el dia que
    exista una cola real, quien dispare esta funcion puede cambiar sin
    que ella misma cambie.

    Devuelve (item_procesado_o_None, sesion_terminada: bool).
    """
    from app.extensions import db
    from datetime import datetime, timezone
    from app.models import SesionFotografica
    from app.services.tareas import encolar

    sesion = db.session.get(SesionFotografica, sesion_id)
    if sesion is None:
        return None, True

    if sesion.estado == "cancelada":
        return None, True

    item = _siguiente_item_pendiente(sesion_id)
    if item is None:
        # No quedan fotografias pendientes: cerrar la sesion.
        if sesion.estado not in ("completada", "completada_con_errores", "cancelada", "error"):
            sesion.estado = "completada_con_errores" if sesion.errores > 0 else "completada"
            sesion.finalizado_en = datetime.now(timezone.utc)
            db.session.commit()
        return None, True

    if sesion.estado not in ("procesando",):
        sesion.estado = "procesando"
        if sesion.iniciado_en is None:
            sesion.iniciado_en = datetime.now(timezone.utc)
        db.session.commit()

    item_id = item.id
    encolar(_procesar_item, sesion_id, item_id)

    # Se relee desde la base de datos a proposito (no se confia en un
    # valor de retorno de encolar()): hoy encolar() es sincrono y ya
    # habria terminado, pero releer es lo que seguiria funcionando
    # igual si mas adelante encolar() solo encolara la tarea y un
    # worker aparte la completara despues.
    db.session.refresh(sesion)
    item_actualizado = db.session.get(type(item), item_id)

    quedan_pendientes = _siguiente_item_pendiente(sesion_id) is not None
    if not quedan_pendientes and sesion.estado not in ("completada", "completada_con_errores", "cancelada", "error"):
        sesion.estado = "completada_con_errores" if sesion.errores > 0 else "completada"
        sesion.finalizado_en = datetime.now(timezone.utc)
        db.session.commit()

    return item_actualizado, not quedan_pendientes


def cancelar_sesion(sesion_id):
    """Marca la sesion como cancelada. La fotografia que ya este en
    curso termina (no se puede detener a la mitad de forma segura sin
    dejar un derivado a medio subir); ninguna fotografia posterior
    arranca. Nada de lo ya completado se borra.
    """
    from app.extensions import db
    from datetime import datetime, timezone
    from app.models import SesionFotografica

    sesion = db.session.get(SesionFotografica, sesion_id)
    if sesion is None:
        return None
    if sesion.estado in ("completada", "completada_con_errores", "error"):
        return sesion  # ya termino, cancelar no tiene efecto

    sesion.estado = "cancelada"
    sesion.finalizado_en = datetime.now(timezone.utc)
    db.session.commit()
    return sesion
