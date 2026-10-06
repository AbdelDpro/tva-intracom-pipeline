"""Chargement du référentiel CSV dans PostgreSQL, avec verdict structurel.

Rechargement idempotent : la clé est l'``id`` du fichier (INSERT ... ON CONFLICT DO UPDATE),
un second chargement met à jour les lignes au lieu de les dupliquer.
"""

import csv
import logging
from datetime import date
from pathlib import Path

from . import config, db
from .structural import valider

log = logging.getLogger(__name__)

UPSERT = """
INSERT INTO ligne_source (
    id_source, raison_sociale, pays_declare, numero_brut, date_saisie, source_saisie,
    pays_normalise, numero_normalise, corrections, verdict_structurel, motif_structurel, charge_le)
VALUES (%(id_source)s, %(raison_sociale)s, %(pays_declare)s, %(numero_brut)s, %(date_saisie)s,
        %(source_saisie)s, %(pays_normalise)s, %(numero_normalise)s, %(corrections)s,
        %(verdict_structurel)s, %(motif_structurel)s, now())
ON CONFLICT (id_source) DO UPDATE SET
    raison_sociale = EXCLUDED.raison_sociale,
    pays_declare = EXCLUDED.pays_declare,
    numero_brut = EXCLUDED.numero_brut,
    date_saisie = EXCLUDED.date_saisie,
    source_saisie = EXCLUDED.source_saisie,
    pays_normalise = EXCLUDED.pays_normalise,
    numero_normalise = EXCLUDED.numero_normalise,
    corrections = EXCLUDED.corrections,
    verdict_structurel = EXCLUDED.verdict_structurel,
    motif_structurel = EXCLUDED.motif_structurel,
    charge_le = now()
"""


def _date(valeur: str) -> date | None:
    try:
        return date.fromisoformat(valeur.strip())
    except (ValueError, AttributeError):
        return None


def lire_csv(chemin: Path) -> list[dict]:
    """Lit le CSV et calcule le verdict structurel de chaque ligne.

    Le CSV est lu en texte brut (aucune conversion automatique), pour ne pas perdre
    les zéros de tête ni transformer 'null' / 'N/A' en valeurs manquantes à notre insu.
    """
    lignes = []
    with chemin.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            r = valider(row["numero_tva"], row["pays_declare"])
            lignes.append({
                "id_source": int(row["id"]),
                "raison_sociale": row["raison_sociale"],
                "pays_declare": row["pays_declare"],
                "numero_brut": row["numero_tva"],
                "date_saisie": _date(row["date_saisie"]),
                "source_saisie": row["source_saisie"],
                "pays_normalise": r.pays,
                "numero_normalise": r.normalise,
                "corrections": r.corrections,
                "verdict_structurel": r.verdict.value,
                "motif_structurel": r.motif.value,
            })
    return lignes


def charger(chemin: Path | None = None) -> int:
    chemin = chemin or config.FICHIER_SOURCE
    lignes = lire_csv(chemin)
    with db.connecter() as conn:
        db.initialiser_schema(conn)
        with conn.cursor() as cur:
            cur.executemany(UPSERT, lignes)
        conn.commit()
        total = conn.execute("SELECT count(*) AS n FROM ligne_source").fetchone()["n"]
    log.info("%d lignes lues dans %s ; %d lignes en base", len(lignes), chemin.name, total)
    return len(lignes)
