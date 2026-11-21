"""Outils de HakimAI, lot 2 : conception et création en BROUILLON uniquement.

- Toute écriture passe par une fiche de confirmation (requires_confirmation) et est tracée dans copilot_actions.
- Rien n'est publié : la publication reste dans les écrans de la plateforme (soumettre_publication la demande).
- Agents : seul le propriétaire modifie ou archive ; un agent publié se modifie dans Agent Builder.
- Équipes : règles du dépôt des équipes (créateur ou administrateur ; modification non-admin -> brouillon).
- Outils : SQL paramétré ou fonction UC ; test réussi obligatoire avant enregistrement (comme le Tool Builder).
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from backend import teams as T
from backend import tool_builder as tb
from backend.tool_registry import ToolContext, ToolError
from tools.hakim_tools import Platform, _find_agent, _p

HAKIM_TOOL_KINDS = ("sql_template", "uc_function", "http_connection")


def _http_write(draft: dict) -> bool:
    """Appel HTTP autre que GET : il peut créer, modifier ou envoyer des données dans le service distant."""
    return draft.get("type") == "http_connection" and (draft.get("method") or "GET").upper() != "GET"


# --- Journal d'audit ------------------------------------------------------------------------------------
def audit(p: Platform, tool_id: str, otype: str, oid: str | None, args: dict, before: Any, after: Any,
          status: str, error: str | None = None) -> str:
    aid = uuid.uuid4().hex
    dump = lambda v: None if v is None else json.dumps(v, ensure_ascii=False, default=str)[:20000]  # noqa: E731
    p.repo.sql.execute(f"""
        INSERT INTO {p.t('copilot_actions')} (action_id, conversation_id, user_name, tool_id, object_type, object_id,
          arguments, before_state, after_state, status, error, created_at)
        VALUES (:id, :c, :u, :t, :ot, CAST(:oi AS STRING), :a, CAST(:b AS STRING), CAST(:af AS STRING), :s,
                CAST(:e AS STRING), current_timestamp())""",
        {"id": aid, "c": p.conv, "u": p.user, "t": tool_id, "ot": otype, "oi": oid, "a": dump(args) or "{}",
         "b": dump(before), "af": dump(after), "s": status, "e": (error or None) and error[:2000]})
    return aid


def _written(tool_id: str, otype: str):
    """Exécute l'écriture, trace le résultat (succès ou erreur) ; les erreurs remontent au modèle telles quelles."""
    def deco(fn):
        def run(ctx: ToolContext, **args):
            p = _p(ctx)
            try:
                oid, before, after, result = fn(ctx, p, **args)
            except (ToolError, PermissionError, ValueError, KeyError) as e:
                msg = str(e).strip("'\"")
                try:
                    audit(p, tool_id, otype, None, args, None, None, "erreur", msg)
                finally:
                    raise ToolError(msg) from e
            result["action_id"] = audit(p, tool_id, otype, oid, args, before, after, "succes")
            return result
        run.__name__ = fn.__name__
        return run
    return deco


def _draft(p: Platform, did: str, kind: str) -> dict:
    d = p.drafts.get(did)
    if not d or d["kind"] != kind:
        raise ToolError(f"Brouillon « {did} » introuvable dans cette conversation : utilisez d'abord concevoir_{kind}.")
    return d


def _new_id(p: Platform, prefix: str) -> str:
    n = 1 + sum(1 for k in p.drafts if k.startswith(prefix))
    return f"{prefix}{n}"


def _mine(p: Platform, a: dict) -> None:
    if a.get("owner") != p.user:
        raise PermissionError(f"Seul le propriétaire de l'agent « {a.get('name')} » peut le modifier ou l'archiver.")


def _agent_summary(d: dict) -> dict:
    return {"nom": d["name"], "appel": "@" + (d.get("handle") or ""), "role": d.get("persona"),
            "accroche": d.get("tagline"), "categorie": d.get("category"), "outils": d.get("tool_ids"),
            "tables": d.get("knowledge_tables"), "instructions": (d.get("instructions") or "")[:1500]}


