import os, smtplib, json, time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
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
    """Aggiorna lo status di una riga nel Google Sheet"""
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file("service_account_Sheet.json", scopes=scopes)
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(GOOGLE_SHEETS_ID).worksheet(SHEET_NAME)
    ws.update_cell(row_index, ws.find("status").col, status)
    print(f"✅ Lead alla riga {row_index} aggiornato a status={status}")


def update_sent_at(row_index: int):
    """Aggiorna la colonna sent_at con ora italiana di invio"""
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file("service_account_Sheet.json", scopes=scopes)
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(GOOGLE_SHEETS_ID).worksheet(SHEET_NAME)

    ws.update_cell(
        row_index,
        ws.find("sent_at").col,
        datetime.now(ZoneInfo("Europe/Rome")).isoformat(timespec="seconds")
    )
    print(f"✅ Lead alla riga {row_index} aggiornato con sent_at")


# === 1. Leggi lead disponibili ===
scopes_read = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
creds_read = Credentials.from_service_account_file("service_account_Sheet.json", scopes=scopes_read)
gc_read = gspread.authorize(creds_read)
ws_read = gc_read.open_by_key(GOOGLE_SHEETS_ID).worksheet(SHEET_NAME)
rows = ws_read.get_all_records()

rows_nuovi = [r for r in rows if r.get("status") == "nuovo"]
if not rows_nuovi:
    raise RuntimeError("Nessun lead nuovo disponibile.")

lead = rows_nuovi[0]   # prendi il primo lead nuovo
lead_id = rows.index(lead) + 1  # indice riga reale (header +1)

print("Lead scelto:", lead)

# === 2. Crea Checkout Session Stripe (scade in 30 minuti) ===
session = stripe.checkout.Session.create(
    mode="payment",
    line_items=[{"price": lead["stripe_price_id"], "quantity": 1}],
    success_url="https://example.com/success",
    cancel_url="https://example.com/cancel",
    client_reference_id=str(lead_id),
    metadata={"lead_id": str(lead_id), "buyer_index": "0"},
    expires_at=int(time.time()) + 30 * 60  # 30 minuti da ora
)

checkout_url = session.url
print("Link generato:", checkout_url)

# === 3. Carica buyers ===
with open("buyers.json", "r", encoding="utf-8") as f:
    buyers = json.load(f)

# === 4. Invia email al primo buyer ===
subject = f"Nuovo lead! – {lead.get('service','')}"
phone = str(lead.get("phone", ""))
masked_phone = phone[:3] + " *** " + phone[-2:] if len(phone) > 5 else "******"

body_txt = f"""Hai ricevuto un nuovo lead:

Servizio: {lead.get('service','')}
Zona: {lead.get('zone','')}
Tempistica: {lead.get('timing','')}
Telefono: {masked_phone}
Prezzo: {lead.get('€','')}

Per ricevere il numero completo, procedi al pagamento (entro 30 minuti) cliccando qui:
{checkout_url}
"""

msg = MIMEMultipart()
msg["From"] = EMAIL_FROM
msg["Subject"] = subject
msg.attach(MIMEText(body_txt, "plain", "utf-8"))

first_buyer = buyers[0]  # manda solo al primo buyer
if first_buyer.get("email"):
    msg["To"] = first_buyer["email"]
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT_SSL) as s:
        s.login(EMAIL_FROM, EMAIL_PASS)
        s.sendmail(EMAIL_FROM, first_buyer["email"], msg.as_string())
        print("✅ Email inviata a", first_buyer["email"])

# === 5. Aggiorna status e sent_at ===
update_lead_status(lead_id + 1, "inviato_buyer1")  # +1 perché la prima riga è l’header
update_sent_at(lead_id + 1)
