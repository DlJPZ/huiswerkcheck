import streamlit as st
import pandas as pd
import docx
import io
import uuid
import datetime
from zoneinfo import ZoneInfo
from config import supabase, LEERJAREN_CLUSTERS, HOOFDSTUKKEN
from docx.text.paragraph import Paragraph
from docx.table import Table

PAGE_SIZE = 500


def get_leerjaar(cluster_naam):
    return next((jaar for jaar, klassen in LEERJAREN_CLUSTERS.items()
                 if cluster_naam in klassen), None)


def haal_tabel_op(tabel, sleutel):
    """Lees alle pagina's. Alleen bedoeld voor beheerfuncties die echt alles nodig hebben."""
    rijen = []
    while True:
        pagina = (
            supabase.table(tabel)
            .select("*")
            .order(sleutel)
            .range(len(rijen), len(rijen) + PAGE_SIZE - 1)
            .execute()
        ).data or []
        if not pagina:
            return rijen
        rijen.extend(pagina)


def _haal_resultaten_gefilterd(gebruikersnaam=None, cluster=None):
    """Haal alle passende resultaten op, ook als de API per request minder rijen teruggeeft."""
    rijen = []
    while True:
        query = supabase.table("resultaten").select("*")
        if gebruikersnaam is not None:
            query = query.eq("Gebruikersnaam", gebruikersnaam)
        if cluster is not None:
            query = query.eq("Cluster", cluster)
        pagina = (
            query.order("Tijdstip", desc=True)
            .range(len(rijen), len(rijen) + PAGE_SIZE - 1)
            .execute()
        ).data or []
        if not pagina:
            return pd.DataFrame(rijen)
        rijen.extend(pagina)


def haal_resultaten_leerling(gebruikersnaam):
    """Haal uitsluitend resultaten van één leerling op."""
    try:
        return _haal_resultaten_gefilterd(gebruikersnaam=gebruikersnaam)
    except Exception:
        st.error("Resultaten konden niet worden opgehaald. Probeer het later opnieuw.")
        st.stop()


def haal_resultaten_klas(cluster):
    """Haal uitsluitend resultaten uit één klas op."""
    try:
        return _haal_resultaten_gefilterd(cluster=cluster)
    except Exception:
        st.error("Klasresultaten konden niet worden opgehaald. Probeer het later opnieuw.")
        st.stop()

def haal_alle_resultaten_op():
    """Alle resultaten; behouden voor beheer/migraties. Gebruik elders liever gefilterde functies."""
    try:
        return pd.DataFrame(haal_tabel_op("resultaten", "PogingID"))
    except Exception as e:
        st.error("Resultaten konden niet worden opgehaald. Probeer het later opnieuw.")
        st.stop()


def les_id(leerjaar, hoofdstuk, bestandsnaam):
    return f"{leerjaar}/{hoofdstuk}/{bestandsnaam}"


def les_resultaat_mask(lessen, leerjaar, hoofdstuk, bestandsnaam):
    """Oude resultaten tellen alleen mee als hun bestandsnaam eenduidig is."""
    mask = lessen.eq(les_id(leerjaar, hoofdstuk, bestandsnaam))
    if lessen.eq(bestandsnaam).any():
        hoofdstukken = [
            hst for hst in HOOFDSTUKKEN[leerjaar]
            if bestandsnaam in haal_bestanden_op(leerjaar, hst)
        ]
        if hoofdstukken == [hoofdstuk]:
            mask |= lessen.eq(bestandsnaam)
        else:
            st.warning(
                "Oude resultaten met deze bestandsnaam zijn niet eenduidig aan een hoofdstuk te koppelen. "
                "Ze blijven zichtbaar in de geschiedenis, maar tellen hier niet mee."
            )
    return mask


def haal_bestanden_op(leerjaar, hoofdstuk):
    try:
        pad = f"{leerjaar}/{hoofdstuk}"
        bestanden = []
        while True:
            pagina = supabase.storage.from_("lesmateriaal").list(
                pad,
                {
                    "limit": 100,
                    "offset": len(bestanden),
                    "sortBy": {"column": "name", "order": "asc"},
                },
            )
            if not pagina:
                break
            bestanden.extend(pagina)
            if len(pagina) < 100:
                break
        return [b["name"] for b in bestanden if b["name"].lower().endswith(".docx")]
    except Exception as e:
        st.error("Lesmateriaal kon niet worden opgehaald. Probeer het later opnieuw.")
        st.stop()


def lees_document_blokken(container):
    """Behoud de volgorde van alinea's en (ook geneste) tabellen."""
    element = container.element.body if hasattr(container, "element") else container._tc
    for kind in element.iterchildren():
        if kind.tag.endswith("}p"):
            yield Paragraph(kind, container).text
        elif kind.tag.endswith("}tbl"):
            for rij in Table(kind, container).rows:
                gezien = set()
                for cel in rij.cells:
                    if cel._tc not in gezien:
                        gezien.add(cel._tc)
                        yield from lees_document_blokken(cel)


def lees_docx(leerjaar, hoofdstuk, bestandsnaam):
    try:
        pad = f"{leerjaar}/{hoofdstuk}/{bestandsnaam}"
        response = supabase.storage.from_("lesmateriaal").download(pad)
        doc = docx.Document(io.BytesIO(response))
        return "\n".join(lees_document_blokken(doc))
    except Exception as e:
        st.error("Het lesbestand kon niet worden gelezen.")
        return ""


def markeer_reactie_gelezen(poging_id, gebruikersnaam):
    """Leerling mag via de app alleen zijn eigen resultaat als gelezen markeren."""
    response = (
        supabase.table("resultaten")
        .update({"ReactieGelezen": "True"})
        .eq("PogingID", poging_id)
        .eq("Gebruikersnaam", gebruikersnaam)
        .execute()
    )
    return bool(response.data)


def sla_docentreactie_op(poging_id, gebruikersnaam, cluster, reactie):
    """Extra server-side beperkingen naast de selectie in de UI."""
    response = (
        supabase.table("resultaten")
        .update({"DocentReactie": reactie, "ReactieGelezen": "False"})
        .eq("PogingID", poging_id)
        .eq("Gebruikersnaam", gebruikersnaam)
        .eq("Cluster", cluster)
        .execute()
    )
    return bool(response.data)


def sla_resultaat_op(niveau, cluster, nummer, voornaam, gebruikersnaam,
                     gekozen_les, cijfer, beoordeling, boek_dicht):
    tijdstip = datetime.datetime.now(ZoneInfo("Europe/Amsterdam")).strftime("%Y-%m-%d %H:%M")
    poging_id = str(uuid.uuid4())

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
        "BoekDicht": boek_dicht,
    }
    try:
        response = supabase.table("resultaten").insert(data).execute()
        if not response.data:
            return False, "Supabase bevestigde de opslag niet."
        return True, ""
    except Exception:
        return False, "opslagfout"
