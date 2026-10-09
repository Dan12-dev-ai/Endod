/*
 * Canonical navigation for the signed-in portal.
 *
 * Why this file exists
 * --------------------
 * Each of the six signed-in pages used to carry its own hand-written <nav>
 * block, copied from a Stitch export. The copies had drifted apart: the same
 * feature appeared under different labels on different pages, the same item
 * used a different Material Symbol depending on the page (Hospitals was
 * `hospital_location` on two pages and `local_hospital` on four), whole items
 * were missing from some pages and present on others, and five entries were
 * `href="#"` placeholders that only worked because `shell.js` rewrote them at
 * runtime against a redirect table.
 *
 * That produced the reported symptom directly: navigating between two pages
 * changed which navigation items existed.
 *
 * This module is the single source of truth. `shell.js` renders the sidebar
 * from it, so a page cannot disagree with another page about what navigation
 * exists, what it is called, where it goes, or which icon it uses.
 *
 * Rules for editing
 * -----------------
 * 1. Every `href` must be a real file in this directory and a real route in the
 *    backend's PORTAL_PAGES allowlist. No `#` placeholders.
 * 2. Every item needs exactly one icon from Material Symbols Outlined, and the
 *    same feature must always use the same icon.
 * 3. Add a nav item here and a route there. Never inline a <nav> in a page.
 */
