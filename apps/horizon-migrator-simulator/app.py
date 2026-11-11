"""Simulateur de migration HORIZON -> Databricks (Databricks App, Streamlit).

Etapes 1 a 3 : calculees localement (analyse statique ; l'Action n'est jamais executee, aucun LLM).
Etapes 4 a 6 : agent migrateur sur Model Serving (generation, validation, tests).
Etape 7 : deploiement a blanc (aucune ressource creee). Etape 8 : historique de la session."""
import io
import json
import os
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml
from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config

import deploy_job as DJ
import git_import as GI
from h2d_facts import extract_facts
from mapping import check_model_mapping, config_endpoints, external_services, planned_mapping

MIGRATOR_ENDPOINT = os.getenv("MIGRATOR_ENDPOINT", "agents_dataops_dev-knowledge-horizon_migrator_agent")
DEPLOY_JOB_ID = os.getenv("DEPLOY_JOB_ID", "231540374932312")
UC_SCHEMA = os.getenv("UC_SCHEMA", "dataops_dev.knowledge")
# Volume où l'App dépose l'Action et le projet relu avant de lancer le Job de déploiement
DEPLOY_VOLUME = os.getenv("DEPLOY_VOLUME", "/Volumes/dataops_dev/knowledge/horizon_migrations")
DEPLOY_POLL_S = 10
DEPLOY_MAX_WAIT_S = 40 * 60
# Import depuis GitHub / GitLab : hôtes autorisés (le Job refait le contrôle avec sa propre liste)
GIT_ALLOWED_HOSTS = [h.strip().lower() for h in os.getenv("GIT_ALLOWED_HOSTS", "github.com,gitlab.com").split(",") if h.strip()]
GIT_POLL_S = 3
GIT_MAX_WAIT_S = 30 * 60   # inclut l'attente éventuelle derrière un déploiement (une exécution du Job à la fois)
EXAMPLES = Path(__file__).parent / "examples"
# Actions réelles lues dans le workspace (le code SNCF reste dans Databricks, il n'est pas copié dans Git).
# L'identité de l'App doit avoir le droit CAN_READ sur chaque fichier.
WORKSPACE_EXAMPLES = [p.strip() for p in os.getenv("WORKSPACE_EXAMPLES", "").split(",") if p.strip()]
EXPECTED_FILES = ["agent.py", "model_config.yml", "requirements.txt", "tests.json",
                  "MIGRATION_NOTES.md", "MIGRATION_REPORT.md", "facts.json"]

STEPS = [
    ("import", "1. Import"),
    ("analyse", "2. Analyse statique"),
    ("mapping", "3. Correspondance"),
    ("generation", "4. Code généré"),
    ("tests", "5. Tests"),
    ("simulation", "6. Simulation"),
    ("deploiement", "7. Déploiement"),
    ("historique", "8. Historique"),
]
ORDER = [k for k, _ in STEPS]
LABEL = dict(STEPS)
# Phases indicatives affichées pendant l'appel au migrateur (durées observées : 70 à 80 s)
PHASES = [(0, "Envoi de l'Action à l'agent migrateur"),
          (5, "Génération du code avec Claude Sonnet"),
          (65, "Validation statique et tests de l'agent généré"),
          (95, "Correction automatique (tentative supplémentaire)")]

st.set_page_config(page_title="Simulateur de migration HORIZON -> Databricks", page_icon="🔁", layout="wide")
ss = st.session_state
for _k, _v in {"step": "import", "code": None, "source_name": None, "facts": None, "mapping": None,
               "result": None, "error": None, "history": [], "deploy": None,
               "git": None, "git_disc": None, "assistant": None}.items():
    ss.setdefault(_k, _v)


# ---------------------------------------------------------------- utilitaires
@st.cache_resource
def client() -> WorkspaceClient:
    # Timeout HTTP long : une migration dure 1 à 2 min, plus le redémarrage éventuel de l'endpoint
    return WorkspaceClient(config=Config(http_timeout_seconds=900, retry_timeout_seconds=900))


def action_name() -> str:
    eps = (ss.facts or {}).get("entrypoints") or []
    return eps[0]["name"].lower() if eps else "action"


def target_names() -> tuple[str, str]:
    uc_model = f"{UC_SCHEMA}.horizon_{action_name()}_agent"
    return uc_model, "agents_" + uc_model.replace(".", "-")


def step_done(key: str) -> bool:
    r = ss.result or {}
    return {
        "import": ss.code is not None or ss.assistant is not None,
        "analyse": ss.facts is not None,
        "mapping": ss.mapping is not None,
        "generation": bool(r.get("files")),
        "tests": bool(r.get("tests")),
        "simulation": "tests.json" in (r.get("files") or {}),
        "deploiement": bool(ss.deploy and ss.deploy["status"].get("result_state") == "SUCCESS"),
        "historique": bool(ss.history),
    }[key]


def verdict() -> tuple[str, list[str]]:
    """Points bloquants avant un déploiement réel."""
    r = ss.result or {}
    issues = []
    if r.get("status") != "VALIDÉ":
        issues.append(f"Statut du migrateur : {r.get('status') or 'aucun'} (VALIDÉ attendu)")
    failed = [t for t in r.get("tests") or [] if not t.get("ok")]
    if failed:
        issues.append(f"{len(failed)} test(s) en échec")
    bad = [c for c in r.get("model_checks") or [] if not c["Équivalent"]]
    if bad:
        issues.append("Correspondances de modèles non équivalentes : "
                      + ", ".join(f"{c['Modèle source']} -> {c['Endpoint Databricks']}" for c in bad))
    missing = [f for f in EXPECTED_FILES if f not in (r.get("files") or {})]
    if missing:
        issues.append(f"Fichiers absents : {', '.join(missing)}")
    return ("Prêt au déploiement" if not issues else "Bloqué"), issues


