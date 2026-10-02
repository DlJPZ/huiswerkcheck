import streamlit as st
import pandas as pd
import docx
import io
import uuid
import datetime
from config import supabase, LEERJAREN_CLUSTERS, HOOFDSTUKKEN
from docx.text.paragraph import Paragraph
from docx.table import Table


def get_leerjaar(cluster_naam):
    return next((jaar for jaar, klassen in LEERJAREN_CLUSTERS.items()
                 if cluster_naam in klassen), None)


def haal_tabel_op(tabel, sleutel):
    """Lees alle pagina's, ook bij een lagere serverlimiet dan de paginagrootte."""
    rijen = []
    while True:
        pagina = (supabase.table(tabel).select("*").order(sleutel)
                  .range(len(rijen), len(rijen) + 499).execute()).data
        if not pagina:
            return rijen
        rijen.extend(pagina)


def les_id(leerjaar, hoofdstuk, bestandsnaam):
    return f"{leerjaar}/{hoofdstuk}/{bestandsnaam}"


def les_resultaat_mask(lessen, leerjaar, hoofdstuk, bestandsnaam):
    """Oude resultaten tellen alleen mee als hun bestandsnaam eenduidig is."""
    mask = lessen.eq(les_id(leerjaar, hoofdstuk, bestandsnaam))
    if lessen.eq(bestandsnaam).any():
        hoofdstukken = [hst for hst in HOOFDSTUKKEN[leerjaar]
                       if bestandsnaam in haal_bestanden_op(leerjaar, hst)]
        if hoofdstukken == [hoofdstuk]:
            mask |= lessen.eq(bestandsnaam)
        else:
            st.warning("Oude resultaten met deze bestandsnaam zijn niet eenduidig aan een hoofdstuk te koppelen. Ze blijven zichtbaar in de geschiedenis, maar tellen hier niet mee.")
    return mask

def haal_bestanden_op(leerjaar, hoofdstuk):
    try:
        pad = f"{leerjaar}/{hoofdstuk}"
        bestanden = []
        while True:
            pagina = supabase.storage.from_("lesmateriaal").list(
                pad, {"limit": 100, "offset": len(bestanden),
                      "sortBy": {"column": "name", "order": "asc"}})
            if not pagina:
                break
            bestanden.extend(pagina)
        return [b["name"] for b in bestanden if b["name"].lower().endswith('.docx')]
    except Exception as e:
        st.error(f"Lesmateriaal ophalen mislukt: {e}")
        st.stop()


def lees_document_blokken(container):
    """Behoud de volgorde van alinea's en (ook geneste) tabellen."""
    element = container.element.body if hasattr(container, "element") else container._tc
    for kind in element.iterchildren():
        if kind.tag.endswith('}p'):
            yield Paragraph(kind, container).text
        elif kind.tag.endswith('}tbl'):
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
        st.error(f"Fout bij lezen uit Supabase: {e}")
        return ""

def haal_alle_resultaten_op():
    try:
        return pd.DataFrame(haal_tabel_op("resultaten", "PogingID"))
    except Exception as e:
        st.error(f"Fout bij ophalen resultaten: {e}")
        st.stop()

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
