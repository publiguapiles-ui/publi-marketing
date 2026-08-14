"""Acciones controladas sobre Meta (Paso 12).

Unica capa de servicio para ESCRIBIR en Meta -- ninguna ruta llama a
MetaClient.post() directamente, todo pasa por aqui. Reutiliza
INTEGRAMENTE lo ya construido: app/services/meta/client.py (MetaClient,
nunca se duplica el cliente Graph API ni el manejo de errores HTTP),
app/services/meta/conexiones.py (obtener_cliente_para_empresa ya hace
la deteccion proactiva de token expirado del Paso 6) y
app/services/meta/errores.py (clasificacion + detalle tecnico del
Paso 6).

Flujo obligatorio, aplicado literalmente en el codigo (no solo en la
interfaz): ANALIZAR (Paso 8/11) -> PROPONER (crear_propuesta) ->
MOSTRAR CAMBIO (la propia fila, siempre visible) -> CONFIRMAR
(aprobar_propuesta, despues confirmacion=True explicito en
ejecutar_accion) -> EJECUTAR (ejecutar_accion) -> VERIFICAR
(ejecutar_accion vuelve a consultar Meta antes de marcar "ejecutada").
Ninguna funcion de este archivo ejecuta un cambio sin que el estado ya
sea "aprobada" Y se reciba `confirmacion=True` explicito -- ambos
GATES viven aqui, no solo en el front-end, para que no se puedan
saltar llamando directamente a la ruta.
"""

from datetime import datetime, timezone

from app.models import ORIGENES_ACCION_META, TIPOS_ACCION_META

TIPOS_ENTIDAD_CON_ACCIONES = ("campana", "conjunto_anuncios", "anuncio")

# Permiso de Meta necesario para CUALQUIER escritura (Paso 12, punto 7)
# -- agregado a SCOPES_PREDETERMINADOS en este mismo paso (ver
# auth_service.py). Una conexion creada ANTES del Paso 12 no lo tiene
# concedido todavia; se verifica explicitamente, nunca se asume.
PERMISO_REQUERIDO_ESCRITURA = "ads_management"


def validar_tipo_accion_para_entidad(entidad_tipo, tipo_accion):
    """None si la combinacion es valida, o un mensaje de error
    explicando por que no (Paso 12, punto 2: "no asumir que todos los
    tipos de campaña permiten exactamente las mismas operaciones").
    Un anuncio no tiene presupuesto propio en el modelo de Meta -- solo
    campañas y conjuntos lo tienen."""
    if tipo_accion not in TIPOS_ACCION_META:
        return "Tipo de acción inválido."
    if entidad_tipo not in TIPOS_ENTIDAD_CON_ACCIONES:
        return f'No hay acciones soportadas para el tipo de recurso "{entidad_tipo}".'
    if tipo_accion == "modificar_presupuesto" and entidad_tipo == "anuncio":
        return "Un anuncio no tiene presupuesto propio en Meta -- modifica el conjunto o la campaña."
    return None


def _leer_valor_actual(entidad, tipo_accion):
    """Lee el valor actual desde la copia YA sincronizada (nunca
    inventado) -- se vuelve a confirmar en vivo contra Meta justo antes
    de escribir, ver ejecutar_accion()."""
    if tipo_accion in ("pausar", "activar"):
        return entidad.estado
    if tipo_accion == "modificar_presupuesto":
        atributos = entidad.atributos or {}
        return atributos.get("presupuesto_diario") or atributos.get("presupuesto_total")
    return None


def _payload_meta(tipo_accion, valor_propuesto):
    if tipo_accion == "pausar":
        return {"status": "PAUSED"}
    if tipo_accion == "activar":
        return {"status": "ACTIVE"}
    if tipo_accion == "modificar_presupuesto":
        return {"daily_budget": valor_propuesto}
    return {}


def _campo_meta_a_verificar(tipo_accion):
    return "status" if tipo_accion in ("pausar", "activar") else "daily_budget"


