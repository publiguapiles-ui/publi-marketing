"""Capa unica de llamadas a un modelo de IA generativa (Paso 10, punto
13). Ninguna otra parte del codigo debe llamar a la API de Anthropic
directamente -- todo pasa por `generar_respuesta()` aqui, para poder
cambiar de proveedor/modelo despues sin tocar el resto del sistema
(mismo principio que app/services/meta/client.py es el UNICO lugar que
habla con graph.facebook.com).

Este archivo no sabe nada de "empresa", "campaña" ni "conversacion" --
solo sabe enviar mensajes a un modelo y devolver texto + uso de tokens.
Construir el contexto de negocio es responsabilidad de
app/services/estratega_ia.py.
"""

import os

import requests

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODELO_PREDETERMINADO = "claude-sonnet-5"
TIEMPO_ESPERA_SEGUNDOS = 60
MAX_TOKENS_RESPUESTA = 1500


def ia_configurada():
    """True si hay una API key configurada en este entorno -- nunca se
    simula una respuesta cuando no la hay (Paso 10, punto 15: mostrar
    un error amigable, no inventar)."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def generar_respuesta(mensajes, system=None, modelo=None, max_tokens=None):
    """`mensajes`: lista de {"role": "user"|"assistant", "content": str},
    ya en orden cronologico (el llamador decide cuanto historial incluir).
    `system` es el prompt de sistema (instrucciones + contexto de
    negocio ya formateado como texto -- ver estratega_ia.py).

    Devuelve (texto_o_None, uso_o_None, error_o_None). `uso` es
    {"modelo": str, "tokens_entrada": int|None, "tokens_salida": int|None}.
    Nunca lanza: cualquier fallo de red o de la API se traduce a
    `error` (mensaje amigable, sin exponer la API key)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None, None, "El asistente de IA no está configurado en este entorno."

    if not mensajes:
        return None, None, "No hay ningún mensaje que enviar."

    try:
        resp = requests.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": modelo or MODELO_PREDETERMINADO,
                "max_tokens": max_tokens or MAX_TOKENS_RESPUESTA,
                "system": system or "",
                "messages": mensajes,
            },
            timeout=TIEMPO_ESPERA_SEGUNDOS,
        )
    except requests.RequestException:
        return None, None, "No se pudo contactar al asistente de IA. Intenta de nuevo."

    if resp.status_code >= 400:
        # Nunca se expone el cuerpo crudo de la respuesta al usuario
        # (podria incluir detalles internos de la API) -- solo el
        # codigo HTTP, suficiente para diagnosticar sin filtrar nada.
        return None, None, f"El asistente de IA respondió con un error (HTTP {resp.status_code}). Intenta de nuevo."

    try:
        cuerpo = resp.json()
    except ValueError:
        return None, None, "El asistente de IA devolvió una respuesta inválida."

    bloques = cuerpo.get("content") or []
    texto = "".join(b.get("text", "") for b in bloques if b.get("type") == "text").strip()
    if not texto:
        return None, None, "El asistente de IA no devolvió ninguna respuesta."

    uso_bruto = cuerpo.get("usage") or {}
    uso = {
        "modelo": cuerpo.get("model") or (modelo or MODELO_PREDETERMINADO),
        "tokens_entrada": uso_bruto.get("input_tokens"),
        "tokens_salida": uso_bruto.get("output_tokens"),
    }
    return texto, uso, None
