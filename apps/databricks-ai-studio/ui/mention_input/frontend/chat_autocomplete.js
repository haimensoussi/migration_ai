/* Installé une seule fois dans la page Streamlit : liste d'agents sur @ et complétion Tab pour la zone
   de saisie standard (st.chat_input). L'envoi reste celui de Streamlit : si ce script échoue, le chat fonctionne. */
(function () {
  if (window.__dscMentionInstalled) return;
  window.__dscMentionInstalled = true;
  const L = window.MentionLogic;
  const SEL = 'textarea[data-testid="stChatInputTextArea"], [data-testid="stChatInput"] textarea';
  let box = null, items = [], active = 0, mention = null, target = null;

  function agents() { return window.__dscAgents || []; }
  function isChat(el) { return !!(el && el.matches && el.matches(SEL)); }
  function isOpen() { return !!(box && box.style.display === "block" && items.length); }
  function stop(e) { e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation(); }

  function ensureBox() {
    if (box && document.body.contains(box)) return box;
    box = document.createElement("div");
    box.id = "dsc-mention-list";
    box.setAttribute("role", "listbox");
    Object.assign(box.style, { position: "fixed", zIndex: "100000", background: "#fff", border: "1px solid #E6E3EA",
      borderRadius: "10px", boxShadow: "0 6px 18px rgba(43,27,51,.15)", maxHeight: "260px", overflowY: "auto",
      display: "none", fontFamily: "inherit", minWidth: "260px" });
    document.body.appendChild(box);
    return box;
  }
  function close() { if (box) { box.style.display = "none"; box.innerHTML = ""; } items = []; mention = null; }

  function setValue(ta, v, caret) {
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
    setter.call(ta, v);                                   // champ contrôlé par React : setter natif + événement input
    ta.dispatchEvent(new Event("input", { bubbles: true }));
    ta.setSelectionRange(caret, caret);
  }

  function render() {
    const b = ensureBox();
    let html = '<div style="font-size:12px;color:#6B6475;padding:7px 12px 4px">Agents disponibles</div>';
    items.forEach(function (a, i) {
      const ini = a.name.split(/\s+/).filter(Boolean).slice(0, 1).map(function (w) { return w[0]; }).join("").toUpperCase();
      const head = (a.handle ? "@" + a.handle + " · " : "") + a.name + (a.persona ? ", " + a.persona : "");
      const sub = a.tagline || a.category || "";
      html += '<div data-i="' + i + '" style="display:flex;align-items:center;gap:10px;padding:7px 12px;cursor:pointer;' +
        (i === active ? "background:#FBF2F7;" : "") + '">' +
        '<div style="width:26px;height:26px;border-radius:8px;background:#FBF2F7;color:#B0124F;border:1px solid #EAD3E0;' +
        'font-weight:700;font-size:11px;display:flex;align-items:center;justify-content:center;flex:none">' + L.escapeHtml(ini) +
        '</div><div style="min-width:0"><div style="color:#2B1B33;font-size:14px;font-weight:600">' + L.escapeHtml(head) +
        ' <span style="font-weight:500;font-size:10px;color:#7A3E9D;border:1px solid #E3D3EC;border-radius:6px;padding:0 5px">Agent IA</span></div>' +
        (sub ? '<div style="color:#6B6475;font-size:12px;white-space:normal">' + L.escapeHtml(sub) + "</div>" : "") + "</div></div>";
    });
    b.innerHTML = html;
    b.querySelectorAll("[data-i]").forEach(function (el) {
      el.addEventListener("mousedown", function (e) { e.preventDefault(); choose(Number(el.getAttribute("data-i"))); });
    });
    b.style.display = "block";
    const r = target.getBoundingClientRect();
    b.style.left = r.left + "px";
    b.style.width = Math.max(300, Math.min(r.width, 520)) + "px";
    b.style.top = Math.max(8, r.top - b.offsetHeight - 8) + "px";
    const cur = b.querySelector('[data-i="' + active + '"]');
    if (cur) cur.scrollIntoView({ block: "nearest" });
  }

  function refresh(ta) {
    target = ta;
    if (!agents().length) { close(); return; }
    mention = L.activeMention(ta.value, ta.selectionStart);
    if (!mention) { close(); return; }
    items = L.filterAgents(agents(), mention.query);
    if (!items.length || L.isComplete(mention.query, items)) { close(); return; }
    if (active >= items.length) active = 0;
    render();
  }

  function choose(i) {
    if (!mention || !items[i] || !target) return;
    const r = L.insertMention(target.value, target.selectionStart, mention, items[i].handle || items[i].name);
    close();
    setValue(target, r.text, r.caret);
    target.focus();
  }

  document.addEventListener("input", function (e) { if (isChat(e.target)) { active = 0; refresh(e.target); } }, true);
  document.addEventListener("click", function (e) {
    if (isChat(e.target)) refresh(e.target);
    else if (box && !box.contains(e.target)) close();
  }, true);
  document.addEventListener("keydown", function (e) {
    if (!isChat(e.target) || e.isComposing) return;
    if (isOpen() && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
      stop(e); active = (active + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length; render(); return;
    }
    if (isOpen() && (e.key === "Enter" || e.key === "Tab") && !e.shiftKey) { stop(e); choose(active); return; }
    if (e.key === "Escape" && box && box.style.display === "block") { stop(e); close(); return; }
    if (e.key === "Tab" && !e.shiftKey) {
      const r = L.tabComplete(e.target.value, e.target.selectionStart, agents());
      if (r) { stop(e); close(); setValue(e.target, r.text, r.caret); }
    }
  }, true);
  document.addEventListener("focusout", function (e) { if (isChat(e.target)) setTimeout(close, 150); }, true);
  window.addEventListener("resize", function () { if (isOpen() && target) render(); });
})();