def load_action(code: str, source_name: str) -> bool:
    try:
        facts = extract_facts(code, source_name)
    except SyntaxError as e:
        st.error(f"Code Python invalide (ligne {e.lineno}) : {e.msg}")
        return False
    if not facts["entrypoints"]:
        st.error("Aucune Action HORIZON trouvée : il faut une fonction dont un paramètre est annoté `RunContext`.")
        return False
    ss.code, ss.source_name, ss.facts = code, source_name, facts
    ss.mapping = planned_mapping(facts)
    ss.result = ss.error = ss.deploy = None
    ss.assistant = None
    return True


def call_migrator(placeholder) -> dict:
    """Appelle l'agent migrateur dans un thread et affiche la phase estimée et le temps écoulé."""
    w, code, box = client(), ss.code, {}

    def work():
        try:
            box["resp"] = w.api_client.do(
                "POST", f"/serving-endpoints/{MIGRATOR_ENDPOINT}/invocations",
                body={"input": [{"role": "user", "content": f"```python\n{code}\n```"}]})
        except Exception as e:  # noqa: BLE001 - affiché à l'utilisateur
            box["error"] = e

    t = threading.Thread(target=work, daemon=True)
    t0 = time.time()
    t.start()
    while t.is_alive():
        el = time.time() - t0
        phase = [label for start, label in PHASES if el >= start][-1]
        placeholder.markdown(f"⏳ **{phase}** _(phase estimée)_ — {int(el)} s écoulées")
        time.sleep(1)
    placeholder.empty()
    if "error" in box:
        raise box["error"]
    resp = box["resp"]
    out = resp.get("custom_outputs") or {}
    files = out.get("files") or {}
    try:
        cfg = yaml.safe_load(files.get("model_config.yml", "")) or {}
    except yaml.YAMLError:
        cfg = {}
    text = "".join(p.get("text", "") for it in resp.get("output", []) for p in (it.get("content") or []))
    return {"status": out.get("status"), "attempts": out.get("attempts"),
            "duration_s": out.get("duration_s") or round(time.time() - t0, 1),
            "tests": out.get("tests") or [], "files": files, "config": cfg,
            "model_checks": check_model_mapping(cfg), "text": text}


def run_generation(placeholder) -> None:
    try:
        ss.result, ss.error = call_migrator(placeholder), None
    except Exception as e:  # noqa: BLE001
        ss.result, ss.error = None, f"{type(e).__name__}: {str(e)[:600]}"
        return
    r = ss.result
    v, _ = verdict()
    ss.history.append({
        "Heure": datetime.now().strftime("%H:%M:%S"), "Action": action_name(), "Source": ss.source_name,
        "Statut migrateur": r["status"], "Tentatives": r["attempts"], "Durée (s)": r["duration_s"],
        "Tests réussis": f"{sum(bool(t.get('ok')) for t in r['tests'])}/{len(r['tests'])}",
        "Modèles non équivalents": sum(not c["Équivalent"] for c in r["model_checks"]),
        "Verdict": v,
    })


def files_zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(f"{action_name()}_agent/{name}", content)
    return buf.getvalue()


@st.cache_data(ttl=600, show_spinner=False)
def read_workspace_file(path: str) -> str:
    import base64
    from databricks.sdk.service.workspace import ExportFormat
    resp = client().workspace.export(path, format=ExportFormat.SOURCE)
    return base64.b64decode(resp.content).decode("utf-8")


def example_options() -> list[tuple[str, str, str]]:
    """(libellé, origine, chemin) : Actions réelles du workspace d'abord, puis exemples fictifs embarqués."""
    opts = [(f"{Path(p).stem} — Action réelle HORIZON (workspace)", "workspace", p) for p in WORKSPACE_EXAMPLES]
    opts += [(f"{p.stem} — exemple fictif", "local", str(p)) for p in sorted(EXAMPLES.glob("*.py"))]
    return opts


def read_example(option: tuple[str, str, str]) -> str:
    _, origin, path = option
    return read_workspace_file(path) if origin == "workspace" else Path(path).read_text(encoding="utf-8")


def need(condition: bool, message: str) -> bool:
    if not condition:
        st.info(message)
    return condition


