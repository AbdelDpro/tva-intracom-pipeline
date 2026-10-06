"""Configuration des logs : console + fichier logs/tva.log."""

import logging
import os
from pathlib import Path

from . import config


def configurer_logs() -> None:
    if getattr(configurer_logs, "_fait", False):
        return
    dossier = Path(os.getenv("LOG_DIR", str(config.RACINE / "logs")))
    dossier.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s - %(message)s")
    racine = logging.getLogger()
    racine.setLevel(os.getenv("LOG_LEVEL", "INFO"))
    for h in (logging.StreamHandler(), logging.FileHandler(dossier / "tva.log", encoding="utf-8")):
        h.setFormatter(fmt)
        racine.addHandler(h)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    configurer_logs._fait = True
