"""Import depuis un dépôt GitHub ou GitLab (étapes 1 à 4 du parcours utilisateur).

1. L'utilisateur colle le lien du dépôt (avec, s'il le souhaite, une branche, une étiquette ou un sous-dossier).
2. L'App dépose une demande git_request.json dans le Volume et lance le Job : le Job (identité et identifiants Git de son
   propriétaire) clone ou met à jour le dépôt dans un dossier Git du workspace et relève le commit exact.
3. Le Job recherche les assistants (assistant.yaml) et les Actions HORIZON, et écrit un instantané dans le Volume.
4. L'App lit l'instantané : l'utilisateur choisit un assistant (ou une Action) et en voit le contenu et les contrôles.
L'App n'a besoin d'aucun nouveau droit : écriture dans le Volume et lancement du Job, comme pour le déploiement."""
from __future__ import annotations

import io
import json
import re
import secrets
import urllib.parse
from datetime import datetime, timezone

import yaml

PROVIDERS = {"github.com": "GitHub", "gitlab.com": "GitLab"}
SEG_RE = re.compile(r"^[A-Za-z0-9._-]+$")
REF_RE = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
REF_TYPES = {"default": "Branche par défaut", "branch": "Branche", "tag": "Étiquette"}


def parse_git_url(url: str, allowed_hosts: list[str]) -> dict:
    """Lien de dépôt, de dossier ou de fichier GitHub/GitLab -> dépôt, branche (si présente) et sous-dossier.
    Ex. https://github.com/o/r/tree/main/assistants -> dépôt o/r, branche main, sous-dossier assistants."""
    u = urllib.parse.urlparse((url or "").strip())
    host = (u.hostname or "").lower()
    if u.scheme != "https":
        raise ValueError("Le lien doit commencer par https://")
    if host not in allowed_hosts:
        raise ValueError(f"Hôte non autorisé : {host or '(vide)'} — autorisés : {', '.join(allowed_hosts)}")
    if u.username or u.password:
        raise ValueError("Le lien ne doit contenir ni identifiant ni jeton")
    parts = [p for p in u.path.split("/") if p]
    ref, sub = None, []
    if "-" in parts:                               # GitLab : <groupe>/<sous-groupe>/<dépôt>/-/tree/<branche>/<dossier>
        i = parts.index("-")
        repo, rest = parts[:i], parts[i + 1:]
    elif host == "github.com":                     # GitHub : <propriétaire>/<dépôt>/tree/<branche>/<dossier>
        repo, rest = parts[:2], parts[2:]
    else:
        repo, rest = parts, []
    if rest and rest[0] in ("tree", "blob") and len(rest) >= 2:
        ref, sub = rest[1], rest[2:]
        if rest[0] == "blob":                      # lien vers un fichier : on garde son dossier
            sub = sub[:-1]
    elif rest:
        raise ValueError("Lien non reconnu : utilisez le lien du dépôt ou d'un dossier (…/tree/<branche>/<dossier>)")
    repo = [p.removesuffix(".git") for p in repo]
    if len(repo) < 2 or not all(SEG_RE.match(p) and p not in (".", "..") for p in repo + sub):
        raise ValueError("Lien de dépôt invalide : attendu https://<hôte>/<propriétaire>/<dépôt>")
    return {"repo_url": f"https://{host}/" + "/".join(repo), "host": host, "repo": "/".join(repo),
            "ref": ref, "subpath": "/".join(sub), "provider": PROVIDERS.get(host, "GitLab (instance interne)")}


def validate_request(ref_type: str, ref: str, subpath: str) -> list[str]:
    errs = []
    if ref_type not in REF_TYPES:
        errs.append("Type de référence inconnu")
    if ref_type != "default" and not REF_RE.match(ref or ""):
        errs.append("Nom de branche ou d'étiquette invalide (lettres, chiffres, . _ - / uniquement)")
    segs = [s for s in (subpath or "").split("/") if s]
    if any(s in (".", "..") or not SEG_RE.match(s) for s in segs):
        errs.append("Sous-dossier invalide")
    return errs


