/**
 * brain_view.js — 3D Brain visualization for Nous
 *
 * A semi-transparent 3D brain model where each region lights up
 * when data is added. Inspired by fMRI heatmaps and the user's vision
 * of "a visual brain that lights up in each area when data is added."
 *
 * Regions are defined in brain_topology.py with 3D positions.
 * Heatmap data from /api/brain_regions/heat drives intensity.
 * SSE events trigger real-time region activation.
 *
 * Three.js scene with:
 *   - Semi-transparent brain mesh (ellipsoid)
 *   - Glowing region spheres at anatomical positions
 *   - Nerve pathway beams between active regions
 *   - Bisociation flashes (lightning between distant regions)
 *   - Pulse animation on new concept addition
 */

(function() {
  'use strict';

  // ── Region definitions (mirrors brain_topology.py) ───────────────
  const REGIONS = {
    prefrontal:     { label: 'Prefrontal cortex',    pos: [0, 25, 105],   color: '#ffd700', desc: 'Metakognition, syntes' },
    frontal:        { label: 'Frontallob',            pos: [0, 0, 85],      color: '#4e9af1', desc: 'Logik, beslut' },
    parietal:       { label: 'Parietallob',           pos: [0, 65, 40],     color: '#4ef1c4', desc: 'Integration, rumslig' },
    temporal_left:  { label: 'Temporallob (v)',       pos: [-85, 0, 0],     color: '#b04ef1', desc: 'Språk, semantik' },
    temporal_right:{ label: 'Temporallob (h)',        pos: [85, 0, 0],      color: '#f14eb0', desc: 'Kreativitet, musik' },
    occipital:      { label: 'Occipitallob',           pos: [0, 0, -85],     color: '#f1c44e', desc: 'Mönster, klassificering' },
    hippocampus:    { label: 'Hippocampus',            pos: [0, -40, 10],    color: '#4ef160', desc: 'Minne, inlärning' },
    amygdala:       { label: 'Amygdala',               pos: [32, -52, 12],   color: '#f16b4e', desc: 'Emotion, risk' },
    cerebellum:     { label: 'Lillhjärnan',             pos: [0, -82, -55],   color: '#8af14e', desc: 'Procedurellt, automatik' },
    brainstem:      { label: 'Hjärnstam',               pos: [0, -105, 0],   color: '#f14e4e', desc: 'Axiom, fundamentala' },
    corpus_callosum:{ label: 'Corpus callosum',        pos: [0, 0, 0],      color: '#ffffff', desc: 'Korsdomän-bryggor' },
  };

  let scene, camera, renderer, brainGroup;
  let regionMeshes = {};
  let heatData = {};
  let pulseEffects = [];
  let animFrame;
  let clock;
  let nervePathCurves = [];   // {curve, particleGroup} — resande signaler
  let energyParticles = [];   // {mesh, curveIdx, t, speed}
  let isDragging = false;     // pausar auto-rotation medan man drar

  // ── Three.js setup ────────────────────────────────────────────────

  function init(container) {
    const W = container.clientWidth || window.innerWidth;
    const H = container.clientHeight || window.innerHeight;

    scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x120d18, 0.0018);

    camera = new THREE.PerspectiveCamera(50, W / H, 1, 2000);
    camera.position.set(0, 20, 280);
    camera.lookAt(0, -20, 0);

    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(W, H);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.2;
    container.appendChild(renderer.domElement);

    clock = new THREE.Clock();
    brainGroup = new THREE.Group();
    scene.add(brainGroup);

    // Ambient light
    const ambient = new THREE.AmbientLight(0x404050, 0.6);
    scene.add(ambient);

    // Point lights
    const keyLight = new THREE.PointLight(0xd88d3f, 1.2, 600);
    keyLight.position.set(100, 150, 200);
    scene.add(keyLight);

    const fillLight = new THREE.PointLight(0x4e9af1, 0.4, 400);
    fillLight.position.set(-150, -50, -100);
    scene.add(fillLight);

    // Build brain geometry
    buildBrain();
    buildRegions();
    buildNervePaths();

    // Load initial heat data
    fetchHeat();

    // Start animation
    animate();

    // Orbit controls (simple drag)
    setupOrbit(container);

    // Resize
    window.addEventListener('resize', () => {
      const w = container.clientWidth || window.innerWidth;
      const h = container.clientHeight || window.innerHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    });
  }

  // ── Brain mesh (semi-transparent ellipsoid) ──────────────────────

  function buildBrain() {
    // Outer brain shell — two hemispheres
    const brainGeo = new THREE.SphereGeometry(110, 64, 48);
    brainGeo.scale(1.0, 0.85, 1.2);

    const brainMat = new THREE.MeshPhysicalMaterial({
      color: 0xe8d8c8,
      transparent: true,
      opacity: 0.08,
      roughness: 0.7,
      metalness: 0.05,
      transmission: 0.6,
      thickness: 0.5,
      side: THREE.DoubleSide,
      depthWrite: false,
    });

    const brainMesh = new THREE.Mesh(brainGeo, brainMat);
    brainGroup.add(brainMesh);

    // Fissure lines (subtle grooves)
    const fissureMat = new THREE.LineBasicMaterial({
      color: 0x8b7678,
      transparent: true,
      opacity: 0.15,
    });

    // Central fissure (coronal)
    const centralFissure = new THREE.EllipseCurve(0, 0, 95, 110, 0, Math.PI * 2, false);
    const centralPoints = centralFissure.getPoints(64);
    const centralGeo = new THREE.BufferGeometry().setFromPoints(
      centralPoints.map(p => new THREE.Vector3(0, p.y, p.x * 0.9))
    );
    brainGroup.add(new THREE.Line(centralGeo, fissureMat));

    // Lateral fissure (sylvian)
    const lateralPoints = [];
    for (let i = 0; i <= 32; i++) {
      const t = i / 32;
      const x = -80 + t * 160;
      const z = -40 + Math.sin(t * Math.PI) * 20;
      lateralPoints.push(new THREE.Vector3(x, 5, z));
    }
    const lateralGeo = new THREE.BufferGeometry().setFromPoints(lateralPoints);
    brainGroup.add(new THREE.Line(lateralGeo, fissureMat));
  }

  // ── Region spheres ──────────────────────────────────────────────

  function buildRegions() {
    for (const [name, region] of Object.entries(REGIONS)) {
      const [x, y, z] = region.pos;
      const color = new THREE.Color(region.color);

      // Region sphere (inner glow)
      const radius = name === 'corpus_callosum' ? 12 : 18;
      const sphereGeo = new THREE.SphereGeometry(radius, 32, 24);
      const sphereMat = new THREE.MeshPhysicalMaterial({
        color: color,
        emissive: color,
        emissiveIntensity: 0.15,
        transparent: true,
        opacity: 0.3,
        roughness: 0.3,
        metalness: 0.1,
        clearcoat: 0.5,
      });

      const mesh = new THREE.Mesh(sphereGeo, sphereMat);
      mesh.position.set(x, y, z);
      mesh.userData = { regionName: name, baseIntensity: 0.15, targetIntensity: 0.15 };
      brainGroup.add(mesh);
      regionMeshes[name] = mesh;

      // Outer glow ring
      const glowGeo = new THREE.RingGeometry(radius + 2, radius + 8, 32);
      const glowMat = new THREE.MeshBasicMaterial({
        color: color,
        transparent: true,
        opacity: 0.08,
        side: THREE.DoubleSide,
        depthWrite: false,
      });
      const glowMesh = new THREE.Mesh(glowGeo, glowMat);
      glowMesh.position.set(x, y, z);
      glowMesh.lookAt(camera.position);
      mesh.userData.glowMesh = glowMesh;
      brainGroup.add(glowMesh);

      // Label sprite
      const labelSprite = createLabel(region.label, region.color);
      labelSprite.position.set(x, y + 22, z);
      labelSprite.userData.regionName = name;
      brainGroup.add(labelSprite);
    }
  }

  function createLabel(text, color) {
    const canvas = document.createElement('canvas');
    canvas.width = 256;
    canvas.height = 64;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = color;
    ctx.font = 'bold 18px IBM Plex Sans, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(text, 128, 40);

    const texture = new THREE.CanvasTexture(canvas);
    const mat = new THREE.SpriteMaterial({
      map: texture,
      transparent: true,
      opacity: 0.85,
      depthWrite: false,
    });
    const sprite = new THREE.Sprite(mat);
    sprite.scale.set(40, 10, 1);
    return sprite;
  }

  // ── Nerve pathways ──────────────────────────────────────────────

  function buildNervePaths() {
    // Key nerve pathways between regions
    const pathways = [
      ['prefrontal', 'frontal'],
      ['frontal', 'parietal'],
      ['frontal', 'temporal_left'],
      ['parietal', 'occipital'],
      ['temporal_left', 'hippocampus'],
      ['temporal_right', 'hippocampus'],
      ['hippocampus', 'amygdala'],
      ['amygdala', 'brainstem'],
      ['cerebellum', 'brainstem'],
      ['prefrontal', 'amygdala'],
      ['corpus_callosum', 'temporal_left'],
      ['corpus_callosum', 'temporal_right'],
    ];

    nervePathCurves = [];

    for (const [a, b] of pathways) {
      const ra = REGIONS[a];
      const rb = REGIONS[b];
      if (!ra || !rb) continue;

      const [ax, ay, az] = ra.pos;
      const [bx, by, bz] = rb.pos;
      const mid = new THREE.Vector3((ax + bx) / 2, (ay + by) / 2 + 8, (az + bz) / 2);
      const curve = new THREE.QuadraticBezierCurve3(
        new THREE.Vector3(ax, ay, az), mid, new THREE.Vector3(bx, by, bz)
      );
      const points = curve.getPoints(20);

      const pathGeo = new THREE.BufferGeometry().setFromPoints(points);
      const pathMat = new THREE.LineBasicMaterial({
        color: 0x5a474a,
        transparent: true,
        opacity: 0.12,
      });
      brainGroup.add(new THREE.Line(pathGeo, pathMat));

      // Spara kurvan så en signal (energipartikel) kan färdas längs den
      // kontinuerligt — det är det som gör att grafen känns levande i
      // stället för en frusen illustration.
      nervePathCurves.push({ curve, colorA: new THREE.Color(ra.color), colorB: new THREE.Color(rb.color) });
    }

    // Ambienta signaler: några partiklar som alltid glider längs slumpade
    // banor, oavsett verklig aktivitet — ren atmosfär, inte ett mätvärde
    // (jämför stjärnfältet i Concept Atlas-vyn).
    const ambientCount = Math.min(10, nervePathCurves.length * 2);
    for (let i = 0; i < ambientCount; i++) {
      spawnEnergyParticle(Math.floor(Math.random() * nervePathCurves.length), 0.4 + Math.random() * 0.5);
    }
  }

  function spawnEnergyParticle(curveIdx, speed) {
    const path = nervePathCurves[curveIdx];
    if (!path) return;
    const geo = new THREE.SphereGeometry(1.3, 8, 8);
    const color = Math.random() < 0.5 ? path.colorA : path.colorB;
    const mat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.85 });
    const mesh = new THREE.Mesh(geo, mat);
    brainGroup.add(mesh);
    energyParticles.push({ mesh, curveIdx, t: Math.random(), speed: speed || 0.5 });
  }

  // ── Heat data ───────────────────────────────────────────────────

  async function fetchHeat() {
    try {
      const resp = await fetch('/api/brain_regions/heat');
      const data = await resp.json();
      if (data.ok) {
        heatData = data.heat;
        updateRegionIntensities();
      }
    } catch (e) {
      // Silent fail
    }
  }

  function updateRegionIntensities() {
    for (const [name, heat] of Object.entries(heatData)) {
      const mesh = regionMeshes[name];
      if (!mesh) continue;

      const intensity = Math.max(0.15, heat.intensity || 0);
      mesh.userData.targetIntensity = intensity;

      // Scale based on activity
      const baseScale = 1.0;
      const activeScale = baseScale + intensity * 0.4;
      mesh.scale.setScalar(activeScale);
    }
  }

  // ── Pulse effects (on SSE events) ──────────────────────────────

  function pulseRegion(regionName) {
    const mesh = regionMeshes[regionName];
    if (!mesh) return;

    // Flash intensity
    mesh.userData.targetIntensity = 1.0;

    // Create pulse ring
    const [x, y, z] = REGIONS[regionName]?.pos || [0, 0, 0];
    const ringGeo = new THREE.RingGeometry(5, 30, 32);
    const ringMat = new THREE.MeshBasicMaterial({
      color: new THREE.Color(REGIONS[regionName]?.color || '#ffffff'),
      transparent: true,
      opacity: 0.6,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const ring = new THREE.Mesh(ringGeo, ringMat);
    ring.position.set(x, y, z);
    ring.lookAt(camera.position);
    brainGroup.add(ring);

    pulseEffects.push({
      mesh: ring,
      life: 1.0,
      decay: 0.015,
    });

    // Decay back after pulse
    setTimeout(() => {
      if (mesh.userData.targetIntensity > 0.5) {
        mesh.userData.targetIntensity = heatData[regionName]?.intensity || 0.15;
      }
    }, 800);
  }

  // ── Bisociation flash ───────────────────────────────────────────

  function bisociationFlash(regionA, regionB) {
    const ra = REGIONS[regionA];
    const rb = REGIONS[regionB];
    if (!ra || !rb) return;

    const [ax, ay, az] = ra.pos;
    const [bx, by, bz] = rb.pos;

    // Lightning bolt between regions
    const points = [];
    const segments = 12;
    for (let i = 0; i <= segments; i++) {
      const t = i / segments;
      const x = ax + (bx - ax) * t + (Math.random() - 0.5) * 20;
      const y = ay + (by - ay) * t + (Math.random() - 0.5) * 20;
      const z = az + (bz - az) * t + (Math.random() - 0.5) * 20;
      points.push(new THREE.Vector3(x, y, z));
    }

    const geo = new THREE.BufferGeometry().setFromPoints(points);
    const mat = new THREE.LineBasicMaterial({
      color: 0xffd700,
      transparent: true,
      opacity: 1.0,
      linewidth: 2,
    });
    const bolt = new THREE.Line(geo, mat);
    brainGroup.add(bolt);

    pulseEffects.push({
      mesh: bolt,
      life: 1.0,
      decay: 0.03,
      isBolt: true,
    });
  }

  // ── Animation loop ──────────────────────────────────────────────

  function animate() {
    animFrame = requestAnimationFrame(animate);
    const dt = clock.getDelta();
    const time = clock.getElapsedTime();

    // Smooth intensity transitions
    for (const [name, mesh] of Object.entries(regionMeshes)) {
      const current = mesh.material.emissiveIntensity;
      const target = mesh.userData.targetIntensity;
      const speed = 2.0;
      const next = current + (target - current) * Math.min(1, dt * speed);
      mesh.material.emissiveIntensity = next;

      // Glow mesh opacity follows intensity
      if (mesh.userData.glowMesh) {
        mesh.userData.glowMesh.material.opacity = 0.05 + next * 0.25;
        mesh.userData.glowMesh.lookAt(camera.position);
      }
    }

    // Pulse effects
    for (let i = pulseEffects.length - 1; i >= 0; i--) {
      const fx = pulseEffects[i];
      fx.life -= fx.decay;

      if (fx.isBolt) {
        fx.mesh.material.opacity = Math.max(0, fx.life);
      } else {
        const scale = 1 + (1 - fx.life) * 3;
        fx.mesh.scale.setScalar(scale);
        fx.mesh.material.opacity = Math.max(0, fx.life * 0.6);
      }

      if (fx.life <= 0) {
        brainGroup.remove(fx.mesh);
        fx.mesh.geometry.dispose();
        fx.mesh.material.dispose();
        pulseEffects.splice(i, 1);
      }
    }

    // Kontinuerlig, långsam svävning — ett levande objekt i rymden,
    // inte en fryst illustration. Pausas medan användaren själv drar.
    if (!isDragging) {
      brainGroup.rotation.y = time * 0.045;
      brainGroup.rotation.x = Math.sin(time * 0.07) * 0.06;
    }

    // Energipartiklar — signaler som färdas mellan regioner längs
    // nervbanorna. Det här är fMRI-känslan: synlig, riktad rörelse
    // mellan fält, inte bara statiska linjer.
    for (const p of energyParticles) {
      const path = nervePathCurves[p.curveIdx];
      if (!path) continue;
      p.t += dt * p.speed * 0.3;
      if (p.t > 1) p.t -= 1;
      const pos = path.curve.getPoint(p.t);
      p.mesh.position.copy(pos);
      const pulse = 0.7 + 0.3 * Math.sin(time * 4 + p.curveIdx);
      p.mesh.material.opacity = 0.5 + 0.35 * pulse;
    }

    renderer.render(scene, camera);
  }

  // ── Simple orbit controls ───────────────────────────────────────

  function setupOrbit(container) {
    // isDragging är modulnivå (delad med auto-rotation i animate())
    let prevX = 0, prevY = 0;
    let rotX = 0, rotY = 0;

    container.addEventListener('mousedown', (e) => {
      isDragging = true;
      prevX = e.clientX;
      prevY = e.clientY;
    });

    window.addEventListener('mousemove', (e) => {
      if (!isDragging) return;
      const dx = e.clientX - prevX;
      const dy = e.clientY - prevY;
      rotY += dx * 0.005;
      rotX += dy * 0.005;
      rotX = Math.max(-1.2, Math.min(1.2, rotX));
      prevX = e.clientX;
      prevY = e.clientY;

      brainGroup.rotation.set(rotX, rotY, 0);
    });

    window.addEventListener('mouseup', () => { isDragging = false; });

    // Zoom
    container.addEventListener('wheel', (e) => {
      e.preventDefault();
      camera.position.z += e.deltaY * 0.3;
      camera.position.z = Math.max(100, Math.min(500, camera.position.z));
    }, { passive: false });
  }

  // ── SSE integration ──────────────────────────────────────────────

  function connectSSE(source) {
    if (!source) return;
    source.addEventListener('node_added', (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.domain) {
          // Classify domain → region and pulse
          const region = classifyDomainSimple(data.domain);
          pulseRegion(region);
        }
      } catch (err) {}
    });

    source.addEventListener('edge_added', (e) => {
      try {
        const data = JSON.parse(e.data);
        // Edge between different regions = nerve pathway activation
        if (data.src_domain && data.tgt_domain && data.src_domain !== data.tgt_domain) {
          const ra = classifyDomainSimple(data.src_domain);
          const rb = classifyDomainSimple(data.tgt_domain);
          if (ra !== rb) {
            // Subtle pulse on both regions
            pulseRegion(ra);
            pulseRegion(rb);
          }
        }
      } catch (err) {}
    });

    source.addEventListener('meta_axiom', (e) => {
      try {
        const data = JSON.parse(e.data);
        // Meta axioms = prefrontal activity
        pulseRegion('prefrontal');
      } catch (err) {}
    });

    source.addEventListener('synapse_formed', (e) => {
      try {
        const data = JSON.parse(e.data);
        // En synaps är en verklig strukturell isomorfi mellan två domäner
        // (axon_growth_cone.py) — Koestlers bisociation, inte bara en
        // pulsering. Blixtra mellan de faktiska regionerna i stället för
        // ett generiskt hippocampus-pulse. Lager 3, docs/BRAIN_VIEW_REDESIGN.md.
        if (data.domain_src && data.domain_tgt) {
          const ra = classifyDomainSimple(data.domain_src);
          const rb = classifyDomainSimple(data.domain_tgt);
          if (ra !== rb) {
            bisociationFlash(ra, rb);
          } else {
            pulseRegion(ra);
          }
        } else {
          pulseRegion('hippocampus');
        }
      } catch (err) {}
    });
  }

  // Simple domain → region classification (mirrors brain_topology.py keywords)
  function classifyDomainSimple(domain) {
    const d = (domain || '').toLowerCase();
    if (d.startsWith('meta::') || d.startsWith('meta_')) return 'prefrontal';
    if (d.includes('bridge') || d.includes('syntes_') || d.includes('brygga')) return 'hippocampus';

    // Keyword matching
    const kwMap = {
      prefrontal: ['meta', 'synth', 'reflex', 'plan', 'abstract', 'strategi'],
      frontal: ['math', 'logic', 'formal', 'proof', 'decision', 'reason', 'algebra'],
      parietal: ['spatial', 'causal', 'integrat', 'relation', 'system', 'network', 'physic', 'fysik'],
      temporal_left: ['lingu', 'lang', 'semant', 'syntax', 'narrat', 'text', 'communic'],
      temporal_right: ['creat', 'music', 'art', 'aesth', 'improv', 'humor', 'design', 'analogi'],
      occipital: ['pattern', 'classif', 'recog', 'vision', 'neural', 'ml', 'deep_learn'],
      hippocampus: ['memory', 'episod', 'learn', 'bridge', 'assoc', 'navigat', 'crystal'],
      amygdala: ['emot', 'value', 'ethic', 'moral', 'motiv', 'reward', 'arousal', 'risk'],
      cerebellum: ['procedur', 'automat', 'algorit', 'techni', 'engineer', 'program', 'tool'],
      brainstem: ['axiom', 'fundament', 'base', 'origin', 'constant', 'ontolog', 'daemon'],
    };

    for (const [region, keywords] of Object.entries(kwMap)) {
      for (const kw of keywords) {
        if (d.includes(kw)) return region;
      }
    }
    return 'corpus_callosum';
  }

  // ── Refresh heat data periodically ──────────────────────────────

  setInterval(fetchHeat, 30000);

  // ── Public API ──────────────────────────────────────────────────

  window.brainViewInit = function(graphData, sseSource) {
    const container = document.getElementById('brain-container');
    if (!container) return;
    container.style.display = 'block';
    init(container);
    if (sseSource) connectSSE(sseSource);
  };

  window.brainViewPulse = function(regionName) {
    pulseRegion(regionName);
  };

  window.brainViewBisociation = function(regionA, regionB) {
    bisociationFlash(regionA, regionB);
  };

  window.brainViewDestroy = function() {
    if (animFrame) cancelAnimationFrame(animFrame);
    const container = document.getElementById('brain-container');
    if (container && renderer) {
      container.removeChild(renderer.domElement);
    }
  };

})();