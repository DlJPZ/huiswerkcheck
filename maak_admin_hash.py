"""Lokaal hulpmiddel: voer uit met `python maak_admin_hash.py` en zet de uitvoer in Streamlit Secrets."""
import getpass
import bcrypt

wachtwoord = getpass.getpass("Nieuw adminwachtwoord: ")
bevestiging = getpass.getpass("Herhaal adminwachtwoord: ")
if wachtwoord != bevestiging:
    raise SystemExit("Wachtwoorden komen niet overeen.")
if len(wachtwoord) < 10:
    raise SystemExit("Gebruik minimaal 10 tekens.")
print("ADMIN_WACHTWOORD_HASH = \"" + bcrypt.hashpw(wachtwoord.encode(), bcrypt.gensalt()).decode() + "\"")
