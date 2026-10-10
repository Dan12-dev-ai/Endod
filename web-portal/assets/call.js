/*
 * Live consultation media stage + workspace interactions.
 *
 * The consultation *content* (transcript, assessment, session) belongs to
 * consult.js; everything here is the presentation layer on top of it:
 *
 *  - Avatar feed: a Canvas 2D scene (the AI companion "video") driven by an
 *    rAF loop, optionally audio-reactive when the microphone is live.
 *  - WebRTC: a loopback RTCPeerConnection pair carries the canvas feed
 *    through encode -> transport -> decode -> render into the stage's <video>,
 *    which is what the viewport shows when the pipeline is available. There is
 *    no signalling endpoint for a real remote peer yet, so the loopback stands
 *    in for one: swapping `startWebRTCLoopback` for an offer/answer exchange
 *    against the care peer is the only change a real deployment needs. Every
 *    failure path is silent and falls back to the canvas feed, so a browser
 *    without WebRTC simply never shows the video layer.
 *  - Camera/microphone: getUserMedia powers the picture-in-picture preview and
 *    the Web Audio AnalyserNode waveform. Nothing is requested on load -- the
 *    Permissions API is asked first, and only an already-granted camera
 *    auto-starts, so no patient is hit with a permission prompt on arrival.
 *  - Web Speech: SpeechRecognition dictates into the message field and
 *    SpeechSynthesis reads DEDAN's replies when the speaker toggle is on
 *    (off by default -- audio must be opted into, never imposed).
 *
 * Everything is feature-detected and wrapped: this page must stay usable in a
 * headless browser, in a hospital kiosk without media devices, and offline.
 */
