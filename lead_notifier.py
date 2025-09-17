# lead_notifier.py
import os, json
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv
load_dotenv()

# ==== ENV (solo quelli che già hai) ====
EMAIL_FROM        = os.getenv("EMAIL_FROM", "")
EMAIL_APP_PASSWORD= os.getenv("EMAIL_APP_PASSWORD", "")
BUYERS_JSON_PATH  = os.getenv("BUYERS_JSON", "buyers.json")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465

app = FastAPI()

# ==== Utils ====
def load_buyers():
    with open(BUYERS_JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def send_email(to_email: str, subject: str, body_txt: str, body_html: str = None):
    if not EMAIL_FROM or not EMAIL_APP_PASSWORD:
        raise RuntimeError("Email non configurata correttamente (manca EMAIL_FROM o EMAIL_APP_PASSWORD)")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = to_email
    msg.attach(MIMEText(body_txt, "plain", "utf-8"))
    if body_html:
        msg.attach(MIMEText(body_html, "html", "utf-8"))

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as s:
        s.login(EMAIL_FROM, EMAIL_APP_PASSWORD)
        s.send_message(msg)
    print("Email inviata a", to_email)

def build_pre_offer_email(lead: dict, buyer: dict):
    subject = f"Nuova potenziale lead – {lead.get('service','')} Milano"
    body_txt = f"""Ciao {buyer.get('name','')},

potremmo avere una lead in linea con i tuoi servizi.

Dettagli:
- Servizio: {lead.get('service','')}
- Zona: {lead.get('zone','')}
- Tempistica: {lead.get('timing','')}
- Telefono: {lead.get('phone','')}
- Timestamp: {lead.get('timestamp','')}

Procedi al pagamento qui:
{lead.get('payment_link','')}

Rispondi a questa email se sei interessato.
"""
    body_html = f"""<p>Ciao {buyer.get('name','')},</p>
<p>Potremmo avere una lead in linea con i tuoi servizi.</p>
<ul>
  <li><b>Servizio:</b> {lead.get('service','')}</li>
  <li><b>Zona:</b> {lead.get('zone','')}</li>
  <li><b>Tempistica:</b> {lead.get('timing','')}</li>
  <li><b>Telefono:</b> {lead.get('phone','')}</li>
  <li><b>Timestamp:</b> {lead.get('timestamp','')}</li>
</ul>
<p><b>Procedi al pagamento qui:</b><br>
<a href="{lead.get('payment_link','')}">{lead.get('payment_link','')}</a></p>

<p>Rispondi a questa email se sei interessato.</p>
"""
    return subject, body_txt, body_html

# ==== Endpoint ====
@app.post("/new-lead", response_class=PlainTextResponse)
async def new_lead(request: Request):
    lead = await request.json()
    print("📩 PAYLOAD ricevuto:", lead)  # <--- DEBUG

    buyers = load_buyers()
    if not buyers:
        return PlainTextResponse("Nessun buyer configurato", status_code=500)

    first_buyer = buyers[0]
    print("👤 Buyer scelto:", first_buyer)  # <--- DEBUG

    subject, body_txt, body_html = build_pre_offer_email(lead, first_buyer)
    print("✉️ Email subject:", subject)   # <--- DEBUG
    print("✉️ Email body:", body_txt)    # <--- DEBUG

    try:
        send_email(first_buyer["email"], subject, body_txt, body_html)
    except Exception as e:
        print("❌ Errore invio email:", e)
        return PlainTextResponse(f"Errore invio email: {e}", status_code=500)

    return PlainTextResponse("ok")