# ---------------------------------------------------------------- simulation complète
def simulate_all() -> None:
    """Enchaîne les 8 étapes avec un suivi visuel de chacune."""
    f = ss.facts
    with st.status(LABEL["import"], state="complete"):
        st.write(f"Action `{action_name()}` chargée depuis **{ss.source_name}** ({len(ss.code.splitlines())} lignes).")
    with st.status(LABEL["analyse"], state="running") as s:
        time.sleep(0.6)
        st.write(f"{len(f['inputs'])} entrées, {len(f['outputs'])} sorties, {len(f['error_codes'])} codes d'erreur, "
                 f"{len(f['llm_calls'])} appel(s) LLM, {len(f['http_calls'])} appel(s) externe(s), "
                 f"{len(f['internal_imports'])} dépendance(s) HORIZON.")
        s.update(state="complete")
    with st.status(LABEL["mapping"], state="running") as s:
        time.sleep(0.6)
        counts = pd.Series([r["Statut prévu"] for r in ss.mapping]).value_counts().to_dict()
        st.write(" | ".join(f"{k} : {v}" for k, v in counts.items()))
        s.update(state="complete")
    with st.status(LABEL["generation"], state="running", expanded=True) as s:
        run_generation(st.empty())
        if ss.error:
            st.error(ss.error)
            s.update(label=f"{LABEL['generation']} — échec", state="error")
            return
        r = ss.result
        st.write(f"Statut **{r['status']}** en {r['attempts']} tentative(s), {r['duration_s']} s.")
        s.update(state="complete" if r["status"] == "VALIDÉ" else "error")
    r = ss.result
    ok = sum(bool(t.get("ok")) for t in r["tests"])
    with st.status(f"{LABEL['tests']} — {ok}/{len(r['tests'])} réussis",
                   state="complete" if r["tests"] and ok == len(r["tests"]) else "error"):
        st.write(", ".join(t["name"] for t in r["tests"] if not t.get("ok")) or "Aucun échec.")
    n_cases = len(json.loads(r["files"].get("tests.json", "{}")).get("cases", [])) if "tests.json" in r["files"] else 0
    with st.status(f"{LABEL['simulation']} — {n_cases} scénario(s) rejouables", state="complete"):
        st.write("Détail des requêtes et des résultats à l'étape 6.")
    v, issues = verdict()
    with st.status(f"{LABEL['deploiement']} — {v}", state="complete" if not issues else "error"):
        for i in issues or ["Aucun point bloquant : le déploiement réel se lance à l'étape 7, après confirmation."]:
            st.write(f"- {i}")
    with st.status(f"{LABEL['historique']} — {len(ss.history)} migration(s) dans la session", state="complete"):
        st.write("Voir l'étape 8.")


# ---------------------------------------------------------------- import depuis un dépôt Git (étapes 1 à 4 du parcours)
def current_user() -> str | None:
    try:
        return st.context.headers.get("X-Forwarded-Email")
    except Exception:  # noqa: BLE001 - version de Streamlit sans st.context
        return None


def git_running() -> bool:
    g = ss.git
    return bool(g) and not DJ.is_finished(g["status"]) and time.time() - g["started"] < GIT_MAX_WAIT_S


def start_git_fetch(parsed: dict, ref_type: str, ref: str, subpath: str) -> None:
    w = client()
    try:
        directory, run_id = GI.start_fetch(w, DEPLOY_JOB_ID, DEPLOY_VOLUME, parsed["repo_url"], ref_type, ref, subpath,
                                           current_user())
        status = DJ.run_status(w, run_id)
    except Exception as e:  # noqa: BLE001 - droits manquants, Volume absent...
        st.error(f"Lancement impossible : {type(e).__name__}: {str(e)[:500]}")
        return
    ss.git = {"run_id": run_id, "directory": directory, "started": time.time(), "status": status, "parsed": parsed,
              "ref_type": ref_type, "ref": ref, "subpath": subpath}
    ss.git_disc = None


def load_discovery() -> None:
    """Lit discovery.json (écrit par le Job, y compris en cas d'échec) et l'ajoute à l'historique."""
    g, w = ss.git, client()
    try:
        ss.git_disc = GI.read_json(w, f"{g['directory']}/discovery.json")
    except Exception as e:  # noqa: BLE001 - le Job a échoué avant d'écrire le fichier
        s = g["status"]
        ss.git_disc = {"ok": False, "error": (s.get("error") or s.get("message") or f"{type(e).__name__}: {e}")[:800]}
    d = ss.git_disc
    repo = d.get("repo") or {}
    ss.history.append({
        "Heure": datetime.now().strftime("%H:%M:%S"), "Action": f"(dépôt) {g['parsed']['repo']}",
        "Source": f"{repo.get('url', g['parsed']['repo_url'])}@{(repo.get('commit') or '?')[:7]}",
        "Verdict": (f"Dépôt récupéré : {len(d.get('packages') or [])} assistant(s), {len(d.get('actions') or [])} Action(s)"
                    if d.get("ok") else "Échec de la récupération"),
        "Exécution du Job": g["run_id"],
    })


def follow_git() -> None:
    """Étape 2 : suit l'exécution du Job (clonage ou mise à jour, relevé du commit, recherche)."""
    g, w = ss.git, client()
    ph = st.empty()
    hints = {"QUEUED": "en file d'attente : une autre exécution du Job est en cours (un déploiement dure 10 à 25 min)",
             "PENDING": "démarrage du calcul serverless", "RUNNING": "clonage ou mise à jour du dépôt, puis recherche",
             "TERMINATING": "fin de l'exécution"}
    while git_running():
        s = g["status"]
        el = int(time.time() - g["started"])
        ph.info(f"⏳ **Étape 2 — Récupération du dépôt** `{g['parsed']['repo']}` — "
                f"{hints.get(s['life_cycle_state'], s['life_cycle_state'])} — {el // 60} min {el % 60:02d} s  \n"
                f"Exécution du Job [{g['run_id']}]({s.get('url')}) — habituellement 20 à 60 s.")
        time.sleep(GIT_POLL_S)
        try:
            g["status"] = DJ.run_status(w, g["run_id"])
        except Exception as e:  # noqa: BLE001 - erreur réseau passagère
            ph.warning(f"Lecture de l'état impossible ({type(e).__name__}), nouvel essai…")
    ph.empty()
    if DJ.is_finished(g["status"]):
        load_discovery()
    st.rerun()


def open_assistant(summary: dict) -> None:
    try:
        pkg = GI.read_json(client(), summary["package_file"])
    except Exception as e:  # noqa: BLE001
        st.error(f"Lecture de l'instantané impossible : {type(e).__name__}: {str(e)[:300]}")
        return
    ss.assistant = {"pkg": pkg, "summary": summary, "repo": ss.git_disc["repo"]}
    # Nouvel objet de migration : on oublie l'Action éventuellement chargée auparavant
    ss.code = ss.source_name = ss.facts = ss.mapping = ss.result = ss.error = ss.deploy = None


