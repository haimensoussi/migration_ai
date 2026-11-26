"""EIA Factory - étape 3 : Team Builder (méta-équipe qui projette des équipes d'agents).

Trois phases, chacune fermée par un contrôle de passage AG08 :
  1. Découverte de la source (AG01) : profil agrégé du Transformation Center (aucune ligne lue) et KPI candidats
     déduits de la structure (comptages et sommes mensuels). Ce sont des constats statistiques, « à valider ».
  2. Proposition d'architecture (AG10) : choix du modèle d'équipe selon ce que le métier a fourni (règles,
     plans d'action, compétences) et génération d'une configuration conforme à team_config.
  3. Déploiement (AG09) : recette en aperçu (cycle complet en mémoire, sans écriture), brouillon versionné,
     mise en service par décision humaine uniquement.

Aucun seuil, aucune règle ni aucun plan d'action n'est inventé : sans règles métier, l'équipe proposée est une
équipe de surveillance (AG01 + AG08). Les tolerances par défaut sont celles du Framework et restent à valider.
"""
from __future__ import annotations

import copy
import datetime as dt
import re
from typing import Any

from backend.eia import agent_catalog as ac
from backend.eia import agent_models as am
from backend.eia import team_config as tc
from backend.eia.contracts import ContractError, new_id

DATE_TYPES = ("date", "timestamp", "timestamp_ntz")
MEASURE_TYPES = ("decimal", "double", "float", "int", "integer", "bigint", "long", "smallint")
MAX_MEASURES = 4            # sommes proposées par table
MAX_KPIS = 12               # KPI retenus par équipe
MAX_FORECASTS = 3
DEFAULT_FORECAST = {"horizon": 3, "season_length": 12, "test_points": 6, "max_error_pct": 15,
                    "exclude_last_incomplete_month": True}
MIN_HISTORY = DEFAULT_FORECAST["season_length"] + DEFAULT_FORECAST["test_points"]   # mois pour une prévision testée
CONFIG_STATUSES = ("brouillon", "en_service", "retiree")
CONFIG_TRANSITIONS = {"brouillon": ("en_service", "retiree"), "en_service": ("retiree",), "retiree": ()}
ROLES_BY_MODEL = {"AG01": ("perception", "analyst", "alerting"), "AG02": ("prediction",), "AG03": ("advisor",),
                  "AG06": ("planner", "staffing")}
_ID = re.compile(r"[^a-z0-9]+")


class TeamBuilderError(ValueError):
    pass


def _base(type_text: str) -> str:
    return (type_text or "").lower().split("(")[0].strip()


def _slug(name: str, limit: int = 30) -> str:
    s = _ID.sub("_", name.lower()).strip("_")
    s = s[5:] if s.startswith("data_") else s
    s = s if s and s[0].isalpha() else f"t_{s}"
    return s[:limit].rstrip("_")


def _month(v: Any) -> str | None:
    m = re.match(r"^(\d{4})-(\d{2})", str(v or ""))
    return f"{m.group(1)}-{m.group(2)}" if m else None


def _span(lo: str | None, hi: str | None) -> int:
    if not lo or not hi:
        return 0
    (y1, m1), (y2, m2) = (map(int, lo.split("-")), map(int, hi.split("-")))
    return max(0, (y2 - y1) * 12 + (m2 - m1) + 1)


def _q(col: str) -> str:
    return "`" + col.replace("`", "``") + "`"


