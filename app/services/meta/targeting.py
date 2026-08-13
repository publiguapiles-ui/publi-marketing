"""Interpretacion del `targeting` real de un conjunto de anuncios
(Paso 5, punto 2 y 5).

`EntidadPublicitaria.atributos["targeting"]` ya guarda, desde el Paso
2 (campanas_service.py::_atributos_conjunto), el objeto `targeting`
crudo tal como lo devuelve Meta -- ver
https://developers.facebook.com/docs/marketing-api/audiences/reference/basic-targeting.
Este archivo NUNCA llama a la Graph API ni guarda nada: solo traduce
ese JSON a etiquetas legibles para la pantalla de campana/audiencias.

Principio central: cada clave del resultado es None si Meta no incluyo
ese campo en el targeting -- nunca se completa un valor por defecto
que Meta no haya reportado explicitamente (con la unica excepcion de
"sexo": Meta omite `genders` por completo cuando el conjunto apunta a
"todos los generos", que es un hecho real y documentado, no un
supuesto nuestro).

Limitacion conocida y deliberada: Meta NO distingue "lookalike" de
"publico personalizado estandar" dentro de `targeting.custom_audiences`
(solo trae {id, name}) -- para saber el subtipo real hace falta una
llamada adicional a la API de audiencias (GET /{custom_audience_id})
que este paso no implementa (no forma parte de lo sincronizado en el
Paso 2). Por eso ambos se muestran juntos como "públicos personalizados
usados", sin inventar la distincion.
"""

_ETIQUETAS_GENERO = {1: "Hombres", 2: "Mujeres"}


def _extraer_nombres(lista):
    return [item.get("name") if isinstance(item, dict) else str(item) for item in lista]


def interpretar_targeting(targeting):
    """dict targeting crudo de Meta -> dict de campos legibles, o None
    si no hay ningun targeting guardado (conjunto no sincronizado
    todavia, o Meta no devolvio el campo)."""
    if not targeting:
        return None

    edades = None
    if targeting.get("age_min") is not None or targeting.get("age_max") is not None:
        edades = f"{targeting.get('age_min', 18)}-{targeting.get('age_max', '65+')}"

    sexo = None
    if "genders" in targeting:
        generos = targeting.get("genders")
        sexo = " y ".join(_ETIQUETAS_GENERO.get(g, f"código {g}") for g in generos) if generos else "Todos"

    ubicaciones = None
    geo = targeting.get("geo_locations") or {}
    partes_geo = []
    for clave, etiqueta in (("countries", "países"), ("regions", "regiones"), ("cities", "ciudades")):
        valores = geo.get(clave)
        if valores:
            nombres = valores if clave == "countries" else _extraer_nombres(valores)
            partes_geo.append(f"{etiqueta}: {', '.join(str(n) for n in nombres)}")
    if partes_geo:
        ubicaciones = "; ".join(partes_geo)

    placements = None
    partes_placement = []
    if targeting.get("publisher_platforms"):
        partes_placement.append("Plataformas: " + ", ".join(targeting["publisher_platforms"]))
    if targeting.get("facebook_positions"):
        partes_placement.append("Facebook: " + ", ".join(targeting["facebook_positions"]))
    if targeting.get("instagram_positions"):
        partes_placement.append("Instagram: " + ", ".join(targeting["instagram_positions"]))
    if partes_placement:
        placements = "; ".join(partes_placement)

    dispositivos = None
    if targeting.get("device_platforms"):
        dispositivos = ", ".join(targeting["device_platforms"])

    publicos_personalizados = None
    if targeting.get("custom_audiences"):
        publicos_personalizados = [
            {"id": a.get("id"), "nombre": a.get("name")} for a in targeting["custom_audiences"] if isinstance(a, dict)
        ]

    intereses = None
    flexible = targeting.get("flexible_spec")
    if flexible:
        nombres = []
        for grupo in flexible:
            if not isinstance(grupo, dict):
                continue
            for valor in grupo.values():
                if isinstance(valor, list):
                    nombres.extend(_extraer_nombres(valor))
        if nombres:
            intereses = nombres

    resultado = {
        "edades": edades,
        "sexo": sexo,
        "ubicaciones": ubicaciones,
        "placements": placements,
        "dispositivos": dispositivos,
        "publicos_personalizados": publicos_personalizados,
        "intereses": intereses,
    }
    resultado["sin_datos"] = not any(resultado.values())
    return resultado
