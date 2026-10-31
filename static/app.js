/* Midnight Stranger radio page.
   Talks only to this server (same origin). Static is synthesised with WebAudio, so no audio files are needed. */
(() => {
  'use strict';

  const MIN_F = 87.5;          // dial range, a little wider than the stations so the ends are not cramped
  const MAX_F = 108.5;
  const SETTLE_MS = 450;       // let the dial rest before taking an episode (taking one marks it played)
  const POLL_MS = 6000;
  const WAIT_RETRY_MS = 8000;

  const $ = (id) => document.getElementById(id);
  const el = {
    power: $('power'), powerBtn: $('power-btn'), radio: $('radio'), dial: $('dial'),
    pill: $('pill'), pillText: $('pill-text'),
    freq: $('freq'), name: $('station-name'), tagline: $('station-tagline'),
    scale: $('scale'), needle: $('needle'), presets: $('presets'),
    replay: $('replay-tag'), title: $('title'), caption: $('caption'),
    play: $('play'), bar: $('bar'), time: $('time'), volume: $('volume'),
    status: $('status-line'), player: $('player'),
  };

  const store = {
    get(key) { try { return localStorage.getItem(key); } catch { return null; } },
    set(key, value) { try { localStorage.setItem(key, value); } catch { /* private mode: fine */ } },
  };

  const state = {
    stations: [], target: 2, current: null,
    segments: [], duration: 0, lastSeg: -2,
    token: 0, settleTimer: 0, retryTimer: 0, pollTimer: 0, raf: 0,
    powered: false, dragging: false, playingEpisode: false,
    volume: Number(store.get('ms.volume')) || 0.9,
  };

  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const pct = (f) => ((f - MIN_F) / (MAX_F - MIN_F)) * 100;
  const fmtTime = (s) => {
    s = Math.max(0, Math.floor(s || 0));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  };
  const make = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  /* ---------------- static (WebAudio) ---------------- */
  const sfx = {
    ctx: null, noise: null, master: null, hiss: null,
    init() {
      if (this.ctx) return;
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      try {
        this.ctx = new AC();
        const len = this.ctx.sampleRate * 2;
        const buf = this.ctx.createBuffer(1, len, this.ctx.sampleRate);
        const data = buf.getChannelData(0);
        for (let i = 0; i < len; i++) data[i] = Math.random() * 2 - 1;
        this.noise = buf;
        this.master = this.ctx.createGain();
        this.master.gain.value = state.volume;
        this.master.connect(this.ctx.destination);
      } catch { this.ctx = null; }
    },
    resume() { if (this.ctx && this.ctx.state === 'suspended') this.ctx.resume().catch(() => {}); },
    setVolume(v) { if (this.master) this.master.gain.value = v; },
    source(loop) {
      const src = this.ctx.createBufferSource();
      src.buffer = this.noise; src.loop = loop;
      const bp = this.ctx.createBiquadFilter();
      bp.type = 'bandpass'; bp.Q.value = 0.6;
      const gain = this.ctx.createGain();
      gain.gain.value = 0;
      src.connect(bp); bp.connect(gain); gain.connect(this.master);
      return { src, bp, gain };
    },
    burst(ms = 900, peak = 0.3) {
      if (!this.ctx) return;
      this.resume();
      const t = this.ctx.currentTime;
      const { src, bp, gain } = this.source(false);
      bp.frequency.setValueAtTime(1200 + Math.random() * 800, t);
      bp.frequency.exponentialRampToValueAtTime(3800, t + ms / 1000);
      gain.gain.setValueAtTime(0.0001, t);
      gain.gain.linearRampToValueAtTime(peak, t + 0.03);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + ms / 1000);
      src.start(t, Math.random());
      src.stop(t + ms / 1000 + 0.05);
    },
    startHiss(level = 0.045) {
      if (!this.ctx || this.hiss) return;
      this.resume();
      const t = this.ctx.currentTime;
      const h = this.source(true);
      h.bp.frequency.value = 2200;
      h.gain.gain.setValueAtTime(0.0001, t);
      h.gain.gain.linearRampToValueAtTime(level, t + 0.4);
      h.src.start(t, Math.random());
      this.hiss = h;
    },
    stopHiss(fadeMs = 500) {
      const h = this.hiss;
      if (!h) return;
      this.hiss = null;
      const t = this.ctx.currentTime;
      h.gain.gain.cancelScheduledValues(t);
      h.gain.gain.setValueAtTime(h.gain.gain.value, t);
      h.gain.gain.linearRampToValueAtTime(0.0001, t + fadeMs / 1000);
      h.src.stop(t + fadeMs / 1000 + 0.05);
    },
  };

  /* Browsers only let a page play sound after a tap. Playing a silent clip on the power button
     unlocks the audio element so later, automatic plays (next story) are allowed. */
  function silentWavUrl() {
    const rate = 8000, n = 800;
    const buf = new ArrayBuffer(44 + n * 2), v = new DataView(buf);
    const text = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
    text(0, 'RIFF'); v.setUint32(4, 36 + n * 2, true); text(8, 'WAVE'); text(12, 'fmt ');
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
    text(36, 'data'); v.setUint32(40, n * 2, true);
    return URL.createObjectURL(new Blob([buf], { type: 'audio/wav' }));
  }
  async function unlockPlayer() {
    try {
      el.player.muted = true;
      el.player.src = silentWavUrl();
      await el.player.play();
      el.player.pause();
    } catch { /* not fatal: the play button still works */ }
    el.player.muted = false;
    el.player.removeAttribute('src');
    el.player.load();
  }

  /* ---------------- dial ---------------- */
  function buildScale() {
    const frag = document.createDocumentFragment();
    for (let n = 176; n <= 216; n++) {            // half-MHz steps, 88.0 to 108.0
      const f = n / 2;
      const major = n % 8 === 0, mid = n % 2 === 0;
      const tick = make('i', 'tick' + (major ? ' major' : mid ? ' mid' : ''));
      tick.style.left = pct(f) + '%';
      frag.appendChild(tick);
      if (major) {
        const label = make('span', 'tick-label', String(f));
        label.style.left = pct(f) + '%';
        frag.appendChild(label);
      }
    }
    for (const s of state.stations) {
      const notch = make('i', 'notch');
      notch.style.left = pct(Number(s.freq)) + '%';
      frag.appendChild(notch);
    }
    el.scale.insertBefore(frag, el.needle);
  }

  function buildPresets() {
    el.presets.textContent = '';
    for (const s of state.stations) {
      const key = make('button', 'preset');
      key.type = 'button';
      key.dataset.freq = s.freq;
      key.dataset.station = s.freq;
      key.setAttribute('aria-pressed', 'false');
      key.setAttribute('aria-label', `${s.freq} FM, ${s.name}`);
      const ready = make('span', 'preset-ready');
      ready.append(make('span', 'ready-text', ''));
      key.append(make('span', 'preset-freq', s.freq), make('span', 'preset-name', s.name), ready);
      key.addEventListener('click', () => { if (state.current && state.current.freq === s.freq && state.powered) return; tune(s); });
      el.presets.appendChild(key);
    }
  }

  function updateReady() {
    for (const key of el.presets.children) {
      const s = state.stations.find((x) => x.freq === key.dataset.freq);
      if (!s) continue;
      const box = key.querySelector('.preset-ready');
      box.textContent = '';
      const slots = clamp(Math.max(state.target, s.queued), 1, 6);
      for (let i = 0; i < slots; i++) box.appendChild(make('span', 'ready-dot' + (i < s.queued ? ' on' : '')));
      box.appendChild(make('span', 'ready-text', s.queued === 1 ? '1 ready' : `${s.queued} ready`));
    }
  }

  function showStation(s) {
    state.current = s;
    document.documentElement.dataset.station = s.freq;
    el.freq.textContent = s.freq;
    el.name.textContent = s.name;
    el.tagline.textContent = s.tagline;
    el.needle.style.left = pct(Number(s.freq)) + '%';
    el.scale.setAttribute('aria-valuenow', s.freq);
    el.scale.setAttribute('aria-valuetext', `${s.freq} FM, ${s.name}`);
    for (const key of el.presets.children) key.setAttribute('aria-pressed', String(key.dataset.freq === s.freq));
    store.set('ms.station', s.freq);
  }

  const nearest = (f) => state.stations.reduce((a, b) => (Math.abs(Number(b.freq) - f) < Math.abs(Number(a.freq) - f) ? b : a));

  function freqFromPointer(e) {
    const r = el.scale.getBoundingClientRect();
    return MIN_F + clamp((e.clientX - r.left) / r.width, 0, 1) * (MAX_F - MIN_F);
  }
  function dragTo(f) {
    const s = nearest(f);
    document.documentElement.dataset.station = s.freq;     // lamp colour follows the needle
    el.needle.style.left = pct(f) + '%';
    el.freq.textContent = f.toFixed(1);
    el.name.textContent = s.name;
  }
  el.scale.addEventListener('pointerdown', (e) => {
    if (!state.stations.length || !state.powered) return;
    state.dragging = true;
    el.dial.classList.add('dragging');
    el.scale.setPointerCapture(e.pointerId);
    dragTo(freqFromPointer(e));
  });
  el.scale.addEventListener('pointermove', (e) => { if (state.dragging) dragTo(freqFromPointer(e)); });
  const endDrag = (e) => {
    if (!state.dragging) return;
    state.dragging = false;
    el.dial.classList.remove('dragging');
    const s = nearest(freqFromPointer(e));
    if (state.current && s.freq === state.current.freq) showStation(s); else tune(s);
  };
  el.scale.addEventListener('pointerup', endDrag);
  el.scale.addEventListener('pointercancel', endDrag);

  function tuneBy(delta) {
    if (!state.stations.length || !state.current) return;
    const i = state.stations.findIndex((s) => s.freq === state.current.freq);
    const next = state.stations[clamp(i + delta, 0, state.stations.length - 1)];
    if (next.freq !== state.current.freq) tune(next);
  }

  /* ---------------- status pill ---------------- */
  function setPill(kind, text) {
    el.pill.dataset.state = kind;
    el.pillText.textContent = text;
  }

  /* ---------------- tuning and playback ---------------- */
  function stopEpisode() {
    state.playingEpisode = false;
    el.player.pause();
    el.player.removeAttribute('src');
    el.player.load();
    state.segments = []; state.duration = 0; state.lastSeg = -2;
    setPlayingUi(false);
    el.bar.style.width = '0%';
    el.time.textContent = '0:00 / 0:00';
  }

  function tune(station) {
    showStation(station);
    stopEpisode();
    clearTimeout(state.settleTimer);
    clearTimeout(state.retryTimer);
    sfx.stopHiss(200);
    sfx.burst(900, 0.3);
    setPill('tuning', 'Tuning');
    el.replay.textContent = '';
    el.title.textContent = 'Tuning in';
    setCaption('', 'lead');
    const token = ++state.token;
    state.settleTimer = setTimeout(() => loadNext(station, token), SETTLE_MS);
  }

  async function loadNext(station, token) {
    let res;
    try {
      res = await fetch(`/api/stations/${encodeURIComponent(station.freq)}/next`, { cache: 'no-store' });
    } catch {
      if (token !== state.token) return;
      showTrouble(station, 'Can’t reach the radio service. Check that it is still running; this page will keep trying.');
      state.retryTimer = setTimeout(() => loadNext(station, token), WAIT_RETRY_MS);
      return;
    }
    if (token !== state.token) return;           // the dial moved on while we waited
    if (res.status === 503) {
      let detail = {};
      try { detail = (await res.json()).detail || {}; } catch { /* keep default */ }
      if (token !== state.token) return;
      showWaiting(station, detail);
      state.retryTimer = setTimeout(() => loadNext(station, token), WAIT_RETRY_MS);
      return;
    }
    if (!res.ok) {
      showTrouble(station, `The radio service answered with an error (${res.status}). Trying again shortly.`);
      state.retryTimer = setTimeout(() => loadNext(station, token), WAIT_RETRY_MS);
      return;
    }
    const ep = await res.json();
    if (token !== state.token) return;
    startEpisode(station, ep);
  }

  function showWaiting(station, detail) {
    el.title.textContent = 'Waiting for a signal';
    el.replay.textContent = '';
    const why = detail && detail.last_error ? ` The story engine said: ${detail.last_error}` : '';
    setCaption(`Nothing is on ${station.freq} yet. The first story is still being made and will start by itself.${why}`, 'lead');
    setPill('waiting', 'No signal');
    sfx.startHiss();
  }

  function showTrouble(station, message) {
    el.title.textContent = 'No signal';
    setCaption(message, 'lead');
    setPill('error', 'Service unreachable');
    sfx.startHiss();
  }

  function startEpisode(station, ep) {
    sfx.stopHiss(700);
    state.segments = ep.segments || [];
    state.duration = ep.duration || 0;
    state.lastSeg = -2;
    state.playingEpisode = true;
    el.title.textContent = ep.title;
    el.replay.textContent = ep.replay ? 'Replay of an earlier story' : '';
    renderCaption(0);
    el.player.src = ep.audio_url;
    el.player.volume = state.volume;
    const p = el.player.play();
    if (p && p.catch) p.catch(onPlayBlocked);
  }

  function onPlayBlocked(err) {
    setPlayingUi(false);
    if (err && err.name === 'NotAllowedError') {
      setCaption('Your browser blocked the sound. Press play to listen.', 'lead');
      setPill('tuning', 'Ready');
    }
  }

  function setPlayingUi(playing) {
    el.play.dataset.playing = String(playing);
    el.play.setAttribute('aria-label', playing ? 'Pause' : 'Play');
    if (playing) setPill('live', 'On air');
    else if (state.playingEpisode) setPill('tuning', 'Paused');
  }

  function setCaption(text, kind) {
    el.caption.dataset.kind = kind || 'story';
    el.caption.textContent = text;
    el.caption.classList.remove('fade');
    void el.caption.offsetWidth;                 // restart the fade
    el.caption.classList.add('fade');
  }

  function segmentIndexAt(t) {
    let found = -1;
    for (let i = 0; i < state.segments.length; i++) if (t + 0.15 >= state.segments[i].start) found = i;
    return found;
  }

  function renderCaption(t) {
    const i = segmentIndexAt(t);
    if (i === state.lastSeg) return;
    state.lastSeg = i;
    if (i < 0) { setCaption('Tuning in…', 'lead'); return; }
    const seg = state.segments[i];
    setCaption(seg.text, seg.kind === 'intro' ? 'intro' : 'story');
  }

  function renderProgress() {
    const t = el.player.currentTime || 0;
    const total = Number.isFinite(el.player.duration) && el.player.duration > 0 ? el.player.duration : state.duration;
    renderCaption(t);
    el.bar.style.width = total ? `${clamp((t / total) * 100, 0, 100)}%` : '0%';
    el.time.textContent = `${fmtTime(t)} / ${fmtTime(total)}`;
  }

  function loop() {
    renderProgress();
    if (!el.player.paused && !el.player.ended) state.raf = requestAnimationFrame(loop);
  }

  el.player.addEventListener('play', () => { setPlayingUi(true); cancelAnimationFrame(state.raf); loop(); });
  el.player.addEventListener('pause', () => { if (state.playingEpisode) setPlayingUi(false); });
  el.player.addEventListener('timeupdate', renderProgress);        // keeps captions right in background tabs
  el.player.addEventListener('seeked', renderProgress);
  el.player.addEventListener('ended', () => {
    if (!state.playingEpisode) return;
    state.playingEpisode = false;
    sfx.burst(900, 0.28);
    setPill('tuning', 'Next story');
    const token = ++state.token;
    loadNext(state.current, token);
  });
  el.player.addEventListener('error', () => {
    if (!el.player.getAttribute('src') || !state.playingEpisode) return;
    state.playingEpisode = false;
    setPill('error', 'Audio problem');
    const token = ++state.token;
    state.retryTimer = setTimeout(() => loadNext(state.current, token), 4000);
  });

  el.play.addEventListener('click', () => {
    if (!state.powered) return;
    if (!el.player.getAttribute('src')) { tune(state.current); return; }
    if (el.player.paused) { const p = el.player.play(); if (p && p.catch) p.catch(onPlayBlocked); } else el.player.pause();
  });

  el.volume.value = String(state.volume);
  el.volume.addEventListener('input', () => {
    state.volume = Number(el.volume.value);
    el.player.volume = state.volume;
    sfx.setVolume(state.volume);
    store.set('ms.volume', String(state.volume));
  });

  document.addEventListener('keydown', (e) => {
    if (!state.powered || e.altKey || e.ctrlKey || e.metaKey) return;
    if (e.target === el.volume) return;
    if (e.key === 'ArrowLeft') { e.preventDefault(); tuneBy(-1); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); tuneBy(1); }
    else if (e.key === ' ' && !/^(BUTTON|INPUT)$/.test(e.target.tagName)) { e.preventDefault(); el.play.click(); }
  });

  /* ---------------- status line ---------------- */
  async function poll() {
    try {
      const [a, b] = await Promise.all([fetch('/api/stations', { cache: 'no-store' }), fetch('/api/status', { cache: 'no-store' })]);
      if (!a.ok || !b.ok) throw new Error('bad status');
      const list = await a.json(), status = await b.json();
      state.target = list.target_per_station || state.target;
      for (const s of list.stations) {
        const mine = state.stations.find((x) => x.freq === s.freq);
        if (mine) mine.queued = s.queued;
      }
      updateReady();
      const w = status.worker;
      const ready = list.stations.reduce((sum, s) => sum + s.queued, 0);
      let msg;
      if (!w.running) msg = `Playing saved episodes only. Story generation is off. ${ready} unplayed.`;
      else if (w.last_error) msg = `The story engine is unavailable, so saved episodes keep playing. ${String(w.last_error).slice(0, 140)}`;
      else if (w.paused) msg = `Story generation is paused. ${ready} unplayed episodes.`;
      else if (w.generating) msg = `${ready} unplayed episodes. Writing a new one for ${w.generating} FM (${Math.round(w.generating_for_s)} s so far).`;
      else msg = `${ready} unplayed episodes, all stations stocked.`;
      el.status.textContent = msg;
    } catch {
      el.status.textContent = 'Can’t reach the radio service. Is it still running?';
    } finally {
      state.pollTimer = setTimeout(poll, POLL_MS);
    }
  }

  /* ---------------- start up ---------------- */
  async function loadStations() {
    try {
      const res = await fetch('/api/stations', { cache: 'no-store' });
      if (!res.ok) throw new Error(String(res.status));
      const data = await res.json();
      state.stations = data.stations;
      state.target = data.target_per_station || 2;
    } catch {
      el.status.textContent = 'Can’t reach the radio service. Start it with: python -m app serve';
      setTimeout(loadStations, 3000);
      return;
    }
    buildScale();
    buildPresets();
    updateReady();
    const saved = store.get('ms.station');
    showStation(state.stations.find((s) => s.freq === saved) || state.stations[0]);
    el.powerBtn.disabled = false;
    poll();
  }

  async function powerOn() {
    if (state.powered || !state.stations.length) return;
    state.powered = true;
    sfx.init();
    sfx.resume();
    const unlocked = unlockPlayer();             // must start inside the click itself
    el.power.hidden = true;                      // respond at once; the sound unlock finishes in the background
    el.radio.removeAttribute('inert');
    el.radio.classList.add('on');                // the glass warms up
    el.player.volume = state.volume;
    await unlocked;
    tune(state.current);
    el.scale.focus({ preventScroll: true });
  }

  el.powerBtn.disabled = true;
  el.powerBtn.addEventListener('click', powerOn);
  loadStations();
})();