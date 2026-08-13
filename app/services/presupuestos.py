"""Presupuesto de pauta (Paso 2, puntos 9 y 10).

Regla central, repetida a proposito en cada docstring de este archivo
porque es la parte mas facil de romper por accidente: el GASTO REAL
nunca se guarda en PresupuestoPauta -- siempre se CALCULA leyendo
Metrica (el spend nativo ya sincronizado de Meta, motor universal del
Paso 1). El presupuesto ESTRATEGICO/ASIGNADO es capital que el cliente
define, independiente de lo que Meta reporte.
"""

from datetime import date

from app.models import TIPOS_PRESUPUESTO


def crear_presupuesto(empresa_id, usuario_id, nombre, tipo, monto, moneda="CRC",
                       periodo_tipo="mensual", fecha_inicio=None, fecha_fin=None,
                       entidad_id=None, objetivo=None, notas=None):
    from app.extensions import db
    from app.models import EntidadPublicitaria, PresupuestoPauta

    nombre = (nombre or "").strip()
    if not nombre:
        return None, "El nombre del presupuesto es obligatorio."
    if tipo not in TIPOS_PRESUPUESTO:
        return None, "Tipo de presupuesto inválido."
    try:
        monto = float(monto)
    except (TypeError, ValueError):
        return None, "El monto debe ser un número."
    if monto <= 0:
        return None, "El monto debe ser mayor que cero."

    if entidad_id is not None:
        entidad = db.session.query(EntidadPublicitaria).filter_by(id=entidad_id, empresa_id=empresa_id).first()
        if entidad is None:
            return None, "La entidad seleccionada no pertenece a esta empresa."
        if entidad.tipo not in ("campana", "conjunto_anuncios"):
            return None, "Un presupuesto asignado solo puede vincularse a una campaña o un conjunto de anuncios."
        if tipo != "asignado":
            return None, "Solo un presupuesto de tipo 'asignado' puede vincularse a una entidad."

    presupuesto = PresupuestoPauta(
        empresa_id=empresa_id,
        entidad_id=entidad_id,
        nombre=nombre,
        tipo=tipo,
        monto=monto,
        moneda=moneda or "CRC",
        periodo_tipo=periodo_tipo,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        objetivo=objetivo,
        notas=notas,
        creado_por=usuario_id,
    )
    db.session.add(presupuesto)
    db.session.commit()
    return presupuesto, None


def obtener_presupuestos_empresa(empresa_id, tipo=None, solo_activos=True):
    from app.extensions import db
    from app.models import PresupuestoPauta

    consulta = db.session.query(PresupuestoPauta).filter_by(empresa_id=empresa_id)
    if solo_activos:
        consulta = consulta.filter_by(activo=True)
    if tipo:
        consulta = consulta.filter_by(tipo=tipo)
    return consulta.order_by(PresupuestoPauta.creado_en.desc()).all()


def obtener_presupuestos_de_entidad(empresa_id, entidad_id):
    """Presupuestos de tipo "asignado" vinculados a UNA campaña/conjunto
    especifico (Paso 5: presupuesto por campaña) -- distinto del
    presupuesto "estrategico" (capital general de la empresa, sin
    entidad_id). SIEMPRE filtrado por empresa_id."""
    from app.extensions import db
    from app.models import PresupuestoPauta

    return (
        db.session.query(PresupuestoPauta)
        .filter_by(empresa_id=empresa_id, entidad_id=entidad_id, activo=True)
        .all()
    )


def obtener_presupuesto(empresa_id, presupuesto_id):
    from app.extensions import db
    from app.models import PresupuestoPauta

    return db.session.query(PresupuestoPauta).filter_by(id=presupuesto_id, empresa_id=empresa_id).first()


def eliminar_presupuesto(empresa_id, presupuesto_id):
    """Soft delete -- nunca borra la fila, para conservar el historial
    de capital planificado incluso despues de descontinuarlo."""
    presupuesto = obtener_presupuesto(empresa_id, presupuesto_id)
    if presupuesto is None:
        return False, "El presupuesto no existe o no pertenece a esta empresa."

    from app.extensions import db

    presupuesto.activo = False
    db.session.commit()
    return True, None


def _rango_efectivo(presupuesto, hoy=None):
    """(fecha_inicio, fecha_fin) a usar para calcular gasto real de
    este presupuesto: sus propias fechas si las tiene, o el mes en
    curso si es "mensual" sin fechas explicitas."""
    from app.services.periodos import resolver_periodo

    if presupuesto.fecha_inicio and presupuesto.fecha_fin:
        return presupuesto.fecha_inicio, presupuesto.fecha_fin
    if presupuesto.periodo_tipo == "mensual":
        return resolver_periodo("este_mes", hoy=hoy)
    return presupuesto.fecha_inicio or (hoy or date.today()), presupuesto.fecha_fin or (hoy or date.today())


def calcular_gasto_real(empresa_id, entidad_id=None, fecha_inicio=None, fecha_fin=None):
    """Suma el `spend` NATIVO ya sincronizado de Meta (Metrica, motor
    universal del Paso 1) -- nunca un numero guardado en
    PresupuestoPauta. `entidad_id=None` suma el gasto de TODAS las
    entidades de la empresa en el rango (gasto total de la cuenta)."""
    from app.services.metricas import consultar_metricas

    filas = consultar_metricas(
        empresa_id, entidad_id=entidad_id, metrica_nombre="spend",
        fecha_desde=fecha_inicio, fecha_hasta=fecha_fin,
    )
    return round(sum(f.valor for f in filas if f.valor is not None), 2)


def calcular_resumen_presupuesto(presupuesto, hoy=None):
    """Dict con gasto real, disponible y porcentaje usado para UN
    presupuesto -- lo que la pantalla de Conexiones muestra (Paso 2,
    punto 17)."""
    fecha_inicio, fecha_fin = _rango_efectivo(presupuesto, hoy=hoy)
    gasto_real = calcular_gasto_real(presupuesto.empresa_id, entidad_id=presupuesto.entidad_id, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin)
    disponible = round(presupuesto.monto - gasto_real, 2)
    porcentaje_usado = round((gasto_real / presupuesto.monto) * 100, 1) if presupuesto.monto else None

    return {
        "presupuesto": presupuesto,
        "fecha_inicio": fecha_inicio,
        "fecha_fin": fecha_fin,
        "gasto_real": gasto_real,
        "disponible": disponible,
        "porcentaje_usado": porcentaje_usado,
        "excedido": disponible < 0,
    }
