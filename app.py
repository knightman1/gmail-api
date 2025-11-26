import os
import pickle
import re
import base64
from flask import Flask, request, jsonify
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from flask_cors import CORS

# ===== FLASK + CORS =====
app = Flask(__name__)
CORS(app)  # Permite acceso desde cualquier dominio (tu web)

# ===== CONFIGURACIÓN =====
GMAIL_SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
CREDENTIALS_PATH = 'credentials.json'  # Debe estar como Secret File en Render

# ===== FUNCIONES DE GMAIL =====
def authenticate_gmail(email_address):
    creds = None
    token_path = f'token_{email_address}.json'

    if os.path.exists(token_path):
        with open(token_path, 'rb') as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, GMAIL_SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_path, 'wb') as token:
            pickle.dump(creds, token)

    service = build('gmail', 'v1', credentials=creds)
    return service


def get_last_email(service, email_address):
    results = service.users().messages().list(
        userId=email_address, 
        labelIds=['INBOX'], 
        q="is:unread"
    ).execute()

    messages = results.get('messages', [])
    if not messages:
        return None, None

    message = service.users().messages().get(
        userId=email_address, 
        id=messages[0]['id'], 
        format='full'
    ).execute()

    payload = message.get('payload', {})
    body = ""

    parts = payload.get('parts', [])
    for part in parts:
        if part.get('mimeType') == 'text/plain':
            body = part.get('body', {}).get('data', '')

    if body:
        body = base64.urlsafe_b64decode(body).decode('utf-8', errors='ignore')

    return message['snippet'], body


def analyze_email_body(body):
    match_update = re.search(r'Sí, la envié yo.*?(https?://[^\s]+)', body, re.DOTALL)
    if match_update:
        return "Actualizar hogar", match_update.group(1)

    match_code = re.search(r'Obtener código.*?(https?://[^\s]+)', body, re.DOTALL)
    if match_code:
        return "Código de acceso temporal", match_code.group(1)

    return "Otro", None


# ===== RUTAS FLASK =====
@app.route("/")
def index():
    return "API Gmail lista. Usar POST /email con JSON { 'email': 'ejemplo@gmail.com' }"


@app.route("/email", methods=["POST"])
def email_query():
    data = request.json
    email = data.get("email")

    if not email:
        return jsonify({"message": "❌ No se envió correo"}), 400

    try:
        service = authenticate_gmail(email)
        snippet, body = get_last_email(service, email)

        if not body:
            return jsonify({"message": "📭 No hay correos no leídos."})

        marca, link = analyze_email_body(body)

        if marca == "Actualizar hogar" and link:
            msg = f"✅ {email}\nActualizar hogar:\n{link}"
        elif marca == "Código de acceso temporal" and link:
            msg = f"✅ {email}\nCódigo de acceso:\n{link}"
        else:
            msg = f"⚠️ {email}: Correo encontrado, pero sin enlace útil."

        return jsonify({"message": msg})

    except Exception as e:
        return jsonify({"message": f"❌ Error con {email}:\n{str(e)}"}), 500


# ===== INICIO =====
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
