# worker_graph.py  ·  FastAPI
# Descarga imágenes inline de un mensaje de Teams, las envía a la API Comercial
# y publica la respuesta en el mismo hilo.

import os
import base64
from html import unescape
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Request
from msal import ConfidentialClientApplication

# ─────────────────────────  Config ──────────────────────────
CLIENT_ID     = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
TENANT_ID     = os.getenv("TENANT_ID")
SCOPE         = ["https://graph.microsoft.com/.default"]

API_COMERCIAL = "https://chatbot-gateway-4xpqf1tp.uc.gateway.dev/consulta-con-imagen"
API_KEY       = "AIzaSyA2hWFYOgx2Nea82xE-KrSQY67HlZVSnT8"

# ─────────────────────────  FastAPI ─────────────────────────
app = FastAPI()

# ──────────────────── 1. Token para Microsoft Graph ─────────
def obtener_token_graph() -> str:
    cca = ConfidentialClientApplication(
        client_id=CLIENT_ID,
        client_credential=CLIENT_SECRET,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}"
    )
    return cca.acquire_token_for_client(scopes=SCOPE)["access_token"]

AUTH_HEADER = lambda token: {"Authorization": f"Bearer {token}"}

# ─────────────── 2. HTML del mensaje (para logging opc.) ────
def obtener_html_del_mensaje(token: str, team_id: str, channel_id: str, message_id: str) -> str:
    url = f"https://graph.microsoft.com/v1.0/teams/{team_id}/channels/{channel_id}/messages/{message_id}"
    res = requests.get(url, headers=AUTH_HEADER(token))
    res.raise_for_status()
    return res.json()["body"]["content"]                       # HTML

# ───────────────── 3. Descarga de hostedContents ────────────
def descargar_imagen_mensaje(token: str, team_id: str, channel_id: str, message_id: str, index: int = 0) -> str:
    """
    Devuelve la imagen en base‑64.
    - Primero intenta vía /hostedContents (método oficial).
    - Si el mensaje no tiene hostedContents (p.ej. pegaste un link de imagen),
      cae al parser de <img src>.
    """
    base_url = f"https://graph.microsoft.com/v1.0/teams/{team_id}/channels/{channel_id}/messages/{message_id}"

    # 3‑A. Lista de hostedContents
    r = requests.get(f"{base_url}/hostedContents", headers=AUTH_HEADER(token))
    r.raise_for_status()
    lista = r.json().get("value", [])

    if lista:
        hosted_id = lista[index]["id"]
        r = requests.get(f"{base_url}/hostedContents/{hosted_id}/$value", headers=AUTH_HEADER(token))
        r.raise_for_status()
        return base64.b64encode(r.content).decode()

    # 3‑B. Fallback: parsear <img src> y convertir a URL absoluta
    html = obtener_html_del_mensaje(token, team_id, channel_id, message_id)
    srcs = extraer_srcs(html)
    if not srcs:
        raise ValueError("No se encontró ninguna imagen (hostedContents ni <img src>).")
    src_abs = normalizar_src(srcs[index], team_id, channel_id, message_id)
    r = requests.get(src_abs, headers=AUTH_HEADER(token))
    r.raise_for_status()
    return base64.b64encode(r.content).decode()

# Utilidades de parseo HTML (solo usadas en el fallback)
def extraer_srcs(html: str) -> list[str]:
    soup = BeautifulSoup(unescape(html), "html.parser")
    return [img["src"] for img in soup.find_all("img")]

def normalizar_src(src_rel: str, team_id: str, channel_id: str, message_id: str) -> str:
    if src_rel.startswith("http"):
        return src_rel
    base = f"https://graph.microsoft.com/v1.0/teams/{team_id}/channels/{channel_id}/messages/{message_id}/"
    return urljoin(base, src_rel.lstrip("./"))

# ──────────────── 4. Llamada a la API Comercial ─────────────
def procesar_imagen_comercial(comentario: str, img64: str) -> dict:
    payload = {"comentario": comentario, "imagen": img64}
    headers = {"x-api-key": API_KEY, "Content-Type": "application/json"}
    res = requests.post(API_COMERCIAL, json=payload, headers=headers, timeout=30)
    res.raise_for_status()
    return res.json()

# ───────────── 5. Responder en el hilo (Teams) ──────────────
def responder_en_teams(token: str, team_id: str, channel_id: str, message_id: str, texto: str) -> None:
    url = f"https://graph.microsoft.com/v1.0/teams/{team_id}/channels/{channel_id}/messages/{message_id}/replies"
    payload = {"body": {"content": texto}}
    r = requests.post(url, json=payload, headers={**AUTH_HEADER(token), "Content-Type": "application/json"})
    print("[RESPUESTA TEAMS]", r.status_code, r.text)

# ──────────────── 6. Endpoint principal /procesar ───────────
@app.post("/procesar")
async def procesar(request: Request):
    data = await request.json()
    team_id    = data["team_id"]
    channel_id = data["channel_id"]
    message_id = data["message_id"]
    comentario = data.get("comentario", "Mensaje desde canal sin adjunto")

    token = obtener_token_graph()

    try:
        img64 = descargar_imagen_mensaje(token, team_id, channel_id, message_id)
    except Exception as e:
        print("[WARN]", e)
        responder_en_teams(token, team_id, channel_id, message_id,
                           f"⚠️ No se pudo leer la imagen: {e}")
        return {"ok": False, "detalle": str(e)}

    print("[INFO] Imagen descargada, enviando a API Comercial…")
    resp_api = procesar_imagen_comercial(comentario, img64)

    responder_en_teams(token, team_id, channel_id, message_id,
                       resp_api.get("respuesta", "No se detectó comercial."))
    return {"ok": True, "respuesta_api": resp_api}