def crear_propuesta(empresa_id, usuario_id, entidad_id, tipo_accion, valor_propuesto, motivo, evidencia=None, riesgo=None, origen="manual"):
    """(accion_o_None, error_o_None). Solo PROPONE -- nunca toca Meta.
    Captura el valor actual leyendo la entidad ya sincronizada."""
    from app.extensions import db
    from app.models import AccionMeta, EntidadPublicitaria

    entidad = db.session.query(EntidadPublicitaria).filter_by(id=entidad_id, empresa_id=empresa_id).first()
    if entidad is None:
        return None, "El recurso seleccionado no pertenece a esta empresa."

    error_tipo = validar_tipo_accion_para_entidad(entidad.tipo, tipo_accion)
    if error_tipo:
        return None, error_tipo

    motivo = (motivo or "").strip()
    if not motivo:
        return None, "El motivo de la propuesta es obligatorio."

    valor_propuesto = str(valor_propuesto).strip() if valor_propuesto is not None else ""
    if not valor_propuesto:
        return None, "El valor propuesto es obligatorio."
    if tipo_accion == "modificar_presupuesto":
        try:
            monto = float(valor_propuesto)
        except ValueError:
            return None, "El nuevo presupuesto debe ser un número."
        if monto <= 0:
            return None, "El nuevo presupuesto debe ser mayor que cero."

    accion = AccionMeta(
        empresa_id=empresa_id,
        entidad_id=entidad.id,
        tipo_accion=tipo_accion,
        valor_actual=str(_leer_valor_actual(entidad, tipo_accion)) if _leer_valor_actual(entidad, tipo_accion) is not None else None,
        valor_propuesto=valor_propuesto,
        motivo=motivo,
        evidencia=(evidencia or "").strip() or None,
        riesgo=(riesgo or "").strip() or None,
        origen=origen if origen in ORIGENES_ACCION_META else "manual",
        estado="pendiente_de_aprobacion",
        propuesto_por=usuario_id,
    )
    db.session.add(accion)
    db.session.commit()
    return accion, None


def obtener_accion(empresa_id, accion_id):
    from app.extensions import db
    from app.models import AccionMeta

    return db.session.query(AccionMeta).filter_by(id=accion_id, empresa_id=empresa_id).first()


def listar_acciones_empresa(empresa_id, estado=None):
    from app.extensions import db
    from app.models import AccionMeta

    consulta = db.session.query(AccionMeta).filter_by(empresa_id=empresa_id)
    if estado:
        consulta = consulta.filter_by(estado=estado)
    return consulta.order_by(AccionMeta.creado_en.desc()).all()


def aprobar_propuesta(empresa_id, usuario_id, accion_id):
    """Primer paso de la doble confirmacion (Paso 12, punto 5) -- NUNCA
    ejecuta nada en Meta, solo marca que un humano revisó y aceptó la
    propuesta."""
    from app.extensions import db

    accion = obtener_accion(empresa_id, accion_id)
    if accion is None:
        return None, "La acción no existe o no pertenece a esta empresa."
    if accion.estado not in ("pendiente_de_aprobacion", "borrador"):
        return None, f'Esta acción está en estado "{accion.estado}" y no se puede aprobar.'

    accion.estado = "aprobada"
    accion.aprobado_por = usuario_id
    accion.aprobado_en = datetime.now(timezone.utc)
    db.session.commit()
    return accion, None


def rechazar_propuesta(empresa_id, usuario_id, accion_id, motivo_rechazo=None):
    from app.extensions import db

    accion = obtener_accion(empresa_id, accion_id)
    if accion is None:
        return None, "La acción no existe o no pertenece a esta empresa."
    if accion.estado not in ("pendiente_de_aprobacion", "borrador", "aprobada"):
        return None, f'Esta acción está en estado "{accion.estado}" y no se puede rechazar.'

    accion.estado = "rechazada"
    if motivo_rechazo:
        accion.riesgo = f"{accion.riesgo} " if accion.riesgo else ""
        accion.riesgo += f"Rechazada: {motivo_rechazo.strip()}"
    db.session.commit()
    return accion, None


