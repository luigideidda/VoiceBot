import os
import re
import csv
import json
import urllib.parse
import requests
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, Form, Request, HTTPException, Body
from fastapi.responses import PlainTextResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from twilio.twiml.voice_response import VoiceResponse, Gather
from dotenv import load_dotenv

# ==== Google Sheets ====
import gspread
from google.oauth2.service_account import Credentials

# =========================
# Config & storage
# =========================
load_dotenv()

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:3000").rstrip("/")
ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY", "")
ELEVEN_VOICE_ID = os.getenv("ELEVEN_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")

# Google Sheets ENV
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "").strip()
SHEET_NAME = os.getenv("SHEET_NAME", "Sheet1").strip() or "Sheet1"

# === Inizializza Google Sheets client ===
GS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
GS_CREDS = Credentials.from_service_account_file("service_account_Sheet.json", scopes=GS_SCOPES)
gclient = gspread.authorize(GS_CREDS)

app = FastAPI()

# === Abilita CORS per la landing su systeme.io ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://adv-mattia1.systeme.io"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

sessions = {}  # in-RAM (in produzione: Redis/DB)
FIRST_STEP = "service"

# === CSV locale come backup
CSV_PATH = Path("data/leads.csv")
CSV_FIELDS = [
    "vertical", "city", "service", "zone", "timing",
    "phone", "consent", "source", "timestamp", "stripe_price_id", "€",
    "status", "sent_at", "sold_at"
]


PRICE_MAP = {
    "price_1S5ox3ELPxBtB8l9Xs7sIc43": "€ 100,00",   # funerale immediato
    "price_1S5oDJELPxBtB8l9GWjyQZHC": "€ 75,00",   # funerale entro 24h
    "price_1S5oEeELPxBtB8l9g38R6i0N": "€ 45,00",   # funerale entro 7 giorni
    "price_1S5p8IELPxBtB8l90NCfNK8Y": "€ 90,00",   # cremazione immediata
    "price_1S5pCRELPxBtB8l9D7grFvYf": "€ 65,00",   # cremazione entro 24h
    "price_1S5pDCELPxBtB8l94iiPKYEw": "€ 35,00",   # cremazione entro 7 giorni
    "price_1S5pDrELPxBtB8l9YdyAHYdU": "€ 80,00",   # trasferimento immediato
    "price_1S5pEXELPxBtB8l9kEgY4YZd": "€ 55,00",   # trasferimento entro 24h
    "price_1S5pFgELPxBtB8l9YkhAqlhA": "€ 30,00",    # trasferimento entro 7 giorni
}

def get_price_from_id(price_id: str) -> str:
    return PRICE_MAP.get(price_id, "")


# === Mappa service+timing -> stripe_price_id
STRIPE_PRICE_MAP = {
    "funerale": {
        "immediato": "price_1S5ox3ELPxBtB8l9Xs7sIc43",
        "entro 24h": "price_1S5oDJELPxBtB8l9GWjyQZHC",
        "entro 7 giorni": "price_1S5oEeELPxBtB8l9g38R6i0N",
    },
    "cremazione": {
        "immediato": "price_1S5p8IELPxBtB8l90NCfNK8Y",
        "entro 24h": "price_1S5pCRELPxBtB8l9D7grFvYf",
        "entro 7 giorni": "price_1S5pDCELPxBtB8l94iiPKYEw",
    },
    "trasferimento": {
        "immediato": "price_1S5pDrELPxBtB8l9YdyAHYdU",
        "entro 24h": "price_1S5pEXELPxBtB8l9kEgY4YZd",
        "entro 7 giorni": "price_1S5pFgELPxBtB8l9YkhAqlhA",
    },
}

def get_stripe_price_id(service: str, timing: str) -> str:
    return STRIPE_PRICE_MAP.get(service, {}).get(timing, "")

def save_lead_to_csv(lead: dict):
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    file_exists = CSV_PATH.exists()
    with CSV_PATH.open(mode="a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow({k: lead.get(k, "") for k in CSV_FIELDS})

# ---------- Google Sheets helper ----------
def save_lead_to_gsheet(lead: dict):
    if not GOOGLE_SHEETS_ID:
        raise RuntimeError("GOOGLE_SHEETS_ID non impostato nel .env")
    try:
        sh = gclient.open_by_key(GOOGLE_SHEETS_ID)
        try:
            ws = sh.worksheet(SHEET_NAME)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=SHEET_NAME, rows="100", cols=str(len(CSV_FIELDS)))
            ws.append_row(CSV_FIELDS, value_input_option="USER_ENTERED")

        row = [
            lead.get("vertical", ""),
            lead.get("city", ""),
            lead.get("service", ""),
            lead.get("zone", ""),
            lead.get("timing", ""),
            lead.get("phone", ""),
            str(lead.get("consent", "")),
            lead.get("source", ""),
            lead.get("timestamp", ""),
            lead.get("stripe_price_id", ""),
            lead.get("€", ""),
            lead.get("status", ""),
            lead.get("sent_at", ""),
            lead.get("sold_at", "")
        ]

        if ws.row_count == 0 or ws.acell("A1").value is None:
            ws.append_row(CSV_FIELDS, value_input_option="USER_ENTERED")
        ws.append_row(row, value_input_option="USER_ENTERED")
        print("LEAD SALVATA SU GOOGLE SHEET:", row)
    except Exception as e:
        print("ERRORE SALVATAGGIO GOOGLE SHEET:", e)
        raise

