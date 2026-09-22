import streamlit as st
import streamlit.components.v1 as components
from google import genai
import datetime
import os
import docx
import pandas as pd
import re
import uuid
import bcrypt
import time
import json
import hmac

# 0. Paginainstellingen & Constanten
st.set_page_config(page_title="Huiswerkcontrole AK", layout="wide")
LAATSTE_UPDATE = "22 september 2026"
VERSIE = "3.0.10"

# 1. API & Cloud instellen
if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
    del os.environ["GOOGLE_APPLICATION_CREDENTIALS"]

api_key = st.secrets["GEMINI_API_KEY"].replace('"', '').replace("'", "").strip()
os.environ["GEMINI_API_KEY"] = api_key

if "ai_client" not in st.session_state:
    st.session_state.ai_client = genai.Client(api_key=api_key)
client = st.session_state.ai_client

# 2. Supabase Connectie (Strikt Vereist)
try:
    from supabase import create_client, Client
    supabase_url = st.secrets["SUPABASE_URL"]
    supabase_key = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(supabase_url, supabase_key)
except Exception as e:
    st.error(f"🚨 Fout bij initialiseren van Supabase. Controleer Streamlit Secrets. Error: {e}")
    st.stop()

# --- STRUCTUUR DEFINIËREN ---
NIVEAUS = {
    "Havo": ["4Hak1", "4Hak2", "4Hak3", "4Hak4", "5Hak1", "5Hak2", "5Hak3"],
    "VWO": ["4Vak1", "5Vak1", "5Vak2", "6Vak1"],
    "Test": ["testklas"]
}
ALLE_CLUSTERS = [klas for klassen in NIVEAUS.values() for klas in klassen]

LEERJAREN_CLUSTERS = {
    "4Havo": ["4Hak1", "4Hak2", "4Hak3", "4Hak4"],
    "5Havo": ["5Hak1", "5Hak2", "5Hak3"],
    "4VWO": ["4Vak1"],
    "5VWO": ["5Vak1", "5Vak2"],
    "6VWO": ["6Vak1"],
    "Testjaar": ["testklas"]
}

HOOFDSTUKKEN = {
    "4Havo": ["H4H1", "H4H2", "H4H3", "H4H4", "H5H1"],
    "5Havo": ["H5H2", "H5H3", "HExamentraining"],
    "4VWO": ["V5H1", "V5H2", "V5H3", "V5H4"],
    "5VWO": ["V4H1", "V4H2", "V4H3", "V6H1"],
    "6VWO": ["V6H2", "V6H3", "VExamentraining"],
    "Testjaar": ["TestMap"]
}

# --- HELPER FUNCTIES CLOUD & DATA ---
def get_leerjaar(cluster_naam):
    for lj, clusters in LEERJAREN_CLUSTERS.items():
        if cluster_naam in clusters:
            return lj
    return None

def haal_bestanden_op(leerjaar, hoofdstuk):
    try:
        pad = f"{leerjaar}/{hoofdstuk}"
        bestanden = supabase.storage.from_("lesmateriaal").list(pad)
        return [b["name"] for b in bestanden if b["name"].endswith('.docx')]
    except Exception:
        return []

def lees_docx(leerjaar, hoofdstuk, bestandsnaam):
    try:
        pad = f"{leerjaar}/{hoofdstuk}/{bestandsnaam}"
        response = supabase.storage.from_("lesmateriaal").download(pad)
        doc = docx.Document(io.BytesIO(response))
        return "\n".join([para.text for para in doc.paragraphs])
    except Exception as e:
        st.error(f"Fout bij lezen uit Supabase: {e}")
        return ""

def haal_alle_resultaten_op():
    try:
        resp = supabase.table("resultaten").select("*").execute()
        return pd.DataFrame(resp.data)
    except Exception as e:
        st.error(f"Fout bij ophalen resultaten: {e}")
        return pd.DataFrame()

def sla_resultaat_op(niveau, cluster, nummer, voornaam, gebruikersnaam, gekozen_les, cijfer, beoordeling, boek_dicht):
    tijdstip = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    poging_id = str(uuid.uuid4())[:8] 
    
    data = {
        "PogingID": poging_id,
        "Tijdstip": tijdstip,
        "Niveau": niveau,
        "Cluster": cluster,
        "Nummer": nummer,
        "Gebruikersnaam": gebruikersnaam,
        "Voornaam": voornaam,
        "Les": gekozen_les,
        "Cijfer": cijfer,
        "Beoordeling": beoordeling,
        "DocentReactie": "",
        "ReactieGelezen": "True",
        "BoekDicht": boek_dicht
    }
    try:
        supabase.table("resultaten").insert(data).execute()
        return True, ""
    except Exception as e:
        return False, str(e)