def open_git_action(a: dict) -> None:
    repo = ss.git_disc["repo"]
    try:
        code = GI.read_text(client(), a["snapshot"])
    except Exception as e:  # noqa: BLE001
        st.error(f"Lecture de l'instantané impossible : {type(e).__name__}: {str(e)[:300]}")
        return
    if load_action(code, f"{repo['url']}@{repo['commit'][:7]}:{a['path']}"):
        ss.step = "analyse"
        st.rerun()


def render_git_results() -> None:
    """Étapes 3 et 4 : résultat de la recherche, puis choix d'un assistant ou d'une Action."""
    d = ss.git_disc
    if not d.get("ok"):
        st.error(f"Récupération en échec : {d.get('error')}")
        st.caption("Causes fréquentes : lien erroné, dépôt privé sans identifiant Git du propriétaire du Job pour cet hôte, "
                   "branche ou étiquette inconnue, hôte injoignable depuis Databricks (GitLab interne).")
        return
    repo = d["repo"]
    st.success(f"Dépôt récupéré : **{repo['url']}** — {GI.ref_label(repo)} — commit "
               f"[`{repo['commit'][:12]}`]({GI.commit_url(repo)}) — {repo['fetched_at']}")
    st.caption(f"Dossier Git du workspace : `{repo['workspace_path']}` — instantané : `{ss.git['directory']}`. "
               "La suite de la migration utilise uniquement cet instantané (commit figé).")
    st.markdown("**Étape 3 — Recherche dans le dépôt**")
    loose = [a for a in d["actions"] if not a.get("package")]
    c = st.columns(4)
    c[0].metric("Assistants (assistant.yaml)", len(d["packages"]))
    c[1].metric("Actions dans un assistant", len(d["actions"]) - len(loose))
    c[2].metric("Actions isolées", len(loose))
    c[3].metric("Fichiers parcourus", d["stats"]["files_scanned"])
    if d["stats"].get("truncated"):
        st.warning("Limite de fichiers atteinte : précisez un sous-dossier pour une recherche complète.")
    if d["packages"]:
        st.dataframe(pd.DataFrame([{"Dossier": p["path"], "Assistant": p.get("name"), "Actions": p.get("n_actions"),
                                    "État": "✅ lisible" if p["ok"] else "❌ " + "; ".join(p["problems"])}
                                   for p in d["packages"]]), hide_index=True, use_container_width=True)
    if d["actions"]:
        with st.expander(f"Actions HORIZON trouvées ({len(d['actions'])})"):
            st.dataframe(pd.DataFrame([{"Fichier": a["path"], "Point d'entrée": a["entrypoint"], "Lignes": a["lines"],
                                        "Assistant": a.get("package") or "(isolée)"} for a in d["actions"]]),
                         hide_index=True, use_container_width=True)
    if not d["packages"] and not d["actions"]:
        st.warning("Aucun assistant (assistant.yaml) ni Action HORIZON (fonction avec un paramètre RunContext) trouvé.")
        return
    st.markdown("**Étape 4 — Choix de l'objet à migrer**")
    left, right = st.columns(2)
    with left:
        usable = [p for p in d["packages"] if p.get("package_file")]
        if usable:
            p = st.selectbox("Assistant", usable, format_func=lambda x: f"{x.get('name') or '?'} — {x['path']}")
            if st.button("Ouvrir cet assistant", type="primary"):
                open_assistant(p)
                st.rerun()
    with right:
        if d["actions"]:
            a = st.selectbox("Ou une Action seule", d["actions"], format_func=lambda x: f"{x['entrypoint']} — {x['path']}")
            if st.button("Migrer cette Action seule"):
                open_git_action(a)


def _facts_row(name, ref, desc, f) -> dict:
    f = f or {}
    return {"Outil": name or "—", "Fichier": ref, "Description (lue par le LLM)": desc,
            "Entrées": ", ".join(f.get("inputs") or []), "Sorties": ", ".join(o["name"] for o in f.get("outputs") or []),
            "Codes d'erreur": ", ".join(f.get("error_codes") or []), "Appels LLM": len(f.get("llm_calls") or []),
            "Appels externes": len(f.get("http_calls") or [])}


