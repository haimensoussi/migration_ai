"""HakimAI, l'architecte de la plateforme DISCOVERY — lot 1 : guider, expliquer, diagnostiquer (lecture seule).

HakimAI n'est pas enregistré dans le catalogue des agents : ses outils lui sont propres et ne sont pas proposés
aux autres agents. Il agit avec les droits de l'utilisateur ; aucun de ses outils du lot 1 n'écrit.
"""
from __future__ import annotations

import json
import os

from backend.agent_runtime import AgentConfig
from backend.tool_registry import ToolSpec
from tools.hakim_tools import GUIDE, PAGES, TOURS

AGENT_ID = "hakimai"
NAME = "HakimAI"
PERSONA = "l'architecte de la plateforme"


def enabled() -> bool:
    return os.environ.get("AI_STUDIO_HAKIM_ENABLED", "true").strip().lower() not in ("0", "false", "non", "off")


def max_turns() -> int:
    try:
        return max(1, int(os.environ.get("AI_STUDIO_HAKIM_MAX_TURNS", "30")))
    except ValueError:
        return 30


def _s(desc, **kw):
    return {"type": "string", "description": desc, **kw}


_AGENT = _s("Nom, @nom d'appel ou identifiant de l'agent")
_OBJ = {"type": "object"}


def _spec(tool_id, name, description, props=None, required=None, write=False, module="hakim_tools"):
    return ToolSpec(tool_id=tool_id, name=name, category="HakimAI", description=description,
                    input_schema={"type": "object", "properties": props or {}, "required": required or []},
                    output_schema=_OBJ, executor=f"tools.{module}:{tool_id}", read_only=not write,
                    requires_confirmation=write)


_LIST = {"type": "array", "items": {"type": "string"}}
_TOOL = _s("Identifiant ou nom de l'outil")
_CASES = {"type": "array", "items": {"type": "object"}, "maxItems": 5,
          "description": "Jusqu'à 5 jeux d'arguments : cas nominal, paramètre facultatif vide, valeur limite..."}
_W = "tools.hakim_write_tools"


def _r(tool_id, name, description, props=None, required=None):
    return _spec(tool_id, name, description, props, required, module="hakim_report_tools")


def _w(tool_id, name, description, props=None, required=None, write=True):
    return _spec(tool_id, name, description, props, required, write=write, module="hakim_write_tools")


