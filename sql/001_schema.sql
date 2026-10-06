-- Schéma du référentiel TVA Meridian Distribution

CREATE TABLE IF NOT EXISTS ligne_source (
    -- Reçu (tel que dans le fichier)
    id_source           INTEGER PRIMARY KEY,          -- colonne "id" du fichier : clé de rechargement
    raison_sociale      TEXT,
    pays_declare        TEXT,
    numero_brut         TEXT,                          -- valeur saisie, espaces compris
    date_saisie         DATE,
    source_saisie       TEXT,
    -- Déduit (validation structurelle)
    pays_normalise      TEXT,
    numero_normalise    TEXT,
    corrections         TEXT[] NOT NULL DEFAULT '{}',
    verdict_structurel  TEXT NOT NULL CHECK (verdict_structurel IN ('VALIDE', 'INVALIDE')),
    motif_structurel    TEXT NOT NULL,
    charge_le           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_ligne_source_numero ON ligne_source (numero_normalise);
CREATE INDEX IF NOT EXISTS ix_ligne_source_motif  ON ligne_source (motif_structurel);


CREATE TABLE IF NOT EXISTS campagne (
    id              SERIAL PRIMARY KEY,
    demarree_le     TIMESTAMPTZ NOT NULL DEFAULT now(),
    terminee_le     TIMESTAMPTZ,
    mode            TEXT NOT NULL,
    taille_demandee INTEGER,
    nb_cibles       INTEGER,
    nb_traites      INTEGER NOT NULL DEFAULT 0,
    statut          TEXT NOT NULL DEFAULT 'EN_COURS'
);


CREATE TABLE IF NOT EXISTS verification_vies (
    numero_normalise    TEXT PRIMARY KEY,
    pays                TEXT NOT NULL,
    statut              TEXT NOT NULL CHECK (statut IN ('VALIDE', 'INVALIDE', 'INDETERMINE')),
    user_error          TEXT,           -- code VIES brut : VALID, INVALID, MS_UNAVAILABLE, TIMEOUT...
    is_valid_vies       BOOLEAN,
    nom                 TEXT,    
    adresse             TEXT,
    date_requete_vies   TIMESTAMPTZ, 
    verifie_le          TIMESTAMPTZ NOT NULL, 
    derniere_reponse_definitive_le TIMESTAMPTZ,
    dernier_statut_definitif TEXT CHECK (dernier_statut_definitif IN ('VALIDE', 'INVALIDE')),
    nb_tentatives       INTEGER NOT NULL DEFAULT 0,
    campagne_id         INTEGER REFERENCES campagne(id)
);


CREATE TABLE IF NOT EXISTS appel_vies (
    id              BIGSERIAL PRIMARY KEY,
    numero_normalise TEXT NOT NULL,
    appele_le       TIMESTAMPTZ NOT NULL DEFAULT now(),
    origine         TEXT NOT NULL,  
    campagne_id     INTEGER REFERENCES campagne(id),
    http_status     INTEGER,
    user_error      TEXT,
    statut          TEXT NOT NULL,
    latence_ms      INTEGER,
    erreur          TEXT
);

CREATE INDEX IF NOT EXISTS ix_appel_vies_numero ON appel_vies (numero_normalise);


-- Vue de synthèse : statut final de chaque ligne, en trois états.
CREATE OR REPLACE VIEW v_statut_ligne AS
SELECT
    l.id_source,
    l.raison_sociale,
    l.pays_declare,
    l.numero_brut,
    l.numero_normalise,
    l.verdict_structurel,
    l.motif_structurel,
    v.statut          AS statut_vies,
    v.user_error,
    v.verifie_le,

    CASE
        WHEN l.verdict_structurel = 'INVALIDE'      THEN 'INVALIDE'
        WHEN v.dernier_statut_definitif IS NOT NULL THEN v.dernier_statut_definitif
        ELSE 'INDETERMINE'
    END AS statut_final,
    CASE
        WHEN l.verdict_structurel = 'INVALIDE'      THEN 'STRUCTUREL:' || l.motif_structurel
        WHEN v.numero_normalise IS NULL             THEN 'NON_VERIFIE'
        WHEN v.dernier_statut_definitif = 'VALIDE'  THEN 'VIES:VALID'
        WHEN v.dernier_statut_definitif = 'INVALIDE' THEN 'VIES:INVALID'
        ELSE 'VIES:' || COALESCE(v.user_error, 'ERREUR')
    END AS motif_final,
    v.derniere_reponse_definitive_le
FROM ligne_source l
LEFT JOIN verification_vies v ON v.numero_normalise = l.numero_normalise;
