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
STRIPE_API_KEY   = os.getenv("STRIPE_SECRET_KEY")
EMAIL_FROM       = os.getenv("EMAIL_FROM")
EMAIL_PASS       = os.getenv("EMAIL_APP_PASSWORD")
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID")
SHEET_NAME       = os.getenv("SHEET_NAME", "Sheet1")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT_SSL = 465

stripe.api_key = STRIPE_API_KEY


# ---------- Helpers Google Sheets ----------
def ws_readonly():
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds  = Credentials.from_service_account_file("service_account_Sheet.json", scopes=scopes)
    gc     = gspread.authorize(creds)
    return gc.open_by_key(GOOGLE_SHEETS_ID).worksheet(SHEET_NAME)

def ws_readwrite():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds  = Credentials.from_service_account_file("service_account_Sheet.json", scopes=scopes)
    gc     = gspread.authorize(creds)
    return gc.open_by_key(GOOGLE_SHEETS_ID).worksheet(SHEET_NAME)

def update_cell(row_index: int, header_name: str, value: str):
    ws = ws_readwrite()
    col = ws.find(header_name).col
    ws.update_cell(row_index, col, value)


# ---------- Email ----------
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


# ---------- Core ----------
def check_and_reassign():
    ws = ws_readonly()
    rows = ws.get_all_records()

    with open("buyers.json", "r", encoding="utf-8") as f:
        buyers = json.load(f)

    for row_index, lead in enumerate(rows, start=2):  # 2 perché riga 1 = header
        status = (lead.get("status") or "").strip().lower()
        sent_at_str = lead.get("sent_at", "").strip()

        if not status.startswith("inviato_"):
            continue

        if not sent_at_str:
            print(f"⚠️ Riga {row_index}: status={status} ma manca sent_at, salto.")
            continue

        try:
            sent_at = datetime.fromisoformat(sent_at_str)
        except Exception:
            print(f"⚠️ Riga {row_index}: sent_at non valido ({sent_at_str}), salto.")
            continue

        # aspetta 30 minuti dall'ultimo invio
        if datetime.now(ZoneInfo("Europe/Rome")) - sent_at < timedelta(minutes=30):
            continue

        # trova quale buyer ha ricevuto l'ultima email
        last_buyer_name = status.replace("inviato_", "")
        last_index = next((i for i, b in enumerate(buyers) if b["name"].lower() == last_buyer_name.lower()), None)

        if last_index is None:
            print(f"⚠️ Riga {row_index}: buyer {last_buyer_name} non trovato in buyers.json")
            continue

        next_index = last_index + 1
        if next_index >= len(buyers):
            # non ci sono più buyer -> invenduto
            update_cell(row_index, "status", "invenduto")
            print(f"🚫 Lead riga {row_index} segnato come invenduto")
            continue

        next_buyer = buyers[next_index]

        # crea checkout session per il nuovo buyer
        try:
            session = stripe.checkout.Session.create(
                mode="payment",
                line_items=[{"price": lead["stripe_price_id"], "quantity": 1}],
                success_url="https://example.com/success",
                cancel_url="https://example.com/cancel",
                client_reference_id=str(row_index - 1),
                metadata={"lead_id": str(row_index - 1), "buyer_index": str(next_index)},
                expires_at=int(time.time()) + 30 * 60
            )
            checkout_url = session.url
        except Exception as e:
            print(f"❌ Stripe error riga {row_index}: {e}")
            continue

        # prepara email
        subject = f"Nuovo lead! – {lead.get('service','')}"
        phone = str(lead.get("phone", ""))
        masked_phone = phone[:1] + " *** " + phone[-1:] if len(phone) > 5 else "******"
        body_txt = f"""Hai ricevuto un nuovo lead:

Servizio: {lead.get('service','')}
Zona: {lead.get('zone','')}
Tempistica: {lead.get('timing','')}
Telefono: {masked_phone}
Prezzo: {lead.get('€','')}

Per ricevere il numero completo, procedi al pagamento (entro 30 minuti) cliccando qui:
{checkout_url}
"""

        try:
            send_email(next_buyer["email"], subject, body_txt)
            print(f"✅ Email inviata a {next_buyer['name']} ({next_buyer['email']}) per riga {row_index}")
        except Exception as e:
            print(f"❌ Errore invio email riga {row_index}: {e}")
            continue

        # aggiorna lo sheet con il nome ufficiale preso da buyers.json
        try:
            update_cell(row_index, "status", f"inviato_{next_buyer['name']}")
            update_cell(row_index, "sent_at", datetime.now(ZoneInfo("Europe/Rome")).isoformat(timespec="seconds"))
        except Exception as e:
            print(f"❌ Errore aggiornamento sheet riga {row_index}: {e}")


if __name__ == "__main__":
    print("⏳ Avvio scheduler lead...")
    while True:
        check_and_reassign()
        time.sleep(30)  # controlla ogni 30 secondi
