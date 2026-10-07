"""Tests d'intégration : base PostgreSQL réelle + faux VIES (transport httpx en mémoire).

Nécessitent une base accessible (DATABASE_URL) ; ignorés sinon.
ATTENTION : vident les tables de la base ciblée -> utiliser une base de test (TEST_DATABASE_URL).
"""

import os

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

TEST_DB = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL non défini")

if TEST_DB:
    os.environ["DATABASE_URL"] = TEST_DB

from tva import campaign, config, db, loader
from tva.vies_client import ClientVies

config.DATABASE_URL = TEST_DB or config.DATABASE_URL


def client_mock(regles):
    """regles : fonction numero -> (isValid, userError)."""
    def handler(req):
        parts = req.url.path.split("/")  # /ms/{PAYS}/vat/{NUMERO}
        ms, vat = parts[-3], parts[-1]
        ok, code = regles(ms + vat)
        return httpx.Response(200, json={"isValid": ok, "userError": code, "name": "---",
                                         "address": "---", "requestDate": "2026-10-06T08:00:00Z"})
    c = ClientVies(base_url="http://vies.test", max_tentatives=1, backoff_s=0)
    c._http = httpx.Client(transport=httpx.MockTransport(handler))
    return c


@pytest.fixture(autouse=True)
def base_propre():
    with psycopg.connect(TEST_DB) as conn:
        conn.execute("DROP VIEW IF EXISTS v_statut_ligne")
        conn.execute("DROP TABLE IF EXISTS appel_vies, verification_vies, campagne, ligne_source CASCADE")
        conn.commit()
    loader.charger()
    yield


def compter(sql):
    with db.connecter() as conn:
        return list(conn.execute(sql).fetchone().values())[0]


def test_rechargement_sans_doublon():
    loader.charger()
    assert compter("SELECT count(*) FROM ligne_source") == 10000


def test_campagne_echantillon_et_reprise():
    # 1er passage : on « coupe » après 5 appels en levant KeyboardInterrupt
    n = {"appels": 0}

    def regles(num):
        n["appels"] += 1
        if n["appels"] > 5:
            raise KeyboardInterrupt
        return False, "INVALID"

    r1 = campaign.executer(echantillon=20, client=client_mock(regles), delai_s=0)
    assert r1["statut"] == "INTERROMPUE"
    assert compter("SELECT count(*) FROM verification_vies") == 5

    # 2e passage : ne refait pas les 5 premiers
    vus = []

    def regles2(num):
        vus.append(num)
        return True, "VALID"

    r2 = campaign.executer(echantillon=20, client=client_mock(regles2), delai_s=0)
    assert r2["statut"] == "TERMINEE" and len(vus) == 15
    assert compter("SELECT count(*) FROM verification_vies") == 20

    # 3e passage : plus rien à faire
    r3 = campaign.executer(echantillon=20, client=client_mock(regles2), delai_s=0)
    assert r3["cibles"] == 0


def test_indisponibilite_jamais_enregistree_comme_invalide():
    campaign.executer(echantillon=10, client=client_mock(lambda n: (False, "MS_UNAVAILABLE")), delai_s=0)
    assert compter("SELECT count(*) FROM verification_vies WHERE statut='INDETERMINE'") == 10
    assert compter("SELECT count(*) FROM v_statut_ligne WHERE motif_final LIKE 'VIES:MS_UNAVAILABLE'") >= 10
    assert compter("SELECT count(*) FROM v_statut_ligne WHERE motif_final = 'VIES:INVALID'") == 0
    # Les indéterminés sont retentés au passage suivant
    r = campaign.executer(echantillon=10, client=client_mock(lambda n: (True, "VALID")), delai_s=0)
    assert r["cibles"] == 10


def test_api_verdict_origine_fraicheur():
    from tva import api

    with TestClient(api.app) as tc:
        api.app.state.vies = client_mock(lambda n: (True, "VALID"))
        r1 = tc.get("/tva/FR27552032534").json()
        assert r1["verdict"] == "VALIDE" and r1["origine"] == "vies" and r1["facturable_ht"]
        r2 = tc.get("/tva/fr 2755 2032534").json()
        assert r2["origine"] == "cache" and r2["age_secondes"] >= 0 and r2["verifie_le"]

        r3 = tc.get("/tva/FR28552032534").json()
        assert r3["verdict"] == "INVALIDE" and r3["origine"] == "controle_structurel"

        api.app.state.vies = client_mock(lambda n: (False, "MS_UNAVAILABLE"))
        r4 = tc.get("/tva/DK61530843").json()
        assert r4["verdict"] == "INDETERMINE" and r4["origine"] == "vies_indisponible" and r4["dernier_verdict_connu"] is None and not r4["facturable_ht"]

        r5 = tc.get("/tva/FR27552032534", params={"forcer": True}).json()
        assert r5["verdict"] == "INDETERMINE" and r5["origine"] == "vies_indisponible"
        assert r5["dernier_verdict_connu"]["verdict"] == "VALIDE"

        assert tc.get("/openapi.json").status_code == 200