(function () {
  'use strict';

  var DEDAN = window.DEDAN;
  var ICONS = window.DEDAN_ICONS;

  /* ------------------------------------------------------------- helpers */

  function $(id) {
    return document.getElementById(id);
  }

  function noop() {}

  function toast(message, kind) {
    if (DEDAN && DEDAN.showToast) {
      DEDAN.showToast(message, kind || 'info');
    }
  }

  /* Swap an icon span's glyph. icons.js hydrates spans into <svg> at load,
     so updating textContent afterwards would do nothing. */
  function setIcon(span, name) {
    if (!span || !ICONS || !ICONS.build) {
      return;
    }
    var svg = ICONS.build(name);
    if (!svg) {
      return;
    }
    svg.setAttribute('class', span.getAttribute('class') || '');
    svg.setAttribute('aria-hidden', 'true');
    if (span.firstChild) {
      span.replaceChild(svg, span.firstChild);
    } else {
      span.appendChild(svg);
    }
    span.dataset.dedanIconDone = '1';
  }

  function iconIn(button, name) {
    if (!button) {
      return;
    }
    setIcon(button.querySelector('.material-symbols-outlined'), name);
  }

  function stopTracks(stream) {
    if (!stream) {
      return;
    }
    try {
      stream.getTracks().forEach(function (track) { track.stop(); });
    } catch (err) { /* nothing to do */ }
  }

  var reduceMotion = !!(window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches);

  /* ------------------------------------------------------- session timer */

  var timerEl = $('call-timer');
  var elapsed = 0;
  var timerId = null;

  function clock(seconds) {
    function pad(n) { return (n < 10 ? '0' : '') + n; }
    var h = Math.floor(seconds / 3600);
    var m = Math.floor((seconds % 3600) / 60);
    var s = seconds % 60;
    return pad(h) + ':' + pad(m) + ':' + pad(s);
  }

  function paintClock() {
    if (timerEl) {
      timerEl.textContent = clock(elapsed);
    }
    var ended = $('end-duration');
    if (ended) {
      ended.textContent = clock(elapsed);
    }
  }

  function startTimer() {
    if (timerId !== null) {
      return;
    }
    timerId = globalThis.setInterval(function () {
      elapsed += 1;
      paintClock();
    }, 1000);
  }

  function stopTimer() {
    if (timerId !== null) {
      globalThis.clearInterval(timerId);
      timerId = null;
    }
  }

  /* ------------------------------------------------ avatar canvas feed */

  var stage = $('video-stage');
  var canvas = $('avatar-canvas');
  var remote = $('remote-video');
  var ctx = canvas ? canvas.getContext('2d') : null;
  var audioLevel = 0.12;
  // 'idle' | 'user' | 'ai' — the orb's current behavioural state, recomputed
  // each frame in drawAvatar from real signals (mic level, speech synthesis).
  var orbState = 'idle';
  var peers = null; /* { pc1, pc2 } for the WebRTC loopback */

  function fitCanvas() {
    if (!canvas) {
      return 0;
    }
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    var w = canvas.clientWidth;
    var h = canvas.clientHeight;
    if (!w || !h) {
      return 0;
    }
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
    }
    return dpr;
  }
  function drawAvatar(t) {
    if (!ctx) {
      return;
    }
    var dpr = fitCanvas();
    if (!dpr) {
      return;
    }
    var w = canvas.width / dpr;
    var h = canvas.height / dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    /* ambient backdrop */
    var bg = ctx.createRadialGradient(w * 0.24, h * 0.16, 0, w * 0.24, h * 0.16, Math.max(w, h));
    bg.addColorStop(0, '#12303f');
    bg.addColorStop(0.55, '#0a1d29');
    bg.addColorStop(1, '#06121b');
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, w, h);

    /*
     * Behavioural state, read from real signals rather than faked:
     *   user  microphone live + the patient is talking -> outward ripple
     *   ai    DEDAN's synthesised voice is playing     -> orbiting particle ring
     *   idle  neither                                   -> slow breathing glow
     */
    var userActive = Boolean(analyser) && audioLevel > 0.3;
    var aiActive = !userActive && Boolean(window.speechSynthesis && window.speechSynthesis.speaking);
    orbState = userActive ? 'user' : (aiActive ? 'ai' : 'idle');

    var cx = w * 0.5;
    var cy = h * 0.46;
    var base = Math.min(w, h) * 0.18;

    // Idle breathes slowly and drifts; the active states breathe faster and sit
    // a little larger. `energy` is what the pulse, bloom and rim all key off.
    var breath = Math.sin(t * (aiActive ? 0.0042 : userActive ? 0.003 : 0.0016));
    var drift = Math.sin(t * 0.0011) * base * 0.05;
    var energy = aiActive ? 0.55 + audioLevel * 0.35
      : userActive ? 0.3 + audioLevel * 0.6
        : 0.07 + audioLevel * 0.12;
    var pulse = base * (1 + energy * 0.45 + breath * (aiActive ? 0.07 : 0.04));
    cy += drift;

    /* outer aura — a soft bloom that swells with energy */
    var aura = ctx.createRadialGradient(cx, cy, pulse * 0.6, cx, cy, pulse * 2.1);
    aura.addColorStop(0, 'rgba(45, 212, 191, ' + (0.2 + energy * 0.26) + ')');
    aura.addColorStop(0.5, 'rgba(56, 189, 248, ' + (0.08 + energy * 0.12) + ')');
    aura.addColorStop(1, 'rgba(79, 70, 229, 0)');
    ctx.beginPath();
    ctx.fillStyle = aura;
    ctx.arc(cx, cy, pulse * 2.1, 0, Math.PI * 2);
    ctx.fill();

    /* user-speaking ripple: rings expand outward and fade */
    if (userActive) {
      for (var ripple = 0; ripple < 3; ripple += 1) {
        var phase = ((t * 0.0009) + ripple / 3) % 1;
        ctx.beginPath();
        ctx.strokeStyle = 'rgba(103, 232, 249, ' + (0.4 * (1 - phase)) + ')';
        ctx.lineWidth = 1.6 * (1 - phase) + 0.4;
        ctx.arc(cx, cy, pulse * (1.15 + phase * 1.25), 0, Math.PI * 2);
        ctx.stroke();
      }
    }

    /* orbital particle ring — spins up and densifies while DEDAN speaks */
    var ringR = pulse * 1.5;
    var spin = t * (aiActive ? 0.0016 : 0.0004);
    var dots = aiActive ? 14 : 7;
    for (var dot = 0; dot < dots; dot += 1) {
      var angle = spin * (1 + (dot % 3) * 0.18) + (dot * Math.PI * 2) / dots;
      var dist = ringR + Math.sin(t * 0.001 + dot) * base * 0.05;
      var dx = cx + Math.cos(angle) * dist;
      var dy = cy + Math.sin(angle) * dist * 0.62;
      ctx.beginPath();
      ctx.fillStyle = 'rgba(167, 243, 208, ' +
        (0.2 + 0.5 * Math.abs(Math.sin(t * 0.002 + dot))) + ')';
      ctx.arc(dx, dy, 1.4 + (dot % 3) * 0.5, 0, Math.PI * 2);
      ctx.fill();
    }

    /* the sphere — a fluid radial blend of emerald-400 -> teal-500 ->
       cyan-400 -> indigo-600, glossy and pulsating with the voice state */
    var sphere = ctx.createRadialGradient(
      cx - pulse * 0.32, cy - pulse * 0.36, pulse * 0.08,
      cx, cy, pulse * 1.05
    );
    sphere.addColorStop(0, 'rgba(209, 250, 229, ' + (0.95 + energy * 0.05) + ')');   // pale emerald highlight
    sphere.addColorStop(0.22, 'rgba(52, 211, 153, 0.96)');                            // emerald-400
    sphere.addColorStop(0.5, 'rgba(20, 184, 166, 0.94)');                             // teal-500
    sphere.addColorStop(0.74, 'rgba(34, 211, 238, 0.9)');                             // cyan-400
    sphere.addColorStop(1, 'rgba(79, 70, 229, 0.82)');                                // indigo-600
    ctx.beginPath();
    ctx.fillStyle = sphere;
    ctx.arc(cx, cy, pulse, 0, Math.PI * 2);
    ctx.fill();

    // rim light that tightens and brightens with energy, giving the sphere its
    // 3D edge against the dark stage
    ctx.beginPath();
    ctx.strokeStyle = 'rgba(167, 243, 208, ' + (0.35 + energy * 0.4) + ')';
    ctx.lineWidth = 1.2 + energy * 0.8;
    ctx.arc(cx, cy, pulse, 0, Math.PI * 2);
    ctx.stroke();

    // specular glint — sells the "orb" as a lit body rather than a flat disc
    ctx.beginPath();
    var glint = ctx.createRadialGradient(
      cx - pulse * 0.34, cy - pulse * 0.4, 0,
      cx - pulse * 0.34, cy - pulse * 0.4, pulse * 0.5
    );
    glint.addColorStop(0, 'rgba(255, 255, 255, ' + (0.5 + energy * 0.2) + ')');
    glint.addColorStop(1, 'rgba(255, 255, 255, 0)');
    ctx.fillStyle = glint;
    ctx.arc(cx - pulse * 0.34, cy - pulse * 0.4, pulse * 0.5, 0, Math.PI * 2);
    ctx.fill();
  }

  /* ---------------------------------------------------- audio waveform */

  var wave = $('waveform');
  var wctx = wave ? wave.getContext('2d') : null;
  var analyser = null;
  var waveData = null;

  function drawWave(t) {
    if (!wave || !wctx) {
      return;
    }
    var w = 128;
    var h = 32;
    wctx.clearRect(0, 0, w, h);
    var bars = 22;
    var gap = 2.4;
    var bw = (w - gap * (bars - 1)) / bars;
    var live = Boolean(analyser);
    wctx.fillStyle = live ? 'rgba(110, 231, 183, 0.95)' : 'rgba(255, 255, 255, 0.4)';
    var level = 0;
    for (var i = 0; i < bars; i += 1) {
      var v;
      if (live && waveData) {
        analyser.getByteTimeDomainData(waveData);
        var sample = waveData[Math.floor((i / bars) * waveData.length)] / 128 - 1;
        v = Math.min(1, Math.abs(sample) * 3);
        level = Math.max(level, Math.abs(sample));
      } else {
        v = 0.18 + 0.14 * (Math.sin(t * 0.004 + i * 0.55) + 1);
      }
      var barH = Math.max(2, v * h);
      wctx.fillRect(i * (bw + gap), (h - barH) / 2, bw, barH);
    }
    if (live) {
      audioLevel = 0.1 + level * 1.6;
    } else {
      audioLevel = 0.1 + 0.05 * (Math.sin(t * 0.002) + 1);
    }
  }

  /* -------------------------------------------------------- frame loop */

  function frame(t) {
    drawAvatar(t);
    drawWave(t);
    globalThis.requestAnimationFrame(frame);
  }

  if (ctx || wctx) {
    if (reduceMotion) {
      drawAvatar(0);
      drawWave(0);
    } else {
      globalThis.requestAnimationFrame(frame);
    }
  }
  /* --------------------------------------------- WebRTC (loopback peer) */

  /*
   * The viewport's <video> is the WebRTC-received leg of the avatar feed.
   * A real deployment replaces this with an offer/answer exchange against the
   * care peer; until that endpoint exists the loopback keeps the whole
   * capture -> encode -> transport -> decode -> render path real and visible.
   * Any failure leaves the canvas feed in place and the page stays usable.
   */
  function startWebRTCLoopback() {
    if (!window.RTCPeerConnection || !canvas || !canvas.captureStream || !remote) {
      return;
    }
    try {
      var stream = canvas.captureStream(24);
      var pc1 = new RTCPeerConnection({ iceServers: [] });
      var pc2 = new RTCPeerConnection({ iceServers: [] });
      stream.getTracks().forEach(function (track) {
        try { pc1.addTrack(track, stream); } catch (err) { noop(); }
      });
      pc1.onicecandidate = function (event) {
        if (event.candidate && pc2.addIceCandidate) {
          pc2.addIceCandidate(event.candidate).catch(noop);
        }
      };
      pc2.onicecandidate = function (event) {
        if (event.candidate && pc1.addIceCandidate) {
          pc1.addIceCandidate(event.candidate).catch(noop);
        }
      };
      pc2.ontrack = function (event) {
        if (!remote.srcObject) {
          if (window.MediaStream && event.track) {
            remote.srcObject = new window.MediaStream([event.track]);
          } else {
            remote.srcObject = event.streams[0];
          }
        }
        remote.play().catch(noop);
      };
      remote.addEventListener('playing', function () {
        remote.classList.add('is-live');
      }, { once: true });
      pc1.createOffer()
        .then(function (offer) { return pc1.setLocalDescription(offer); })
        .then(function () { return pc2.setRemoteDescription(pc1.localDescription); })
        .then(function () { return pc2.createAnswer(); })
        .then(function (answer) { return pc2.setLocalDescription(answer); })
        .then(function () { return pc1.setRemoteDescription(pc2.localDescription); })
        .catch(noop);
      peers = { pc1: pc1, pc2: pc2 };
    } catch (err) {
      /* no WebRTC here: the canvas feed stays visible, the page is fine */
    }
  }

  function stopWebRTCLoopback() {
    if (!peers) {
      return;
    }
    try {
      peers.pc1.close();
      peers.pc2.close();
    } catch (err) { noop(); }
    peers = null;
    if (remote) {
      remote.classList.remove('is-live');
    }
  }

  /* ----------------------------------------------------- local media */

  var micBtn = $('btn-mic');
  var camBtn = $('btn-camera');
  var pipVideo = $('pip-video');
  var micStream = null;
  var camStream = null;
  var micOn = false;
  var camOn = false;
  var audioCtx = null;

  function hasMedia() {
    return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  }

  function ensureAudioContext() {
    if (!audioCtx && window.AudioContext) {
      try {
        audioCtx = new window.AudioContext();
      } catch (err) {
        audioCtx = null;
      }
    }
    if (audioCtx && audioCtx.state === 'suspended') {
      audioCtx.resume().catch(noop);
    }
    return audioCtx;
  }

  function attachAnalyser(stream) {
    var actx = ensureAudioContext();
    if (!actx) {
      return;
    }
    try {
      var source = actx.createMediaStreamSource(stream);
      analyser = actx.createAnalyser();
      analyser.fftSize = 128;
      waveData = new Uint8Array(analyser.fftSize);
      source.connect(analyser);
    } catch (err) {
      analyser = null;
    }
  }

  function setMicState(on) {
    micOn = on;
    if (micBtn) {
      micBtn.classList.toggle('is-alert', !on);
      micBtn.setAttribute('aria-pressed', on ? 'true' : 'false');
      micBtn.setAttribute('aria-label', on ? 'Mute microphone' : 'Unmute microphone');
    }
  }

  function enableMic(on) {
    if (on) {
      if (!hasMedia()) {
        toast('This browser cannot access the microphone. DEDAN will continue in text mode.', 'warn');
        return;
      }
      navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
        micStream = stream;
        attachAnalyser(stream);
        setMicState(true);
      }).catch(function () {
        toast('Microphone access was denied. You can continue describing symptoms in writing.', 'warn');
        setMicState(false);
      });
      return;
    }
    stopTracks(micStream);
    micStream = null;
    analyser = null;
    waveData = null;
    setMicState(false);
  }

  function setCamState(on) {
    camOn = on;
    if (camBtn) {
      camBtn.classList.toggle('is-alert', !on);
      camBtn.setAttribute('aria-pressed', on ? 'true' : 'false');
      camBtn.setAttribute('aria-label', on ? 'Turn camera off' : 'Turn camera on');
    }
  }

  function enableCamera(on) {
    if (on) {
      if (!hasMedia()) {
        toast('This browser cannot access the camera.', 'warn');
        return;
      }
      navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' } }).then(function (stream) {
        camStream = stream;
        if (pipVideo) {
          pipVideo.srcObject = stream;
          pipVideo.classList.add('is-on');
          pipVideo.play().catch(noop);
        }
        setCamState(true);
      }).catch(function () {
        toast('Camera access was denied. The consultation continues without your video.', 'warn');
        setCamState(false);
      });
      return;
    }
    stopTracks(camStream);
    camStream = null;
    if (pipVideo) {
      pipVideo.classList.remove('is-on');
      pipVideo.srcObject = null;
    }
    setCamState(false);
  }

  /*
   * Ask the Permissions API what the camera situation already is; only an
   * already-granted camera auto-starts, so opening the page never throws a
   * permission prompt at a patient who has not asked for one.
   */
  function autoStartMedia() {
    if (!hasMedia()) {
      return;
    }
    if (navigator.permissions && navigator.permissions.query) {
      navigator.permissions.query({ name: 'camera' }).then(function (status) {
        if (status && status.state === 'granted') {
          enableCamera(true);
          enableMic(true);
        }
      }).catch(noop);
    }
  }

  /* --------------------------------------------------- control bar */

  function toggleFullscreen() {
    if (!stage) {
      return;
    }
    try {
      if (document.fullscreenElement) {
        document.exitFullscreen().catch(noop);
        return;
      }
      if (stage.requestFullscreen) {
        stage.requestFullscreen().catch(function () {
          toast('Fullscreen is not available in this browser.', 'info');
        });
      }
    } catch (err) {
      toast('Fullscreen is not available in this browser.', 'info');
    }
  }

  var speakerBtn = $('btn-speaker');
  var transcriptBtn = $('btn-transcript');
  var transcriptCard = $('transcript-card');
  var endOverlay = $('end-overlay');
  var speakerOn = false;

  function setSpeaker(on) {
    speakerOn = on;
    if (speakerBtn) {
      speakerBtn.classList.toggle('is-on', on);
      speakerBtn.setAttribute('aria-pressed', on ? 'true' : 'false');
      speakerBtn.setAttribute('aria-label', on ? 'Disable AI voice output' : 'Enable AI voice output');
    }
    if (!on && window.speechSynthesis) {
      try { window.speechSynthesis.cancel(); } catch (err) { noop(); }
    }
  }

  function setTranscript(visible) {
    if (!transcriptCard || !transcriptBtn) {
      return;
    }
    transcriptCard.hidden = !visible;
    transcriptBtn.classList.toggle('is-on', visible);
    transcriptBtn.setAttribute('aria-pressed', visible ? 'true' : 'false');
    transcriptBtn.setAttribute('aria-label', visible ? 'Hide transcript panel' : 'Show transcript panel');
  }

  function endConsultation() {
    stopTimer();
    stopWebRTCLoopback();
    stopTracks(micStream);
    micStream = null;
    analyser = null;
    waveData = null;
    setMicState(false);
    stopTracks(camStream);
    camStream = null;
    if (pipVideo) {
      pipVideo.classList.remove('is-on');
      pipVideo.srcObject = null;
    }
    setCamState(false);
    setSpeaker(false);
    stopDictation();
    if (endOverlay) {
      endOverlay.hidden = false;
    }
  }

  function rejoinConsultation() {
    if (endOverlay) {
      endOverlay.hidden = true;
    }
    elapsed = 0;
    paintClock();
    startTimer();
    startWebRTCLoopback();
    autoStartMedia();
  }

  function wireControls() {
    var mic = $('btn-mic');
    if (mic) {
      mic.addEventListener('click', function () { enableMic(!micOn); });
    }
    var cam = $('btn-camera');
    if (cam) {
      cam.addEventListener('click', function () { enableCamera(!camOn); });
    }
    if (speakerBtn) {
      speakerBtn.addEventListener('click', function () { setSpeaker(!speakerOn); });
    }
    if (transcriptBtn) {
      transcriptBtn.addEventListener('click', function () { setTranscript(transcriptCard ? transcriptCard.hidden : true); });
    }
    var endBtn = $('btn-end');
    if (endBtn) {
      endBtn.addEventListener('click', endConsultation);
    }
    var rejoin = $('btn-rejoin');
    if (rejoin) {
      rejoin.addEventListener('click', rejoinConsultation);
    }
    var fs = $('btn-fullscreen');
    if (fs) {
      fs.addEventListener('click', toggleFullscreen);
    }
    var attach = $('btn-attach');
    if (attach) {
      attach.addEventListener('click', function () {
        toast('Document sharing is not enabled yet. Describe what the document shows, or add it in Settings.', 'info');
      });
    }
    var followup = $('quick-followup');
    var input = $('message-input');
    if (followup && input) {
      followup.addEventListener('click', function () {
        input.focus();
        input.scrollIntoView({ block: 'center', behavior: reduceMotion ? 'auto' : 'smooth' });
      });
    }
  }
  /* --------------------------------------------------------- popovers */

  function popover(buttonId, panelId) {
    var button = $(buttonId);
    var panel = $(panelId);
    if (!button || !panel) {
      return;
    }
    function close() {
      panel.hidden = true;
      button.setAttribute('aria-expanded', 'false');
      button.classList.remove('is-open');
    }
    button.addEventListener('click', function (event) {
      event.stopPropagation();
      var open = panel.hidden;
      panel.hidden = !open;
      button.setAttribute('aria-expanded', open ? 'true' : 'false');
      button.classList.toggle('is-open', open);
    });
    panel.addEventListener('click', function (event) { event.stopPropagation(); });
    document.addEventListener('click', function (event) {
      if (!panel.hidden && !panel.contains(event.target) && event.target !== button) {
        close();
      }
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && !panel.hidden) {
        close();
        button.focus();
      }
    });
  }

  var EMOJIS = ['😊', '😟', '😣', '😰', '🤒', '🤕', '🤢', '😴'];

  function buildEmojiPanel() {
    var panel = $('emoji-panel');
    var button = $('btn-emoji');
    var input = $('message-input');
    if (!panel || !button || !input || !DEDAN.el) {
      return;
    }
    EMOJIS.forEach(function (glyph) {
      var item = DEDAN.el('button', {
        class: 'ld-emoji-btn',
        type: 'button',
        text: glyph,
        'aria-label': 'Insert ' + glyph
      });
      item.addEventListener('click', function (event) {
        event.stopPropagation();
        var caret = input.selectionStart || input.value.length;
        input.value = input.value.slice(0, caret) + glyph + input.value.slice(caret);
        input.focus();
        input.selectionStart = input.selectionEnd = caret + glyph.length;
        autoGrow(input);
        panel.hidden = true;
        button.setAttribute('aria-expanded', 'false');
      });
      panel.appendChild(item);
    });
  }

  function autoGrow(input) {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 96) + 'px';
  }

  /* -------------------------------------------- Web Speech: dictation */

  var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  var recognition = null;
  var dictateBtn = $('btn-dictate');

  function stopDictation() {
    if (recognition) {
      try { recognition.stop(); } catch (err) { noop(); }
    }
  }

  function startDictation() {
    var input = $('message-input');
    if (!input || !SpeechRecognition) {
      toast('Voice dictation is not supported in this browser.', 'warn');
      return;
    }
    stopDictation();
    recognition = new SpeechRecognition();
    recognition.lang = document.documentElement.lang || 'en-US';
    recognition.interimResults = true;
    recognition.continuous = false;
    var finalText = '';
    recognition.onresult = function (event) {
      var interim = '';
      for (var i = event.resultIndex; i < event.results.length; i += 1) {
        var transcript = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          finalText += transcript;
        } else {
          interim += transcript;
        }
      }
      if (finalText || interim) {
        input.value = (finalText + interim).trim();
        autoGrow(input);
      }
    };
    recognition.onerror = function (event) {
      var reason = (event && event.error) || '';
      if (reason === 'not-allowed' || reason === 'service-not-allowed') {
        toast('Microphone access for dictation was denied.', 'warn');
      } else if (reason && reason !== 'aborted' && reason !== 'no-speech') {
        toast('Dictation stopped (' + reason + ').', 'warn');
      }
    };
    recognition.onend = function () {
      recognition = null;
      if (dictateBtn) {
        dictateBtn.classList.remove('is-on');
        dictateBtn.setAttribute('aria-pressed', 'false');
      }
    };
    try {
      recognition.start();
      if (dictateBtn) {
        dictateBtn.classList.add('is-on');
        dictateBtn.setAttribute('aria-pressed', 'true');
      }
    } catch (err) {
      recognition = null;
      toast('Dictation could not start in this browser.', 'warn');
    }
  }

  /* ---------------------------------------- Web Speech: AI voice output */

  /*
   * New assistant messages are spoken only when the patient turned the
   * speaker toggle on. The listener observes the transcript that consult.js
   * renders, so voice stays a pure presentation concern: no coupling to the
   * clinical engine, and nothing is spoken by default.
   */
  function watchForSpeech() {
    var list = $('message-list');
    if (!list || !window.MutationObserver) {
      return;
    }
    new MutationObserver(function (records) {
      if (!speakerOn || !window.speechSynthesis) {
        return;
      }
      records.forEach(function (record) {
        Array.prototype.forEach.call(record.addedNodes, function (node) {
          if (!node || node.nodeType !== 1) {
            return;
          }
          var name = node.querySelector('.font-semibold');
          if (!name || name.textContent.trim() !== 'DEDAN') {
            return;
          }
          var line = node.querySelector('p');
          var text = line ? line.textContent.trim() : '';
          if (!text) {
            return;
          }
          try {
            window.speechSynthesis.cancel();
            var utterance = new SpeechSynthesisUtterance(text);
            window.speechSynthesis.speak(utterance);
          } catch (err) { noop(); }
        });
      });
    }).observe(list, { childList: true });
  }

  /* ------------------------------------------- session details metrics */

  function truncate(text, limit) {
    return text.length > limit ? text.slice(0, limit - 1) + '…' : text;
  }

  var NUMBER_WORDS = { one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10 };

  function captureSymptom() {
    var input = $('message-input');
    var symptoms = $('metric-symptoms');
    var duration = $('metric-duration');
    if (!input || !symptoms) {
      return;
    }
    var text = input.value.trim().replace(/\s+/g, ' ');
    if (!text) {
      return;
    }
    symptoms.textContent = truncate(text, 70);
    if (duration) {
      /* accepts digits ("2 days") and spelled-out numbers ("two days") */
      var span = text.match(/(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s*(hour|day|week)s?\b/i);
      duration.textContent = span
        ? (span[1].match(/^\d+$/) ? span[1] : String(NUMBER_WORDS[span[1].toLowerCase()])) +
          ' ' + span[2].toLowerCase() + (span[1] === '1' ? '' : 's')
        : 'Not specified';
    }
  }

  /*
   * Severity and safety mirror what the assessment actually concluded. The
   * panel is rendered by consult.js, so the panel's own text is the source of
   * truth here -- duplicating the engine's classification logic would be.
   */
  function watchAssessment() {
    var panel = $('analysis-panel');
    var severity = $('metric-severity');
    var safety = $('metric-safety');
    if (!panel || !severity || !window.MutationObserver) {
      return;
    }
    function sync() {
      var text = panel.textContent || '';
      var urgent = /needs immediate care/i.test(text);
      var check = text.match(/Safety check:\s*([A-Za-z]+)/);
      severity.textContent = urgent
        ? 'High'
        : (check ? check[1].charAt(0).toUpperCase() + check[1].slice(1).toLowerCase() : '—');
      if (safety) {
        safety.textContent = urgent
          ? 'Needs immediate care'
          : (/Safety check/i.test(text) ? 'Stable' : '—');
      }
    }
    new MutationObserver(sync).observe(panel, { childList: true, subtree: true });
  }

  /* ------------------------------------------------------------- boot */

  wireControls();
  popover('btn-notifications', 'notif-panel');
  popover('btn-user-menu', 'user-menu');
  popover('btn-emoji', 'emoji-panel');
  buildEmojiPanel();

  var inputEl = $('message-input');
  if (inputEl) {
    inputEl.addEventListener('input', function () { autoGrow(inputEl); });
    /*
     * Registered before consult.js wires its own listener (that happens on
     * shell boot, later), so the metric is captured from the text the patient
     * actually submitted, before the field is cleared.
     */
    inputEl.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' && !event.shiftKey) {
        captureSymptom();
      }
    });
    autoGrow(inputEl);
  }

  var sendBtn = $('send-btn');
  if (sendBtn) {
    sendBtn.addEventListener('click', captureSymptom);
  }

  var dictate = $('btn-dictate');
  if (dictate) {
    dictate.addEventListener('click', function () {
      if (recognition) {
        stopDictation();
      } else {
        startDictation();
      }
    });
  }

  watchForSpeech();
  watchAssessment();

  paintClock();
  startTimer();
  startWebRTCLoopback();
  autoStartMedia();
})();