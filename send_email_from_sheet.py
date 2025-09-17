import os
import smtplib
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

# Carica .env
load_dotenv()

GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID")
SHEET_NAME = os.getenv("SHEET_NAME", "Sheet1")
EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_PASS = os.getenv("EMAIL_APP_PASSWORD")
STRIPE_PAYMENT_LINK = "https://buy.stripe.com/test_7sYeVd2sqcQMcbce100sU00"


# === 1. Leggi ultimo record da Google Sheet ===
GS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
GS_CREDS = Credentials.from_service_account_file("service_account_Sheet.json", scopes=GS_SCOPES)
gclient = gspread.authorize(GS_CREDS)

sh = gclient.open_by_key(GOOGLE_SHEETS_ID)
ws = sh.worksheet(SHEET_NAME)
rows = ws.get_all_records()

if not rows:
    raise RuntimeError("Nessuna riga nel foglio.")

last = rows[-1]  # ultima riga
print("Ultimo record:", last)

# === 2. Carica i buyers dal JSON ===
with open("buyers.json", "r", encoding="utf-8") as f:
    buyers = json.load(f)

if not buyers:
    raise RuntimeError("Nessun buyer trovato in buyers.json")

# === 3. Prepara email ===
subject = f"Nuovo lead! – {last.get('service','')}"

# offusca telefono
phone = str(last.get("phone", ""))
masked_phone = phone[:3] + " *** " + phone[-2:] if len(phone) > 5 else "******"

# versione plain text
body_txt = f"""
Hai ricevuto un nuovo lead:

Servizio: {last.get('service','')}
Zona: {last.get('zone','')}
Tempistica: {last.get('timing','')}
Telefono: {masked_phone} 
Prezzo: {last.get('€','')}

Per ricevere il numero del telefono del potenziale cliente procedi al pagamento cliccando qui:
{STRIPE_PAYMENT_LINK}
"""


msg = MIMEMultipart()
msg["From"] = EMAIL_FROM
msg["Subject"] = subject
msg.attach(MIMEText(body_txt, "plain", "utf-8"))

# === 4. Invia a tutti i buyer ===
with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
    server.login(EMAIL_FROM, EMAIL_PASS)
    for b in buyers:
        if not b.get("email"):
            continue

        # crea un messaggio nuovo per ogni buyer
        msg = MIMEMultipart()
        msg["From"] = EMAIL_FROM
        msg["To"] = b["email"]
        msg["Subject"] = subject
        msg.attach(MIMEText(body_txt, "plain", "utf-8"))

        server.sendmail(EMAIL_FROM, b["email"], msg.as_string())
        print("✅ Email inviata a", b["email"])