TOOLS: list[ToolSpec] = [
    _spec("contexte_page", "Contexte de la page", "Page où se trouve l'utilisateur, objet affiché (agent, équipe...), "
          "identité et rôle administrateur. À appeler quand la question dépend de « ici », « cet agent », « cette page »."),
    _spec("ouvrir_page", "Ouvrir une page", "Propose à l'utilisateur un bouton pour aller sur une page de la plateforme.",
          {"page": _s("Page cible", enum=list(PAGES)), "raison": _s("Pourquoi cette page (une phrase)")}, ["page"]),
    _spec("aide_plateforme", "Aide sur la plateforme", "Explication de référence d'un concept de la plateforme.",
          {"sujet": _s("Sujet", enum=list(GUIDE))}, ["sujet"]),
    _spec("visite_guidee", "Visite guidée", "Parcours de pages recommandé selon le profil de l'utilisateur.",
          {"profil": _s("Profil", enum=list(TOURS))}),
    _spec("lister_agents", "Lister les agents", "Agents visibles par l'utilisateur (publiés, les siens ; tous pour un administrateur).",
          {"recherche": _s("Mot recherché (nom, rôle, catégorie)"), "statut": _s("Filtre", enum=["brouillon", "publie"])}),
    _spec("decrire_agent", "Décrire un agent", "Fiche d'un agent : identité, version, modèle, outils, tables, équipes, instructions.",
          {"agent": _AGENT}, ["agent"]),
    _spec("comparer_versions", "Comparer deux versions", "Différences entre deux versions d'un agent (outils, tables, modèle, "
          "instructions). Par défaut : version courante et précédente.",
          {"agent": _AGENT, "version_a": {"type": "integer", "minimum": 0}, "version_b": {"type": "integer", "minimum": 0}},
          ["agent"]),
    _spec("lister_outils", "Lister les outils", "Catalogue des outils : statut, lecture seule, confirmation, intégré ou créé.",
          {"recherche": _s("Mot recherché"), "statut": _s("Filtre", enum=["brouillon", "publie", "planifie", "indisponible"])}),
    _spec("lister_equipes", "Lister les équipes", "Équipes visibles : mission, chef, membres, responsable humain."),
    _spec("activite", "Activité", "Conversations, appels d'outils et taux de succès par agent sur une période.",
          {"agent": _AGENT, "jours": {"type": "integer", "minimum": 1, "maximum": 90}}),
    _spec("diagnostiquer_echec", "Diagnostiquer les échecs", "Échecs récents regroupés par agent, outil et message. Les "
          "détails ne sont montrés que pour les appels de l'utilisateur ou ses agents.",
          {"agent": _AGENT, "outil": _s("Identifiant d'outil"), "jours": {"type": "integer", "minimum": 1, "maximum": 30}}),
    _spec("explorer_donnees", "Explorer les données", "Lister les tables d'un schéma, décrire, profiler ou prévisualiser "
          "une table, avec les droits Unity Catalog de l'utilisateur. lister_tables sans catalog ni schema : zone de "
          "données de la plateforme (dataops_dev.ai_studio, tables data_*).",
          {"action": _s("Action", enum=["lister_tables", "decrire", "profiler", "apercu"]),
           "table": _s("Nom complet catalog.schema.table"), "catalog": _s("Catalogue"), "schema": _s("Schéma"),
           "limite": {"type": "integer", "minimum": 1, "maximum": 50}}, ["action"]),
]

# Lot 3b : visuels et rapports (lecture seule, droits de l'utilisateur)
_SECTION = {"type": "object", "properties": {"titre": {"type": "string"}, "texte": {"type": "string"},
                                             "visuel_id": {"type": "string"}}, "required": ["titre"]}
TOOLS += [
    _r("creer_visuel", "Créer un visuel", "Exécute une requête SELECT (lecture seule, droits de l'utilisateur) et "
       "affiche un graphique, un tableau ou une carte sous la réponse. Agréger en SQL (GROUP BY) avant de tracer.",
       {"titre": _s("Titre du visuel"), "requete": _s("Requête SELECT renvoyant les colonnes à tracer"),
        "type": _s("Type de visuel", enum=["barres", "barres_horizontales", "courbe", "aire", "camembert", "nuage",
                                           "tableau", "carte"]),
        "x": _s("Colonne des catégories ou de l'axe horizontal"), "y": _s("Colonne numérique"),
        "couleur": _s("Colonne de regroupement (facultatif)"),
        "infobulle": {"type": "array", "items": {"type": "string"}, "description": "Colonnes de l'infobulle (carte)"},
        "limite": {"type": "integer", "minimum": 1, "maximum": 1000}}, ["titre", "requete", "type"]),
    _r("generer_rapport", "Générer un rapport", "Assemble un rapport téléchargeable (HTML et Markdown) à partir des "
       "visuels créés dans la conversation, avec les requêtes en annexe.",
       {"titre": _s("Titre du rapport"), "introduction": _s("Contexte et périmètre"),
        "sections": {"type": "array", "items": _SECTION, "description": "Sections : titre, texte, visuel_id"},
        "conclusion": _s("Constats principaux")}, ["titre", "sections"]),
]

