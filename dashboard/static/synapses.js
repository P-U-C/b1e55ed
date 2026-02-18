// synapses.js — Neural mesh background
// Each producer is a core node with its own heartbeat pulse
// Inspired by: fred again.. Vancouver light show

(function () {
  const canvas = document.createElement('canvas');
  canvas.id = 'synapses';
  canvas.style.cssText =
    'position:fixed;inset:0;z-index:1;pointer-events:none;opacity:0.85;';
  document.body.prepend(canvas);

  const ctx = canvas.getContext('2d');
  let W, H, nodes, cores, mouse;
  const PERIPHERAL_COUNT = 90;
  const CONNECT_DIST = 170;
  const BASE_SPEED = 0.12;

  const GREEN = [34, 197, 94];
  const WARM = [176, 172, 164];

  // 13 producers — each becomes a core node
  const PRODUCERS = [
    { id: 'ta',         label: 'TA' },
    { id: 'onchain',    label: 'ON' },
    { id: 'tradfi',     label: 'TF' },
    { id: 'sentiment',  label: 'SE' },
    { id: 'social',     label: 'SO' },
    { id: 'events',     label: 'EV' },
    { id: 'etf',        label: 'ET' },
    { id: 'orderbook',  label: 'OB' },
    { id: 'price',      label: 'PR' },
    { id: 'curator',    label: 'CU' },
    { id: 'aci',        label: 'AC' },
    { id: 'contract',   label: 'CO' },
    { id: 'whale',      label: 'WH' },
  ];

  function resize() {
    W = canvas.width = window.innerWidth;
    H = canvas.height = window.innerHeight;
    if (cores) positionCores();
  }

  function positionCores() {
    // Distribute cores in an organic cluster — not a grid, not a circle
    // Use golden angle spiral for natural spacing
    const cx = W * 0.5;
    const cy = H * 0.48;
    const maxR = Math.min(W, H) * 0.3;
    const golden = Math.PI * (3 - Math.sqrt(5)); // golden angle

    cores.forEach((c, i) => {
      const r = maxR * Math.sqrt((i + 0.5) / PRODUCERS.length) * 0.85;
      const angle = i * golden;
      c.homeX = cx + Math.cos(angle) * r;
      c.homeY = cy + Math.sin(angle) * r;
      c.x = c.homeX;
      c.y = c.homeY;
    });
  }

  function createCore(producer, index) {
    return {
      ...producer,
      x: 0, y: 0,
      homeX: 0, homeY: 0,
      vx: (Math.random() - 0.5) * 0.03,
      vy: (Math.random() - 0.5) * 0.03,
      baseR: 3,
      energy: 0,
      fireDecay: 0.97,
      isCore: true,
      // Each core has its own pulse rhythm (staggered, slightly different intervals)
      pulse: {
        radius: 0,
        energy: 0,
        interval: 3000 + index * 400 + Math.random() * 1500, // 3-5.7s, staggered
        lastFire: performance.now() - index * 300, // stagger initial fire
        speed: 2.5 + Math.random() * 1,
      },
    };
  }

  function createPeripheral() {
    // Peripheral nodes fill the space, slightly center-biased
    const angle = Math.random() * Math.PI * 2;
    const dist = Math.pow(Math.random(), 0.7) * Math.min(W, H) * 0.5;
    return {
      x: W * 0.5 + Math.cos(angle) * dist,
      y: H * 0.48 + Math.sin(angle) * dist,
      vx: (Math.random() - 0.5) * BASE_SPEED,
      vy: (Math.random() - 0.5) * BASE_SPEED,
      baseR: Math.random() * 1.2 + 0.3,
      energy: 0,
      fireDecay: 0.96,
      isCore: false,
    };
  }

  function init() {
    resize();
    cores = PRODUCERS.map((p, i) => createCore(p, i));
    positionCores();
    nodes = [];
    for (let i = 0; i < PERIPHERAL_COUNT; i++) nodes.push(createPeripheral());
    mouse = { x: -9999, y: -9999 };
  }

  function nodeDist(a, b) {
    const dx = a.x - b.x, dy = a.y - b.y;
    return Math.sqrt(dx * dx + dy * dy);
  }

  function draw(now) {
    ctx.clearRect(0, 0, W, H);

    const all = [...cores, ...nodes];
    const maxFade = Math.min(W, H) * 0.55;

    // ── Core pulses ──
    for (const c of cores) {
      const p = c.pulse;

      if (now - p.lastFire > p.interval) {
        p.radius = 0;
        p.energy = 1;
        p.lastFire = now;
        c.energy = 1; // core lights up on fire
      }

      if (p.energy > 0.01) {
        p.radius += p.speed;
        p.energy *= 0.988;

        // Pulse ring from this core
        ctx.beginPath();
        ctx.arc(c.x, c.y, p.radius, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(${GREEN[0]},${GREEN[1]},${GREEN[2]},${p.energy * 0.06})`;
        ctx.lineWidth = 20 * p.energy;
        ctx.stroke();

        // Energize nearby nodes (cores + peripherals)
        for (const n of all) {
          if (n === c) continue;
          const d = nodeDist(c, n);
          const diff = Math.abs(d - p.radius);
          if (diff < 35) {
            const hit = (1 - diff / 35) * p.energy * 0.7;
            n.energy = Math.max(n.energy, hit);
          }
        }
      }
    }

    // ── Connections ──
    for (let i = 0; i < all.length; i++) {
      const ni = all[i];
      for (let j = i + 1; j < all.length; j++) {
        const nj = all[j];
        const d = nodeDist(ni, nj);

        // Core-to-core connections reach further
        const bothCore = ni.isCore && nj.isCore;
        const oneCore = ni.isCore || nj.isCore;
        const maxD = bothCore ? CONNECT_DIST * 1.8 : oneCore ? CONNECT_DIST * 1.2 : CONNECT_DIST;

        if (d < maxD) {
          const alpha = 1 - d / maxD;
          const energy = Math.max(ni.energy, nj.energy);

          // Propagate energy through connections
          if (ni.energy > 0.15 && d < maxD * 0.7) {
            nj.energy = Math.max(nj.energy, ni.energy * 0.45);
          }
          if (nj.energy > 0.15 && d < maxD * 0.7) {
            ni.energy = Math.max(ni.energy, nj.energy * 0.45);
          }

          const r = WARM[0] + (GREEN[0] - WARM[0]) * energy;
          const g = WARM[1] + (GREEN[1] - WARM[1]) * energy;
          const b = WARM[2] + (GREEN[2] - WARM[2]) * energy;

          // Core-core connections are thicker
          const baseWidth = bothCore ? 1.0 : oneCore ? 0.6 : 0.4;
          const lineAlpha = alpha * (bothCore ? 0.3 : 0.2) + energy * alpha * 0.35;
          const lineWidth = baseWidth + energy * (bothCore ? 1.2 : 0.7);

          ctx.beginPath();
          ctx.moveTo(ni.x, ni.y);
          ctx.lineTo(nj.x, nj.y);
          ctx.strokeStyle = `rgba(${r|0},${g|0},${b|0},${lineAlpha})`;
          ctx.lineWidth = lineWidth;
          ctx.stroke();
        }
      }
    }

    // ── Draw nodes ──
    // Peripherals first
    for (const n of nodes) {
      n.x += n.vx;
      n.y += n.vy;

      if (n.x < -30) n.vx += 0.015;
      if (n.x > W + 30) n.vx -= 0.015;
      if (n.y < -30) n.vy += 0.015;
      if (n.y > H + 30) n.vy -= 0.015;

      // Mouse
      const md = nodeDist(n, mouse);
      if (md < 180 && md > 1) {
        n.vx += (mouse.x - n.x) / md * 0.004;
        n.vy += (mouse.y - n.y) / md * 0.004;
        if (md < 80) n.energy = Math.max(n.energy, 0.5 * (1 - md / 80));
      }

      n.vx *= 0.998;
      n.vy *= 0.998;
      n.energy *= n.fireDecay;
      if (n.energy < 0.005) n.energy = 0;

      const nr = WARM[0] + (GREEN[0] - WARM[0]) * n.energy;
      const ng = WARM[1] + (GREEN[1] - WARM[1]) * n.energy;
      const nb = WARM[2] + (GREEN[2] - WARM[2]) * n.energy;
      const nodeAlpha = 0.2 + n.energy * 0.6;
      const nodeR = n.baseR + n.energy * 2;

      ctx.beginPath();
      ctx.arc(n.x, n.y, nodeR, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${nr|0},${ng|0},${nb|0},${nodeAlpha})`;
      ctx.fill();

      if (n.energy > 0.2) {
        ctx.beginPath();
        ctx.arc(n.x, n.y, nodeR + n.energy * 6, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${GREEN[0]},${GREEN[1]},${GREEN[2]},${n.energy * 0.1})`;
        ctx.fill();
      }
    }

    // Cores — drawn on top, larger, with labels
    for (const c of cores) {
      // Gentle drift around home position
      c.x += c.vx;
      c.y += c.vy;
      // Spring back to home
      c.vx += (c.homeX - c.x) * 0.001;
      c.vy += (c.homeY - c.y) * 0.001;
      c.vx *= 0.99;
      c.vy *= 0.99;

      c.energy *= c.fireDecay;
      if (c.energy < 0.005) c.energy = 0;

      // Mouse energizes cores too
      const md = nodeDist(c, mouse);
      if (md < 120) c.energy = Math.max(c.energy, 0.6 * (1 - md / 120));

      const nr = WARM[0] + (GREEN[0] - WARM[0]) * c.energy;
      const ng = WARM[1] + (GREEN[1] - WARM[1]) * c.energy;
      const nb = WARM[2] + (GREEN[2] - WARM[2]) * c.energy;
      const coreR = c.baseR + c.energy * 3;
      const coreAlpha = 0.35 + c.energy * 0.55;

      // Outer glow (always slightly visible for cores)
      ctx.beginPath();
      ctx.arc(c.x, c.y, coreR + 8 + c.energy * 10, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${GREEN[0]},${GREEN[1]},${GREEN[2]},${0.02 + c.energy * 0.08})`;
      ctx.fill();

      // Core dot
      ctx.beginPath();
      ctx.arc(c.x, c.y, coreR, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${nr|0},${ng|0},${nb|0},${coreAlpha})`;
      ctx.fill();

      // Label (very subtle, only when somewhat energized)
      if (c.energy > 0.15) {
        ctx.font = `${9 * (0.7 + c.energy * 0.3)}px JetBrains Mono, monospace`;
        ctx.fillStyle = `rgba(${GREEN[0]},${GREEN[1]},${GREEN[2]},${c.energy * 0.4})`;
        ctx.textAlign = 'center';
        ctx.fillText(c.label, c.x, c.y - coreR - 6);
      }
    }

    requestAnimationFrame(draw);
  }

  window.addEventListener('resize', () => { resize(); });
  document.addEventListener('mousemove', (e) => {
    mouse.x = e.clientX;
    mouse.y = e.clientY;
  });
  document.addEventListener('mouseleave', () => {
    mouse.x = -9999;
    mouse.y = -9999;
  });

  init();
  requestAnimationFrame(draw);
})();