def request_dir(volume_root: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{volume_root.rstrip('/')}/_git/{ts}_{secrets.token_hex(3)}"


def start_fetch(w, job_id: str, volume_root: str, repo_url: str, ref_type: str, ref: str, subpath: str,
                requested_by: str | None) -> tuple[str, int]:
    """Dépose <dossier>/git_request.json puis lance le Job en mode dépôt Git (ni migration ni déploiement)."""
    directory = request_dir(volume_root)
    req = {"repo_url": repo_url, "ref_type": ref_type, "ref": ref if ref_type != "default" else "",
           "subpath": subpath.strip("/"), "requested_by": requested_by,
           "requested_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    w.files.upload(f"{directory}/git_request.json", io.BytesIO(json.dumps(req, ensure_ascii=False).encode("utf-8")),
                   overwrite=True)
    resp = w.api_client.do("POST", "/api/2.1/jobs/run-now", body={
        "job_id": int(job_id),
        "job_parameters": {"action_path": f"{directory}/git_request.json", "deploy": "false"},
    })
    return directory, int(resp["run_id"])


def read_text(w, path: str) -> str:
    return w.files.download(path).contents.read().decode("utf-8")


def read_json(w, path: str) -> dict:
    return json.loads(read_text(w, path))


def commit_url(repo: dict) -> str | None:
    if not repo.get("commit"):
        return None
    sep = "/-/commit/" if "gitlab" in repo.get("host", "") else "/commit/"
    return f"{repo['url']}{sep}{repo['commit']}"


def ref_label(repo: dict) -> str:
    return f"étiquette {repo['tag']}" if repo.get("tag") else f"branche {repo.get('branch') or '?'}"


# ------------------------------------------------------------------ contrôles préliminaires d'un assistant
FUNCTION_ROLES = {"agent": "agent (appel LLM) -> agent.py, code recopié",
                  "indexing": "indexation -> indexation du Job (table des segments + index Vector Search)",
                  "config": "configuration -> model_config.yml"}


def check_functions_package(pkg: dict) -> tuple[list[dict], dict]:
    """Paquet « fonctions » (source_kind: functions) : code Python simple, rôles agent / indexing / config.
    Contrôles préliminaires ; l'analyse complète (faits, comparaisons, dépendances) est faite par le Job."""
    import ast
    m, files = pkg.get("manifest") or {}, pkg.get("files") or {}
    checks = []

    def check(label, ok, detail=""):
        checks.append({"Contrôle": label, "Résultat": "✅" if ok else "❌", "Détail": detail})

    for p in pkg.get("problems") or []:
        check("Fichier cité par le manifeste", False, p)
    check("Version du format", m.get("format_version") == 1, f"format_version = {m.get('format_version')!r} (1 attendu)")
    check("Nom de l'assistant", isinstance(m.get("name"), str) and bool(NAME_RE.match(m["name"])), f"{m.get('name')!r}")
    rows, prompt = [], ""
    entries = [("agent", m.get("agent"))] + [("indexing", i) for i in m.get("indexing") or []] \
        + ([("config", m["config"])] if m.get("config") else [])
    for role, e in entries:
        e = e if isinstance(e, dict) else {}
        ref, fn = e.get("file"), e.get("entrypoint")
        code, err, params = files.get(ref or ""), None, []
        if not code:
            err = f"fichier introuvable : {ref!r}"
        else:
            try:
                tree = ast.parse(code)
                node = next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                             and n.name == fn), None)
                if node is None:
                    err = f"fonction {fn!r} introuvable"
                else:
                    params = [a.arg for a in node.args.args]
                if role == "agent" and not err:
                    if not any(isinstance(n, ast.Call) and ast.unparse(n.func).endswith("serving_endpoints.query")
                               for n in ast.walk(node)):
                        err = "aucun appel serving_endpoints.query"
                    prompt = next((n.value.value for n in tree.body if isinstance(n, ast.Assign)
                                   and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
                                   and any(isinstance(t, ast.Name) and "PROMPT" in t.id for t in n.targets)), "")
            except SyntaxError as ex:
                err = f"erreur de syntaxe ligne {ex.lineno} : {ex.msg}"
        check(f"{role.capitalize()} {ref}", err is None, err or f"{fn}({', '.join(params)})")
        rows.append({"name": fn, "file": ref, "description": FUNCTION_ROLES[role], "facts": None, "role": role})
    check("Fonction agent", isinstance(m.get("agent"), dict), "clé agent (file, entrypoint, env)")
    check("Chaîne d'indexation", bool(m.get("indexing")), f"{len(m.get('indexing') or [])} fonction(s)")
    tests = {}
    if m.get("tests_file"):
        try:
            tests = yaml.safe_load(files.get(m["tests_file"], "")) or {}
            check(f"YAML {m['tests_file']}", bool(tests.get("cases")), f"{len(tests.get('cases') or [])} cas")
        except yaml.YAMLError as ex:
            check(f"YAML {m['tests_file']}", False, str(ex)[:200])
    agent = m.get("agent") if isinstance(m.get("agent"), dict) else {}
    info = {"prompt": prompt, "config": {}, "config_text": yaml.safe_dump({"env": agent.get("env") or {}},
                                                                           allow_unicode=True, sort_keys=False),
            "tests": tests, "n_tool_tests": len(tests.get("cases") or []), "n_conversations": 0,
            "llm": {"name": agent.get("entrypoint"), "source": agent.get("file"), "facts": None},
            "actions": rows, "kind": "functions", "ok": all(c["Résultat"] == "✅" for c in checks)}
    return checks, info


