"""Agent IA "Analyste Data Quality" (etape 12 du cadrage : agent en cadre controle).

Capacites : expliquer les scores et resultats, resumer les anomalies, identifier des causes possibles,
comparer les executions, proposer des regles candidates, generer du SQL / PySpark en brouillon,
suggerer des actions correctives.

Garde-fous :
* outils en lecture seule, executes avec le jeton de l'utilisateur (droits Unity Catalog) ;
* perimetre limite aux schemas du prefixe choisi et au Bronze de la source ;
* aucune ecriture, aucun lancement de job, aucune execution en production ;
* une regle proposee est un brouillon au statut a_valider, jamais enregistre par l'agent.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable

from backend.naming import check_identifier, check_prefix, schema_fqn
from backend.sql_guard import SqlGuardError, check_read_only, check_scope

MAX_STEPS = 8
MAX_TOOL_CHARS = 14000
DIMENSIONS = ["Disponibilite", "Integrite", "Unicite", "Validite", "Completude", "Coherence", "Exactitude",
              "Exhaustivite", "Fraicheur", "Precision"]
TEMPLATES = ["not_null", "unique", "regex", "range", "in_list", "expression", "foreign_key",
             "reverse_foreign_key", "schema_columns", "freshness"]
STATUTS_REGLE = ["conforme", "anomalie", "a_qualifier", "non_evalue", "erreur_technique"]


def _fn(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required or []}}}


_TABLE = {"type": "string", "description": "Nom court de l'objet (table_name), par ex. vitesse_limite_ligne_v"}

TOOLS = [
    _fn("synthese_qualite", "Synthese par objet de la derniere execution : regles en echec (dont critiques et bloquantes), "
        "scores regles et DAMA, quarantaine, reconciliation Bronze/Silver.", {"table_name": _TABLE}),
    _fn("resultats_regles", "Resultats courants des regles metier avec leur definition, criticite, seuil et statut de validation.",
        {"table_name": _TABLE, "statut": {"type": "string", "enum": STATUTS_REGLE}}),
    _fn("scores_dama", "Mesures generiques DAMA (couche 1) par objet, colonne et dimension, avec seuil indicatif.",
        {"table_name": _TABLE, "sous_seuil_uniquement": {"type": "boolean"}}),
    _fn("anomalies", "Anomalies de la derniere execution : comptage par regle et exemples de lignes (cle et valeurs).",
        {"table_name": _TABLE, "rule_id": {"type": "string"},
         "nb_exemples": {"type": "integer", "description": "1 a 20, defaut 5"}}),
    _fn("historique_executions", "Comparaison des executions successives : regles en echec, anomalies et taux moyen par run.",
        {"table_name": _TABLE}),
    _fn("catalogue_regles", "Catalogue des regles (definition, template, parametres, criticite, seuil, statut de validation).",
        {"table_name": _TABLE, "statut_validation": {"type": "string", "enum": ["a_valider", "validee", "rejetee"]}}),
    _fn("profil_colonnes", "Profil statistique des colonnes d'un objet (dernier profilage) : remplissage, unicite, type infere, "
        "motif dominant, min/max. Ce sont des constats statistiques, pas des exigences metier.", {"table_name": _TABLE},
        ["table_name"]),
    _fn("executer_sql", "Requete SELECT en lecture seule, limitee aux schemas autorises (noms complets catalogue.schema.table).",
        {"requete": {"type": "string"}}, ["requete"]),
    _fn("proposer_regle", "Formalise une regle candidate en BROUILLON (statut a_valider). Elle n'est PAS enregistree : "
        "le responsable metier doit la valider.", {
            "table_name": _TABLE,
            "colonnes": {"type": "array", "items": {"type": "string"}},
            "dimension": {"type": "string", "enum": DIMENSIONS},
            "template": {"type": "string", "enum": TEMPLATES},
            "parametres": {"type": "object", "additionalProperties": {"type": "string"}},
            "definition_metier": {"type": "string"},
            "justification": {"type": "string", "description": "Constat qui motive la regle (citer les chiffres)"},
            "critere_acceptation": {"type": "string"},
            "criticite_proposee": {"type": "string", "enum": ["critique", "majeure", "mineure", "a_definir"]},
            "seuil_propose": {"type": "number", "description": "Taux de conformite 0-1, indicatif"},
        }, ["table_name", "colonnes", "dimension", "template", "definition_metier", "justification"]),
]


def system_prompt(prefix: str, catalog: str, bronze_fqn: str | None, source_label: str) -> str:
    schemas = ", ".join(f"{catalog}.{prefix}_{c}" for c in ("config", "results", "silver", "gold"))
    return f"""Tu es l'Analyste Data Quality de SNCF Reseau, dans l'App SNCF DQ Studio.