def render_assistant_detail() -> None:
    """Étape 4 (suite) : contenu de l'assistant choisi et contrôles préliminaires (mêmes règles que le migrateur)."""
    a = ss.assistant
    pkg, repo = a["pkg"], a["repo"]
    m, files = pkg["manifest"], pkg["files"]
    checks, info = GI.check_package(pkg, extract_facts)
    st.divider()
    st.markdown(f"### Assistant `{m.get('name')}`")
    if m.get("description"):
        st.write(str(m["description"]).strip())
    st.caption(f"Source : [{repo['url']}]({repo['url']}) — {GI.ref_label(repo)} — commit "
               f"[`{repo['commit'][:12]}`]({GI.commit_url(repo)}) — dossier `{a['summary']['path']}`")
    bad = [c for c in checks if c["Résultat"] != "✅"]
    if bad:
        st.error(f"Contrôles préliminaires : {len(bad)} point(s) bloquant(s) — " + " ; ".join(f"{c['Contrôle']} : {c['Détail']}" for c in bad))
    else:
        st.success(f"Contrôles préliminaires : {len(checks)}/{len(checks)} conformes")
    c = st.columns(4)
    c[0].metric("Actions métier (outils)", len(info["actions"]))
    c[1].metric("Appels d'outils max", (m.get("orchestration") or {}).get("max_tool_calls", 5))
    c[2].metric("Tests d'Actions", info["n_tool_tests"])
    c[3].metric("Conversations de test", info["n_conversations"])
    tabs = st.tabs(["Prompt système", "Actions", "Action LLM", "Configuration", "Contrôles", "Manifeste"])
    with tabs[0]:
        st.caption("Recopié mot pour mot dans l'agent (clé system_prompt de model_config.yml).")
        st.code(info["prompt"] or "(absent)", language="markdown")
    with tabs[1]:
        st.dataframe(pd.DataFrame([_facts_row(x["name"], x["file"], x["description"], x["facts"]) for x in info["actions"]]),
                     hide_index=True, use_container_width=True)
        for x in info["actions"]:
            if x["file"] in files:
                with st.expander(f"Code de {x['file']}"):
                    st.code(files[x["file"]], language="python")
    with tabs[2]:
        llm = info["llm"]
        st.write(f"Action LLM : **{llm['name'] or '?'}** — source `{llm['source']}` — devient la boucle de l'agent.")
        st.dataframe(pd.DataFrame([_facts_row(llm["name"], llm["source"], "", llm["facts"])]).drop(
            columns=["Description (lue par le LLM)"]), hide_index=True, use_container_width=True)
        if (m.get("llm") or {}).get("action") in files:
            with st.expander("Code de l'Action LLM"):
                st.code(files[m["llm"]["action"]], language="python")
    with tabs[3]:
        st.code(info["config_text"] or "(aucune configuration)", language="yaml")
    with tabs[4]:
        st.dataframe(pd.DataFrame(checks), hide_index=True, use_container_width=True)
    with tabs[5]:
        st.code(yaml.safe_dump(m, allow_unicode=True, sort_keys=False), language="yaml")
    st.info("Suite du parcours (génération et tests de l'assistant, puis déploiement par le Job) : en cours de développement. "
            "Une Action seule du dépôt se migre déjà de bout en bout (bouton « Migrer cette Action seule »).")


def render_git_import() -> None:
    """Étape 1 : lien du dépôt ; puis étapes 2 à 4 selon l'avancement."""
    st.markdown("**Étape 1 — Lien du dépôt GitHub ou GitLab**")
    url = st.text_input("Lien du dépôt ou d'un dossier", key="git_url",
                        placeholder="https://github.com/<propriétaire>/<dépôt>  ou  …/tree/<branche>/<dossier>")
    parsed = None
    if url.strip():
        try:
            parsed = GI.parse_git_url(url, GIT_ALLOWED_HOSTS)
        except ValueError as e:
            st.error(str(e))
    types = list(GI.REF_TYPES)
    c1, c2, c3 = st.columns([1, 1, 2])
    ref_type = c1.selectbox("Version", types, index=types.index("branch" if parsed and parsed["ref"] else "default"),
                            format_func=GI.REF_TYPES.get)
    ref = c2.text_input("Nom de la branche ou de l'étiquette", value=(parsed or {}).get("ref") or "",
                        disabled=ref_type == "default")
    subpath = c3.text_input("Sous-dossier (facultatif)", value=(parsed or {}).get("subpath") or "")
    problems = GI.validate_request(ref_type, ref, subpath) if parsed else []
    for p in problems:
        st.error(p)
    if parsed:
        st.caption(f"Dépôt **{parsed['repo']}** ({parsed['provider']}). Le dépôt est récupéré par le Job "
                   f"[{DEPLOY_JOB_ID}]({client().config.host}/jobs/{DEPLOY_JOB_ID}) avec les identifiants Git de son "
                   "propriétaire ; le commit exact est relevé pour la traçabilité. Aucun jeton n'est saisi dans l'App.")
    if st.button("Récupérer le dépôt", type="primary", disabled=not parsed or bool(problems) or git_running()):
        start_git_fetch(parsed, ref_type, ref.strip(), subpath.strip())
        st.rerun()
    if not ss.git:
        return
    if git_running():
        follow_git()
        return
    if ss.git_disc is None:
        if DJ.is_finished(ss.git["status"]):
            load_discovery()
        else:
            st.warning(f"Suivi interrompu après {GIT_MAX_WAIT_S // 60} min : l'exécution [{ss.git['run_id']}]"
                       f"({ss.git['status'].get('url')}) continue dans le Job.")
            return
    st.markdown("**Étape 2 — Récupération du dépôt**")
    el = (ss.git["status"].get("end_time") or 0) - (ss.git["status"].get("start_time") or 0)
    st.caption(f"Exécution du Job [{ss.git['run_id']}]({ss.git['status'].get('url')}) — "
               f"{ss.git['status'].get('result_state')} en {max(el, 0) // 1000} s.")
    render_git_results()
    if ss.assistant is not None:
        render_assistant_detail()


