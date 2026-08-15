"""Importador manual de reportes CSV exportados desde Meta Ads Manager.

Alternativa real mientras la sincronizacion automatica esta limitada
por Meta (codigo 17, ver insights_service.py): Meta Ads Manager
permite exportar un reporte (Descargar > Exportar tabla como .csv)
desde su propia interfaz, sin usar la API -- no consume ninguna cuota.
Este modulo carga ese archivo en el MISMO motor de metricas que ya usa
la sincronizacion automatica (app/services/metricas.py), para que el
Centro de Control/Informes/Optimizacion lo puedan usar sin saber que
esos datos no vinieron de la API.

Las filas se guardan con fuente="meta_csv" (NUNCA "meta", que
significa especificamente "sincronizado via API") -- asi
consultar_metricas() las sigue incluyendo en los KPI (nunca filtra por
fuente), pero reemplazar_metricas_del_dia() nunca borra ni mezcla sus
filas con las de una sincronizacion API real del mismo dia (ese
reemplazo ya esta scopeado por fuente). Si ya existe una fila "meta"
real para la misma entidad/dia, se AVISA en vez de sumarla en
silencio (Paso 2, punto 11: "no aceptar silenciosamente
discrepancias") -- sigue guardandose (el usuario decide que hacer con
el aviso), nunca se descarta ni se sobreescribe.

Nunca inventa una entidad: una fila cuyo nombre de campana no coincide
con ninguna campana ya sincronizada de esa cuenta se omite y se
reporta, no se crea una campana nueva a partir de un CSV.
"""

import csv
import io
from datetime import date, datetime

FUENTE_CSV = "meta_csv"

# Alias de encabezados conocidos de las exportaciones de Meta Ads
# Manager (en ingles y espanol -- Meta cambia el idioma segun el de la
# cuenta) -- comparados en minusculas y sin espacios sobrantes.
ALIAS_COLUMNAS = {
    "campana": ["campaign name", "nombre de la campaña", "nombre de la campana"],
    "fecha": ["day", "día", "dia", "date"],
    "spend": ["amount spent (usd)", "amount spent", "importe gastado (usd)", "importe gastado"],
    "impressions": ["impressions", "impresiones"],
    "clicks": ["link clicks", "clicks (all)", "clics en el enlace", "clics (todos)"],
    "reach": ["reach", "alcance"],
    "frequency": ["frequency", "frecuencia"],
    "conversiones": ["results", "resultados"],
    "valor_conversion": ["conversion value", "valor de conversión", "valor de conversion"],
}

_FORMATOS_FECHA = ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"]


def _normalizar_encabezado(texto):
    return (texto or "").strip().lower()


def _mapear_columnas(encabezados):
    """encabezado_normalizado -> clave interna, solo para los
    encabezados que realmente aparecen en ESTE archivo."""
    normalizados = {_normalizar_encabezado(h): h for h in encabezados}
    mapa = {}
    for clave, alias in ALIAS_COLUMNAS.items():
        for alias_posible in alias:
            if alias_posible in normalizados:
                mapa[clave] = normalizados[alias_posible]
                break
    return mapa


def _parsear_fecha(texto):
    texto = (texto or "").strip()
    for formato in _FORMATOS_FECHA:
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None


def _parsear_numero(texto):
    if texto is None:
        return None
    texto = str(texto).strip()
    if not texto:
        return None
    texto = texto.replace("$", "").replace("₡", "").replace(",", "").replace("%", "").strip()
    try:
        return float(texto)
    except ValueError:
        return None


def procesar_csv_meta(empresa_id, cuenta_id, contenido_bytes):
    """Procesa un CSV exportado de Meta Ads Manager para las campañas
    YA sincronizadas de `cuenta_id`. Devuelve (resumen_dict, error_o_None).

    resumen_dict:
      filas_totales, filas_guardadas, filas_omitidas, advertencias (list[str])
    """
    from app.services.meta.cuentas_service import listar_campanas_de_cuenta
    from app.services.metricas import (
        consultar_metricas,
        reemplazar_metricas_del_dia,
        registrar_metricas_nativas_y_calculadas,
    )

    campanas = listar_campanas_de_cuenta(empresa_id, cuenta_id)
    if not campanas:
        return None, "Esta cuenta no tiene campañas sincronizadas todavía -- sincroniza la estructura al menos una vez antes de importar un CSV (así se puede saber a cuál campaña pertenece cada fila)."

    campanas_por_nombre = {(c.nombre or "").strip().lower(): c for c in campanas}

    try:
        texto = contenido_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None, "El archivo no es un CSV de texto válido (no se pudo leer como UTF-8)."

    lector = csv.DictReader(io.StringIO(texto))
    if not lector.fieldnames:
        return None, "El archivo no tiene ninguna fila de encabezado -- no se puede interpretar."

    mapa = _mapear_columnas(lector.fieldnames)
    if "campana" not in mapa or "fecha" not in mapa:
        return None, "No se reconocieron las columnas de campaña y/o fecha en este archivo. Verifica que sea un export de Meta Ads Manager sin modificar los encabezados."

    filas_totales = 0
    filas_guardadas = 0
    filas_omitidas = 0
    advertencias = []

    for fila in lector:
        filas_totales += 1

        nombre_campana = (fila.get(mapa["campana"]) or "").strip()
        entidad = campanas_por_nombre.get(nombre_campana.lower())
        if entidad is None:
            filas_omitidas += 1
            advertencias.append(f"Fila {filas_totales}: la campaña \"{nombre_campana}\" no coincide con ninguna campaña ya sincronizada de esta cuenta -- se omitió (nunca se inventa una campaña nueva a partir de un CSV).")
            continue

        fecha = _parsear_fecha(fila.get(mapa["fecha"]))
        if fecha is None:
            filas_omitidas += 1
            advertencias.append(f"Fila {filas_totales}: la fecha \"{fila.get(mapa['fecha'])}\" no se pudo interpretar -- se omitió.")
            continue

        filas_existentes = consultar_metricas(empresa_id, entidad_id=entidad.id, fecha_desde=fecha, fecha_hasta=fecha, metrica_nombre="spend")
        if any(m.fuente == "meta" for m in filas_existentes):
            advertencias.append(f"Fila {filas_totales}: \"{nombre_campana}\" ya tiene datos sincronizados por API para {fecha.isoformat()} -- revisa si esta importación duplica esos datos antes de confiar en ambos a la vez.")

        valores_nativos = {}
        for clave in ("spend", "impressions", "clicks", "reach", "frequency", "conversiones", "valor_conversion"):
            if clave in mapa:
                valores_nativos[clave] = _parsear_numero(fila.get(mapa[clave]))

        if not any(v is not None for v in valores_nativos.values()):
            filas_omitidas += 1
            advertencias.append(f"Fila {filas_totales}: ninguna columna numérica reconocida trajo un valor -- se omitió.")
            continue

        reemplazar_metricas_del_dia(empresa_id, entidad.id, fecha, fuente=FUENTE_CSV)
        registrar_metricas_nativas_y_calculadas(
            empresa_id, entidad.id, entidad.tipo, valores_nativos, fecha, fuente=FUENTE_CSV,
        )
        filas_guardadas += 1

    return {
        "filas_totales": filas_totales,
        "filas_guardadas": filas_guardadas,
        "filas_omitidas": filas_omitidas,
        "advertencias": advertencias,
    }, None
