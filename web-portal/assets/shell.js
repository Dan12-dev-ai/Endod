/*
 * Shared application shell for the signed-in pages.
 *
 * One shell for every authenticated route
 * ---------------------------------------
 * The sidebar, header and page furniture used to be duplicated into each of the
 * six signed-in pages. The copies had drifted: different navigation items,
 * different icons for the same feature, different spacing, and no mobile
 * behaviour at all (a fixed 16rem sidebar and a matching 16rem content offset
 * applied at every viewport, leaving a phone-width screen with almost no room
 * for content).
 *
 * Everything below is rendered from `DEDAN_NAV`, so a page cannot define its
 * own navigation. A page supplies a mount point and its own content; the shell
 * supplies the chrome.
 *
 * Layout contract
 * ---------------
 *   --dedan-sidebar-w   expanded sidebar width
 *   --dedan-header-h    header height
 *
 * Both are set on :root in tailwind.config.js and used by both the sidebar and
 * the content offset, which is what keeps the content from sitting underneath
 * the fixed navigation.
 */
(function (global) {
  'use strict';

  var DEDAN = global.DEDAN;
  var NAV = global.DEDAN_NAV;

  // --- shared style constants ------------------------------------------------
  // Single definitions. These were previously restated inline on every page,
  // which is how two cards on different pages ended up subtly different.

  var CARD = 'rounded-xl bg-surface-container-lowest border border-outline-variant/40 p-space-lg';
  var BTN_PRIMARY = 'inline-flex items-center justify-center gap-1.5 rounded-lg bg-secondary text-on-secondary px-4 py-2 font-label-lg text-label-lg hover:opacity-90 transition-opacity disabled:opacity-60';
  var BTN_GHOST = 'inline-flex items-center justify-center gap-1.5 rounded-lg border border-outline-variant/50 px-4 py-2 font-label-lg text-label-lg text-on-surface hover:bg-surface-container transition-colors disabled:opacity-60';
  var INPUT = 'w-full bg-surface-container-lowest text-on-surface rounded-lg shadow-sm px-3 py-2 font-body-md text-body-md placeholder:text-outline focus:outline-none focus:ring-1 focus:ring-secondary';
  var LABEL = 'font-label-sm text-label-sm uppercase tracking-wider text-on-surface-variant font-semibold';

  var SIDEBAR_W = '16rem';
  var HEADER_H = '4rem';

  // --- small render helpers (existing API, unchanged) ------------------------

  function fill(containerId, nodes) {
    var host = document.getElementById(containerId);
    if (!host) {
      return null;
    }
    DEDAN.render(host, nodes);
    return host;
  }

  function pageHeader(title, subtitle, actions) {
    return DEDAN.el('div', { class: 'flex flex-col md:flex-row md:items-end md:justify-between gap-space-md' }, [
      DEDAN.el('div', { class: 'flex flex-col gap-1' }, [
        DEDAN.el('h1', { class: 'font-headline-lg text-headline-lg text-primary font-bold tracking-tight', text: title }),
        subtitle ? DEDAN.el('p', { class: 'font-body-md text-body-md text-on-surface-variant', text: subtitle }) : null
      ]),
      actions ? DEDAN.el('div', { class: 'flex flex-wrap gap-space-sm' }, actions) : null
    ]);
  }

  function card(children, extraClass) {
    return DEDAN.el('section', { class: (extraClass ? extraClass + ' ' : '') + CARD }, children);
  }

  function label(text) {
    return DEDAN.el('label', { class: LABEL, text: text });
  }

  function field(labelText, control, hint) {
    return DEDAN.el('div', { class: 'flex flex-col gap-1.5' }, [
      label(labelText),
      control,
      hint ? DEDAN.el('p', { class: 'font-body-sm text-body-sm text-on-surface-variant', text: hint }) : null
    ]);
  }

  function button(text, className, onClick) {
    return DEDAN.el('button', { type: 'button', class: className || BTN_PRIMARY, onclick: onClick }, [
      text
    ]);
  }

  function errorSlot() {
    return DEDAN.el('p', {
      class: 'hidden rounded-lg bg-error-container text-on-error-container px-3 py-2 font-body-sm text-body-sm',
      'data-form-error': '', role: 'alert'
    });
  }

  function showError(container, message) {
    var box = container.querySelector('[data-form-error]');
    if (!box) {
      DEDAN.showToast(message, 'error');
      return;
    }
    box.textContent = message;
    box.classList.remove('hidden');
  }

  function clearError(container) {
    var box = container.querySelector('[data-form-error]');
    if (box) {
      box.textContent = '';
      box.classList.add('hidden');
    }
  }

  // --- collapsible rail ------------------------------------------------------
  //
  // ChatGPT-style: the sidebar is an icon rail by default and expands to a
  // labelled rail when you click the wordmark. The state is persisted, because
  // a rail that forgets its state on every page load is worse than no rail at
  // all -- it re-collapses mid-session and the content shifts under the cursor.
  //
  // Below `lg` the sidebar is an off-canvas drawer and the same wordmark opens
  // it instead of toggling the rail; collapse is meaningless there.

  var COLLAPSE_KEY = 'dedan.nav.collapsed';
  var RAIL_EXPANDED = 'w-sidebar';
  var RAIL_COLLAPSED = 'w-sidebar-collapsed';
  var OFFSET_EXPANDED = 'lg:pl-sidebar';
  var OFFSET_COLLAPSED = 'lg:pl-sidebar-collapsed';

  function storageGet(key) {
    try { return global.localStorage.getItem(key); } catch (e) { return null; }
  }

  function storageSet(key, value) {
    try { global.localStorage.setItem(key, value); } catch (e) { /* private mode */ }
  }

  function isCollapsed() {
    return storageGet(COLLAPSE_KEY) === '1';
  }

  /**
   * Apply the collapsed state to the rail and the content offset together.
   *
   * Both have to move in step: the offset is what keeps content clear of a
   * fixed rail, so changing one without the other slides the page underneath
   * the sidebar.
   */
  function applyCollapsed(collapsed) {
    var aside = document.getElementById('dedan-sidebar');
    var content = document.getElementById('dedan-content');
    var mount = document.getElementById('dedan-sidebar-mount');

    if (aside) {
      aside.classList.toggle(RAIL_COLLAPSED, collapsed);
      aside.classList.toggle(RAIL_EXPANDED, !collapsed);
      aside.setAttribute('data-collapsed', collapsed ? 'true' : 'false');
    }
    if (content) {
      content.classList.toggle(OFFSET_COLLAPSED, collapsed);
      content.classList.toggle(OFFSET_EXPANDED, !collapsed);
    }
    if (mount) {
      // Labels and group headings are what the rail gives up when collapsed.
      // Icons stay, so every destination remains reachable and identifiable.
      mount.querySelectorAll('.dedan-nav-label, .dedan-nav-group-label').forEach(
        function (node) { node.classList.toggle('hidden', collapsed); }
      );
      mount.querySelectorAll('.dedan-nav-item').forEach(function (node) {
        node.classList.toggle('justify-center', collapsed);
        node.classList.toggle('px-space-sm', collapsed);
        node.classList.toggle('px-space-md', !collapsed);
      });
      mount.querySelectorAll('.dedan-nav-brand-text').forEach(function (node) {
        node.classList.toggle('hidden', collapsed);
      });
      mount.querySelectorAll('.dedan-nav-footer-text').forEach(function (node) {
        node.classList.toggle('hidden', collapsed);
      });
    }
    document.querySelectorAll('[data-dedan="nav-collapse"]').forEach(function (button) {
      button.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
      button.setAttribute('aria-label', collapsed ? 'Expand navigation' : 'Collapse navigation');
    });
    storageSet(COLLAPSE_KEY, collapsed ? '1' : '0');
  }

  function toggleCollapsed() {
    applyCollapsed(!isCollapsed());
  }

  /** Mobile drawer vs. desktop rail: the wordmark does the right one for each. */
  function handleBrandClick(event) {
    if (global.matchMedia && !global.matchMedia('(min-width: 1024px)').matches) {
      event.preventDefault();
      setNavOpen(true);
      return;
    }
    event.preventDefault();
    toggleCollapsed();
  }

  function wireCollapse() {
    document.querySelectorAll('[data-dedan="nav-brand"]').forEach(function (brand) {
      brand.addEventListener('click', handleBrandClick);
    });
    document.querySelectorAll('[data-dedan="nav-collapse"]').forEach(function (button) {
      button.addEventListener('click', function (event) {
        event.preventDefault();
        toggleCollapsed();
      });
    });
    applyCollapsed(isCollapsed());
  }

  // --- sidebar ---------------------------------------------------------------

  var NAV_ITEM_BASE = [
    'dedan-nav-item flex items-center gap-space-sm px-space-md py-space-sm rounded-lg',
    'font-body-sm text-body-md font-medium',
    'text-on-surface-variant hover:bg-surface-container hover:text-on-surface',
    'transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-secondary',
    'truncate min-w-0'
  ].join(' ');

  var NAV_ITEM_ACTIVE = 'bg-primary-container text-on-primary font-semibold hover:bg-primary-container hover:text-on-primary shadow-sm';

  function navItem(item, current) {
    var active = item.href === current;
    var link = DEDAN.el('a', {
      href: item.href,
      class: NAV_ITEM_BASE + (active ? ' ' + NAV_ITEM_ACTIVE : ''),
      // `aria-current="page"` is what a screen reader announces; the class only
      // changes the paint. Both are set together so they cannot disagree.
      'aria-current': active ? 'page' : null,
      // When the rail is collapsed the label is hidden, so the title is the
      // only accessible name left.
      title: item.label
    }, [
      DEDAN.el('span', {
        class: 'material-symbols-outlined text-[20px] shrink-0',
        'data-dedan-icon': item.icon,
        'aria-hidden': 'true',
        text: item.icon
      }),
      DEDAN.el('span', { class: 'dedan-nav-label truncate', text: item.label })
    ]);
    return DEDAN.el('li', null, [link]);
  }

  function navGroup(group, current) {
    var children = [];
    if (group.label) {
      children.push(DEDAN.el('p', {
        class: 'dedan-nav-group-label px-space-md pt-space-md pb-space-xs font-label-sm text-label-sm uppercase tracking-wider text-outline font-semibold',
        text: group.label
      }));
    }
    var list = DEDAN.el('ul', { class: 'space-y-space-xs' },
      group.items.map(function (item) { return navItem(item, current); }));
    children.push(list);
    return DEDAN.el('div', { class: 'space-y-space-xs' }, children);
  }

  function sidebarBody(current) {
    return [
      DEDAN.el('div', { class: 'px-space-lg py-space-sm mb-space-sm flex items-center gap-space-sm' }, [
        // The wordmark is the expand/collapse control, matching the pattern the
        // product is modelled on. It stays a real link for middle-click and
        // "open in new tab"; the handler only intercepts a plain left click.
        DEDAN.el('a', {
          href: 'index.html',
          'data-dedan': 'nav-brand',
          class: 'flex items-center gap-space-sm rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-secondary'
        }, [
          DEDAN.el('span', {
            class: 'material-symbols-outlined text-[22px] text-secondary shrink-0',
            'data-dedan-icon': 'neurology',
            'aria-hidden': 'true',
            text: 'neurology'
          }),
          DEDAN.el('span', { class: 'dedan-nav-brand-text flex flex-col leading-none' }, [
            DEDAN.el('span', {
              class: 'font-headline-sm text-headline-sm text-on-surface font-bold tracking-tight',
              text: 'DEDAN'
            }),
            DEDAN.el('span', {
              class: 'font-label-sm text-label-sm text-secondary uppercase font-semibold tracking-wider mt-0.5',
              text: 'Health Network'
            })
          ])
        ])
      ]),
      DEDAN.el('div', { class: 'overflow-y-auto px-space-sm flex-1' },
        [DEDAN.el('nav', { 'aria-label': 'Main' },
          NAV.GROUPS.map(function (group) { return navGroup(group, current); }))])
    ];
  }

  function sidebarFooter() {
    return DEDAN.el('div', { class: 'px-space-md pt-space-sm' }, [
      DEDAN.el('div', { class: 'bg-surface-container-lowest p-space-sm rounded-lg shadow-sm flex items-center gap-space-sm' }, [
        DEDAN.el('div', {
          class: 'w-8 h-8 rounded-full bg-secondary-container text-on-secondary-container flex items-center justify-center shrink-0'
        }, [
          DEDAN.el('span', {
            class: 'material-symbols-outlined text-[18px]',
            'data-dedan-icon': 'verified_user',
            'aria-hidden': 'true',
            text: 'verified_user'
          })
        ]),
        DEDAN.el('div', { class: 'dedan-nav-footer-text flex flex-col min-w-0' }, [
          DEDAN.el('span', {
            class: 'font-label-sm text-label-sm font-semibold text-on-surface truncate',
            text: 'Better Health Through AI'
          }),
          DEDAN.el('span', {
            class: 'font-body-sm text-body-sm text-secondary truncate flex items-center gap-space-xs'
          }, [
            DEDAN.el('span', { class: 'w-1.5 h-1.5 rounded-full bg-secondary inline-block' }),
            'Clinical Intelligence'
          ])
        ])
      ])
    ]);
  }

  /**
   * Paint the sidebar into its mount point.
   *
   * Renders into `#dedan-sidebar-mount` rather than the drawer itself: the
   * `<aside>` carries the positioning and the mobile transform, and must keep
   * those classes intact across renders or the drawer stops opening.
   *
   * Idempotent, and safe to call before or after the session is resolved -- it
   * renders navigation, which does not depend on who is signed in.
   */
  function renderSidebar() {
    var host = document.getElementById('dedan-sidebar-mount');
    if (!host || !NAV) {
      return null;
    }
    // `DEDAN.render` takes a flat array: it appends each entry directly, so a
    // nested array reaches `appendChild` as an array and throws
    // "parameter 1 is not of type 'Node'" -- which silently leaves the sidebar
    // empty on every page. `.concat` flattens the body into the top level.
    DEDAN.render(host, sidebarBody(NAV.activeHref(location.pathname)).concat([sidebarFooter()]));
    if (global.DEDAN_ICONS) {
      global.DEDAN_ICONS.hydrate(host);
    }
    return host;
  }

  // --- mobile navigation -----------------------------------------------------

  function sidebar() {
    return document.getElementById('dedan-sidebar');
  }

  function overlay() {
    return document.getElementById('dedan-nav-overlay');
  }

  function setNavOpen(open) {
    var el = sidebar();
    if (!el) {
      return;
    }
    el.classList.toggle('-translate-x-full', !open);
    el.classList.toggle('translate-x-0', open);
    el.setAttribute('aria-hidden', open ? 'false' : 'true');
    var scrim = overlay();
    if (scrim) {
      scrim.classList.toggle('hidden', !open);
    }
    var toggle = document.querySelector('[data-dedan="nav-toggle"]');
    if (toggle) {
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    }
    // Move focus into the drawer so keyboard users are not left behind it.
    if (open) {
      var first = el.querySelector('a');
      if (first) {
        first.focus();
      }
    }
  }

  function wireNavToggle() {
    document.querySelectorAll('[data-dedan="nav-toggle"]').forEach(function (toggle) {
      toggle.addEventListener('click', function () {
        var el = sidebar();
        if (!el) {
          return;
        }
        setNavOpen(el.classList.contains('-translate-x-full'));
      });
    });
    var scrim = overlay();
    if (scrim) {
      scrim.addEventListener('click', function () { setNavOpen(false); });
    }
    // Escape closes the drawer; without this a keyboard user can be trapped
    // behind an overlay they cannot reach.
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        setNavOpen(false);
      }
    });
  }

  /**
   * Mark the active navigation item.
   *
   * Kept for pages that still inline a <nav>; once every page renders from
   * `renderSidebar` this is a no-op, and it is left in place so an older page
   * cannot ship with no active state at all.
   */
  function wireChrome() {
    if (!NAV) {
      return;
    }
    var current = NAV.activeHref(location.pathname);
    document.querySelectorAll('nav a[href]').forEach(function (link) {
      var href = link.getAttribute('href');
      if (href === current) {
        link.setAttribute('aria-current', 'page');
        link.classList.add('bg-primary-container', 'text-on-primary', 'font-semibold');
        link.classList.remove('text-on-surface-variant');
      }
    });
  }

  /**
   * Standard boot for a signed-in page.
   *
   * Renders the shell first so navigation is present immediately, then requires
   * a session, then runs `main`. Redirects to the sign-in wall when there is no
   * valid token, so no page has to remember.
   */
  function boot(main) {
    renderSidebar();
    wireCollapse();
    wireNavToggle();
    wireChrome();
    DEDAN.requireSession().then(function (profile) {
      if (!profile) {
        return;
      }
      return main(profile);
    }).catch(function (err) {
      DEDAN.showToast(err.message || 'Could not load this page.', 'error');
    });
  }

  global.DEDAN_SHELL = {
    fill: fill,
    pageHeader: pageHeader,
    card: card,
    field: field,
    label: label,
    button: button,
    errorSlot: errorSlot,
    showError: showError,
    clearError: clearError,
    renderSidebar: renderSidebar,
    setNavOpen: setNavOpen,
    toggleCollapsed: toggleCollapsed,
    isCollapsed: isCollapsed,
    wireChrome: wireChrome,
    boot: boot,
    SIDEBAR_W: SIDEBAR_W,
    RAIL_EXPANDED: RAIL_EXPANDED,
    RAIL_COLLAPSED: RAIL_COLLAPSED,
    HEADER_H: HEADER_H,
    CARD: CARD,
    BTN_PRIMARY: BTN_PRIMARY,
    BTN_GHOST: BTN_GHOST,
    INPUT: INPUT,
    LABEL: LABEL
  };
}(window));