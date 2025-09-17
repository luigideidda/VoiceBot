import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv

# Carica variabili da .env
load_dotenv()

EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")

def send_test_email():
    recipient = EMAIL_FROM  # mandiamo a noi stessi
    subject = "Test invio email dal VoiceBot"
    body = "Se stai leggendo questa email, la configurazione SMTP con Gmail funziona correttamente 🎉"

    # Crea messaggio MIME
    msg = MIMEMultipart()
    msg["From"] = EMAIL_FROM
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        # Connessione SMTP a Gmail
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_FROM, EMAIL_APP_PASSWORD)
            server.sendmail(EMAIL_FROM, recipient, msg.as_string())
        print("✅ Email inviata con successo!")
    except Exception as e:
        print("❌ Errore nell'invio email:", e)

if __name__ == "__main__":
    send_test_email()