def check_package(pkg: dict, extract_facts) -> tuple[list[dict], dict]:
    """Contrôles du paquet (mêmes règles que migrator.assistant.validate_package) et analyse de chaque Action.
    Renvoie (contrôles [{Contrôle, Résultat, Détail}], infos {prompt, config, tests, llm, actions})."""
    if (pkg.get("manifest") or {}).get("source_kind") == "functions":
        return check_functions_package(pkg)
    m, files = pkg.get("manifest") or {}, pkg.get("files") or {}
    checks = []

    def check(label: str, ok: bool, detail: str = ""):
        checks.append({"Contrôle": label, "Résultat": "✅" if ok else "❌", "Détail": detail})

    for p in pkg.get("problems") or []:
        check("Fichier cité par le manifeste", False, p)
    check("Version du format", m.get("format_version") == 1, f"format_version = {m.get('format_version')!r} (1 attendu)")
    check("Nom de l'assistant", isinstance(m.get("name"), str) and bool(NAME_RE.match(m["name"])),
          f"{m.get('name')!r} (minuscules, chiffres et _)")
    prompt = (files.get(m.get("system_prompt_file") or "") or "").strip()
    check("Prompt système", bool(prompt), f"{len(prompt)} caractères" if prompt else f"absent : {m.get('system_prompt_file')!r}")
    orch = m.get("orchestration") or {}
    check("Mode d'orchestration", orch.get("mode") == "llm_tools", f"{orch.get('mode')!r} (seul llm_tools est généré)")
    mtc = orch.get("max_tool_calls", 5)
    check("Appels d'outils maximum", isinstance(mtc, int) and 1 <= mtc <= 20, f"{mtc!r} (entre 1 et 20)")

    def analyse(code: str, ref: str):
        try:
            f = extract_facts(code, ref)
        except SyntaxError as e:
            return None, f"erreur de syntaxe ligne {e.lineno} : {e.msg}"
        eps = f["entrypoints"]
        if len(eps) != 1:
            return f, f"{len(eps)} fonction(s) RunContext, 1 attendue"
        return f, None

    llm = m.get("llm") or {}
    llm_info = {"source": llm.get("source") or llm.get("action"), "facts": None, "name": None}
    code = files.get(llm.get("action") or "")
    if code:
        f, err = analyse(code, "llm_action.py")
        llm_info["facts"] = f
        if not err and not f["llm_calls"]:
            err = "aucun appel LLM détecté"
        llm_info["name"] = f["entrypoints"][0]["name"] if f and len(f["entrypoints"]) == 1 else None
        check("Action LLM", err is None, err or f"{llm_info['name']} ({llm_info['source']})")
    else:
        check("Action LLM", False, f"introuvable : {llm_info['source']!r}")

    actions, names = [], {llm_info["name"]} - {None}
    entries = m.get("actions") or []
    check("Actions métier", bool(entries), f"{len(entries)} déclarée(s)")
    for a in entries:
        ref, desc = a.get("file"), str(a.get("description") or "").strip()
        row = {"file": ref, "description": desc, "facts": None, "name": None}
        if ref not in files:
            actions.append(row)
            continue
        f, err = analyse(files[ref], ref)
        row["facts"] = f
        if not err:
            row["name"] = f["entrypoints"][0]["name"]
            if row["name"] in names:
                err = f"nom d'outil en double : {row['name']}"
            names.add(row["name"])
        if not desc:
            err = (err + " ; " if err else "") + "description absente (c'est elle que lit le LLM)"
        check(f"Action {ref}", err is None, err or f"outil {row['name']}")
        actions.append(row)

    parsed = {}
    for key in ("config_file", "tests_file"):
        ref = m.get(key)
        if not ref:
            parsed[key] = {}
            continue
        try:
            parsed[key] = yaml.safe_load(files.get(ref, "")) or {}
            check(f"YAML {ref}", isinstance(parsed[key], dict), "lisible")
        except yaml.YAMLError as e:
            parsed[key] = {}
            check(f"YAML {ref}", False, str(e)[:200])
    tests = parsed["tests_file"] if isinstance(parsed["tests_file"], dict) else {}
    unknown = [t for t in (tests.get("actions") or {}) if t not in names]
    if unknown:
        check("Tests", False, f"tests pour des Actions inconnues : {unknown}")
    n_tool = sum(len(v or []) for v in (tests.get("actions") or {}).values())
    n_conv = len(tests.get("conversations") or [])
    info = {"prompt": prompt, "config": parsed["config_file"], "config_text": files.get(m.get("config_file") or "", ""),
            "tests": tests, "n_tool_tests": n_tool, "n_conversations": n_conv, "llm": llm_info, "actions": actions,
            "ok": all(c["Résultat"] == "✅" for c in checks)}
    return checks, info