# ---------------------------------------------------------------- phase 1 : découverte (AG01)
def kpi_candidates(discovery: dict, today: dt.date | None = None) -> list[dict]:
    """KPI candidats déduits de la structure : par table, un axe temporel et des mesures numériques.

    Exclus : colonnes clés ou identifiants, colonnes signalées sensibles, tables vides ou en erreur, dates futures
    (planification : une période future n'est pas une observation).
    """
    now_m = (today or dt.date.today()).strftime("%Y-%m")
    sensitive = {(s["table"], s["colonne"]) for s in discovery.get("donnees_sensibles") or []}
    out = []
    for t in discovery.get("tables") or []:
        if "erreur" in t or not t.get("lignes"):
            continue
        alias = _slug(t["table"].split(".")[-1])
        cols = [c for c in t.get("colonnes") or [] if (t["table"], c["nom"]) not in sensitive]
        dates = [c for c in cols if _base(c["type"]) in DATE_TYPES and (c.get("remplissage_pct") or 0) > 0
                 and _month(c.get("min")) and _month(c.get("max"))]
        if not dates:
            continue
        # Axe temporel : colonne sans dates futures d'abord, puis la mieux remplie, puis nom contenant « date ».
        d = sorted(dates, key=lambda c: (_month(c["max"]) > now_m, -(c.get("remplissage_pct") or 0),
                                         "date" not in c["nom"].lower(), c["nom"]))[0]
        lo, hi = _month(d.get("min")), min(_month(d.get("max")), now_m)
        months = _span(lo, hi)
        period = f"date_format({_q(d['nom'])}, 'yyyy-MM')"
        common = {"grain": "mois", "direction": "hausse_favorable", "origine": "donnees", "statut": "a_valider",
                  "table": t["table"], "alias": alias, "axe_temporel": d["nom"], "historique_mois": months,
                  "periode": f"{lo} à {hi}", "previsible": months >= MIN_HISTORY,
                  "exclusions": f"Lignes sans {d['nom']} ou datées après la date du jour",
                  "limits": "Candidat déduit de la structure des données, sans règle métier : définition, sens et "
                            "exclusions à valider par le responsable métier"}
        out.append({**common, "id": f"nb_{alias}"[:40], "label": f"Nombre de lignes - {alias}", "unit": "lignes",
                    "formula": f"Nombre de lignes de {t['table']} par mois de {d['nom']}",
                    "sql": f"SELECT {period} AS period, COUNT(*) AS value FROM {{{alias}}} WHERE {_q(d['nom'])} IS NOT NULL "
                           f"AND {_q(d['nom'])} <= current_date() GROUP BY {period} ORDER BY period"})
        measures = [c for c in cols if _base(c["type"]) in MEASURE_TYPES and not c.get("cle_candidate")
                    and not re.search(r"(^id_|_id$|^id$|_key$|_code$)", c["nom"].lower())
                    and (c.get("remplissage_pct") or 0) > 0]
        for m in measures[:MAX_MEASURES]:
            out.append({**common, "id": f"total_{alias}_{_slug(m['nom'], 20)}"[:40],
                        "label": f"Total {m['nom']} - {alias}", "unit": "unité de la colonne",
                        "formula": f"Somme de {m['nom']} de {t['table']} par mois de {d['nom']}",
                        "sql": f"SELECT {period} AS period, SUM({_q(m['nom'])}) AS value FROM {{{alias}}} "
                               f"WHERE {_q(d['nom'])} IS NOT NULL AND {_q(d['nom'])} <= current_date() "
                               f"GROUP BY {period} ORDER BY period"})
    seen, uniq = set(), []
    for k in out:                       # identifiants uniques (tables au nom proche)
        base, i = k["id"], 2
        while k["id"] in seen:
            k["id"] = f"{base[:37]}_{i}"
            i += 1
        seen.add(k["id"])
        uniq.append(k)
    return uniq


def discovery_view(discovery: dict) -> dict:
    """Résumé de découverte pour HAKIM et la page (sans le détail de chaque colonne)."""
    tables = []
    for t in discovery.get("tables") or []:
        if "erreur" in t:
            tables.append({"table": t["table"], "erreur": t["erreur"]})
            continue
        cols = t.get("colonnes") or []
        tables.append({"table": t["table"], "lignes": t["lignes"], "colonnes": len(cols),
                       "dates": [c["nom"] for c in cols if _base(c["type"]) in DATE_TYPES],
                       "cles_candidates": [c["nom"] for c in cols if c.get("cle_candidate")]})
    return {"perimetre": discovery.get("perimetre"), "date": discovery.get("date"), "tables": tables,
            "liens_probables": len(discovery.get("liens_probables") or []),
            "donnees_sensibles": len(discovery.get("donnees_sensibles") or []),
            "constats": (discovery.get("constats") or [])[:20], "avertissement": discovery.get("avertissement")}


