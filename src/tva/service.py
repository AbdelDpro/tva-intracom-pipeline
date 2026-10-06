"""Logique de décision de l'API : quel verdict rendre, d'où il vient, de quand il date.

Ordre de décision pour un numéro :
  1. contrôle structurel  -> s'il échoue, INVALIDE immédiat, sans appel réseau ;
  2. cache (dernière réponse VIES définitive) -> réutilisée si plus récente que le TTL ;
  3. appel VIES frais     -> VALIDE / INVALIDE enregistrés avec leur date ;
  4. VIES injoignable     -> INDETERMINE (origine 'vies_indisponible'), jamais INVALIDE ;
                            on joint pour information le dernier verdict connu s'il existe
                            (avec sa date), mais on ne l'avalise pas pour une facture HT.

Règle de facturation : ``facturable_ht`` n'est vrai QUE pour un VALIDE dont la
fraîcheur est dans le TTL. Tout le reste -> facturer TTC ou bloquer.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from . import config, db, repository
from .structural import Verdict, valider
from .vies_client import INDETERMINE, VALIDE, ClientVies


class DetailVies(BaseModel):
    user_error: str | None = Field(None, description="Code brut renvoyé par VIES (VALID, INVALID, MS_UNAVAILABLE...)")
    nom: str | None = Field(None, description="Nom enregistré (NULL si l'État ne le communique pas)")
    adresse: str | None = None
    date_requete_vies: datetime | None = Field(None, description="requestDate renvoyé par VIES")


class DernierVerdictConnu(BaseModel):
    verdict: str
    verifie_le: datetime
    age_secondes: int


class ReponseVerification(BaseModel):
    numero_saisi: str
    numero_normalise: str | None
    verdict: str = Field(description="VALIDE | INVALIDE | INDETERMINE")
    facturable_ht: bool = Field(description="True uniquement si VALIDE et frais : autorise la facture hors taxe")
    origine: str = Field(description="vies (appel frais) | cache (valeur déjà connue) | "
                                     "controle_structurel (rejet sans appel) | vies_indisponible (VIES n'a pas pu trancher)")
    verifie_le: datetime | None = Field(description="Date de l'information renvoyée")
    age_secondes: int | None = Field(description="Âge de l'information au moment de la réponse")
    ttl_secondes: int | None = Field(description="Durée de validité accordée à ce type de verdict")
    motif: str
    detail_vies: DetailVies | None = None
    dernier_verdict_connu: DernierVerdictConnu | None = Field(
        None, description="Renseigné quand VIES est injoignable : dernier verdict définitif, pour information")
    message: str


def _ttl_s(verdict: str) -> int:
    return int((config.TTL_VALIDE_H if verdict == VALIDE else config.TTL_INVALIDE_H) * 3600)


def _age_s(date: datetime) -> int:
    return int((datetime.now(timezone.utc) - date).total_seconds())


def verifier(numero_saisi: str, pays_declare: str | None, client: ClientVies,
             forcer: bool = False) -> ReponseVerification:
    s = valider(numero_saisi, pays_declare)
    maintenant = datetime.now(timezone.utc)

    # 1. Rejet structurel : certain, pas besoin de VIES.
    if s.verdict is Verdict.INVALIDE:
        return ReponseVerification(
            numero_saisi=numero_saisi, numero_normalise=s.normalise, verdict="INVALIDE",
            facturable_ht=False, origine="controle_structurel", verifie_le=maintenant,
            age_secondes=0, ttl_secondes=None, motif=f"STRUCTUREL:{s.motif.value}",
            message="Numéro rejeté par le contrôle de format/clé : facturer TTC et corriger la fiche client.")

    numero = s.normalise
    with db.connecter() as conn:
        connu = repository.lire(conn, numero)

        # 2. Cache frais
        if connu and connu["dernier_statut_definitif"] and not forcer:
            verdict = connu["dernier_statut_definitif"]
            age = _age_s(connu["derniere_reponse_definitive_le"])
            if age < _ttl_s(verdict):
                return ReponseVerification(
                    numero_saisi=numero_saisi, numero_normalise=numero, verdict=verdict,
                    facturable_ht=verdict == VALIDE, origine="cache",
                    verifie_le=connu["derniere_reponse_definitive_le"], age_secondes=age,
                    ttl_secondes=_ttl_s(verdict), motif=f"VIES:{'VALID' if verdict == VALIDE else 'INVALID'}",
                    detail_vies=DetailVies(user_error="VALID" if verdict == VALIDE else "INVALID",
                                           nom=connu["nom"], adresse=connu["adresse"],
                                           date_requete_vies=connu["date_requete_vies"]),
                    message="Verdict déjà connu, encore dans sa durée de validité.")

        # 3. Appel frais
        rep = client.verifier(numero)
        repository.enregistrer(conn, rep, "api")

    detail = DetailVies(user_error=rep.user_error, nom=rep.nom, adresse=rep.adresse,
                        date_requete_vies=rep.date_requete_vies)
    if rep.statut != INDETERMINE:
        return ReponseVerification(
            numero_saisi=numero_saisi, numero_normalise=numero, verdict=rep.statut,
            facturable_ht=rep.statut == VALIDE, origine="vies", verifie_le=maintenant,
            age_secondes=0, ttl_secondes=_ttl_s(rep.statut), motif=f"VIES:{rep.user_error}",
            detail_vies=detail,
            message="Réponse fraîche de VIES." if rep.statut == VALIDE
            else "VIES déclare ce numéro non valide : facturer TTC.")

    # 4. VIES n'a pas pu trancher
    dernier = None
    if connu and connu["dernier_statut_definitif"]:
        dernier = DernierVerdictConnu(verdict=connu["dernier_statut_definitif"],
                                      verifie_le=connu["derniere_reponse_definitive_le"],
                                      age_secondes=_age_s(connu["derniere_reponse_definitive_le"]))
    return ReponseVerification(
        numero_saisi=numero_saisi, numero_normalise=numero, verdict=INDETERMINE,
        facturable_ht=False, origine="vies_indisponible",
        verifie_le=dernier.verifie_le if dernier else None,
        age_secondes=dernier.age_secondes if dernier else None, ttl_secondes=None,
        motif=f"VIES:{rep.user_error}", detail_vies=detail, dernier_verdict_connu=dernier,
        message="VIES n'a pas pu trancher (service ou administration nationale indisponible). "
                "Ce n'est PAS une invalidité : réessayer plus tard ; en attendant, ne pas facturer hors taxe.")
