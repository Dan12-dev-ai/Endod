/*
 * Settings page.
 *
 * Each section keeps its heading and renders live controls bound to the API.
 * The static markup that shipped with the page was placeholder content -- a
 * fictional patient, fictional devices, fictional consent -- so leaving it in
 * place and layering live data over it would have produced a page that *looked*
 * populated while showing another person's record. It is replaced wholesale.
 *
 * Consent is treated as load-bearing rather than decorative: withdrawing
 * treatment consent must immediately stop health data being read, so the toggle
 * re-reads the profile afterwards and the health section re-renders to match.
 */
(function () {
  'use strict';

  var DEDAN = window.DEDAN;
  var SHELL = window.DEDAN_SHELL;
  var state = { profile: null, preferences: null, consent: null, health: null };

  /* ------------------------------------------------------------ form atoms */

  var INPUT = 'w-full bg-surface-container-lowest text-on-surface rounded-lg shadow-sm px-3 py-2 font-body-md text-body-md placeholder:text-outline focus:outline-none focus:ring-1 focus:ring-secondary';
  var LABEL = 'font-label-sm text-label-sm uppercase tracking-wider text-on-surface-variant font-semibold';
  var BTN_PRIMARY = 'inline-flex items-center justify-center gap-1.5 rounded-lg bg-secondary text-on-secondary px-4 py-2 font-label-lg text-label-lg hover:opacity-90 transition-opacity disabled:opacity-60';
  var BTN_GHOST = 'inline-flex items-center justify-center gap-1.5 rounded-lg border border-outline-variant/50 px-4 py-2 font-label-lg text-label-lg text-on-surface hover:bg-surface-container transition-colors disabled:opacity-60';

  function field(labelText, control, hint) {
    return DEDAN.el('div', { class: 'flex flex-col gap-1.5' }, [
      DEDAN.el('label', { class: LABEL, text: labelText }),
      control,
      hint ? DEDAN.el('p', { class: 'font-body-sm text-body-sm text-on-surface-variant', text: hint }) : null
    ]);
  }

  function textInput(id, value, placeholder) {
    return DEDAN.el('input', {
      id: id, class: INPUT, type: 'text', value: value || '', placeholder: placeholder || ''
    });
  }

  function selectInput(id, value, options) {
    var node = DEDAN.el('select', { id: id, class: INPUT });
    options.forEach(function (option) {
      var opt = DEDAN.el('option', { value: option.value, text: option.label });
      if (option.value === value) {
        opt.selected = true;
      }
      node.appendChild(opt);
    });
    return node;
  }

  function toggle(id, labelText, description, checked) {
    var box = DEDAN.el('input', { id: id, type: 'checkbox', class: 'w-4 h-4 rounded text-secondary focus:ring-0 cursor-pointer' });
    box.checked = Boolean(checked);
    return DEDAN.el('div', { class: 'flex items-start gap-3 py-1.5' }, [
      box,
      DEDAN.el('label', { for: id, class: 'flex flex-col cursor-pointer' }, [
        DEDAN.el('span', { class: 'font-label-lg text-label-lg text-on-surface', text: labelText }),
        description ? DEDAN.el('span', { class: 'font-body-sm text-body-sm text-on-surface-variant', text: description }) : null
      ])
    ]);
  }

  function saveButton(labelText) {
    return DEDAN.el('button', { type: 'submit', class: BTN_PRIMARY, text: labelText || 'Save changes' });
  }

  function errorSlot() {
    return DEDAN.el('p', {
      class: 'hidden rounded-lg bg-error-container text-on-error-container px-3 py-2 font-body-sm text-body-sm',
      'data-form-error': '', role: 'alert'
    });
  }

  /*
   * Replace a section's body, keeping its heading.
   *
   * Two details this has to get right, both learned the hard way:
   *
   *  - The new container must be *appended to the section*. Building it detached
   *    and rendering into it produces a page that looks fine in the console and
   *    empty in the browser, because nothing was ever inserted.
   *  - Not every section's <h2> is a direct child; some are wrapped. Trimming
   *    "everything after the heading" then deletes the heading too, leaving an
   *    untitled, empty section. So the heading is preserved only when it really
   *    is a direct child, and rebuilt from its own text otherwise.
   */
  function bodyOf(sectionId) {
    var section = document.getElementById(sectionId);
    if (!section) {
      return null;
    }
    var heading = section.querySelector('h2');
    var keepHeading = Boolean(heading) && heading.parentNode === section;

    while (section.lastChild && !(keepHeading && section.lastChild === heading)) {
      section.removeChild(section.lastChild);
    }
    if (!keepHeading) {
      section.appendChild(DEDAN.el('h2', {
        class: 'font-headline-md text-headline-md text-primary font-semibold',
        text: heading ? heading.textContent.trim() : sectionId
      }));
    }

    var body = DEDAN.el('div', { class: 'flex flex-col gap-space-md pt-1' });
    section.appendChild(body);
    return body;
  }

  /** Wire a section: build `nodes`, attach a submit handler, mount. */
  function mount(sectionId, nodes, onSubmit) {
    var body = bodyOf(sectionId);
    if (!body) {
      return;
    }
    var form = DEDAN.el('form', { class: 'flex flex-col gap-space-md', novalidate: true });
    var error = errorSlot();
    DEDAN.render(body, [error, form]);

    form.addEventListener('submit', function (event) {
      event.preventDefault();
      error.classList.add('hidden');
      var button = form.querySelector('button[type="submit"]');
      var restore = DEDAN.busy(form, button, 'Saving…');
      Promise.resolve(onSubmit(form))
        .then(function () {
          DEDAN.showToast('Saved.', 'success');
        })
        .catch(function (err) {
          restore();
          error.textContent = err.message;
          error.classList.remove('hidden');
        });
    });

    DEDAN.render(form, nodes);
  }

  /* -------------------------------------------------------------- sections */

  function renderPersonal() {
    var profile = state.profile;
    mount('personal-info', [
      DEDAN.el('div', { class: 'grid grid-cols-1 md:grid-cols-2 gap-space-md' }, [
        field('Full name', textInput('set-display-name', profile.display_name)),
        field('DEDAN ID', DEDAN.el('input', {
          id: 'set-dedan-id', class: INPUT + ' opacity-60', type: 'text',
          value: profile.dedan_user_id, disabled: true
        }), 'Assigned by DEDAN when you registered. It cannot be changed.')
      ]),
      DEDAN.el('div', { class: 'grid grid-cols-1 md:grid-cols-2 gap-space-md' }, [
        field('Primary email', textInput('set-email', profile.email)),
        field('Mobile phone', textInput('set-phone', profile.phone), 'Used for SMS telehealth reminders.')
      ]),
      DEDAN.el('div', { class: 'grid grid-cols-1 md:grid-cols-2 gap-space-md' }, [
        field('Language', selectInput('set-locale', profile.locale || 'en', [
          { value: 'en', label: 'English' },
          { value: 'sw', label: 'Kiswahili' },
          { value: 'fr', label: 'Français' }
        ])),
        field('Timezone', textInput('set-timezone', profile.timezone || 'UTC'))
      ]),
      DEDAN.el('div', { class: 'flex gap-space-sm' }, [saveButton('Update information')])
    ], function () {
      return DEDAN.patch('/users/me', {
        display_name: document.getElementById('set-display-name').value.trim(),
        email: document.getElementById('set-email').value.trim(),
        phone: document.getElementById('set-phone').value.trim(),
        locale: document.getElementById('set-locale').value,
        timezone: document.getElementById('set-timezone').value.trim() || 'UTC'
      }).then(function (profile) {
        state.profile = profile;
        DEDAN.setSession(DEDAN.getToken(), profile);
        DEDAN.paintIdentity(profile);
      });
    });
  }

  function renderAccount() {
    var profile = state.profile;
    mount('account', [
      DEDAN.el('div', { class: 'grid grid-cols-2 md:grid-cols-4 gap-space-md' }, [
        statTile('DEDAN ID', profile.dedan_user_id),
        statTile('Member since', DEDAN.fmtDate(profile.created_at)),
        statTile('Locale', DEDAN.humanise(profile.locale || 'en')),
        statTile('Region', profile.country_code || 'KE')
      ]),
      DEDAN.el('div', { class: 'flex flex-col gap-space-sm pt-2' }, [
        DEDAN.el('p', { class: 'font-body-sm text-body-sm text-on-surface-variant', text:
          'Your health record is retained for audit even if you stop using DEDAN. Contact support to request an export or erasure.' })
      ]),
      DEDAN.el('div', { class: 'flex flex-wrap gap-space-sm' }, [
        DEDAN.el('button', {
          type: 'button', class: BTN_GHOST,
          onclick: function () { DEDAN.logout(); }
        }, [DEDAN.el('span', { class: 'material-symbols-outlined', style: 'font-size:18px', text: 'logout' }), 'Sign out of this device']),
        DEDAN.el('a', { class: BTN_GHOST, href: 'health-history.html' }, ['View health history'])
      ])
    ], function () { return Promise.resolve(); });
  }

  function statTile(labelText, value) {
    return DEDAN.el('div', { class: 'rounded-lg bg-surface-container-low px-3 py-2.5 flex flex-col gap-0.5' }, [
      DEDAN.el('span', { class: LABEL, text: labelText }),
      DEDAN.el('span', { class: 'font-label-lg text-label-lg text-on-surface', text: value || '—' })
    ]);
  }

  function renderCommunication() {
    var prefs = state.preferences;
    mount('communication', [
      toggle('pref-email', 'Email notifications', 'Appointment reminders and care updates.', prefs.email_notifications),
      toggle('pref-sms', 'SMS notifications', 'Text alerts for urgent triage outcomes.', prefs.sms_notifications),
      toggle('pref-push', 'Push notifications', 'In-app alerts on this device.', prefs.push_notifications),
      field('Reminder lead times', textInput('pref-offsets', prefs.reminder_offsets),
        'Comma-separated seconds before an appointment, e.g. 604800,86400,3600 for 7 days, 1 day and 1 hour.'),
      DEDAN.el('div', { class: 'flex gap-space-sm' }, [saveButton('Save preferences')])
    ], function () {
      return DEDAN.patch('/users/me/preferences', {
        email_notifications: document.getElementById('pref-email').checked,
        sms_notifications: document.getElementById('pref-sms').checked,
        push_notifications: document.getElementById('pref-push').checked,
        reminder_offsets: document.getElementById('pref-offsets').value.trim()
      }).then(function (prefs) {
        state.preferences = prefs;
      });
    });
  }

  function renderDedanAi() {
    var prefs = state.preferences;
    mount('dedan-ai', [
      DEDAN.el('div', { class: 'grid grid-cols-1 md:grid-cols-2 gap-space-md' }, [
        field('Conversation language', selectInput('ai-language', prefs.language || 'en', [
          { value: 'en', label: 'English' },
          { value: 'sw', label: 'Kiswahili' },
          { value: 'fr', label: 'Français' }
        ])),
        field('Theme', selectInput('ai-theme', prefs.theme || 'system', [
          { value: 'system', label: 'Match device' },
          { value: 'light', label: 'Light' },
          { value: 'dark', label: 'Dark' }
        ]))
      ]),
      field('Preferred voice', textInput('ai-voice', prefs.voice_preference),
        'Leave blank to use the default voice for your language.'),
      DEDAN.el('div', { class: 'flex gap-space-sm' }, [saveButton('Save AI preferences')])
    ], function () {
      return DEDAN.patch('/users/me/preferences', {
        language: document.getElementById('ai-language').value,
        theme: document.getElementById('ai-theme').value,
        voice_preference: document.getElementById('ai-voice').value.trim() || null
      }).then(function (prefs) {
        state.preferences = prefs;
      });
    });
  }

  function renderSecurity() {
    mount('security', [
      DEDAN.el('p', { class: 'font-body-sm text-body-sm text-on-surface-variant', text:
        'Changing your password requires your current one. You will stay signed in on this device.' }),
      DEDAN.el('div', { class: 'grid grid-cols-1 md:grid-cols-2 gap-space-md' }, [
        field('Current password', DEDAN.el('input', { id: 'pw-current', class: INPUT, type: 'password', autocomplete: 'current-password' })),
        field('New password', DEDAN.el('input', { id: 'pw-new', class: INPUT, type: 'password', autocomplete: 'new-password' }),
          'At least 10 characters, mixing upper and lower case.')
      ]),
      field('Confirm new password', DEDAN.el('input', { id: 'pw-confirm', class: INPUT, type: 'password', autocomplete: 'new-password' })),
      DEDAN.el('div', { class: 'flex gap-space-sm' }, [saveButton('Update password')]),
      DEDAN.el('div', { class: 'mt-2 pt-4 border-t border-outline-variant/30 flex flex-col gap-space-sm' }, [
        DEDAN.el('h3', { class: 'font-label-lg text-label-lg text-on-surface font-semibold', text: 'This device' }),
        DEDAN.el('p', { class: 'font-body-sm text-body-sm text-on-surface-variant', text:
          'This session is protected by a signed token that expires automatically. Signing out on this device clears it immediately.' }),
        DEDAN.el('div', { class: 'flex' }, [
          DEDAN.el('button', {
            type: 'button', class: BTN_GHOST,
            onclick: function () { DEDAN.logout(); }
          }, ['Sign out of this device'])
        ])
      ])
    ], function (form) {
      var current = document.getElementById('pw-current').value;
      var next = document.getElementById('pw-new').value;
      var confirm = document.getElementById('pw-confirm').value;
      if (next !== confirm) {
        throw new Error('New passwords do not match.');
      }
      return DEDAN.post('/auth/password', {
        current_password: current,
        new_password: next,
        new_password_confirmation: confirm
      }).then(function () {
        form.reset();
      });
    });
  }

  function renderPrivacy() {
    var consent = state.consent;
    var hasConsent = consent.treatment_processing;
    mount('privacy-fhir', [
      DEDAN.el('div', {
        class: 'rounded-lg px-3 py-2.5 font-body-sm text-body-sm ' +
          (hasConsent ? 'bg-secondary-container text-on-secondary-container' : 'bg-tertiary-container text-on-tertiary-container')
      }, hasConsent
        ? 'You have consented to clinical data processing. DEDAN can store and read your health profile.'
        : 'Consent is withheld. DEDAN cannot store or read your health profile until you grant it.'),
      toggle('consent-treatment', 'Clinical data processing',
        'Required to store your health profile, history and consultation records.', consent.treatment_processing),
      toggle('consent-clinicians', 'Share with my care team',
        'Allows a clinician to receive a visit summary you have reviewed and approved.', consent.data_sharing_with_clinicians),
      toggle('consent-analytics', 'Anonymous analytics', 'Usage statistics with no health data attached.', consent.analytics),
      toggle('consent-research', 'De-identified research', 'Contribute de-identified data to clinical research.', consent.research),
      toggle('consent-marketing', 'Product communications', 'Feature announcements. Never health-related.', consent.marketing),
      DEDAN.el('p', { class: 'font-body-sm text-body-sm text-on-surface-variant', text:
        consent.granted_at ? 'Consent last granted ' + DEDAN.fmtDateTime(consent.granted_at) + '. Policy version ' + (consent.policy_version || '1.0') + '.' : 'No consent has been recorded yet.' }),
      DEDAN.el('div', { class: 'flex gap-space-sm' }, [saveButton('Save consent choices')])
    ], function () {
      return DEDAN.patch('/users/me/consent', {
        treatment_processing: document.getElementById('consent-treatment').checked,
        data_sharing_with_clinicians: document.getElementById('consent-clinicians').checked,
        analytics: document.getElementById('consent-analytics').checked,
        research: document.getElementById('consent-research').checked,
        marketing: document.getElementById('consent-marketing').checked
      }).then(function (consent) {
        state.consent = consent;
        /*
         * The health endpoint is gated on consent, so withdrawing it changes what
         * this page can show. Re-render rather than leaving a stale panel that
         * still shows a medication list the server would now refuse to return.
         */
        state.health = null;
        return refreshProfile().then(renderPrivacy).then(renderHealthProfile);
      });
    });
  }

  function renderHealthProfile() {
    var body = bodyOf('health-profile');
    if (!body) {
      return;
    }

    if (!state.consent.treatment_processing) {
      DEDAN.render(body, DEDAN.emptyState(
        'Health data is locked',
        'Grant consent for clinical data processing above to store and view your health profile.',
        'lock'
      ));
      return;
    }

    if (state.health === null) {
      DEDAN.render(body, DEDAN.el('p', { class: 'font-body-md text-body-md text-on-surface-variant', text: 'Loading health profile…' }));
      DEDAN.get('/users/me/health-profile')
        .then(function (health) {
          state.health = health;
          renderHealthProfile();
        })
        .catch(function (err) {
          state.health = false;
          DEDAN.render(body, DEDAN.el('p', { class: 'font-body-md text-body-md text-error', text: err.message }));
        });
      return;
    }

    if (state.health === false) {
      DEDAN.render(body, DEDAN.el('p', { class: 'font-body-md text-body-md text-error', text: 'Could not load your health profile.' }));
      return;
    }

    var health = state.health;
    mount('health-profile', [
      DEDAN.el('div', { class: 'grid grid-cols-1 md:grid-cols-2 gap-space-md' }, [
        field('Biological sex', selectInput('hp-sex', health.sex || '', [
          { value: '', label: 'Not specified' },
          { value: 'female', label: 'Female' },
          { value: 'male', label: 'Male' },
          { value: 'intersex', label: 'Intersex' },
          { value: 'other', label: 'Other' }
        ])),
        field('Blood type', textInput('hp-blood', health.blood_type, 'e.g. O+'))
      ]),
      field('Known allergies', textInput('hp-allergies', DEDAN.splitList(health.allergies).join(', ')),
        'Comma separated, e.g. penicillin, latex.'),
      field('Current medications', textInput('hp-medications', DEDAN.splitList(health.medications).join(', '))),
      field('Existing conditions', textInput('hp-conditions', DEDAN.splitList(health.conditions).join(', '))),
      DEDAN.el('div', { class: 'grid grid-cols-1 md:grid-cols-2 gap-space-md' }, [
        field('Emergency contact', textInput('hp-ec-name', health.emergency_contact_name)),
        field('Emergency contact phone', textInput('hp-ec-phone', health.emergency_contact_phone))
      ]),
      DEDAN.el('p', { class: 'font-body-sm text-body-sm text-on-surface-variant', text:
        'DEDAN reads this during every consultation to check your medications for interactions and to warn your emergency contact.' }),
      DEDAN.el('div', { class: 'flex gap-space-sm' }, [saveButton('Save health profile')])
    ], function () {
      var payload = {
        sex: document.getElementById('hp-sex').value || null,
        blood_type: document.getElementById('hp-blood').value.trim() || null,
        allergies: document.getElementById('hp-allergies').value.trim(),
        medications: document.getElementById('hp-medications').value.trim(),
        conditions: document.getElementById('hp-conditions').value.trim(),
        emergency_contact_name: document.getElementById('hp-ec-name').value.trim() || null,
        emergency_contact_phone: document.getElementById('hp-ec-phone').value.trim() || null
      };
      return DEDAN.patch('/users/me/health-profile', payload).then(function (health) {
        state.health = health;
      });
    });
  }

  /* ----------------------------------------------------------------- boot */

  function refreshProfile() {
    return DEDAN.get('/auth/session').then(function (session) {
      state.profile = session.profile;
      DEDAN.setSession(DEDAN.getToken(), session.profile);
      state.consent = session.profile.consent;
      return session.profile;
    });
  }

  function paintHeader() {
    var profile = state.profile;
    DEDAN.paintIdentity(profile);
    // The header ships with a placeholder patient; replace those two nodes.
    document.querySelectorAll('header .font-label-md.font-semibold').forEach(function (node) {
      if (node.textContent === 'Daniel Vance') {
        node.textContent = profile.display_name || 'Patient';
      }
    });
    document.querySelectorAll('header .font-label-sm.text-on-surface-variant').forEach(function (node) {
      if (node.textContent === 'DE482731') {
        node.textContent = profile.dedan_user_id;
      }
    });
    var avatar = document.querySelector('header .w-8.h-8.rounded-full.bg-primary span.material-symbols-outlined');
    if (avatar) {
      avatar.textContent = 'account_circle';
    }
  }

  // `SHELL.boot` renders the shared sidebar and mobile navigation, then
  // requires a session before running the page body.
  //
  // This previously called `DEDAN.requireSession()` directly and then
  // `SHELL.wireChrome()`. That worked only because this page still carried its
  // own hand-written <nav> block; it was the one page that never booted the
  // shell, so it was also the one page that silently rendered no sidebar at
  // all once the duplicated markup was removed.
  SHELL.boot(function (profile) {
    state.profile = profile;
    state.consent = profile.consent || {};

    paintHeader();
    renderPersonal();
    renderAccount();
    renderSecurity();

    return DEDAN.get('/users/me/preferences')
      .then(function (prefs) {
        state.preferences = prefs;
        renderCommunication();
        renderDedanAi();
      })
      .then(function () {
        renderPrivacy();
        renderHealthProfile();
      });
  });
})();
