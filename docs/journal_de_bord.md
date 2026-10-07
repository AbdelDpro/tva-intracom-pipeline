# Journal de bord

Format : **Blocage** → **Tentatives** → **Résolution**.

## J1 — Cadrage, réduction, chargement

### Le module de validation structurelle n'était pas dans le kit
- **Blocage** : le kit récupéré ne contenait que le CSV, le XLSX et le `docker-compose.yml`.
- **Tentatives** : recherche dans les ressources de la plateforme, sans succès.
- **Résolution** : écriture du module (`src/tva/structural.py`) pour les 10 pays du jeu, avec
  la même interface (verdict + motif). Chaque algorithme est testé sur un numéro réel par pays
  (`tests/test_structural.py`). Si le module officiel est fourni plus tard, il se branche à la
  place de `valider()` sans toucher au reste.

### Les vides n'ont pas une seule forme
- **Blocage** : un premier comptage avec pandas donnait moins de vides qu'à l'œil.
- **Tentatives** : `isna()` ne voit que ce que pandas a converti ; `'-'`, `' '` et `'NU.LL'` passaient.
- **Résolution** : 6 formes identifiées (`''`, `' '`, `'-'`, `'N/A'`, `'null'`, `'NU.LL'`) ;
  lecture du CSV en texte brut et détection du vide **après** nettoyage.

### Trop de clés françaises fausses
- **Blocage** : première version, 742 numéros FR sur 814 rejetés pour clé invalide.
- **Tentatives** : vérification de la formule de clé TVA `(12 + 3 × (SIREN mod 97)) mod 97` — correcte.
  En plus, je contrôlais la clé de Luhn du SIREN.
- **Résolution** : le contrôle Luhn du SIREN ne fait pas partie de la validation du numéro de
  TVA ; retiré. Il reste 259 FR invalides (format + clé TVA). Leçon : chaque règle ajoutée au
  contrôle structurel déplace des centaines de lignes, il faut savoir la justifier.

### Belgique à 9 chiffres, Danemark commençant par 0
- **Blocage** : des numéros BE à 9 chiffres et DK commençant par `0`.
- **Résolution** : BE 9 chiffres = ancien format, complété par un `0` (règle officielle) — mais
  seuls 2 sur 51 deviennent valides : ce sont surtout des numéros tronqués. DK : un numéro CVR
  ne commence pas par 0, rejet maintenu.

### Lettres au milieu des chiffres
- **Blocage** : 103 numéros avec `O` au lieu de `0` : les corriger aurait « sauvé » des lignes.
- **Résolution** : refusé. On ne devine pas un chiffre sur un numéro qui conditionne une facture
  hors taxe. Rejet `FORMAT_INVALIDE`, décision documentée dans `exploration_donnees.md`.

### Rechargement sans doublon
- **Résolution** : clé primaire = `id` du fichier, `INSERT … ON CONFLICT DO UPDATE`. Deux
  chargements successifs → toujours 10 000 lignes (test `test_rechargement_sans_doublon`).

### Bilan J1
Répartition structurelle : 6 569 valides, 3 431 invalides. 3 739 appels VIES évités sur 10 000
(filtre structurel + dédoublonnage), soit −37,4 %.

## J2 — VIES, campagne, API

### Lecture des réponses VIES en entier
- Trois appels à la main sur l'API REST (`/ms/{pays}/vat/{numero}`) :
  - `FR27552032534` (Danone) → `isValid: true`, `userError: VALID`, nom et adresse renseignés ;
  - `FR28552032534` (clé fausse) → `isValid: false`, `userError: INVALID`, nom `---` ;
  - `DK73224645` (numéro du jeu, clé fausse) → `INVALID`.
- Champs notés : `requestDate`, `userError`, `name`/`address` (`---` = non communiqué, certains
  États ne publient jamais le nom), `viesApproximate` (rapprochement, non utilisé ici).
- Constat : sur un appel, `requestDate` était antérieur de plusieurs semaines à l'heure de
  l'appel (réponse servie depuis un cache intermédiaire). → On horodate **nous-mêmes** chaque
  appel (`verifie_le`) et on garde `requestDate` à côté.

### La réponse qui contredit l'attente
- **Blocage** : `isValid` n'est pas la réponse à la question. Quand l'administration nationale
  ne répond pas, VIES renvoie `isValid: false`… avec `userError: MS_UNAVAILABLE` (même chose pour
  `TIMEOUT`, `MS_MAX_CONCURRENT_REQ`, etc.).
- **Tentatives** : une première version basée sur `isValid` aurait compté chaque panne comme
  une invalidité — exactement l'erreur interdite par le brief.
- **Résolution** : verdict dérivé de `userError` uniquement ; `MS_UNAVAILABLE`, `TIMEOUT`,
  `*_MAX_CONCURRENT_REQ`, erreurs HTTP/réseau → INDETERMINE. Garde-fou : si `isValid` et
  `userError` se contredisent → INDETERMINE. Testé (`test_ms_unavailable_avec_isvalid_false_est_indetermine`).

### Ne pas tester sur le vrai service
- **Blocage** : démontrer interruption, reprise et indisponibilité en martelant VIES n'est ni
  correct ni reproductible.
- **Résolution** : faux VIES (`tests/mock_vies.py`) au format réel, avec ~10 % de `MS_UNAVAILABLE`,
  et `httpx.MockTransport` dans les tests. La variable `VIES_BASE_URL` bascule de l'un à l'autre.

### Reprise après interruption
- **Résolution** : commit après chaque numéro ; la campagne ne cible que les numéros sans
  réponse définitive récente ; échantillon tiré de façon stable (ordre `md5`) pour que la
  relance reprenne le **même** échantillon. Ctrl+C (ou `docker stop`) → campagne marquée
  `INTERROMPUE`. Démontré : interruption après 13 puis 4 numéros, relance → 183 restants, 0 au
  passage suivant (test `test_campagne_echantillon_et_reprise`).

### Une panne qui efface un verdict
- **Blocage** : avec une seule colonne `statut`, un `MS_UNAVAILABLE` sur un numéro déjà VALIDE
  aurait écrasé ce qu'on savait.
- **Résolution** : colonnes `dernier_statut_definitif` / `derniere_reponse_definitive_le`,
  mises à jour uniquement par une réponse VALIDE/INVALIDE ; la vue `v_statut_ligne` s'appuie dessus.

### Contrat de l'API
- Question : que répondre quand VIES est injoignable et qu'on n'a rien en mémoire ?
- **Résolution** : `200` avec `verdict: INDETERMINE`, `origine: vies_indisponible`,
  `facturable_ht: false`. Pas d'erreur 5xx : l'appelant reçoit une réponse exploitable et un
  message explicite. Si un verdict existe en mémoire, il est joint avec sa date mais n'autorise
  pas la facture HT.

### Tout se lance en une commande
- `docker compose up -d --build` : base, chargement (service `init`, une fois), puis API.
  Les commandes ponctuelles passent par le service `cli` (`docker compose run --rm cli …`).
