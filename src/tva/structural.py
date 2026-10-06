"""Normalisation et validation *structurelle* des numéros de TVA intracommunautaire.

Ce module répond à une seule question : « ce numéro a-t-il la forme d'un numéro
de TVA de son pays, et sa clé de contrôle est-elle cohérente ? »

Il ne répond PAS à la question métier : « ce numéro est-il attribué à une
entreprise réellement assujettie aujourd'hui ? ». Un numéro inventé mais dont
la clé tombe juste est « structurellement valide ». Seul VIES peut trancher.

Chaque verdict est accompagné d'un motif (voir ``Motif``) pour que les rejets
puissent être comptés et traités explicitement, famille par famille.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class Motif(str, Enum):
    """Motifs renvoyés par la validation structurelle."""

    OK = "OK"                                    # format + clé vérifiés
    OK_CLE_NON_CONTROLABLE = "OK_CLE_NON_CONTROLABLE"  # format OK, clé non calculable
    VIDE = "VIDE"                                # aucune valeur exploitable
    PAYS_INCONNU = "PAYS_INCONNU"                # préfixe qui n'est pas un code pays
    PAYS_HORS_UE = "PAYS_HORS_UE"                # Royaume-Uni (GB / UK) : hors VIES depuis le Brexit
    PAYS_NON_SUPPORTE = "PAYS_NON_SUPPORTE"      # pays UE, mais pas dans le périmètre du module
    CONFLIT_PAYS = "CONFLIT_PAYS"                # préfixe saisi ≠ pays déclaré de la fiche client
    FORMAT_INVALIDE = "FORMAT_INVALIDE"          # longueur ou caractères incompatibles avec le pays
    CLE_INVALIDE = "CLE_INVALIDE"                # format OK mais clé de contrôle fausse


class Verdict(str, Enum):
    VALIDE = "VALIDE"
    INVALIDE = "INVALIDE"


# Valeurs qui, une fois nettoyées, signifient « rien n'a été saisi ».
VALEURS_VIDES = {"", "NA", "NULL", "NONE", "NAN", "NC", "ND"}

# Caractères de bruit de saisie retirés à la normalisation.
BRUIT = re.compile(r"[\s.\-/_,]")

PAYS_SUPPORTES = {"BE", "DK", "FI", "FR", "IT", "LU", "NL", "PL", "PT", "SE"}
PAYS_UE = PAYS_SUPPORTES | {
    "AT", "BG", "CY", "CZ", "DE", "EE", "EL", "ES", "HR", "HU", "IE", "LT",
    "LV", "MT", "RO", "SI", "SK", "XI",
}
PAYS_HORS_UE = {"GB", "UK"}


@dataclass
class Resultat:
    """Résultat de la normalisation + validation d'un numéro."""

    brut: str | None
    pays: str | None          # code pays retenu (préfixe saisi, sinon pays déclaré)
    corps: str | None         # partie nationale, sans préfixe
    normalise: str | None     # forme canonique PAYS+CORPS, clé de dédoublonnage et d'appel VIES
    verdict: Verdict
    motif: Motif
    corrections: list[str] = field(default_factory=list)  # bruit retiré, pour traçabilité

# Normalisation

def normaliser(brut: str | None, pays_declare: str | None = None) -> tuple[str | None, str | None, list[str]]:
    """Nettoie une saisie et retourne (pays, corps, corrections).

    Corrections appliquées (= « bruit de saisie », jamais une modification de chiffre) :
      - espaces de début/fin et espaces internes ;
      - séparateurs ``. - / _ ,`` ;
      - passage en majuscules ;
      - ajout du préfixe pays à partir du pays déclaré quand il manque.

    Décision volontaire : on NE corrige PAS les lettres glissées dans les
    chiffres (O pour 0, etc.). Deviner un chiffre sur un numéro qui conditionne
    une facture hors taxe serait inventer une donnée.
    """
    corrections: list[str] = []
    if brut is None:
        return None, None, corrections

    valeur = brut
    if valeur != valeur.strip():
        corrections.append("espaces_bords")
    valeur = valeur.strip()
    if BRUIT.search(valeur):
        corrections.append("separateurs")
        valeur = BRUIT.sub("", valeur)
    if valeur != valeur.upper():
        corrections.append("casse")
        valeur = valeur.upper()

    if valeur in VALEURS_VIDES:
        return None, None, corrections

    pays_declare = (pays_declare or "").strip().upper() or None
    if re.match(r"^[A-Z]{2}", valeur):
        pays, corps = valeur[:2], valeur[2:]
    else:
        pays, corps = pays_declare, valeur
        corrections.append("prefixe_ajoute")

    if pays == "BE" and re.fullmatch(r"\d{9}", corps):
        corps = "0" + corps
        corrections.append("be_zero_ajoute")
    return pays, corps, corrections


# Clés de contrôle par pays — chaque fonction reçoit le corps (sans préfixe)
# et retourne None si OK, sinon le motif d'échec.

def _poids(chiffres: str, poids: list[int]) -> int:
    return sum(int(c) * p for c, p in zip(chiffres, poids))


