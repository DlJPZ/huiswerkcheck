# Upgrade 3.2.0

Voer na deployment eenmalig in Supabase SQL Editor uit:
1. `supabase_storingen.sql` — voegt de teller en bevestigingen voor storingen toe en borgt de private bijlagenbucket.
2. `supabase_security.sql` — voegt server-side account-lockout toe.

## Adminwachtwoord
Voer lokaal `python maak_admin_hash.py` uit en zet de getoonde regel in Streamlit Secrets als `ADMIN_WACHTWOORD_HASH`.
Daarna kan de oude `ADMIN_WACHTWOORD` secret worden verwijderd. De code ondersteunt die oude secret tijdelijk voor een soepele migratie.

## Bestaande beveiliging
De app verwacht dat RLS aan staat op `gebruikers`, `docenten`, `resultaten`, `storingen`, `storing_bevestigingen` en `login_lockouts` en dat de Streamlit-server uitsluitend de `sb_secret_...` sleutel gebruikt.