# --- Agents -----------------------------------------------------------------------------------------------
def concevoir_agent(ctx: ToolContext, demande: str) -> dict:
    p = _p(ctx)
    if not callable(p.designer):
        raise ToolError("Assistant de conception indisponible.")
    r = p.designer().design(demande)
    did = _new_id(p, "A")
    p.drafts[did] = {"kind": "agent", "draft": r.draft}
    return {"brouillon_id": did, "agent_propose": _agent_summary(r.draft), "avertissements": r.warnings,
            "hypotheses": r.hypotheses, "questions_de_test": r.test_questions,
            "suite": "Présenter la proposition ; creer_agent l'enregistre en brouillon après confirmation."}


@_written("creer_agent", "agent")
def creer_agent(ctx, p, brouillon_id: str, nom: str = "", nom_appel: str = "", role: str = "", accroche: str = "",
                instructions: str = "") -> tuple:
    d = dict(_draft(p, brouillon_id, "agent")["draft"])
    for k, v in (("name", nom), ("handle", nom_appel.lstrip("@")), ("persona", role), ("tagline", accroche),
                 ("instructions", instructions)):
        if v:
            d[k] = v
    if len((d.get("instructions") or "").strip()) < 20:
        raise ToolError("Les instructions doivent faire au moins 20 caractères.")
    meta = {k: d.get(k) for k in ("name", "description", "icon", "category", "handle", "persona", "tagline",
                                   "call_examples", "aliases")}
    cfg = {k: d[k] for k in ("model_endpoint", "instructions", "tool_ids", "knowledge_tables", "temperature",
                             "max_iterations")}
    aid = p.repo.create_agent(meta, cfg, p.user, "brouillon")
    after = {"agent_id": aid, "statut": "brouillon", "version": 1, **_agent_summary(d)}
    return aid, None, after, {"agent_id": aid, "nom": d["name"], "appel": "@" + (d.get("handle") or ""),
                              "statut": "brouillon", "version": 1,
                              "suite": "Tester dans Chat & Test, relire dans Agent Builder, puis publier depuis Agent Builder."}


@_written("modifier_agent", "agent")
def modifier_agent(ctx, p, agent: str, instructions: str = "", ajouter_outils: list | None = None,
                   retirer_outils: list | None = None, ajouter_tables: list | None = None,
                   retirer_tables: list | None = None, role: str = "", accroche: str = "") -> tuple:
    a = _find_agent(p, agent)
    _mine(p, a)
    if a.get("status") == "publie":
        raise ToolError(f"« {a['name']} » est publié : sa modification se fait dans Agent Builder (ou retirez-le d'abord).")
    cur = p.repo.get_config(a["agent_id"])
    published = {s.tool_id for s in p.repo.list_tools() if s.status == "publie"}
    add = [t for t in (ajouter_outils or []) if t not in cur.tool_ids]
    bad = [t for t in add if t not in published and not t.startswith(T.AGENT_PREFIX)]
    if bad:
        raise ToolError("Outils inconnus ou non publiés : " + ", ".join(bad))
    tools = [t for t in cur.tool_ids if t not in (retirer_outils or [])] + add
    tables = [t for t in cur.knowledge_tables if t not in (retirer_tables or [])]
    from tools import uc_tools
    for t in ajouter_tables or []:
        if t not in tables:
            uc_tools.describe_table(ctx, t)          # vérifie l'accès avec les droits de l'utilisateur
            tables.append(t)
    cfg = {"model_endpoint": cur.model_endpoint, "instructions": instructions or cur.instructions, "tool_ids": tools,
           "knowledge_tables": tables, "temperature": cur.temperature, "max_iterations": cur.max_iterations}
    meta = {k: a.get(k) for k in ("name", "description", "icon", "category", "handle", "persona", "tagline",
                                   "call_examples", "aliases")}
    if role:
        meta["persona"] = role
    if accroche:
        meta["tagline"] = accroche
    before = {"version": cur.version, "outils": cur.tool_ids, "tables": cur.knowledge_tables,
              "instructions": cur.instructions[:3000], "role": a.get("persona"), "accroche": a.get("tagline")}
    v = p.repo.save_version(a["agent_id"], meta, cfg, p.user, None)
    after = {"version": v, "outils": tools, "tables": tables, "instructions": cfg["instructions"][:3000],
             "role": meta.get("persona"), "accroche": meta.get("tagline")}
    return a["agent_id"], before, after, {"agent": a["name"], "nouvelle_version": v, "statut": a.get("status"),
                                          "outils": tools, "tables": tables}


