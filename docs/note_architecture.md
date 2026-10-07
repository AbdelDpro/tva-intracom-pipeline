# Note d'architecture

## 1. Réduction des appels à VIES

VIES est un service public partagé, sans engagement de débit, qui renvoie des erreurs de
surcharge (`MS_MAX_CONCURRENT_REQ`, `GLOBAL_MAX_CONCURRENT_REQ`) quand on le sollicite trop.
Il faut le temporiser (1 appel/s par défaut) : le coût d'une campagne est donc
**nombre d'appels × (latence + temporisation)**. Mesure : `docker compose run --rm cli mesurer`.
Hypothèse de calcul ci-dessous : ~0,5 s de latence, soit ~1,5 s par numéro avec la
temporisation (à remplacer par la valeur mesurée).

| Étape (ordre imposé) | Appels restants | Évités | Durée estimée à 1,5 s/appel |
|---|---|---|---|
| Naïf : une ligne = un appel | 10 000 | — | ~4 h 10 |
| 1. Normalisation | 10 000 | 0 (mais 2 530 lignes sauvées d'un faux rejet) | |
| 2. Filtre structurel (clé, format, pays, vide) | 6 569 | 3 431 | |
| 3. Dédoublonnage sur le numéro normalisé | **6 261** | 308 | ~2 h 35 |
| **Total** | | **3 739 (−37,4 %)** | |

Puis, dans la durée : **le cache**. Une réponse définitive est stockée (`verification_vies`)
avec sa date ; une campagne relancée ne réinterroge que les numéros jamais tranchés ou dont la
réponse a plus de 30 jours, et l'API ne rappelle VIES que si le verdict a plus de 24 h. Un mode
échantillon (`--echantillon 200`, tirage stable par hachage, ~5 min) permet de tout démontrer
sans lancer les 2 h 35.

Un **coupe-circuit par pays** arrête d'interroger un État qui renvoie `MS_UNAVAILABLE` trois
fois de suite : ses numéros restent INDETERMINE et seront repris au passage suivant, au lieu de
consommer appels et nouvelles tentatives pour rien.

## 2. Durée de validité d'un verdict

La règle fiscale porte sur la validité **au moment de la facturation** ; un numéro valide peut
être radié du jour au lendemain (cessation, fraude carrousel). Un verdict vieux de six mois
n'apporte donc aucune protection lors d'un contrôle. Deux horizons :

- **API de facturation : 24 h** (`TTL_VALIDE_H`, `TTL_INVALIDE_H`). Au-delà, l'API rappelle VIES
  avant de répondre. 24 h couvre une série de factures du même jour pour un client sans
  rappeler VIES à chaque ligne, tout en garantissant une vérification datée de la veille au
  plus. Un INVALIDE n'est pas gardé plus longtemps : un client peut régulariser son inscription.
- **Campagne sur le référentiel : 30 jours** (`TTL_CAMPAGNE_J`) — c'est un état des lieux, pas
  une autorisation de facturer.

Chaque réponse de l'API porte `verifie_le`, `age_secondes` et `ttl_secondes` : l'appelant voit
toujours de quand date l'information. On conserve aussi le `requestDate` de VIES et chaque
appel dans `appel_vies`, ce qui constitue une **preuve datée** en cas de contrôle.

## 3. Ce que l'on fait des indéterminés

« Indéterminé » = VIES **n'a pas pu répondre** : administration nationale indisponible
(`MS_UNAVAILABLE`), délai dépassé, surcharge, erreur réseau ou HTTP, ou réponse incohérente.
Le piège : VIES renvoie alors `isValid: false`. Se fier à ce champ enregistrerait une panne
comme une invalidité. Le verdict est donc dérivé de `userError` ; seul `INVALID` (ou
`INVALID_INPUT`) donne INVALIDE.

- En base : statut `INDETERMINE` avec le code VIES ; une panne **n'efface jamais** un verdict
  définitif déjà obtenu (colonnes `dernier_statut_definitif` / `derniere_reponse_definitive_le`).
- Dans la campagne : nouvelles tentatives avec attente croissante (2 s, 4 s), puis le numéro est
  repris automatiquement à la campagne suivante.
- Dans l'API : `verdict = INDETERMINE`, `origine = vies_indisponible`, `facturable_ht = false`,
  avec le dernier verdict connu et sa date **pour information**. Décision métier proposée :
  facturer TTC (la TVA pourra être régularisée par avoir une fois le numéro confirmé) ou
  différer la facture — jamais émettre hors taxe sur la foi d'une absence de réponse.
- Dans le rapport : comptés à part, avec leur code, par pays, pour que la direction financière
  sache ce qui reste à trancher et pourquoi.
