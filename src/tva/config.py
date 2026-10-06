"""Configuration centralisée, lue depuis les variables d'environnement (voir .env.example)."""

import os
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]


def _env(nom: str, defaut: str) -> str:
    return os.getenv(nom, defaut)


DATABASE_URL = _env(
    "DATABASE_URL",
    "postgresql://{u}:{p}@{h}:{port}/{db}".format(
        u=_env("POSTGRES_USER", "meridian"),
        p=_env("POSTGRES_PASSWORD", "meridian"),
        h=_env("POSTGRES_HOST", "localhost"),
        port=_env("POSTGRES_PORT", "5435"),
        db=_env("POSTGRES_DB", "tva"),
    ),
)

FICHIER_SOURCE = Path(_env("FICHIER_SOURCE", str(RACINE / "data" / "numeros_tva.csv")))

VIES_BASE_URL = _env("VIES_BASE_URL", "https://ec.europa.eu/taxation_customs/vies/rest-api")
VIES_TIMEOUT_S = float(_env("VIES_TIMEOUT_S", "10"))
VIES_DELAI_S = float(_env("VIES_DELAI_S", "1.0"))          # temporisation entre deux appels
VIES_MAX_TENTATIVES = int(_env("VIES_MAX_TENTATIVES", "3"))  # par numéro et par passage
VIES_BACKOFF_S = float(_env("VIES_BACKOFF_S", "2.0"))        # attente de base avant nouvelle tentative

# Durée pendant laquelle un verdict VIES est réutilisable sans nouvel appel.
TTL_VALIDE_H = float(_env("TTL_VALIDE_H", "24"))
TTL_INVALIDE_H = float(_env("TTL_INVALIDE_H", "24"))
# Au-delà de cette durée, un verdict de campagne est considéré à revérifier.
TTL_CAMPAGNE_J = int(_env("TTL_CAMPAGNE_J", "30"))

RAPPORT_SORTIE = Path(_env("RAPPORT_SORTIE", str(RACINE / "docs" / "rapport_reconciliation.md")))
