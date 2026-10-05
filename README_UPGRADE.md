# Upgrade 3.2.2

Deze versie start overal via `main.py`.

## Opstartreparatie 3.2.2
- De Codespaces-startconfiguratie verwijst nu naar het bestaande `main.py`, in plaats van het verwijderde `huiswerkchecker.py`.
- Het importeren van `config.py` start geen API-clients meer. Het inlogscherm werkt daardoor ook wanneer secrets nog niet zijn ingesteld.
- Gemini en Supabase worden onafhankelijk en pas bij gebruik aangemaakt. Ontbrekende of ongeldige instellingen geven een duidelijke melding bij de functie die ze nodig heeft.
- Clients worden hergebruikt via Streamlit's resource-cache.
- De minigame gebruikt de huidige `st.iframe` API.

Start lokaal met `streamlit run main.py`. Voeg voor database- en AI-functies `SUPABASE_URL`, `SUPABASE_KEY` en `GEMINI_API_KEY` toe aan `.streamlit/secrets.toml` of aan Streamlit Cloud Secrets. Commit dit secrets-bestand niet.

Na het bijwerken van een bestaande Codespace: herbouw de container zodat de gewijzigde startconfiguratie wordt toegepast, of voer `streamlit run main.py` uit in de terminal.

## Na deployment
Voer in Supabase SQL Editor opnieuw uit:
1. `supabase_storingen.sql` — voegt `ZichtbaarVoorLeerlingen` toe, borgt de bevestigingstabel en de private bijlagenbucket.
2. `supabase_security.sql` — alleen nodig als de server-side login-lockouttabel nog niet bestaat.

De SQL in `supabase_storingen.sql` is zo geschreven dat hij opnieuw kan worden uitgevoerd.

## Adminwachtwoord
Voer lokaal `python maak_admin_hash.py` uit en zet de getoonde regel in Streamlit Secrets als `ADMIN_WACHTWOORD_HASH`.
Daarna kan de oude `ADMIN_WACHTWOORD` secret worden verwijderd.

## Beveiliging
De app verwacht RLS op `gebruikers`, `docenten`, `resultaten`, `storingen`, `storing_bevestigingen` en `login_lockouts`. De Streamlit-server gebruikt uitsluitend de `sb_secret_...` sleutel.

## Belangrijkste wijzigingen in 3.2.1
- Codespaces en Streamlit starten via `main.py`.
- Geen automatische A-keuze meer bij meerkeuzevragen; alle antwoorden moeten ingevuld zijn.
- Inlogproblemen via "wachtwoord vergeten" zijn privé voor de beheerder.
- De oorspronkelijke storingsmelder kan dezelfde storing niet nogmaals meetellen.
- Docenten halen alleen leerlingen van hun eigen klassen op, zonder wachtwoordhashes.
- Docenten kunnen alleen lesmateriaal beheren voor hun toegewezen leerjaren.
- Server-side lockoutrecords worden alleen voor bestaande leerling-/docentaccounts aangemaakt; admin wordt niet server-side geblokkeerd.
- Resultaattijden worden expliciet in `Europe/Amsterdam` opgeslagen.
