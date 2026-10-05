# Upgrade 3.2.1

Deze versie start overal via `main.py`.

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