def cancelar_propuesta(empresa_id, usuario_id, accion_id):
    from app.extensions import db

    accion = obtener_accion(empresa_id, accion_id)
    if accion is None:
        return None, "La acción no existe o no pertenece a esta empresa."
    if accion.estado in ("ejecutando", "ejecutada"):
        return None, f'Esta acción ya está en estado "{accion.estado}" y no se puede cancelar.'

    accion.estado = "cancelada"
    db.session.commit()
    return accion, None


def _marcar_error(accion, mensaje):
    from app.extensions import db

    accion.estado = "error"
    accion.error_mensaje = (mensaje or "")[:500]
    db.session.commit()


def _registrar_error_meta(accion, exc, prefijo=""):
    from app.services.meta.errores import clasificar_error_meta, detalle_tecnico, mensaje_para_usuario

    categoria = clasificar_error_meta(exc)
    _marcar_error(accion, detalle_tecnico(exc))
    return prefijo + mensaje_para_usuario(categoria, exc)


def ejecutar_accion(empresa_id, usuario_id, accion_id, confirmacion=False):
    """(accion_o_None, error_o_None). EJECUTAR + VERIFICAR (Paso 12,
    puntos 8 y 10) -- la unica funcion de todo el sistema que escribe
    en Meta. Verifica, en este orden, TODO lo que el punto 7 exige
    antes de escribir: la accion existe y pertenece a la empresa, esta
    "aprobada", se recibio `confirmacion=True` explicito (segundo paso
    de la doble confirmacion -- nunca se ejecuta solo porque este
    "aprobada"), el recurso todavia pertenece a la empresa, hay una
    conexion activa con token valido, y esa conexion tiene el permiso
    ads_management. Si algo falla: NO ejecuta, y muestra exactamente el
    motivo (nunca un mensaje generico)."""
    from app.extensions import db
    from app.models import EntidadPublicitaria
    from app.services.meta.client import MetaAPIError
    from app.services.meta.conexiones import obtener_cliente_para_empresa, obtener_conexion_activa

    accion = obtener_accion(empresa_id, accion_id)
    if accion is None:
        return None, "La acción no existe o no pertenece a esta empresa."

    if accion.estado != "aprobada":
        return None, f'Solo se puede ejecutar una acción en estado "aprobada" (estado actual: "{accion.estado}").'

    if not confirmacion:
        return None, "Falta la confirmación explícita para ejecutar este cambio."

    entidad = db.session.query(EntidadPublicitaria).filter_by(id=accion.entidad_id, empresa_id=empresa_id).first()
    if entidad is None:
        _marcar_error(accion, "El recurso ya no pertenece a esta empresa o no existe.")
        return None, "El recurso de esta acción ya no existe o no pertenece a esta empresa."

    conexion = obtener_conexion_activa(empresa_id)
    if conexion is None:
        _marcar_error(accion, "No hay una conexión activa con Meta.")
        return None, "No hay una conexión activa con Meta."

    scopes_concedidos = (conexion.scopes_concedidos or "").split(",")
    if PERMISO_REQUERIDO_ESCRITURA not in scopes_concedidos:
        mensaje = (
            f'Esta conexión con Meta no tiene el permiso "{PERMISO_REQUERIDO_ESCRITURA}" '
            "necesario para modificar campañas. Reconecta la cuenta para concederlo."
        )
        _marcar_error(accion, mensaje)
        return None, mensaje

    cliente, error = obtener_cliente_para_empresa(empresa_id)
    if cliente is None:
        _marcar_error(accion, error)
        return None, error

    campo = _campo_meta_a_verificar(accion.tipo_accion)

    # Se relee el valor REAL justo antes de escribir -- si cambio desde
    # que se creo la propuesta (otra persona lo modifico mientras
    # tanto), nunca se sobreescribe a ciegas.
    try:
        valor_real_actual = cliente.get(entidad.id_externo, params={"fields": campo}).get(campo)
    except MetaAPIError as exc:
        mensaje = _registrar_error_meta(accion, exc)
        return None, mensaje

    valor_real_actual_str = str(valor_real_actual) if valor_real_actual is not None else None
    if accion.valor_actual and valor_real_actual_str and valor_real_actual_str != accion.valor_actual:
        mensaje = (
            f'El valor real en Meta cambió desde que se creó esta propuesta '
            f'(era "{accion.valor_actual}", ahora es "{valor_real_actual_str}"). '
            "Revisa la propuesta antes de continuar."
        )
        _marcar_error(accion, mensaje)
        return None, mensaje

    accion.estado = "ejecutando"
    db.session.commit()

    payload = _payload_meta(accion.tipo_accion, accion.valor_propuesto)
    try:
        cliente.post(entidad.id_externo, data=payload)
    except MetaAPIError as exc:
        mensaje = _registrar_error_meta(accion, exc)
        return None, mensaje

    # Verificacion posterior (Paso 12, punto 10): se vuelve a consultar
    # el recurso para confirmar que el cambio REALMENTE ocurrio -- Meta
    # puede responder sin error sin que el campo haya quedado como se
    # pidio (ej. algun limite propio de la cuenta); nunca se asume
    # exito solo porque la llamada no lanzo una excepcion.
    try:
        valor_verificado = cliente.get(entidad.id_externo, params={"fields": campo}).get(campo)
    except MetaAPIError as exc:
        mensaje = _registrar_error_meta(accion, exc, prefijo="El cambio se envió a Meta pero no se pudo verificar: ")
        return None, mensaje

    valor_verificado_str = str(valor_verificado) if valor_verificado is not None else None
    if valor_verificado_str != accion.valor_propuesto:
        mensaje = f'Meta no reportó el cambio esperado (se esperaba "{accion.valor_propuesto}", Meta reporta "{valor_verificado_str}").'
        _marcar_error(accion, mensaje)
        return None, mensaje

    # Se actualiza la copia local para que Publi Marketing quede
    # consistente sin esperar la proxima sincronizacion completa.
    if accion.tipo_accion in ("pausar", "activar"):
        entidad.estado = valor_verificado_str
    else:
        atributos = dict(entidad.atributos or {})
        atributos["presupuesto_diario"] = valor_verificado_str
        entidad.atributos = atributos

    accion.estado = "ejecutada"
    accion.ejecutado_en = datetime.now(timezone.utc)
    accion.resultado_meta = {"campo_verificado": campo, "valor_confirmado": valor_verificado_str}
    accion.error_mensaje = None
    db.session.commit()
    return accion, None


def preparar_reversion(empresa_id, accion_id):
    """(dict_o_None, error_o_None) -- SOLO calcula que valores tendria
    una reversion (Paso 12, punto 11). NUNCA la ejecuta ni crea la
    propuesta por si sola: el llamador debe pasar este dict a
    crear_propuesta() explicitamente si el usuario decide revertir, y
    esa nueva propuesta pasa por el MISMO flujo completo de
    aprobacion."""
    accion = obtener_accion(empresa_id, accion_id)
    if accion is None:
        return None, "La acción no existe o no pertenece a esta empresa."
    if accion.estado != "ejecutada":
        return None, "Solo se puede preparar una reversión de una acción ya ejecutada."
    if not accion.valor_actual:
        return None, "No se registró el valor anterior de esta acción -- no es posible preparar una reversión segura."

    return {
        "entidad_id": accion.entidad_id,
        "tipo_accion": accion.tipo_accion,
        "valor_propuesto": accion.valor_actual,
        "motivo": f'Revertir la acción #{accion.id} ({accion.tipo_accion}) al valor anterior ("{accion.valor_actual}").',
    }, None
