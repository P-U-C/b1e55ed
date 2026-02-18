// synapses.js — Neural mesh background
// Subtle particle nodes with pulsing connections
// Inspired by: fred again.. Vancouver light show

(function () {
  const canvas = document.createElement('canvas');
  canvas.id = 'synapses';
  canvas.style.cssText =
    'position:fixed;inset:0;z-index:0;pointer-events:none;opacity:0.4;';
  document.body.prepend(canvas);

  const ctx = canvas.getContext('2d');
  let W, H, nodes, mouse;
  const NODE_COUNT = 80;
  const CONNECT_DIST = 160;
  const PULSE_CHANCE = 0.003; // chance per frame a node fires
  const BASE_SPEED = 0.15;

  // Color from PUC green, very dim
  const NODE_COLOR = [34, 197, 94]; // #22C55E
  const WARM_COLOR = [176, 172, 164]; // #b0aca4 warm neutral

  function resize() {
    W = canvas.width = window.innerWidth;
    H = canvas.height = window.innerHeight;
  }

  function createNode() {
    return {
      x: Math.random() * W,
      y: Math.random() * H,
      vx: (Math.random() - 0.5) * BASE_SPEED,
      vy: (Math.random() - 0.5) * BASE_SPEED,
      r: Math.random() * 1.5 + 0.5,
      energy: 0,       // 0 = resting, 1 = firing
      fireDecay: 0.97, // how fast energy fades
    };
  }

  function init() {
    resize();
    nodes = [];
    for (let i = 0; i < NODE_COUNT; i++) nodes.push(createNode());
    mouse = { x: -9999, y: -9999 };
  }

  function dist(a, b) {
    const dx = a.x - b.x;
    const dy = a.y - b.y;
    return Math.sqrt(dx * dx + dy * dy);
  }

  function draw() {
    ctx.clearRect(0, 0, W, H);

    // Random firing — synapses activating
    for (const n of nodes) {
      if (n.energy < 0.01 && Math.random() < PULSE_CHANCE) {
        n.energy = 1;
      }
    }

    // Connections
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const d = dist(nodes[i], nodes[j]);
        if (d < CONNECT_DIST) {
          const alpha = (1 - d / CONNECT_DIST);
          const energy = Math.max(nodes[i].energy, nodes[j].energy);

          // Propagate energy through connections (like neural impulse)
          if (nodes[i].energy > 0.3 && d < CONNECT_DIST * 0.6) {
            nodes[j].energy = Math.max(nodes[j].energy, nodes[i].energy * 0.4);
          }
          if (nodes[j].energy > 0.3 && d < CONNECT_DIST * 0.6) {
            nodes[i].energy = Math.max(nodes[i].energy, nodes[j].energy * 0.4);
          }

          // Blend color: warm neutral base → green when energized
          const r = WARM_COLOR[0] + (NODE_COLOR[0] - WARM_COLOR[0]) * energy;
          const g = WARM_COLOR[1] + (NODE_COLOR[1] - WARM_COLOR[1]) * energy;
          const b = WARM_COLOR[2] + (NODE_COLOR[2] - WARM_COLOR[2]) * energy;

          const lineAlpha = alpha * 0.12 + energy * alpha * 0.2;

          ctx.beginPath();
          ctx.moveTo(nodes[i].x, nodes[i].y);
          ctx.lineTo(nodes[j].x, nodes[j].y);
          ctx.strokeStyle = `rgba(${r|0},${g|0},${b|0},${lineAlpha})`;
          ctx.lineWidth = 0.5 + energy * 0.5;
          ctx.stroke();
        }
      }
    }

    // Nodes
    for (const n of nodes) {
      // Move
      n.x += n.vx;
      n.y += n.vy;

      // Bounce softly
      if (n.x < 0 || n.x > W) n.vx *= -1;
      if (n.y < 0 || n.y > H) n.vy *= -1;

      // Slight drift toward mouse (subtle attraction)
      const md = dist(n, mouse);
      if (md < 250 && md > 1) {
        n.vx += (mouse.x - n.x) / md * 0.003;
        n.vy += (mouse.y - n.y) / md * 0.003;
        // Mouse proximity energizes nearby nodes
        if (md < 120) n.energy = Math.max(n.energy, 0.3 * (1 - md / 120));
      }

      // Dampen velocity
      n.vx *= 0.999;
      n.vy *= 0.999;

      // Decay energy
      n.energy *= n.fireDecay;
      if (n.energy < 0.005) n.energy = 0;

      // Draw node
      const nr = WARM_COLOR[0] + (NODE_COLOR[0] - WARM_COLOR[0]) * n.energy;
      const ng = WARM_COLOR[1] + (NODE_COLOR[1] - WARM_COLOR[1]) * n.energy;
      const nb = WARM_COLOR[2] + (NODE_COLOR[2] - WARM_COLOR[2]) * n.energy;
      const nodeAlpha = 0.15 + n.energy * 0.5;

      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r + n.energy * 2, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${nr|0},${ng|0},${nb|0},${nodeAlpha})`;
      ctx.fill();

      // Glow on energized nodes
      if (n.energy > 0.3) {
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r + n.energy * 6, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${NODE_COLOR[0]},${NODE_COLOR[1]},${NODE_COLOR[2]},${n.energy * 0.08})`;
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
  draw();
})();
