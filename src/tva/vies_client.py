"""Client de l'API REST VIES (Commission européenne).

Endpoint : GET {base}/ms/{PAYS}/vat/{NUMERO}

Point clé découvert en lisant les réponses en entier : le champ ``isValid`` vaut
``false`` aussi bien quand le numéro est inconnu (``userError = INVALID``) que quand
l'administration nationale n'a PAS RÉPONDU (``userError = MS_UNAVAILABLE``, ``TIMEOUT``...).
Se fier à ``isValid`` seul enregistrerait une panne comme une invalidité.
Le verdict est donc dérivé de ``userError``, et toute incohérence donne INDETERMINE.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime

import httpx

from . import config

log = logging.getLogger(__name__)

VALIDE, INVALIDE, INDETERMINE = "VALIDE", "INVALIDE", "INDETERMINE"

# Codes userError -> statut. Tout code non listé est traité comme INDETERMINE.
CODES_DEFINITIFS = {"VALID": VALIDE, "INVALID": INVALIDE, "INVALID_INPUT": INVALIDE}
# Codes pour lesquels réessayer plus tard a un sens (panne, surcharge, quota).
CODES_TRANSITOIRES = {
    "MS_UNAVAILABLE", "TIMEOUT", "SERVICE_UNAVAILABLE",
    "MS_MAX_CONCURRENT_REQ", "MS_MAX_CONCURRENT_REQ_TIME",
    "GLOBAL_MAX_CONCURRENT_REQ", "GLOBAL_MAX_CONCURRENT_REQ_TIME",
    "HTTP_ERROR", "NETWORK_ERROR", "BAD_RESPONSE",
}
VIES_NON_COMMUNIQUE = "---"  # valeur renvoyée par VIES quand un État ne publie pas le nom/l'adresse


@dataclass
class ReponseVies:
    numero: str                 # numéro normalisé interrogé
    statut: str                 # VALIDE | INVALIDE | INDETERMINE
    user_error: str             # code VIES (ou code interne pour les erreurs réseau)
    is_valid: bool | None = None
    nom: str | None = None
    adresse: str | None = None
    date_requete_vies: datetime | None = None
    http_status: int | None = None
    latence_ms: int | None = None
    erreur: str | None = None

    @property
    def transitoire(self) -> bool:
        return self.statut == INDETERMINE and self.user_error in CODES_TRANSITOIRES


def _texte(v: str | None) -> str | None:
    """'---' signifie « non communiqué » : on stocke NULL plutôt qu'une fausse donnée."""
    if v is None or v.strip() in ("", VIES_NON_COMMUNIQUE):
        return None
    return v.strip()


def _date(v: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")) if v else None
    except ValueError:
        return None


def interpreter(numero: str, http_status: int, corps: dict, latence_ms: int) -> ReponseVies:
    """Transforme une réponse HTTP de VIES en verdict à trois états."""
    # Format d'erreur alternatif : {"actionSucceed": false, "errorWrappers": [{"error": "..."}]}
    if corps.get("errorWrappers"):
        code = corps["errorWrappers"][0].get("error") or "BAD_RESPONSE"
        return ReponseVies(numero, INDETERMINE if code != "INVALID_INPUT" else INVALIDE, code,
                           http_status=http_status, latence_ms=latence_ms,
                           erreur=corps["errorWrappers"][0].get("message"))

    code = corps.get("userError") or "BAD_RESPONSE"
    is_valid = corps.get("isValid")
    statut = CODES_DEFINITIFS.get(code, INDETERMINE)

    # Garde-fou : isValid et userError doivent raconter la même histoire.
    if (statut == VALIDE and is_valid is not True) or (statut == INVALIDE and code == "INVALID" and is_valid is not False):
        log.warning("Réponse VIES incohérente pour %s : isValid=%s userError=%s", numero, is_valid, code)
        statut, code = INDETERMINE, f"INCOHERENT_{code}"

    return ReponseVies(
        numero=numero, statut=statut, user_error=code, is_valid=is_valid,
        nom=_texte(corps.get("name")), adresse=_texte(corps.get("address")),
        date_requete_vies=_date(corps.get("requestDate")),
        http_status=http_status, latence_ms=latence_ms,
    )


class ClientVies:
    """Client synchrone avec timeout et nouvelles tentatives sur erreurs transitoires."""

    def __init__(self, base_url: str | None = None, timeout_s: float | None = None,
                 max_tentatives: int | None = None, backoff_s: float | None = None):
        self.base_url = (base_url or config.VIES_BASE_URL).rstrip("/")
        self.max_tentatives = max_tentatives or config.VIES_MAX_TENTATIVES
        self.backoff_s = config.VIES_BACKOFF_S if backoff_s is None else backoff_s
        self._http = httpx.Client(timeout=timeout_s or config.VIES_TIMEOUT_S,
                                  headers={"Accept": "application/json"})

    def close(self) -> None:
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _appel_unique(self, numero: str) -> ReponseVies:
        pays, corps_num = numero[:2], numero[2:]
        url = f"{self.base_url}/ms/{pays}/vat/{corps_num}"
        debut = time.perf_counter()
        try:
            r = self._http.get(url)
        except httpx.TimeoutException as e:
            ms = int((time.perf_counter() - debut) * 1000)
            return ReponseVies(numero, INDETERMINE, "TIMEOUT", latence_ms=ms, erreur=repr(e))
        except httpx.HTTPError as e:
            ms = int((time.perf_counter() - debut) * 1000)
            return ReponseVies(numero, INDETERMINE, "NETWORK_ERROR", latence_ms=ms, erreur=repr(e))
        ms = int((time.perf_counter() - debut) * 1000)

        try:
            corps = r.json()
        except ValueError:
            corps = None
        if isinstance(corps, dict) and (r.status_code == 200 or corps.get("errorWrappers")):
            return interpreter(numero, r.status_code, corps, ms)
        return ReponseVies(numero, INDETERMINE, "HTTP_ERROR", http_status=r.status_code,
                           latence_ms=ms, erreur=r.text[:300])

    def verifier(self, numero: str) -> ReponseVies:
        """Interroge VIES, en réessayant (backoff exponentiel) sur les erreurs transitoires.

        Ne lève jamais d'exception : en cas d'échec, renvoie un statut INDETERMINE.
        """
        rep = self._appel_unique(numero)
        tentative = 1
        while rep.transitoire and tentative < self.max_tentatives:
            attente = self.backoff_s * 2 ** (tentative - 1)
            log.info("VIES %s -> %s, nouvelle tentative dans %.1fs", numero, rep.user_error, attente)
            time.sleep(attente)
            rep = self._appel_unique(numero)
            tentative += 1
        return rep
