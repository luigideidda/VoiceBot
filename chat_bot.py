from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse

app = Flask(__name__)

@app.get("/health")
def health():
    return "ok", 200

@app.post("/chatbot")
def chatbot():
    # log utile per capire cosa arriva da Twilio
    print("FORM:", request.form.to_dict())

    incoming = (request.form.get("Body") or "").strip().lower()

    resp = MessagingResponse()
    msg = resp.message()

    if "ciao" in incoming:
        msg.body("Ciao 👋 Sono il tuo bot WhatsApp su Twilio.")
    elif "aiuto" in incoming:
        msg.body("Posso rispondere a domande semplici. Prova a scrivere 'ciao'.")
    else:
        msg.body("Non ho capito 🤔. Scrivi 'aiuto' per vedere cosa posso fare.")

    return Response(str(resp), mimetype="application/xml")

if __name__ == "__main__":
    app.run(port=5000, debug=True)
