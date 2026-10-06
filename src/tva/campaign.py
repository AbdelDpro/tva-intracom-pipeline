"""Campagne de vérification VIES du référentiel.

Propriétés :
  - ne vise que les numéros structurellement valides, DÉDOUBLONNÉS (un appel par numéro normalisé) ;
  - saute les numéros ayant déjà une réponse définitive récente (< TTL_CAMPAGNE_J) -> reprise ;
  - temporise entre deux appels (VIES_DELAI_S) ;
  - commit après CHAQUE numéro : une interruption (Ctrl+C, crash) ne perd rien ;
  - mode échantillon (--echantillon N) avec un tirage stable, pour qu'une relance
    reprenne le même échantillon au lieu d'en tirer un autre ;
  - coupe-circuit par pays : si un État renvoie MS_UNAVAILABLE plusieurs fois de suite,
    ses numéros restants sont laissés pour une prochaine passe au lieu de marteler VIES.
"""

from __future__ import annotations

import logging
import time
from collections import Counter, defaultdict

from . import config, db, repository
from .vies_client import ClientVies

log = logging.getLogger(__name__)

SEUIL_COUPE_CIRCUIT = 3

# Tirage stable : l'ordre par md5 mélange les pays sans dépendre d'un random.
CIBLES = """
SELECT DISTINCT l.numero_normalise, md5(l.numero_normalise) AS ordre
FROM ligne_source l
LEFT JOIN verification_vies v ON v.numero_normalise = l.numero_normalise
WHERE l.verdict_structurel = 'VALIDE'
  AND NOT (v.derniere_reponse_definitive_le IS NOT NULL
           AND v.derniere_reponse_definitive_le > now() - make_interval(days => %(ttl)s))
ORDER BY ordre
"""

# En mode échantillon, l'échantillon est fixé une fois pour toutes (les N premiers
# numéros dans l'ordre md5) ; on ne traite que ceux qui n'ont pas encore de réponse.
CIBLES_ECHANTILLON = """
WITH echantillon AS (
    SELECT DISTINCT numero_normalise, md5(numero_normalise) AS ordre
    FROM ligne_source WHERE verdict_structurel = 'VALIDE'
    ORDER BY ordre LIMIT %(n)s
)
SELECT e.numero_normalise
FROM echantillon e
LEFT JOIN verification_vies v ON v.numero_normalise = e.numero_normalise
WHERE NOT (v.derniere_reponse_definitive_le IS NOT NULL
           AND v.derniere_reponse_definitive_le > now() - make_interval(days => %(ttl)s))
ORDER BY e.ordre
"""


def executer(echantillon: int | None = None, client: ClientVies | None = None,
             delai_s: float | None = None) -> dict:
    delai_s = config.VIES_DELAI_S if delai_s is None else delai_s
    mode = "echantillon" if echantillon else "complet"
    client = client or ClientVies()
    stats: Counter = Counter()
    echecs_consecutifs: defaultdict[str, int] = defaultdict(int)
    pays_coupes: set[str] = set()

    with db.connecter() as conn:
        db.initialiser_schema(conn)
        if echantillon:
            cibles = [r["numero_normalise"] for r in conn.execute(
                CIBLES_ECHANTILLON, {"n": echantillon, "ttl": config.TTL_CAMPAGNE_J})]
        else:
            cibles = [r["numero_normalise"] for r in conn.execute(CIBLES, {"ttl": config.TTL_CAMPAGNE_J})]

        campagne_id = conn.execute(
            "INSERT INTO campagne (mode, taille_demandee, nb_cibles) VALUES (%s, %s, %s) RETURNING id",
            (mode, echantillon, len(cibles))).fetchone()["id"]
        conn.commit()
        log.info("Campagne #%d (%s) : %d numéros à interroger (déjà tranchés et récents ignorés)",
                 campagne_id, mode, len(cibles))
        if cibles:
            log.info("Durée estimée : ~%.0f s (temporisation %.1f s/appel + latence)",
                     len(cibles) * (delai_s + 0.5), delai_s)

        statut_final = "TERMINEE"
        try:
            for i, numero in enumerate(cibles, 1):
                pays = numero[:2]
                if pays in pays_coupes:
                    stats["saute_coupe_circuit"] += 1
                    continue

                rep = client.verifier(numero)
                repository.enregistrer(conn, rep, "campagne", campagne_id)
                stats[rep.statut] += 1
                conn.execute("UPDATE campagne SET nb_traites = nb_traites + 1 WHERE id = %s", (campagne_id,))
                conn.commit()
                log.info("[%d/%d] %s -> %s (%s, %s ms)", i, len(cibles), numero, rep.statut,
                         rep.user_error, rep.latence_ms)

                if rep.user_error == "MS_UNAVAILABLE":
                    echecs_consecutifs[pays] += 1
                    if echecs_consecutifs[pays] >= SEUIL_COUPE_CIRCUIT:
                        pays_coupes.add(pays)
                        log.warning("Coupe-circuit : %s indisponible %d fois de suite, numéros restants reportés",
                                    pays, SEUIL_COUPE_CIRCUIT)
                else:
                    echecs_consecutifs[pays] = 0

                if i < len(cibles):
                    time.sleep(delai_s)
        except KeyboardInterrupt:
            statut_final = "INTERROMPUE"
            log.warning("Campagne #%d interrompue : les %d réponses déjà obtenues sont en base, "
                        "relancer la même commande reprendra là où elle s'est arrêtée.",
                        campagne_id, sum(stats[s] for s in ("VALIDE", "INVALIDE", "INDETERMINE")))
        finally:
            conn.execute("UPDATE campagne SET terminee_le = now(), statut = %s WHERE id = %s",
                         (statut_final, campagne_id))
            conn.commit()

    log.info("Campagne #%d %s : %s", campagne_id, statut_final.lower(), dict(stats))
    return {"campagne_id": campagne_id, "statut": statut_final, "cibles": len(cibles), **stats}


def mesurer(n: int = 5, client: ClientVies | None = None, delai_s: float = 1.0) -> dict:
    """Mesure la latence de VIES sur n numéros réels du référentiel et projette le coût total."""
    client = client or ClientVies(max_tentatives=1)
    with db.connecter() as conn:
        numeros = [r["numero_normalise"] for r in conn.execute(
            "SELECT DISTINCT numero_normalise FROM ligne_source WHERE verdict_structurel='VALIDE' "
            "ORDER BY numero_normalise LIMIT %s", (n,))]
        nb_lignes = conn.execute("SELECT count(*) AS n FROM ligne_source").fetchone()["n"]
        nb_uniques = conn.execute(
            "SELECT count(DISTINCT numero_normalise) AS n FROM ligne_source WHERE verdict_structurel='VALIDE'"
        ).fetchone()["n"]

    latences = []
    for numero in numeros:
        rep = client.verifier(numero)
        latences.append(rep.latence_ms or 0)
        log.info("%s -> %s / %s en %s ms", numero, rep.statut, rep.user_error, rep.latence_ms)
        time.sleep(delai_s)

    moy_s = sum(latences) / len(latences) / 1000 if latences else 0
    res = {
        "latence_moyenne_s": round(moy_s, 3),
        "latence_max_s": round(max(latences) / 1000, 3) if latences else 0,
        "naif_lignes": nb_lignes,
        "naif_duree_h": round(nb_lignes * (moy_s + delai_s) / 3600, 2),
        "reduit_appels": nb_uniques,
        "reduit_duree_h": round(nb_uniques * (moy_s + delai_s) / 3600, 2),
    }
    log.info("Mesure : %s", res)
    return res
