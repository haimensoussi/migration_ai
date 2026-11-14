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