# --- Outils -----------------------------------------------------------------------------------------------
def concevoir_outil(ctx: ToolContext, demande: str) -> dict:
    p = _p(ctx)
    if not callable(p.tool_designer):
        raise ToolError("Assistant d'outils indisponible.")
    r = p.tool_designer().design(demande)
    if not r.draft:
        return {"brouillon_id": None, "non_realisable": r.unsupported or "Aucune proposition.", "hypotheses": r.hypotheses}
    if r.draft.get("type") not in HAKIM_TOOL_KINDS:
        return {"brouillon_id": None, "type": r.draft.get("type"), "non_realisable": "Type d'outil non pris en charge."}
    did = _new_id(p, "O")
    p.drafts[did] = {"kind": "outil", "draft": r.draft}
    keys = ("tool_id", "name", "type", "description", "parameters", "sql", "function", "connection", "method",
            "path", "query", "body", "headers")
    suite = ("verifier_outil contrôle l'appel (sans l'envoyer) ; tester_appel_http envoie un appel réel après "
             "validation de l'utilisateur ; creer_outil n'est possible qu'après un appel réel réussi."
             if _http_write(r.draft) else
             "verifier_outil exécute un test réel en lecture ; creer_outil n'est possible qu'après un test réussi.")
    return {"brouillon_id": did, "outil_propose": {k: r.draft.get(k) for k in keys if r.draft.get(k) not in (None, "", {})},
            "erreurs": r.check.errors, "avertissements": r.check.warnings, "hypotheses": r.hypotheses,
            "suite": suite}


MAX_CASES = 5


def _run_cases(spec, cases: list[dict], ctx: ToolContext) -> dict:
    """Exécute 1 à MAX_CASES jeux d'arguments ; le test n'est réussi que si TOUS les cas réussissent."""
    results = [tb.run_test(spec, dict(a or {}), ctx) for a in cases[:MAX_CASES]]
    first = dict(results[0])
    if len(results) == 1:
        return first
    return {**first, "ok": all(r.get("ok") for r in results), "nombre_cas": len(results),
            "cas_reussis": sum(1 for r in results if r.get("ok")), "cas": results}


def _cases(default: dict, arguments: dict | None, cas_test: list | None) -> list[dict]:
    cases = [c for c in (cas_test or []) if isinstance(c, dict)]
    if arguments:
        cases.insert(0, arguments)
    return cases or [default]


def verifier_outil(ctx: ToolContext, brouillon_id: str, arguments_test: dict | None = None,
                   cas_test: list | None = None) -> dict:
    p = _p(ctx)
    d = _draft(p, brouillon_id, "outil")
    draft = d["draft"]
    existing = {s.tool_id: s for s in p.repo.list_tools()}
    c = tb.check(draft, existing, p.user, sql=ctx.sql)
    if not c.ok:
        d.pop("test", None)
        return {"ok": False, "erreurs": c.errors, "avertissements": c.warnings}
    if _http_write(draft):              # pas d'envoi sans validation : l'appel réel passe par tester_appel_http
        d.pop("test", None)
        d["checked_fp"] = tb.fingerprint(draft)
        return {"ok": True, "controle": "réussi (connexion, paramètres, compilation)", "appel_reel": "non envoyé",
                "avertissements": c.warnings,
                "suite": f"Appel {draft['method']} : tester_appel_http envoie un appel réel après validation de "
                         "l'utilisateur (il peut créer ou modifier des données dans le service distant)."}
    spec = tb.build_spec(draft, p.user)
    res = _run_cases(spec, _cases(tb.example_args(draft), arguments_test, cas_test), ctx)
    d["test"], d["fp"] = res, tb.fingerprint(draft)
    return {"ok": bool(res.get("ok")), "avertissements": c.warnings, "test": res}


