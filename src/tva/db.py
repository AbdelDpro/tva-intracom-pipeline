"""Accès PostgreSQL : connexion et création du schéma."""

import logging

import psycopg
from psycopg.rows import dict_row

from . import config

log = logging.getLogger(__name__)
FICHIER_SCHEMA = config.RACINE / "sql" / "001_schema.sql"


def connecter() -> psycopg.Connection:
    """Ouvre une connexion ; les lignes sont retournées sous forme de dict."""
    return psycopg.connect(config.DATABASE_URL, row_factory=dict_row)


def initialiser_schema(conn: psycopg.Connection) -> None:
    """Applique le script versionné (idempotent)."""
    conn.execute(FICHIER_SCHEMA.read_text(encoding="utf-8"))
    conn.commit()
    log.info("Schéma appliqué depuis %s", FICHIER_SCHEMA.name)