# Lot 2 : conception (lecture) puis création en brouillon (confirmation + journal d'audit)
TOOLS += [
    _w("concevoir_agent", "Concevoir un agent", "Propose un agent complet (identité, instructions, outils, tables) à "
       "partir d'une demande, sans rien enregistrer. Renvoie un brouillon_id.",
       {"demande": _s("Besoin de l'utilisateur, en une ou plusieurs phrases")}, ["demande"], write=False),
    _w("creer_agent", "Créer un agent (brouillon)", "Enregistre en BROUILLON l'agent conçu (brouillon_id), avec "
       "ajustements éventuels. Demande la confirmation de l'utilisateur.",
       {"brouillon_id": _s("Identifiant renvoyé par concevoir_agent"), "nom": _s("Prénom de l'agent"),
        "nom_appel": _s("Nom d'appel @"), "role": _s("Rôle"), "accroche": _s("Accroche"),
        "instructions": _s("Instructions complètes (remplacent celles proposées)")}, ["brouillon_id"]),
    _w("modifier_agent", "Modifier un agent (brouillon)", "Nouvelle version d'un agent EN BROUILLON dont "
       "l'utilisateur est propriétaire : instructions, outils, tables, rôle, accroche.",
       {"agent": _AGENT, "instructions": _s("Nouvelles instructions complètes"), "ajouter_outils": _LIST,
        "retirer_outils": _LIST, "ajouter_tables": _LIST, "retirer_tables": _LIST, "role": _s("Rôle"),
        "accroche": _s("Accroche")}, ["agent"]),
    _w("concevoir_outil", "Concevoir un outil", "Propose un outil SQL paramétré ou une fonction UC à partir d'une "
       "demande, sans rien enregistrer. Renvoie un brouillon_id.",
       {"demande": _s("Ce que l'outil doit faire")}, ["demande"], write=False),
    _w("verifier_outil", "Vérifier un outil", "Contrôle le brouillon d'outil et exécute un test en lecture avec "
       "les droits de l'utilisateur. Obligatoire avant creer_outil.",
       {"brouillon_id": _s("Identifiant renvoyé par concevoir_outil ou ameliorer_outil"),
         "arguments_test": {"type": "object", "description": "Arguments d'essai (sinon exemples du brouillon)"},
         "cas_test": _CASES},
        ["brouillon_id"], write=False),
    _w("decrire_outil", "Décrire un outil", "Fiche technique d'un outil : type, paramètres, requête SQL ou fonction, "
       "exemples, statut, et pour son propriétaire l'historique des versions avec le résultat des tests.",
       {"outil": _TOOL}, ["outil"], write=False),
    _w("tester_outil", "Tester un outil existant", "Exécute un outil existant EN LECTURE SEULE avec les droits de "
       "l'utilisateur, sur un ou plusieurs jeux d'arguments, sans rien enregistrer. Refusé pour les outils qui écrivent.",
       {"outil": _TOOL, "arguments": {"type": "object", "description": "Arguments (sinon exemples de l'outil)"},
        "cas_test": _CASES}, ["outil"], write=False),
    _w("ameliorer_outil", "Améliorer un outil", "Le copilote d'outils propose une nouvelle version d'un outil créé "
       "(SQL ou fonction UC) en brouillon dont l'utilisateur est propriétaire, en tenant compte du dernier test. "
       "Rien n'est enregistré : renvoie un brouillon_id à vérifier puis enregistrer avec creer_outil.",
       {"outil": _TOOL, "demande": _s("Ce qu'il faut changer ou corriger (facultatif)")}, ["outil"], write=False),
    _w("creer_outil", "Créer un outil (brouillon)", "Enregistre en BROUILLON un outil vérifié avec succès : nouvel "
       "outil, ou nouvelle version d'un outil en brouillon (brouillon issu d'ameliorer_outil).",
       {"brouillon_id": _s("Identifiant renvoyé par concevoir_outil ou ameliorer_outil")}, ["brouillon_id"]),
    _w("creer_equipe", "Créer une équipe (brouillon)", "Crée une équipe en BROUILLON : membres, chef existant ou "
       "chef généré en brouillon (creer_chef).",
       {"nom": _s("Nom de l'équipe"), "membres": _LIST, "mission": _s("Mission en une phrase"),
        "chef": _s("Agent coordinateur existant"), "creer_chef": {"type": "boolean"},
        "filiere": _s("Filière", enum=["Transverse", "Supply Chain", "PTE", "UDR"]),
        "nom_appel": _s("Nom d'appel @"), "responsable_humain": _s("E-mail du responsable humain")},
       ["nom", "membres"]),
    _w("modifier_equipe", "Modifier une équipe", "Ajoute ou retire des membres, change la mission, le chef ou le "
       "responsable humain. Une équipe publiée modifiée par un non-administrateur repasse en brouillon.",
       {"equipe": _s("Nom ou @nom d'appel de l'équipe"), "ajouter_membres": _LIST, "retirer_membres": _LIST,
        "mission": _s("Mission"), "chef": _s("Agent coordinateur"), "responsable_humain": _s("E-mail")}, ["equipe"]),
    _w("soumettre_publication", "Demander la publication", "Signale aux administrateurs qu'un brouillon de "
       "l'utilisateur est prêt à publier. Ne publie rien.",
       {"type_objet": _s("Type", enum=["agent", "outil", "equipe"]), "objet": _s("Nom, @nom d'appel ou identifiant"),
        "message": _s("Message pour l'administrateur")}, ["type_objet", "objet"]),
    _w("archiver", "Archiver", "Archive un agent ou une équipe, ou retire un outil créé, dont l'utilisateur est "
       "propriétaire (équipe : créateur ou administrateur).",
       {"type_objet": _s("Type", enum=["agent", "outil", "equipe"]), "objet": _s("Nom, @nom d'appel ou identifiant")},
       ["type_objet", "objet"]),
]

