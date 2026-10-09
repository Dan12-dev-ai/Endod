/*
 * Find hospitals / care navigation.
 *
 * Backed by POST /users/me/care/facilities, which ranks the real facility
 * directory by clinical relevance and, only when the patient grants it, by
 * distance. Two rules from the server are honoured here rather than papered
 * over:
 *
 *  - Coordinates are sent only after an explicit geolocation grant, and the
 *    request declares `location_granted` truthfully. The server treats
 *    coordinates without the grant as absent, so claiming otherwise would just
 *    produce relevance-only ranking with extra steps.
 *  - Availability is never invented. `availability_source` is shown verbatim, so
 *    "not integrated" reads as an honest gap rather than a silent empty state.
 */
(function () {
  'use strict';

  var DEDAN = window.DEDAN;
  var SHELL = window.DEDAN_SHELL;
  var state = { results: null, locationGranted: false, coords: null, lastSearch: null };

  /* -------------------------------------------------------------- searching */

  function search() {
    var symptoms = DEDAN.splitList(document.getElementById('search-symptoms').value);
    var urgency = document.getElementById('search-urgency').value;
    var emergency = document.getElementById('search-emergency').checked;
    var query = document.getElementById('search-query').value.trim();

    if (!symptoms.length && !query) {
      DEDAN.showToast('Describe a symptom, or search by name.', 'warn');
      return;
    }

    var payload = {
      symptoms: symptoms,
      urgency: emergency ? 'emergency' : urgency,
      is_emergency: emergency,
      language: (DEDAN.getProfile() || {}).locale || 'en',
      query: query || null,
      limit: 8,
      location_granted: state.locationGranted
    };
    if (state.locationGranted && state.coords) {
      payload.latitude = state.coords.latitude;
      payload.longitude = state.coords.longitude;
    }

    state.lastSearch = payload;
    DEDAN.render(document.getElementById('results'), DEDAN.el('p', {
      class: 'font-body-md text-body-md text-on-surface-variant', text: 'Searching the care directory…'
    }));

    DEDAN.post('/users/me/care/facilities', payload)
      .then(function (result) {
        state.results = result;
        renderResults(result);
      })
      .catch(function (err) {
        DEDAN.render(document.getElementById('results'),
          DEDAN.emptyState('Could not search the care directory', err.message, 'error'));
      });
  }

  /* -------------------------------------------------------------- rendering */

  function renderResults(result) {
    var facilities = result.facilities || [];

    if (!facilities.length) {
      DEDAN.render(document.getElementById('results'), DEDAN.emptyState(
        'No matching facilities',
        'Try fewer symptoms, or a different country code.',
        'local_hospital'
      ));
      return;
    }

    var header = DEDAN.el('div', { class: 'flex flex-col gap-1 pb-1' }, [
      DEDAN.el('div', { class: 'flex flex-wrap items-center gap-2' }, [
        DEDAN.el('h2', { class: 'font-headline-sm text-headline-sm text-primary font-semibold',
          text: facilities.length + ' facilit' + (facilities.length === 1 ? 'y' : 'ies') + ' matched' }),
        DEDAN.el('span', {
          class: 'inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-label-sm text-label-sm ' +
            (result.location_used
              ? 'bg-secondary-container text-on-secondary-container'
              : 'bg-surface-container text-on-surface-variant'),
          text: result.location_used ? 'Ranked by distance' : 'Ranked by clinical relevance'
        })
      ]),
      DEDAN.el('p', { class: 'font-body-sm text-body-sm text-on-surface-variant', text:
        result.location_used
          ? 'Sorted using the location you shared with this page.'
          : 'Share your location to sort by distance. Without it DEDAN ranks on clinical relevance alone.' })
    ]);

    DEDAN.render(document.getElementById('results'), [header].concat(facilities.map(facilityCard)));
  }

  function facilityCard(facility) {
    var open = DEDAN.el('details', { class: 'mt-2' });
    var body = DEDAN.el('div', { class: 'flex flex-col gap-2 pt-2' });

    var availability = DEDAN.el('div', { class: 'font-body-sm text-body-sm text-on-surface-variant',
      text: 'Loading availability…' });

    open.appendChild(DEDAN.el('summary', {
      class: 'cursor-pointer font-label-sm text-label-sm text-secondary hover:underline',
      text: 'Check availability'
    }));
    open.addEventListener('toggle', function () {
      if (!open.open || open.dataset.loaded) {
        return;
      }
      open.dataset.loaded = '1';
      DEDAN.get('/users/me/care/facilities/' + encodeURIComponent(facility.id) + '/availability')
        .then(function (payload) {
          DEDAN.render(availability, availabilityView(payload));
        })
        .catch(function (err) {
          availability.textContent = err.message;
        });
    });
    body.appendChild(availability);
    open.appendChild(body);

    return DEDAN.el('article', { class: 'rounded-xl bg-surface-container-lowest border border-outline-variant/40 p-space-md flex flex-col gap-2' }, [
      DEDAN.el('div', { class: 'flex items-start justify-between gap-3' }, [
        DEDAN.el('div', { class: 'flex flex-col gap-0.5' }, [
          DEDAN.el('h3', { class: 'font-headline-sm text-headline-sm text-on-surface font-semibold', text: facility.name }),
          DEDAN.el('p', { class: 'font-body-sm text-body-sm text-on-surface-variant',
            text: [facility.address, facility.city].filter(Boolean).join(', ') }),
          DEDAN.el('p', { class: 'font-body-sm text-body-sm text-outline',
            text: facility.open_hours + (facility.emergency ? ' · Emergency department' : '') })
        ]),
        DEDAN.el('div', { class: 'flex flex-col items-end gap-1 shrink-0' }, [
          DEDAN.el('span', { class: 'inline-flex items-center gap-1 rounded-full bg-surface-container px-2 py-0.5 font-label-sm text-label-sm text-on-surface-variant',
            text: Math.min(100, Math.max(0, Math.round((facility.relevance_score || 0) * 100))) + '% match' }),
          facility.verified ? DEDAN.el('span', { class: 'inline-flex items-center gap-1 font-label-sm text-label-sm text-secondary',
            text: '✓ Verified' }) : null,
          typeof facility.distance_km === 'number'
            ? DEDAN.el('span', { class: 'font-label-sm text-label-sm text-on-surface-variant',
                text: facility.distance_km.toFixed(1) + ' km away' })
            : null
        ])
      ]),
      facility.notes ? DEDAN.el('p', { class: 'font-body-sm text-body-sm text-on-surface-variant', text: facility.notes }) : null,
      facility.reasons && facility.reasons.length
        ? DEDAN.el('div', { class: 'flex flex-wrap gap-1' }, facility.reasons.map(function (reason) {
            return DEDAN.el('span', { class: 'rounded-full bg-surface-container px-2 py-0.5 font-label-sm text-label-sm text-on-surface-variant', text: reason });
          }))
        : null,
      DEDAN.el('div', { class: 'flex flex-wrap gap-space-xs pt-1' }, [
        facility.phone ? DEDAN.el('a', { class: SHELL.BTN_GHOST, href: 'tel:' + facility.phone.replace(/\s+/g, '') },
          ['Call ' + facility.phone]) : null,
        DEDAN.el('button', {
          type: 'button', class: SHELL.BTN_PRIMARY,
          onclick: function () { recordNavigation(facility); }
        }, ['Add to my care plan']),
        open
      ])
    ]);
  }

  /**
   * Availability view.
   *
   * `availability_source` is rendered as-is. The directory is not yet wired to
   * any provider system, so the honest answer is "no live availability" -- and
   * inventing slots would be the single most damaging thing this page could do.
   */
  function availabilityView(payload) {
    var slots = (payload && (payload.slots || payload.available_slots)) || [];
    var source = (payload && payload.availability_source) || 'unknown';

    if (!slots.length) {
      return DEDAN.el('div', { class: 'flex flex-col gap-1' }, [
        DEDAN.el('p', { class: 'font-body-sm text-body-sm text-on-surface', text:
          'No live availability (' + DEDAN.humanise(source) + ').' }),
        DEDAN.el('p', { class: 'font-body-sm text-body-sm text-on-surface-variant', text:
          'Call the facility directly to confirm a slot, then book it from the Appointments page.' })
      ]);
    }
    return DEDAN.el('div', { class: 'flex flex-wrap gap-1' }, slots.map(function (slot) {
      return DEDAN.el('span', { class: 'rounded-lg bg-secondary-container text-on-secondary-container px-2 py-1 font-label-sm text-label-sm',
        text: typeof slot === 'string' ? slot : (slot.start || slot.label || JSON.stringify(slot)) });
    }));
  }

  function recordNavigation(facility) {
    var payload = {
      facility_id: facility.id,
      facility_name: facility.name,
      symptoms: state.lastSearch ? state.lastSearch.symptoms : [],
      urgency: state.lastSearch ? state.lastSearch.urgency : 'routine',
      is_emergency: state.lastSearch ? state.lastSearch.is_emergency : false,
      reason: 'Saved from care navigation'
    };
    DEDAN.post('/users/me/care/navigation', payload)
      .then(function () {
        DEDAN.showToast(facility.name + ' added to your care plan.', 'success');
      })
      .catch(function (err) {
        DEDAN.showToast(err.message, 'error');
      });
  }

  /* ----------------------------------------------------------- geolocation */

  function requestLocation() {
    if (!navigator.geolocation) {
      DEDAN.showToast('This browser cannot share a location.', 'warn');
      return;
    }
    var status = document.getElementById('location-status');
    status.textContent = 'Asking your browser for a location…';

    navigator.geolocation.getCurrentPosition(function (position) {
      state.locationGranted = true;
      state.coords = {
        latitude: position.coords.latitude,
        longitude: position.coords.longitude
      };
      status.textContent = 'Location shared with this page. Results will be sorted by distance.';
      document.getElementById('share-location').disabled = true;
      search();
    }, function (err) {
      // Denial is a legitimate answer, not an error to apologise for.
      status.textContent = err.code === err.PERMISSION_DENIED
        ? 'Location declined. Results stay ranked by clinical relevance.'
        : 'Could not determine your location. Results stay ranked by clinical relevance.';
    }, { enableHighAccuracy: false, timeout: 8000, maximumAge: 300000 });
  }

  /* ------------------------------------------------------------------ boot */

  SHELL.boot(function () {
    document.getElementById('share-location').addEventListener('click', requestLocation);
    document.getElementById('care-search-form').addEventListener('submit', function (event) {
      event.preventDefault();
      search();
    });

    DEDAN.render(document.getElementById('results'), DEDAN.emptyState(
      'Search the care directory',
      'Describe your symptoms and DEDAN will rank verified facilities by clinical relevance.',
      'search'
    ));

    // Deep link from a consultation escalation: ?symptoms=a,b&emergency=1
    var params = new URLSearchParams(window.location.search);
    if (params.get('symptoms')) {
      document.getElementById('search-symptoms').value = params.get('symptoms');
    }
    if (params.get('emergency') === '1') {
      document.getElementById('search-emergency').checked = true;
    }
    if (params.get('symptoms')) {
      search();
    }
  });
})();