# ---------------------------------------------------------------- contrôles de passage (AG08)
def gate(phase: str, discovery: dict | None = None, candidates: list[dict] | None = None,
         config: dict | None = None, data_scope: tuple | None = None, recette: dict | None = None) -> dict:
    blocking, warnings = [], []
    if phase == "decouverte":
        tables = (discovery or {}).get("tables") or []
        ok = [t for t in tables if "erreur" not in t]
        if not ok:
            blocking.append("Aucune table lisible dans le périmètre")
        warnings += [f"{t['table']} : profil impossible" for t in tables if "erreur" in t]
        warnings += [f"{t['table']} : table vide" for t in ok if not t.get("lignes")]
        if ok and not candidates:
            blocking.append("Aucun KPI candidat : aucune table avec une colonne date renseignée")
        if candidates and not any(k["previsible"] for k in candidates):
            warnings.append(f"Historique inférieur à {MIN_HISTORY} mois : aucune prévision testée possible")
        if (discovery or {}).get("donnees_sensibles"):
            warnings.append(f"{len(discovery['donnees_sensibles'])} colonne(s) potentiellement sensible(s) exclue(s) "
                            "des KPI candidats (à confirmer)")
    elif phase == "architecture":
        blocking += tc.validate(config or {}, data_scope)
        if not blocking:
            blocking += am.check_team(config)
    elif phase == "deploiement":
        r = recette or {}
        if not r:
            blocking.append("Recette non exécutée")
        blocking += [f"KPI écarté par la perception : {k} ({v})" for k, v in (r.get("kpi_ecartes") or {}).items()]
        blocking += [f"Erreur technique : {e}" for e in r.get("erreurs") or []]
        if r and not r.get("kpi_exploitables"):
            blocking.append("Aucun KPI exploitable pendant la recette")
    else:
        raise TeamBuilderError(f"Phase inconnue : {phase}")
    return {"phase": phase, "controle": "AG08", "reussi": not blocking, "bloquants": blocking,
            "avertissements": warnings}


# ---------------------------------------------------------------- phase 2 : architecture (AG10)
def _validators(owner: str) -> list[str]:
    return [owner] if owner else ["proprietaire_equipe"]


def design(team_id: str, name: str, description: str, objectives: list[str], candidates: list[dict],
           kpi_ids: list[str] | None = None, owner: str = "", rules: list[dict] | None = None,
           playbooks: list[dict] | None = None, skills: list | None = None, staffing: dict | None = None) -> dict:
    """Architecture proposée et configuration d'équipe générée. Rien n'est enregistré."""
    if not tc.TEAM_ID.match(team_id or ""):
        raise TeamBuilderError("Identifiant d'équipe invalide (minuscules, chiffres, _)")
    if team_id in tc.available():
        raise TeamBuilderError(f"L'équipe {team_id} existe déjà dans les configurations versionnées")
    by_id = {k["id"]: k for k in candidates}
    chosen = [by_id[k] for k in (kpi_ids or list(by_id)) if k in by_id][:MAX_KPIS]
    unknown = [k for k in kpi_ids or [] if k not in by_id]
    if not chosen:
        raise TeamBuilderError("Aucun KPI retenu parmi les candidats de la découverte")
    rules, playbooks = list(rules or []), list(playbooks or [])
    full = bool(rules and playbooks)
    template_id = "equipe_metier" if full else "equipe_surveillance"
    forecast_kpis = [k["id"] for k in chosen if k["previsible"]][:MAX_FORECASTS]
    # AG02 (Predictive Intelligence) n'est retenu que si au moins un KPI est prévisible.
    models = [m for m in ac.TEMPLATES[template_id]["modeles"] if m != "AG02" or forecast_kpis]
    roles = [r for m in models for r in ROLES_BY_MODEL.get(m, ())]
    fields = ("id", "label", "unit", "grain", "direction", "formula", "exclusions", "limits", "sql")
    cfg = {
        "team_id": team_id, "version": "0.1", "name": name or team_id, "description": description or "",
        "objectives": list(objectives or []) or ["Suivre les indicateurs du périmètre (objectif à préciser)"],
        "sources": {k["alias"]: k["table"] for k in chosen},
        "kpis": [{f: k[f] for f in fields} for k in chosen],
        "rules": rules, "playbooks": playbooks,
        "analysis": {"kpis": [k["id"] for k in chosen], "window_months": 1},
        "perception": {"status": "a_valider", "note": "AG01 : aucune tolérance de retard tant que le responsable "
                                                       "des données ne l'a pas fixée ; le retard est signalé sans bloquer"},
        "agents": roles, "models": models,
        "tools": ["execute_sql", "render_kpi", "render_chart", "eia_kpi", "eia_forecast", "eia_alert"]
                 + (["eia_recommendation", "eia_mission", "eia_affectation"] if full else []),
        "instructions": {"commun": f"Équipe {name or team_id} conçue par le Team Builder. KPI déduits des données, à "
                                   "valider par le métier. Ne cite que des chiffres renvoyés par les outils."},
        "validation_policy": {"mission_requires_validation": True, "recommendation_selection": "utilisateur",
                              "validators": _validators(owner), "external_actions": "interdit"},
    }
    if forecast_kpis:
        cfg["forecast"] = {"kpis": forecast_kpis, **DEFAULT_FORECAST}
    if skills is not None:
        cfg["skills"] = skills
    if staffing is not None:
        cfg["staffing"] = staffing
    reasons = [f"Modèle d'équipe : {ac.TEMPLATES[template_id]['nom']}"]
    if not full:
        reasons.append("Sans règles d'alerte ni plans d'action fournis par le métier, AG03 (recommandations) et AG06 "
                       "(missions) ne sont pas activés : aucune règle ni aucun seuil n'est inventé")
    reasons.append(f"{len(chosen)} KPI retenu(s) sur {len(by_id)} candidat(s) ; {len(forecast_kpis)} prévision(s) "
                   f"(historique >= {MIN_HISTORY} mois)")
    to_validate = ["Définition, sens et exclusions de chaque KPI", "Tolérance de retard des données (perception)"]
    if forecast_kpis:
        to_validate.append(f"Erreur maximale admise des prévisions ({DEFAULT_FORECAST['max_error_pct']} %, valeur par "
                           "défaut du Framework)")
    if not full:
        to_validate.append("Règles d'alerte, seuils et plans d'action pour passer au modèle d'équipe métier")
    return {"team_id": team_id, "modele_equipe": template_id, "modeles": models, "roles": roles,
            "justification": reasons, "a_valider": to_validate, "kpi_inconnus": unknown, "config": cfg,
            "architecte": "AG10"}


