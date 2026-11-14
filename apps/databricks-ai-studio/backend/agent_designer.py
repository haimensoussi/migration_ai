"""Copilote de conception : une description en langage naturel devient un brouillon d'agent validé.

Fonctionnement :
1. Le modèle explore les données avec list_tables / describe_table, sous l'identité de l'utilisateur.
2. Il termine en appelant la fonction propose_agent (configuration structurée).
3. La proposition est validée : outils publiés uniquement, tables effectivement accessibles,
   catégorie et icône connues, paramètres bornés. Rien n'est enregistré ni publié automatiquement.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from backend.agent_runtime import ToolEvent, _parse_args
from backend.tool_registry import ToolContext, ToolError, ToolRegistry, ToolSpec

CATEGORIES = ["Général", "Qualité des données", "Analyse", "FinOps", "Documents", "Gouvernance", "Exploitation"]
ICONS = ["smart_toy", "verified", "terminal", "savings", "description", "policy", "query_stats", "support_agent"]
EXPLORATION_TOOLS = ("list_tables", "describe_table")
DATA_TOOLS = {"describe_table", "get_table_profile", "execute_sql"}
MAX_STEPS = 8
MAX_TABLES = 20
MAX_TOOL_RESULT_CHARS = 8000

PROPOSE_AGENT = {"type": "function", "function": {
    "name": "propose_agent",
    "description": "Termine la conception en proposant la configuration complète du brouillon d'agent.",
    "parameters": {"type": "object", "properties": {
        "name": {"type": "string", "description": "Nom court de l'agent"},
        "description": {"type": "string", "description": "Description fonctionnelle (2 phrases maximum)"},
        "category": {"type": "string", "enum": CATEGORIES},
        "icon": {"type": "string", "enum": ICONS},
        "instructions": {"type": "string", "description": "Prompt système complet en français, à la 2e personne"},
        "tool_ids": {"type": "array", "items": {"type": "string"}},
        "knowledge_tables": {"type": "array", "items": {"type": "string"},
                             "description": "Noms complets catalog.schema.table effectivement consultés"},
        "temperature": {"type": "number"},
        "max_iterations": {"type": "integer"},
        "test_questions": {"type": "array", "items": {"type": "string"}},
        "hypotheses": {"type": "array", "items": {"type": "string"},
                       "description": "Hypothèses faites et points à confirmer par l'utilisateur"},
        "changes": {"type": "array", "items": {"type": "string"},
                    "description": "Mode amélioration : chaque modification apportée et sa raison"}},
        "required": ["name", "description", "category", "icon", "instructions", "tool_ids",
                     "knowledge_tables", "test_questions"]}}}


@dataclass
class DesignResult:
    draft: dict
    warnings: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    test_questions: list[str] = field(default_factory=list)
    events: list[ToolEvent] = field(default_factory=list)
    raw_proposal: dict = field(default_factory=dict)
    changes: list[str] = field(default_factory=list)
    latency_ms: int = 0
    usage: dict = field(default_factory=dict)


def designer_prompt(published: list[ToolSpec], scope: str | None) -> str:
    catalog = "\n".join(f"- {t.tool_id} : {t.description}" for t in published) or "- (aucun outil publié)"
    lines = [
        "Tu es le copilote de conception de Databricks AI Studio. Tu transformes la demande de l'utilisateur "
        "en configuration d'agent.",
        "",
        "Catalogue des outils publiés (tu ne peux choisir QUE parmi eux, sans en créer) :",
        catalog,
        "",
        "Règles :",
        "- Si la demande porte sur des données, explore-les avec list_tables puis describe_table. "
        "Ne retiens dans knowledge_tables que des tables que tu as effectivement décrites, en nom complet catalog.schema.table.",
        "- N'invente ni table, ni colonne, ni règle métier, ni seuil. Si l'agent doit évoquer des règles ou des seuils, "
        "ses instructions doivent imposer de les présenter comme « à valider » par le responsable métier.",
        "- Les instructions décrivent : le rôle, le périmètre, la méthode (quels outils et dans quel ordre), "
        "le format de réponse et les limites (lecture seule, ce qu'il doit refuser).",
        "- Choisis le minimum d'outils nécessaires. Température basse (0 à 0,2) pour un agent analytique.",
        "- Propose 3 à 5 questions de test réalistes et liste tes hypothèses.",
        "- Termine OBLIGATOIREMENT par un appel à propose_agent. Ne réponds pas en texte libre.",
    ]
    if scope:
        lines.insert(1, f"Périmètre de données suggéré par l'utilisateur : {scope}.")
    return "\n".join(lines)


class AgentDesigner:
    def __init__(self, model, registry: ToolRegistry, ctx: ToolContext, model_endpoint: str,
                 max_steps: int = MAX_STEPS):
        self.model, self.registry, self.ctx = model, registry, ctx
        self.model_endpoint, self.max_steps = model_endpoint, max_steps

    def design(self, request: str, scope: str | None = None) -> DesignResult:
        if len((request or "").strip()) < 15:
            raise ToolError("Décrivez le besoin en une ou deux phrases (15 caractères minimum).")
        messages = [{"role": "system", "content": designer_prompt(self.registry.published(), scope)},
                    {"role": "user", "content": request.strip()}]
        return self._run(messages)

    def improve(self, current: dict, request: str = "", signals: list[dict] | None = None) -> DesignResult:
        """Propose une version améliorée d'un agent existant (configuration complète + liste des changements).

        Le modèle de l'agent n'est jamais modifié par le copilote : il reste un choix de l'utilisateur.
        """
        request = (request or "").strip() or ("Améliore la clarté et la robustesse des instructions et vérifie "
                                              "la cohérence entre instructions, outils et tables.")
        cfg = {k: current.get(k) for k in ("name", "description", "category", "icon", "instructions", "tool_ids",
                                           "knowledge_tables", "temperature", "max_iterations")}
        parts = [f"Demande d'amélioration : {request}", "",
                 "Configuration actuelle (JSON) :", json.dumps(cfg, ensure_ascii=False, indent=1)]
        if signals:
            parts += ["", "Erreurs récentes de cet agent (journal tool_calls, à prendre en compte) :"]
            parts += [f"- {s.get('tool_id')} : {str(s.get('error') or s.get('status'))[:300]}" for s in signals[:15]]
        system = designer_prompt(self.registry.published(), None) + "\n" + "\n".join([
            "",
            "Mode amélioration :",
            "- Conserve ce qui fonctionne ; ne modifie que ce qui sert la demande ou corrige un défaut constaté.",
            "- Ne retire ni outil ni table sans le justifier dans changes ; vérifie avec describe_table toute table ajoutée.",
            "- Renvoie la configuration COMPLÈTE via propose_agent et liste dans changes chaque modification et sa raison.",
        ])
        res = self._run([{"role": "system", "content": system}, {"role": "user", "content": "\n".join(parts)}])
        res.draft["model_endpoint"] = current.get("model_endpoint") or res.draft["model_endpoint"]
        if not res.changes:
            res.warnings.append("Le copilote n'a listé aucune modification : comparez les versions avant d'appliquer.")
        return res

    def _run(self, messages: list[dict]) -> DesignResult:
        t0, usage, events = time.monotonic(), {}, []
        self.ctx.allowed_tables = []  # la conception explore tout ce que l'utilisateur peut lire
        explore = {t: self.registry.specs[t] for t in EXPLORATION_TOOLS
                   if t in self.registry.specs and self.registry.specs[t].status == "publie"}
        payload = [s.to_openai() for s in explore.values()] + [PROPOSE_AGENT]
        nudged = False
        for _ in range(self.max_steps):
            resp = self.model.chat(self.model_endpoint, messages, tools=payload, temperature=0.2, max_tokens=4096)
            for k, v in (resp.get("usage") or {}).items():
                if isinstance(v, (int, float)):
                    usage[k] = usage.get(k, 0) + v
            msg = resp["message"]
            messages.append(msg)
            calls = msg.get("tool_calls") or []
            if not calls:
                if nudged:
                    break
                messages.append({"role": "user", "content": "Termine maintenant en appelant propose_agent."})
                nudged = True
                continue
            for call in calls:
                name = call["function"]["name"]
                if name == "propose_agent":
                    proposal = _parse_args(call)
                    res = self.validate(proposal, events)
                    res.latency_ms, res.usage, res.raw_proposal = int((time.monotonic() - t0) * 1000), usage, proposal
                    return res
                ev = self._explore(call, explore)
                events.append(ev)
                content = json.dumps({"status": ev.status, "result": ev.result, "error": ev.error},
                                     ensure_ascii=False, default=str)[:MAX_TOOL_RESULT_CHARS]
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": content})
        raise ToolError("Le copilote n'a pas produit de proposition. Reformulez ou précisez la demande.")

    def _explore(self, call: dict, explore: dict[str, ToolSpec]) -> ToolEvent:
        name, t0 = call["function"]["name"], time.monotonic()
        args = _parse_args(call)
        try:
            if name not in explore:
                raise ToolError(f"Outil « {name} » non disponible pendant la conception.")
            out = self.registry.run(explore[name], self.ctx, args)
            return ToolEvent(call["id"], name, args, "succes", result=out,
                             duration_ms=int((time.monotonic() - t0) * 1000))
        except ToolError as e:
            err = str(e)
        except Exception as e:  # noqa: BLE001
            err = f"Erreur technique ({type(e).__name__}) : {e}"
        return ToolEvent(call["id"], name, args, "erreur", error=err[:1000],
                         duration_ms=int((time.monotonic() - t0) * 1000))

    # -- Validation -----------------------------------------------------------
    def _accessible(self, table: str) -> bool:
        spec = self.registry.specs.get("describe_table")
        if spec is None:
            return False
        try:
            self.registry.run(spec, self.ctx, {"table": table})
            return True
        except Exception:  # noqa: BLE001
            return False

    def validate(self, p: dict, events: list[ToolEvent]) -> DesignResult:
        warnings: list[str] = []
        name = str(p.get("name") or "").strip()[:80] or "Nouvel agent"
        category = p.get("category") if p.get("category") in CATEGORIES else "Général"
        if p.get("category") not in CATEGORIES:
            warnings.append(f"Catégorie « {p.get('category')} » inconnue : « Général » retenue.")
        icon = p.get("icon") if p.get("icon") in ICONS else "smart_toy"
        instructions = str(p.get("instructions") or "").strip()
        if len(instructions) < 20:
            warnings.append("Instructions trop courtes : à compléter à l'étape 3.")

        published = {t.tool_id for t in self.registry.published()}
        tools, unknown = [], []
        for t in p.get("tool_ids") or []:
            (tools if t in published else unknown).append(t)
        tools = list(dict.fromkeys(tools))
        if unknown:
            warnings.append("Outils ignorés (absents ou non publiés) : " + ", ".join(sorted(set(unknown))))

        described = {str(e.result.get("table", "")).lower() for e in events
                     if e.tool_id == "describe_table" and e.status == "succes" and isinstance(e.result, dict)}
        tables, dropped = [], []
        for t in list(dict.fromkeys(str(x).strip().strip("`") for x in (p.get("knowledge_tables") or [])))[:MAX_TABLES]:
            if t.count(".") != 2:
                dropped.append(f"{t} (nom incomplet)")
            elif t.lower() in described or self._accessible(t):
                tables.append(t)
            else:
                dropped.append(f"{t} (introuvable ou non accessible avec vos droits)")
        if dropped:
            warnings.append("Tables écartées : " + "; ".join(dropped))
        if tables and not (set(tools) & DATA_TOOLS):
            warnings.append("Des tables sont sélectionnées mais aucun outil de données (describe_table, "
                            "get_table_profile, execute_sql) n'est associé.")

        def num(v, lo, hi, default, cast):
            try:
                return min(hi, max(lo, cast(v)))
            except (TypeError, ValueError):
                return default
        draft = {"name": name, "description": str(p.get("description") or "").strip()[:500], "icon": icon,
                 "category": category, "model_endpoint": self.model_endpoint, "instructions": instructions,
                 "tool_ids": tools, "knowledge_tables": tables,
                 "temperature": num(p.get("temperature"), 0.0, 1.0, 0.1, float),
                 "max_iterations": num(p.get("max_iterations"), 1, 12, 6, int)}
        questions = [str(q).strip() for q in (p.get("test_questions") or []) if str(q).strip()][:5]
        hyps = [str(h).strip() for h in (p.get("hypotheses") or []) if str(h).strip()][:10]
        changes = [str(c).strip() for c in (p.get("changes") or []) if str(c).strip()][:20]
        return DesignResult(draft=draft, warnings=warnings, hypotheses=hyps, test_questions=questions,
                            events=events, changes=changes)


FIELDS_LABELS = {"name": "Nom", "description": "Description", "category": "Catégorie", "icon": "Icône",
                 "tool_ids": "Outils", "knowledge_tables": "Tables", "temperature": "Température",
                 "max_iterations": "Itérations max", "instructions": "Instructions"}


def config_diff(current: dict, proposed: dict) -> list[dict]:
    """Champs modifiés entre deux configurations (listes comparées comme ensembles ordonnés)."""
    out = []
    for k, label in FIELDS_LABELS.items():
        a, b = current.get(k), proposed.get(k)
        if isinstance(a, list) or isinstance(b, list):
            sa, sb = list(a or []), list(b or [])
            if sa != sb:
                out.append({"champ": label, "cle": k, "ajouts": [x for x in sb if x not in sa],
                            "retraits": [x for x in sa if x not in sb], "actuel": sa, "propose": sb})
        elif (a if a is not None else "") != (b if b is not None else ""):
            out.append({"champ": label, "cle": k, "actuel": a, "propose": b})
    return out
