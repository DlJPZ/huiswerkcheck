import streamlit as st
import pandas as pd
import docx
import io
import uuid
import datetime
from config import supabase

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
