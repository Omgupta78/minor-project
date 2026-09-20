/* CSRF support and small compatibility fixes for existing templates. */
(function () {
  "use strict";
  function cookie(name) {
    var prefix = name + "=";
    return document.cookie.split(";").map(function (v) { return v.trim(); })
      .filter(function (v) { return v.indexOf(prefix) === 0; })
      .map(function (v) { return decodeURIComponent(v.slice(prefix.length)); })[0] || "";
  }
  function protectForms() {
    var token = cookie("csrf_token");
    if (!token) return;
    document.querySelectorAll("form").forEach(function (form) {
      var method = (form.getAttribute("method") || "get").toLowerCase();
      if (method === "get" || form.querySelector('input[name="csrf_token"]')) return;
      var input = document.createElement("input");
      input.type = "hidden"; input.name = "csrf_token"; input.value = token;
      form.appendChild(input);
    });
    document.querySelectorAll('[data-icon="logout"]').forEach(function (icon) {
      icon.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 5H5v14h5"/><path d="M13 8l4 4-4 4"/><path d="M17 12H8"/></svg>';
    });
  }
  var originalFetch = window.fetch;
  window.fetch = function (input, init) {
    init = init || {};
    var url = typeof input === "string" ? input : input.url;
    if (!url || new URL(url, location.href).origin === location.origin) {
      var headers = new Headers(init.headers || (typeof input !== "string" ? input.headers : undefined));
      var token = cookie("csrf_token");
      if (token) headers.set("X-CSRF-Token", token);
      init.headers = headers;
    }
    return originalFetch.call(this, input, init);
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", protectForms);
  else protectForms();
})();
