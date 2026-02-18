// synapses.js — Neural mesh background
// Central pulse radiates outward, connections fade with distance
// Inspired by: fred again.. Vancouver light show

(function () {
  const canvas = document.createElement('canvas');
  canvas.id = 'synapses';
  canvas.style.cssText =
    'position:fixed;inset:0;z-index:1;pointer-events:none;opacity:0.85;';
  document.body.prepend(canvas);

  const ctx = canvas.getContext('2d');
  let W, H, nodes, mouse, center;
  const NODE_COUNT = 120;
  const CONNECT_DIST = 180;
  const BASE_SPEED = 0.12;

  // Colors
  const GREEN = [34, 197, 94];
  const WARM = [176, 172, 164];

  // Central pulse state
  const pulse = {
    radius: 0,
    energy: 0,
    interval: 4000,  // ms between pulses
    lastFire: 0,
    speed: 3,        // px per frame expansion
    maxRadius: 0,    // set on resize
  };

  function resize() {
    W = canvas.width = window.innerWidth;
    H = canvas.height = window.innerHeight;
    center = { x: W * 0.5, y: H * 0.45 }; // slightly above center
    pulse.maxRadius = Math.sqrt(W * W + H * H) * 0.6;
  }

  function createNode(clustered) {
    // More nodes near center, fewer at edges
    let x, y;
    if (clustered && Math.random() < 0.6) {
      // Gaussian-ish cluster around center
      const angle = Math.random() * Math.PI * 2;
      const dist = Math.random() * Math.random() * Math.min(W, H) * 0.45;
      x = W * 0.5 + Math.cos(angle) * dist;
      y = H * 0.45 + Math.sin(angle) * dist;
    } else {
      x = Math.random() * W;
      y = Math.random() * H;
    }
    return {
      x, y,
      vx: (Math.random() - 0.5) * BASE_SPEED,
      vy: (Math.random() - 0.5) * BASE_SPEED,
      baseR: Math.random() * 1.2 + 0.4,
      energy: 0,
      fireDecay: 0.965,
    };
  }

  function init() {
    resize();
    nodes = [];
    for (let i = 0; i < NODE_COUNT; i++) nodes.push(createNode(true));
    mouse = { x: -9999, y: -9999 };
    pulse.lastFire = performance.now();
  }

  function dist(a, b) {
    const dx = a.x - b.x, dy = a.y - b.y;
    return Math.sqrt(dx * dx + dy * dy);
  }

  function distFromCenter(n) {
    const dx = n.x - center.x, dy = n.y - center.y;
    return Math.sqrt(dx * dx + dy * dy);
  }

  function draw(now) {
    ctx.clearRect(0, 0, W, H);

    // ── Central pulse wave ──
    if (now - pulse.lastFire > pulse.interval) {
      pulse.radius = 0;
      pulse.energy = 1;
      pulse.lastFire = now;
    }

    if (pulse.energy > 0.01) {
      pulse.radius += pulse.speed;
      pulse.energy *= 0.992;

      // Draw the pulse ring (very subtle)
      ctx.beginPath();
      ctx.arc(center.x, center.y, pulse.radius, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(${GREEN[0]},${GREEN[1]},${GREEN[2]},${pulse.energy * 0.08})`;
      ctx.lineWidth = 30 * pulse.energy;
      ctx.stroke();

      // Energize nodes the wave passes through
      for (const n of nodes) {
        const d = distFromCenter(n);
        const diff = Math.abs(d - pulse.radius);
        if (diff < 40) {
          const hitStrength = (1 - diff / 40) * pulse.energy;
          n.energy = Math.max(n.energy, hitStrength * 0.8);
        }
      }
    }

    // ── Density factor: nodes near center are more visible ──
    const maxDist = Math.min(W, H) * 0.55;

    // ── Connections ──
    for (let i = 0; i < nodes.length; i++) {
      const ni = nodes[i];
      const di = distFromCenter(ni);
      // Connection distance shrinks further from center
      const localConnect = CONNECT_DIST * Math.max(0.4, 1 - di / (maxDist * 1.5));

      for (let j = i + 1; j < nodes.length; j++) {
        const nj = nodes[j];
        const d = dist(ni, nj);
        if (d < localConnect) {
          const alpha = 1 - d / localConnect;
          const energy = Math.max(ni.energy, nj.energy);
          const avgDist = (di + distFromCenter(nj)) / 2;
          // Fade with distance from center
          const centerFade = Math.max(0.15, 1 - avgDist / maxDist);

          // Propagate energy
          if (ni.energy > 0.2 && d < localConnect * 0.7) {
            nj.energy = Math.max(nj.energy, ni.energy * 0.5);
          }
          if (nj.energy > 0.2 && d < localConnect * 0.7) {
            ni.energy = Math.max(ni.energy, nj.energy * 0.5);
          }

          const r = WARM[0] + (GREEN[0] - WARM[0]) * energy;
          const g = WARM[1] + (GREEN[1] - WARM[1]) * energy;
          const b = WARM[2] + (GREEN[2] - WARM[2]) * energy;

          // Thicker + brighter near center, thinner at edges
          const lineAlpha = (alpha * 0.25 + energy * alpha * 0.4) * centerFade;
          const lineWidth = (0.4 + energy * 0.8) * centerFade + 0.1;

          ctx.beginPath();
          ctx.moveTo(ni.x, ni.y);
          ctx.lineTo(nj.x, nj.y);
          ctx.strokeStyle = `rgba(${r|0},${g|0},${b|0},${lineAlpha})`;
          ctx.lineWidth = lineWidth;
          ctx.stroke();
        }
      }
    }

    // ── Nodes ──
    for (const n of nodes) {
      n.x += n.vx;
      n.y += n.vy;

      // Soft boundary — drift back toward play area
      if (n.x < -20) n.vx += 0.02;
      if (n.x > W + 20) n.vx -= 0.02;
      if (n.y < -20) n.vy += 0.02;
      if (n.y > H + 20) n.vy -= 0.02;

      // Very gentle gravity toward center (keeps density)
      const dc = distFromCenter(n);
      if (dc > maxDist * 0.8) {
        n.vx += (center.x - n.x) * 0.00003;
        n.vy += (center.y - n.y) * 0.00003;
      }

      // Mouse interaction
      const md = dist(n, mouse);
      if (md < 200 && md > 1) {
        n.vx += (mouse.x - n.x) / md * 0.005;
        n.vy += (mouse.y - n.y) / md * 0.005;
        if (md < 100) n.energy = Math.max(n.energy, 0.5 * (1 - md / 100));
      }

      // Dampen
      n.vx *= 0.998;
      n.vy *= 0.998;

      // Decay energy
      n.energy *= n.fireDecay;
      if (n.energy < 0.005) n.energy = 0;

      // Distance-based fade
      const centerFade = Math.max(0.1, 1 - dc / maxDist);

      const nr = WARM[0] + (GREEN[0] - WARM[0]) * n.energy;
      const ng = WARM[1] + (GREEN[1] - WARM[1]) * n.energy;
      const nb = WARM[2] + (GREEN[2] - WARM[2]) * n.energy;
      const nodeAlpha = (0.3 + n.energy * 0.6) * centerFade;
      const nodeR = (n.baseR + n.energy * 2.5) * (0.6 + centerFade * 0.4);

      ctx.beginPath();
      ctx.arc(n.x, n.y, nodeR, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${nr|0},${ng|0},${nb|0},${nodeAlpha})`;
      ctx.fill();

      // Glow
      if (n.energy > 0.25) {
        ctx.beginPath();
        ctx.arc(n.x, n.y, nodeR + n.energy * 8, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${GREEN[0]},${GREEN[1]},${GREEN[2]},${n.energy * 0.12 * centerFade})`;
        ctx.fill();
      }
    }

    requestAnimationFrame(draw);
  }

  window.addEventListener('resize', resize);
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
