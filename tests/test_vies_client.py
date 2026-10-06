"""Interprétation des réponses VIES : la panne ne doit jamais devenir une invalidité."""

import httpx

from tva.vies_client import INDETERMINE, INVALIDE, VALIDE, ClientVies, interpreter


def corps(valide, code, name="---"):
    return {"isValid": valide, "userError": code, "name": name, "address": "---",
            "requestDate": "2026-10-06T07:48:36.354Z"}


def test_valide():
    r = interpreter("FR27552032534", 200, corps(True, "VALID", "SA DANONE"), 50)
    assert r.statut == VALIDE and r.nom == "SA DANONE" and r.adresse is None


def test_invalide():
    assert interpreter("DK73224645", 200, corps(False, "INVALID"), 50).statut == INVALIDE


def test_ms_unavailable_avec_isvalid_false_est_indetermine():
    r = interpreter("DK73224645", 200, corps(False, "MS_UNAVAILABLE"), 50)
    assert r.statut == INDETERMINE and r.transitoire


def test_incoherence_isvalid_userError():
    assert interpreter("X", 200, corps(False, "VALID"), 1).statut == INDETERMINE


def test_error_wrappers():
    r = interpreter("X", 200, {"actionSucceed": False, "errorWrappers": [{"error": "MS_MAX_CONCURRENT_REQ"}]}, 1)
    assert r.statut == INDETERMINE and r.transitoire


def _client(handler):
    c = ClientVies(base_url="http://vies.test", max_tentatives=3, backoff_s=0)
    c._http = httpx.Client(transport=httpx.MockTransport(handler))
    return c


def test_timeout_reseau_est_indetermine():
    def handler(req):
        raise httpx.ConnectTimeout("boom")
    assert _client(handler).verifier("FR27552032534").statut == INDETERMINE


def test_http_500_est_indetermine():
    assert _client(lambda req: httpx.Response(500, text="err")).verifier("FR27552032534").statut == INDETERMINE


def test_nouvelle_tentative_puis_succes():
    appels = []

    def handler(req):
        appels.append(1)
        if len(appels) < 2:
            return httpx.Response(200, json=corps(False, "MS_UNAVAILABLE"))
        return httpx.Response(200, json=corps(True, "VALID"))

    assert _client(handler).verifier("FR27552032534").statut == VALIDE
    assert len(appels) == 2


def test_url_construite():
    vu = {}

    def handler(req):
        vu["url"] = str(req.url)
        return httpx.Response(200, json=corps(True, "VALID"))

    _client(handler).verifier("NL004495445B01")
    assert vu["url"] == "http://vies.test/ms/NL/vat/004495445B01"
