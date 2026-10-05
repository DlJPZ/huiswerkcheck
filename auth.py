import streamlit as st
import bcrypt
import re
import time
from copy import deepcopy
from config import supabase
from bestanden import haal_tabel_op

MAX_LOGIN_POGINGEN = 5
LOCKOUT_DUUR_SECONDEN = 300
MIN_WACHTWOORD_LENGTE = 10
MAX_BCRYPT_BYTES = 72


class AccountOverzicht(dict):
    """Bewaar originele waarden zodat alleen gewijzigde velden worden geschreven."""

    def __init__(self, waarden):
        super().__init__(waarden)
        self.origineel = deepcopy(waarden)


def _normaliseer_klassen(waarde):
    if isinstance(waarde, str):
        return [klas.strip() for klas in waarde.split(",") if klas.strip()]
    if isinstance(waarde, list):
        return [str(klas).strip() for klas in waarde if str(klas).strip()]
    return []


def _account_ophalen(tabel, sleutel, account_id):
    """Haal precies één account op; voorkom een volledige tabelscan bij login."""
    if not isinstance(account_id, str) or not account_id.strip():
        return None

    response = (
        supabase.table(tabel)
        .select("*")
        .eq(sleutel, account_id.strip())
        .limit(1)
        .execute()
    )
    rijen = response.data or []
    return rijen[0] if rijen else None


def haal_gebruiker(gebruikersnaam):
    row = _account_ophalen("gebruikers", "Gebruikersnaam", gebruikersnaam)
    if row is None:
        return None
    row.setdefault("Goedgekeurd", "Ja")
    row.setdefault("Nummer", "999")
    return row


def haal_docent(docent_id):
    row = _account_ophalen("docenten", "DocentID", docent_id)
    if row is None:
        return None
    row["Klassen"] = _normaliseer_klassen(row.get("Klassen", ""))
    row.setdefault("Goedgekeurd", "Ja")
    return row


def account_bestaat(tabel, sleutel, account_id):
    return _account_ophalen(tabel, sleutel, account_id) is not None


def maak_account(tabel, sleutel, account_id, gegevens):
    """Maak één nieuw account aan zonder eerst alle accounts te downloaden."""
    if not isinstance(account_id, str) or not account_id.strip():
        raise ValueError("Account-ID ontbreekt.")
    if not isinstance(gegevens, dict):
        raise ValueError("Ongeldige accountgegevens.")

    account_id = account_id.strip()
    payload = deepcopy(gegevens)
    payload[sleutel] = account_id

    if isinstance(payload.get("Klassen"), list):
        payload["Klassen"] = ",".join(_normaliseer_klassen(payload["Klassen"]))

    try:
        response = supabase.table(tabel).insert(payload).execute()
    except Exception as exc:
        # Database-unique constraint blijft de definitieve bescherming tegen races.
        raise RuntimeError("Account kon niet worden aangemaakt. Mogelijk is de gebruikersnaam al bezet.") from exc

    if not response.data:
        raise RuntimeError("Account is niet opgeslagen.")
    return response.data[0]


def update_account_velden(tabel, sleutel, account_id, wijzigingen):
    """Gerichte update van één account."""
    if not isinstance(wijzigingen, dict) or not wijzigingen:
        return False

    payload = deepcopy(wijzigingen)
    if isinstance(payload.get("Klassen"), list):
        payload["Klassen"] = ",".join(_normaliseer_klassen(payload["Klassen"]))

    response = (
        supabase.table(tabel)
        .update(payload)
        .eq(sleutel, account_id)
        .execute()
    )
    if not response.data:
        raise RuntimeError("Geen account bijgewerkt. Het account bestaat mogelijk niet meer.")
    return True


def bewaar_account_wijzigingen(tabel, sleutel, overzicht):
    if not isinstance(overzicht, AccountOverzicht):
        raise ValueError("Gebruik het overzicht dat door de laadfunctie is teruggegeven.")

    for account_id, gegevens in overzicht.items():
        if not isinstance(gegevens, dict):
            raise ValueError(f"Ongeldige accountgegevens voor '{account_id}'.")

        origineel = overzicht.origineel.get(account_id)
        wijzigingen = {
            k: v for k, v in gegevens.items()
            if origineel is None or origineel.get(k) != v
        }
        if not wijzigingen:
            continue

        if origineel is None:
            maak_account(tabel, sleutel, account_id, wijzigingen)
        else:
            update_account_velden(tabel, sleutel, account_id, wijzigingen)

        overzicht.origineel[account_id] = deepcopy(gegevens)


def verwijder_account(tabel, sleutel, account_id):
    if not account_id:
        st.error("Geen geldig account opgegeven.")
        st.stop()

    try:
        response = supabase.table(tabel).delete().eq(sleutel, account_id).execute()
        if not response.data:
            raise RuntimeError("Geen account verwijderd. Vernieuw het overzicht en controleer de toegang.")
    except Exception as e:
        st.error(f"Verwijderen mislukt: {e}")
        st.stop()


