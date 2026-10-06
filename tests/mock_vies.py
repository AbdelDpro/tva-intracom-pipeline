"""Faux service VIES, pour tester sans dépendre du vrai (ni le surcharger).

Reproduit le format réel de l'API REST VIES, y compris le piège :
isValid=false accompagné de userError=MS_UNAVAILABLE.

Lancement manuel : uvicorn tests.mock_vies:app --port 8099
puis VIES_BASE_URL=http://localhost:8099 python -m tva.cli campagne --echantillon 20
"""

import hashlib
import os
from datetime import datetime, timezone

from fastapi import FastAPI

app = FastAPI(title="Mock VIES")

VALIDES_CONNUS = {"FR27552032534"}               # Danone, vérifié à la main sur le vrai VIES
PAYS_EN_PANNE = set(filter(None, os.getenv("MOCK_PAYS_EN_PANNE", "").split(",")))


def _h(num: str) -> int:
    return int(hashlib.md5(num.encode()).hexdigest(), 16)


def _reponse(ms: str, vat: str, valide: bool, code: str) -> dict:
    return {
        "isValid": valide,
        "requestDate": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "userError": code,
        "name": "SOCIETE TEST" if valide else "---",
        "address": "1 RUE DU TEST\n69000 LYON" if valide else "---",
        "requestIdentifier": "",
        "originalVatNumber": vat,
        "vatNumber": vat,
        "viesApproximate": {"name": "---", "street": "---", "postalCode": "---", "city": "---",
                            "companyType": "---", "matchName": 3, "matchStreet": 3,
                            "matchPostalCode": 3, "matchCity": 3, "matchCompanyType": 3},
    }


@app.get("/ms/{ms}/vat/{vat}")
def check(ms: str, vat: str):
    num = ms + vat
    if ms in PAYS_EN_PANNE or _h(num) % 10 == 0:
        return _reponse(ms, vat, False, "MS_UNAVAILABLE")
    if num in VALIDES_CONNUS or _h(num) % 10 in (1, 2):
        return _reponse(ms, vat, True, "VALID")
    return _reponse(ms, vat, False, "INVALID")
