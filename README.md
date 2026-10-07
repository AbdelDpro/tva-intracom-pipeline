# Meridian Distribution — Validation du référentiel TVA intracommunautaire

Service qui répond, pour les 10 000 numéros de TVA du référentiel client de Meridian Distribution, à la question :

> « Lesquels sont valides, lesquels ne le sont pas — et lesquels n'ont pas pu être tranchés ? »

et API REST que la facturation appelle **avant chaque facture hors taxe** (autoliquidation).

Le projet enchaîne, dans l'ordre imposé :

1. **Normalisation** de la saisie (espaces, séparateurs, casse, préfixe pays manquant) ;
2. **Dédoublonnage** sur le numéro normalisé ;
3. **Contrôle structurel** hors ligne (format + clé de contrôle, 10 pays) ;
4. **Vérification en ligne VIES** des seuls numéros restants, avec trois états (VALIDE / INVALIDE / INDETERMINE), temporisation, journalisation et reprise ;
5. **API** renvoyant verdict, origine et fraîcheur ;
6. **Rapport de réconciliation** régénéré par une commande.

## Documents à lire

| Document | Contenu |
|---|---|
| [docs/rapport_reconciliation.md](docs/rapport_reconciliation.md) | Rapport pour la direction financière (généré) |
| [docs/note_architecture.md](docs/note_architecture.md) | Note d'une page : réduction des appels, durée de validité, indéterminés |
| [docs/exploration_donnees.md](docs/exploration_donnees.md) | Exploration du jeu (phase 1) et traitement de chaque motif de rejet |
| [docs/journal_de_bord.md](docs/journal_de_bord.md) | Blocages, tentatives, résolutions |

## Technologies et justification

