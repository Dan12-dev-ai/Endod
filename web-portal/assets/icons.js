/*
 * DEDAN icon set.
 *
 * Why this exists
 * ---------------
 * Every page rendered icons as `<span class="material-symbols-outlined">home</span>`
 * and relied on the Material Symbols webfont from fonts.googleapis.com. When
 * that request fails -- which it does whenever the machine is offline, on a
 * hospital wifi with a captive portal, or during any CDN incident -- the
 * browser falls back to the body font and prints the ligature *word*:
 *
 *     home        video_chat        clinical_notes
 *
 * The sidebar then fills with English words, pushes every label into a
 * truncated ellipsis, and the product reads as broken. This is the same class
 * of problem the project already fixed for Tailwind, which was moved off the
 * CDN and compiled into `assets/tailwind.css`. The icon font was never given
 * the same treatment.
 *
 * What this is
 * ------------
 * A small, self-contained line-icon set rendered as inline SVG. It is DEDAN's
 * own artwork, not a copy of Google's Material Symbols glyphs -- those are
 * Apache-2.0 licensed but the exact outlines are not reproducible without the
 * font binary, so claiming parity would be false. Every icon here is drawn on
 * the same 24x24 grid with the same stroke weight and cap style, which is what
 * makes the set read as one family.
 *
 * How it is used
 * --------------
 * Existing markup is unchanged: `<span class="material-symbols-outlined">home
 * </span>` is hydrated in place into an inline `<svg>`. Pages need no edits,
 * and `data-dedan-icon` forces a specific icon (used by the sidebar, where the
 * name is supplied from nav.js rather than from the element's text).
 *
 * If an icon name is not in the set, the span is emptied rather than left to
 * print its own name -- a missing glyph must never become visible text.
 */
