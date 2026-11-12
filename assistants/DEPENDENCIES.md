# Section `dependencies` du paquet d'assistant

Objets externes dont l'assistant a besoin (documents RAG, index vectoriels, bases de données, secrets). Le migrateur :

1. **contrôle** la déclaration ;
2. **repère** dans le code des Actions (sans l'exécuter) les accès aux fichiers, bases vectorielles (FAISS, Chroma,
   pgvector, OpenSearch…), embeddings, bases de données (psycopg2, oracledb, pyodbc, SQLAlchemy…), tables citées en SQL,
   stockages objet et variables d'environnement — **tout accès détecté et non déclaré bloque la migration** ;
3. calcule le **plan** : objet Databricks cible, existence vérifiée, action prévue, responsable, droits ;
4. génère l'agent avec les noms lus dans `model_config.yml` (clé `dependencies`, écrite par le migrateur) ;
5. au déploiement : recalcule le plan, crée **uniquement** les Volumes vides autorisés (`create_if_missing: true`),
   refuse de déployer s'il manque un objet, déclare les ressources de l'agent (accès automatique de l'endpoint).

Le migrateur ne copie **aucune donnée**, ne crée ni index, ni table, ni connexion, ni secret : ces opérations relèvent
d'un pipeline ou d'un administrateur, après validation du Data Owner.

## Exemple (assistant RAG)

```yaml
dependencies:
  sql_warehouse_id: "<id de l'entrepôt SQL>"      # obligatoire si une base copie_uc ou federation
  documents:
    - name: corpus_referentiel
      source: "/data/rag"                         # emplacement HORIZON (information)
      volume: dataops_dev.knowledge.horizon_rag_docs
      formats: [pdf, docx]
      create_if_missing: true                     # seul objet que le Job peut créer (Volume vide)
  vector_indexes:
    - name: index_referentiel
      from: corpus_referentiel
      index: dataops_dev.knowledge.horizon_rag_index
      chunks_table: dataops_dev.knowledge.horizon_rag_chunks
      vector_search_endpoint: <endpoint Vector Search>
      embedding_endpoint: databricks-gte-large-en
      columns: [content, source]                  # colonnes renvoyées au LLM
      top_k: 5
  databases:
    - name: referentiel_gares
      engine: postgres                            # postgres | oracle | sqlserver | mysql | autre
      strategy: federation                        # federation (données dans la source) | copie_uc
      connection: horizon_pg                      # federation : connexion Unity Catalog
      foreign_catalog: horizon_pg_cat             # federation : catalogue étranger
      tables: [ref.gares, ref.lignes]             # federation : <schéma>.<table> de la source
      access: READ
      secret: {scope: horizon_rag, key: db_password}   # utilisé par la connexion, jamais par l'agent
```

En `copie_uc`, remplacer `connection` et `foreign_catalog` par `uc_schema: <catalogue>.<schéma>` : les tables sont
attendues sous `<uc_schema>.<nom de la table>` (copie à réaliser par un pipeline). La stratégie `lakebase` est prévue
mais pas encore générée.

## Correspondances

| HORIZON | Databricks | Créé par le migrateur |
| --- | --- | --- |
| Fichiers sources | Volume Unity Catalog | Volume vide si `create_if_missing` ; copie des fichiers : non |
| Segments | Table Delta (pipeline d'indexation) | Non |
| Base vectorielle | Index Vector Search (ressource de l'agent) | Non |
| Embeddings | Endpoint d'embedding existant (ressource) | Non |
| Base de données | Tables étrangères (fédération) ou copiées + entrepôt SQL (ressources) | Non |
| Secrets | Portée de secrets (connexion Unity Catalog) | Non |