(function (global) {
  'use strict';

  /**
   * Every route the signed-in portal can navigate to.
   *
   * `auth: false` marks pages that legitimately have no sidebar (the sign-in
   * wall and the public landing page). They are listed rather than omitted so
   * this file remains a complete map of the portal's pages.
   */
  var ROUTES = {
    // The sidebar's "Home", but it is also the public marketing landing
    // page. Being a navigation target is not the same as being a valid place
    // to send a freshly authenticated patient: doing so is precisely the
    // "signed in but returned to the landing page" bug.
    'index.html': { title: 'Home', auth: true, publicLanding: true },
    'live-discussion.html': { title: 'Live Consultation', auth: true },
    'appointments.html': { title: 'Appointments', auth: true },
    'health-history.html': { title: 'Health Records', auth: true },
    'find-hospitals.html': { title: 'Find Care', auth: true },
    'settings.html': { title: 'Settings', auth: true },
    'login.html': { title: 'Sign in', auth: false },
    'register.html': { title: 'Create account', auth: false }
  };

  /**
   * The sidebar, in order.
   *
   * Groups are visual only -- they render as a small uppercase heading with a
   * divider, so navigation stays scannable on a long list.
   *
   * History of the entries that were removed, and why. They are recorded here
   * so the decision is not silently reversed by the next person who notices the
   * gap:
   *
   *   "Health Assessment" -> merged into Live Consultation. It was a second
   *     link to live-discussion.html on some pages and `href="#"` on others.
   *   "Hospitals"        -> merged into Find Care. `hospitals.html` was an
   *     orphaned Stitch mockup presenting a fictional clinician ("Dr. Sarah
   *     Aris, MD") and facility as real, and it was absent from the backend's
   *     PORTAL_PAGES allowlist. `find-hospitals.html` is the real page, backed
   *     by POST /users/me/care/facilities.
   *   "Health Timeline" -> merged into Health Records (same destination).
   *   "Medications"      -> removed. `href="#"`, redirected to settings.html,
   *     which has no medications section. Pointing at an unrelated page is
   *     worse than omitting the entry.
   *   "Follow-ups"       -> removed. No route. Post-appointment follow-up is
   *     not implemented; it must not be advertised as though it were.
   *   "Messages"         -> removed. No route.
   */
  var GROUPS = [
    {
      label: null,
      items: [
        { label: 'Home', href: 'index.html', icon: 'home' }
      ]
    },
    {
      label: 'Consult',
      items: [
        { label: 'Live Consultation', href: 'live-discussion.html', icon: 'video_chat' },
        { label: 'Appointments', href: 'appointments.html', icon: 'event_available' }
      ]
    },
    {
      label: 'My Health',
      items: [
        { label: 'Health Records', href: 'health-history.html', icon: 'clinical_notes' },
        { label: 'Find Care', href: 'find-hospitals.html', icon: 'local_hospital' }
      ]
    },
    {
      label: 'Account',
      items: [
        { label: 'Settings', href: 'settings.html', icon: 'settings' }
      ]
    }
  ];

  /**
   * Where a successful sign-in lands when there is no intended destination.
   *
   * This must be an authenticated page. It was `index.html`, which is the
   * public marketing landing page -- so signing in appeared to do nothing,
   * because the patient was returned to a page full of "Sign up" buttons.
   */
  var DEFAULT_AUTHENTICATED_ROUTE = 'live-discussion.html';

  /** Flattened view, used for validation and by tests. */
  function items() {
    var flat = [];
    GROUPS.forEach(function (group) {
      group.items.forEach(function (item) { flat.push(item); });
    });
    return flat;
  }

  /** True when `href` is a route the portal actually serves. */
  function isKnownRoute(href) {
    return Object.prototype.hasOwnProperty.call(ROUTES, href);
  }

  /**
   * Resolve `next` to a safe internal destination, or '' when it is not one.
   *
   * `next` arrives from the query string and is therefore attacker-controlled.
   * It is checked against the known route map rather than pattern-matched:
   *
   *   - rejects anything containing '/', which covers absolute URLs,
   *     protocol-relative "//evil.example", path traversal and trailing slashes;
   *   - rejects backslashes, which some browsers normalise into '/';
   *   - requires the route to be in the map, so a renamed or archived page can
   *     never be a redirect target -- `hospitals.html` used to sit in a
   *     hand-maintained list here after the page was archived to a 404;
   *   - rejects public routes, so a sign-in cannot bounce back into the
   *     sign-in wall and loop.
   *
   * Returns '' rather than a fallback so the caller chooses the default
   * explicitly, and the reason for ignoring the request is not lost.
   */
  function safeDestination(requested) {
    if (typeof requested !== 'string') {
      return '';
    }
    var value = requested.trim();
    if (!value || value !== requested) {
      return '';
    }
    if (value.indexOf('/') !== -1 || value.indexOf('\\') !== -1) {
      return '';
    }
    if (!/\.html$/i.test(value)) {
      return '';
    }
    if (!isKnownRoute(value)) {
      return '';
    }
    var route = ROUTES[value];
    if (!route || !route.auth) {
      return '';
    }
    if (route.publicLanding) {
      return '';
    }
    return value;
  }

  /**
   * The destination to use after a successful sign-in or registration.
   * The intended page when there is a valid one, otherwise the app default.
   */
  function destinationAfterAuth(requested) {
    return safeDestination(requested) || DEFAULT_AUTHENTICATED_ROUTE;
  }

  /**
   * Resolve the active item for a page.
   *
   * Compares on the normalised file name so a query string or a trailing
   * `./` does not silently clear the active state.
   */
  function activeHref(pathname) {
    var file = (pathname || '').split('?')[0].split('#')[0];
    file = file.replace(/^.*\//, '');
    return file || 'index.html';
  }

  /** Structural self-check. Surfaced in the console and asserted in tests. */
  function validate() {
    var problems = [];
    var seen = {};
    items().forEach(function (item) {
      if (!isKnownRoute(item.href)) {
        problems.push('nav item "' + item.label + '" points at unknown route ' + item.href);
      }
      if (seen[item.href]) {
        problems.push('duplicate nav entry for ' + item.href);
      }
      seen[item.href] = true;
      if (!item.icon) {
        problems.push('nav item "' + item.label + '" has no icon');
      }
      if (!item.label) {
        problems.push('nav entry for ' + item.href + ' has no label');
      }
    });
    return problems;
  }

  global.DEDAN_NAV = {
    ROUTES: ROUTES,
    GROUPS: GROUPS,
    DEFAULT_AUTHENTICATED_ROUTE: DEFAULT_AUTHENTICATED_ROUTE,
    items: items,
    isKnownRoute: isKnownRoute,
    safeDestination: safeDestination,
    destinationAfterAuth: destinationAfterAuth,
    activeHref: activeHref,
    validate: validate
  };
}(window));