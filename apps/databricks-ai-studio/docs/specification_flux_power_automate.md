# Spécification du flux Power Automate « Smart Office » — mode boîte d'échange DISCOVERY

Version 0.1 — 18/11/2026 — Statut : **à valider** (propriétaire du flux, RSSI, Data Office)
Auteur : Solution Architecte DISCOVERY

## 1. Objet

Permettre aux agents de DISCOVERY (App Databricks `databricks-ai-studio`) de consulter la messagerie et d'envoyer
des messages via Power Automate, **sans appel sortant depuis Databricks** (bloqué par la politique réseau serverless).

Principe : DISCOVERY dépose une demande dans une table Delta ; Power Automate la lit, l'exécute, puis écrit la
réponse dans la même table ; l'agent la relit avec l'outil `flux_suivi`.

```
Utilisateur -> Agent DISCOVERY -> [validation si action] -> INSERT flux_demandes (en_attente)
                                                              |
Power Automate (récurrence) <- SELECT en_attente --------------+
   -> UPDATE en_cours -> action Office 365 -> UPDATE terminee | erreur
                                                              |
Agent DISCOVERY -> flux_suivi(demande_id) <- SELECT ----------+
```

Repère DAMA-DMBOK : Data Integration and Interoperability (échange asynchrone par table), Data Security (identité
technique, moindre privilège, contrôle des envois), Metadata Management (traçabilité demande -> utilisateur ->
conversation -> réponse).

## 2. Périmètre

