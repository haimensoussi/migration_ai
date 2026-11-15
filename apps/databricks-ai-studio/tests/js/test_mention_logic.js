const assert = require("assert");
const L = require("../../ui/mention_input/frontend/mention_logic.js");
const A = [{ name: "Data Quality Advisor" }, { name: "Sentinelle DQ Réseau" }, { name: "Superviseur Data Quality" },
           { name: "SQL Assistant" }, { name: "Smart Office" }];
const names = (xs) => xs.map((a) => a.name);

// Ouverture de la liste
assert.deepStrictEqual(L.activeMention("bonjour @", 9), { start: 8, query: "" });
assert.deepStrictEqual(L.activeMention("@sen", 4), { start: 0, query: "sen" });
assert.strictEqual(L.activeMention("jean@sncf.fr", 12), null);            // e-mail
assert.strictEqual(L.activeMention("pas de mention", 14), null);
assert.strictEqual(L.activeMention("@a\nb", 4), null);                   // retour à la ligne : liste fermée
// Filtre
assert.strictEqual(L.filterAgents(A, "").length, 5);
assert.deepStrictEqual(names(L.filterAgents(A, "sen")), ["Sentinelle DQ Réseau"]);
assert.deepStrictEqual(names(L.filterAgents(A, "s")), ["Sentinelle DQ Réseau", "Smart Office", "SQL Assistant", "Superviseur Data Quality"]);
assert.deepStrictEqual(names(L.filterAgents(A, "RESEAU")), ["Sentinelle DQ Réseau"]);   // mot du nom, sans accent
assert.deepStrictEqual(names(L.filterAgents(A, "data q")), ["Data Quality Advisor"]);
assert.deepStrictEqual(names(L.filterAgents(A, "qual")), ["Data Quality Advisor", "Superviseur Data Quality"]);
// Insertion
let r = L.insertMention("Bonjour @sen la table", 12, { start: 8, query: "sen" }, "Sentinelle DQ Réseau");
assert.strictEqual(r.text, "Bonjour @Sentinelle DQ Réseau la table");
assert.strictEqual(r.text.slice(0, r.caret), "Bonjour @Sentinelle DQ Réseau ");
// Tab : complétion unique seulement
assert.strictEqual(L.tabComplete("@sen", 4, A).text, "@Sentinelle DQ Réseau ");
assert.strictEqual(L.tabComplete("@s", 2, A), null);
assert.strictEqual(L.tabComplete("@", 1, A), null);
// Surlignage et échappement
assert.strictEqual(L.highlight("@sql assistant <b>", A), "<mark>@sql assistant</mark> &lt;b&gt;");
assert.strictEqual(L.highlight("@Data Quality Advisor, ok", A), "<mark>@Data Quality Advisor</mark>, ok");
assert.strictEqual(L.highlight("@Data Quality Advisors", A), "@Data Quality Advisors");
console.log("OK mention_logic");

// Mention déjà complète suivie d'un espace : liste fermée
assert.strictEqual(L.isComplete("Sentinelle DQ Réseau ", L.filterAgents(A, "Sentinelle DQ Réseau ")), true);
assert.strictEqual(L.isComplete("Sentinelle", L.filterAgents(A, "Sentinelle")), false);
console.log("OK isComplete");


// --- Identité des agents : @nom d'appel, anciens noms, mots de l'accroche ---
(function () {
  const assert = require("assert");
  const L = require("../../ui/mention_input/frontend/mention_logic.js");
  const P = [{ name: "Margot", handle: "margot", persona: "la cartographe", tagline: "Je situe les gares sur une carte.",
               aliases: ["Carto Réseau"] },
             { name: "Victor", handle: "victor", persona: "le veilleur", tagline: "Je surveille la fraîcheur." }];
  assert.deepStrictEqual(L.filterAgents(P, "vic").map(a => a.name), ["Victor"]);
  assert.deepStrictEqual(L.filterAgents(P, "carto").map(a => a.name), ["Margot"]);      // ancien nom
  assert.deepStrictEqual(L.filterAgents(P, "carte").map(a => a.name), ["Margot"]);      // mot de l'accroche
  assert.deepStrictEqual(L.filterAgents(P, "fraich").map(a => a.name), ["Victor"]);
  assert.deepStrictEqual(L.filterAgents(P, "ca").map(a => a.name), ["Margot"]);         // < 3 lettres : pas l'accroche
  const t = L.tabComplete("Bonjour @mar", 12, P);
  assert.strictEqual(t.text, "Bonjour @margot ");
  assert.ok(L.highlight("@margot et @Carto Réseau", P).split("<mark>").length === 3);
  assert.ok(L.isComplete("margot ", P));
  console.log("identité des agents : ok");
})();
