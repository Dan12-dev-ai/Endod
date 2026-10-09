/*
 * DEDAN Health — shared portal client.
 *
 * Every page loads this before its own script. It owns the four things that
 * would otherwise be copy-pasted into all eight pages and drift apart:
 *
 *   1. The session token  -- read, written and attached in exactly one place.
 *   2. API error shape   -- the backend answers errors as
 *                           {error, error_code, details}, not FastAPI's default
 *                           {detail}, so unwrapping lives here.
 *   3. Auth guards       -- one `requireSession()` instead of eight hand-rolled
 *                           redirect checks that each miss a page.
 *   4. DOM construction  -- everything is built with createElement/textContent.
 *                           No `innerHTML` anywhere, because every value
 *                           rendered here is patient-supplied or clinical text:
 *                           assigning it as markup would make a symptom string
 *                           an XSS vector against a health record.
 *
 * Plain ES2018, no build step, no dependencies: the portal is served as static
 * files and `scripts/check-portal.py` syntax-checks it as-is.
 */

(function (global) {
  'use strict';

  var TOKEN_KEY = 'dedan.session.token';
  var PROFILE_KEY = 'dedan.session.profile';

  /* ---------------------------------------------------------------- errors */

  /**
   * An API call that came back non-2xx.
   *
   * `detail` is the human-readable reason, already unwrapped from whichever of
   * the two error envelopes the server used. Pages show it directly, so it must
   * never contain a stack trace or an internal identifier.
   */
  function ApiError(message, status, code) {
    this.name = 'ApiError';
    this.message = message || 'Something went wrong. Please try again.';
    this.status = status || 0;
    this.code = code || null;
  }
  ApiError.prototype = Object.create(Error.prototype);
  ApiError.prototype.constructor = ApiError;

  /* --------------------------------------------------------------- storage */

  /*
   * localStorage throws in two situations that matter here: Safari private
   * browsing (quota) and a browser configured to block storage entirely. Either
   * one must degrade to "not signed in" rather than taking the page down, so
   * every access is guarded.
   */
  function readStore(key) {
    try {
      return global.localStorage.getItem(key);
    } catch (err) {
      return null;
    }
  }

  function writeStore(key, value) {
    try {
      global.localStorage.setItem(key, value);
      return true;
    } catch (err) {
      return false;
    }
  }

  function dropStore(key) {
    try {
      global.localStorage.removeItem(key);
    } catch (err) {
      /* nothing useful to do */
    }
  }

  function getToken() {
    return readStore(TOKEN_KEY);
  }

  function setSession(token, profile) {
    writeStore(TOKEN_KEY, token);
    if (profile) {
      writeStore(PROFILE_KEY, JSON.stringify(profile));
    }
  }

  function getProfile() {
    var raw = readStore(PROFILE_KEY);
    if (!raw) {
      return null;
    }
    try {
      return JSON.parse(raw);
    } catch (err) {
      // A corrupted cache entry must not wedge the page: drop it and let the
      // caller re-fetch from /auth/session.
      dropStore(PROFILE_KEY);
      return null;
    }
  }

  function clearSession() {
    dropStore(TOKEN_KEY);
    dropStore(PROFILE_KEY);
  }

  /* ------------------------------------------------------------------ http */

  /*
   * Pull a usable message out of whichever error envelope arrived.
   *
   * The platform's exception handlers answer
   *   {"error": "Authentication required.", "error_code": "HTTP_401"}
   * while FastAPI's own validation errors answer
   *   {"detail": [{"msg": "...", "loc": ["body", "email"]}]}.
   * Both are normalised here so no page has to know which it got.
   */
  function errorMessage(payload, fallback) {
    if (!payload) {
      return fallback;
    }
    if (typeof payload === 'string' && payload) {
      return payload;
    }
    if (typeof payload.error === 'string' && payload.error) {
      return payload.error;
    }
    if (typeof payload.detail === 'string' && payload.detail) {
      return payload.detail;
    }
    if (Array.isArray(payload.detail) && payload.detail.length) {
      var first = payload.detail[0];
      if (first && typeof first.msg === 'string') {
        return first.msg;
      }
    }
    if (Array.isArray(payload.errors) && payload.errors.length) {
      return String(payload.errors[0]);
    }
    return fallback;
  }

  function errorCode(payload) {
    if (payload && typeof payload.error_code === 'string') {
      return payload.error_code;
    }
    return null;
  }

  /**
   * Perform an API call.
   *
   * opts: {method, body, auth, redirectOn401, raw}
   *   auth           attach the session token (default true)
   *   redirectOn401  send the browser to the sign-in wall (default true)
   *   raw            return the Response instead of parsed JSON
   *
   * Redirecting centrally is the point: an expired token on any page must land
   * the patient back at sign-in rather than leaving a page of broken widgets.
   */
  function request(path, opts) {
    opts = opts || {};
    var method = (opts.method || 'GET').toUpperCase();
    var headers = { Accept: 'application/json' };
    var token = getToken();

    if (opts.auth !== false && token) {
      headers.Authorization = token;
    }

    var init = { method: method, headers: headers, credentials: 'same-origin' };

    if (opts.body !== undefined && opts.body !== null) {
      headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(opts.body);
    }

    return fetch(path, init).then(function (response) {
      if (opts.raw) {
        if (!response.ok) {
          return response.text().then(function (text) {
            throw new ApiError(errorMessage(safeParse(text), response.statusText), response.status);
          });
        }
        return response;
      }

      return response.text().then(function (text) {
        var payload = text ? safeParse(text) : null;

        if (!response.ok) {
          // 401 means the credential is gone or expired. Clearing it here stops
          // every later request from re-sending a token the server will reject.
          if (response.status === 401 && opts.redirectOn401 !== false) {
            clearSession();
            if (!isAuthPage()) {
              global.location.href = 'login.html?next=' + encodeURIComponent(currentPage());
              return Promise.reject(new ApiError('Your session has expired. Please sign in again.', 401));
            }
          }
          throw new ApiError(
            errorMessage(payload, 'Request failed (' + response.status + ').'),
            response.status,
            errorCode(payload)
          );
        }
        return payload;
      });
    }, function (networkError) {
      // fetch only rejects here on a transport failure (server down, DNS, CORS),
      // which is worth distinguishing from a 500 the server actually produced.
      throw new ApiError(
        'Cannot reach the DEDAN service. Check that the server is running.',
        0,
        'NETWORK'
      );
    });
  }

  function safeParse(text) {
    try {
      return JSON.parse(text);
    } catch (err) {
      return null;
    }
  }

  function get(path, opts) {
    return request(path, Object.assign({ method: 'GET' }, opts || {}));
  }
  function post(path, body, opts) {
    return request(path, Object.assign({ method: 'POST', body: body }, opts || {}));
  }
  function patch(path, body, opts) {
    return request(path, Object.assign({ method: 'PATCH', body: body }, opts || {}));
  }
  function del(path, opts) {
    return request(path, Object.assign({ method: 'DELETE' }, opts || {}));
  }

  /* ------------------------------------------------------------ navigation */

  function currentPage() {
    var path = global.location.pathname.split('/').pop();
    return path || 'index.html';
  }

  function isAuthPage() {
    var page = currentPage();
    return page === 'login.html' || page === 'register.html';
  }

  /**
   * Sign the patient out and return to the sign-in wall.
   *
   * The token is cleared rather than merely ignored: leaving it in storage means
   * the next visitor to this browser profile would be handed a live credential.
   */
  function logout() {
    clearSession();
    global.location.href = 'login.html';
  }

  /**
   * Gate a page behind a valid session.
   *
   * Returns the profile when signed in. When the cached profile is missing or
   * stale it revalidates against /auth/session, because the only thing that
   * proves the token still works is the server saying so — a token in
   * localStorage is not evidence of anything.
   */
  function requireSession() {
    if (!getToken()) {
      global.location.replace('login.html?next=' + encodeURIComponent(currentPage()));
      return Promise.resolve(null);
    }

    var cached = getProfile();
    return get('/auth/session', { redirectOn401: false })
      .then(function (payload) {
        var profile = (payload && payload.profile) || cached;
        if (profile) {
          writeStore(PROFILE_KEY, JSON.stringify(profile));
        }
        paintIdentity(profile);
        return profile;
      })
      .catch(function (err) {
        // A network blip must not sign the patient out of a working session;
        // only an explicit 401 from the server ends the session.
        if (err && err.status === 401) {
          clearSession();
          global.location.replace('login.html?next=' + encodeURIComponent(currentPage()));
          return null;
        }
        if (cached) {
          return cached;
        }
        showToast('Cannot reach the DEDAN service.', 'error');
        return null;
      });
  }

  /*
   * Fill in the signed-in patient's details wherever a page provides a hook.
   *
   * Pages opt in with data attributes rather than bespoke per-page code:
   *   <span data-dedan="display-name"></span>
   *   <span data-dedan="dedan-id"></span>
   *   <span data-dedan="email"></span>
   *   <span data-dedan="created"></span>
   *   <span data-dedan="country"></span>
   *   <button data-dedan="logout">…</button>
   * An absent hook is a no-op, so every page can call this unconditionally.
   */
  function paintIdentity(profile) {
    if (!profile) {
      return;
    }
    var name = profile.display_name || 'Patient';
    var initials = name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map(function (part) { return part.charAt(0).toUpperCase(); })
      .join('');

    var values = {
      'display-name': name,
      'initials': initials || 'D',
      'dedan-id': profile.dedan_user_id || '—',
      'email': profile.email || 'No email on file',
      'country': profile.country_code || '—',
      'locale': profile.locale || '—'
    };

    Object.keys(values).forEach(function (key) {
      document.querySelectorAll('[data-dedan="' + key + '"]').forEach(function (node) {
        node.textContent = values[key];
      });
    });

    // Membership date needs formatting, so it is handled separately.
    document.querySelectorAll('[data-dedan="created"]').forEach(function (node) {
      node.textContent = profile.created_at ? fmtDate(profile.created_at) : '—';
    });

    document.querySelectorAll('[data-dedan="logout"]').forEach(function (node) {
      node.addEventListener('click', function (event) {
        event.preventDefault();
        logout();
      });
    });
  }

  /* ----------------------------------------------------------------- toasts */

  var TOAST_CLASSES = {
    info: 'bg-surface-container text-on-surface',
    success: 'bg-primary-container text-on-primary-container',
    error: 'bg-error-container text-on-error-container',
    warn: 'bg-tertiary-container text-on-tertiary-container'
  };

  /**
   * Show a transient message.
   *
   * Built as DOM nodes and mounted in a live region so screen readers announce
   * it; `aria-live="polite"` rather than `assertive` because a confirmation is
   * not an emergency, and an error is reported in place on the form as well.
   */
  function showToast(message, kind) {
    var host = document.getElementById('dedan-toast-host');
    if (!host) {
      host = document.createElement('div');
      host.id = 'dedan-toast-host';
      host.setAttribute('role', 'status');
      host.setAttribute('aria-live', 'polite');
      host.className = 'fixed bottom-5 right-5 z-[100] flex flex-col gap-2 max-w-sm';
      document.body.appendChild(host);
    }

    var toast = document.createElement('div');
    toast.className =
      'px-4 py-3 rounded-lg shadow-lg text-sm font-medium ' +
      (TOAST_CLASSES[kind] || TOAST_CLASSES.info);
    toast.textContent = message;
    host.appendChild(toast);

    global.setTimeout(function () {
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast);
      }
    }, 5200);
  }

  /* ------------------------------------------------------- form utilities */

  /**
   * Read a form's fields into a plain object, trimming text inputs.
   *
   * Falls back to `id` when a field has no `name`. The portal's markup labels
   * and addresses inputs by `id` (`#first-name`) and omits `name` entirely, so
   * keying on `name` alone silently produced an empty object — which reads as
   * "the form is empty" rather than "the selector was wrong", and would have
   * blocked every submission on the page.
   */
  function formValues(form) {
    var values = {};
    Array.prototype.forEach.call(form.elements, function (field) {
      var key = field.name || field.id;
      if (!key) {
        return;
      }
      if (field.type === 'checkbox') {
        values[key] = field.checked;
      } else if (field.type === 'radio') {
        if (field.checked) {
          values[key] = field.value;
        }
      } else {
        values[key] = typeof field.value === 'string' ? field.value.trim() : field.value;
      }
    });
    return values;
  }

  /**
   * Put a form into a pending state and return a function that restores it.
   *
   * Both halves matter: the button must not stay disabled after a failure (a
   * dead submit button with no explanation is the most common cause of "the
   * site is broken"), and the label must say what is happening.
   */
  function busy(form, button, label) {
    var original = button ? button.textContent : null;
    if (button) {
      button.disabled = true;
      button.textContent = label || 'Working…';
    }
    Array.prototype.forEach.call(form.elements, function (field) {
      field.disabled = true;
    });
    return function restore() {
      if (button) {
        button.disabled = false;
        button.textContent = original;
      }
      Array.prototype.forEach.call(form.elements, function (field) {
        field.disabled = false;
      });
    };
  }

  /**
   * Show an inline message inside a form.
   *
   * Falls back to a toast when the page provides no slot, so a validation
   * failure is never silently swallowed.
   */
  function formError(form, message) {
    var box = form.querySelector('[data-form-error]');
    if (!box) {
      showToast(message, 'error');
      return;
    }
    box.textContent = message;
    box.classList.remove('hidden');
  }

  function clearFormError(form) {
    var box = form.querySelector('[data-form-error]');
    if (box) {
      box.textContent = '';
      box.classList.add('hidden');
    }
  }

  /* ---------------------------------------------------------- DOM builders */

  /**
   * Create an element. Children may be nodes or strings (inserted as text).
   *
   * Strings go through `textContent`, never markup — that is the whole point.
   */
  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    var key;

    if (attrs) {
      for (key in attrs) {
        if (!Object.prototype.hasOwnProperty.call(attrs, key)) {
          continue;
        }
        var value = attrs[key];
        if (value === null || value === undefined || value === false) {
          continue;
        }
        if (key === 'class') {
          node.className = value;
        } else if (key === 'text') {
          node.textContent = value;
        } else if (key.indexOf('on') === 0 && typeof value === 'function') {
          node.addEventListener(key.slice(2).toLowerCase(), value);
        } else {
          node.setAttribute(key, value === true ? '' : value);
        }
      }
    }

    appendAll(node, children);
    return node;
  }

  function appendAll(node, children) {
    if (children === null || children === undefined) {
      return;
    }
    if (!Array.isArray(children)) {
      children = [children];
    }
    children.forEach(function (child) {
      if (child === null || child === undefined || child === false) {
        return;
      }
      if (typeof child === 'string' || typeof child === 'number') {
        node.appendChild(document.createTextNode(String(child)));
      } else {
        node.appendChild(child);
      }
    });
  }

  /** Replace a container's contents with `children`. */
  function render(container, children) {
    if (!container) {
      return null;
    }
    while (container.firstChild) {
      container.removeChild(container.firstChild);
    }
    appendAll(container, children);
    return container;
  }

  /** Standard empty state, so an empty list never looks like a broken page. */
  function emptyState(title, detail, icon) {
    return el('div', { class: 'flex flex-col items-center justify-center text-center py-12 px-6 gap-2' }, [
      el('span', { class: 'material-symbols-outlined text-5xl text-outline-variant', text: icon || 'inbox' }),
      el('p', { class: 'font-label-lg text-on-surface', text: title }),
      detail ? el('p', { class: 'font-body-sm text-on-surface-variant max-w-sm', text: detail }) : null
    ]);
  }

  /* ---------------------------------------------------------- formatting */

  function toDate(value) {
    if (!value) {
      return null;
    }
    var date = value instanceof Date ? value : new Date(value);
    return isNaN(date.getTime()) ? null : date;
  }

  function fmtDate(value) {
    var date = toDate(value);
    if (!date) {
      return '—';
    }
    return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
  }

  function fmtTime(value) {
    var date = toDate(value);
    if (!date) {
      return '—';
    }
    return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  }

  function fmtDateTime(value) {
    var date = toDate(value);
    if (!date) {
      return '—';
    }
    return fmtDate(date) + ' · ' + fmtTime(date);
  }

  /** Human-friendly relative time, e.g. "in 3 days" / "2 hours ago". */
  function fmtRelative(value) {
    var date = toDate(value);
    if (!date) {
      return '—';
    }
    var seconds = Math.round((date.getTime() - Date.now()) / 1000);
    var units = [
      ['year', 31536000],
      ['month', 2592000],
      ['day', 86400],
      ['hour', 3600],
      ['minute', 60]
    ];
    var formatter = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
    for (var i = 0; i < units.length; i++) {
      var amount = seconds / units[i][1];
      if (Math.abs(amount) >= 1) {
        return formatter.format(Math.round(amount), units[i][0]);
      }
    }
    return 'just now';
  }

  /** Split a comma/newline-separated API list field into a trimmed array. */
  function splitList(value) {
    if (!value) {
      return [];
    }
    if (Array.isArray(value)) {
      return value.filter(Boolean);
    }
    return String(value)
      .split(/[,;\n]/)
      .map(function (part) { return part.trim(); })
      .filter(Boolean);
  }

  /** Title-case an API enum for display (SCREAMING_SNAKE -> Screaming snake). */
  function humanise(value) {
    if (!value) {
      return '';
    }
    var text = String(value).replace(/[_-]+/g, ' ').trim();
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  /* ------------------------------------------------------------- consent */

  /**
   * True when the patient has agreed to health-data processing.
   *
   * `/users/me/health-profile` answers 403 without it — by design, so that a
   * refusal is distinguishable from "no data recorded". Pages must therefore
   * ask for consent rather than retrying the read.
   */
  function hasTreatmentConsent(profile) {
    return Boolean(profile && profile.consent && profile.consent.treatment_processing);
  }

  /**
   * Copy the signed-in patient's DEDAN ID to the clipboard.
   *
   * Reads the value from the rendered page rather than a hard-coded literal, so
   * the button can never copy someone else's ID. The Clipboard API is only
   * available on a secure origin, so a failure is reported rather than silent.
   */
  function copyDedanId() {
    var node = document.querySelector('[data-dedan="dedan-id"]');
    var value = node ? node.textContent.trim() : '';
    if (!value || value === '—') {
      showToast('Your DEDAN ID is not available yet.', 'error');
      return;
    }
    if (!navigator.clipboard) {
      showToast('Copying is not available in this browser. Your ID is ' + value, 'warn');
      return;
    }
    navigator.clipboard.writeText(value).then(function () {
      showToast('DEDAN ID ' + value + ' copied.', 'success');
    }, function () {
      showToast('Could not copy. Your ID is ' + value, 'error');
    });
  }

  global.DEDAN = {
    ApiError: ApiError,
    get: get,
    post: post,
    patch: patch,
    del: del,
    request: request,
    getToken: getToken,
    setSession: setSession,
    getProfile: getProfile,
    clearSession: clearSession,
    requireSession: requireSession,
    logout: logout,
    copyDedanId: copyDedanId,
    currentPage: currentPage,
    isAuthPage: isAuthPage,
    paintIdentity: paintIdentity,
    showToast: showToast,
    formValues: formValues,
    busy: busy,
    formError: formError,
    clearFormError: clearFormError,
    el: el,
    render: render,
    emptyState: emptyState,
    fmtDate: fmtDate,
    fmtTime: fmtTime,
    fmtDateTime: fmtDateTime,
    fmtRelative: fmtRelative,
    splitList: splitList,
    humanise: humanise,
    hasTreatmentConsent: hasTreatmentConsent
  };
})(window);