# ---------------------------------------------------------------- écrans
def render_import():
    st.subheader(LABEL["import"])
    st.caption("Le code HORIZON est analysé sans être exécuté. Depuis un dépôt Git : assistants (prompt, configuration et "
               "Actions) ou Actions seules. Les Actions d'exemple réelles sont lues dans le workspace Databricks.")
    tab_git, tab_ex, tab_paste, tab_file = st.tabs(["Dépôt Git", "Exemple", "Coller le code", "Déposer un fichier"])
    with tab_git:
        render_git_import()
    with tab_ex:
        options = example_options()
        if options:
            choice = st.selectbox("Exemple", options, format_func=lambda o: o[0])
            try:
                example_code = read_example(choice)
            except Exception as e:  # noqa: BLE001 - droit de lecture manquant, fichier déplacé...
                st.error(f"Lecture impossible de `{choice[2]}` : {type(e).__name__}: {str(e)[:300]}")
                st.caption("Vérifiez que l'identité de l'App a le droit CAN_READ sur ce fichier.")
                example_code = None
            if example_code is not None:
                with st.expander(f"Voir le code ({len(example_code.splitlines())} lignes)"):
                    st.code(example_code, language="python")
                if st.button("Charger cet exemple", type="primary"):
                    if load_action(example_code, choice[0]):
                        ss.step = "analyse"
                        st.rerun()
    with tab_paste:
        pasted = st.text_area("Code Python de l'Action HORIZON", height=360)
        if st.button("Analyser ce code", disabled=not pasted.strip()):
            if load_action(pasted, "code collé"):
                ss.step = "analyse"
                st.rerun()
    with tab_file:
        up = st.file_uploader("Fichier .py", type=["py"])
        if up is not None and st.button("Analyser ce fichier"):
            if load_action(up.getvalue().decode("utf-8"), up.name):
                ss.step = "analyse"
                st.rerun()


def render_analyse():
    st.subheader(LABEL["analyse"])
    if not need(ss.facts is not None, "Importez d'abord une Action (étape 1)."):
        return
    f = ss.facts
    cols = st.columns(6)
    for c, (label, value) in zip(cols, [("Entrées", len(f["inputs"])), ("Sorties", len(f["outputs"])),
                                        ("Codes d'erreur", len(f["error_codes"])), ("Appels LLM", len(f["llm_calls"])),
                                        ("Appels externes", len(f["http_calls"])),
                                        ("Dépendances HORIZON", len(f["internal_imports"]))]):
        c.metric(label, value)
    if f["insecure_tls"]:
        st.warning("La source désactive la vérification TLS (`verify=False`) : elle sera rétablie dans l'agent.")
    left, right = st.columns(2)
    with left:
        st.markdown("**Point d'entrée**")
        st.dataframe(pd.DataFrame(f["entrypoints"]), hide_index=True, use_container_width=True)
        st.markdown("**Entrées (`get_input_value`)**")
        st.dataframe(pd.DataFrame({"Entrée": f["inputs"]}), hide_index=True, use_container_width=True)
        st.markdown("**Sorties (`context.addValue`)**")
        st.dataframe(pd.DataFrame(f["outputs"]), hide_index=True, use_container_width=True)
    with right:
        st.markdown("**Erreurs (`AppException`)**")
        errs = [{"app_code": e.get("app_code"), "status_code": e.get("status_code"), "message": e.get("message"),
                 "ligne": e.get("line")} for e in f["errors"]]
        st.dataframe(pd.DataFrame(errs), hide_index=True, use_container_width=True)
        st.markdown("**Appels LLM et externes**")
        calls = [{"type": "LLM", "appel": c["call"], "détail": ", ".join(c["kwargs"]), "ligne": c["line"]} for c in f["llm_calls"]]
        calls += [{"type": "HTTP", "appel": h["call"], "détail": h.get("url") or "", "ligne": h["line"]} for h in f["http_calls"]]
        st.dataframe(pd.DataFrame(calls), hide_index=True, use_container_width=True)
        st.markdown("**Dépendances HORIZON supprimées**")
        st.write(", ".join(f"`{m}`" for m in f["internal_imports"]) or "Aucune")


def render_mapping():
    st.subheader(LABEL["mapping"])
    if not need(ss.mapping is not None, "Importez d'abord une Action (étape 1)."):
        return
    df = pd.DataFrame(ss.mapping)
    counts = df["Statut prévu"].value_counts()
    cols = st.columns(3)
    for c, s in zip(cols, ["Automatique", "Adapté", "Manuel"]):
        c.metric(s, int(counts.get(s, 0)))
    st.dataframe(df, hide_index=True, use_container_width=True)
    st.caption("Correspondance prévisionnelle calculée par règles, sans LLM. "
               "La correspondance définitive figure dans les notes de migration (étape 4).")


def render_generation():
    st.subheader(LABEL["generation"])
    if not need(ss.code is not None, "Importez d'abord une Action (étape 1)."):
        return
    if ss.result is None:
        if ss.error:
            st.error(f"Dernière tentative en échec : {ss.error}")
        st.write(f"La génération est confiée à l'agent migrateur `{MIGRATOR_ENDPOINT}` (1 à 2 min).")
        if st.button("Lancer la génération", type="primary"):
            run_generation(st.empty())
            st.rerun()
        return
    r = ss.result
    (st.success if r["status"] == "VALIDÉ" else st.warning)(
        f"Statut **{r['status']}** — {r['attempts']} tentative(s) — {r['duration_s']} s")
    if r["model_checks"]:
        st.markdown("**Contrôle des correspondances de modèles**")
        st.dataframe(pd.DataFrame(r["model_checks"]), hide_index=True, use_container_width=True)
        if any(not c["Équivalent"] for c in r["model_checks"]):
            st.error("Au moins un modèle source est associé à un modèle différent : relancez la génération ou corrigez model_config.yml.")
    files = r["files"]
    left, right = st.columns(2)
    with left:
        st.markdown("**Source HORIZON**")
        st.code(ss.code, language="python")
    with right:
        st.markdown("**Agent Databricks (`agent.py`)**")
        st.code(files.get("agent.py", "(absent)"), language="python")
    tabs = st.tabs(["model_config.yml", "requirements.txt", "Notes de migration", "Rapport"])
    with tabs[0]:
        st.code(files.get("model_config.yml", "(absent)"), language="yaml")
    with tabs[1]:
        st.code(files.get("requirements.txt", "(absent)"), language="text")
    with tabs[2]:
        st.markdown(files.get("MIGRATION_NOTES.md", "(absent)"))
    with tabs[3]:
        st.markdown(files.get("MIGRATION_REPORT.md", "(absent)"))
    c1, c2 = st.columns(2)
    c1.download_button("Télécharger le projet (.zip)", files_zip(files), f"{action_name()}_agent.zip", "application/zip")
    if c2.button("Relancer la génération"):
        run_generation(st.empty())
        st.rerun()


