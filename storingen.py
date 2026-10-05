import datetime
import mimetypes
import re
import uuid
from pathlib import PurePath

import pandas as pd
from config import supabase

STORINGEN_BUCKET = "storingsbijlagen"
MAX_BIJLAGE_BYTES = 8 * 1024 * 1024
TOEGESTAAN_EXTENSIES = {".png", ".jpg", ".jpeg", ".webp", ".pdf"}
TOEGESTANE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "application/pdf",
}
STATUSSEN = ("in behandeling", "opgelost")


def _veilige_bestandsnaam(bestandsnaam):
    naam = PurePath(bestandsnaam or "bijlage").name
    stam = re.sub(r"[^A-Za-z0-9._-]+", "_", naam).strip("._")
    return stam[:120] or "bijlage"


def _mime_type(uploaded_file):
    mime = getattr(uploaded_file, "type", None)
    if mime:
        return mime.lower()
    guessed, _ = mimetypes.guess_type(getattr(uploaded_file, "name", ""))
    return (guessed or "application/octet-stream").lower()


def valideer_bijlage(uploaded_file):
    if uploaded_file is None:
        return
    naam = _veilige_bestandsnaam(uploaded_file.name)
    extensie = PurePath(naam).suffix.lower()
    if extensie not in TOEGESTAAN_EXTENSIES:
        raise ValueError("Bijlagen moeten PNG, JPG, WEBP of PDF zijn.")
    inhoud = uploaded_file.getvalue()
    if len(inhoud) > MAX_BIJLAGE_BYTES:
        raise ValueError("De bijlage mag maximaal 8 MB groot zijn.")
    mime = _mime_type(uploaded_file)
    if mime not in TOEGESTANE_MIME_TYPES:
        raise ValueError("Dit bestandstype is niet toegestaan.")


def haal_storingen(status=None):
    query = supabase.table("storingen").select("*")
    if status in STATUSSEN:
        query = query.eq("Status", status)
    data = query.order("Aangemaakt", desc=True).execute().data or []
    return pd.DataFrame(data)


def maak_storing(titel, omschrijving, categorie, voornaam, gebruikersnaam, cluster, uploaded_file=None):
    titel = (titel or "").strip()
    omschrijving = (omschrijving or "").strip()
    categorie = (categorie or "Overig").strip()
    if len(titel) < 5:
        raise ValueError("Geef een duidelijke titel van minimaal 5 tekens.")
    if len(omschrijving) < 10:
        raise ValueError("Beschrijf de storing in minimaal 10 tekens.")

    storing_id = str(uuid.uuid4())
    bijlage_pad = None

    if uploaded_file is not None:
        valideer_bijlage(uploaded_file)
        veilige_naam = _veilige_bestandsnaam(uploaded_file.name)
        bijlage_pad = f"{storing_id}/{veilige_naam}"
        supabase.storage.from_(STORINGEN_BUCKET).upload(
            path=bijlage_pad,
            file=uploaded_file.getvalue(),
            file_options={
                "content-type": _mime_type(uploaded_file),
                "upsert": "false",
            },
        )

    data = {
        "StoringID": storing_id,
        "Status": "in behandeling",
        "Titel": titel[:160],
        "Omschrijving": omschrijving[:4000],
        "Categorie": categorie[:80],
        "Gebruikersnaam": (gebruikersnaam or "")[:160],
        "Voornaam": (voornaam or "")[:160],
        "Cluster": (cluster or "")[:80],
        "BijlagePad": bijlage_pad,
        "AdminNotitie": "",
    }

    try:
        response = supabase.table("storingen").insert(data).execute()
        if not response.data:
            raise RuntimeError("Supabase bevestigde de storingsmelding niet.")
    except Exception:
        if bijlage_pad:
            try:
                supabase.storage.from_(STORINGEN_BUCKET).remove([bijlage_pad])
            except Exception:
                pass
        raise

    return storing_id


def download_bijlage(pad):
    if not pad:
        return None
    return supabase.storage.from_(STORINGEN_BUCKET).download(pad)


def werk_storing_bij(storing_id, status, admin_notitie=""):
    if status not in STATUSSEN:
        raise ValueError("Ongeldige storingsstatus.")
    wijzigingen = {
        "Status": status,
        "AdminNotitie": (admin_notitie or "")[:4000],
        "OpgelostOp": (
            datetime.datetime.now(datetime.timezone.utc).isoformat()
            if status == "opgelost"
            else None
        ),
    }
    response = (
        supabase.table("storingen")
        .update(wijzigingen)
        .eq("StoringID", storing_id)
        .execute()
    )
    if not response.data:
        raise RuntimeError("De storing kon niet worden bijgewerkt.")
    return True
