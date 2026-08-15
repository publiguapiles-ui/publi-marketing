"""Centro de Datos de Marketing (Paso 2).

Capa de servicio unificadora: el resto de la aplicacion (Datos de
Meta, Informes, Optimizacion, y en el Paso 3 la Inteligencia con
Claude) debe poder pedir "las campañas de esta empresa" o "los
resultados de este periodo" SIN saber que hoy eso viene de Meta ni
como Meta guarda sus datos -- exactamente el patron ya usado en
app/services/meta/conexiones.py para el cliente HTTP, aplicado ahora
un nivel mas arriba.

Meta es la UNICA fuente real conectada. Cada funcion de aqui
simplemente delega en los servicios de app/services/meta/* que ya
existen (kpi.py, cuentas_service.py, conexiones.py) -- nunca
recalcula ni duplica esa logica, nunca hace una consulta nueva a
Meta ni a la base de datos que esos modulos no hagan ya. El dia que
se conecte una fuente nueva (CRM/ventas/WhatsApp), estas mismas
funciones deberan combinar sus resultados con los de Meta -- hoy
devuelven honestamente "no disponible" para todo lo que Meta no
puede proporcionar (ventas reales, ROAS real), nunca lo inventan.

SIEMPRE filtrado por empresa_id -- aislamiento multi-tenant, igual
que el resto del proyecto.
"""

from app.models import TIPOS_FUENTE_DATOS, ETIQUETAS_FUENTE_DATOS

# Punto 8 (Paso 2): estado de calidad de un dato devuelto por este
# modulo -- nunca se inventa informacion para "llenar" un campo con
# mejor calidad de la que realmente tiene.
#   verificado    -- confirmado contra una fuente autoritativa distinta
#                     (no aplica todavia a nada; ninguna funcion de
#                     aqui lo devuelve hoy).
#   sincronizado  -- viene de una sincronizacion real y reciente (el
#                     caso normal de todo lo que ya trae Meta).
#   incompleto    -- la fuente respondio pero con huecos conocidos
#                     (ej. algunas filas sin ese campo).
#   no_disponible -- no existe ninguna fuente conectada para ese dato.
CONFIANZA_VERIFICADO = "verificado"
CONFIANZA_SINCRONIZADO = "sincronizado"
CONFIANZA_INCOMPLETO = "incompleto"
CONFIANZA_NO_DISPONIBLE = "no_disponible"

ESTADOS_CONFIANZA_DATO = [CONFIANZA_VERIFICADO, CONFIANZA_SINCRONIZADO, CONFIANZA_INCOMPLETO, CONFIANZA_NO_DISPONIBLE]


def obtener_fuentes_empresa(empresa_id):
    """Todas las fuentes de datos que el sistema RECONOCE (punto 14:
    "Fuentes conectadas"), conectadas o no. Meta se deriva en vivo del
    estado real de MetaConexion (nunca se duplica ese estado en una
    fila aparte -- ver FuenteDatos). Las demas se leen de la tabla
    FuenteDatos si alguna vez llegan a tener una fila real; hoy no
    tienen ninguna, asi que aparecen honestamente como
    "no_conectada"."""
    from app.services.meta.conexiones import obtener_conexion_mas_reciente

    fuentes = []
    for tipo in TIPOS_FUENTE_DATOS:
        if tipo == "meta":
            conexion = obtener_conexion_mas_reciente(empresa_id)
            if conexion is None:
                fuentes.append(_fuente_no_conectada(tipo))
                continue
            fuentes.append({
                "tipo": tipo,
                "etiqueta": ETIQUETAS_FUENTE_DATOS[tipo],
                "estado": "conectada" if conexion.estado == "activa" else "error",
                "conectada": conexion.estado == "activa",
                "ultima_sincronizacion_en": conexion.ultima_sincronizacion_en,
                "ultimo_error": conexion.ultimo_error,
                "creado_en": conexion.creado_en,
            })
            continue

        fila = _fuente_datos_de_empresa(empresa_id, tipo)
        if fila is None:
            fuentes.append(_fuente_no_conectada(tipo))
        else:
            fuentes.append({
                "tipo": tipo,
                "etiqueta": ETIQUETAS_FUENTE_DATOS[tipo],
                "estado": fila.estado,
                "conectada": fila.estado == "conectada",
                "ultima_sincronizacion_en": fila.ultima_sincronizacion_en,
                "ultimo_error": fila.ultimo_error,
                "creado_en": fila.creado_en,
            })
    return fuentes


def _fuente_no_conectada(tipo):
    return {
        "tipo": tipo,
        "etiqueta": ETIQUETAS_FUENTE_DATOS[tipo],
        "estado": "no_conectada",
        "conectada": False,
        "ultima_sincronizacion_en": None,
        "ultimo_error": None,
        "creado_en": None,
    }


def _fuente_datos_de_empresa(empresa_id, tipo):
    from app.extensions import db
    from app.models import FuenteDatos

    return db.session.query(FuenteDatos).filter_by(empresa_id=empresa_id, tipo=tipo).first()


