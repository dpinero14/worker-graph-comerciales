# worker_graph.py (versión FastAPI)

import requests
from bs4 import BeautifulSoup
from msal import ConfidentialClientApplication
import base64
from fastapi import FastAPI, Request

app = FastAPI()

# === Config ===
import os

CLIENT_ID     = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
TENANT_ID     = os.getenv("TENANT_ID")
SCOPE = ["https://graph.microsoft.com/.default"]

API_COMERCIAL = "https://chatbot-gateway-4xpqf1tp.uc.gateway.dev/consulta-con-imagen"
API_KEY       = "AIzaSyA2hWFYOgx2Nea82xE-KrSQY67HlZVSnT8"

# === 1. Obtener token ===
def obtener_token_graph():
    app = ConfidentialClientApplication(
        client_id=CLIENT_ID,
        client_credential=CLIENT_SECRET,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}"
    )
    result = app.acquire_token_for_client(scopes=SCOPE)
    return result["access_token"]

# === 2. Leer mensaje de Teams ===
def obtener_html_del_mensaje(token, team_id, channel_id, message_id):
    url = f"https://graph.microsoft.com/v1.0/teams/{team_id}/channels/{channel_id}/messages/{message_id}"
    res = requests.get(url, headers={"Authorization": f"Bearer {token}"})
    res.raise_for_status()
    return res.json()["body"]["content"]

# === 3. Extraer src del <img> ===
def extraer_src(html):
    soup = BeautifulSoup(html, "html.parser")
    img = soup.find("img")
    return img["src"] if img else None

# === 4. Descargar imagen y codificar ===
def descargar_base64_img(src_url, token):
    headers = {"Authorization": f"Bearer {token}"} if "graph.microsoft.com" in src_url else {}
    res = requests.get(src_url, headers=headers)
    res.raise_for_status()
    return base64.b64encode(res.content).decode("utf-8")

# === 5. Llamar a tu API con base64 ===
def procesar_imagen_comercial(comentario, img64):
    payload = {"comentario": comentario, "imagen": img64}
    headers = {"x-api-key": API_KEY, "Content-Type": "application/json"}
    res = requests.post(API_COMERCIAL, json=payload, headers=headers)
    print("[RESPUESTA API]", res.json())
    return res.json()

# === 6. Responder en el hilo original ===
def responder_en_teams(token, team_id, channel_id, message_id, texto):
    url = f"https://graph.microsoft.com/v1.0/teams/{team_id}/channels/{channel_id}/messages/{message_id}/replies"
    payload = {"body": {"content": texto}}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    res = requests.post(url, json=payload, headers=headers)
    print("[RESPUESTA TEAMS]", res.status_code)

# === Endpoint para procesamiento ===
@app.post("/procesar")
async def procesar(request: Request):
    data = await request.json()
    team_id = data.get("team_id")
    channel_id = data.get("channel_id")
    message_id = data.get("message_id")
    comentario = data.get("comentario", "Mensaje desde canal sin adjunto")

    token = obtener_token_graph()
    html = obtener_html_del_mensaje(token, team_id, channel_id, message_id)
    src = extraer_src(html)

    if not src:
        print("[WARN] No se encontró imagen en el mensaje.")
        responder_en_teams(token, team_id, channel_id, message_id, "⚠️ No se encontró ninguna imagen en el mensaje.")
        return {"ok": False, "detalle": "No se encontró <img>"}

    print("[INFO] Imagen encontrada en HTML")
    img64 = descargar_base64_img(src, token)
    resp = procesar_imagen_comercial(comentario, img64)
    responder_en_teams(token, team_id, channel_id, message_id, resp.get("respuesta", "No se detectó comercial."))
    return {"ok": True, "respuesta": resp}