# ---------- TTS ElevenLabs helpers ----------
def tts_url_for(text: str) -> str:
    q = urllib.parse.quote_plus(text)
    return f"{PUBLIC_BASE_URL}/tts?q={q}"

def speak_in_gather(gather: Gather, text: str):
    gather.play(tts_url_for(text))

def speak_in_response(resp: VoiceResponse, text: str):
    resp.play(tts_url_for(text))

def say_and_gather(text: str, action: str = "/voice/handle"):
    resp = VoiceResponse()
    g: Gather = resp.gather(
        input="speech",
        action=action,
        method="POST",
        speech_timeout="auto",
        language="it-IT"
    )
    speak_in_gather(g, text)
    return resp

def clean_phone(raw: str) -> str:
    if not raw:
        return ""
    p = re.sub(r"[^\d+]", "", raw)
    if p.startswith("0"):
        p = "+39" + p.lstrip("0")
    if p.startswith("39") and not p.startswith("+39"):
        p = "+39" + p[2:]
    return p

# =========================
# Endpoint utili
# =========================
@app.get("/health")
def health():
    return {
        "status": "ok",
        "public_base_url": PUBLIC_BASE_URL,
        "eleven_set": bool(ELEVEN_API_KEY),
        "gsheets_set": bool(GOOGLE_SHEETS_ID),
        "sheet_name": SHEET_NAME
    }

@app.post("/twiml-test", response_class=PlainTextResponse)
async def twiml_test():
    resp = VoiceResponse()
    speak_in_response(resp, "Questo è un test in italiano. Se mi senti, il numero è configurato correttamente.")
    return PlainTextResponse(str(resp), media_type="text/xml")

# ---------- Endpoint TTS ----------
@app.get("/tts")
def tts(q: str):
    if not ELEVEN_API_KEY:
        raise HTTPException(status_code=500, detail="ELEVEN_API_KEY mancante")
    text = (q or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Parametro q mancante")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE_ID}"
    headers = {
        "xi-api-key": ELEVEN_API_KEY,
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.8}
    }
    r = requests.post(url, headers=headers, json=payload, timeout=20)
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Errore ElevenLabs: {r.status_code} - {r.text[:200]}")

    return Response(content=r.content, media_type="audio/mpeg")

# =========================
# Endpoint dal form landing
# =========================
@app.post("/lead/form")
async def lead_form(payload: dict = Body(...)):
    try:
        servizio = payload.get("servizio", "").strip().lower()
        zona = payload.get("zona", "").strip()
        urgenza = payload.get("urgenza", "").strip().lower()
        telefono = payload.get("telefono", "").strip()

        # Normalizzazione service
        if "funerale" in servizio:
            service = "funerale"
        elif "cremaz" in servizio:
            service = "cremazione"
        elif "trasfer" in servizio or "salma" in servizio:
            service = "trasferimento"
        else:
            service = servizio or "altro"

        # Normalizzazione timing
        if "prima" in urgenza or "subito" in urgenza or "immediat" in urgenza:
            timing = "immediato"
        elif "24" in urgenza:
            timing = "entro 24h"
        else:
            timing = "entro 7 giorni"

        stripe_price_id = get_stripe_price_id(service, timing)
        #print("DEBUG service:", service, "timing:", timing, "-> stripe_price_id:", stripe_price_id)

        lead = {
            "vertical": "onoranze_funebri",
            "city": "Milano",
            "service": service,
            "zone": zona,
            "timing": timing,
            "phone": telefono,
            "consent": True,
            "source": "form-landing",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "stripe_price_id": stripe_price_id,
            "€": get_price_from_id(stripe_price_id),
            "status": "nuovo",
            "sent_at": "",
            "sold_at": ""
        }

        save_lead_to_gsheet(lead)
        return {"success": True, "lead": lead}
    except Exception as e:
        print("ERRORE /lead/form:", e)
        return {"success": False, "error": str(e)}

# =========================
# Flusso Voice
# =========================
@app.post("/voice/incoming", response_class=PlainTextResponse)
async def voice_incoming(
    request: Request,
    CallSid: str = Form(...),
):
    get_session(CallSid)
    text = (
        "Buongiorno. Ti aiuto a ricevere un preventivo gratuito e discreto "
        "per un’agenzia funebre a Milano. Ti farò poche domande. "
        "Di cosa hai bisogno: funerale completo, cremazione o trasferimento salma?"
    )
    resp = say_and_gather(text)
    return PlainTextResponse(str(resp), media_type="text/xml")

