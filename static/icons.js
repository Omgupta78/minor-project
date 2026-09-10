/* Offline icon set.
 *
 * The UI was written against the Material Symbols webfont, where the element's
 * text ("download") is turned into a glyph by a font ligature. With no
 * internet that font never loads and the browser prints the literal word
 * inside every button. This script swaps each icon element for a small inline
 * SVG drawn locally, so the interface looks the same on a machine with no
 * network at all.
 *
 * Adding an icon: add its name here, using a 24x24 viewBox and currentColor.
 */
(function () {
  "use strict";

  var S = {
    download: '<path d="M12 3v11"/><path d="M7.5 10.5 12 15l4.5-4.5"/><path d="M4 20h16"/>',
    upload: '<path d="M12 21V10"/><path d="M7.5 13.5 12 9l4.5 4.5"/><path d="M4 4h16"/>',
    close: '<path d="M6 6l12 12"/><path d="M18 6 6 18"/>',
    delete: '<path d="M4 7h16"/><path d="M9.5 7V4h5v3"/><path d="M6.5 7 7.5 20h9L17.5 7"/><path d="M10.5 11v5"/><path d="M13.5 11v5"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="M16.2 16.2 21 21"/>',
    schedule: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5.3l3.4 2"/>',
    face: '<circle cx="12" cy="12" r="9"/><path d="M9 10h.01"/><path d="M15 10h.01"/><path d="M8.4 14.3c.9 1.4 2.1 2.1 3.6 2.1s2.7-.7 3.6-2.1"/>',
    school: '<path d="M2.5 9 12 4.2 21.5 9 12 13.8z"/><path d="M6.5 11.6V17c0 1.4 2.5 2.4 5.5 2.4s5.5-1 5.5-2.4v-5.4"/>',
    task_alt: '<circle cx="12" cy="12" r="9"/><path d="M8 12.3l2.8 2.8L16.4 9.5"/>',
    check_circle: '<circle cx="12" cy="12" r="9"/><path d="M8 12.3l2.8 2.8L16.4 9.5"/>',
    error: '<circle cx="12" cy="12" r="9"/><path d="M12 7.4v5.4"/><path d="M12 16.3h.01"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11.2v5.4"/><path d="M12 7.7h.01"/>',
    camera_alt: '<path d="M3 7.8h4L8.4 5.2h7.2L17 7.8h4V19H3z"/><circle cx="12" cy="13.2" r="3.6"/>',
    add_a_photo: '<path d="M14 19.5H3V8h4l1.4-2.6h4.3"/><circle cx="8.5" cy="13.6" r="3.3"/><path d="M18.5 3.5v7"/><path d="M15 7h7"/>',
    burst_mode: '<path d="M3 6.5v11"/><path d="M6.2 5.5v13"/><path d="M9.5 5.5H21v13H9.5z"/><path d="M11.4 15.6l2.7-3.2 2 2.3 1.7-2 2.2 2.9"/>',
    radio_button_checked: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4" fill="currentColor" stroke="none"/>',
    person_add: '<circle cx="9.5" cy="8.2" r="3.6"/><path d="M3 20c0-3.6 2.9-5.6 6.5-5.6s6.5 2 6.5 5.6"/><path d="M19 6.5v6"/><path d="M16 9.5h6"/>',
    group_add: '<circle cx="8" cy="8.6" r="3.4"/><path d="M2 19.5c0-3.3 2.7-5.2 6-5.2s6 1.9 6 5.2"/><path d="M18.5 7v6"/><path d="M15.5 10h6"/>',
    person_off: '<circle cx="12" cy="8" r="3.6"/><path d="M5.5 20c0-3.6 2.9-5.6 6.5-5.6 1.2 0 2.3.2 3.2.6"/><path d="M4 4l16 16"/>',
    badge: '<path d="M3.5 5.5h17v13h-17z"/><circle cx="8.8" cy="10.8" r="2.1"/><path d="M5.6 16.5c.5-1.7 1.7-2.5 3.2-2.5s2.7.8 3.2 2.5"/><path d="M14.5 9.8h4"/><path d="M14.5 13.5h4"/>',
    fact_check: '<path d="M3.5 4.5h17v15h-17z"/><path d="M7 9h6"/><path d="M7 13h5"/><path d="M13.5 15.8l1.6 1.6 3.2-3.4"/>',
    event_note: '<path d="M3.5 5.5h17v14h-17z"/><path d="M3.5 10h17"/><path d="M8 3.5v4"/><path d="M16 3.5v4"/><path d="M7 13.5h8"/><path d="M7 16.5h5"/>',
    description: '<path d="M6 3.5h8l4 4v13H6z"/><path d="M13.8 3.6V8h4.3"/><path d="M9 12.5h6"/><path d="M9 16h6"/>',
    inbox: '<path d="M3.5 13h4.6l1.5 3h4.8l1.5-3h4.6"/><path d="M3.5 13 6 5h12l2.5 8v6.5h-17z"/>',
    leaderboard: '<path d="M5 20v-7"/><path d="M12 20V4.5"/><path d="M19 20v-10"/>',
    library_add: '<path d="M8.5 3.5h12v12h-12z"/><path d="M4.5 7.5v13h13"/><path d="M14.5 6v7"/><path d="M11 9.5h7"/>',
    arrow_back: '<path d="M20 12H4.5"/><path d="M10.5 6 4.5 12l6 6"/>',
    chevron_right: '<path d="M9.5 5.5 16 12l-6.5 6.5"/>',
    chevron_left: '<path d="M14.5 5.5 8 12l6.5 6.5"/>',
    expand_more: '<path d="M5.5 9.5 12 16l6.5-6.5"/>',
    edit: '<path d="M4 20h4l11-11-4-4L4 16z"/><path d="M14.5 5.5l4 4"/>',
    add: '<path d="M12 5v14"/><path d="M5 12h14"/>',
    // Anything not listed renders as a neutral dot rather than breaking layout.
    _fallback: '<circle cx="12" cy="12" r="3.2" fill="currentColor" stroke="none"/>',
  };

  function svg(name) {
    var body = Object.prototype.hasOwnProperty.call(S, name) && name.charAt(0) !== "_"
      ? S[name] : S._fallback;
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" ' +
      'aria-hidden="true" focusable="false">' + body + "</svg>";
  }

  function render(root) {
    var nodes = (root || document).querySelectorAll(".material-symbols-outlined");
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (el.dataset.icon) continue;              // already rendered
      var name = (el.textContent || "").trim();
      el.dataset.icon = name || "_fallback";
      if (!el.getAttribute("aria-label") && name) {
        el.setAttribute("aria-hidden", "true");   // decorative next to a text label
      }
      el.innerHTML = svg(name);
      el.classList.add("icon-ready");
    }
  }

  window.renderIcons = render;   // call after injecting markup with innerHTML

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { render(); });
  } else {
    render();
  }

  // Lists are re-rendered from JavaScript (review roster, thumbnails), so watch
  // for new icon elements instead of asking every caller to remember.
  if (window.MutationObserver) {
    new MutationObserver(function (records) {
      for (var i = 0; i < records.length; i++) {
        if (records[i].addedNodes.length) { render(); return; }
      }
    }).observe(document.documentElement, { childList: true, subtree: true });
  }
})();