def obtener_campanas(empresa_id, cuenta_id=None):
    """Campañas normalizadas de la empresa (punto 3/4: id interno y
    externo separados). Delega en cuentas_service -- lectura pura, sin
    llamar a Meta."""
    from app.services.meta.cuentas_service import listar_campanas_de_cuenta, listar_entidades_empresa

    if cuenta_id is not None:
        campanas = listar_campanas_de_cuenta(empresa_id, cuenta_id)
    else:
        campanas = listar_entidades_empresa(empresa_id, tipo="campana")

    return [_serializar_entidad(c) for c in campanas]


def obtener_audiencias(empresa_id, cuenta_id=None):
    """Conjuntos de anuncios (segmentacion) de la empresa. Delega en
    cuentas_service -- lectura pura, sin llamar a Meta."""
    from app.services.meta.cuentas_service import listar_conjuntos_de_empresa

    conjuntos = listar_conjuntos_de_empresa(empresa_id, cuenta_id=cuenta_id)
    return [_serializar_entidad(c) for c in conjuntos]


def _serializar_entidad(entidad):
    return {
        "id_interno": entidad.id,
        "id_externo": entidad.id_externo,
        "nombre": entidad.nombre,
        "tipo": entidad.tipo,
        "estado": entidad.estado,
        "fuente": entidad.fuente,
        "confianza": CONFIANZA_SINCRONIZADO,
    }


def obtener_resultados(empresa_id, entidad_id, fecha_inicio, fecha_fin):
    """KPI reales de Meta para una entidad (cuenta/campaña/conjunto/
    anuncio) y periodo, mas la distincion del punto 15: el ROAS que
    Meta REPORTA (atribucion propia de Meta) nunca se confunde con un
    ROAS real del negocio, que requeriria ventas conectadas -- ese
    campo queda honestamente en no_disponible."""
    from app.services.meta.kpi import calcular_kpis, resolver_entidades_para_kpi

    entidad_ids, error = resolver_entidades_para_kpi(empresa_id, entidad_id)
    if error:
        return None, error

    kpis = calcular_kpis(empresa_id, entidad_ids, fecha_inicio, fecha_fin)
    return {
        "fuente": "meta",
        "periodo": {"desde": fecha_inicio.isoformat(), "hasta": fecha_fin.isoformat()},
        "kpis": kpis,
        "confianza": CONFIANZA_SINCRONIZADO if any(v is not None for v in kpis.values()) else CONFIANZA_NO_DISPONIBLE,
        "roas_reportado": kpis.get("roas"),
        "roas_real": None,
        "roas_real_razon": "No hay ninguna fuente de ventas conectada todavía -- el ROAS real requiere ingresos reales del negocio, no solo conversiones reportadas por Meta.",
    }, None


def obtener_conversiones(empresa_id, entidad_id, fecha_inicio, fecha_fin):
    """Conversiones REPORTADAS por Meta (nunca ventas reales -- ver
    obtener_ventas_reales) para una entidad y periodo."""
    resultados, error = obtener_resultados(empresa_id, entidad_id, fecha_inicio, fecha_fin)
    if error:
        return None, error

    kpis = resultados["kpis"]
    return {
        "fuente": "meta",
        "periodo": resultados["periodo"],
        "conversiones_reportadas": kpis.get("conversiones"),
        "valor_conversion_reportado": kpis.get("valor_conversion"),
        "confianza": CONFIANZA_SINCRONIZADO if kpis.get("conversiones") is not None else CONFIANZA_NO_DISPONIBLE,
        "nota": "Estas son las conversiones que Meta reporta haber atribuido a la pauta, no ventas verificadas del negocio.",
    }, None


def obtener_ventas_reales(empresa_id, fecha_inicio=None, fecha_fin=None):
    """Punto 15/19: NUNCA se inventan ventas ni ingresos reales. Sin
    una fuente de ventas conectada (CRM, punto de venta, etc. -- ver
    TIPOS_FUENTE_DATOS), esto es honestamente no_disponible siempre."""
    return {
        "fuente": None,
        "confianza": CONFIANZA_NO_DISPONIBLE,
        "valor": None,
        "razon": "No hay ninguna fuente de ventas conectada todavía para esta empresa.",
    }


def construir_contexto_marketing(empresa_id, cuenta_id, fecha_inicio, fecha_fin):
    """Punto 16 (Paso 2) / preparacion para el Paso 3: un contexto
    estructurado y ya resumido para que una capa de inteligencia
    (Claude) pueda consultarlo sin tener que conocer Meta ni volver a
    calcular nada -- reutiliza el motor de Centro de Control (Paso 14),
    que ya es el punto unico de agregacion de KPI/alertas/oportunidades
    para una cuenta, en vez de construir un segundo resumen distinto."""
    from app.services.meta.centro_control import construir_centro_control

    paquete, error = construir_centro_control(empresa_id, cuenta_id, fecha_inicio, fecha_fin)
    if error:
        return None, error

    return {
        "empresa_id": empresa_id,
        "cuenta_id": cuenta_id,
        "periodo": {"desde": fecha_inicio.isoformat(), "hasta": fecha_fin.isoformat()},
        "fuentes": obtener_fuentes_empresa(empresa_id),
        "kpis": paquete["kpis"],
        "campanas": paquete["campanas"],
        "alertas": paquete["alertas"],
        "oportunidades": paquete["oportunidades"],
        "diagnostico_cuenta": paquete.get("diagnostico_cuenta"),
        "ventas_reales": obtener_ventas_reales(empresa_id, fecha_inicio, fecha_fin),
    }, None
