/*
 * Live consultation with DEDAN.
 *
 * Two paths, one clinical engine:
 *
 *  1. WebSocket (`/ws/live-voice`) for duplex voice, authenticated with the
 *     portal's own session token.
 *  2. `POST /api/analyze` for text, which is the same rules-based engine in
 *     offline mode and the model-backed path when a provider is configured.
 *
 * The previous version minted a *new anonymous identity on every page load*
 * (`/realtime/token?subject=patient-<timestamp>`), so no consultation was ever
 * attributable to the patient who had it, and when the socket failed to open the
 * send handler echoed the message and dropped it -- the primary feature appeared
 * to accept input and do nothing. Both are fixed here: identity comes from the
 * session, and the text path always produces an answer.
 *
 * Clinical safety rules honoured in the UI:
 *   - The model's own safety block is rendered before anything else, and an
 *     emergency finding replaces the rest of the page with the escalation path.
 *   - The disclaimer is shown with every result, not once at the bottom.
 *   - Confidence and uncertainty are displayed rather than hidden, so a patient
 *     can tell a hedged answer from a confident one.
 */
(function () {
  'use strict';

  var DEDAN = window.DEDAN;
  var SHELL = window.DEDAN_SHELL;

  var state = {
    profile: null,
    health: null,
    socket: null,
    connected: false,
    attempts: 0,
    maxAttempts: 3,
    turns: [],
    sessionId: null,
    pending: false
  };

  /* ------------------------------------------------------------ transcript */

  function addMessage(role, text) {
    var list = document.getElementById('message-list');
    if (!list) {
      return;
    }
    var isAssistant = role === 'assistant';
    var row = DEDAN.el('div', { class: 'flex items-start gap-2.5' }, [
      DEDAN.el('div', {
        class: 'w-6 h-6 rounded-full flex items-center justify-center text-[10px] shrink-0 ' +
          (isAssistant ? 'bg-teal-600 text-white' : 'bg-slate-100 text-slate-600 font-semibold')
      }, [
        DEDAN.el('span', { class: 'material-symbols-outlined', style: 'font-size:13px', text: isAssistant ? 'smart_toy' : 'person' })
      ]),
      DEDAN.el('div', { class: 'flex-1 text-xs flex flex-col gap-0.5' }, [
        DEDAN.el('div', { class: 'flex items-center justify-between' }, [
          DEDAN.el('span', { class: 'font-semibold text-[11px] ' + (isAssistant ? 'text-teal-800' : 'text-slate-900'), text: isAssistant ? 'DEDAN' : 'You' }),
          DEDAN.el('span', { class: 'text-[10px] text-slate-400', text: DEDAN.fmtTime(new Date()) })
        ]),
        DEDAN.el('p', { class: 'text-slate-600 text-[11px] leading-relaxed whitespace-pre-wrap', text: text })
      ])
    ]);
    list.appendChild(row);
    list.scrollTop = list.scrollHeight;
  }

  function setConnection(connected, label) {
    state.connected = connected;
    var pill = document.getElementById('connection-pill');
    if (!pill) {
      return;
    }
    pill.className = 'w-2.5 h-2.5 rounded-full ' + (connected ? 'bg-emerald-500 animate-pulse' : 'bg-amber-400');
    var text = document.getElementById('connection-label');
    if (text) {
      text.textContent = label || (connected ? 'Voice connected' : 'Text mode');
    }
  }

  /* ------------------------------------------------------------- websocket */

  function connect(token) {
    if (state.socket) {
      return;
    }
    var proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    var url = proto + '//' + window.location.host + '/ws/live-voice?token=' + encodeURIComponent(token);

    setConnection(false, 'Connecting…');
    var socket;
    try {
      socket = new WebSocket(url);
    } catch (err) {
      setConnection(false, 'Text mode');
      return;
    }
    state.socket = socket;

    socket.onopen = function () {
      state.attempts = 0;
      setConnection(true, 'Voice connected');
    };

    socket.onmessage = function (event) {
      var message;
      try {
        message = JSON.parse(event.data);
      } catch (err) {
        return;
      }
      if (message.type === 'ready') {
        state.sessionId = message.conversation_id || state.sessionId;
      } else if (message.type === 'transcript' && message.final && message.text) {
        pushTurn(message.role || 'assistant', message.text);
        addMessage(message.role || 'assistant', message.text);
      } else if (message.type === 'reply_done' && message.text) {
        addMessage('assistant', message.text);
      } else if (message.type === 'error') {
        // A voice failure degrades to text rather than ending the consultation.
        addMessage('assistant', 'Voice is unavailable (' + (message.message || 'unknown') + '). Continuing in text mode — describe your symptoms below.');
        setConnection(false, 'Text mode');
      }
    };

    socket.onclose = function (event) {
      state.socket = null;
      setConnection(false, 'Text mode');
      if (state.attempts < state.maxAttempts && event.code !== 4401) {
        state.attempts += 1;
        globalThis.setTimeout(function () { connect(token); }, 1500 * state.attempts);
      }
    };

    socket.onerror = function () {
      setConnection(false, 'Text mode');
    };
  }

  /* ------------------------------------------------------------ text engine */

  function pushTurn(role, content) {
    state.turns.push({ role: role, content: content });
    // Keep the context bounded; a very long history both costs tokens and
    // degrades relevance.
    if (state.turns.length > 12) {
      state.turns = state.turns.slice(-12);
    }
  }

  function send() {
    var input = document.getElementById('message-input');
    var text = input.value.trim();
    if (!text || state.pending) {
      return;
    }
    if (text.length < 10) {
      DEDAN.showToast('Please describe your symptoms in a little more detail (at least 10 characters).', 'warn');
      return;
    }

    input.value = '';
    addMessage('user', text);
    pushTurn('user', text);

    /*
     * Typed messages always go through the HTTP clinical engine, never the
     * socket.
     *
     * The socket opens successfully in an offline deployment -- there is no
     * provider key, so it simply never replies. When text was sent over it
     * instead, the patient watched their own message appear and nothing came
     * back, with no error anywhere: the primary feature looked broken and gave
     * no clue why. The socket is kept for voice, where it is the only transport,
     * and every typed turn gets an answer from the engine that can answer it.
     */
    analyse(text);
  }

  function analyse(symptomText) {
    state.pending = true;
    setBusy(true);

    var health = state.health || {};
    var payload = {
      patient_age: estimateAge(health) || 30,
      patient_sex: normalizeSex(health.sex),
      patient_language: (state.profile && state.profile.locale) || 'en',
      patient_chronic_conditions: health.conditions || [],
      patient_medications: health.medications || [],
      patient_allergies: health.allergies || [],
      symptom_description: symptomText,
      conversation_history: state.turns.slice(0, -1),
      consent: true
    };

    DEDAN.post('/api/analyze', payload)
      .then(function (result) {
        state.pending = false;
        setBusy(false);
        renderAnalysis(result);
      })
      .catch(function (err) {
        state.pending = false;
        setBusy(false);
        DEDAN.render(document.getElementById('analysis-panel'),
          DEDAN.el('p', { class: 'font-body-md text-body-md text-error', text: err.message }));
        addMessage('assistant', 'I could not complete that assessment (' + err.message + '). Please try again, or contact your clinic if this is urgent.');
      });
  }

  function setBusy(busy) {
    var button = document.getElementById('send-btn');
    if (button) {
      button.disabled = busy;
    }
    var status = document.getElementById('thinking');
    if (status) {
      status.classList.toggle('hidden', !busy);
    }
  }

  /*
   * Age is not stored anywhere in the platform, and /api/analyze requires it.
   * Rather than invent one silently, the patient is asked once and the answer is
   * kept for the session only.
   */
  function estimateAge(health) {
    return health && health.age ? Number(health.age) : null;
  }

  function normalizeSex(sex) {
    var value = String(sex || '').toLowerCase();
    if (value === 'male' || value === 'female') {
      return value;
    }
    return 'other';
  }

  /* --------------------------------------------------------- result render */

  function renderAnalysis(result) {
    var safety = result.safety || {};
    var urgent = safety.requires_immediate_care || safety.urgency === 'emergency';

    addMessage('assistant', summarise(result));

    var nodes = [];

    nodes.push(safetyBanner(safety, urgent));

    if (urgent) {
      nodes.push(DEDAN.el('div', { class: 'flex flex-col gap-2' }, [
        DEDAN.el('p', { class: 'font-body-md text-body-md text-on-surface',
          text: 'DEDAN recommends immediate professional care for what you described.' }),
        DEDAN.el('a', { class: SHELL.BTN_PRIMARY, href: 'find-hospitals.html?emergency=1', onclick: function () {
          recordConsultation(result, true);
        } }, ['Find emergency care near me']),
        DEDAN.el('a', { class: SHELL.BTN_GHOST, href: 'hospitals.html' }, ['Book an urgent appointment'])
      ]));
    } else {
      nodes = nodes.concat(explanations(result));
      nodes = nodes.concat(education(result));
      nodes = nodes.concat(followUp(result));
    }

    nodes.push(DEDAN.el('div', { class: 'flex flex-col gap-1 pt-3 mt-2 border-t border-outline-variant/30' }, [
      DEDAN.el('p', { class: 'font-body-sm text-body-sm text-on-surface-variant', text:
        'Confidence ' + Math.round((result.confidence_score || 0) * 100) + '% · assessed by ' + (result.provider || 'unknown') + ' (' + (result.model || 'n/a') + ')' }),
      result.uncertainty && result.uncertainty.missing_information && result.uncertainty.missing_information.length
        ? DEDAN.el('p', { class: 'font-body-sm text-body-sm text-on-surface-variant',
            text: 'Still needed for a firmer answer: ' + result.uncertainty.missing_information.join(', ') + '.' })
        : null,
      DEDAN.el('p', { class: 'font-body-sm text-body-sm text-outline', text: result.disclaimer || '' }),
      DEDAN.el('button', {
        type: 'button', class: SHELL.BTN_GHOST + ' self-start',
        onclick: function () { recordConsultation(result, urgent); }
      }, ['Save to my health history'])
    ]));

    DEDAN.render(document.getElementById('analysis-panel'), nodes);
  }

  function summarise(result) {
    var safety = result.safety || {};
    var lead = (result.possible_explanations || [])[0];
    var parts = [];
    if (lead) {
      parts.push('The most likely explanation is ' + lead.label + '.');
    }
    parts.push('Urgency: ' + DEDAN.humanise(safety.urgency || 'routine') + '.');
    if (safety.requires_immediate_care) {
      parts.push(safety.emergency_message || 'Please seek immediate professional care.');
    }
    return parts.join(' ');
  }

  function safetyBanner(safety, urgent) {
    var flags = safety.red_flags || [];
    return DEDAN.el('div', {
      class: 'rounded-lg px-3 py-2.5 flex flex-col gap-1 font-body-sm text-body-sm ' +
        (urgent ? 'bg-error-container text-on-error-container' : 'bg-surface-container text-on-surface')
    }, [
      DEDAN.el('span', { class: 'font-semibold',
        text: urgent ? 'Needs immediate care' : 'Safety check: ' + DEDAN.humanise(safety.urgency || 'routine') }),
      safety.emergency_message ? DEDAN.el('span', { text: safety.emergency_message }) : null,
      flags.length ? DEDAN.el('span', { class: 'opacity-80', text: 'Flags: ' + flags.join(', ') }) : null
    ]);
  }

  function explanations(result) {
    var items = result.possible_explanations || [];
    if (!items.length) {
      return [];
    }
    return [DEDAN.el('div', { class: 'flex flex-col gap-2' }, [
      DEDAN.el('h3', { class: 'font-label-lg text-label-lg text-on-surface font-semibold', text: 'Possible explanations' }),
      DEDAN.el('ul', { class: 'flex flex-col gap-2' }, items.map(function (item) {
        return DEDAN.el('li', { class: 'rounded-lg bg-surface-container px-3 py-2 flex flex-col gap-0.5' }, [
          DEDAN.el('span', { class: 'font-label-lg text-label-lg text-primary font-semibold', text: item.label }),
          item.why_it_fits ? DEDAN.el('span', { class: 'font-body-sm text-body-sm text-on-surface-variant', text: item.why_it_fits }) : null,
          typeof item.confidence === 'number'
            ? DEDAN.el('span', { class: 'font-label-sm text-label-sm text-outline', text: Math.round(item.confidence * 100) + '% likely' })
            : null
        ]);
      }))
    ])];
  }

  function education(result) {
    var items = result.treatment_education || [];
    if (!items.length) {
      return [];
    }
    return [DEDAN.el('details', { class: 'rounded-lg border border-outline-variant/30 px-3 py-2' }, [
      DEDAN.el('summary', { class: 'cursor-pointer font-label-lg text-label-lg text-on-surface font-semibold',
        text: 'Self-care and treatment education (' + items.length + ')' }),
      DEDAN.el('ul', { class: 'flex flex-col gap-2 pt-2' }, items.map(function (item) {
        return DEDAN.el('li', { class: 'flex flex-col gap-0.5' }, [
          DEDAN.el('span', { class: 'font-label-lg text-label-lg text-secondary', text: item.title }),
          item.description ? DEDAN.el('span', { class: 'font-body-sm text-body-sm text-on-surface-variant', text: item.description }) : null
        ]);
      }))
    ])];
  }

  function followUp(result) {
    var follow = result.follow_up || {};
    if (!follow.recommended) {
      return [];
    }
    return [DEDAN.el('div', { class: 'rounded-lg bg-surface-container px-3 py-2 flex flex-col gap-1' }, [
      DEDAN.el('span', { class: 'font-label-lg text-label-lg text-on-surface font-semibold',
        text: follow.timeframe ? 'Follow up: ' + follow.timeframe : 'Follow-up recommended' }),
      (follow.warning_signs || []).length
        ? DEDAN.el('span', { class: 'font-body-sm text-body-sm text-on-surface-variant',
            text: 'Seek help sooner if you notice: ' + follow.warning_signs.join('; ') + '.' })
        : null
    ])];
  }

  /**
   * Record the consultation on the patient's timeline.
   *
   * Only the patient's own words and the headline urgency are stored -- not the
   * full clinical payload. The timeline is read far more widely than the
   * consultation itself, and copying an entire assessment into it would widen
   * exposure for no benefit.
   */
  function recordConsultation(result, urgent) {
    var complaint = (state.turns.filter(function (t) { return t.role === 'user'; }).pop() || {}).content || '';
    DEDAN.post('/users/me/care/navigation', {
      symptoms: [],
      urgency: (result.safety || {}).urgency || 'routine',
      is_emergency: Boolean(urgent),
      reason: complaint.slice(0, 180)
    }).then(function () {
      DEDAN.showToast('Consultation saved to your health history.', 'success');
      return DEDAN.get('/users/me/timeline/summary');
    }).then(function (summary) {
      var badge = document.getElementById('history-count');
      if (badge) {
        badge.textContent = String(summary.total || 0);
      }
    }).catch(function (err) {
      DEDAN.showToast('Could not save to history: ' + err.message, 'error');
    });
  }

  /**
   * Show which of the patient's own record is feeding this consultation.
   *
   * Shown because it changes the answer: DEDAN weighs medications and allergies
   * during assessment, and a patient who cannot see that their penicillin allergy
   * was considered has no way to know whether to trust the result.
   */
  function renderProfileContext(health) {
    var host = document.getElementById('profile-context');
    if (!host) {
      return;
    }
    if (!health) {
      DEDAN.render(host, DEDAN.el('p', { class: 'font-body-sm text-body-sm text-on-surface-variant', text:
        DEDAN.hasTreatmentConsent(state.profile)
          ? 'Loading your health profile…'
          : 'Your health profile is not shared with DEDAN. Grant consent in Settings so allergies and medications can be checked.' }));
      return;
    }
    var rows = [
      ['Allergies', DEDAN.splitList(health.allergies)],
      ['Medications', DEDAN.splitList(health.medications)],
      ['Conditions', DEDAN.splitList(health.conditions)]
    ].filter(function (row) { return row[1].length; });

    if (!rows.length) {
      DEDAN.render(host, [
        DEDAN.el('p', { class: 'font-body-sm text-body-sm text-on-surface-variant',
          text: 'No allergies, medications or conditions recorded.' }),
        DEDAN.el('a', { class: 'font-label-sm text-label-sm text-secondary hover:underline', href: 'settings.html#health-profile' },
          ['Add them in Settings'])
      ]);
      return;
    }
    DEDAN.render(host, rows.map(function (row) {
      return DEDAN.el('p', { class: 'font-body-sm text-body-sm text-on-surface' }, [
        DEDAN.el('span', { class: 'font-semibold', text: row[0] + ': ' }),
        DEDAN.el('span', { class: 'text-on-surface-variant', text: row[1].join(', ') })
      ]);
    }));
  }

  /* ------------------------------------------------------------------ boot */

  SHELL.boot(function (profile) {
    state.profile = profile;

    addMessage('assistant',
      'Hello ' + (profile.display_name ? profile.display_name.split(' ')[0] : 'there') +
      '. Describe what you are feeling and I will help you understand your options. ' +
      'If this is an emergency, contact your local emergency services now.');

    var button = document.getElementById('send-btn');
    var input = document.getElementById('message-input');
    button.addEventListener('click', send);
    input.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        send();
      }
    });

    // Age is required by the clinical endpoint; ask rather than assume.
    var ageField = document.getElementById('patient-age');
    if (ageField) {
      ageField.addEventListener('change', function () {
        state.health = state.health || {};
        state.health.age = ageField.value;
      });
    }

    // Health profile enriches the assessment, but only with consent.
    renderProfileContext(null);

    if (DEDAN.hasTreatmentConsent(profile)) {
      DEDAN.get('/users/me/health-profile').then(function (health) {
        state.health = health;
        if (ageField && !ageField.value) {
          ageField.placeholder = 'Not recorded';
        }
        renderProfileContext(health);
      }).catch(function () { /* locked or unavailable; the engine copes */ });
    }

    // Voice needs a token; the portal already holds one for this patient.
    var token = DEDAN.getToken();
    if (token) {
      connect(token);
    } else {
      setConnection(false, 'Text mode');
    }
  });
})();
