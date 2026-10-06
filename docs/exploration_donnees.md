# Phase 1 — Exploration du jeu et traitement des motifs de rejet

Jeu : `data/numeros_tva.csv` (identique au `.xlsx`), 10 000 lignes, colonnes
`id, raison_sociale, pays_declare, numero_tva, date_saisie, source_saisie`.
Saisies entre 2024 et 2025, cinq canaux (`crm`, `reprise_erp`, `portail_client`,
`saisie_manuelle`, `import_fournisseur`), ~2 000 lignes chacun.

## Ce que montre le jeu avant toute transformation

| Constat | Chiffre |
|---|---|
| Pays déclarés distincts | 15 : les 10 pays UE du module (BE, DK, FI, FR, IT, LU, NL, PL, PT, SE) + GB, UK, ZZ, QQ, XX |
| Formats différents pour un même pays | 25 à 31 « gabarits » par pays (chiffres/lettres/séparateurs) |
| Lignes avec bruit de saisie (espaces, `.`, `-`, `/`) | 1 861 (18,6 %) |
| Lignes saisies en minuscules | 480 |
| Numéros sans préfixe pays | 532 |
| Valeurs vides | 261, sous **6 formes** : `''` (60), `' '` (59), `'-'` (55), `'N/A'` (48), `'null'` (38), `'NU.LL'` (1) |
| Lettres glissées dans la partie chiffrée | 532 lignes, dont 103 avec un `O` à la place d'un `0` |
| Doublons exacts sur la valeur brute | 135 lignes en trop |
| Doublons après normalisation | 438 lignes en trop (396 numéros) |

Piège de lecture : avec `pandas.read_csv` par défaut, `'null'` et `'N/A'` deviennent `NaN`
et se mélangent aux vrais vides, et les zéros de tête peuvent disparaître si une colonne est
lue en nombre. Le chargeur lit donc le CSV **en texte brut** (module `csv`).

## Normalisation retenue (= bruit, jamais un chiffre)

1. retrait des espaces (bords et intérieur) ;
2. retrait des séparateurs `. - / _ ,` ;
3. passage en majuscules ;
4. si le numéro ne commence pas par deux lettres, ajout du préfixe du **pays déclaré** ;
5. Belgique : un numéro à 9 chiffres est complété d'un `0` en tête (ancien format officiel).

**Non corrigé volontairement** : une lettre dans la partie chiffrée (ex. `FI17O38139`).
Remplacer `O` par `0` serait deviner une donnée qui conditionne une facture hors taxe ;
le numéro est rejeté et doit être redemandé au client.

Effet : **2 530 lignes** sont structurellement valides grâce à cette normalisation, et ne sont
donc pas comptées comme invalides pour un simple bruit de saisie.

## Ce que garantit le module structurel — et ce qu'il ne garantit pas

Le module (`src/tva/structural.py`) vérifie pour chaque pays la **longueur**, les **caractères
autorisés** et la **clé de contrôle** (mod 97 en BE/FR, mod 11 pondéré en DK/FI/PL/PT/NL,
Luhn en IT/SE, mod 89 en LU, suffixe `01`–`94` en SE, double algorithme mod 11 / mod 97 aux NL).

Un verdict « structurellement valide » garantit seulement que **le numéro pourrait exister** :
il n'a pas de faute de frappe détectable. Il ne dit **rien** de :

- l'attribution réelle du numéro à une entreprise (un numéro inventé dont la clé tombe juste
  passe — une clé à 2 chiffres laisse ~1 chance sur 97 au hasard, une clé mod 11 ~1 sur 11) ;
- l'assujettissement **actuel** (un numéro radié garde une clé correcte) ;
- l'identité du titulaire (le numéro peut appartenir à une autre société).

Or c'est exactement ce que l'administration fiscale contrôle. Seul VIES, qui interroge la
base de chaque État membre, répond à cette question.

## Traitement de chaque motif

| Motif | Lignes | Signification exacte | Décision | Appel VIES ? |
|---|---|---|---|---|
| `OK` | 6 560 | format + clé corrects | à vérifier en ligne | **oui** |
| `OK_CLE_NON_CONTROLABLE` | 9 | France, clé alphanumérique (ancien système) : format correct, clé non calculable | traité comme `OK` | **oui** |
| `CLE_INVALIDE` | 1 365 | format correct, clé fausse : faute de frappe certaine | INVALIDE, à corriger avec le client | non (VIES dirait INVALID) |
| `FORMAT_INVALIDE` | 1 286 | longueur ou caractère impossible (dont les lettres dans les chiffres) | INVALIDE, à corriger | non |
| `PAYS_INCONNU` | 311 | préfixe `ZZ`, `QQ`, `XX` : pas un État membre | INVALIDE | non (VIES refuserait la requête) |
| `PAYS_HORS_UE` | 208 | `GB` et `UK` (`UK` n'est même pas un code ISO) : hors VIES depuis le Brexit | INVALIDE **pour l'autoliquidation intra-UE** ; régime export à traiter à part | non |
| `VIDE` | 261 | aucun numéro saisi | INVALIDE : pas de numéro = pas de facture HT ; à demander au client | non |
| `CONFLIT_PAYS` / `PAYS_NON_SUPPORTE` | 0 | préfixe ≠ pays déclaré / pays UE hors des 10 | prévus, non rencontrés | — |

Décisions qui pèsent sur les chiffres finaux (à savoir défendre) :

- **Normaliser avant de valider** : sans normalisation, 2 530 lignes de plus seraient invalides (+25 points).
- **Ne pas corriger O → 0** : 103 lignes restent invalides ; les corriger les ferait passer en structurellement valides sur une hypothèse.
- **Compter `VIDE` en INVALIDE** plutôt qu'en INDETERMINE : 261 lignes (2,6 points). Choix fait car l'action est la même (pas de facture HT) et que « indéterminé » est réservé à ce que VIES n'a pas pu trancher.
- **Compter GB/UK en INVALIDE** : 208 lignes (2,1 points). Un client britannique peut être parfaitement en règle, mais pas pour une autoliquidation intra-communautaire.
- **Ne pas envoyer les `CLE_INVALIDE` à VIES** : économie de 1 365 appels ; la clé fausse est une preuve suffisante.