def render_tests():
    st.subheader(LABEL["tests"])
    if not need(step_done("tests"), "Lancez d'abord la génération (étape 4)."):
        return
    tests = ss.result["tests"]
    ok = sum(bool(t.get("ok")) for t in tests)
    c1, c2 = st.columns(2)
    c1.metric("Tests réussis", f"{ok}/{len(tests)}")
    c2.metric("Tests en échec", len(tests) - ok)
    df = pd.DataFrame([{"Résultat": "✅" if t.get("ok") else "❌", "Test": t.get("name"), "Détail": t.get("detail")}
                       for t in tests])
    st.dataframe(df, hide_index=True, use_container_width=True)
    st.caption("Tests exécutés par l'agent migrateur contre Model Serving : cas nominaux (appel réel au LLM) "
               "et cas d'erreur, plus deux tests ajoutés par le migrateur (entrée vide, streaming).")


def render_simulation():
    st.subheader(LABEL["simulation"])
    if not need(step_done("simulation"), "Lancez d'abord la génération (étape 4)."):
        return
    try:
        spec = json.loads(ss.result["files"]["tests.json"])
    except json.JSONDecodeError:
        st.error("tests.json illisible.")
        return
    cases = spec.get("cases", [])
    if not need(bool(cases), "Aucun scénario dans tests.json."):
        return
    results = {t.get("name"): t for t in ss.result["tests"]}
    name = st.selectbox("Scénario", [c.get("name") for c in cases])
    case = next(c for c in cases if c.get("name") == name)
    left, right = st.columns(2)
    with left:
        st.markdown("**Requête envoyée à l'agent**")
        st.json(case.get("request", {}))
    with right:
        st.markdown("**Attendu**")
        st.json({k: case.get(k) for k in ("expect_error", "expect_output_nonempty", "expect_custom_outputs_keys")})
        res = results.get(name)
        st.markdown("**Observé (exécution réelle par le migrateur)**")
        if res is None:
            st.write("Non exécuté.")
        else:
            (st.success if res.get("ok") else st.error)(res.get("detail") or ("Conforme" if res.get("ok") else "Échec"))
    if spec.get("optional_outputs"):
        st.caption("Sorties conditionnelles (pas toujours produites) : " + ", ".join(spec["optional_outputs"]))
    st.info("Simulation interactive avec vos propres valeurs : prévue dans une phase suivante "
            "(mode « simulation » à ajouter à l'agent migrateur, pour ne pas exécuter de code généré dans l'App).")


def start_real_deploy(uc_model: str) -> None:
    w = client()
    directory = DJ.deposit_dir(DEPLOY_VOLUME, action_name())
    try:
        DJ.write_deposit(w, directory, ss.code, ss.result)
        run_id = DJ.start_deploy(w, DEPLOY_JOB_ID, directory, uc_model)
        status = DJ.run_status(w, run_id)
    except Exception as e:  # noqa: BLE001 - droits manquants, Volume absent...
        st.error(f"Lancement impossible : {type(e).__name__}: {str(e)[:500]}")
        return
    ss.deploy = {"run_id": run_id, "directory": directory, "uc_model": uc_model,
                 "started": time.time(), "status": status, "logged": False}


def follow_deploy() -> None:
    """Suit l'exécution du Job jusqu'à la fin (l'exécution continue même si la page est fermée)."""
    dep, w = ss.deploy, client()
    ph = st.empty()
    while not DJ.is_finished(dep["status"]) and time.time() - dep["started"] < DEPLOY_MAX_WAIT_S:
        s = dep["status"]
        el = int(time.time() - dep["started"])
        ph.info(f"⏳ Déploiement en cours — état du Job : **{s['life_cycle_state']}** — {el // 60} min {el % 60:02d} s  \n"
                f"Exécution [{dep['run_id']}]({s.get('url')}) — compter 15 à 25 min (enregistrement, création ou "
                f"mise à jour de l'endpoint, test de fumée).")
        time.sleep(DEPLOY_POLL_S)
        try:
            dep["status"] = DJ.run_status(w, dep["run_id"])
        except Exception as e:  # noqa: BLE001 - erreur réseau passagère : on réessaie
            ph.warning(f"Lecture de l'état impossible ({type(e).__name__}), nouvel essai…")
    ph.empty()
    if DJ.is_finished(dep["status"]) and not dep["logged"]:
        s, res = dep["status"], dep["status"].get("result") or {}
        ss.history.append({
            "Heure": datetime.now().strftime("%H:%M:%S"), "Action": action_name(), "Source": ss.source_name,
            "Verdict": "Déployé" if s.get("result_state") == "SUCCESS" else "Échec du déploiement",
            "Déploiement": f"{dep['uc_model']} v{res.get('version')}" if res.get("version") else s.get("result_state"),
            "Endpoint": res.get("endpoint"), "Exécution du Job": dep["run_id"],
        })
        dep["logged"] = True
    st.rerun()