(function (global) {
  'use strict';

  // 24x24 grid, 1.8 stroke, round caps and joins, no fills. One style
  // throughout; mixing weights is what makes an icon set look assembled.
  var P = {
    home: '<path d="M3.5 10.8 12 3.5l8.5 7.3"/><path d="M5.8 9.6V20.5h12.4V9.6"/>',
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
    close: '<path d="M6 6l12 12M18 6L6 18"/>',
    search: '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.2 5.2l2.1 2.1M16.7 16.7l2.1 2.1M18.8 5.2l-2.1 2.1M7.3 16.7l-2.1 2.1"/>',
    logout: '<path d="M14.5 4H19v16h-4.5"/><path d="M10 8.5 6 12l4 3.5M6.5 12H16"/>',
    person: '<circle cx="12" cy="8" r="3.6"/><path d="M4.8 20.5c0-3.9 3.2-6.1 7.2-6.1s7.2 2.2 7.2 6.1"/>',
    account_circle: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="10" r="2.8"/><path d="M6.2 19.4c1.2-2.6 3.3-4 5.8-4s4.6 1.4 5.8 4"/>',
    group_add: '<circle cx="9" cy="8.5" r="3.2"/><path d="M2.8 19.6c0-3.4 2.8-5.3 6.2-5.3s6.2 1.9 6.2 5.3"/><path d="M18 14.5v5M15.5 17h5"/>',
    event: '<rect x="3.5" y="5" width="17" height="15.5" rx="2"/><path d="M3.5 9.5h17M8 3v4M16 3v4"/>',
    event_available: '<rect x="3.5" y="5" width="17" height="15.5" rx="2"/><path d="M3.5 9.5h17M8 3v4M16 3v4"/><path d="M8.8 15.2l2.2 2.2 4-4.2"/>',
    event_repeat: '<path d="M4 9.5V7a2 2 0 0 1 2-2h12"/><path d="M20 14.5V17a2 2 0 0 1-2 2H6"/><path d="M17.5 8.5 20 6l2.5 2.5M6.5 15.5 4 18l-2.5-2.5" transform="translate(2.5 0)"/>',
    calendar_month: '<rect x="3.5" y="5" width="17" height="15.5" rx="2"/><path d="M3.5 9.5h17M8 3v4M16 3v4"/><path d="M7.5 13h3M7.5 16.5h3M13.5 13h3M13.5 16.5h3"/>',
    schedule: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5.2l3.4 2"/>',
    clinical_notes: '<path d="M6 3.5h8.5L19 8v12.5H6z"/><path d="M14 3.5V8h5"/><path d="M9 12.5h7M9 16h5"/>',
    description: '<path d="M6 3.5h8.5L19 8v12.5H6z"/><path d="M14 3.5V8h5"/><path d="M9 12h7M9 15.5h7"/>',
    article: '<path d="M6 3.5h8.5L19 8v12.5H6z"/><path d="M14 3.5V8h5"/><path d="M9 11.5h7M9 15h7M9 18h4"/>',
    menu_book: '<path d="M3.5 5.5A2 2 0 0 1 5.5 3.5H10v16H5.5a2 2 0 0 0-2 2z"/><path d="M20.5 5.5a2 2 0 0 0-2-2H14v16h4.5a2 2 0 0 1 2 2z"/>',
    medical_information: '<rect x="3.5" y="5" width="17" height="15.5" rx="2"/><path d="M12 9v7.5M8.2 12.8h7.6"/>',
    medication: '<path d="M10.5 4.5a5 5 0 0 1 7 7l-6 6a5 5 0 0 1-7-7z" transform="rotate(-45 12 12)"/><path d="M8 8l7 7"/>',
    prescriptions: '<path d="M6 3.5h12v17H6z"/><path d="M9 8h6M9 12h6"/><path d="M14.5 16.5l3.5 3.5M18 16.5l-3.5 3.5"/>',
    biotech: '<path d="M9 3.5v6L4.5 18a2 2 0 0 0 1.7 3h11.6a2 2 0 0 0 1.7-3L15 9.5v-6"/><path d="M8 3.5h8M6.8 14.5h10.4"/>',
    science: '<path d="M10 3.5v6.2L4.8 18a2 2 0 0 0 1.7 3h11a2 2 0 0 0 1.7-3L14 9.7V3.5"/><path d="M8.6 3.5h6.8"/><circle cx="10.5" cy="17" r="1"/><circle cx="14.5" cy="19" r="1"/>',
    radiology: '<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5v17M3.5 12h17"/><path d="M6 6l12 12"/>',
    local_hospital: '<path d="M4 8.5h16v11.5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1z"/><path d="M8.5 8.5V4.5a1 1 0 0 1 1-1h5a1 1 0 0 1 1 1v4"/><path d="M12 11v5M9.5 13.5h5"/>',
    health_and_safety: '<path d="M12 3.2 4.5 6v6c0 4.4 3.1 7.6 7.5 9 4.4-1.4 7.5-4.6 7.5-9V6z"/><path d="M12 9v4M12 15.6v.2"/>',
    shield: '<path d="M12 3.2 4.5 6v6c0 4.4 3.1 7.6 7.5 9 4.4-1.4 7.5-4.6 7.5-9V6z"/>',
    shield_lock: '<path d="M12 3.2 4.5 6v6c0 4.4 3.1 7.6 7.5 9 4.4-1.4 7.5-4.6 7.5-9V6z"/><rect x="9.2" y="10.5" width="5.6" height="4.6" rx="1"/><path d="M10.4 10.5V9.4a1.6 1.6 0 0 1 3.2 0v1.1"/>',
    shield_locked: '<path d="M12 3.2 4.5 6v6c0 4.4 3.1 7.6 7.5 9 4.4-1.4 7.5-4.6 7.5-9V6z"/><rect x="9.2" y="10.5" width="5.6" height="4.6" rx="1"/><path d="M10.4 10.5V9.4a1.6 1.6 0 0 1 3.2 0v1.1"/>',
    shield_with_heart: '<path d="M12 3.2 4.5 6v6c0 4.4 3.1 7.6 7.5 9 4.4-1.4 7.5-4.6 7.5-9V6z"/><path d="M12 16.2c-2.6-1.6-3.9-3-3.9-4.6a2 2 0 0 1 3.9-.9 2 2 0 0 1 3.9.9c0 1.6-1.3 3-3.9 4.6z"/>',
    emergency: '<path d="M12 3.5 2.5 20.5h19z"/><path d="M12 9.5v5M12 17v.2"/>',
    e911_emergency: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5v5M12 15.5v.2M8.2 10.5h2.3M13.5 10.5h2.3M9.3 14.2h5.4"/>',
    gavel: '<path d="M13.5 4.5 19.5 10.5M16.5 7.5 9.5 14.5"/><path d="M4 20.5h9"/><path d="M6.5 14 12 19.5"/>',
    badge: '<path d="M12 3.5 14.5 8l5 .8-3.6 3.5.9 5-4.8-2.5-4.8 2.5.9-5L4.5 8.8l5-.8z"/>',
    verified: '<path d="m12 3.5 2.2 1.6 2.7-.3 1 2.5 2.3 1.4-.8 2.6.8 2.6-2.3 1.4-1 2.5-2.7-.3L12 20.5l-2.2-1.6-2.7.3-1-2.5-2.3-1.4.8-2.6-.8-2.6L6.1 8.8l1-2.5 2.7.3z"/><path d="m9 12 2.2 2.2L15.2 10"/>',
    verified_user: '<circle cx="10" cy="8" r="3.4"/><path d="M3.8 20c0-3.5 2.8-5.5 6.2-5.5 1.2 0 2.3.2 3.2.7"/><path d="m14.5 19.5 2 2 4-4.4"/>',
    vital_signs: '<path d="M2.5 12h4l2-5 3.5 10 2.5-7 1.5 2h6"/>',
    monitor_heart: '<rect x="2.8" y="4.5" width="18.4" height="13" rx="2"/><path d="M6 12.5h2.8l1.6-3 2.4 5 1.6-2.6H18"/><path d="M9 20.5h6M12 17.5v3"/>',
    monitoring: '<path d="M2.5 12h4l2-5 3.5 10 2.5-7 1.5 2h6"/>',
    call: '<path d="M6.5 3.8 9 7.4 7.4 9.6a12.5 12.5 0 0 0 7 7l2.2-1.6 3.6 2.5-.8 3a1.5 1.5 0 0 1-1.6 1.1C10 20.5 3.5 14 2.5 6.2A1.5 1.5 0 0 1 3.6 4.6z"/>',
    call_end: '<path d="M2.5 13.5c0-1 .9-1.8 2-1.6l4 .9c.8.2 1.3 1 1.2 1.8l-.2 1.6a13 13 0 0 0 5.1 5.1l1.6-.2c.8-.1 1.6.4 1.8 1.2l.9 4c.2 1.1-.6 2-2 1.6C9.5 20.5 3.5 14.5 2.5 7.5c-.4-1.4 0-6 0-6"/>',
    phone: '<path d="M6.5 3.8 9 7.4 7.4 9.6a12.5 12.5 0 0 0 7 7l2.2-1.6 3.6 2.5-.8 3a1.5 1.5 0 0 1-1.6 1.1C10 20.5 3.5 14 2.5 6.2A1.5 1.5 0 0 1 3.6 4.6z"/>',
    mail: '<rect x="3" y="5.5" width="18" height="13" rx="2"/><path d="m3.6 7 8.4 6 8.4-6"/>',
    notifications_none: '<path d="M6 9.5a6 6 0 1 1 12 0c0 4 1.5 5.5 1.5 5.5h-15S6 13.5 6 9.5"/><path d="M10 18.5a2.2 2.2 0 0 0 4 0"/>',
    help_center: '<circle cx="12" cy="12" r="8.5"/><path d="M9.6 9.4a2.5 2.5 0 1 1 3.4 2.3c-.7.3-1 .9-1 1.7v.3"/><path d="M12 16.8v.2"/>',
    lock: '<rect x="5" y="10.5" width="14" height="9.5" rx="2"/><path d="M8 10.5V7.8a4 4 0 0 1 8 0v2.7"/>',
    lock_clock: '<rect x="4.5" y="10.5" width="15" height="9.5" rx="2"/><path d="M8 10.5V7.8a4 4 0 0 1 8 0v2.7"/><path d="M12 13.8V16l1.4.9"/>',
    lock_reset: '<rect x="5" y="10.5" width="14" height="9.5" rx="2"/><path d="M8 10.5V7.8a4 4 0 0 1 7.7-1.5"/><path d="M14 4.5v2.4h-2.4"/>',
    fingerprint: '<path d="M12 4.5a7.5 7.5 0 0 0-7.5 7.5v2"/><path d="M12 8a4 4 0 0 0-4 4v4"/><path d="M12 8a4 4 0 0 1 4 4v2.5"/><path d="M19.5 12a7.5 7.5 0 0 0-3.2-6.2"/><path d="M8.8 20.5A9 9 0 0 0 9.8 17v-5"/><path d="M14.5 20.5a9 9 0 0 0 .7-3.5v-3"/>',
    key: '<circle cx="8" cy="12" r="4"/><path d="M12 12h9M17.5 12v3.5M20.5 12v2.5"/>',
    location_on: '<path d="M12 21s7-5.7 7-11a7 7 0 1 0-14 0c0 5.3 7 11 7 11"/><circle cx="12" cy="10" r="2.6"/>',
    near_me: '<path d="M20.5 3.5 3.5 10.2l6.5 3 3 6.5z"/>',
    domain: '<path d="M4 20.5h16"/><path d="M5.5 20.5V9l6.5-5 6.5 5v11.5"/><path d="M9.5 20.5v-5h5v5"/><path d="M9.5 12h1M13.5 12h1"/>',
    search_center: '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>',
    sync: '<path d="M20 12a8 8 0 0 1-14 5"/><path d="M4 12a8 8 0 0 1 14-5"/><path d="M18 3.5V7h-3.5M6 20.5V17h3.5"/>',
    sync_alt: '<path d="M20 12a8 8 0 0 1-14 5"/><path d="M4 12a8 8 0 0 1 14-5"/><path d="M18 3.5V7h-3.5M6 20.5V17h3.5"/>',
    speed: '<path d="M12 20.5a8.5 8.5 0 1 1 8.5-8.5"/><path d="m12 12 5-4"/><circle cx="12" cy="12" r="1.6"/>',
    tune: '<path d="M4 7h10M18 7h2M4 12h2M10 12h10M4 17h7M15 17h5"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="12" r="2"/><circle cx="13" cy="17" r="2"/>',
    fullscreen: '<path d="M3.5 9V3.5H9M15 3.5h5.5V9M20.5 15v5.5H15M9 20.5H3.5V15"/>',
    expand_more: '<path d="m6 9.5 6 6 6-6"/>',
    visibility: '<path d="M1.8 12S5.5 5.5 12 5.5 22.2 12 22.2 12 18.5 18.5 12 18.5 1.8 12 1.8 12"/><circle cx="12" cy="12" r="3"/>',
    visibility_off: '<path d="M9.5 5.9A9.6 9.6 0 0 1 12 5.5c6.5 0 10.2 6.5 10.2 6.5a17 17 0 0 1-3 3.8M6.3 7.8A16.7 16.7 0 0 0 1.8 12S5.5 18.5 12 18.5c1.4 0 2.6-.3 3.7-.8"/><path d="m3 3 18 18"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
    arrow_forward: '<path d="M4 12h15"/><path d="m13 6 6 6-6 6"/>',
    mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0"/><path d="M12 18v3M9 21h6"/>',
    videocam: '<rect x="2.5" y="6" width="13" height="12" rx="2"/><path d="m15.5 11 6-3.5v9l-6-3.5z"/>',
    volume_up: '<path d="M4 9.5v5h3.5L12 18.5v-13L7.5 9.5z"/><path d="M15.5 9.2a4 4 0 0 1 0 5.6"/><path d="M18.2 6.5a8 8 0 0 1 0 11"/>',
    record_voice_over: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5a4.5 4.5 0 0 1 0 9 4.5 4.5 0 0 1 0-9"/><path d="M5.5 5.5 18.5 18.5"/>',
    graphic_eq: '<path d="M4 10v4M8 7v10M12 4v16M16 8v8M20 10.5v3"/>',
    video_chat: '<rect x="2.5" y="6" width="13" height="12" rx="2"/><path d="m15.5 11 6-3.5v9l-6-3.5z"/><path d="M6.5 10.5h5M6.5 13.5h3"/>',
    send: '<path d="M21 3 3 10.5l7 3 3 7z"/><path d="m10 13.5 4-4"/>',
    forum: '<path d="M4 5.5h16v10H9l-5 4z"/><path d="M8 9h8M8 12h5"/>',
    delete: '<path d="M4.5 6.5h15"/><path d="M9 6.5V4.5h6v2"/><path d="M6.5 6.5 7.5 20a1 1 0 0 0 1 1h7a1 1 0 0 0 1-1l1-13.5"/><path d="M10.5 10.5v6.5M13.5 10.5v6.5"/>',
    warning: '<path d="M12 3.5 2.5 20.5h19z"/><path d="M12 9.5v5M12 17v.2"/>',
    neurology: '<circle cx="12" cy="12" r="3.2"/><path d="M12 8.8c0-3 1.4-4.8 4.3-4.8 2 0 3.2 1.2 3.2 2.8M8.8 12c-3 0-4.8 1.4-4.8 4.3 0 2 1.2 3.2 2.8 3.2"/><path d="M15.2 12c0 3 1.4 4.8 4.3 4.8 2 0 3.2-1.2 3.2-2.8"/>',
    smart_toy: '<rect x="4" y="7" width="16" height="12" rx="3"/><path d="M12 7V4M9.5 4h5"/><circle cx="9.5" cy="13" r="1.2"/><circle cx="14.5" cy="13" r="1.2"/><path d="M9.5 16.2h5"/>',
    smart_display: '<rect x="2.5" y="4.5" width="19" height="12.5" rx="2"/><path d="M8.5 20.5h7M12 17v3.5"/><path d="m9.5 10 4 2.5-4 2.5z"/>',
    enhanced_encryption: '<rect x="4.5" y="10" width="15" height="10" rx="2"/><path d="M8 10V7.5a4 4 0 0 1 7.5-2"/><path d="M12 14v2.5"/>',
    hd: '<rect x="2.5" y="5.5" width="19" height="13" rx="2"/><path d="M6.5 9.5v5M6.5 12h3M9.5 9.5v5"/><path d="M14 9.5v5h1.5a2.5 2.5 0 0 0 0-5z"/>',
    chevron_left: '<path d="M14.5 5.5 8 12l6.5 6.5"/>',
    chevron_right: '<path d="M9.5 5.5 16 12l-6.5 6.5"/>',
    moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
  };

  var SVG_NS = 'http://www.w3.org/2000/svg';

  /** Build an <svg> for `name`, or null when the name is unknown. */
  function build(name) {
    var body = P[name];
    if (!body) {
      return null;
    }
    var svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '1.8');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    // The span it replaces carried the size; the svg inherits it from the
    // element's class list, so explicit sizing is applied here as a fallback.
    svg.setAttribute('width', '1em');
    svg.setAttribute('height', '1em');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    svg.innerHTML = body;
    return svg;
  }

  /** Swap one span for its svg. Returns true when an icon was rendered. */
  function hydrateOne(span) {
    if (span.dataset.dedanIconDone === '1') {
      return true;
    }
    var name = span.getAttribute('data-dedan-icon') || (span.textContent || '').trim();
    var svg = build(name);
    if (!svg) {
      // Never leave the ligature name visible: an unknown icon must be absent,
      // not spelled out in the layout.
      span.textContent = '';
      span.dataset.dedanIconDone = '1';
      span.setAttribute('aria-hidden', 'true');
      return false;
    }
    span.replaceChild(svg, span.firstChild);
    // Preserve the original classes so size/colour utilities still apply.
    svg.setAttribute('class', span.getAttribute('class') || '');
    span.dataset.dedanIconDone = '1';
    return true;
  }

  function hydrate(root) {
    var scope = root || document;
    var spans = scope.querySelectorAll('span.material-symbols-outlined');
    var missing = [];
    Array.prototype.forEach.call(spans, function (span) {
      if (!hydrateOne(span)) {
        missing.push((span.textContent || '').trim());
      }
    });
    return { count: spans.length, missing: missing };
  }

  global.DEDAN_ICONS = {
    names: Object.keys(P),
    build: build,
    hydrate: hydrate,
    hydrateOne: hydrateOne,
  };

  // Hydrate now for anything already in the DOM, and again once the document
  // settles. JavaScript-built icons appear later, so a single pass at load is
  // not enough -- the previous CDN font worked because it was a stylesheet and
  // applied retroactively to every element, including ones added later.
  function run() {
    var result = hydrate();
    if (result.missing.length) {
      // Surfaced rather than swallowed: an unmapped icon is a visible gap in
      // the set, and should be noticed rather than silently blank.
      console.warn('[dedan-icons] no SVG for:', result.missing.join(', '));
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', run);
  } else {
    run();
  }

  // The realtime and consultation views build large trees asynchronously.
  var observer = null;
  if (global.MutationObserver) {
    var scheduled = false;
    observer = new MutationObserver(function () {
      if (scheduled) {
        return;
      }
      scheduled = true;
      // Coalesced: a single render pass can emit hundreds of nodes, and
      // hydrating per mutation would walk the whole document each time.
      global.requestAnimationFrame(function () {
        scheduled = false;
        hydrate();
      });
    });
  }

  global.DEDAN_ICONS.observe = function (target) {
    if (observer && target) {
      observer.observe(target, { childList: true, subtree: true });
    }
  };
}(window));