def hash_wachtwoord(wachtwoord):
    if not isinstance(wachtwoord, str):
        raise ValueError("Wachtwoord moet tekst zijn.")

    wachtwoord_bytes = wachtwoord.encode("utf-8")
    if len(wachtwoord_bytes) > MAX_BCRYPT_BYTES:
        raise ValueError(f"Het wachtwoord mag maximaal {MAX_BCRYPT_BYTES} UTF-8 bytes bevatten.")

    return bcrypt.hashpw(wachtwoord_bytes, bcrypt.gensalt()).decode("utf-8")


def controleer_wachtwoord(ingevoerd_wachtwoord, opgeslagen_hash):
    if not isinstance(ingevoerd_wachtwoord, str):
        return False
    if not isinstance(opgeslagen_hash, str) or not opgeslagen_hash.strip():
        return False

    try:
        return bcrypt.checkpw(
            ingevoerd_wachtwoord.encode("utf-8"),
            opgeslagen_hash.encode("utf-8")
        )
    except (ValueError, TypeError, AttributeError):
        return False


def is_sterk_wachtwoord(wachtwoord):
    if not isinstance(wachtwoord, str):
        return False, "Ongeldig wachtwoord."
    if len(wachtwoord.encode("utf-8")) > MAX_BCRYPT_BYTES:
        return False, f"Het wachtwoord mag maximaal {MAX_BCRYPT_BYTES} UTF-8 bytes bevatten."
    if len(wachtwoord) < MIN_WACHTWOORD_LENGTE:
        return False, f"Minimaal {MIN_WACHTWOORD_LENGTE} tekens lang."
    if not re.search(r"\d", wachtwoord):
        return False, "Minimaal 1 cijfer vereist."
    if not re.search(r"[^\w\s]", wachtwoord, re.UNICODE):
        return False, "Minimaal 1 speciaal teken vereist."
    return True, ""


def init_lockout_keys(prefix):
    st.session_state.setdefault(f"login_pogingen_{prefix}", 0)
    st.session_state.setdefault(f"lockout_time_{prefix}", 0.0)


def reset_login_pogingen(prefix):
    init_lockout_keys(prefix)
    st.session_state[f"login_pogingen_{prefix}"] = 0
    st.session_state[f"lockout_time_{prefix}"] = 0.0


def check_lockout(prefix):
    init_lockout_keys(prefix)
    pogingen_key = f"login_pogingen_{prefix}"
    lockout_key = f"lockout_time_{prefix}"

    if st.session_state[pogingen_key] >= MAX_LOGIN_POGINGEN:
        if time.time() < st.session_state[lockout_key]:
            resterend = max(1, int(st.session_state[lockout_key] - time.time()))
            minuten, seconden = divmod(resterend, 60)
            wachttijd = f"{minuten}:{seconden:02d} minuten" if minuten else f"{seconden} seconden"
            st.error(f"🔒 Te veel mislukte inlogpogingen. Probeer het over {wachttijd} opnieuw.")
            return True
        reset_login_pogingen(prefix)
    return False


def registreer_fout_inlog(prefix):
    init_lockout_keys(prefix)
    pogingen_key = f"login_pogingen_{prefix}"
    lockout_key = f"lockout_time_{prefix}"
    st.session_state[pogingen_key] += 1
    if st.session_state[pogingen_key] >= MAX_LOGIN_POGINGEN:
        st.session_state[lockout_key] = time.time() + LOCKOUT_DUUR_SECONDEN


def laad_gebruikers():
    """Volledig overzicht: alleen gebruiken voor docent/admin-beheer."""
    try:
        users = {}
        for row in haal_tabel_op("gebruikers", "Gebruikersnaam"):
            gebruikersnaam = row.get("Gebruikersnaam")
            if not gebruikersnaam:
                continue
            row.setdefault("Goedgekeurd", "Ja")
            row.setdefault("Nummer", "999")
            users[gebruikersnaam] = row
        return AccountOverzicht(users)
    except Exception as e:
        st.warning(f"Cloud gebruikers ophalen mislukt: {e}")
        st.stop()


def bewaar_alle_gebruikers(users_dict):
    try:
        bewaar_account_wijzigingen("gebruikers", "Gebruikersnaam", users_dict)
    except Exception as e:
        st.error(f"🚨 Supabase-fout bij opslaan gebruikers: {e}")
        st.stop()


def laad_docenten():
    """Volledig overzicht: alleen gebruiken voor admin-beheer."""
    try:
        docs = {}
        for row in haal_tabel_op("docenten", "DocentID"):
            docent_id = row.get("DocentID")
            if not docent_id:
                continue
            row["Klassen"] = _normaliseer_klassen(row.get("Klassen", ""))
            row.setdefault("Goedgekeurd", "Ja")
            docs[docent_id] = row
        return AccountOverzicht(docs)
    except Exception as e:
        st.warning(f"Cloud docenten ophalen mislukt: {e}")
        st.stop()


def bewaar_alle_docenten(docs_dict):
    try:
        bewaar_account_wijzigingen("docenten", "DocentID", docs_dict)
    except Exception as e:
        st.error(f"Cloud opslag fout (Docenten): {e}")
        st.stop()