INSTRUCTIONS = f"""Tu es {NAME}, {PERSONA} DISCOVERY (SNCF Réseau). Tu guides les utilisateurs dans la plateforme :
agents IA, outils, équipes d'agents, chat et @mentions, catalogue d'outils, monitoring.

Ce que tu fais :
- Expliquer la plateforme et ses concepts (utilise aide_plateforme pour les définitions de référence).
- Répondre aux questions sur les agents, outils et équipes à partir des outils de lecture ; jamais de mémoire.
- Diagnostiquer : erreurs d'outils, agents peu utilisés, différences entre versions.
- Orienter : proposer la bonne page avec ouvrir_page, ou une visite guidée.
- Explorer les données avec les droits de l'utilisateur quand il le demande.

Zone de données : dataops_dev.ai_studio, tables préfixées data_ (explorer_donnees action=lister_tables sans
catalog ni schema). Les autres tables de ce schéma sont la configuration de la plateforme : ne les explore pas.

Visuels et rapports :
- creer_visuel : vérifie d'abord les colonnes (explorer_donnees action=decrire), agrège en SQL, choisis le type
  adapté (barres pour comparer des catégories, courbe pour une évolution, camembert seulement pour peu de parts,
  carte s'il y a latitude/longitude). Noms de colonnes avec espaces entre accents graves.
- Commente le visuel avec les chiffres renvoyés (aperçu, statistiques_y) ; signale tronque et les valeurs vides.
- generer_rapport : uniquement avec des visuels déjà créés ; les textes ne contiennent que des constats issus des
  résultats ; aucun seuil ni objectif inventé (« à valider » si tu proposes une règle).

Création (lot 2), toujours en BROUILLON :
- Agent : concevoir_agent, présente la proposition (prénom, @appel, rôle, outils, tables), puis creer_agent.
- Outil : concevoir_outil, puis verifier_outil (test réel en lecture), puis creer_outil seulement si le test réussit.
  Les outils HTTP se créent dans le Catalogue d'outils.

Développement d'outils (méthode à suivre) :
1. Cadrer : besoin, données concernées, qui l'utilisera. Vérifie d'abord avec lister_outils qu'aucun outil publié ne
   couvre déjà le besoin ; si oui, propose-le (decrire_outil) au lieu d'en créer un.
2. Explorer : explorer_donnees (decrire, apercu) sur les tables visées, pour connaître les colonnes et des valeurs réelles.
3. Concevoir : concevoir_outil avec une demande précise (tables en nom complet, filtres attendus, colonnes renvoyées).
   Présente la proposition : identifiant, type, paramètres (obligatoire ou non, exemple), requête, hypothèses.
4. Tester : verifier_outil avec cas_test couvrant au moins le cas nominal et, s'il y a des paramètres facultatifs,
   le cas où ils sont vides. Commente les résultats (nombre de lignes, colonnes, tronque) ; 0 ligne n'est pas un succès
   métier : signale-le et propose une correction.
5. Corriger : en cas d'échec ou de résultat douteux, concevoir_outil à nouveau (outil pas encore enregistré) ou
   ameliorer_outil (outil déjà enregistré en brouillon), puis verifier_outil de nouveau.
6. Enregistrer : creer_outil (brouillon), puis indique la publication dans le Catalogue d'outils (onglet Mes outils)
   et l'ajout à un agent (modifier_agent, une fois l'outil publié).
Qualité attendue d'un outil :
- Description pour les agents : ce que fait l'outil, quand l'utiliser, ce qu'il renvoie (colonnes).
- Un paramètre par valeur variable, avec description et exemple réel ; aucune valeur métier en dur.
- Pas de LIMIT dans la requête (max_rows), un ORDER BY utile, noms complets catalog.schema.table.
- Aucun seuil ni règle SNCF Réseau inventé : paramètre ou hypothèse « à valider par le responsable métier ».
- decrire_outil pour relire un outil et son historique ; tester_outil pour rejouer un outil existant (lecture seule).
- Un outil publié ou intégré ne se modifie pas ici : explique pourquoi et ouvre le Catalogue d'outils.
- Équipe : creer_equipe ou modifier_equipe ; un chef est obligatoire au-delà d'un membre.
- Quand l'utilisateur demande une écriture et que l'objet est identifiable, appelle DIRECTEMENT l'outil d'écriture : l'application affiche alors une fiche qu'il valide ou refuse. Ne demande jamais « confirmez-vous ? » en texte. S'il refuse, n'enchaîne pas d'autres écritures.
- Tu ne publies jamais. Propose soumettre_publication, et indique l'écran où la publication se fait.
- Un agent publié se modifie dans Agent Builder.
- Après une création, indique comment tester (Chat & Test) et propose ouvrir_page.

Règles :
- Si la question dépend de la page (« ici », « cet agent »), appelle d'abord contexte_page.
- Hors des outils de création ci-dessus, tu ne modifies et n'exécutes rien : explique comment faire et ouvre la page.
- Un refus d'accès est normal : signale-le tel quel, sans le contourner.
- N'invente aucun agent, outil, chiffre ou résultat. Dis quand une information n'est pas disponible.
- Pour décrire ce qu'on peut faire sur une page, ne cite que les actions_disponibles renvoyées par contexte_page :
  n'ajoute aucune fonctionnalité (pas de « supprimer » si seule l'archive existe).
- Les chiffres doivent venir des outils et rester cohérents : un total est la somme exacte des groupes affichés.
- Ne rattache des résultats à une équipe ou un agent que si l'outil a été appelé avec ce filtre.
- Une colonne proposée par un message d'erreur est une suggestion de la plateforme, pas une correction certaine.
- Pas d'emoji ni de titres décoratifs.
- Réponds en français, de façon concise et concrète : étapes numérotées pour un « comment faire », tableau court pour une liste.
- Désigne les agents par leur prénom et leur nom d'appel (ex. Margot, @margot).
"""


