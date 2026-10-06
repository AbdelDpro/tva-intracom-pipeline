"""Point d'entrée en ligne de commande.

    python -m tva.cli init                       # crée le schéma
    python -m tva.cli charger                    # charge le CSV (idempotent)
    python -m tva.cli repartition                # répartition par motif structurel
    python -m tva.cli mesurer --n 5              # mesure la latence VIES et projette le coût
    python -m tva.cli campagne --echantillon 200 # campagne VIES (reprenable)
    python -m tva.cli campagne                   # campagne complète
    python -m tva.cli rapport                    # régénère docs/rapport_reconciliation.md
"""

import argparse
import json
import logging
import signal

from . import campaign, db, loader, report
from .logs import configurer_logs

log = logging.getLogger("tva")


def _sigterm(*_):
    # `docker stop` envoie SIGTERM : on le traite comme un Ctrl+C pour clôturer proprement la campagne.
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> None:
    signal.signal(signal.SIGTERM, _sigterm)
    configurer_logs()
    p = argparse.ArgumentParser(prog="tva", description="Référentiel TVA Meridian")
    sp = p.add_subparsers(dest="cmd", required=True)
    sp.add_parser("init", help="Créer le schéma")
    sp.add_parser("charger", help="Charger le CSV avec verdict structurel")
    sp.add_parser("repartition", help="Répartition par motif structurel")
    m = sp.add_parser("mesurer", help="Mesurer la latence VIES")
    m.add_argument("--n", type=int, default=5)
    c = sp.add_parser("campagne", help="Campagne de vérification VIES")
    c.add_argument("--echantillon", type=int, default=None, help="Nombre de numéros (mode échantillon)")
    c.add_argument("--delai", type=float, default=None, help="Temporisation entre appels (s)")
    sp.add_parser("rapport", help="Générer le rapport de réconciliation")
    a = p.parse_args(argv)

    if a.cmd == "init":
        with db.connecter() as conn:
            db.initialiser_schema(conn)
    elif a.cmd == "charger":
        loader.charger()
    elif a.cmd == "repartition":
        with db.connecter() as conn:
            rows = conn.execute("SELECT verdict_structurel, motif_structurel, count(*) AS n FROM ligne_source "
                                "GROUP BY 1, 2 ORDER BY 1 DESC, 3 DESC").fetchall()
        for r in rows:
            print(f"{r['verdict_structurel']:9} {r['motif_structurel']:24} {r['n']:>6}")
    elif a.cmd == "mesurer":
        print(json.dumps(campaign.mesurer(a.n), indent=2))
    elif a.cmd == "campagne":
        print(json.dumps(campaign.executer(a.echantillon, delai_s=a.delai), indent=2, default=str))
    elif a.cmd == "rapport":
        print(report.generer())


if __name__ == "__main__":
    main()