| Techno | Pourquoi |
|---|---|
| **Python 3.12** | Langage imposé ; bibliothèque standard suffisante pour lire le CSV (`csv`, sans conversion automatique des types qui ferait perdre zéros de tête et valeurs `null`). |
| **PostgreSQL 16** | Imposé. `INSERT … ON CONFLICT` pour des rechargements idempotents, vue SQL pour le statut final, `TEXT[]` pour tracer les corrections. |
| **psycopg 3** | Pilote PostgreSQL standard, requêtes paramétrées (pas d'injection SQL). |
| **httpx** | Client HTTP avec timeouts explicites et transport simulable (`MockTransport`) pour tester sans appeler le vrai VIES. |
| **FastAPI** | API typée (modèles Pydantic) et documentation **OpenAPI générée automatiquement** sur `/docs`. |
| **Docker Compose** | Toute la pile (base + chargement + API) se lance en une commande, identique sur toutes les machines. |
| **pytest** | Tests unitaires (module structurel, interprétation VIES) et d'intégration (base réelle, reprise, API). |

## Lancement depuis zéro

Prérequis : Git et Docker Desktop (ou Docker Engine + plugin Compose). Toutes les commandes se tapent **dans un terminal, à la racine du dépôt cloné**.

```bash
git clone <url-du-depot> meridian-tva
cd meridian-tva

# 1. Toute la pile : PostgreSQL + chargement des 10 000 lignes + API
docker compose up -d --build
```

Le service `init` charge le CSV puis s'arrête ; l'API démarre ensuite sur <http://localhost:8000> (documentation OpenAPI : <http://localhost:8000/docs>).

```bash
# 2. Répartition par motif structurel
docker compose run --rm cli repartition

# 3. Mesurer la latence de VIES et projeter le coût d'une campagne
docker compose run --rm cli mesurer --n 5

# 4. Campagne VIES en mode échantillon (200 numéros, ~5 min)
docker compose run --rm cli campagne --echantillon 200
#    -> Ctrl+C pour l'interrompre, puis relancer la même commande : elle reprend où elle s'était arrêtée.
#    Campagne complète : docker compose run --rm cli campagne

# 5. Régénérer le rapport de réconciliation (écrit dans docs/rapport_reconciliation.md)
docker compose run --rm cli rapport

# 6. Interroger l'API
curl http://localhost:8000/tva/FR27552032534          # numéro valide
curl http://localhost:8000/tva/FR28552032534          # clé fausse -> rejet structurel
curl "http://localhost:8000/tva/27552032534?pays_declare=FR"   # sans préfixe
curl "http://localhost:8000/tva/FR27552032534?forcer=true"     # ignorer le cache
curl http://localhost:8000/referentiel/repartition

# Recharger le CSV (aucun doublon créé) :
docker compose run --rm cli charger

# Tout arrêter (ajouter -v pour effacer la base)
docker compose down
```

Les journaux sont dans `logs/tva.log` (et à l'écran). Les variables réglables (temporisation, durées de validité, ports) sont listées dans [.env.example](.env.example) : copier ce fichier en `.env` pour les modifier.

### Tests

```bash
# Tests unitaires (sans base)
docker compose run --rm --entrypoint pytest cli -q

# Tests d'intégration : nécessitent une base DÉDIÉE (elle est vidée !)
docker compose exec postgres createdb -U meridian tva_test
docker compose run --rm -e TEST_DATABASE_URL=postgresql://meridian:meridian@postgres:5432/tva_test --entrypoint pytest cli -q
```

Un faux VIES (`tests/mock_vies.py`) reproduit le format réel de l'API, y compris les réponses `MS_UNAVAILABLE`, pour démontrer la reprise et les indéterminés sans solliciter le service public.

### Sans Docker (développement)

```bash
python -m venv .venv && source .venv/bin/activate     # Windows : .venv\Scripts\activate
pip install -r requirements.txt
docker compose up -d postgres                          # la base seule, port 5435
export PYTHONPATH=src                                  # Windows PowerShell : $env:PYTHONPATH="src"
python -m tva.cli charger
uvicorn tva.api:app --reload
```

## Contrat de l'API

`GET /tva/{numero}?pays_declare=FR&forcer=false`

```json
{
  "numero_saisi": "fr 2755 2032534",
  "numero_normalise": "FR27552032534",
  "verdict": "VALIDE",
  "facturable_ht": true,
  "origine": "cache",
  "verifie_le": "2026-10-06T08:12:03Z",
  "age_secondes": 5400,
  "ttl_secondes": 86400,
  "motif": "VIES:VALID",
  "detail_vies": {"user_error": "VALID", "nom": "SA DANONE", "adresse": "59 RUE LA FAYETTE\n75009 PARIS", "date_requete_vies": "..."},
  "dernier_verdict_connu": null,
  "message": "Verdict déjà connu, encore dans sa durée de validité."
}
```

| `origine` | Signification |
|---|---|
| `vies` | Réponse fraîche de VIES, obtenue pendant cet appel |
| `cache` | Verdict VIES déjà connu, plus récent que la durée de validité (24 h par défaut) |
| `controle_structurel` | Rejet hors ligne (format, clé, pays) : certain, aucun appel réseau |
| `vies_indisponible` | VIES n'a pas pu trancher : `verdict = INDETERMINE`, `facturable_ht = false`. Le dernier verdict connu est joint avec sa date, pour information uniquement |

**Seul `facturable_ht = true` autorise une facture hors taxe.**

## Structure du dépôt

```
├── data/                 # jeu fourni (CSV + XLSX, mêmes données)
├── sql/001_schema.sql    # schéma versionné, idempotent
├── src/tva/
│   ├── structural.py     # normalisation + validation structurelle (10 pays)
│   ├── loader.py         # chargement CSV -> PostgreSQL (upsert)
│   ├── vies_client.py    # client VIES, verdict à trois états
│   ├── repository.py     # écriture des verdicts + journal des appels
│   ├── campaign.py       # campagne (échantillon, temporisation, reprise, coupe-circuit)
│   ├── service.py        # logique de décision de l'API (structurel -> cache -> VIES)
│   ├── api.py            # FastAPI
│   ├── report.py         # rapport de réconciliation
│   └── cli.py            # point d'entrée : python -m tva.cli <commande>
├── tests/                # pytest + faux VIES
├── docs/                 # rapport, note d'architecture, exploration, journal de bord
├── Dockerfile
└── docker-compose.yml
```