Perimetre : source {source_label} (Bronze {bronze_fqn or 'non renseigne'}, lecture seule), resultats de la chaine DQ v3
dans les schemas {schemas}.

Ta mission : expliquer les scores et les resultats, resumer les anomalies, identifier des causes possibles, comparer les
executions, proposer des regles candidates, generer du SQL ou du PySpark en brouillon, suggerer des actions correctives.

Regles imperatives :
- Appuie chaque chiffre sur un outil ; cite l'objet et la regle concernes. N'invente ni objet, ni regle, ni seuil.
- Commence toujours par les regles critiques ou bloquantes en echec : ne masque jamais une anomalie critique derriere une moyenne.
- Une criticite ou un seuil a NULL signifie "non valide par le metier" : signale-le.
- Distingue les constats statistiques (profilage, mesures DAMA) des exigences metier (regles validees).
- Distingue les erreurs techniques (execution) des anomalies metier (donnees non conformes).
- Les causes que tu avances sont des hypotheses a verifier avec le Data Steward ou le Data Owner.
- Toute regle candidate passe par l'outil proposer_regle : statut a_valider, jamais enregistree par toi.
  Les seuils et criticites que tu proposes sont indicatifs et doivent etre valides par le responsable metier.
- Le SQL et le PySpark que tu ecris sont des brouillons a faire relire ; tu ne lances aucun job, tu n'ecris rien,
  tu n'executes rien en production.
