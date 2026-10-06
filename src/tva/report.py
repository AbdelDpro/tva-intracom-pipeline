"""Génération du rapport de réconciliation (Markdown) à partir de la base.

Commande : python -m tva.cli rapport   -> docs/rapport_reconciliation.md
Le rapport ne contient que des chiffres calculés en SQL : il est reproductible.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from . import config, db

log = logging.getLogger(__name__)


def _table(lignes: list[dict], colonnes: list[str], entetes: list[str] | None = None) -> str:
    entetes = entetes or colonnes
    out = ["| " + " | ".join(entetes) + " |", "|" + "---|" * len(entetes)]
    for r in lignes:
        out.append("| " + " | ".join("" if r[c] is None else str(r[c]) for c in colonnes) + " |")
    return "\n".join(out)


def _pct(n: int, total: int) -> str:
    return f"{100 * n / total:.1f} %" if total else "-"


def generer(sortie: Path | None = None) -> Path:
    sortie = sortie or config.RAPPORT_SORTIE
    with db.connecter() as conn:
        q = lambda sql, *a: conn.execute(sql, a).fetchall()
        un = lambda sql, *a: conn.execute(sql, a).fetchone()

        total = un("SELECT count(*) AS n FROM ligne_source")["n"]
        statuts = q("SELECT statut_final, count(*) AS lignes, count(DISTINCT numero_normalise) AS numeros_distincts "
                    "FROM v_statut_ligne GROUP BY 1 ORDER BY 1")
        for r in statuts:
            r["part"] = _pct(r["lignes"], total)

        motifs_struct = q("SELECT verdict_structurel, motif_structurel, count(*) AS lignes FROM ligne_source "
                          "GROUP BY 1, 2 ORDER BY 1 DESC, 3 DESC")
        for r in motifs_struct:
            r["part"] = _pct(r["lignes"], total)

        motifs_final = q("SELECT statut_final, motif_final, count(*) AS lignes FROM v_statut_ligne "
                         "GROUP BY 1, 2 ORDER BY 1, 3 DESC")

        corrections = q("SELECT c AS correction, count(*) AS lignes, "
                        "count(*) FILTER (WHERE verdict_structurel = 'VALIDE') AS dont_struct_valides "
                        "FROM ligne_source, unnest(corrections) c GROUP BY 1 ORDER BY 2 DESC")
        sauvees = un("SELECT count(*) AS n FROM ligne_source WHERE verdict_structurel='VALIDE' "
                     "AND cardinality(corrections) > 0")["n"]

        # Doublons : même numéro normalisé sur plusieurs lignes
        dup = un("""
            WITH g AS (SELECT numero_normalise, count(*) AS n, count(DISTINCT numero_brut) AS formes,
                              count(DISTINCT raison_sociale) AS noms
                       FROM ligne_source WHERE numero_normalise IS NOT NULL GROUP BY 1)
            SELECT count(*) FILTER (WHERE n > 1) AS groupes,
                   coalesce(sum(n - 1) FILTER (WHERE n > 1), 0) AS lignes_en_trop,
                   count(*) FILTER (WHERE n > 1 AND formes > 1) AS groupes_formes_multiples,
                   count(*) FILTER (WHERE noms > 1) AS groupes_noms_divergents
            FROM g""")
        dup_brut = un("SELECT coalesce(sum(n - 1), 0) AS n FROM (SELECT numero_brut, count(*) n FROM ligne_source "
                      "WHERE numero_normalise IS NOT NULL GROUP BY 1 HAVING count(*) > 1) x")["n"]
        dup_taille = q("SELECT n AS lignes_par_numero, count(*) AS numeros FROM (SELECT numero_normalise, count(*) n "
                       "FROM ligne_source WHERE numero_normalise IS NOT NULL GROUP BY 1) x WHERE n > 1 GROUP BY 1 ORDER BY 1")
        dup_ex = q("""SELECT numero_normalise, string_agg(DISTINCT quote_literal(numero_brut), ' , ') AS formes_saisies,
                             count(*) AS lignes, string_agg(DISTINCT source_saisie, ', ') AS sources
                      FROM ligne_source WHERE numero_normalise IS NOT NULL GROUP BY 1
                      HAVING count(DISTINCT numero_brut) > 2 ORDER BY 3 DESC, 1 LIMIT 5""")

        # Réduction des appels
        struct_ok = un("SELECT count(*) AS n FROM ligne_source WHERE verdict_structurel='VALIDE'")["n"]
        uniques = un("SELECT count(DISTINCT numero_normalise) AS n FROM ligne_source "
                     "WHERE verdict_structurel='VALIDE'")["n"]

        # VIES
        vies = q("SELECT statut, user_error, count(*) AS numeros FROM verification_vies GROUP BY 1, 2 ORDER BY 1, 3 DESC")
        appels = un("SELECT count(*) AS n, round(avg(latence_ms)) AS lat_moy, max(latence_ms) AS lat_max, "
                    "min(appele_le) AS premier, max(appele_le) AS dernier FROM appel_vies")
        campagnes = q("SELECT id, mode, taille_demandee, nb_cibles, nb_traites, statut, "
                      "to_char(demarree_le, 'YYYY-MM-DD HH24:MI') AS demarree, "
                      "to_char(terminee_le, 'YYYY-MM-DD HH24:MI') AS terminee FROM campagne ORDER BY id")
        fraicheur = q(f"""SELECT CASE WHEN derniere_reponse_definitive_le IS NULL THEN 'jamais tranché'
                                     WHEN derniere_reponse_definitive_le > now() - interval '1 day' THEN '< 24 h'
                                     WHEN derniere_reponse_definitive_le > now() - interval '{config.TTL_CAMPAGNE_J} days'
                                          THEN '< {config.TTL_CAMPAGNE_J} j'
                                     ELSE '> {config.TTL_CAMPAGNE_J} j (à revérifier)' END AS fraicheur,
                                count(*) AS numeros FROM verification_vies GROUP BY 1 ORDER BY 1""")

        par_pays = q("""SELECT coalesce(pays_normalise, '(vide)') AS pays, count(*) AS lignes,
                         count(*) FILTER (WHERE statut_final='VALIDE') AS valides,
                         count(*) FILTER (WHERE statut_final='INVALIDE') AS invalides,
                         count(*) FILTER (WHERE statut_final='INDETERMINE') AS indetermines
                  FROM v_statut_ligne s JOIN ligne_source l USING (id_source)
                  GROUP BY 1 ORDER BY 2 DESC""")
        par_source = q("""SELECT source_saisie, count(*) AS lignes,
                           count(*) FILTER (WHERE verdict_structurel='INVALIDE') AS rejets_structurels,
                           round(100.0 * count(*) FILTER (WHERE verdict_structurel='INVALIDE') / count(*), 1) AS taux_rejet_pct
                    FROM ligne_source GROUP BY 1 ORDER BY 4 DESC""")

    md = [
        "# Rapport de réconciliation — référentiel TVA Meridian Distribution",
        "",
        f"_Généré le {datetime.now():%Y-%m-%d %H:%M} par `python -m tva.cli rapport` — ne pas éditer à la main._",
        "",
        "## 1. Réponse à la question",
        "",
        "> Parmi nos numéros, lesquels sont valides, lesquels ne le sont pas — et lesquels n'ont pas pu être tranchés ?",
        "",
        _table(statuts, ["statut_final", "lignes", "part", "numeros_distincts"],
               ["Statut", "Lignes", "Part", "Numéros distincts"]),
        "",
        f"Total : **{total} lignes**. Règles : une ligne rejetée au contrôle structurel est INVALIDE sans appel VIES ; "
        "une ligne structurellement valide est VALIDE/INVALIDE selon la **dernière réponse définitive** de VIES, "
        "et INDETERMINE tant que VIES n'a pas répondu (non encore interrogée, ou État membre indisponible). "
        "Seuls les VALIDE autorisent la facturation hors taxe.",
        "",
        "### Détail par motif",
        "",
        _table(motifs_final, ["statut_final", "motif_final", "lignes"], ["Statut", "Motif", "Lignes"]),
        "",
        "## 2. Contrôle structurel (hors ligne)",
        "",
        _table(motifs_struct, ["verdict_structurel", "motif_structurel", "lignes", "part"],
               ["Verdict", "Motif", "Lignes", "Part"]),
        "",
        "### Normalisation : bruit de saisie retiré",
        "",
        _table(corrections, ["correction", "lignes", "dont_struct_valides"],
               ["Correction", "Lignes concernées", "dont structurellement valides"]),
        "",
        f"**{sauvees} lignes** sont structurellement valides *grâce* à la normalisation : sans elle, "
        "elles auraient été comptées comme invalides pour un simple bruit de saisie.",
        "",
        "## 3. Doublons",
        "",
        "Définition retenue : **deux lignes sont des doublons si elles portent le même numéro normalisé** "
        "(préfixe pays + corps, après retrait du bruit de saisie). Un numéro de TVA identifie un assujetti : "
        "le vérifier une fois suffit pour toutes ses lignes. La raison sociale n'entre pas dans la définition "
        "(elle varie selon les canaux et n'est pas ce que l'on vérifie).",
        "",
        f"- Numéros présents sur plusieurs lignes : **{dup['groupes']}**",
        f"- Lignes en trop (doublons) : **{dup['lignes_en_trop']}**",
        f"- dont doublons visibles sur la valeur brute : {dup_brut} ; révélés seulement par la normalisation : "
        f"{dup['lignes_en_trop'] - dup_brut}",
        f"- Numéros saisis sous plusieurs formes différentes : {dup['groupes_formes_multiples']}",
        f"- Numéros partagés par des raisons sociales différentes : {dup['groupes_noms_divergents']}",
        "",
        _table(dup_taille, ["lignes_par_numero", "numeros"], ["Lignes par numéro", "Numéros"]),
        "",
        "Exemples de numéros saisis sous 3 formes ou plus :",
        "",
        _table(dup_ex, ["numero_normalise", "formes_saisies", "lignes", "sources"],
               ["Numéro normalisé", "Formes saisies", "Lignes", "Canaux"]),
        "",
        "## 4. Réduction des appels VIES",
        "",
        "| Étape | Appels nécessaires | Évités |",
        "|---|---|---|",
        f"| Approche naïve : un appel par ligne | {total} | - |",
        f"| Après filtre structurel | {struct_ok} | {total - struct_ok} |",
        f"| Après dédoublonnage | {uniques} | {struct_ok - uniques} |",
        f"| **Total évité** | | **{total - uniques} ({_pct(total - uniques, total)})** |",
        "",
        "## 5. Vérification en ligne (VIES)",
        "",
        f"Appels effectués : {appels['n']} (latence moyenne {appels['lat_moy']} ms, max {appels['lat_max']} ms) ; "
        f"premier appel {appels['premier']:%Y-%m-%d %H:%M}, dernier {appels['dernier']:%Y-%m-%d %H:%M}."
        if appels["n"] else "Aucun appel VIES effectué pour l'instant (lancer `python -m tva.cli campagne --echantillon 200`).",
        "",
        "### Dernier état connu par numéro",
        "",
        _table(vies, ["statut", "user_error", "numeros"], ["Statut", "Code VIES", "Numéros"]) if vies else "_(vide)_",
        "",
        "### Fraîcheur des réponses",
        "",
        _table(fraicheur, ["fraicheur", "numeros"], ["Âge du dernier verdict définitif", "Numéros"]) if fraicheur else "_(vide)_",
        "",
        "### Campagnes",
        "",
        _table(campagnes, ["id", "mode", "taille_demandee", "nb_cibles", "nb_traites", "statut", "demarree", "terminee"],
               ["#", "Mode", "Échantillon", "Cibles", "Traités", "Statut", "Début", "Fin"]) if campagnes else "_(aucune)_",
        "",
        "## 6. Par pays",
        "",
        _table(par_pays, ["pays", "lignes", "valides", "invalides", "indetermines"],
               ["Pays", "Lignes", "Valides", "Invalides", "Indéterminés"]),
        "",
        "## 7. Qualité par canal de saisie",
        "",
        _table(par_source, ["source_saisie", "lignes", "rejets_structurels", "taux_rejet_pct"],
               ["Canal", "Lignes", "Rejets structurels", "Taux de rejet (%)"]),
        "",
    ]
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text("\n".join(md), encoding="utf-8")
    log.info("Rapport écrit dans %s", sortie)
    return sortie
