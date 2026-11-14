/* Logique pure de complétion des mentions @agent (testée sous Node, chargée par index.html). */
(function (root) {
  function norm(s) {
    return String(s || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  }
  function slug(s) { return norm(s).replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, ""); }

  /* Mention en cours de saisie avant le curseur : {start, query} ou null. */
  function activeMention(text, caret) {
    const before = String(text || "").slice(0, caret);
    const at = before.lastIndexOf("@");
    if (at < 0) return null;
    if (at > 0 && /[\p{L}\p{N}_.]/u.test(before[at - 1])) return null;   // adresse e-mail
    const query = before.slice(at + 1);
    if (query.length > 40 || /[\n@]/.test(query) || query.split(" ").length > 4) return null;
    return { start: at, query: query };
  }

  /* Agents correspondant à la saisie : début du nom, du slug ou d'un mot du nom. */
  function filterAgents(agents, query) {
    const q = norm(query).trim();
    if (!q) return agents.slice(0, 8);
    const qs = slug(query);
    const scored = [];
    agents.forEach(function (a) {
      const n = norm(a.name), s = slug(a.name);
      let score = -1;
      if (n.startsWith(q) || s.startsWith(qs)) score = 0;
      else if (n.split(/\s+/).some(function (w) { return w.startsWith(q); })) score = 1;
      if (score >= 0) scored.push([score, a]);
    });
    scored.sort(function (x, y) { return x[0] - y[0] || x[1].name.localeCompare(y[1].name); });
    return scored.map(function (x) { return x[1]; }).slice(0, 8);
  }

  /* Remplace la mention en cours par « @Nom complet  » ; renvoie {text, caret}. */
  function insertMention(text, caret, mention, name) {
    const ins = "@" + name + " ";
    const after = text.slice(caret).replace(/^ /, "");
    return { text: text.slice(0, mention.start) + ins + after, caret: mention.start + ins.length };
  }

  /* Tab : complète seulement si un seul agent correspond. */
  function tabComplete(text, caret, agents) {
    const m = activeMention(text, caret);
    if (!m || !m.query) return null;
    const hits = filterAgents(agents, m.query);
    return hits.length === 1 ? insertMention(text, caret, m, hits[0].name) : null;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /* HTML du calque de surlignage : mentions reconnues (nom complet) en <mark>. */
  function highlight(text, agents) {
    const names = agents.map(function (a) { return a.name; }).sort(function (a, b) { return b.length - a.length; });
    const nt = norm(text);
    let out = "", i = 0;
    while (i < text.length) {
      if (text[i] === "@" && (i === 0 || !/[\p{L}\p{N}_.]/u.test(text[i - 1]))) {
        const hit = names.find(function (n) {
          const k = norm(n), end = i + 1 + k.length;
          return nt.startsWith(k, i + 1) && (end >= text.length || !/[\p{L}\p{N}]/u.test(text[end]));
        });
        if (hit) {
          const len = 1 + hit.length;
          out += "<mark>" + escapeHtml(text.slice(i, i + len)) + "</mark>";
          i += len;
          continue;
        }
      }
      out += escapeHtml(text[i]);
      i += 1;
    }
    return out + (text.endsWith("\n") ? " " : "");
  }

  /* Vrai si la saisie correspond déjà exactement au nom d'un agent proposé (liste à fermer). */
  function isComplete(query, hits) {
    const q = norm(query).trim();
    return hits.some(function (a) { return norm(a.name) === q; }) && /\s$/.test(query);
  }

  const api = { norm, slug, activeMention, filterAgents, insertMention, tabComplete, highlight, escapeHtml, isComplete };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.MentionLogic = api;
})(typeof window !== "undefined" ? window : this);