@_written("tester_appel_http", "outil")
def tester_appel_http(ctx, p, brouillon_id: str, arguments: dict | None = None, cas_test: list | None = None) -> tuple:
    """Appel réel d'un brouillon HTTP autre que GET, après fiche de validation. Tracé dans copilot_actions."""
    d = _draft(p, brouillon_id, "outil")
    draft = d["draft"]
    if not _http_write(draft):
        raise ToolError("Réservé aux appels HTTP autres que GET : utilisez verifier_outil.")
    if d.get("checked_fp") != tb.fingerprint(draft):
        raise ToolError("Contrôle requis avant l'appel réel : lancez verifier_outil.")
    spec = tb.build_spec(draft, p.user)
    res = _run_cases(spec, _cases(tb.example_args(draft), arguments, cas_test), ctx)
    d["test"], d["fp"] = res, tb.fingerprint(draft)
    return draft["tool_id"], None, {"test": res}, {"ok": bool(res.get("ok")), "test": res}


def lister_connexions(ctx: ToolContext) -> dict:
    """Connexions HTTP Unity Catalog visibles avec les droits de l'utilisateur (system_* exclues)."""
    _p(ctx)
    try:
        rows = ctx.sql.query("SHOW CONNECTIONS", row_limit=200).get("rows") or []
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"Liste des connexions inaccessible : {str(e)[:300]}") from e
    pick = lambda r, *ks: next((r[k] for k in ks if r.get(k) not in (None, "")), None)  # noqa: E731
    out = []
    for r in rows:
        name, kind = str(pick(r, "name", "connection_name") or ""), str(pick(r, "connection_type", "type") or "")
        if not name or name.lower().startswith("system_") or kind.upper() != "HTTP":
            continue
        out.append({"connexion": name, "type": kind, "proprietaire": pick(r, "owner"),
                    "commentaire": pick(r, "comment")})
    res = {"nombre": len(out), "connexions": out}
    if not out:
        res["note"] = ("Aucune connexion HTTP visible. Sa création (CREATE CONNECTION ... TYPE HTTP) est réservée à un "
                       "administrateur du metastore : indiquez-lui l'hôte, le port, le chemin de base et le type "
                       "d'authentification. Les identifiants restent dans la connexion, jamais dans l'outil.")
    return res


# --- Développement d'outils : fiche, test d'un outil existant, amélioration --------------------------------
def _find_tool(p: Platform, ref: str):
    key = str(ref or "").strip().lower()
    for s in p.repo.list_tools():
        if key in (s.tool_id.lower(), (s.name or "").lower()):
            mine = bool(s.owner) and s.owner == p.user
            if s.status in ("archive", "retire") and not (p.is_admin or mine):
                break
            if s.status == "brouillon" and s.owner and not (p.is_admin or mine):
                break
            return s
    raise ToolError(f"Outil « {ref} » introuvable ou non visible pour vous (lister_outils pour la liste).")


def _loads(v, default=None):
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v) if v else default
    except (TypeError, ValueError):
        return default


def _kind(s) -> str:
    return (s.config or {}).get("type") if tb.is_custom(s) else "intégré"


