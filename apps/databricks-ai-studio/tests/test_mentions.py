from backend.mentions import MAX_MENTIONS, norm, parse_mentions

AGENTS = [{"agent_id": "dq", "name": "Data Quality Advisor"}, {"agent_id": "se", "name": "Sentinelle DQ Réseau"},
          {"agent_id": "sup", "name": "Superviseur Data Quality"}, {"agent_id": "sql", "name": "SQL Assistant"}]


def ids(r):
    return [a["agent_id"] for a in r.agents]


def test_full_name_case_and_accents():
    r = parse_mentions("@sentinelle dq reseau la table est-elle à jour ?", AGENTS)
    assert ids(r) == ["se"] and r.text == "la table est-elle à jour ?"
    r = parse_mentions("Bonjour @DATA QUALITY ADVISOR, combien d'anomalies ?", AGENTS)
    assert ids(r) == ["dq"] and r.text == "Bonjour, combien d'anomalies ?"


def test_slug_and_short_alias():
    assert ids(parse_mentions("@sentinelle-dq-reseau ok", AGENTS)) == ["se"]
    assert ids(parse_mentions("@sentinelle ok", AGENTS)) == ["se"]
    assert ids(parse_mentions("@sql combien de tables ?", AGENTS)) == ["sql"]
    # « data » est ambigu ? non : seul Data Quality Advisor commence par data -> alias valide
    assert ids(parse_mentions("@data question", AGENTS)) == ["dq"]


def test_longest_match_wins():
    agents = AGENTS + [{"agent_id": "dq2", "name": "Data Quality Advisor Pro"}]
    assert ids(parse_mentions("@Data Quality Advisor Pro test", agents)) == ["dq2"]
    assert ids(parse_mentions("@Data Quality Advisor test", agents)) == ["dq"]
    assert ids(parse_mentions("@data x", agents)) == []        # alias court ambigu : refusé


def test_multiple_dedup_and_limit():
    r = parse_mentions("@sql @sentinelle @sql et @Data Quality Advisor @Superviseur Data Quality", AGENTS)
    assert ids(r) == ["sql", "se", "dq"] and r.truncated and len(r.agents) == MAX_MENTIONS


def test_unknown_with_suggestions_and_emails_ignored():
    r = parse_mentions("@sentinel ? écrire à jean@sncf.fr", AGENTS)
    assert r.agents == [] and r.unknown[0][0] == "sentinel" and "Sentinelle DQ Réseau" in r.unknown[0][1]
    assert all(u[0] != "sncf" for u in r.unknown)
    assert parse_mentions("pas de mention", AGENTS).agents == []


def test_norm_keeps_length():
    t = "Réseau Élève œuvre"
    assert len(norm(t)) == len(t)