| Flux DISCOVERY (flux_id) | Type | Valeurs fixes injectées par DISCOVERY | Délai d'expiration |
| --- | --- | --- | --- |
| `flux_smart_office_consulter` | lecture | `status = requested`, `requires_confirmation = false` | 15 min |
| `flux_smart_office_envoyer` | action (validée par l'utilisateur dans DISCOVERY avant dépôt) | `status = approved`, `requires_confirmation = true` | 15 min |

Hors périmètre : `flux_essai_discovery_flux` (brouillon d'essai, à supprimer), tout autre flux.

Un seul flux Power Automate peut traiter les deux `flux_id` (aiguillage sur `flux_id`), ou deux flux distincts.
Recommandation : **deux flux distincts** (droits et journalisation séparés lecture / envoi).

## 3. Prérequis

| # | Prérequis | Responsable | État |
| --- | --- | --- | --- |
| P1 | Connecteur Azure Databricks disponible dans l'environnement Power Platform SNCF Réseau | Admin Power Platform | À vérifier |
| P2 | Identité technique Power Automate -> Databricks (principal de service recommandé, pas un compte nominatif) | Admin Databricks | À créer |
| P3 | Droits de cette identité : `USE CATALOG dataops_dev`, `USE SCHEMA dataops_dev.ai_studio`, `SELECT` + `MODIFY` sur **la seule table** `flux_demandes` ; `CAN_USE` sur un entrepôt SQL | Admin Databricks / propriétaire du schéma | À faire |
| P4 | Entrepôt SQL pour le connecteur (proposé : entrepôt serverless de l'App `d0642494ed2912f0`, ou un entrepôt dédié pour isoler les coûts) | Admin Databricks | À arbitrer |
| P5 | Accès réseau Power Platform -> espace Databricks (listes d'accès IP de l'espace éventuelles) | Réseau / RSSI | À vérifier |
| P6 | Connexion Office 365 Outlook du flux : boîte utilisée (voir §8, point de sécurité S1) | Propriétaire du flux / RSSI | À arbitrer |
| P7 | Valeurs de `technology` et `operation` attendues par le flux Smart Office existant | Propriétaire du flux | **Inconnues** |

## 4. Contrat de la table d'échange

Table : `dataops_dev.ai_studio.flux_demandes` — grain : 1 ligne par demande — clé : `demande_id`.

| Colonne | Type | Écrite par | Règle |
| --- | --- | --- | --- |
| `demande_id` | STRING (32 hex) | DISCOVERY | Clé unique, ne jamais modifier |
| `flux_id` | STRING | DISCOVERY | Filtre obligatoire de toutes les requêtes du flux |
| `flux_version` | STRING | DISCOVERY | Information |
| `conversation_id` | STRING | DISCOVERY | Équivalent du `sessionId` Smart Office |
| `agent_id` | STRING | DISCOVERY | Vide pour le banc de test |
| `user_name` | STRING | DISCOVERY | Utilisateur pour qui la demande est faite (e-mail) |
| `parametres` | STRING (JSON) | DISCOVERY | Paramètres de l'agent + valeurs fixes (les valeurs fixes priment) |
| `statut` | STRING | DISCOVERY puis Power Automate | `en_attente` -> `en_cours` -> `terminee` ou `erreur` |
| `reponse` | STRING (JSON) | Power Automate | Renseignée seulement si `terminee` |
| `erreur` | STRING | Power Automate | Renseignée seulement si `erreur` ; message lisible, sans secret |
| `test` | BOOLEAN | DISCOVERY | `true` = banc de test : **aucune action réelle** (voir R5) |
| `created_at` | TIMESTAMP | DISCOVERY | Dépôt |
| `pris_en_charge_at` | TIMESTAMP | Power Automate | Passage en `en_cours` |
| `termine_at` | TIMESTAMP | Power Automate | Passage en `terminee` ou `erreur` |

Power Automate ne crée ni ne supprime de ligne ; il ne modifie que `statut`, `reponse`, `erreur`,
`pris_en_charge_at`, `termine_at`.

### Cycle de vie

| De | Vers | Acteur | Condition |
| --- | --- | --- | --- |
| (création) | `en_attente` | DISCOVERY | Dépôt par l'agent (après validation de l'utilisateur pour l'envoi) |
| `en_attente` | `en_cours` | Power Automate | Prise en charge, UPDATE conditionnel sur `statut = 'en_attente'` |
| `en_cours` | `terminee` | Power Automate | Action réussie |
| `en_attente` / `en_cours` | `erreur` | Power Automate | Paramètres invalides, action en échec, règle de sécurité non respectée |

Expiration : si une demande reste `en_attente` au-delà du délai du flux (15 min), DISCOVERY l'affiche « expirée »
à l'utilisateur ; la ligne reste `en_attente` en base. **Le flux ne doit pas traiter une demande expirée**
(règle R4), pour éviter un envoi tardif que l'utilisateur croit abandonné.

## 5. Paramètres transmis (`parametres`)

À coller dans l'action « Analyser JSON » (schéma généré par DISCOVERY, page Flux).

`flux_smart_office_consulter`
```json
{"type": "object",
 "properties": {"technology": {"type": "string"}, "operation": {"type": "string"}, "query": {"type": "string"},
                "message_id": {"type": "string"}, "question": {"type": "string"},
                "status": {"type": "string"}, "requires_confirmation": {"type": "boolean"}},
 "required": ["technology", "operation", "status", "requires_confirmation"]}
```

`flux_smart_office_envoyer`
```json
{"type": "object",
 "properties": {"technology": {"type": "string"}, "operation": {"type": "string"}, "to": {"type": "string"},
                "subject": {"type": "string"}, "body": {"type": "string"}, "message_id": {"type": "string"},
                "question": {"type": "string"}, "status": {"type": "string"},
                "requires_confirmation": {"type": "boolean"}},
 "required": ["technology", "operation", "to", "subject", "body", "status", "requires_confirmation"]}
```

Valeurs de `operation` : **à fournir par le propriétaire du flux** (P7). Proposition à valider :
`search_messages`, `read_message` (consulter) ; `send_message`, `reply_message` (envoyer). Une fois fixées, elles
seront déclarées comme liste de valeurs dans DISCOVERY pour que les agents ne puissent pas en inventer.

## 6. Déroulé du flux

**Déclencheur** : Récurrence toutes les 1 minute (compatible avec le délai de 15 min). Contrôle de simultanéité
du déclencheur activé, degré 1 (pas deux exécutions en parallèle).

| Étape | Action Power Automate | Requête / règle |
| --- | --- | --- |
| 1 | Azure Databricks : exécuter une instruction SQL | Lire les demandes (requête Q1) |
| 2 | Appliquer à chacun (simultanéité 1) | Pour chaque ligne |
| 3 | Exécuter SQL | Prise en charge (Q2) ; **si 0 ligne modifiée, passer à la suivante** (déjà prise) |
| 4 | Analyser JSON | `parametres` avec le schéma du §5 ; en échec -> étape 8 |
| 5 | Conditions de sécurité | Règles R1 à R6 ; en échec -> étape 8 avec le motif |
| 6 | Commutateur sur `operation` | Actions Office 365 Outlook correspondantes ; si `test = true`, réponse simulée sans action |
| 7 | Exécuter SQL | Écrire la réponse (Q3) |
| 8 | Étendue « Catch » (exécuter après : échec, expiration) | Signaler l'erreur (Q4) |

Structure recommandée : étapes 4 à 7 dans une étendue « Try », étape 8 dans une étendue « Catch » configurée
pour s'exécuter si « Try » a échoué ou expiré.

### Requêtes (exemple pour `flux_smart_office_envoyer`)

Q1 — Lire les demandes en attente non expirées
```sql
SELECT demande_id, parametres, test, user_name, created_at
FROM dataops_dev.ai_studio.flux_demandes
WHERE flux_id = 'flux_smart_office_envoyer' AND statut = 'en_attente'
  AND created_at >= current_timestamp() - INTERVAL 15 MINUTES
ORDER BY created_at
LIMIT 10
```

Q2 — Prendre en charge
```sql
UPDATE dataops_dev.ai_studio.flux_demandes
SET statut = 'en_cours', pris_en_charge_at = current_timestamp()
WHERE demande_id = '<demande_id>' AND flux_id = 'flux_smart_office_envoyer' AND statut = 'en_attente'
```

Q3 — Écrire la réponse
```sql
UPDATE dataops_dev.ai_studio.flux_demandes
SET statut = 'terminee', reponse = '<reponse_json>', termine_at = current_timestamp()
WHERE demande_id = '<demande_id>' AND flux_id = 'flux_smart_office_envoyer' AND statut = 'en_cours'
```

Q4 — Signaler une erreur
```sql
UPDATE dataops_dev.ai_studio.flux_demandes
SET statut = 'erreur', erreur = '<message_erreur>', termine_at = current_timestamp()
WHERE demande_id = '<demande_id>' AND flux_id = 'flux_smart_office_envoyer' AND statut IN ('en_attente', 'en_cours')
```

Pour `flux_smart_office_consulter`, remplacer le `flux_id`. Q1 à Q4 sont aussi générées par DISCOVERY (page Flux) ;
Q1 ajoute ici le filtre d'expiration (R4).

**Injection SQL** : `<reponse_json>` et `<message_erreur>` contiennent du texte libre (corps de mails). Utiliser les
paramètres de requête du connecteur s'il les propose ; à défaut, doubler les apostrophes
(`replace(texte, '''', '''''')`) et retirer les barres obliques inverses avant insertion. `<demande_id>` vient de Q1
(32 caractères hexadécimaux) : le contrôler par expression avant usage.

## 7. Format de la réponse (`reponse`, JSON) — à valider

Commun : `{"ok": true, "operation": "...", "test": false, "traite_le": "<horodatage ISO>", ...}`

| Opération | Champs proposés |
| --- | --- |
| `search_messages` | `messages` : liste (20 au plus) de `{id, de, objet, recu_le, apercu}` ; `nombre` |
| `read_message` | `message` : `{id, de, a, objet, recu_le, corps_texte}` (corps tronqué à 8 000 caractères, indicateur `tronque`) |
| `send_message` / `reply_message` | `message_id` (si fourni par Outlook), `destinataires`, `envoye_le` |

Taille maximale conseillée de `reponse` : 100 000 caractères (au-delà, DISCOVERY tronque ce qu'il transmet au modèle).
Pas de pièce jointe dans ce lot.

## 8. Règles de gestion et de sécurité

| # | Règle | Si non respectée |
| --- | --- | --- |
| R1 | Traiter uniquement les `flux_id` du flux (filtre dans Q1 à Q4) | — |
| R2 | Envoi : exiger `status = approved` et `requires_confirmation = true` (preuve de validation dans DISCOVERY) | `erreur` « envoi non validé » |
| R3 | Consultation : exiger `status = requested` ; aucune action d'écriture Outlook | `erreur` |
| R4 | Ne pas traiter une demande plus ancienne que le délai (15 min) | Ignorée par Q1 (reste « expirée » côté DISCOVERY) |
| R5 | `test = true` : aucune action réelle, réponse simulée `{"ok": true, "test": true, ...}` | — |
| R6 | Envoi : destinataires limités aux domaines autorisés (proposition : `sncf.fr`, `reseau.sncf.fr`, à valider RSSI) ; 10 destinataires au plus | `erreur` « destinataire non autorisé » |
| R7 | `erreur` : message lisible, sans jeton, URL signée ni donnée personnelle superflue | — |
| R8 | Une demande n'est traitée qu'une fois (UPDATE conditionnels + contrôle du nombre de lignes modifiées) | — |

**Point de sécurité S1 — boîte utilisée (à arbitrer)** : un flux Power Automate agit avec la connexion Office 365
de son propriétaire, pas avec celle de l'utilisateur DISCOVERY (`user_name`). Options :
- A. Boîte partagée dédiée (ex. « DISCOVERY Smart Office ») : consultation et envoi limités à cette boîte. Recommandé.
- B. Boîte de l'utilisateur : nécessite des droits de délégation sur chaque boîte, à proscrire sans accord RSSI.
- C. Boîte du propriétaire du flux : à proscrire (tout utilisateur DISCOVERY lirait cette boîte).

En A, rappeler `user_name` dans le corps ou la signature des envois pour la traçabilité.

## 9. Exploitation

- Supervision : alerte Power Automate en cas d'échec d'exécution ; côté Databricks, requête de contrôle des demandes
  `en_cours` depuis plus de 15 min (flux interrompu en cours de traitement) et des demandes expirées.
- Reprise : une demande bloquée `en_cours` est passée en `erreur` (« traitement interrompu ») par l'exploitant ;
  jamais remise en `en_attente` pour un envoi (risque de double envoi).
- Rétention : purge des demandes de plus de 90 jours (proposition, à valider Data Office / RGPD), `reponse`
  pouvant contenir des extraits de messages.
- Journal : l'historique Power Automate (28 jours) et la table `flux_demandes` constituent la preuve d'exécution.

## 10. Recette

| # | Cas | Attendu |
| --- | --- | --- |
| T1 | Banc de test page Flux, consulter, `test = true` | `terminee`, réponse simulée, aucune action Outlook |
| T2 | Agent : recherche réelle | `terminee`, `messages` conformes à Outlook, lue par `flux_suivi` |
| T3 | Agent : envoi validé vers une adresse autorisée | `terminee`, message reçu, `message_id` renseigné |
| T4 | Envoi refusé par l'utilisateur dans DISCOVERY | Aucune ligne déposée |
| T5 | Destinataire hors domaine autorisé | `erreur` « destinataire non autorisé », aucun envoi |
| T6 | `parametres` invalide (champ obligatoire manquant) | `erreur` explicite |
| T7 | Flux arrêté 20 min puis relancé | Demande « expirée » dans DISCOVERY, non traitée à la reprise |
| T8 | Deux exécutions simultanées forcées | Une seule prise en charge (R8), un seul envoi |
| T9 | Corps contenant apostrophes et guillemets | Réponse écrite sans erreur SQL, texte intact |

## 11. Points ouverts

1. Disponibilité du connecteur Azure Databricks (P1) et accès réseau (P5).
2. Identité technique et droits limités à `flux_demandes` (P2, P3).
3. Valeurs `technology` / `operation` du flux Smart Office (P7).
4. Boîte utilisée (S1) et domaines autorisés (R6) : arbitrage RSSI.
5. Format de réponse (§7) et durée de rétention (§9).
6. Suppression des données d'essai `flux_essai_discovery_flux` (1 outil, 1 version, 2 demandes) : accord à donner.
