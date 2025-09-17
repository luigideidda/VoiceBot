import os, smtplib, json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from flask import Flask, request
from dotenv import load_dotenv
import stripe
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from zoneinfo import ZoneInfo

load_dotenv()

# === ENV ===
WEBHOOK_SECRET   = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_API_KEY   = os.getenv("STRIPE_SECRET_KEY")

EMAIL_FROM       = os.getenv("EMAIL_FROM")
EMAIL_PASS       = os.getenv("EMAIL_APP_PASSWORD")
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID")
SHEET_NAME       = os.getenv("SHEET_NAME", "Sheet1")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT_SSL = 465

stripe.api_key = STRIPE_API_KEY
app = Flask(__name__)


def update_lead_status(row_index: int, status: str):
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds  = Credentials.from_service_account_file("service_account_Sheet.json", scopes=scopes)
    gc     = gspread.authorize(creds)
    ws     = gc.open_by_key(GOOGLE_SHEETS_ID).worksheet(SHEET_NAME)
    ws.update_cell(row_index, ws.find("status").col, status)
    print(f"✅ Lead alla riga {row_index} aggiornato a status={status}")

def update_lead_field(row_index: int, header_name: str, value: str):
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds  = Credentials.from_service_account_file("service_account_Sheet.json", scopes=scopes)
    gc     = gspread.authorize(creds)
    ws     = gc.open_by_key(GOOGLE_SHEETS_ID).worksheet(SHEET_NAME)
    col    = ws.find(header_name).col
    ws.update_cell(row_index, col, value)
    print(f"✅ Lead riga {row_index}: {header_name} = {value}")


def read_lead_by_id(lead_id: int):
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds  = Credentials.from_service_account_file("service_account_Sheet.json", scopes=scopes)
    gc     = gspread.authorize(creds)
    ws     = gc.open_by_key(GOOGLE_SHEETS_ID).worksheet(SHEET_NAME)
    rows   = ws.get_all_records()
    return rows[lead_id - 1]  # 1-based


def send_email(to_email: str, subject: str, body_txt: str):
    msg = MIMEMultipart()
    msg["From"] = EMAIL_FROM
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body_txt, "plain", "utf-8"))

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT_SSL) as s:
        s.login(EMAIL_FROM, EMAIL_PASS)
        s.send_message(msg)

    print("📧 Email inviata a:", to_email)


@app.post("/stripe/webhook")
def stripe_webhook():
    payload    = request.data
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=WEBHOOK_SECRET,
        )
    except stripe.error.SignatureVerificationError:
        print("❌ Firma non valida")
        return "Invalid signature", 400
    except Exception as e:
        print("❌ Errore parsing webhook:", e)
        return f"Webhook error: {e}", 400

    print(f"✅ Evento ricevuto: {event['type']}")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]

        # ✅ Controlla che il pagamento sia stato effettivamente completato
        if session.get("payment_status") != "paid":
            print(f"⚠️ Session completata ma non pagata (status={session.get('payment_status')})")
            return "ok", 200

        lead_id = session.get("client_reference_id") or (session.get("metadata") or {}).get("lead_id")
        buyer_index = (session.get("metadata") or {}).get("buyer_index")

        print("🔗 Lead ID:", lead_id)
        print("🏷️ Buyer index:", buyer_index)

        if lead_id and buyer_index is not None:
            # Carica il buyer corretto da buyers.json
            try:
                with open("buyers.json", "r", encoding="utf-8") as f:
                    buyers = json.load(f)
                buyer_index = int(buyer_index)
                buyer = buyers[buyer_index]
                buyer_name = buyer.get("name", f"buyer{buyer_index}")
                buyer_email = buyer.get("email")
            except Exception as e:
                print(f"❌ Errore recupero buyer: {e}")
                return "Invalid buyer", 400

            # recupera la lead
            lead = read_lead_by_id(int(lead_id))
            phone_full = str(lead.get("phone", ""))

            subject = f"Dettagli lead sbloccati – {lead.get('service','')}"
            body = f"""Grazie per il pagamento {buyer_name}!

Dettagli completi del lead:
- Servizio: {lead.get('service','')}
- Zona: {lead.get('zone','')}
- Tempistica: {lead.get('timing','')}
- Telefono: {phone_full}
- Prezzo: {lead.get('€','')}
"""

            # Invia al buyer corretto (non al payer_email di Stripe!)
            send_email(buyer_email, subject, body)

            # Aggiorna status con il nome reale del buyer
            row_index = int(lead_id) + 1  # header +1
            update_lead_status(row_index, f"venduto_{buyer_name}")
            # Scrivi anche la data/ora della vendita
            sold_at_value = datetime.now(ZoneInfo("Europe/Rome")).isoformat(timespec="seconds")
            update_lead_field(row_index, "sold_at", sold_at_value)

    return "ok", 200


if __name__ == "__main__":
    app.run(port=4242, debug=True)