def _luhn_ok(chiffres: str) -> bool:
    total = 0
    for i, c in enumerate(reversed(chiffres)):
        d = int(c)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _be(c: str) -> Motif | None:
    # 10 chiffres, commence par 0 ou 1 ; 97 - (8 premiers mod 97) = 2 derniers
    if not re.fullmatch(r"[01]\d{9}", c):
        return Motif.FORMAT_INVALIDE
    return None if 97 - int(c[:8]) % 97 == int(c[8:]) else Motif.CLE_INVALIDE


def _dk(c: str) -> Motif | None:
    if not re.fullmatch(r"[1-9]\d{7}", c):
        return Motif.FORMAT_INVALIDE
    return None if _poids(c, [2, 7, 6, 5, 4, 3, 2, 1]) % 11 == 0 else Motif.CLE_INVALIDE


def _fi(c: str) -> Motif | None:
    if not re.fullmatch(r"\d{8}", c):
        return Motif.FORMAT_INVALIDE
    r = _poids(c[:7], [7, 9, 10, 5, 8, 4, 2]) % 11
    if r == 1:
        return Motif.CLE_INVALIDE
    cle = 0 if r == 0 else 11 - r
    return None if cle == int(c[7]) else Motif.CLE_INVALIDE


def _fr(c: str) -> Motif | None:
    if not re.fullmatch(r"[0-9A-HJ-NP-Z]{2}\d{9}", c):
        return Motif.FORMAT_INVALIDE
    if not c[:2].isdigit():
        return Motif.OK_CLE_NON_CONTROLABLE
    siren = c[2:]
    return None if (12 + 3 * (int(siren) % 97)) % 97 == int(c[:2]) else Motif.CLE_INVALIDE


def _it(c: str) -> Motif | None:

    if not re.fullmatch(r"\d{11}", c):
        return Motif.FORMAT_INVALIDE
    return None if _luhn_ok(c) else Motif.CLE_INVALIDE


def _lu(c: str) -> Motif | None:
    if not re.fullmatch(r"\d{8}", c):
        return Motif.FORMAT_INVALIDE
    return None if int(c[:6]) % 89 == int(c[6:]) else Motif.CLE_INVALIDE


def _nl(c: str) -> Motif | None:

    if not re.fullmatch(r"\d{9}B\d{2}", c):
        return Motif.FORMAT_INVALIDE
    if _poids(c[:9], [9, 8, 7, 6, 5, 4, 3, 2, -1]) % 11 == 0:
        return None
    converti = "".join(str(ord(x) - 55) if x.isalpha() else x for x in "NL" + c)
    return None if int(converti) % 97 == 1 else Motif.CLE_INVALIDE


def _pl(c: str) -> Motif | None:
    if not re.fullmatch(r"\d{10}", c):
        return Motif.FORMAT_INVALIDE
    r = _poids(c[:9], [6, 5, 7, 2, 3, 4, 5, 6, 7]) % 11
    return None if r != 10 and r == int(c[9]) else Motif.CLE_INVALIDE


def _pt(c: str) -> Motif | None:
    if not re.fullmatch(r"[1-9]\d{8}", c):
        return Motif.FORMAT_INVALIDE
    r = 11 - _poids(c[:8], [9, 8, 7, 6, 5, 4, 3, 2]) % 11
    cle = 0 if r >= 10 else r
    return None if cle == int(c[8]) else Motif.CLE_INVALIDE


def _se(c: str) -> Motif | None:
    # 10 chiffres (Luhn) + suffixe '01' à '94'
    if not re.fullmatch(r"\d{10}\d{2}", c) or not (1 <= int(c[10:]) <= 94):
        return Motif.FORMAT_INVALIDE
    return None if _luhn_ok(c[:10]) else Motif.CLE_INVALIDE


CONTROLES = {"BE": _be, "DK": _dk, "FI": _fi, "FR": _fr, "IT": _it,
             "LU": _lu, "NL": _nl, "PL": _pl, "PT": _pt, "SE": _se}


# Point d'entrée

def valider(brut: str | None, pays_declare: str | None = None) -> Resultat:
    """Normalise puis valide structurellement un numéro."""
    pays, corps, corrections = normaliser(brut, pays_declare)

    def res(verdict: Verdict, motif: Motif) -> Resultat:
        normalise = f"{pays}{corps}" if pays and corps else None
        return Resultat(brut, pays, corps, normalise, verdict, motif, corrections)

    if not corps:
        return res(Verdict.INVALIDE, Motif.VIDE)
    if pays in PAYS_HORS_UE:
        return res(Verdict.INVALIDE, Motif.PAYS_HORS_UE)
    if pays not in PAYS_UE:
        return res(Verdict.INVALIDE, Motif.PAYS_INCONNU)
    if pays not in PAYS_SUPPORTES:
        return res(Verdict.INVALIDE, Motif.PAYS_NON_SUPPORTE)
    pd = (pays_declare or "").strip().upper()
    if pd and pd != pays and pd in PAYS_UE:
        return res(Verdict.INVALIDE, Motif.CONFLIT_PAYS)

    echec = CONTROLES[pays](corps)
    if echec is None:
        return res(Verdict.VALIDE, Motif.OK)
    if echec is Motif.OK_CLE_NON_CONTROLABLE:
        return res(Verdict.VALIDE, echec)
    return res(Verdict.INVALIDE, echec)
