"""Periodos de fecha reutilizables para sincronizacion y consulta de
metricas (Paso 2, punto 11). Deliberadamente agnostico de Meta -- solo
calcula rangos (fecha_inicio, fecha_fin), no sabe nada de la Graph API
ni de nuestros modelos. Reutilizable por cualquier fuente futura.
"""

from datetime import date, timedelta

PERIODOS_PREDEFINIDOS = [
    "ultimos_7_dias",
    "ultimos_14_dias",
    "ultimos_30_dias",
    "ultimos_90_dias",
    "este_mes",
    "mes_anterior",
    "personalizado",
]

ETIQUETAS_PERIODOS = {
    "ultimos_7_dias": "Últimos 7 días",
    "ultimos_14_dias": "Últimos 14 días",
    "ultimos_30_dias": "Últimos 30 días",
    "ultimos_90_dias": "Últimos 90 días",
    "este_mes": "Este mes",
    "mes_anterior": "Mes anterior",
    "personalizado": "Período personalizado",
}

_DIAS_POR_CLAVE = {
    "ultimos_7_dias": 7,
    "ultimos_14_dias": 14,
    "ultimos_30_dias": 30,
    "ultimos_90_dias": 90,
}


def resolver_periodo(clave, fecha_inicio=None, fecha_fin=None, hoy=None):
    """(fecha_inicio, fecha_fin), ambas inclusive. `hoy` es inyectable
    solo para tests deterministas -- por defecto usa la fecha real."""
    hoy = hoy or date.today()

    if clave not in PERIODOS_PREDEFINIDOS:
        raise ValueError(f"Período desconocido: '{clave}'.")

    if clave in _DIAS_POR_CLAVE:
        dias = _DIAS_POR_CLAVE[clave]
        return hoy - timedelta(days=dias - 1), hoy

    if clave == "este_mes":
        return hoy.replace(day=1), hoy

    if clave == "mes_anterior":
        primer_dia_mes_actual = hoy.replace(day=1)
        ultimo_dia_mes_anterior = primer_dia_mes_actual - timedelta(days=1)
        primer_dia_mes_anterior = ultimo_dia_mes_anterior.replace(day=1)
        return primer_dia_mes_anterior, ultimo_dia_mes_anterior

    # clave == "personalizado"
    if fecha_inicio is None or fecha_fin is None:
        raise ValueError("Un período personalizado requiere fecha_inicio y fecha_fin.")
    if fecha_fin < fecha_inicio:
        raise ValueError("fecha_fin no puede ser anterior a fecha_inicio.")
    return fecha_inicio, fecha_fin


def periodo_anterior_equivalente(fecha_inicio, fecha_fin):
    """El rango inmediatamente anterior, de la misma duración -- para
    comparar "30 días vs 30 días anteriores" (punto 11). Pura
    aritmética de fechas, no consulta nada."""
    duracion = (fecha_fin - fecha_inicio).days + 1
    fin_anterior = fecha_inicio - timedelta(days=1)
    inicio_anterior = fin_anterior - timedelta(days=duracion - 1)
    return inicio_anterior, fin_anterior
