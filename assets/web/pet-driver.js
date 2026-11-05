/* Desktop pet driver.
 *
 * Each part has its own clock, with non-harmonic periods so the combination
 * never lands back on the same frame:
 *   lashes - continuous rotation | sclera - shares the layer-three beat
 *   layer three / two / one - separate periods and phases
 *
 * The sclera rides the same clock as the ring just inside it, so the white of
 * the eye and that ring swell together (their edges stay parallel). Every layer
 * scales about 80,80 via transform-origin, so the pupil never leaves its spot.
 *
 * The eyelid is one 0..1 parameter written into the reference clip path, so the
 * resting expressions (open / quarter / half) and a blink are separate things.
 * Nothing blinks on a metronome: only an interaction triggers one.
 *
 * Two signal glitches play at random, both using the artwork's own mechanism:
 *   blocks  - the five clipped <use> clones slide sideways (offset bars)
 *   threads - the displacement filter with a jagged, live base frequency
 *
 * The ripple (rings leaving the rim and dissolving) is not a glitch: it keeps
 * its own slow, random schedule and can run while a glitch is playing.
 */
(function () {
  const root = document.querySelector('[data-dsh-fairy-mascot-root="true"]');
  const signal = document.querySelector('.dsh-fairy-signal');
  const eyeball = document.querySelector('.dsh-fairy-eyeball');
  const corners = document.querySelector('.dsh-fairy-corners');
  const sclera = document.querySelector('.dsh-fairy-sclera');
  const layer3 = document.querySelector('.dsh-fairy-layer-three');
  const layer2 = document.querySelectorAll('.dsh-fairy-eye .dsh-fairy-layer-two');
  const layer1 = document.querySelectorAll('.dsh-fairy-eye .dsh-fairy-layer-one');
  const lidPath = document.querySelector('.dsh-fairy-thinking-clip-shape');
  const noise = document.getElementById('dsh-fairy-noise');
  const displace = document.getElementById('dsh-fairy-displace');

  const EXPRESSION_LID = { idle: 0.0, working: 0.22, waiting: 0.5 };
  const BLINK_DEPTH = 0.5;

  let rate = 1;
  let lashAngle = 0;
  let beatPhase = 0;
  let lastFrame = null;
  let gaze = { x: 0, y: 0 };
  let gazeSmooth = { x: 0, y: 0 };
  let expression = 'idle';
  let lid = 0;
  let blinkAt = null;
  let blinkDepth = BLINK_DEPTH;
  let lidNext = 0;                       // next random micro-blink while a turn runs
  let workLid = EXPRESSION_LID.working;  // resting angle while working, drifts
  let workLidAt = 0;                     // when to pick a new resting angle
  let loadLid = 0;
  let loadSmooth = 0;

  let faultUntil = 0;
  let faultNext = 0;
  let faultKind = null;
  let haloPhase = -1;
  let rippleNext = 0;

  /* Ripple: a slow train of soft rings that leave the rim, drift outwards and
   * dissolve. It has its own clock and never competes with the glitches. */
  const RIPPLE_RINGS = 4;
  const RIPPLE_GAP = 0.2;        // phase between consecutive rings
  const RIPPLE_REACH = 0.42;     // how far past the rim a ring travels
  const RIPPLE_SPEED = 0.36;     // phase per second: one ring takes ~2.8s
  let lastSliceAt = 0;
  let frames = 0;
  let fpsAt = 0;
  let fps = 60;

  /* ---- halo rings, drawn on top of the artwork ---------------------- */
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.querySelector('svg');
  if (svg) {
    const defs = document.createElementNS(NS, 'defs');
    defs.innerHTML =
      '<filter id="pet-halo-blur" x="-30%" y="-30%" width="160%" height="160%">' +
      '<feGaussianBlur stdDeviation="2.4"/></filter>';
    svg.insertBefore(defs, svg.firstChild);
  }
  const halo = document.createElementNS(NS, 'g');
  halo.setAttribute('pointer-events', 'none');
  const haloRings = [];
  for (let i = 0; i < RIPPLE_RINGS; i += 1) {
    const group = document.createElementNS(NS, 'g');
    // The pulse is the artwork's own outer glow, scaled outwards and blurred.
    const glow = document.createElementNS(NS, 'circle');
    glow.setAttribute('cx', '80');
    glow.setAttribute('cy', '80');
    glow.setAttribute('r', '79');
    glow.setAttribute('fill', 'url(#dsh-fairy-outer-halo-gradient)');
    glow.setAttribute('opacity', '0');
    glow.setAttribute('filter', 'url(#pet-halo-blur)');
    group.appendChild(glow);
    halo.appendChild(group);
    haloRings.push({ group: group, glow: glow });
  }
  const body = document.querySelector('.dsh-fairy-body');
  if (body) body.appendChild(halo);

  /* ---- the eye beat --------------------------------------------------
   * One cycle in beat seconds: rise / hold at full size / fall / pause at the
   * bottom. Both stops last exactly as long as each other, so the eye lingers
   * at the maximum and at the minimum for the same time. Smoothstep ramps mean
   * the plateaus are entered and left without a visible corner.
   */
  const PULSE_CYCLE = 2.7;   // 1.9 was too brisk: speed x0.7, so one round takes 1.43x longer
  const PULSE_RISE = 0.26;
  const PULSE_HOLD = 0.24;   // the leftover 0.24 is the pause at the bottom
  const PULSE_FALL = 0.26;
  const PULSE_LAG = [0, 0.055, 0.11, 0.165];   // layer one, two, three, sclera
  const PULSE_AMP = [0.072, 0.056, 0.044, 0.050];

  function smoothstep(x) {
    return x * x * (3 - 2 * x);
  }

  function envelope(local) {
    if (local < PULSE_RISE) return smoothstep(local / PULSE_RISE);
    if (local < PULSE_RISE + PULSE_HOLD) return 1;
    const falling = local - PULSE_RISE - PULSE_HOLD;
    if (falling < PULSE_FALL) return 1 - smoothstep(falling / PULSE_FALL);
    return 0;
  }

  function beat(clock, lag) {
    let local = ((clock / PULSE_CYCLE) % 1) - lag;
    if (local < 0) local += 1;
    return envelope(local);
  }

  function now() {
    return performance.now() / 1000;
  }

  function ease(current, target, k) {
    return current + (target - current) * k;
  }

  function setScale(el, s) {
    if (el) el.style.transform = 'scale(' + s.toFixed(3) + ')';
  }

  function lidCurve(k) {
    const mid = 30 + k * 110;
    const bow = 30 * Math.sin(Math.PI * Math.min(1, k));
    const side = mid - bow;
    const ctrl = 2 * mid - side;
    return 'M 10 ' + side.toFixed(2) + ' Q 80 ' + ctrl.toFixed(2) +
      ' 150 ' + side.toFixed(2) + ' V 200 H 10 Z';
  }

  function pickFault() {
    // Only the two signal glitches are faults now; the ripple has its own
    // schedule and plays whenever it wants to.
    faultKind = Math.random() < 0.52 ? 'blocks' : 'threads';
    faultUntil = now() + 0.26 + Math.random() * 0.16;
    lastSliceAt = 0;
    if (signal) signal.setAttribute('data-glitch', faultKind);
    if (faultKind === 'threads' && noise && displace) {
      noise.setAttribute('baseFrequency', '0.006 ' + (0.16 + Math.random() * 0.14).toFixed(3));
      noise.setAttribute('seed', String(1 + Math.floor(Math.random() * 9)));
      displace.setAttribute('scale', String(5 + Math.random() * 5));
    }
    faultNext = now() + 4.5 + Math.random() * 7;
  }

  function startRipple() {
    haloPhase = 0;
    rippleNext = now() + 8 + Math.random() * 10;
  }

  function clearRipple() {
    haloRings.forEach((ring) => ring.glow.setAttribute('opacity', '0'));
    haloPhase = -1;
  }

  function endFault() {
    if (signal && signal.hasAttribute('data-glitch')) signal.removeAttribute('data-glitch');
    faultKind = null;
  }

  function frame() {
    const t = now();
    frames += 1;
    if (t - fpsAt >= 1) {
      fps = frames / (t - fpsAt);
      frames = 0;
      fpsAt = t;
    }

    const dt = lastFrame === null ? 0 : Math.min(0.1, t - lastFrame);
    lastFrame = t;
    beatPhase += dt * rate;

    lashAngle = (lashAngle + dt * rate * (360 / 18)) % 360;
    if (corners) corners.style.transform = 'rotate(' + lashAngle.toFixed(2) + 'deg)';

    // The wave: pupil first, then each ring outwards, sclera last. They all sit
    // at full size together for a moment, then unwind in the same order.
    // The pupil breathes around its nominal radius instead of only swelling, so
    // its contracted state sits below the resting size.
    const s1 = 1 + PULSE_AMP[0] * (beat(beatPhase, PULSE_LAG[0]) * 2 - 1);
    layer1.forEach((el) => setScale(el, s1));
    const s2 = 1 + PULSE_AMP[1] * beat(beatPhase, PULSE_LAG[1]);
    layer2.forEach((el) => setScale(el, s2));
    setScale(layer3, 1 + PULSE_AMP[2] * beat(beatPhase, PULSE_LAG[2]));
    setScale(sclera, 1 + PULSE_AMP[3] * beat(beatPhase, PULSE_LAG[3]));

    // eyelid: resting expression plus an interaction blink, on one curve
    let target = EXPRESSION_LID[expression] || 0;
    if (expression === 'working') {
      // A turn is running. Let the resting angle wander a little and drop into
      // soft blinks at irregular intervals: a metronome reads as a machine, and
      // one frozen angle reads as a dead one. Both are wrong.
      if (t >= workLidAt) {
        workLid = 0.13 + Math.random() * 0.15;
        workLidAt = t + 1.6 + Math.random() * 3.6;
      }
      target = workLid;
      if (t >= lidNext) {
        lidNext = t + 1.0 + Math.random() * 3.4;
        if (blinkAt === null) {
          blinkDepth = 0.24 + Math.random() * 0.3;
          blinkAt = t;
        }
      }
    } else {
      lidNext = 0;
      workLidAt = 0;
    }
    if (blinkAt !== null) {
      const span = (t - blinkAt) / 0.2;
      if (span >= 1) blinkAt = null;
      else {
        const env = span < 0.42 ? span / 0.42 : Math.max(0, 1 - (span - 0.42) / 0.58);
        target = Math.max(target, blinkDepth * env);
      }
    }
    // system load closes the lid slowly, never past half
    loadSmooth = ease(loadSmooth, loadLid, 0.028);
    target = Math.max(target, loadSmooth);
    lid = ease(lid, target, 0.6);
    if (lidPath) lidPath.setAttribute('d', lidCurve(lid));
    if (root) {
      if (lid > 0.01) root.setAttribute('data-lid', 'on');
      else root.removeAttribute('data-lid');
    }

    gazeSmooth.x = ease(gazeSmooth.x, gaze.x, 0.2);
    gazeSmooth.y = ease(gazeSmooth.y, gaze.y, 0.2);
    if (eyeball) {
      eyeball.style.transform =
        'translate(' + gazeSmooth.x.toFixed(2) + 'px, ' + gazeSmooth.y.toFixed(2) + 'px)';
    }

    // faults
    if (faultKind === 'threads' && noise && displace && t < faultUntil && t - lastSliceAt > 0.07) {
      lastSliceAt = t;
      noise.setAttribute('baseFrequency', '0.006 ' + (0.16 + Math.random() * 0.14).toFixed(3));
      noise.setAttribute('seed', String(1 + Math.floor(Math.random() * 9)));
      displace.setAttribute('scale', String(5 + Math.random() * 5));
    }
    if (t > faultNext && t > faultUntil) pickFault();
    if (faultKind === 'blocks') {
      // Smaller and quicker: two slices at a time, refreshed ~20 times a second.
      if (t - lastSliceAt > 0.05) {
        lastSliceAt = t;
        const first = 1 + Math.floor(Math.random() * 5);
        const second = 1 + ((first + 1 + Math.floor(Math.random() * 3)) % 5);
        for (let i = 1; i <= 5; i += 1) {
          const swing = i === first || i === second ? (Math.random() * 2 - 1) * 5.5 : 0;
          signal.style.setProperty('--dsh-g-s' + i + '-x', swing.toFixed(1) + 'px');
        }
        signal.style.setProperty('--dsh-g-bright', (1.05 + Math.random() * 0.06).toFixed(2));
        signal.style.setProperty('--dsh-g-contrast', (1.08 + Math.random() * 0.08).toFixed(2));
      }
    }
    if (t > faultUntil && faultKind) endFault();

    // ripple: its own clock, untouched by the glitch schedule. Each ring leaves
    // the rim, drifts out about 40% of its radius and dissolves on the way — no
    // snap, no strobe, roughly three seconds from rim to nothing.
    if (haloPhase < 0 && t > rippleNext) startRipple();
    if (haloPhase >= 0) {
      haloPhase += dt * RIPPLE_SPEED;
      haloRings.forEach((ring, index) => {
        const p = haloPhase - index * RIPPLE_GAP;
        if (p <= 0 || p >= 1) {
          ring.glow.setAttribute('opacity', '0');
          return;
        }
        const scale = 1 + p * RIPPLE_REACH;
        ring.group.setAttribute(
          'transform',
          'translate(80 80) scale(' + scale.toFixed(3) + ') translate(-80 -80)'
        );
        const appear = Math.min(1, p / 0.18);
        const fade = Math.pow(1 - p, 1.9);
        ring.glow.setAttribute('opacity', (0.7 * appear * fade).toFixed(3));
      });
      if (haloPhase > 1 + RIPPLE_GAP * (RIPPLE_RINGS - 1) + 0.02) clearRipple();
    }

    requestAnimationFrame(frame);
  }

  window.pet = {
    setSpeed(value) {
      const v = Number(value);
      rate = Math.max(1, Math.min(3, Number.isFinite(v) ? v : 1));
    },
    setGaze(x, y) {
      gaze.x = Math.max(-9, Math.min(9, x));
      gaze.y = Math.max(-9, Math.min(9, y));
    },
    setExpression(name) {
      expression = EXPRESSION_LID[name] === undefined ? 'idle' : name;
    },
    setLoad(ratio) {
      const value = Math.max(0, Math.min(1, Number(ratio) || 0));
      loadLid = value * 0.5;
    },
    blink(soft) {
      blinkDepth = soft ? 0.32 : BLINK_DEPTH;
      if (blinkAt === null) blinkAt = now();
    },
    fault(kind) {
      if (signal) signal.removeAttribute('data-glitch');
      faultUntil = 0;
      if (kind === 'halo') {
        // The ripple is its own event now: asking for it just plays one.
        faultKind = null;
        startRipple();
        return;
      }
      faultKind = kind || null;
      if (kind) {
        if (noise && displace) {
          noise.setAttribute('baseFrequency', '0.006 ' + (0.16 + Math.random() * 0.14).toFixed(3));
          noise.setAttribute('seed', String(1 + Math.floor(Math.random() * 9)));
          displace.setAttribute('scale', String(5 + Math.random() * 5));
        }
        signal.setAttribute('data-glitch', kind);
        faultUntil = now() + 0.5;
      }
      faultNext = now() + 5 + Math.random() * 6;
    },
    stats() {
      return { fps: Math.round(fps), lid: Number(lid.toFixed(2)) };
    },
  };

  faultNext = now() + 2.5;
  rippleNext = now() + 4 + Math.random() * 5;
  requestAnimationFrame(frame);
})();
