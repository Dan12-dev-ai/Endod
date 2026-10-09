/*
 * Health history: the patient's timeline plus their stored health profile.
 *
 * Backed by /users/me/timeline (cursor-paginated), /users/me/timeline/summary
 * and /users/me/health-profile. Two behaviours worth stating:
 *
 *  - The health profile is only read when consent for clinical data processing
 *    is recorded. The server answers 403 otherwise, by design, so a refusal is
 *    distinguishable from "no data recorded". The page explains that and links
 *    to Settings instead of rendering an empty panel that looks like data loss.
 *  - Deleting a timeline event asks first and reloads the list from the server
 *    rather than splicing the array, so the view can never drift from the record.
 */
(function () {
  'use strict';

  var DEDAN = window.DEDAN;
  var SHELL = window.DEDAN_SHELL;

  var state = { cursor: null, events: [], filterType: '', exhausted: false, profile: null };

  /*
   * The API's event vocabulary is UPPER_SNAKE (`HealthEventType` in
   * `dedan_platform/models.py`) and is a *closed set*. The keys here are
   * lowercased, and lookups normalise, so `APPOINTMENT` matches instead of
   * falling through to a generic glyph.
   */
  var TYPE_META = {
    ai_conversation: { icon: 'forum', label: 'AI consultation' },
    consultation: { icon: 'forum', label: 'Consultation' },
    appointment: { icon: 'event', label: 'Appointment' },
    follow_up: { icon: 'event_repeat', label: 'Follow-up' },
    medication: { icon: 'medication', label: 'Medication' },
    prescription: { icon: 'prescriptions', label: 'Prescription' },
    document: { icon: 'description', label: 'Document' },
    lab_result: { icon: 'science', label: 'Lab result' },
    imaging: { icon: 'radiology', label: 'Imaging' },
    vital: { icon: 'monitor_heart', label: 'Vital sign' },
    safety_alert: { icon: 'warning', label: 'Safety alert' },
    care_navigation: { icon: 'local_hospital', label: 'Care navigation' },
    other: { icon: 'article', label: 'Other' }
  };

  /** Normalise an API event type to a TYPE_META key, or null when unknown. */
  function metaFor(eventType) {
    return TYPE_META[String(eventType || '').toLowerCase()] || null;
  }

  var STATUS_CLASS = {
    COMPLETED: 'bg-secondary-container text-on-secondary-container',
    SCHEDULED: 'bg-surface-container text-on-surface-variant',
    CANCELLED: 'bg-surface-container-high text-outline',
    MISSED: 'bg-error-container text-on-error-container'
  };

  /* ---------------------------------------------------------------- events */

  function load(reset) {
    if (reset) {
      state.cursor = null;
      state.events = [];
      state.exhausted = false;
    }
    var url = '/users/me/timeline?limit=25';
    if (state.cursor) {
      url += '&cursor=' + encodeURIComponent(state.cursor);
    }
    if (state.filterType) {
      url += '&event_type=' + encodeURIComponent(state.filterType);
    }

    return DEDAN.get(url).then(function (payload) {
      state.events = state.events.concat(payload.events || []);
      state.cursor = payload.next_cursor;
      state.exhausted = !payload.has_more;
      renderTimeline();
      renderSummary(payload);
    }).catch(function (err) {
      DEDAN.render(document.getElementById('timeline'),
        DEDAN.emptyState('Could not load your history', err.message, 'error'));
    });
  }

  function renderTimeline() {
    var host = document.getElementById('timeline');
    if (!state.events.length) {
      DEDAN.render(host, DEDAN.emptyState(
        state.filterType ? 'Nothing of this type yet' : 'No health activity yet',
        state.filterType
          ? 'Try a different type filter.'
          : 'Your consultations, documents and care events will be recorded here.',
        'history'
      ));
      return;
    }

    var byMonth = {};
    state.events.forEach(function (event) {
      var key = (event.occurred_at || event.created_at || '').slice(0, 7);
      (byMonth[key] = byMonth[key] || []).push(event);
    });

    var sections = Object.keys(byMonth).sort().reverse().map(function (month) {
      return DEDAN.el('div', { class: 'flex flex-col gap-space-sm' }, [
        DEDAN.el('h3', { class: 'font-headline-sm text-headline-sm text-primary font-semibold sticky top-0 bg-surface py-1',
          text: monthLabel(month) }),
        DEDAN.el('div', { class: 'flex flex-col gap-space-xs' }, byMonth[month].map(eventCard))
      ]);
    });

    var loadMore = state.exhausted ? null : DEDAN.el('div', { class: 'pt-2 flex justify-center' }, [
      DEDAN.el('button', {
        type: 'button', class: SHELL.BTN_GHOST,
        onclick: function (event) {
          var btn = event.currentTarget;
          btn.disabled = true;
          btn.textContent = 'Loading…';
          load(false).then(function () { btn.disabled = false; btn.textContent = 'Load earlier events'; });
        }
      }, ['Load earlier events'])
    ]);

    DEDAN.render(host, sections.concat([loadMore]));
  }

  function monthLabel(month) {
    if (!month) {
      return 'Earlier';
    }
    var date = new Date(month + '-01T00:00:00');
    return isNaN(date.getTime()) ? month : date.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
  }

  function eventCard(event) {
    var meta = metaFor(event.event_type) || { icon: 'article', label: DEDAN.humanise(event.event_type) };
    var expanded = false;
    var detail = DEDAN.el('div', { class: 'hidden pt-2 flex flex-col gap-2' });

    var toggle = DEDAN.el('button', {
      type: 'button',
      class: 'font-body-sm text-body-sm text-secondary hover:underline text-left',
      onclick: function () {
        expanded = !expanded;
        detail.classList.toggle('hidden', !expanded);
        toggle.textContent = expanded ? 'Hide detail' : 'Show detail';
        if (expanded && !detail.dataset.loaded) {
          detail.dataset.loaded = '1';
          DEDAN.get('/users/me/timeline/' + encodeURIComponent(event.event_id)).then(function (full) {
            DEDAN.render(detail, detailView(full));
          }).catch(function (err) {
            DEDAN.render(detail, DEDAN.el('p', { class: 'font-body-sm text-body-sm text-error', text: err.message }));
          });
        }
      }
    }, ['Show detail']);

    return DEDAN.el('article', { class: 'rounded-xl border border-outline-variant/30 bg-surface-container-lowest p-space-md flex flex-col gap-2' }, [
      DEDAN.el('div', { class: 'flex items-start gap-space-sm' }, [
        DEDAN.el('span', { class: 'material-symbols-outlined text-secondary mt-0.5 shrink-0', style: 'font-size:20px', text: meta.icon }),
        DEDAN.el('div', { class: 'flex flex-col gap-1 flex-1' }, [
          DEDAN.el('div', { class: 'flex items-center gap-2 flex-wrap' }, [
            DEDAN.el('h4', { class: 'font-label-lg text-label-lg text-on-surface font-semibold', text: event.title || meta.label }),
            DEDAN.el('span', { class: 'rounded-full px-2 py-0.5 font-label-sm text-label-sm ' + (STATUS_CLASS[event.status] || STATUS_CLASS.SCHEDULED),
              text: DEDAN.humanise(event.status) })
          ]),
          event.description ? DEDAN.el('p', { class: 'font-body-sm text-body-sm text-on-surface-variant', text: event.description }) : null,
          DEDAN.el('p', { class: 'font-label-sm text-label-sm text-outline',
            text: meta.label + ' · ' + DEDAN.fmtDateTime(event.occurred_at || event.created_at) })
        ]),
        DEDAN.el('button', {
          type: 'button',
          class: 'inline-flex items-center gap-1 text-outline hover:text-error transition-colors shrink-0 font-label-sm text-label-sm',
          title: 'Delete this event',
          'aria-label': 'Delete ' + (event.title || 'this event'),
          onclick: function () { deleteEvent(event); }
        }, [
          DEDAN.el('span', { class: 'material-symbols-outlined', style: 'font-size:16px', 'aria-hidden': 'true', text: 'delete' }),
          'Delete'
        ])
      ]),
      toggle,
      detail
    ]);
  }

  function detailView(event) {
    var meta = (event.metadata && Object.keys(event.metadata).length)
      ? DEDAN.el('pre', {
          class: 'rounded-lg bg-surface-container p-3 text-[11px] leading-relaxed overflow-x-auto whitespace-pre-wrap break-words font-body-sm text-body-sm text-on-surface-variant'
        })
      : null;

    return [
      DEDAN.el('p', { class: 'font-body-sm text-body-sm text-on-surface-variant',
        text: 'Recorded ' + DEDAN.fmtDateTime(event.created_at) + (event.source ? ' · source: ' + event.source : '') }),
      meta ? DEDAN.el('span', { class: SHELL.LABEL, text: 'Metadata' }) : null,
      meta
    ];
  }

  function deleteEvent(event) {
    if (!globalThis.confirm('Delete "' + (event.title || 'this event') + '" from your history? This cannot be undone.')) {
      return;
    }
    DEDAN.del('/users/me/timeline/' + encodeURIComponent(event.event_id))
      .then(function () {
        DEDAN.showToast('Event deleted.', 'success');
        return load(true).then(renderHealthProfile);
      })
      .catch(function (err) { DEDAN.showToast(err.message, 'error'); });
  }

  function renderSummary() {
    return DEDAN.get('/users/me/timeline/summary').then(function (summary) {
      var counts = summary.by_type || {};
      DEDAN.render(document.getElementById('history-summary'), DEDAN.el('div', { class: 'grid grid-cols-2 sm:grid-cols-4 gap-3' }, [
        tile('Total events', summary.total || 0),
        tile('Upcoming', summary.upcoming || 0),
        tile('Consultations', counts.consultation || 0),
        tile('Safety alerts', counts.safety_alert || 0)
      ]));

      var filter = document.getElementById('type-filter');
      DEDAN.render(filter, [DEDAN.el('option', { value: '', text: 'All types' })].concat(
        Object.keys(TYPE_META).map(function (key) {
          return DEDAN.el('option', { value: key, text: TYPE_META[key].label });
        })
      ));
      filter.value = state.filterType;
    });
  }

  function tile(labelText, value) {
    return DEDAN.el('div', { class: 'rounded-lg bg-surface-container px-3 py-2.5 flex flex-col gap-0.5' }, [
      DEDAN.el('span', { class: SHELL.LABEL, text: labelText }),
      DEDAN.el('span', { class: 'font-headline-sm text-headline-sm text-primary font-semibold', text: String(value) })
    ]);
  }

  /* -------------------------------------------------------- health profile */

  function renderHealthProfile() {
    var host = document.getElementById('health-summary');
    var profile = DEDAN.getProfile() || {};

    if (!DEDAN.hasTreatmentConsent(profile)) {
      DEDAN.render(host, DEDAN.emptyState(
        'Health profile is locked',
        'DEDAN needs your consent for clinical data processing before it can store or show your health profile.',
        'lock'
      ));
      var link = DEDAN.el('a', { class: SHELL.BTN_PRIMARY, href: 'settings.html#privacy-fhir' }, ['Review consent in Settings']);
      host.appendChild(link);
      return Promise.resolve();
    }

    DEDAN.render(host, DEDAN.el('p', { class: 'font-body-md text-body-md text-on-surface-variant', text: 'Loading…' }));

    return DEDAN.get('/users/me/health-profile').then(function (health) {
      state.profile = health;
      var rows = [
        ['Allergies', health.allergies],
        ['Medications', health.medications],
        ['Conditions', health.conditions],
        ['Blood type', health.blood_type],
        ['Emergency contact', health.emergency_contact_name],
        ['Emergency phone', health.emergency_contact_phone]
      ].filter(function (row) {
        var value = row[1];
        return Array.isArray(value) ? value.length : Boolean(value);
      });

      if (!rows.length) {
        DEDAN.render(host, DEDAN.emptyState(
          'No health profile recorded yet',
          'Add your allergies, medications and conditions so DEDAN can check them during every consultation.',
          'medical_information'
        ));
        var edit = DEDAN.el('a', { class: SHELL.BTN_PRIMARY, href: 'settings.html#health-profile' }, ['Add health details']);
        host.appendChild(edit);
        return;
      }

      DEDAN.render(host, [
        DEDAN.el('dl', { class: 'grid grid-cols-1 sm:grid-cols-2 gap-3' }, rows.map(function (row) {
          var value = row[1];
          return DEDAN.el('div', { class: 'rounded-lg bg-surface-container px-3 py-2.5 flex flex-col gap-0.5' }, [
            DEDAN.el('dt', { class: SHELL.LABEL, text: row[0] }),
            DEDAN.el('dd', { class: 'font-body-md text-body-md text-on-surface',
              text: Array.isArray(value) ? value.join(', ') : String(value) })
          ]);
        })),
        DEDAN.el('a', { class: SHELL.BTN_GHOST, href: 'settings.html#health-profile' }, ['Edit health profile'])
      ]);
    }).catch(function (err) {
      DEDAN.render(host, DEDAN.emptyState('Could not load your health profile', err.message, 'error'));
    });
  }

  /* ------------------------------------------------------------------ boot */

  SHELL.boot(function () {
    var filter = document.getElementById('type-filter');
    filter.addEventListener('change', function () {
      state.filterType = filter.value;
      load(true);
    });

    return renderSummary()
      .then(function () { return load(true); })
      .then(renderHealthProfile);
  });
})();