def decrire_outil(ctx: ToolContext, outil: str) -> dict:
    p = _p(ctx)
    s = _find_tool(p, outil)
    cfg = s.config or {}
    out = {"outil": s.tool_id, "nom": s.name, "categorie": s.category, "type": _kind(s),
           "type_libelle": tb.TYPE_LABELS.get(_kind(s), "Outil intégré (code de la plateforme)"),
           "statut": s.status, "version": s.version, "proprietaire": s.owner or None,
           "lecture_seule": s.read_only, "confirmation": s.requires_confirmation, "identite": s.identity,
           "description": s.description, "parametres": s.input_schema.get("properties") or {},
           "obligatoires": s.input_schema.get("required") or [],
           "modifiable_par_vous": tb.is_custom(s) and s.owner == p.user and s.status != "publie"}
    if tb.is_custom(s):
        out["definition"] = {k: cfg.get(k) for k in ("sql", "function", "kind", "connection", "method", "path",
                                                     "query", "body", "max_rows", "tables") if cfg.get(k) not in (None, "", {}, [])}
        out["exemples"] = cfg.get("examples") or {}
        if p.is_admin or s.owner == p.user:
            vers = []
            for v in p.repo.tool_versions(s.tool_id)[:10]:
                t = _loads(v.get("test_result"), {}) or {}
                vers.append({"version": v.get("version"), "note": v.get("note"), "par": v.get("created_by"),
                             "le": str(v.get("created_at") or "")[:19], "test_ok": t.get("ok"),
                             "test_erreur": (t.get("erreur") or None) and str(t["erreur"])[:300]})
            out["versions"] = vers
    else:
        out["definition"] = "Outil intégré : son code fait partie de la plateforme, il ne se modifie pas ici."
    return out


def tester_outil(ctx: ToolContext, outil: str, arguments: dict | None = None, cas_test: list | None = None) -> dict:
    """Exécute un outil existant (lecture seule uniquement) avec les droits de l'utilisateur. N'écrit rien."""
    p = _p(ctx)
    s = _find_tool(p, outil)
    if not s.read_only or s.requires_confirmation:
        raise ToolError(f"« {s.tool_id} » écrit ou envoie des données : il se teste dans Chat & Test, avec "
                        "validation humaine à chaque appel.")
    if s.status in ("planifie", "indisponible"):
        raise ToolError(f"« {s.tool_id} » n'est pas exécutable (statut : {s.status}).")
    default = (s.config or {}).get("examples") or {}
    res = _run_cases(s, _cases(default, arguments, cas_test), ctx)
    return {"outil": s.tool_id, "statut": s.status, "test": res,
            "note": "Test en lecture seule avec vos droits ; résultat non enregistré."}


def ameliorer_outil(ctx: ToolContext, outil: str, demande: str = "") -> dict:
    """Le copilote d'outils propose une nouvelle version d'un outil créé dont l'utilisateur est propriétaire."""
    p = _p(ctx)
    s = _find_tool(p, outil)
    if not tb.is_custom(s):
        raise ToolError(f"« {s.tool_id} » est un outil intégré : il ne se modifie pas. Proposez plutôt un nouvel "
                        "outil (concevoir_outil).")
    if s.owner != p.user:
        raise ToolError(f"Seul le propriétaire de « {s.tool_id} » peut le modifier.")
    if s.status == "publie":
        raise ToolError(f"« {s.tool_id} » est publié : sa modification se fait dans le Tool Builder "
                        "(onglet Mes outils), pour ne pas interrompre les agents qui l'utilisent.")
    if _kind(s) not in HAKIM_TOOL_KINDS:
        raise ToolError("Type d'outil non pris en charge par HakimAI : modifiez-le dans le Tool Builder.")
    if not callable(p.tool_designer):
        raise ToolError("Assistant d'outils indisponible.")
    current = tb.draft_from_spec(s)
    vers = p.repo.tool_versions(s.tool_id)
    last = _loads(vers[0].get("test_result"), None) if vers else None
    r = p.tool_designer().improve(current, demande, last)
    if not r.draft:
        return {"brouillon_id": None, "non_realisable": r.unsupported or "Aucune proposition.", "hypotheses": r.hypotheses}
    if r.draft.get("type") not in HAKIM_TOOL_KINDS:
        return {"brouillon_id": None, "non_realisable": "Le type proposé n'est pas pris en charge par HakimAI."}
    did = _new_id(p, "O")
    p.drafts[did] = {"kind": "outil", "draft": r.draft, "base": {"tool_id": s.tool_id, "version": s.version}}
    diff = {k: {"avant": current.get(k), "apres": r.draft.get(k)}
            for k in ("name", "description", "sql", "function", "connection", "method", "path", "query", "body",
                      "parameters", "max_rows")
            if current.get(k) != r.draft.get(k)}
    return {"brouillon_id": did, "outil": s.tool_id, "version_actuelle": s.version, "modifications": r.changes,
            "differences": diff, "erreurs": r.check.errors, "avertissements": r.check.warnings,
            "hypotheses": r.hypotheses,
            "suite": "verifier_outil (test réel), puis creer_outil enregistre la nouvelle version en brouillon."}


