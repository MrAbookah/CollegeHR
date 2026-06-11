// CollegeDB — tiny vanilla-JS helper. No framework, no build step.
// 1. data-poll: periodically refresh a fragment from the server (bell).
// 2. .tabs a[data-url]: lazy-load person-360 tabs into #tab-panel.
// 3. form[data-confirm]: confirm before destructive submits.

function pollFragments() {
  document.querySelectorAll("[data-poll]").forEach(function (el) {
    var interval = (parseInt(el.dataset.pollInterval, 10) || 60) * 1000;
    setInterval(function () {
      if (el.querySelector("details[open]")) return; // don't yank an open menu
      fetch(el.dataset.poll, { headers: { "X-Requested-With": "fetch" } })
        .then(function (r) { return r.ok ? r.text() : null; })
        .then(function (html) { if (html !== null) el.innerHTML = html; })
        .catch(function () {});
    }, interval);
  });
}

function initTabs() {
  var panel = document.getElementById("tab-panel");
  if (!panel) return;
  var links = document.querySelectorAll(".tabs a[data-url]");
  function load(link, push) {
    links.forEach(function (l) { l.classList.remove("active"); });
    link.classList.add("active");
    panel.innerHTML = '<p class="muted">Loading…</p>';
    fetch(link.dataset.url, { headers: { "X-Requested-With": "fetch" } })
      .then(function (r) { return r.text(); })
      .then(function (html) { panel.innerHTML = html; })
      .catch(function () { panel.innerHTML = '<p class="msg error">Could not load this tab.</p>'; });
    if (push) history.replaceState(null, "", "#" + link.dataset.tab);
  }
  links.forEach(function (link) {
    link.addEventListener("click", function (e) { e.preventDefault(); load(link, true); });
  });
  var initial = null;
  if (location.hash) {
    initial = document.querySelector('.tabs a[data-tab="' + location.hash.slice(1) + '"]');
  }
  initial = initial || links[0];
  if (initial) load(initial, false);
}

function initConfirms() {
  document.addEventListener("submit", function (e) {
    var form = e.target.closest("form[data-confirm]");
    if (form && !window.confirm(form.dataset.confirm)) e.preventDefault();
  });
}

document.addEventListener("DOMContentLoaded", function () {
  pollFragments();
  initTabs();
  initConfirms();
});
