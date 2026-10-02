import streamlit as st
import bcrypt
import re
import time
from copy import deepcopy
from config import supabase
from bestanden import haal_tabel_op


class AccountOverzicht(dict):
    """Bewaar de gelezen waarden om uitsluitend gewijzigde velden te schrijven."""
    def __init__(self, waarden):
        super().__init__(waarden)
        self.origineel = deepcopy(waarden)


def bewaar_account_wijzigingen(tabel, sleutel, overzicht):
    if not isinstance(overzicht, AccountOverzicht):
        raise ValueError("Gebruik het overzicht dat door de laadfunctie is teruggegeven.")
    for account_id, gegevens in overzicht.items():
        origineel = overzicht.origineel.get(account_id)
        wijzigingen = {k: v for k, v in gegevens.items()
                       if origineel is None or origineel.get(k) != v}
        if not wijzigingen:
            continue
        if isinstance(wijzigingen.get("Klassen"), list):
            wijzigingen["Klassen"] = ",".join(wijzigingen["Klassen"])
        if origineel is None:
            # Een gelijktijdige registratie mag nooit een bestaand account vervangen.
            response = supabase.table(tabel).insert(wijzigingen).execute()
        else:
            response = (supabase.table(tabel).update(wijzigingen)
                        .eq(sleutel, account_id).execute())
        if not response.data:
            raise RuntimeError("Geen account opgeslagen. Het account is mogelijk verwijderd of toegang is geweigerd.")
        overzicht.origineel[account_id] = deepcopy(gegevens)


def verwijder_account(tabel, sleutel, account_id):
    try:
        response = supabase.table(tabel).delete().eq(sleutel, account_id).execute()
        if not response.data:
            raise RuntimeError("Geen account verwijderd. Vernieuw het overzicht en controleer de toegang.")
    except Exception as e:
        st.error(f"Verwijderen mislukt: {e}")
        st.stop()

def hash_wachtwoord(wachtwoord):
    return bcrypt.hashpw(wachtwoord.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def controleer_wachtwoord(ingevoerd_wachtwoord, opgeslagen_hash):
    try:
        return bcrypt.checkpw(ingevoerd_wachtwoord.encode('utf-8'), opgeslagen_hash.encode('utf-8'))
    except ValueError:
        return False 

def is_sterk_wachtwoord(wachtwoord):
    if len(wachtwoord.encode('utf-8')) > 72: return False, "Het wachtwoord mag maximaal 72 UTF-8 bytes bevatten."
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
        users = {}
        for row in haal_tabel_op('gebruikers', 'Gebruikersnaam'):
            if "Goedgekeurd" not in row: row["Goedgekeurd"] = "Ja"
            if "Nummer" not in row: row["Nummer"] = "999"
            users[row["Gebruikersnaam"]] = row
        return AccountOverzicht(users)
    except Exception as e:
        st.warning(f"Cloud gebruikers ophalen mislukt: {e}")
        st.stop()

def bewaar_alle_gebruikers(users_dict):
    try:
        bewaar_account_wijzigingen('gebruikers', 'Gebruikersnaam', users_dict)
    except Exception as e:
        st.error(f"🚨 Supabase Fout bij opslaan gebruikers: {e}")
        st.stop()

def laad_docenten():
    try:
        docs = {}
        for row in haal_tabel_op('docenten', 'DocentID'):
            k = row.get("Klassen", "")
            if isinstance(k, str):
                row["Klassen"] = k.split(",") if k else []
            elif isinstance(k, list):
                row["Klassen"] = k
            else:
                row["Klassen"] = []
                
            if "Goedgekeurd" not in row: row["Goedgekeurd"] = "Ja"
            docs[row["DocentID"]] = row
        return AccountOverzicht(docs)
    except Exception as e:
        st.warning(f"Cloud docenten ophalen mislukt: {e}")
        st.stop()

def bewaar_alle_docenten(docs_dict):
    try:
        bewaar_account_wijzigingen('docenten', 'DocentID', docs_dict)
    except Exception as e:
        st.error(f"Cloud opslag fout (Docenten): {e}")
        st.stop()
