"""Écriture/lecture des verdicts VIES en base (partagé par la campagne et l'API)."""

from __future__ import annotations

import psycopg

from .vies_client import INDETERMINE, ReponseVies

JOURNALISER = """
INSERT INTO appel_vies (numero_normalise, origine, campagne_id, http_status, user_error, statut, latence_ms, erreur)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
"""

# Un résultat INDETERMINE met à jour le statut courant mais ne touche pas aux
# colonnes « dernier verdict définitif » : une panne n'efface pas ce qu'on savait.
UPSERT = """
INSERT INTO verification_vies AS v (
    numero_normalise, pays, statut, user_error, is_valid_vies, nom, adresse,
    date_requete_vies, verifie_le, derniere_reponse_definitive_le, dernier_statut_definitif,
    nb_tentatives, campagne_id)
VALUES (%(numero)s, %(pays)s, %(statut)s, %(user_error)s, %(is_valid)s, %(nom)s, %(adresse)s,
        %(date_requete_vies)s, now(),
        CASE WHEN %(definitif)s THEN now() END,
        CASE WHEN %(definitif)s THEN %(statut)s END,
        1, %(campagne_id)s)
ON CONFLICT (numero_normalise) DO UPDATE SET
    statut = EXCLUDED.statut,
    user_error = EXCLUDED.user_error,
    is_valid_vies = EXCLUDED.is_valid_vies,
    nom = COALESCE(EXCLUDED.nom, v.nom),
    adresse = COALESCE(EXCLUDED.adresse, v.adresse),
    date_requete_vies = COALESCE(EXCLUDED.date_requete_vies, v.date_requete_vies),
    verifie_le = now(),
    derniere_reponse_definitive_le = COALESCE(EXCLUDED.derniere_reponse_definitive_le, v.derniere_reponse_definitive_le),
    dernier_statut_definitif = COALESCE(EXCLUDED.dernier_statut_definitif, v.dernier_statut_definitif),
    nb_tentatives = v.nb_tentatives + 1,
    campagne_id = COALESCE(EXCLUDED.campagne_id, v.campagne_id)
"""


def enregistrer(conn: psycopg.Connection, rep: ReponseVies, origine: str,
                campagne_id: int | None = None) -> None:
    """Journalise l'appel ET met à jour le dernier état connu, dans la même transaction."""
    conn.execute(JOURNALISER, (rep.numero, origine, campagne_id, rep.http_status, rep.user_error,
                               rep.statut, rep.latence_ms, rep.erreur))
    conn.execute(UPSERT, {
        "numero": rep.numero, "pays": rep.numero[:2], "statut": rep.statut,
        "user_error": rep.user_error, "is_valid": rep.is_valid, "nom": rep.nom,
        "adresse": rep.adresse, "date_requete_vies": rep.date_requete_vies,
        "definitif": rep.statut != INDETERMINE, "campagne_id": campagne_id,
    })
    conn.commit()


def lire(conn: psycopg.Connection, numero: str) -> dict | None:
    return conn.execute(
        "SELECT *, now() AS maintenant FROM verification_vies WHERE numero_normalise = %s", (numero,)
    ).fetchone()