@_written("creer_outil", "outil")
def creer_outil(ctx, p, brouillon_id: str) -> tuple:
    d = _draft(p, brouillon_id, "outil")
    if not (d.get("test") or {}).get("ok") or d.get("fp") != tb.fingerprint(d["draft"]):
        raise ToolError("Test réussi requis avant l'enregistrement : lancez verifier_outil.")
    cur = next((s for s in p.repo.list_tools() if s.tool_id == d["draft"]["tool_id"]), None)
    if cur is not None and cur.status == "publie":
        raise ToolError(f"« {cur.tool_id} » est publié : sa modification se fait dans le Tool Builder.")
    before = {"version": cur.version, "statut": cur.status} if cur is not None else None
    spec = tb.build_spec(d["draft"], p.user, status="brouillon")
    v = p.repo.save_custom_tool(spec, p.user, d["test"],
                                note="Modifié avec HakimAI" if cur is not None else "Créé avec HakimAI")
    return spec.tool_id, before, {"tool_id": spec.tool_id, "version": v, "statut": "brouillon"}, {
        "outil": spec.tool_id, "version": v, "statut": "brouillon", "nouvelle_version": cur is not None,
        "suite": "Tester dans un agent en brouillon (modifier_agent ajoute l'outil une fois publié), puis publier "
                 "depuis le Tool Builder (onglet Mes outils)."}


# --- Équipes ----------------------------------------------------------------------------------------------
def _find_team(p: Platform, ref: str) -> dict:
    key = str(ref).lstrip("@").lower()
    for t in p.teams.list_teams():
        if key in (t["team_id"], t["handle"].lower(), t["name"].lower()):
            if p.is_admin or t["status"] == "publie" or t.get("owner") == p.user:
                return t
    raise ToolError(f"Équipe « {ref} » introuvable ou non visible pour vous.")


@_written("creer_equipe", "equipe")
def creer_equipe(ctx, p, nom: str, membres: list, mission: str = "", chef: str = "", creer_chef: bool = False,
                 filiere: str = "Transverse", nom_appel: str = "", responsable_humain: str = "") -> tuple:
    ids = [_find_agent(p, m)["agent_id"] for m in membres]
    data = {"name": nom, "handle": nom_appel.lstrip("@"), "mission": mission, "filiere": filiere, "members": ids,
            "primary": ids, "human_owner": responsable_humain,
            "lead_agent_id": _find_agent(p, chef)["agent_id"] if chef else None}
    if creer_chef and not chef:
        check = T.normalize({**data, "lead_agent_id": "en-creation"})
        errs = [e for e in T.validate(check, p.repo.list_agents(), p.teams.list_teams())
                if "Chef d'équipe introuvable" not in e]
        if errs:
            raise ToolError(" ".join(errs))
        data["lead_agent_id"] = p.teams.create_lead(data, p.user)
    tid = p.teams.save(data, p.user, note="Créée avec HakimAI")
    t = next(x for x in p.teams.list_teams() if x["team_id"] == tid)
    after = {k: t.get(k) for k in ("name", "handle", "status", "lead_agent_id", "members", "mission")}
    return tid, None, after, {"equipe": t["name"], "appel": "@" + t["handle"], "statut": t["status"],
                              "chef_cree_en_brouillon": bool(creer_chef and not chef),
                              "suite": "Publication par un administrateur depuis la page Équipes."}