# --- ACCOUNT & SECURITY FUNCTIES ---
def hash_wachtwoord(wachtwoord):
    return bcrypt.hashpw(wachtwoord.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def controleer_wachtwoord(ingevoerd_wachtwoord, opgeslagen_hash):
    try:
        return bcrypt.checkpw(ingevoerd_wachtwoord.encode('utf-8'), opgeslagen_hash.encode('utf-8'))
    except ValueError:
        return False 

def is_sterk_wachtwoord(wachtwoord):
    if len(wachtwoord) < 8: return False, "Minimaal 8 tekens lang."
    if not re.search(r'\d', wachtwoord): return False, "Minimaal 1 cijfer vereist."
    if not re.search(r'[^a-zA-Z0-9]', wachtwoord): return False, "Minimaal 1 speciaal teken vereist."
    return True, ""

def init_lockout_keys(prefix):
    if f"login_pogingen_{prefix}" not in st.session_state:
        st.session_state[f"login_pogingen_{prefix}"] = 0
    if f"lockout_time_{prefix}" not in st.session_state:
        st.session_state[f"lockout_time_{prefix}"] = 0

def check_lockout(prefix):
    init_lockout_keys(prefix)
    if st.session_state[f"login_pogingen_{prefix}"] >= 5:
        if time.time() < st.session_state[f"lockout_time_{prefix}"]:
            resterend = int(st.session_state[f"lockout_time_{prefix}"] - time.time())
            st.error(f"🔒 Te veel mislukte inlogpogingen. Probeer het over {resterend} seconden opnieuw.")
            return True
        else:
            st.session_state[f"login_pogingen_{prefix}"] = 0
            st.session_state[f"lockout_time_{prefix}"] = 0
    return False

def registreer_fout_inlog(prefix):
    init_lockout_keys(prefix)
    st.session_state[f"login_pogingen_{prefix}"] += 1
    if st.session_state[f"login_pogingen_{prefix}"] >= 5:
        st.session_state[f"lockout_time_{prefix}"] = time.time() + 300 

def laad_gebruikers():
    try:
        response = supabase.table('gebruikers').select("*").execute()
        users = {}
        for row in response.data:
            if "Goedgekeurd" not in row: row["Goedgekeurd"] = "Ja"
            if "Nummer" not in row: row["Nummer"] = "999"
            users[row["Gebruikersnaam"]] = row
        return users
    except Exception as e:
        st.warning(f"Cloud gebruikers ophalen mislukt: {e}")
        return {}

def bewaar_alle_gebruikers(users_dict):
    fouten = []
    for user in users_dict.values():
        try:
            supabase.table('gebruikers').upsert(user).execute()
        except Exception as e:
            fouten.append(str(e))
    if fouten:
        st.error(f"🚨 Supabase Fout bij opslaan gebruikers: {fouten[0]}")

def laad_docenten():
    try:
        response = supabase.table('docenten').select("*").execute()
        docs = {}
        for row in response.data:
            k = row.get("Klassen", "")
            if isinstance(k, str):
                row["Klassen"] = k.split(",") if k else []
            elif isinstance(k, list):
                row["Klassen"] = k
            else:
                row["Klassen"] = []
                
            if "Goedgekeurd" not in row: row["Goedgekeurd"] = "Ja"
            docs[row["DocentID"]] = row
        return docs
    except Exception as e:
        st.warning(f"Cloud docenten ophalen mislukt: {e}")
        return {}

def bewaar_alle_docenten(docs_dict):
    fouten = []
    for doc_data in docs_dict.values():
        save_data = doc_data.copy()
        if isinstance(save_data.get("Klassen"), list):
            save_data["Klassen"] = ",".join(save_data["Klassen"])
        try:
            supabase.table('docenten').upsert(save_data).execute()
        except Exception as e:
            fouten.append(str(e))
    if fouten:
        st.error(f"Cloud opslag fout (Docenten): {fouten[0]}")

def extract_json(raw_text):
    match = re.search(r'```json(.*?)
