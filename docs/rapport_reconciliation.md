# Rapport de réconciliation — référentiel TVA Meridian Distribution

_Généré le 2026-10-06 08:30 par `python -m tva.cli rapport` — ne pas éditer à la main._

## 1. Réponse à la question

> Parmi nos numéros, lesquels sont valides, lesquels ne le sont pas — et lesquels n'ont pas pu être tranchés ?

| Statut | Lignes | Part | Numéros distincts |
|---|---|---|---|
| INDETERMINE | 6545 | 65.5 % | 6238 |
| INVALIDE | 3454 | 34.5 % | 3062 |
| VALIDE | 1 | 0.0 % | 1 |

Total : **10000 lignes**. Règles : une ligne rejetée au contrôle structurel est INVALIDE sans appel VIES ; une ligne structurellement valide est VALIDE/INVALIDE selon la **dernière réponse définitive** de VIES, et INDETERMINE tant que VIES n'a pas répondu (non encore interrogée, ou État membre indisponible). Seuls les VALIDE autorisent la facturation hors taxe.

### Détail par motif

| Statut | Motif | Lignes |
|---|---|---|
| INDETERMINE | NON_VERIFIE | 6544 |
| INDETERMINE | VIES:TIMEOUT | 1 |
| INVALIDE | STRUCTUREL:CLE_INVALIDE | 1365 |
| INVALIDE | STRUCTUREL:FORMAT_INVALIDE | 1286 |
| INVALIDE | STRUCTUREL:PAYS_INCONNU | 311 |
| INVALIDE | STRUCTUREL:VIDE | 261 |
| INVALIDE | STRUCTUREL:PAYS_HORS_UE | 208 |
| INVALIDE | VIES:INVALID | 23 |
| VALIDE | VIES:VALID | 1 |

## 2. Contrôle structurel (hors ligne)

| Verdict | Motif | Lignes | Part |
|---|---|---|---|
| VALIDE | OK | 6560 | 65.6 % |
| VALIDE | OK_CLE_NON_CONTROLABLE | 9 | 0.1 % |
| INVALIDE | CLE_INVALIDE | 1365 | 13.7 % |
| INVALIDE | FORMAT_INVALIDE | 1286 | 12.9 % |
| INVALIDE | PAYS_INCONNU | 311 | 3.1 % |
| INVALIDE | VIDE | 261 | 2.6 % |
| INVALIDE | PAYS_HORS_UE | 208 | 2.1 % |

### Normalisation : bruit de saisie retiré

| Correction | Lignes concernées | dont structurellement valides |
|---|---|---|
| separateurs | 1383 | 1211 |
| prefixe_ajoute | 532 | 528 |
| casse | 480 | 416 |
| espaces_bords | 478 | 391 |
| be_zero_ajoute | 51 | 2 |

**2530 lignes** sont structurellement valides *grâce* à la normalisation : sans elle, elles auraient été comptées comme invalides pour un simple bruit de saisie.

## 3. Doublons

Définition retenue : **deux lignes sont des doublons si elles portent le même numéro normalisé** (préfixe pays + corps, après retrait du bruit de saisie). Un numéro de TVA identifie un assujetti : le vérifier une fois suffit pour toutes ses lignes. La raison sociale n'entre pas dans la définition (elle varie selon les canaux et n'est pas ce que l'on vérifie).

- Numéros présents sur plusieurs lignes : **396**
- Lignes en trop (doublons) : **438**
- dont doublons visibles sur la valeur brute : 135 ; révélés seulement par la normalisation : 303
- Numéros saisis sous plusieurs formes différentes : 289
- Numéros partagés par des raisons sociales différentes : 0

| Lignes par numéro | Numéros |
|---|---|
| 2 | 365 |
| 3 | 23 |
| 4 | 6 |
| 5 | 1 |
| 6 | 1 |

Exemples de numéros saisis sous 3 formes ou plus :

| Numéro normalisé | Formes saisies | Lignes | Canaux |
|---|---|---|---|
| DK71704289 | 'DK 7170 4289' , 'DK.71704289' , 'DK71704289' | 6 | portail_client, reprise_erp |
| DK91970813 | '  DK91970813 ' , 'DK.91970813' , 'dk91970813' | 4 | crm, portail_client, reprise_erp |
| FI64379216 | 'FI-64379216' , 'FI64379216' , 'fi64379216' | 4 | crm, portail_client, reprise_erp |
| NL785427788B39 | 'NL 7854 27788B39' , 'NL.785427788B39' , 'nl785427788b39' | 4 | crm, reprise_erp |
| PL2944016503 | '  PL2944016503 ' , 'PL 2944 016503' , 'PL.2944016503' , 'PL2944016503' | 4 | portail_client, reprise_erp |

## 4. Réduction des appels VIES

| Étape | Appels nécessaires | Évités |
|---|---|---|
| Approche naïve : un appel par ligne | 10000 | - |
| Après filtre structurel | 6569 | 3431 |
| Après dédoublonnage | 6261 | 308 |
| **Total évité** | | **3739 (37.4 %)** |

## 5. Vérification en ligne (VIES)

Appels effectués : 24 (latence moyenne 3578 ms, max 10070 ms) ; premier appel 2026-10-06 08:26, dernier 2026-10-06 08:30.

### Dernier état connu par numéro

| Statut | Code VIES | Numéros |
|---|---|---|
| INDETERMINE | TIMEOUT | 1 |
| INVALIDE | INVALID | 22 |
| VALIDE | VALID | 1 |

### Fraîcheur des réponses

| Âge du dernier verdict définitif | Numéros |
|---|---|
| < 24 h | 23 |
| jamais tranché | 1 |

### Campagnes

| # | Mode | Échantillon | Cibles | Traités | Statut | Début | Fin |
|---|---|---|---|---|---|---|---|
| 1 | echantillon | 200 | 200 | 24 | INTERROMPUE | 2026-10-06 08:26 | 2026-10-06 08:30 |

## 6. Par pays

| Pays | Lignes | Valides | Invalides | Indéterminés |
|---|---|---|---|---|
| FR | 948 | 0 | 263 | 685 |
| DK | 938 | 0 | 341 | 597 |
| LU | 932 | 0 | 256 | 676 |
| BE | 930 | 1 | 259 | 670 |
| SE | 922 | 0 | 258 | 664 |
| PT | 921 | 0 | 250 | 671 |
| PL | 919 | 0 | 237 | 682 |
| NL | 919 | 0 | 266 | 653 |
| IT | 918 | 0 | 277 | 641 |
| FI | 873 | 0 | 267 | 606 |
| (vide) | 261 | 0 | 261 | 0 |
| ZZ | 115 | 0 | 115 | 0 |
| QQ | 109 | 0 | 109 | 0 |
| UK | 104 | 0 | 104 | 0 |
| GB | 104 | 0 | 104 | 0 |
| XX | 87 | 0 | 87 | 0 |

## 7. Qualité par canal de saisie

| Canal | Lignes | Rejets structurels | Taux de rejet (%) |
|---|---|---|---|
| reprise_erp | 2071 | 747 | 36.1 |
| saisie_manuelle | 1976 | 683 | 34.6 |
| portail_client | 1990 | 687 | 34.5 |
| import_fournisseur | 1944 | 669 | 34.4 |
| crm | 2019 | 645 | 31.9 |