- Distingue les recommandations DAMA-DMBOK (methode) des choix techniques Databricks (implementation).
- Reponds en francais, de facon structuree et concise, sans emojis."""


@dataclass
class AgentResult:
    answer: str
    tool_calls: list[dict] = field(default_factory=list)
    drafts: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)


def _truncate(text: str, limit: int = MAX_TOOL_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + "\n[... resultat tronque ...]"


class DqAnalyst:
    def __init__(self, model, sql, endpoint: str, catalog: str, prefix: str, bronze_fqn: str | None = None,
                 source_label: str = "", max_rows: int = 200, on_event: Callable[[dict], None] | None = None):
        self.model, self.sql, self.endpoint = model, sql, endpoint
        self.catalog = check_identifier(catalog, "catalogue")
        self.prefix = check_prefix(prefix)
        self.bronze_fqn = bronze_fqn
        self.source_label = source_label or prefix
        self.max_rows = max_rows
        self.on_event = on_event

    # ---------- perimetre ----------
    def t(self, layer: str, table: str) -> str:
        return f"{schema_fqn(self.catalog, self.prefix, layer)}.{table}"

    def allowed_schemas(self) -> set[str]:
        out = {schema_fqn(self.catalog, self.prefix, c) for c in ("config", "results", "silver", "gold")}
        if self.bronze_fqn:
            out.add(self.bronze_fqn.lower())
        return out

    def _q(self, statement: str, params: dict | None = None) -> dict:
        res = self.sql.query(statement, params, row_limit=self.max_rows)
        return {"lignes": res["rows"], "nb_lignes": len(res["rows"]), "tronque": res.get("truncated", False)}

    @staticmethod
    def _filtre(args: dict, col: str = "table_name", key: str = "table_name", alias: str = "") -> tuple[str, dict]:
        v = (args.get(key) or "").strip()
        return (f" AND {alias}{col} = :{key}", {key: v}) if v else ("", {})

    # ---------- outils ----------
    def tool_synthese_qualite(self, args: dict) -> dict:
        f, p = self._filtre(args)
        return self._q(f"SELECT * FROM {self.t('gold', 'v_dq_synthese_table')} WHERE 1 = 1{f} "
                       "ORDER BY nb_critiques_en_echec DESC, nb_bloquantes_en_echec DESC", p)

    def tool_resultats_regles(self, args: dict) -> dict:
        f, p = self._filtre(args, alias="k.")
        if args.get("statut"):
            f += " AND k.statut = :statut"
            p["statut"] = args["statut"]
        return self._q(f"""SELECT k.table_name, k.rule_id, k.dimension, k.criticite, k.action, k.statut, k.nb_controles,
                   k.nb_conformes, k.nb_anomalies, round(k.score, 4) AS taux_conformite, k.seuil, k.inclus_score,
                   c.definition_metier, c.template, c.statut_validation, k.date_kpi
            FROM {self.t('gold', 'v_dq_kpi_courant')} k
            LEFT JOIN {self.t('config', 'dq_rule_catalog')} c ON c.rule_id = k.rule_id AND c.table_name = k.table_name AND c.is_active
            WHERE k.niveau = 'regle'{f}
            ORDER BY CASE k.criticite WHEN 'critique' THEN 0 WHEN 'majeure' THEN 1 WHEN 'mineure' THEN 2 ELSE 3 END,
                     k.nb_anomalies DESC""", p)

    def tool_scores_dama(self, args: dict) -> dict:
        f, p = self._filtre(args)
        if args.get("sous_seuil_uniquement"):
            f += " AND score < seuil"
        return self._q(f"""SELECT table_name, colonne, dimension, famille_score, statut, round(score, 4) AS score, seuil,
                   nb_controles, nb_conformes, inclus_score
            FROM {self.t('gold', 'v_dq_kpi_courant')} WHERE niveau = 'dama'{f}
            ORDER BY score ASC NULLS LAST""", p)

    def tool_anomalies(self, args: dict) -> dict:
        f, p = self._filtre(args)
        if args.get("rule_id"):
            f += " AND rule_id = :rule_id"
            p["rule_id"] = args["rule_id"]
        n = max(1, min(int(args.get("nb_exemples") or 5), 20))
        src = self.t("gold", "v_dq_anomalies_courantes")
        comptage = self.sql.query(f"""SELECT table_name, rule_id, dimension, criticite, action, count(*) AS nb_anomalies,
                   count_if(action_en_retard) AS nb_actions_en_retard
            FROM {src} WHERE 1 = 1{f} GROUP BY ALL ORDER BY nb_anomalies DESC""", p, row_limit=self.max_rows)
        exemples = self.sql.query(f"""SELECT table_name, rule_id, to_json(cle_enregistrement) AS cle, to_json(valeurs) AS valeurs,
                   statut_traitement
            FROM {src} WHERE 1 = 1{f} QUALIFY row_number() OVER (PARTITION BY table_name, rule_id ORDER BY dq_row_id) <= {n}""",
                                  p, row_limit=self.max_rows)
        return {"comptage_par_regle": comptage["rows"], "exemples": exemples["rows"]}

    def tool_historique_executions(self, args: dict) -> dict:
        f, p = self._filtre(args)
        return self._q(f"""SELECT run_id, min(date_execution) AS date_execution, table_name, count(*) AS nb_regles,
                   count_if(statut = 'anomalie') AS nb_en_echec, count_if(statut = 'anomalie' AND criticite = 'critique') AS nb_critiques,
                   count_if(statut = 'erreur_technique') AS nb_erreurs_techniques, sum(nb_anomalies) AS nb_anomalies,
                   round(avg(taux_conformite), 4) AS taux_moyen
            FROM {self.t('results', 'dq_rule_results')} WHERE 1 = 1{f}
            GROUP BY run_id, table_name ORDER BY date_execution DESC LIMIT 40""", p)

    def tool_catalogue_regles(self, args: dict) -> dict:
        f, p = self._filtre(args)
        if args.get("statut_validation"):
            f += " AND statut_validation = :sv"
            p["sv"] = args["statut_validation"]
        return self._q(f"""SELECT rule_id, version, table_name, colonnes, dimension, template, to_json(parametres) AS parametres,
                   definition_metier, critere_acceptation, seuil_cible, criticite, action, origine, statut_validation, is_active
            FROM {self.t('config', 'dq_rule_catalog')} WHERE 1 = 1{f} ORDER BY table_name, rule_id, version""", p)

    def tool_profil_colonnes(self, args: dict) -> dict:
        table = (args.get("table_name") or "").strip()
        if not table:
            return {"erreur": "table_name est obligatoire."}
        return self._q(f"""SELECT colonne, type_physique, type_infere, nb_lignes, nb_null, nb_vide, nb_distinct,
                   round(taux_remplissage, 4) AS taux_remplissage, round(taux_unicite, 4) AS taux_unicite, valeur_min, valeur_max,
                   motif_dominant, round(part_motif_dominant, 4) AS part_motif_dominant, round(part_conforme_type, 4) AS part_conforme_type,
                   nb_atypiques
            FROM {self.t('results', 'dq_profile_column')}
            WHERE table_name = :t AND run_id = (SELECT max_by(run_id, date_profil) FROM {self.t('results', 'dq_profile_table')}
                                                WHERE table_name = :t)
            ORDER BY position""", {"t": table})

    def tool_executer_sql(self, args: dict) -> dict:
        try:
            text = check_read_only(args.get("requete") or "")
            check_scope(text, self.allowed_schemas())
        except SqlGuardError as e:
            return {"erreur": str(e)}
        return self._q(text)

    def tool_proposer_regle(self, args: dict) -> dict:
        draft = {
            "table_name": args.get("table_name"),
            "colonnes": list(args.get("colonnes") or []),
            "dimension": args.get("dimension"),
            "template": args.get("template"),
            "parametres": {str(k): str(v) for k, v in (args.get("parametres") or {}).items()},
            "definition_metier": args.get("definition_metier"),
            "justification_metier": args.get("justification"),
            "critere_acceptation": args.get("critere_acceptation"),
            "criticite_proposee": args.get("criticite_proposee") or "a_definir",
            "seuil_propose": args.get("seuil_propose"),
            "origine": "agent_ia",
            "statut_validation": "a_valider",
            "dq_prefix": self.prefix,
        }
        manquants = [k for k in ("table_name", "dimension", "template", "definition_metier") if not draft.get(k)]
        if manquants:
            return {"erreur": f"Champs manquants : {', '.join(manquants)}."}
        if draft["template"] not in TEMPLATES:
            return {"erreur": f"Template inconnu : {draft['template']}."}
        return {"brouillon": draft, "enregistre": False,
                "note": "Brouillon non enregistre : a valider par le responsable metier (seuil et criticite indicatifs)."}

    def call_tool(self, name: str, args: dict) -> dict:
        fn = getattr(self, f"tool_{name}", None)
        if fn is None or name not in {t["function"]["name"] for t in TOOLS}:
            return {"erreur": f"Outil inconnu : {name}"}
        try:
            return fn(args or {})
        except Exception as e:  # noqa: BLE001  (erreur remontee au modele, pas d'arret de la conversation)
            return {"erreur": f"{type(e).__name__} : {str(e)[:500]}"}

    # ---------- boucle ----------
    def run(self, question: str, history: list[dict] | None = None) -> AgentResult:
        messages = [{"role": "system", "content": system_prompt(self.prefix, self.catalog, self.bronze_fqn, self.source_label)}]
        for h in (history or [])[-10:]:
            if h.get("role") in ("user", "assistant") and h.get("content"):
                messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": question})
        result = AgentResult(answer="")
        for _ in range(MAX_STEPS):
            resp = self.model.chat(self.endpoint, messages, tools=TOOLS, temperature=0.1)
            self._usage(result, resp)
            msg = resp["message"]
            messages.append(msg)
            calls = msg.get("tool_calls") or []
            if not calls:
                result.answer = msg.get("content") or ""
                return result
            for c in calls:
                name = c["function"]["name"]
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args, out = {}, {"erreur": "Arguments JSON invalides."}
                else:
                    out = self.call_tool(name, args)
                if name == "proposer_regle" and "brouillon" in out:
                    result.drafts.append(out["brouillon"])
                event = {"outil": name, "arguments": args, "erreur": out.get("erreur") if isinstance(out, dict) else None,
                         "nb_lignes": out.get("nb_lignes") if isinstance(out, dict) else None}
                result.tool_calls.append(event)
                if self.on_event:
                    self.on_event(event)
                messages.append({"role": "tool", "tool_call_id": c["id"],
                                 "content": _truncate(json.dumps(out, ensure_ascii=False, default=str))})
        messages.append({"role": "user", "content": "Nombre maximal d'appels d'outils atteint : redige maintenant ta reponse "
                                                    "avec les elements obtenus, en signalant ce qui reste a verifier."})
        # outils toujours declares : l'historique contient des appels d'outils ; un nouvel appel est ignore ici
        resp = self.model.chat(self.endpoint, messages, tools=TOOLS, temperature=0.1)
        self._usage(result, resp)
        result.answer = resp["message"].get("content") or (
            "Analyse interrompue : nombre maximal d'appels d'outils atteint. Reformulez la question sur un perimetre plus restreint.")
        return result

    @staticmethod
    def _usage(result: AgentResult, resp: dict) -> None:
        for k, v in (resp.get("usage") or {}).items():
            if isinstance(v, (int, float)):
                result.usage[k] = result.usage.get(k, 0) + v
