import os, json, time, smtplib
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
STRIPE_API_KEY    = os.getenv("STRIPE_SECRET_KEY")
EMAIL_FROM        = os.getenv("EMAIL_FROM")
EMAIL_PASS        = os.getenv("EMAIL_APP_PASSWORD")
GOOGLE_SHEETS_ID  = os.getenv("GOOGLE_SHEETS_ID")
SHEET_NAME        = os.getenv("SHEET_NAME", "Sheet1")

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
    if not to_email:
        raise ValueError("Destinatario email vuoto")
    msg = MIMEMultipart()
    msg["From"] = EMAIL_FROM
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body_txt, "plain", "utf-8"))

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT_SSL) as s:
        s.login(EMAIL_FROM, EMAIL_PASS)
        s.send_message(msg)

# ---------- Core ----------
def process_new_leads_once():
    """Legge il foglio e processa tutte le righe con status == 'nuovo'."""
    ws = ws_readonly()
    rows = ws.get_all_records()

    # carica buyers e prendi il primo
    with open("buyers.json", "r", encoding="utf-8") as f:
        buyers = json.load(f)
    if not buyers or not buyers[0].get("email"):
        print("⚠️ Nessun buyer valido in buyers.json")
        return

    first_buyer = buyers[0]

    # scorri le righe con indice reale di foglio (2 = prima riga dati)
    for row_index, lead in enumerate(rows, start=2):
        status = (lead.get("status") or "").strip().lower()
        if status != "nuovo":
            continue

        price_id = lead.get("stripe_price_id")
        if not price_id:
            print(f"⚠️ Riga {row_index}: manca stripe_price_id, salto.")
            continue

        # Crea checkout session (min 30 min per Stripe)
        try:
            session = stripe.checkout.Session.create(
                mode="payment",
                line_items=[{"price": price_id, "quantity": 1}],
                success_url="https://example.com/success",
                cancel_url="https://example.com/cancel",
                client_reference_id=str(row_index - 1),  # lead_id = indice 1-based
                metadata={"lead_id": str(row_index - 1), "buyer_index": "0"},
                expires_at=int(time.time()) + 30 * 60
            )
            checkout_url = session.url
        except Exception as e:
            print(f"❌ Stripe error riga {row_index}: {e}")
            continue

        # Prepara email
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

        # Invia email e aggiorna stato/sent_at
        try:
            send_email(first_buyer["email"], subject, body_txt)
            print(f"✅ Email inviata a {first_buyer['email']} per riga {row_index}")
        except Exception as e:
            print(f"❌ Errore invio email riga {row_index}: {e}")
            # non aggiorno lo stato se la mail non è partita
            continue

        try:
            # status -> inviato_<nome buyer>
            buyer_name = first_buyer.get("name", f"buyer0")
            update_cell(row_index, "status", f"inviato_{buyer_name.replace(' ', '_')}")
            # sent_at -> ora italiana
            update_cell(
                row_index,
                "sent_at",
                datetime.now(ZoneInfo("Europe/Rome")).isoformat(timespec="seconds")
            )
            print(f"📝 Aggiornati status=inviato_buyer1 e sent_at per riga {row_index}")
        except Exception as e:
            print(f"❌ Errore aggiornamento sheet riga {row_index}: {e}")

def main():
    print("👀 lead_watcher avviato: controllo ogni 10 minuti per nuove lead (status=nuovo).")
    while True:
        try:
            process_new_leads_once()
        except KeyboardInterrupt:
            print("👋 Uscita richiesta.")
            break
        except Exception as e:
            print(f"❌ Errore inatteso nel watcher: {e}")
        # attende 10 minuti
        time.sleep(1 * 60)

if __name__ == "__main__":
    main()