def get_session(call_sid: str):
    if call_sid not in sessions:
        sessions[call_sid] = {"step": FIRST_STEP, "data": {}}
    return sessions[call_sid]

@app.post("/voice/handle", response_class=PlainTextResponse)
async def voice_handle(
    request: Request,
    CallSid: str = Form(...),
    SpeechResult: str = Form(default=""),
):
    s = get_session(CallSid)

    def _advance_and_say(next_step: str, text: str):
        s["step"] = next_step
        return PlainTextResponse(str(say_and_gather(text)), media_type="text/xml")

    def _repeat(text: str, same_step: str):
        s["step"] = same_step
        return PlainTextResponse(str(say_and_gather(text)), media_type="text/xml")

    tclean = (SpeechResult or "").lower()

    # 1) Servizio
    if s["step"] == "service":
        if "cremaz" in tclean:
            s["data"]["service"] = "cremazione"
        elif "funeral" in tclean or "funerale" in tclean:
            s["data"]["service"] = "funerale"
        elif "trasfer" in tclean or "salma" in tclean:
            s["data"]["service"] = "trasferimento"
        else:
            return _repeat("Non ho capito bene. Ti serve un funerale, una cremazione o un trasferimento salma?", "service")
        return _advance_and_say("zone", "In quale zona o quartiere di Milano serve il servizio?")

    # 2) Zona
    if s["step"] == "zone":
        z = (SpeechResult or "").strip()
        if not z:
            return _repeat("Puoi ripetere la zona di Milano?", "zone")
        s["data"]["zone"] = z
        return _advance_and_say("timing", "Serve subito, entro ventiquattro ore, oppure nei prossimi giorni?")

    # 3) Tempistica
    if s["step"] == "timing":
        if "subito" in tclean or "immediat" in tclean:
            s["data"]["timing"] = "immediato"
        elif "24" in tclean or "ventiquattro" in tclean or "domani" in tclean:
            s["data"]["timing"] = "entro 24h"
        else:
            s["data"]["timing"] = "entro 7 giorni"
        return _advance_and_say("phone", "Perfetto. Mi lasci un numero di telefono per l’invio della stima e la chiamata di conferma?")

    # 4) Telefono
    if s["step"] == "phone":
        phone = clean_phone(SpeechResult or "")
        if not phone or len(re.sub(r"\D", "", phone)) < 9:
            return _repeat("Il numero non sembra valido. Potresti ripeterlo lentamente, per favore?", "phone")
        s["data"]["phone"] = phone
        return _advance_and_say("consent", "Confermi che possiamo far contattare il tuo numero da un’agenzia autorizzata della tua zona, solo per confermare il preventivo?")

    # 5) Consenso e chiusura
    if s["step"] == "consent":
        consent = any(x in tclean for x in ["si", "sì", "ok", "va bene", "confermo"])
        s["data"]["consent"] = consent

        resp = VoiceResponse()

        if not consent:
            speak_in_response(resp, "Capito. Non procederò con il contatto. Se cambi idea, puoi richiamarci quando vuoi. Un caro saluto.")
            resp.hangup()
            sessions.pop(CallSid, None)
            return PlainTextResponse(str(resp), media_type="text/xml")

        # === Calcolo stripe_price_id
        service = s["data"].get("service")
        timing = s["data"].get("timing")
        stripe_price_id = get_stripe_price_id(service, timing)

        lead = {
            "vertical": "onoranze_funebri",
            "city": "Milano",
            "service": service,
            "zone": s["data"].get("zone"),
            "timing": timing,
            "phone": s["data"].get("phone"),
            "consent": True,
            "source": "voicebot",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "stripe_price_id": stripe_price_id,
            "€": get_price_from_id(stripe_price_id),
            "status": "nuovo",
            "sent_at": "",
            "sold_at": ""
        }

        try:
            save_lead_to_gsheet(lead)
        except Exception:
            try:
                save_lead_to_csv(lead)
            except Exception as e:
                print("ERRORE SALVATAGGIO CSV:", e)

        speak_in_response(resp, "Grazie. Riceverai a breve una stima indicativa e la chiamata di conferma. Siamo a disposizione ventiquattro ore su ventiquattro.")
        resp.hangup()
        sessions.pop(CallSid, None)
        return PlainTextResponse(str(resp), media_type="text/xml")

    # Fallback
    resp = VoiceResponse()
    speak_in_response(resp, "Grazie per la chiamata. Un saluto.")
    resp.hangup()
    sessions.pop(CallSid, None)
    return PlainTextResponse(str(resp), media_type="text/xml")

