/* =====================================================================
 * HBL Voice Assistant - call-style client
 *
 *  - Mic par EK click  -> call shuru, agent pehle greeting bolta hai
 *  - Phir hands-free: aap bolein, rukein (~0.7s), jawab foran aana shuru
 *  - Neeche sirf aapki awaaz ka text aur agent ka text
 *  - Mic dobara click (ya End Call) -> call khatam
 *
 * Latency ke liye:
 *  - Aap ke ruktay hi audio (16 kHz WAV) server ko jata hai (VAD client par)
 *  - Server ek hi request mein STT + RAG + TTS stream karta hai (/api/turn)
 *  - Har jumla bantay hi gapless chal jata hai (Web Audio)
 *  - Agar jawab 1s mein nahi aaya to chhota "ek lamha" filler bolta hai
 * ===================================================================== */
(() => {
    'use strict';

    // -------- Tunable settings --------
    const CFG = {
        SILENCE_MS: 1150,         // 1.15s khamoshi: na baat katay gi aur jawab bhi foran aayega
        MIN_SPEECH_MS: 400,       // isse chhoti awaaz ignore
        MAX_UTTERANCE_MS: 35000,  // lambay jumlay ke liye 35s
        PRE_ROLL_MS: 600,         // pehla lafz bilkul na kate
        START_LOUD_MS: 90,        // awaaz shuru manne ke liye
        ENABLE_FILLER: false,     // filler completely disabled
        FILLER_DELAY_MS: 1200,    // filler delay
        FILLER_CATEGORY: 'searching_information',
        HISTORY_TURNS: 6,
        TARGET_RATE: 16000,
        TAIL_KEEP_MS: 600,        // aakhri lafz na kate
        MIN_PEAK: 0.02,           // dheemi awaaz bhi capture ho
        MAX_GAIN: 8,              // dheemi awaaz ko buland karna
        MIC: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    };

    const $ = (id) => document.getElementById(id);
    const el = {
        callCard: $('callCard'), mic: $('micBtn'), end: $('endBtn'), status: $('status'),
        timer: $('timer'), wave: $('wave'), halo1: $('halo1'), halo2: $('halo2'),
        transcript: $('transcript'), emptyNote: $('emptyNote'),
    };

    // -------- Language (STT) --------
    let LANG = 'ur';
    try { const v = localStorage.getItem('hbl_lang'); if (v !== null) LANG = v; } catch (_) { }
    function paintLang() {
        document.querySelectorAll('#lang button').forEach((b) => b.classList.toggle('on', b.dataset.lang === LANG));
    }
    document.querySelectorAll('#lang button').forEach((b) => b.addEventListener('click', () => {
        LANG = b.dataset.lang;
        try { localStorage.setItem('hbl_lang', LANG); } catch (_) { }
        paintLang();
    }));
    paintLang();

    // -------- Navigation --------
    const PAGES = {
        live: ['📞', 'HBL Live Voice', 'A call-style banking information assistant.'],
        text: ['💬', 'Text Chat', 'Ask questions in Urdu or English.'],
        search: ['📄', 'Document Search', 'Search the HBL knowledge base.'],
        faq: ['❓', 'FAQs', 'Frequently asked questions.'],
        about: ['ℹ️', 'About', 'About the HBL Assistant.'],
    };
    document.querySelectorAll('#nav button').forEach((b) => {
        b.addEventListener('click', () => {
            const v = b.dataset.view;
            document.querySelectorAll('#nav button').forEach((x) => x.classList.toggle('active', x === b));
            document.querySelectorAll('.view').forEach((s) => s.classList.toggle('active', s.id === 'view-' + v));
            $('bannerIcon').textContent = PAGES[v][0];
            $('bannerTitle').textContent = PAGES[v][1];
            $('bannerSub').textContent = PAGES[v][2];
        });
    });

    // -------- Small helpers --------
    const b64ToBuf = (b64) => {
        const bin = atob(b64);
        const u8 = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
        return u8.buffer;
    };
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

    function downsample(input, inRate, outRate) {
        if (inRate === outRate) return input;
        const ratio = inRate / outRate;
        const n = Math.floor(input.length / ratio);
        const out = new Float32Array(n);
        for (let i = 0; i < n; i++) {
            const s = Math.floor(i * ratio);
            const e = Math.min(Math.floor((i + 1) * ratio), input.length);
            let sum = 0, c = 0;
            for (let j = s; j < e; j++) { sum += input[j]; c++; }
            out[i] = c ? sum / c : 0;
        }
        return out;
    }

    function encodeWav(f32, rate) {
        const buf = new ArrayBuffer(44 + f32.length * 2);
        const v = new DataView(buf);
        const w = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
        w(0, 'RIFF'); v.setUint32(4, 36 + f32.length * 2, true); w(8, 'WAVE'); w(12, 'fmt ');
        v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
        v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true);
        v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, 'data'); v.setUint32(40, f32.length * 2, true);
        let o = 44;
        for (let i = 0; i < f32.length; i++, o += 2) {
            const s = Math.max(-1, Math.min(1, f32[i]));
            v.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7fff, true);
        }
        return buf;
    }

    // Dheemi recording ko buland karo (STT ko saaf awaaz chahiye); sirf shor ho to null
    function normalizePcm(pcm) {
        let peak = 0;
        for (let i = 0; i < pcm.length; i++) { const a = Math.abs(pcm[i]); if (a > peak) peak = a; }
        if (peak < CFG.MIN_PEAK) return null;
        if (peak >= 0.6) return pcm;
        const g = Math.min(CFG.MAX_GAIN, 0.9 / peak);
        const out = new Float32Array(pcm.length);
        for (let i = 0; i < pcm.length; i++) out[i] = pcm[i] * g;
        return out;
    }

    // -------- Gapless audio player (Web Audio) --------
    class Player {
        constructor(ctx) {
            this.ctx = ctx; this.nextTime = 0; this.sources = new Set();
            this.waiters = []; this.chain = Promise.resolve();
        }
        enqueue(arrayBuffer) {                       // tartib barqarar: chain mein
            this.chain = this.chain.then(() => this._play(arrayBuffer)).catch(() => { });
            return this.chain;
        }
        async _play(ab) {
            const buf = await this.ctx.decodeAudioData(ab.slice(0));
            const src = this.ctx.createBufferSource();
            src.buffer = buf; src.connect(this.ctx.destination);
            const at = Math.max(this.ctx.currentTime + 0.02, this.nextTime);
            src.start(at); this.nextTime = at + buf.duration;
            this.sources.add(src);
            src.onended = () => { this.sources.delete(src); if (!this.sources.size) this._idle(); };
        }
        async drain() { await this.chain; if (this.sources.size) await new Promise((r) => this.waiters.push(r)); }
        stop() {
            for (const s of this.sources) { try { s.onended = null; s.stop(); } catch (_) { } }
            this.sources.clear(); this.nextTime = 0; this._idle();
        }
        _idle() { this.waiters.splice(0).forEach((f) => f()); }
    }

    // -------- Call state --------
    const S = {
        active: false, phase: 'idle', ctx: null, stream: null, node: null, player: null,
        abort: null, history: [], timerId: null, t0: 0, runId: 0,
        level: 0, bars: new Array(26).fill(0), lastBarAt: 0,
        pre: [], preMs: 0, chunks: [], recMs: 0, speechMs: 0, silenceMs: 0, loudMs: 0, noise: 0.01,
    };

    const STATUS = {
        idle: 'Tap the microphone button above to begin',
        connecting: 'Connecting…',
        greeting: 'Agent is speaking…',
        listening: 'Listening… speak whenever you are ready',
        hearing: 'Listening to you…',
        thinking: 'One moment…',
        speaking: 'Agent is speaking…',
    };

    function setPhase(p, text) {
        S.phase = p;
        el.callCard.className = 'card' + (S.active ? ' in-call' : '') + ' phase-' + p;
        el.status.classList.remove('error');
        el.status.textContent = text || STATUS[p] || '';
        el.mic.setAttribute('aria-label', S.active ? 'End call' : 'Start call');
    }
    function showError(msg) {
        el.status.textContent = msg;
        el.status.classList.add('error');
    }

    // -------- Transcript --------
    function addMsg(role, text) {
        if (el.emptyNote) { el.emptyNote.remove(); el.emptyNote = null; }
        const d = document.createElement('div');
        d.className = 'chat-bubble ' + (role === 'agent' ? 'agent' : 'customer');
        d.dir = 'auto';
        const label = document.createElement('small');
        label.textContent = role === 'agent' ? 'AGENT' : 'CUSTOMER';
        const body = document.createElement('span');
        body.textContent = text || '';
        d.append(label, body);
        el.transcript.appendChild(d);
        d.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        return body;
    }

    // -------- Timer / visuals --------
    function startTimer() {
        S.t0 = Date.now();
        clearInterval(S.timerId);
        S.timerId = setInterval(() => {
            const s = Math.floor((Date.now() - S.t0) / 1000);
            el.timer.textContent = String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0');
        }, 500);
    }
    function stopTimer() { clearInterval(S.timerId); S.timerId = null; }

    for (let i = 0; i < 26; i++) el.wave.appendChild(document.createElement('i'));
    const dots = Array.from(el.wave.children);

    function frame(ts) {
        let lvl = S.level;
        if (S.phase === 'speaking' || S.phase === 'greeting') {
            lvl = 0.28 + 0.22 * Math.sin(ts / 110) + 0.12 * Math.sin(ts / 47);
        } else if (S.phase === 'thinking') {
            lvl = 0.12 + 0.08 * Math.sin(ts / 220);
        } else if (!S.active) {
            lvl = 0;
        }
        lvl = Math.max(0, Math.min(1, lvl));
        if (ts - S.lastBarAt > 55) {
            S.bars.push(lvl); S.bars.shift(); S.lastBarAt = ts;
            dots.forEach((d, i) => { d.style.height = (6 + S.bars[i] * 36).toFixed(1) + 'px'; });
        }
        const sc = 0.95 + lvl * 0.35;
        el.halo1.style.transform = 'scale(' + sc.toFixed(3) + ')';
        el.halo2.style.transform = 'scale(' + (0.95 + lvl * 0.5).toFixed(3) + ')';
        S.level *= 0.85;
        requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);

    // -------- Microphone + VAD --------
    const WORKLET = `
    class PcmCapture extends AudioWorkletProcessor {
      constructor() { super(); this.buf = new Float32Array(2048); this.n = 0; }
      process(inputs) {
        const ch = inputs[0] && inputs[0][0];
        if (ch) {
          for (let i = 0; i < ch.length; i++) {
            this.buf[this.n++] = ch[i];
            if (this.n === 2048) { this.port.postMessage(this.buf.slice(0)); this.n = 0; }
          }
        }
        return true;
      }
    }
    registerProcessor('pcm-capture', PcmCapture);`;

    async function setupMic(stream) {
        const url = URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' }));
        await S.ctx.audioWorklet.addModule(url);
        URL.revokeObjectURL(url);
        const src = S.ctx.createMediaStreamSource(stream);
        const node = new AudioWorkletNode(S.ctx, 'pcm-capture');
        const mute = S.ctx.createGain(); mute.gain.value = 0;
        src.connect(node); node.connect(mute); mute.connect(S.ctx.destination);
        node.port.onmessage = (e) => onFrame(e.data);
        S.node = node;
    }

    function resetVad() {
        S.pre = []; S.preMs = 0; S.chunks = []; S.recMs = 0;
        S.speechMs = 0; S.silenceMs = 0; S.loudMs = 0;
    }

    function onFrame(chunk) {
        if (!S.active) return;
        let sum = 0;
        for (let i = 0; i < chunk.length; i++) sum += chunk[i] * chunk[i];
        const rms = Math.sqrt(sum / chunk.length);
        const dur = (chunk.length / S.ctx.sampleRate) * 1000;

        if (S.phase !== 'listening' && S.phase !== 'hearing') return;   // agent bol raha ho to sunna band (echo se bachav)
        S.level = Math.max(S.level, Math.min(1, rms * 7));

        const onTh = Math.max(0.018, S.noise * 2.8);
        const offTh = Math.max(0.009, S.noise * 1.5);

        if (S.phase === 'listening') {
            S.pre.push(chunk); S.preMs += dur;
            while (S.preMs > CFG.PRE_ROLL_MS && S.pre.length > 1) { S.preMs -= (S.pre[0].length / S.ctx.sampleRate) * 1000; S.pre.shift(); }
            if (rms > onTh) {
                S.loudMs += dur;
            } else {
                S.loudMs = 0;
                S.noise = Math.min(0.05, S.noise * 0.95 + rms * 0.05);
            }
            if (S.loudMs >= CFG.START_LOUD_MS) {
                S.chunks = S.pre.slice(); S.recMs = S.preMs; S.pre = []; S.preMs = 0;
                S.speechMs = S.loudMs; S.silenceMs = 0;
                setPhase('hearing');
            }
        } else { // hearing
            S.chunks.push(chunk); S.recMs += dur;
            if (rms > offTh) { S.silenceMs = 0; S.speechMs += dur; } else { S.silenceMs += dur; }
            if (S.silenceMs >= CFG.SILENCE_MS || S.recMs >= CFG.MAX_UTTERANCE_MS) finishUtterance();
        }
    }

    function finishUtterance() {
        const chunks = S.chunks, speechMs = S.speechMs, silenceMs = S.silenceMs;
        const sr = S.ctx.sampleRate;
        resetVad();
        if (speechMs < CFG.MIN_SPEECH_MS) { setPhase('listening'); return; }

        // akhir ki zyada khamoshi kaat do (upload aur STT chhota)
        let dropMs = Math.max(0, silenceMs - CFG.TAIL_KEEP_MS);
        while (dropMs > 0 && chunks.length > 1) {
            const ms = (chunks[chunks.length - 1].length / sr) * 1000;
            if (ms > dropMs) break;
            dropMs -= ms; chunks.pop();
        }
        let total = 0; chunks.forEach((c) => (total += c.length));
        const pcm = new Float32Array(total);
        let o = 0; chunks.forEach((c) => { pcm.set(c, o); o += c.length; });
        handleTurn(pcm, sr);
    }

    // -------- One conversation turn --------
    async function handleTurn(pcm, sr) {
        const run = S.runId;
        const norm = normalizePcm(pcm);
        if (!norm) { resetVad(); setPhase('listening'); return; }      // sirf shor tha
        setPhase('thinking');
        const wav = encodeWav(downsample(norm, sr, CFG.TARGET_RATE), CFG.TARGET_RATE);
        const fd = new FormData();
        fd.append('audio', new Blob([wav], { type: 'audio/wav' }), 'speech.wav');
        fd.append('language', LANG);
        fd.append('history', JSON.stringify(S.history.slice(-CFG.HISTORY_TURNS)));

        const ctrl = new AbortController(); S.abort = ctrl;
        let firstAudio = false, agentBody = null, agentText = '', userText = '', failed = null, empty = false;

        let fillerTimer = null;

        function triggerFiller() {
            if (!CFG.ENABLE_FILLER) return;
            if (fillerTimer || firstAudio || !S.active || run !== S.runId) return;
            fillerTimer = setTimeout(async () => {
                if (firstAudio || !S.active || run !== S.runId) return;
                try {
                    const r = await fetch('/api/filler?cat=' + CFG.FILLER_CATEGORY);
                    if (!r.ok) return;
                    const ab = await r.arrayBuffer();
                    if (!firstAudio && S.active && run === S.runId) {
                        setPhase('speaking');
                        S.player.enqueue(ab);
                    }
                } catch (_) { }
            }, CFG.FILLER_DELAY_MS);
        }

        function onEvent(ev) {
            if (ev.type === 'transcript') {
                userText = ev.text; addMsg('customer', ev.text);
            } else if (ev.type === 'searching') {
                triggerFiller();
            } else if (ev.type === 'sentence') {
                firstAudio = true;
                if (fillerTimer) { clearTimeout(fillerTimer); fillerTimer = null; }
                if (S.phase !== 'speaking') setPhase('speaking');
                if (!agentBody) agentBody = addMsg('agent', '');
                agentText += (agentText ? ' ' : '') + ev.text;
                agentBody.textContent = agentText;
                agentBody.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
                S.player.enqueue(b64ToBuf(ev.audio));
            } else if (ev.type === 'empty') {
                empty = true;
            } else if (ev.type === 'error') {
                failed = ev.message || 'Something went wrong.';
            } else if (ev.type === 'done') {
                if (fillerTimer) { clearTimeout(fillerTimer); fillerTimer = null; }
                if (ev.timings) console.log('[turn timings]', ev.timings);
            }
        }

        try {
            const res = await fetch('/api/turn', { method: 'POST', body: fd, signal: ctrl.signal });
            if (!res.ok) {
                const e = await res.json().catch(() => ({}));
                throw new Error(e.detail || 'Server error ' + res.status);
            }
            const reader = res.body.getReader();
            const dec = new TextDecoder();
            let buf = '';
            for (; ;) {
                const { value, done } = await reader.read();
                if (done) break;
                buf += dec.decode(value, { stream: true });
                let i;
                while ((i = buf.indexOf('\n')) >= 0) {
                    const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
                    if (line) { try { onEvent(JSON.parse(line)); } catch (_) { } }
                }
            }
        } catch (e) {
            if (e.name !== 'AbortError') failed = e.message || String(e);
        } finally {
            clearTimeout(fillerTimer);
        }

        if (!S.active || run !== S.runId) return;           // call khatam ho chuki

        if (userText) S.history.push({ role: 'customer', text: userText });
        if (agentText) S.history.push({ role: 'agent', text: agentText });

        await S.player.drain();                              // jawab (ya filler) khatam hone tak bolne do
        if (!S.active || run !== S.runId) return;
        await sleep(180);                                    // speaker ki gonj khatam
        resetVad();
        setPhase('listening');
        if (failed) showError(failed);
        else if (empty) { /* kuch sunai nahi diya - chupchap dobara sunna */ }
    }

    // -------- Start / End call --------
    async function startCall() {
        if (S.active) return;
        S.active = true; S.runId++; S.history = []; resetVad();
        el.transcript.innerHTML = '';
        el.emptyNote = null;
        el.timer.textContent = '00:00';
        setPhase('connecting');
        const run = S.runId;

        try {
            S.ctx = new (window.AudioContext || window.webkitAudioContext)({ latencyHint: 'interactive' });
            await S.ctx.resume();
            S.player = new Player(S.ctx);
            startTimer();

            // greeting aur mic permission SAATH SAATH (aap ko foran awaaz sunai de)
            const micP = navigator.mediaDevices.getUserMedia({
                audio: CFG.MIC,
            });
            micP.catch(() => { });                              // (error neeche await par pakda jata hai)
            const greetP = fetch('/api/greeting').then((r) => { if (!r.ok) throw new Error('Greeting failed'); return r.json(); });

            const g = await greetP;
            if (!S.active || run !== S.runId) { try { (await micP).getTracks().forEach((t) => t.stop()); } catch (_) { } return; }
            setPhase('greeting');
            addMsg('agent', g.text);
            S.player.enqueue(b64ToBuf(g.audio));

            S.stream = await micP;
            await setupMic(S.stream);

            await S.player.drain();
            if (!S.active || run !== S.runId) return;
            await sleep(150);
            resetVad();
            setPhase('listening');
        } catch (e) {
            console.error(e);
            const denied = e && (e.name === 'NotAllowedError' || e.name === 'SecurityError');
            endCall();
            showError(denied ? 'Microphone permission was denied. Please allow it and try again.' : 'Could not start the call: ' + (e.message || e));
        }
    }

    function endCall() {
        S.runId++;
        S.active = false;
        try { S.abort && S.abort.abort(); } catch (_) { }
        try { S.player && S.player.stop(); } catch (_) { }
        try { S.node && S.node.disconnect(); } catch (_) { }
        try { S.stream && S.stream.getTracks().forEach((t) => t.stop()); } catch (_) { }
        try { S.ctx && S.ctx.close(); } catch (_) { }
        S.node = S.stream = S.ctx = S.player = S.abort = null;
        stopTimer();
        resetVad();
        setPhase('idle');
    }

    el.mic.addEventListener('click', () => (S.active ? endCall() : startCall()));
    el.end.addEventListener('click', endCall);
    window.addEventListener('pagehide', () => { if (S.active) endCall(); });

    // =====================================================================
    // Baqi pages: Text chat / Search / FAQ
    // =====================================================================
    let textCtx = null, textPlayer = null;
    function ensureTextAudio() {
        if (!textCtx) {
            textCtx = new (window.AudioContext || window.webkitAudioContext)();
            textPlayer = new Player(textCtx);
        }
        if (textCtx.state === 'suspended') textCtx.resume();
    }
    function splitSentences(t) {
        return (t.match(/[^۔.؟?!\n]+[۔.؟?!]?/g) || [t]).map((s) => s.trim()).filter(Boolean);
    }
    function speakText(text) {
        ensureTextAudio();
        textPlayer.stop();
        splitSentences(text).forEach((s) => {
            const p = fetch('/api/tts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: s }) })
                .then((r) => (r.ok ? r.arrayBuffer() : null)).catch(() => null);
            textPlayer.chain = textPlayer.chain.then(async () => { const ab = await p; if (ab) await textPlayer._play(ab); }).catch(() => { });
        });
    }

    function bubble(container, role, text) {
        const d = document.createElement('div');
        d.className = 'chat-bubble ' + (role === 'agent' ? 'agent' : 'customer');
        d.dir = 'auto';
        const l = document.createElement('small'); l.textContent = role === 'agent' ? 'AGENT' : 'CUSTOMER';
        const b = document.createElement('span'); b.textContent = text;
        d.append(l, b); container.appendChild(d);
        return b;
    }

    async function askText(q) {
        const r = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: q }) });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'Request failed');
        return (await r.json()).answer;
    }

    const textQ = $('textQ');
    async function sendText() {
        const q = textQ.value.trim();
        if (!q) return;
        textQ.value = '';
        const log = $('textLog');
        bubble(log, 'customer', q);
        const body = bubble(log, 'agent', '…');
        try {
            const a = await askText(q);
            body.textContent = a;
            if ($('speakToggle').checked) speakText(a);
        } catch (e) { body.textContent = 'Error: ' + e.message; }
    }
    $('textSend').addEventListener('click', sendText);
    textQ.addEventListener('keydown', (e) => { if (e.key === 'Enter') sendText(); });

    async function doSearch() {
        const q = $('searchQ').value.trim();
        const out = $('searchOut');
        if (!q) return;
        out.textContent = 'Searching…';
        try {
            const r = await fetch('/api/search', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query: q }) });
            if (!r.ok) throw new Error('Search failed');
            const data = await r.json();
            out.innerHTML = '';
            if (!data.results.length) { out.textContent = 'No relevant information was found.'; return; }
            data.results.forEach((x, i) => {
                const d = document.createElement('div'); d.className = 'result'; d.dir = 'auto';
                const h = document.createElement('b'); h.textContent = 'Result ' + (i + 1) + (x.page ? ' · page ' + x.page : '');
                d.append(h, document.createElement('br'), document.createTextNode(x.text));
                out.appendChild(d);
            });
        } catch (e) { out.textContent = 'Document search is currently unavailable.'; }
    }
    $('searchGo').addEventListener('click', doSearch);
    $('searchQ').addEventListener('keydown', (e) => { if (e.key === 'Enter') doSearch(); });

    const FAQS = [
        'How can I open an account at HBL?',
        'What are the debit card charges?',
        'What documents are required to open an account?',
        'How can I report a lost or stolen card?',
        'What are the HBL contact details?',
        'مجھے ایچ بی ایل میں اکاؤنٹ کھولنے کا طریقہ بتائیں۔',
    ];
    FAQS.forEach((q) => {
        const wrap = document.createElement('div'); wrap.className = 'faq-item';
        const btn = document.createElement('button'); btn.textContent = q; btn.dir = 'auto';
        const ans = document.createElement('div'); ans.className = 'faq-answer'; ans.dir = 'auto';
        btn.addEventListener('click', async () => {
            ans.textContent = 'Searching HBL documents…';
            try { ans.textContent = await askText(q); } catch (e) { ans.textContent = 'Error: ' + e.message; }
        });
        wrap.append(btn, ans); $('faqList').appendChild(wrap);
    });
})();
