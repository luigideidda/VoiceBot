import os, time, json, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv
import stripe

load_dotenv()

# === ENV ===
STRIPE_API_KEY = os.getenv("STRIPE_SECRET_KEY")
EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_PASS = os.getenv("EMAIL_APP_PASSWORD")
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID")
SHEET_NAME = os.getenv("SHEET_NAME", "Sheet1")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT_SSL = 465

stripe.api_key = STRIPE_API_KEY


def update_lead_status(row_index: int, status: str):
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file("service_account_Sheet.json", scopes=scopes)
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(GOOGLE_SHEETS_ID).worksheet(SHEET_NAME)
    ws.update_cell(row_index, ws.find("status").col, status)
    print(f"✅ Lead alla riga {row_index} aggiornato a status={status}")


def send_email(to_email, subject, body_txt):
    msg = MIMEMultipart()
    msg["From"] = EMAIL_FROM
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body_txt, "plain", "utf-8"))

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT_SSL) as s:
        s.login(EMAIL_FROM, EMAIL_PASS)
        s.send_message(msg)
    print("📧 Email inviata a:", to_email)


def check_and_reassign():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file("service_account_Sheet.json", scopes=scopes)
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(GOOGLE_SHEETS_ID).worksheet(SHEET_NAME)
    rows = ws.get_all_records()

    with open("buyers.json", "r", encoding="utf-8") as f:
        buyers = json.load(f)

    for i, lead in enumerate(rows, start=2):  # start=2 perché riga 1 è header
        status = lead.get("status")
        if status == "inviato_buyer1":
            # usa la colonna sent_at invece di timestamp
            ts_str = lead.get("sent_at")
            if not ts_str:
                print(f"⚠️ Nessun sent_at trovato per la riga {i}, skip")
                continue

            try:
                ts = datetime.fromisoformat(ts_str)
            except Exception:
                print(f"⚠️ sent_at non valido per la riga {i}: {ts_str}")
                continue

            # confronto in fuso orario Italia
            if datetime.now(ZoneInfo("Europe/Rome")) - ts > timedelta(minutes=30):
                # crea nuova checkout session per buyer2
                session = stripe.checkout.Session.create(
                    mode="payment",
                    line_items=[{"price": lead["stripe_price_id"], "quantity": 1}],
                    success_url="https://example.com/success",
                    cancel_url="https://example.com/cancel",
                    client_reference_id=str(i - 1),
                    metadata={"lead_id": str(i - 1), "buyer_index": "1"},
                    expires_at=int(time.time()) + 30 * 60
                )
                checkout_url = session.url

                if len(buyers) > 1 and buyers[1].get("email"):
                    buyer2 = buyers[1]
                    subject = f"Nuovo lead! – {lead.get('service','')}"
                    phone = str(lead.get("phone", ""))
                    masked_phone = phone[:1] + " *** " + phone[-2:] if len(phone) > 5 else "******"
                    body_txt = f"""Hai ricevuto un nuovo lead:

Servizio: {lead.get('service', '')}
Zona: {lead.get('zone', '')}
Tempistica: {lead.get('timing', '')}
Telefono: {masked_phone}
Prezzo: {lead.get('€', '')}

Per ricevere il numero completo, procedi al pagamento (entro 30 minuti) cliccando qui:
{checkout_url}
"""

                    send_email(buyer2["email"], subject, body_txt)
                    buyer_name = buyer2.get("name", f"buyer2")
                    update_lead_status(i, f"inviato_{buyer_name.replace(' ', '_')}")


if __name__ == "__main__":
    print("⏳ Avvio scheduler lead...")
    while True:
        check_and_reassign()
        time.sleep(30)  # controlla ogni 30 secondi