# ---------------------------------------------------------------- phase 3 : déploiement (AG09)
def recette(config: dict, source: Any, today: dt.date | None = None, data_scope: tuple | None = None) -> dict:
    """Cycle complet en aperçu : magasin en mémoire, aucune écriture SQL ni notification."""
    from backend.eia import engine
    from backend.eia.store import EiaRepository, MemoryEiaStore
    cfg = tc.from_dict(copy.deepcopy(config), data_scope)
    out = engine.run_cycle(cfg, source, EiaRepository(MemoryEiaStore()), today=today, actor="agent:team_builder")
    st = out["etapes"]
    perceived = [f for f in st["perception"]["findings"] if "exploitable" in (f.get("detail") or "")]
    errors = [e for e in out.get("erreurs") or [] if not str(e).startswith("staffing")]
    fc = st.get("prediction", {}).get("forecasts") or []
    return {"statut_cycle": out.get("statut"), "kpi_exploitables": len(perceived), "kpi_ecartes": out["kpi_ecartes"],
            "constats": len(st["analyst"]["findings"]), "previsions": len(fc),
            "previsions_fiables": sum(1 for f in fc if f.get("reliable")),
            "alertes": len(st["alerting"]["alerts"]), "recommandations": len(st["advisor"]["recommendations"]),
            "requetes_kpi": out.get("requetes_kpi"), "erreurs": errors, "modeles": out.get("modeles"),
            "persistant": False}


_FC_ERR = re.compile(r"^prediction : Prévision ([a-z0-9_]+) : (.+)$")


def adjust(design_out: dict, candidates: list[dict], recette_out: dict) -> dict | None:
    """AG09 : retire des prévisions les KPI dont la série ne permet pas de prévoir (ex. mois manquants) et les
    remplace par d'autres KPI prévisibles. Les KPI restent suivis. None si aucun ajustement n'est possible."""
    failed = {}
    for e in recette_out.get("erreurs") or []:
        m = _FC_ERR.match(str(e))
        if m:
            failed[m.group(1)] = m.group(2)
    others = [e for e in recette_out.get("erreurs") or [] if not _FC_ERR.match(str(e))]
    if not failed or others:
        return None
    out = copy.deepcopy(design_out)
    cfg = out["config"]
    tried = set(failed) | {k for a in out.get("ajustements", []) for k in a["previsions_retirees"]}
    # Un trou de série vient de la table (axe temporel commun) : tous ses KPI sont écartés de la prévision.
    table_of = {k["id"]: k["table"] for k in candidates}
    bad_tables = {table_of.get(k) for k in tried} - {None}
    chosen = set(cfg["analysis"]["kpis"])
    keep = [k for k in (cfg.get("forecast") or {}).get("kpis", []) if k not in failed and table_of.get(k) not in bad_tables]
    pool = [k["id"] for k in candidates if k["previsible"] and k["id"] in chosen and k["id"] not in tried
            and k["table"] not in bad_tables]
    new = (keep + [k for k in pool if k not in keep])[:MAX_FORECASTS]
    if new:
        cfg["forecast"] = {"kpis": new, **DEFAULT_FORECAST}
    else:
        cfg.pop("forecast", None)
        cfg["agents"] = [r for r in cfg["agents"] if r != "prediction"]
        cfg["models"] = [m for m in cfg["models"] if m != "AG02"]
        out["roles"], out["modeles"] = cfg["agents"], cfg["models"]
    out["justification"].append("Ajustement AG09 après recette : prévision retirée pour "
                                + ", ".join(f"{k} ({v})" for k, v in failed.items()))
    out["a_valider"].append("Complétude des séries retirées de la prévision (mois manquants à corriger à la source)")
    out["ajustements"] = out.get("ajustements", []) + [{"previsions_retirees": failed, "previsions": new}]
    return out