@_written("modifier_equipe", "equipe")
def modifier_equipe(ctx, p, equipe: str, ajouter_membres: list | None = None, retirer_membres: list | None = None,
                    mission: str = "", chef: str = "", responsable_humain: str = "") -> tuple:
    t = _find_team(p, equipe)
    add = [_find_agent(p, m)["agent_id"] for m in (ajouter_membres or [])]
    rem = {_find_agent(p, m)["agent_id"] for m in (retirer_membres or [])}
    members = [m for m in t["members"] if m not in rem] + [m for m in add if m not in t["members"]]
    data = {**t, "members": members, "primary": [m for m in t["primary"] if m in members] + [m for m in add if m not in t["primary"]],
            "mission": mission or t.get("mission"), "human_owner": responsable_humain or t.get("human_owner"),
            "lead_agent_id": _find_agent(p, chef)["agent_id"] if chef else t.get("lead_agent_id")}
    before = {k: t.get(k) for k in ("status", "lead_agent_id", "members", "mission", "human_owner")}
    p.teams.save(data, p.user, note="Modifiée avec HakimAI")
    n = next(x for x in p.teams.list_teams() if x["team_id"] == t["team_id"])
    after = {k: n.get(k) for k in ("status", "lead_agent_id", "members", "mission", "human_owner")}
    return t["team_id"], before, after, {"equipe": n["name"], "statut": n["status"], "membres": len(n["members"]),
                                         "repassee_en_brouillon": before["status"] == "publie" and n["status"] == "brouillon"}


# --- Publication et archivage -----------------------------------------------------------------------------
def _resolve(p: Platform, type_objet: str, objet: str) -> tuple[str, dict]:
    if type_objet == "agent":
        a = _find_agent(p, objet)
        return a["agent_id"], {"nom": a["name"], "statut": a.get("status"), "proprietaire": a.get("owner")}
    if type_objet == "outil":
        s = next((x for x in p.repo.list_tools() if x.tool_id == objet), None)
        if not s:
            raise ToolError(f"Outil « {objet} » introuvable.")
        return s.tool_id, {"nom": s.name, "statut": s.status, "proprietaire": s.owner}
    if type_objet == "equipe":
        t = _find_team(p, objet)
        return t["team_id"], {"nom": t["name"], "statut": t["status"], "proprietaire": t.get("owner")}
    raise ToolError("type_objet : agent, outil ou equipe.")


@_written("soumettre_publication", "demande")
def soumettre_publication(ctx, p, type_objet: str, objet: str, message: str = "") -> tuple:
    oid, info = _resolve(p, type_objet, objet)
    if info["proprietaire"] != p.user:
        raise PermissionError("Seul le propriétaire peut demander la publication.")
    if info["statut"] != "brouillon":
        raise ToolError(f"« {info['nom']} » n'est pas en brouillon (statut : {info['statut']}).")
    aid = audit(p, "demande_publication", type_objet, oid, {"message": message[:500]}, info, None, "en_attente")
    return oid, info, {"demande": aid}, {"objet": info["nom"], "demande": "en attente",
                                         "suite": "Les administrateurs la voient sur la page HakimAI ; "
                                                  "la publication reste faite depuis l'écran de l'objet."}


@_written("archiver", "objet")
def archiver(ctx, p, type_objet: str, objet: str) -> tuple:
    oid, info = _resolve(p, type_objet, objet)
    if type_objet == "agent":
        if info["proprietaire"] != p.user:
            raise PermissionError(f"Seul le propriétaire peut archiver « {info['nom']} ».")
        leads = [t["name"] for t in p.teams.list_teams() if t.get("lead_agent_id") == oid]
        if leads:
            raise ToolError(f"« {info['nom']} » dirige l'équipe {', '.join(leads)} : changez d'abord de chef.")
        p.repo.set_status(oid, "archive")
    elif type_objet == "outil":
        p.repo.set_tool_status(oid, "retire", p.user)
    else:
        p.teams.set_status(oid, "archive", p.user)
    return oid, info, {"statut": "retire" if type_objet == "outil" else "archive"}, {
        "objet": info["nom"], "type": type_objet, "statut": "retiré" if type_objet == "outil" else "archivé"}
