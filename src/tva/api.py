"""API REST appelée par la facturation avant chaque émission hors taxe.

Documentation OpenAPI : /docs (Swagger) et /openapi.json
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Query

from . import db, service
from .logs import configurer_logs
from .vies_client import ClientVies

configurer_logs()


@asynccontextmanager
async def lifespan(app: FastAPI):
    with db.connecter() as conn:
        db.initialiser_schema(conn)
    app.state.vies = ClientVies()
    yield
    app.state.vies.close()


app = FastAPI(
    title="Meridian — Vérification TVA intracommunautaire",
    version="1.0.0",
    description="Renvoie pour un numéro de TVA : le verdict (VALIDE / INVALIDE / INDETERMINE), "
                "son origine (appel VIES frais, cache, contrôle structurel) et sa fraîcheur. "
                "Seul `facturable_ht = true` autorise une facture hors taxe.",
    lifespan=lifespan,
)


@app.get("/sante", tags=["technique"])
def sante() -> dict:
    with db.connecter() as conn:
        conn.execute("SELECT 1")
    return {"statut": "ok"}


# Endpoint synchrone (def, pas async) : FastAPI l'exécute dans un thread,
# l'appel bloquant à VIES ne gèle donc pas le serveur.
@app.get("/tva/{numero}", response_model=service.ReponseVerification, tags=["vérification"])
def verifier_tva(
    numero: str,
    pays_declare: str | None = Query(None, description="Pays de la fiche client, utilisé si le numéro n'a pas de préfixe"),
    forcer: bool = Query(False, description="Ignorer le cache et interroger VIES"),
) -> service.ReponseVerification:
    return service.verifier(numero, pays_declare, app.state.vies, forcer=forcer)


@app.get("/referentiel/repartition", tags=["référentiel"])
def repartition() -> dict:
    """Répartition des lignes du référentiel par statut final et par motif."""
    with db.connecter() as conn:
        statuts = conn.execute(
            "SELECT statut_final, count(*) AS n FROM v_statut_ligne GROUP BY 1 ORDER BY 1").fetchall()
        motifs = conn.execute(
            "SELECT motif_final, count(*) AS n FROM v_statut_ligne GROUP BY 1 ORDER BY 2 DESC").fetchall()
    return {"par_statut": {r["statut_final"]: r["n"] for r in statuts},
            "par_motif": {r["motif_final"]: r["n"] for r in motifs}}