def build(design_out: dict, gates: list[dict], recette_out: dict | None, user: str) -> dict:
    """AG09 : brouillon versionné prêt à enregistrer ; jamais en service sans décision humaine."""
    if not user or user.startswith("agent:"):
        raise ContractError("Enregistrement réservé à un utilisateur identifié")
    cfg = design_out["config"]
    return {"config_id": new_id("tc"), "team_id": cfg["team_id"], "version": cfg["version"], "status": "brouillon",
            "name": cfg["name"], "models": design_out["modeles"], "config": cfg,
            "controls": {"passages": gates, "a_valider": design_out["a_valider"],
                         "justification": design_out["justification"]},
            "recette": recette_out or {}, "created_by": user}


PHASES = ("decouverte", "architecture", "deploiement")


def run(discover: Any, source: Any, *, team_id: str = "", name: str = "", description: str = "",
        objectives: list[str] | None = None, kpi_ids: list[str] | None = None, owner: str = "",
        upto: str = "deploiement", data_scope: tuple | None = None, today: dt.date | None = None) -> dict:
    """Enchaîne les phases jusqu'à `upto` ; s'arrête au premier contrôle AG08 en échec. Aucune écriture.

    discover : fonction sans argument renvoyant le profil (Transformation Center) ; source : KpiSource.
    """
    if upto not in PHASES:
        raise TeamBuilderError(f"Phase inconnue : {upto}")
    disc = discover()
    cands = kpi_candidates(disc, today)
    g = gate("decouverte", disc, cands)
    out = {"decouverte": discovery_view(disc), "kpi_candidats": [
        {k: c[k] for k in ("id", "label", "formula", "table", "axe_temporel", "periode", "historique_mois",
                           "previsible", "statut")} for c in cands], "controles": [g], "phase_atteinte": "decouverte"}
    if upto == "decouverte" or not g["reussi"]:
        return out
    d = design(team_id, name, description, objectives or [], cands, kpi_ids, owner)
    g = gate("architecture", config=d["config"], data_scope=data_scope)
    out.update(architecture=d, phase_atteinte="architecture")
    out["controles"].append(g)
    if upto == "architecture" or not g["reussi"]:
        return out
    r = recette(d["config"], source, today, data_scope)
    adj = adjust(d, cands, r) if r["erreurs"] else None
    if adj is not None:
        g_adj = gate("architecture", config=adj["config"], data_scope=data_scope)
        if g_adj["reussi"]:
            d, r = adj, recette(adj["config"], source, today, data_scope)
            out["controles"][-1] = g_adj
    out.update(architecture=d, recette=r, phase_atteinte="deploiement")
    out["controles"].append(gate("deploiement", recette=r))
    return out


def deployable(row: dict) -> list[str]:
    """Conditions de mise en service : tous les contrôles de passage réussis, recette comprise."""
    gates = {g["phase"]: g for g in (row.get("controls") or {}).get("passages") or []}
    return [f"Contrôle {p} non réussi" for p in ("decouverte", "architecture", "deploiement")
            if not gates.get(p, {}).get("reussi")]


def resolve(team_id: str, repo: Any = None, data_scope: tuple | None = None) -> tc.TeamConfig:
    """Équipe versionnée (config/teams) ou, à défaut, équipe en service créée par le Team Builder."""
    if team_id in tc.available():
        return tc.load(team_id, data_scope=data_scope)
    row = repo.team_config_in_service(team_id) if repo is not None else None
    if not row:
        raise tc.TeamConfigError(f"Configuration d'équipe introuvable : {team_id}")
    return tc.from_dict(row["config"], data_scope)


def teams(repo: Any = None) -> list[str]:
    out = list(tc.available())
    if repo is not None:
        try:
            out += [r["team_id"] for r in repo.team_configs(statuses=["en_service"]) if r["team_id"] not in out]
        except Exception:  # noqa: BLE001  table absente ou droits : seules les équipes versionnées
            pass
    return out
