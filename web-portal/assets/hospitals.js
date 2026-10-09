/*
 * Appointments: book, reschedule, cancel.
 *
 * Backed by /users/me/appointments. The page previously showed a fixed calendar
 * for "Thursday, October 24, 2024" with a fictional clinician and slots that
 * went nowhere; every value here now comes from the server, and an empty list
 * says so rather than implying the patient has nothing booked.
 *
 * Slot times are entered by the patient rather than scraped from a provider
 * system: `care_navigation.slots_for` exists for facility availability, but a
 * DEDAN consultation is not tied to one facility record, and inventing slots the
 * backend cannot confirm would be exactly the fabrication the clinical spec
 * forbids.
 */
(function () {
  'use strict';

  var DEDAN = window.DEDAN;
  var SHELL = window.DEDAN_SHELL;
  var state = { appointments: [], filters: 'all' };

  var STATUS_STYLE = {
    SCHEDULED: 'bg-surface-container text-on-surface-variant',
    CONFIRMED: 'bg-secondary-container text-on-secondary-container',
    RESCHEDULED: 'bg-tertiary-container text-on-tertiary-container',
    CANCELLED: 'bg-surface-container-high text-outline',
    COMPLETED: 'bg-surface-container text-on-surface-variant',
    MISSED: 'bg-error-container text-on-error-container'
  };

  /* ------------------------------------------------------------- rendering */

  function visible() {
    var now = Date.now();
    return state.appointments.filter(function (a) {
      var at = new Date(a.scheduled_at).getTime();
      if (state.filters === 'upcoming') {
        return at >= now && a.status !== 'CANCELLED' && a.status !== 'COMPLETED';
      }
      if (state.filters === 'past') {
        return at < now || a.status === 'COMPLETED' || a.status === 'CANCELLED';
      }
      return true;
    }).sort(function (a, b) {
      return new Date(a.scheduled_at) - new Date(b.scheduled_at);
    });
  }

  function statusPill(status) {
    return DEDAN.el('span', {
      class: 'inline-flex items-center rounded-full px-2 py-0.5 font-label-sm text-label-sm ' +
        (STATUS_STYLE[status] || STATUS_STYLE.SCHEDULED),
      text: DEDAN.humanise(status)
    });
  }

  /**
   * Headline counts.
   *
   * Derived from `state.appointments` at render time, never from a count fetched
   * alongside the list, so the tiles and the list can never disagree.
   */
  function renderSummary() {
    var profile = DEDAN.getProfile() || {};
    SHELL.fill('appointments-summary', DEDAN.el('div', { class: 'grid grid-cols-1 sm:grid-cols-3 gap-gutter' }, [
      stat('Total booked', state.appointments.length),
      stat('Upcoming', visibleCount('upcoming')),
      stat('Signed in as', profile.display_name || 'Patient')
    ]));
  }

  function renderList() {
    var host = document.getElementById('appointments-list');
    if (!host) {
      return;
    }
    var rows = visible();

    if (!rows.length) {
      DEDAN.render(host, DEDAN.emptyState(
        state.appointments.length ? 'Nothing in this view' : 'No appointments yet',
        state.appointments.length
          ? 'Try a different filter.'
          : 'Book a consultation and it will appear here with its reminders.',
        'event_busy'
      ));
      return;
    }

    DEDAN.render(host, rows.map(function (a) {
      var id = a.appointment_id;
      var active = a.status !== 'CANCELLED' && a.status !== 'COMPLETED';

      return DEDAN.el('article', { class: 'flex flex-col md:flex-row md:items-center gap-space-md rounded-xl border border-outline-variant/30 bg-surface-container-lowest p-space-md' }, [
        DEDAN.el('div', { class: 'flex flex-col md:flex-row md:items-center gap-3 md:gap-space-md flex-1' }, [
          DEDAN.el('div', { class: 'w-12 h-12 rounded-lg bg-surface-container flex flex-col items-center justify-center shrink-0' }, [
            DEDAN.el('span', { class: 'font-label-sm text-label-sm uppercase text-secondary', text: new Date(a.scheduled_at).toLocaleDateString(undefined, { month: 'short' }) }),
            DEDAN.el('span', { class: 'font-headline-sm text-headline-sm text-primary font-bold', text: new Date(a.scheduled_at).getDate() })
          ]),
          DEDAN.el('div', { class: 'flex flex-col gap-0.5' }, [
            DEDAN.el('div', { class: 'flex items-center gap-2 flex-wrap' }, [
              DEDAN.el('h3', { class: 'font-headline-sm text-headline-sm text-on-surface font-semibold', text: DEDAN.humanise(a.appointment_type) }),
              statusPill(a.status)
            ]),
            DEDAN.el('p', { class: 'font-body-sm text-body-sm text-on-surface-variant', text: DEDAN.fmtTime(a.scheduled_at) + ' · ' + a.duration_minutes + ' min · ' + DEDAN.fmtRelative(a.scheduled_at) }),
            a.location ? DEDAN.el('p', { class: 'font-body-sm text-body-sm text-on-surface-variant', text: a.location }) : null,
            a.notes ? DEDAN.el('p', { class: 'font-body-sm text-body-sm text-outline italic', text: a.notes }) : null
          ])
        ]),
        active ? DEDAN.el('div', { class: 'flex gap-space-xs' }, [
          SHELL.button('Reschedule', SHELL.BTN_GHOST, function () { openReschedule(a); }),
          SHELL.button('Cancel', 'inline-flex items-center rounded-lg border border-error/40 px-3 py-1.5 font-label-sm text-label-sm text-error hover:bg-error-container transition-colors', function () {
            cancelAppointment(a);
          })
        ]) : null
      ]);
    }));
  }

  function renderFilters() {
    var host = document.getElementById('appointment-filters');
    if (!host) {
      return;
    }
    var counts = {
      all: state.appointments.length,
      upcoming: visibleCount('upcoming'),
      past: visibleCount('past')
    };
    var base = 'px-3 py-1.5 rounded-lg font-label-lg text-label-lg transition-colors';
    DEDAN.render(host, ['all', 'upcoming', 'past'].map(function (key) {
      return DEDAN.el('button', {
        type: 'button',
        class: base + ' ' + (state.filters === key
          ? 'bg-primary text-on-primary font-semibold'
          : 'bg-surface-container text-on-surface-variant hover:bg-surface-container-high'),
        onclick: function () { state.filters = key; renderFilters(); renderList(); }
      }, [DEDAN.humanise(key) + ' (' + counts[key] + ')']);
    }));
  }

  function visibleCount(filter) {
    var save = state.filters;
    state.filters = filter;
    var n = visible().length;
    state.filters = save;
    return n;
  }

  /* --------------------------------------------------------------- actions */

  function reload() {
    return DEDAN.get('/users/me/appointments?limit=100').then(function (rows) {
      state.appointments = rows || [];
      renderFilters();
      renderList();
      renderSummary();
    }).catch(function (err) {
      DEDAN.render(document.getElementById('appointments-list'),
        DEDAN.emptyState('Could not load appointments', err.message, 'error'));
    });
  }

  function cancelAppointment(appointment) {
    if (!globalThis.confirm('Cancel this ' + DEDAN.humanise(appointment.appointment_type).toLowerCase() +
      ' on ' + DEDAN.fmtDateTime(appointment.scheduled_at) + '?')) {
      return;
    }
    DEDAN.patch('/users/me/appointments/' + appointment.appointment_id + '/status', { status: 'CANCELLED' })
      .then(function () {
        DEDAN.showToast('Appointment cancelled.', 'success');
        return reload();
      })
      .catch(function (err) { DEDAN.showToast(err.message, 'error'); });
  }

  function openReschedule(appointment) {
    var form = document.getElementById('reschedule-form');
    var panel = document.getElementById('reschedule-panel');
    if (!form || !panel) {
      return;
    }
    var when = new Date(appointment.scheduled_at);
    // `toISOString` is UTC and `datetime-local` wants local wall time, so the
    // value is shifted before formatting; skipping this books the visit at the
    // wrong hour for every patient outside UTC.
    var local = new Date(when.getTime() - when.getTimezoneOffset() * 60000);
    document.getElementById('reschedule-id').value = appointment.appointment_id;
    document.getElementById('reschedule-when').value = local.toISOString().slice(0, 16);
    panel.classList.remove('hidden');
    panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function wireReschedule() {
    var form = document.getElementById('reschedule-form');
    if (!form) {
      return;
    }
    var dismiss = document.getElementById('reschedule-cancel');
    if (dismiss) {
      dismiss.addEventListener('click', function () {
        document.getElementById('reschedule-panel').classList.add('hidden');
      });
    }

    form.addEventListener('submit', function (event) {
      event.preventDefault();
      var error = form.querySelector('[data-form-error]');
      error.classList.add('hidden');

      var id = document.getElementById('reschedule-id').value;
      var when = document.getElementById('reschedule-when').value;
      if (!when) {
        error.textContent = 'Choose a new date and time.';
        error.classList.remove('hidden');
        return;
      }

      var restore = DEDAN.busy(form, form.querySelector('button[type=submit]'), 'Moving…');
      DEDAN.post('/users/me/appointments/' + id + '/reschedule', {
        // No timezone field: the backend stores what it is given, and sending the
        // browser's offset would double-apply it.
        scheduled_at: new Date(when).toISOString(),
        appointment_type: 'consultation'
      }).then(function () {
        DEDAN.showToast('Appointment moved. Reminders were updated.', 'success');
        document.getElementById('reschedule-panel').classList.add('hidden');
        return reload();
      }).catch(function (err) {
        restore();
        error.textContent = err.message;
        error.classList.remove('hidden');
      });
    });
  }

  function wireBooking() {
    var form = document.getElementById('booking-form');
    if (!form) {
      return;
    }
    form.addEventListener('submit', function (event) {
      event.preventDefault();
      SHELL.clearError(form);

      var when = document.getElementById('book-when').value;
      var type = document.getElementById('book-type').value;
      var modality = document.getElementById('book-modality').value;
      var reason = document.getElementById('book-reason').value.trim();
      var location = document.getElementById('book-location').value.trim();
      var meetingUrl = document.getElementById('book-url').value.trim();

      if (!when) {
        SHELL.showError(form, 'Choose a date and time for the appointment.');
        return;
      }
      if (reason.length < 5) {
        SHELL.showError(form, 'Tell DEDAN briefly what the visit is for.');
        return;
      }
      if (modality === 'telehealth' && !/^https:\/\//i.test(meetingUrl)) {
        SHELL.showError(form, 'A telehealth appointment needs a secure https:// meeting link.');
        return;
      }

      var restore = DEDAN.busy(form, form.querySelector('button[type=submit]'), 'Booking…');
      DEDAN.post('/users/me/appointments', {
        scheduled_at: new Date(when).toISOString(),
        appointment_type: type,
        duration_minutes: 30,
        location: location || null,
        meeting_url: modality === 'telehealth' ? meetingUrl : null,
        notes: reason
      }).then(function (result) {
        restore();
        DEDAN.showToast('Appointment booked.', 'success');
        form.reset();
        var queued = (result && result.reminders && result.reminders.length) || 0;
        if (queued) {
          DEDAN.showToast(queued + ' reminder(s) scheduled.', 'info');
        }
        return reload();
      }).catch(function (err) {
        restore();
        SHELL.showError(form, err.message);
      });
    });
  }

  /* ------------------------------------------------------------------ boot */

  SHELL.boot(function (profile) {
    wireBooking();
    wireReschedule();

    // Default the booking form to tomorrow at 09:00, which is a valid future
    // slot in every timezone (an empty value would fail server-side validation).
    var tomorrow = new Date(Date.now() + 86400000);
    tomorrow.setHours(9, 0, 0, 0);
    var bookWhen = document.getElementById('book-when');
    if (bookWhen && !bookWhen.value) {
      bookWhen.value = new Date(tomorrow.getTime() - tomorrow.getTimezoneOffset() * 60000)
        .toISOString().slice(0, 16);
    }

    return reload();
  });

  function stat(labelText, value) {
    return DEDAN.el('div', { class: 'rounded-xl bg-surface-container-lowest border border-outline-variant/40 px-4 py-3 flex flex-col gap-0.5' }, [
      DEDAN.el('span', { class: SHELL.LABEL, text: labelText }),
      DEDAN.el('span', { class: 'font-headline-sm text-headline-sm text-primary font-semibold', text: String(value) })
    ]);
  }
})();