def show_deploy_result() -> None:
    dep = ss.deploy
    s, res = dep["status"], dep["status"].get("result") or {}
    host = client().config.host
    if s.get("result_state") == "SUCCESS" and res.get("endpoint"):
        st.success(f"Déployé : **{dep['uc_model']} v{res.get('version')}** sur l'endpoint "
                   f"[{res['endpoint']}]({host}/ml/endpoints/{res['endpoint']}) — test de fumée réussi.")
    elif DJ.is_finished(s):
        st.error(f"Déploiement en échec ({s.get('result_state')}) : {(s.get('error') or s.get('message') or '')[:800]}")
    else:
        st.warning(f"Suivi interrompu après {DEPLOY_MAX_WAIT_S // 60} min : l'exécution continue dans le Job.")
    st.caption(f"Exécution du Job : [{dep['run_id']}]({s.get('url')}) — dépôt : `{dep['directory']}`")


def render_deploiement():
    st.subheader(LABEL["deploiement"])
    if not need(bool((ss.result or {}).get("files")), "Lancez d'abord la génération (étape 4)."):
        return
    r = ss.result
    uc_model, endpoint = target_names()
    v, issues = verdict()
    (st.success if not issues else st.error)(f"Verdict : **{v}**")
    for i in issues:
        st.write(f"- {i}")
    st.markdown("**Ce qui serait créé ou modifié**")
    reqs = [l for l in r["files"].get("requirements.txt", "").splitlines() if l.strip()]
    plan = [
        {"Ressource": "Modèle Unity Catalog", "Valeur": uc_model, "Action": "Nouvelle version (numéro attribué à l'enregistrement)"},
        {"Ressource": "Endpoint Model Serving", "Valeur": endpoint, "Action": "Création ou mise à jour (100 % du trafic sur la nouvelle version)"},
        {"Ressource": "Endpoints LLM utilisés", "Valeur": ", ".join(config_endpoints(r["config"])) or "-", "Action": "Déclarés comme ressources de l'agent"},
        {"Ressource": "Dépendances", "Valeur": ", ".join(reqs) or "-", "Action": "Installées dans l'environnement de l'endpoint"},
    ]
    st.dataframe(pd.DataFrame(plan), hide_index=True, use_container_width=True)
    ext = external_services(r["config"])
    if ext:
        st.markdown("**Services externes**")
        st.dataframe(pd.DataFrame(ext), hide_index=True, use_container_width=True)
    host = client().config.host
    st.markdown("**Déploiement réel**")
    if ss.deploy and not DJ.is_finished(ss.deploy["status"]) and \
            time.time() - ss.deploy["started"] < DEPLOY_MAX_WAIT_S:
        follow_deploy()
        return
    if ss.deploy:
        show_deploy_result()
    if issues:
        st.warning("Déploiement impossible tant que les points bloquants ne sont pas levés.")
        return
    st.write(f"Le projet relu ci-dessus est déposé dans `{DEPLOY_VOLUME}` puis déployé tel quel par le Job "
             f"[{DEPLOY_JOB_ID}]({host}/jobs/{DEPLOY_JOB_ID}), qui refait les contrôles bloquants, enregistre le modèle, "
             f"déploie l'endpoint et exécute un test de fumée. Le Job s'exécute avec l'identité de son propriétaire.")
    confirmed = st.checkbox(f"Je confirme le déploiement réel : nouvelle version de `{uc_model}` et 100 % du trafic "
                            f"de `{endpoint}` basculé sur cette version.")
    if st.button("🚀 Déployer", type="primary", disabled=not confirmed):
        start_real_deploy(uc_model)
        if ss.deploy:
            st.rerun()


def render_historique():
    st.subheader(LABEL["historique"])
    if not need(bool(ss.history), "Aucune migration dans cette session."):
        return
    df = pd.DataFrame(ss.history)
    st.dataframe(df, hide_index=True, use_container_width=True)
    st.download_button("Télécharger l'historique (.csv)", df.to_csv(index=False).encode("utf-8"),
                       "historique_migrations.csv", "text/csv")
    st.caption("Historique conservé pendant la session uniquement (persistance prévue dans une table Unity Catalog).")


RENDER = {"import": render_import, "analyse": render_analyse, "mapping": render_mapping,
          "generation": render_generation, "tests": render_tests, "simulation": render_simulation,
          "deploiement": render_deploiement, "historique": render_historique}

# ---------------------------------------------------------------- mise en page
with st.sidebar:
    st.title("🔁 Migrateur HORIZON")
    st.caption(f"Agent migrateur : `{MIGRATOR_ENDPOINT}`")
    choice = st.radio("Étapes", ORDER, index=ORDER.index(ss.step),
                      format_func=lambda k: f"{'✅' if step_done(k) else '⬜'} {LABEL[k]}")
    if choice != ss.step:
        ss.step = choice
        st.rerun()
    st.divider()
    if ss.assistant is not None:
        st.write(f"Assistant ouvert : **{ss.assistant['pkg']['manifest'].get('name')}** "
                 f"(commit `{ss.assistant['repo']['commit'][:7]}`)")
    if ss.code is not None:
        st.write(f"Action chargée : **{action_name()}**")
        run_all = st.button("▶ Migrer (étapes 1 à 7)", type="primary", use_container_width=True,
                            help="Analyse, génère et teste l'agent. Le déploiement réel se confirme ensuite à l'étape 7.")
    else:
        run_all = False
        st.caption("Chargez une Action pour lancer la migration.")

st.title("Migration HORIZON → Databricks")
done = sum(step_done(k) for k in ORDER)
st.progress(done / len(ORDER), text=f"{done}/{len(ORDER)} étapes réalisées")

if run_all:
    simulate_all()
else:
    RENDER[ss.step]()