def config(model_endpoint: str) -> AgentConfig:
    return AgentConfig(agent_id=AGENT_ID, version=1, name=NAME, model_endpoint=model_endpoint,
                       instructions=INSTRUCTIONS, tool_ids=[t.tool_id for t in TOOLS], temperature=0.1,
                       max_iterations=12)   # 12 : explorer, concevoir, vérifier, corriger, revérifier, enregistrer


def describe_action(tool_id: str, args: dict, drafts: dict | None = None) -> list[str]:
    """Lignes de la fiche de confirmation, construites par l'application (pas par le modèle)."""
    a, drafts = args or {}, drafts or {}
    lst = lambda v: ", ".join(map(str, v)) if v else "—"  # noqa: E731
    if tool_id == "creer_agent":
        d = (drafts.get(a.get("brouillon_id")) or {}).get("draft") or {}
        return [f"Créer l'agent « {a.get('nom') or d.get('name', '?')} » (@{(a.get('nom_appel') or d.get('handle') or '?').lstrip('@')}) "
                "en brouillon", f"Rôle : {a.get('role') or d.get('persona') or '—'}",
                f"Outils : {lst(d.get('tool_ids'))}", f"Tables : {lst(d.get('knowledge_tables'))}",
                "Instructions : " + ("remplacées par celles indiquées" if a.get("instructions") else "celles proposées")]
    if tool_id == "modifier_agent":
        out = [f"Nouvelle version de l'agent « {a.get('agent')} »"]
        for k, lab in (("ajouter_outils", "Outils ajoutés"), ("retirer_outils", "Outils retirés"),
                       ("ajouter_tables", "Tables ajoutées"), ("retirer_tables", "Tables retirées")):
            if a.get(k):
                out.append(f"{lab} : {lst(a[k])}")
        for k, lab in (("instructions", "Instructions remplacées"), ("role", "Rôle"), ("accroche", "Accroche")):
            if a.get(k):
                out.append(f"{lab} : {str(a[k])[:200]}")
        return out
    if tool_id == "creer_outil":
        e = drafts.get(a.get("brouillon_id")) or {}
        d, t, base = e.get("draft") or {}, e.get("test") or {}, e.get("base")
        head = (f"Nouvelle version de l'outil « {d.get('name', '?')} » ({d.get('tool_id', '?')}), en brouillon"
                if base else f"Enregistrer l'outil « {d.get('name', '?')} » ({d.get('tool_id', '?')}) en brouillon")
        out = [head, f"Type : {d.get('type', '?')}",
               f"Paramètres : {lst([x.get('name') for x in d.get('parameters') or []])}",
               "Test réussi : " + ("oui" if t.get("ok") else "non")]
        if t.get("nombre_cas"):
            out.append(f"Cas de test réussis : {t.get('cas_reussis')} / {t.get('nombre_cas')}")
        return out
    if tool_id == "creer_equipe":
        chef = a.get("chef") or ("chef généré en brouillon" if a.get("creer_chef") else "aucun")
        return [f"Créer l'équipe « {a.get('nom')} » en brouillon", f"Membres : {lst(a.get('membres'))}",
                f"Chef : {chef}", f"Mission : {a.get('mission') or '—'}"]
    if tool_id == "modifier_equipe":
        out = [f"Modifier l'équipe « {a.get('equipe')} »"]
        for k, lab in (("ajouter_membres", "Membres ajoutés"), ("retirer_membres", "Membres retirés"),
                       ("chef", "Nouveau chef"), ("mission", "Mission"), ("responsable_humain", "Responsable humain")):
            if a.get(k):
                out.append(f"{lab} : {lst(a[k]) if isinstance(a[k], list) else a[k]}")
        return out + ["Si l'équipe est publiée et que vous n'êtes pas administrateur, elle repasse en brouillon."]
    if tool_id == "soumettre_publication":
        return [f"Demander la publication de {a.get('type_objet')} « {a.get('objet')} »", "Rien n'est publié par HakimAI."]
    if tool_id == "archiver":
        return [f"Archiver {a.get('type_objet')} « {a.get('objet')} »",
                "L'objet n'est plus proposé aux utilisateurs ; son historique est conservé."]
    return [f"{tool_id} : {json.dumps(a, ensure_ascii=False)[:300]}"]


def navigation_targets(events) -> list[dict]:
    """Boutons de navigation proposés par ouvrir_page pendant un tour (succès uniquement, sans doublon)."""
    seen, out = set(), []
    for ev in events:
        r = ev.result if isinstance(ev.result, dict) else {}
        if ev.tool_id == "ouvrir_page" and ev.status == "succes" and r.get("navigation") and r["navigation"] not in seen:
            seen.add(r["navigation"])
            out.append({"path": r["navigation"], "title": r.get("titre", ""), "reason": r.get("raison", "")})
    return out
