import streamlit as st
import bcrypt
import re
import time
from config import supabase

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
