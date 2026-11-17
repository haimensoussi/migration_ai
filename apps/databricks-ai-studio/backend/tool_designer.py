"""Copilote d'outils : une demande en langage naturel devient un outil déclaratif vérifié.

1. Le modèle explore les données sous l'identité de l'utilisateur (list_tables, describe_table, execute_sql en
   lecture seule et limité, y compris SHOW USER FUNCTIONS / DESCRIBE FUNCTION).
2. Il termine en appelant propose_tool. La proposition est vérifiée (tool_builder.check) ; en cas d'erreur, elle
   lui est renvoyée pour correction (2 fois au plus).
3. Rien n'est enregistré ni publié automatiquement : l'utilisateur relit, teste puis enregistre.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, replace

from backend import tool_builder as tb
from backend.agent_runtime import ToolEvent, _parse_args
from backend.tool_registry import ToolContext, ToolError, ToolRegistry, ToolSpec

EXPLORATION_TOOLS = ("list_tables", "describe_table", "execute_sql")
MAX_STEPS = 12
MAX_FIXES = 2
EXPLORE_ROWS = 20
MAX_TOOL_RESULT_CHARS = 8000

PROPOSE_TOOL = {"type": "function", "function": {
    "name": "propose_tool",
    "description": "Termine la conception en proposant la définition complète de l'outil.",
    "parameters": {"type": "object", "properties": {
        "feasible": {"type": "boolean", "description": "false si la demande ne peut pas être couverte par les types disponibles"},
        "unsupported_reason": {"type": "string", "description": "Si feasible = false : pourquoi, et ce qui serait nécessaire"},
        "tool_id": {"type": "string", "description": "Identifiant snake_case, 3 à 40 caractères"},
        "name": {"type": "string", "description": "Nom court lisible"},
        "description": {"type": "string", "description": "Pour les agents : ce que fait l'outil, quand l'utiliser, ce qu'il renvoie"},
        "category": {"type": "string", "enum": tb.CATEGORIES},
        "type": {"type": "string", "enum": list(tb.EXECUTORS)},
        "sql": {"type": "string", "description": "sql_template : une requête SELECT avec des paramètres :nom"},
        "function": {"type": "string", "description": "uc_function : catalog.schema.fonction"},
        "function_kind": {"type": "string", "enum": ["scalar", "table"]},
        "connection": {"type": "string", "description": "http_connection : nom de la connexion HTTP Unity Catalog"},
        "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
        "path": {"type": "string", "description": "http_connection : chemin relatif, ex. /api/items/{{id}}"},
        "body": {"type": "object", "description": "http_connection : modèle de corps JSON avec {{nom}}"},
        "query": {"type": "object", "description": "http_connection : paramètres de requête avec {{nom}}"},
        "headers": {"type": "object", "description": "http_connection : en-têtes fixes sans identifiants"},
        "parameters": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "type": {"type": "string", "enum": list(tb.PARAM_TYPES)},
            "description": {"type": "string"}, "required": {"type": "boolean"},
            "enum": {"type": "array", "items": {"type": "string"}},
            "example": {"type": "string", "description": "Valeur d'exemple réaliste, observée dans les données"}},
            "required": ["name", "type", "description", "required"]}},
        "max_rows": {"type": "integer"},
        "hypotheses": {"type": "array", "items": {"type": "string"},
                       "description": "Hypothèses faites et points à confirmer par l'utilisateur"},
        "changes": {"type": "array", "items": {"type": "string"},
                    "description": "Mode amélioration : chaque modification et sa raison"}},
        "required": ["feasible"]}}}


@dataclass
class ToolDesignResult:
    draft: dict | None
    check: tb.Check = field(default_factory=tb.Check)
    hypotheses: list[str] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)
    unsupported: str = ""
    events: list[ToolEvent] = field(default_factory=list)
    attempts: int = 0
    latency_ms: int = 0
    usage: dict = field(default_factory=dict)


def designer_prompt(existing: list[ToolSpec], scope: str | None = None) -> str:
    catalog = "\n".join(f"- {t.tool_id} : {t.description[:160]}" for t in existing if t.status == "publie")
    where = ([f"Périmètre de données suggéré par l'utilisateur : {scope}. Commence ton exploration par ce périmètre "
              "(list_tables) et n'en sors que s'il ne contient pas les données utiles.", ""] if scope else [])
    return "\n".join(where + [
        "Tu es le copilote d'outils de DISCOVERY (SNCF Réseau). Tu transformes la demande de l'utilisateur en un outil "
        "que des agents pourront appeler.",
        "",
        "Types d'outils disponibles (aucun autre) :",
        "- sql_template : UNE requête SELECT en lecture seule, avec des paramètres nommés :nom.",
        "- uc_function : appel d'une fonction Unity Catalog existante (catalog.schema.fonction), scalar ou table.",
        "- http_connection : appel HTTP via une connexion HTTP Unity Catalog EXISTANTE (liste : execute_sql avec "
        "SHOW CONNECTIONS ; les connexions system_* sont interdites). Tu fournis connection, method (GET, POST, PUT, "
        "PATCH, DELETE), path relatif commençant par /, body (objet JSON, pas pour GET), query (objet JSON) et headers "
        "(objet JSON, jamais d'identifiants : ils restent dans la connexion). Les valeurs variables s'écrivent {{nom}} "
        "dans path, body ou query. Tout appel autre que GET exigera une validation humaine.",
        "- Si aucune connexion adaptée n'existe, appelle propose_tool avec feasible = false et indique la connexion "
        "à demander à un administrateur du metastore (nom proposé, hôte, type d'authentification).",
        "Les écritures SQL (INSERT, UPDATE, MERGE...) et le lancement de Jobs ne sont pas disponibles : feasible = false.",
        "",
        "Outils déjà publiés (évite les doublons ; si l'un d'eux suffit, dis-le dans hypotheses) :",
        catalog or "- (aucun)",
        "",
        "Méthode :",
        "- Explore avec list_tables puis describe_table. N'utilise que des tables et des colonnes que tu as vues, "
        "en nom complet catalog.schema.table. Les noms de colonnes avec espaces ou caractères spéciaux s'écrivent "
        "entre `backticks`.",
        "- Pour chercher une table par mot-clé dans un catalogue : execute_sql avec SELECT table_schema, table_name "
        "FROM <catalogue>.information_schema.tables WHERE table_name ILIKE '%mot%'. Ne parcours pas les catalogues "
        "schéma par schéma.",
        "- Tu disposes de peu d'étapes : 3 à 5 explorations suffisent en général avant de proposer.",
        "- Utilise execute_sql (lecture seule, 20 lignes) pour observer des valeurs réelles : elles servent "
        "d'exemples aux paramètres. Pour les fonctions : SHOW USER FUNCTIONS IN catalog.schema, puis DESCRIBE FUNCTION.",
        "- Chaque valeur variable est un paramètre :nom, jamais une valeur écrite en dur ni concaténée. "
        "Paramètre facultatif : (:nom IS NULL OR colonne = :nom) et required = false.",
        "- Noms de paramètres en minuscules (a-z, 0-9, _). Types : string, integer, number, boolean.",
        "- Pas de LIMIT dans la requête : utilise max_rows (100 par défaut, 1000 au plus). Ajoute un ORDER BY utile.",
        "- Apostrophe dans une chaîne SQL : écris \\' (ex. 'Provence-Alpes-Côte d\\'Azur') ou entoure la chaîne de "
        "guillemets doubles (\"Côte d'Azur\"). Jamais '' : en Spark SQL, 'd''Azur' devient dAzur (deux chaînes collées).",
        "- Valeurs avec caractères spéciaux (apostrophe, accent, tiret, espace) : recopie-les exactement depuis les "
        "données observées et donne en exemple de paramètre l'une d'elles quand elles existent, pour qu'elle soit testée.",
        "- La description dit aux agents ce que fait l'outil, quand l'utiliser, et ce qu'il renvoie (colonnes).",
        "- N'invente ni règle métier ni seuil SNCF Réseau : s'il en faut, mets-les en paramètre ou dans hypotheses "
        "comme « à valider par le responsable métier ».",
        "- Termine OBLIGATOIREMENT par un appel à propose_tool. Si on te renvoie des erreurs, corrige et rappelle propose_tool.",
    ])


class ToolDesigner:
    def __init__(self, model, registry: ToolRegistry, ctx: ToolContext, model_endpoint: str, owner: str,
                 max_steps: int = MAX_STEPS):
        self.model, self.registry, self.owner = model, registry, owner
        self.ctx = replace(ctx, allowed_tables=[], max_rows=min(ctx.max_rows, EXPLORE_ROWS))
        self.check_sql = ctx.sql
        self.model_endpoint, self.max_steps = model_endpoint, max_steps

    def design(self, request: str, scope: str | None = None) -> ToolDesignResult:
        if len((request or "").strip()) < 15:
            raise ToolError("Décrivez l'outil voulu en une ou deux phrases (15 caractères minimum).")
        scope = (scope or "").strip() or None
        return self._run([{"role": "system", "content": designer_prompt(list(self.registry.specs.values()), scope)},
                          {"role": "user", "content": request.strip()}])

    def improve(self, current: dict, request: str = "", test_result: dict | None = None) -> ToolDesignResult:
        request = (request or "").strip() or "Améliore la description, les paramètres et la robustesse de la requête."
        keep = {k: current.get(k) for k in ("tool_id", "name", "description", "category", "type", "sql", "function",
                                            "function_kind", "connection", "method", "path", "body", "query",
                                            "headers", "parameters", "max_rows")}
        parts = [f"Demande d'amélioration : {request}", "", "Outil actuel (JSON) :",
                 json.dumps(keep, ensure_ascii=False, indent=1, default=str)]
        if test_result and not test_result.get("ok"):
            parts += ["", f"Dernier test en échec : {test_result.get('erreur')}"]
        system = designer_prompt(list(self.registry.specs.values())) + "\n" + "\n".join([
            "", "Mode amélioration :",
            f"- Conserve l'identifiant « {current.get('tool_id')} ».",
            "- Ne modifie que ce qui sert la demande ou corrige un défaut ; liste chaque modification dans changes."])
        return self._run([{"role": "system", "content": system}, {"role": "user", "content": "\n".join(parts)}],
                         keep_id=current.get("tool_id"))

    def _run(self, messages: list[dict], keep_id: str | None = None) -> ToolDesignResult:
        t0, usage, events, fixes, attempts, nudged = time.monotonic(), {}, [], 0, 0, False
        explore = {t: self.registry.specs[t] for t in EXPLORATION_TOOLS
                   if t in self.registry.specs and self.registry.specs[t].status == "publie"}
        payload = [s.to_openai() for s in explore.values()] + [PROPOSE_TOOL]
        existing = dict(self.registry.specs)
        last, warned = None, False
        for step in range(self.max_steps):
            if not warned and step >= self.max_steps - 2:   # budget presque épuisé : conclure
                messages.append({"role": "user", "content": "Il te reste 2 étapes : appelle propose_tool maintenant "
                                 "avec ce que tu as trouvé (feasible = false si les données nécessaires sont introuvables)."})
                warned = True
            resp = self.model.chat(self.model_endpoint, messages, tools=payload, temperature=0.1, max_tokens=4096)
            for k, v in (resp.get("usage") or {}).items():
                if isinstance(v, (int, float)):
                    usage[k] = usage.get(k, 0) + v
            msg = resp["message"]
            messages.append(msg)
            calls = msg.get("tool_calls") or []
            if not calls:
                if nudged:
                    break
                messages.append({"role": "user", "content": "Termine maintenant en appelant propose_tool."})
                nudged = True
                continue
            for call in calls:
                if call["function"]["name"] != "propose_tool":
                    ev = self._explore(call, explore)
                    events.append(ev)
                    content = json.dumps({"status": ev.status, "result": ev.result, "error": ev.error},
                                         ensure_ascii=False, default=str)[:MAX_TOOL_RESULT_CHARS]
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": content})
                    continue
                p = _parse_args(call)
                attempts += 1
                done = lambda **kw: ToolDesignResult(events=events, attempts=attempts, usage=usage,  # noqa: E731
                                                     latency_ms=int((time.monotonic() - t0) * 1000), **kw)
                if p.get("feasible") is False:
                    return done(draft=None, unsupported=str(p.get("unsupported_reason") or "Demande non couverte."),
                                hypotheses=[str(h) for h in p.get("hypotheses") or []])
                draft = tb.normalize(p)
                if keep_id:
                    draft["tool_id"] = keep_id
                c = tb.check(draft, existing, self.owner, self.check_sql)
                last = done(draft=draft, check=c, hypotheses=draft["hypotheses"],
                            changes=[str(x) for x in p.get("changes") or []])
                if c.ok or fixes >= MAX_FIXES:
                    return last
                fixes += 1
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(
                    {"statut": "a_corriger", "erreurs": c.errors,
                     "consigne": "Corrige ces erreurs (explore si besoin) puis rappelle propose_tool."},
                    ensure_ascii=False)})
        if last is not None:
            return last
        raise ToolError("Le copilote n'a pas produit de proposition. Reformulez ou précisez la demande.")

    def _explore(self, call: dict, explore: dict[str, ToolSpec]) -> ToolEvent:
        name, t0 = call["function"]["name"], time.monotonic()
        args = _parse_args(call)
        try:
            if name not in explore:
                raise ToolError(f"Outil « {name} » non disponible pendant la conception.")
            if name == "execute_sql":
                args = {**args, "limit": min(int(args.get("limit") or EXPLORE_ROWS), EXPLORE_ROWS)}
            out = self.registry.run(explore[name], self.ctx, args)
            return ToolEvent(call["id"], name, args, "succes", result=out,
                             duration_ms=int((time.monotonic() - t0) * 1000))
        except ToolError as e:
            err = str(e)
        except Exception as e:  # noqa: BLE001
            err = f"Erreur technique ({type(e).__name__}) : {e}"
        return ToolEvent(call["id"], name, args, "erreur", error=err[:1000],
                         duration_ms=int((time.monotonic() - t0) * 1000))
