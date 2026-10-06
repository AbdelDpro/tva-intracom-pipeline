"""Tests du module de validation structurelle : ce qu'il garantit, et ce qu'il ne garantit pas."""

import pytest

from tva.structural import Motif, Verdict, valider


@pytest.mark.parametrize("brut", [
    "FR27552032534", "fr27552032534", "  FR27552032534 ", "FR 2755 2032534",
    "FR-27552032534", "FR.27552032534", "FR27/552032534",
])
def test_bruit_de_saisie_n_invalide_pas(brut):
    r = valider(brut, "FR")
    assert r.verdict is Verdict.VALIDE
    assert r.normalise == "FR27552032534"


def test_prefixe_ajoute_depuis_pays_declare():
    r = valider("27552032534", "FR")
    assert r.normalise == "FR27552032534"
    assert "prefixe_ajoute" in r.corrections


@pytest.mark.parametrize("brut", ["", " ", "-", "N/A", "null", "NU.LL", None])
def test_formes_du_vide(brut):
    assert valider(brut, "FR").motif is Motif.VIDE


def test_cle_fausse():
    assert valider("FR28552032534", "FR").motif is Motif.CLE_INVALIDE


def test_lettre_dans_les_chiffres_non_corrigee():
    assert valider("FR27552O32534", "FR").motif is Motif.FORMAT_INVALIDE


@pytest.mark.parametrize("brut,motif", [
    ("GB123456789", Motif.PAYS_HORS_UE), ("UK123456789", Motif.PAYS_HORS_UE),
    ("ZZ23140153", Motif.PAYS_INCONNU), ("DE123456789", Motif.PAYS_NON_SUPPORTE),
])
def test_pays(brut, motif):
    assert valider(brut, None).motif is motif


def test_conflit_pays():
    assert valider("FR27552032534", "BE").motif is Motif.CONFLIT_PAYS


def test_france_cle_alphanumerique():
    r = valider("FRH3842670445", "FR")
    assert r.verdict is Verdict.VALIDE and r.motif is Motif.OK_CLE_NON_CONTROLABLE


@pytest.mark.parametrize("num", [
    "BE0403170701", "DK13585628", "FI20774740", "IT00743110157", "LU15027442",
    "NL004495445B01", "PL5260250995", "PT501964843", "SE556703748501",
])
def test_numeros_reels_par_pays(num):
    assert valider(num, num[:2]).verdict is Verdict.VALIDE, num


def test_be_ancien_format_9_chiffres():
    r = valider("BE403170701", "BE")
    assert r.normalise == "BE0403170701" and r.verdict is Verdict.VALIDE


def test_structurellement_valide_ne_veut_pas_dire_existant():
    assert valider("DK61530843", "DK").verdict is Verdict.VALIDE
