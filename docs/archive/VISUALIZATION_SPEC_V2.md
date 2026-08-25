> **SUPERSEDED, 2026-08-25.** Describes an early speculative architecture (a Rust/"Zulu DB" system at 10M+ node scale) that was never built. The actual implementation is SQLite WAL + NetworkX (see README.md, CHANGELOG.md). Kept for history, not current status.

# NoUse Visualization Specification v2.0
## Inspired by Biological Neural Networks
**Date:** 2026-04-02 08:11
**Author:** Base76 Agent Collective
**Status:** Enhancement to FNC Implementation Spec

---

## 🎨 NYCKELFÖRBÄTTRINGAR (från rio_roue analys)

### 1. REAL-TIME NEURAL ACTIVITY VISUALIZATION

**BEFORE (v1.0):**
- Statisk graf (nodes + edges)
- Uppdateras på query

**AFTER (v2.0):**
- **Live 3D neural field** (1,000+ nodes visible)
- **Spiking activity** (pulserande noder vid activation)
- **Synaptic transmission** (animerade signalspridning)
- **Continuous rendering** (60 FPS, WebGL)

**Technical:**
```typescript
// Three.js + WebGL 2.0
const neuralField = new InstancedMesh(1000);  // GPU-instanced nodes
const synapses = new LineSegments(edges);      // Dynamic connections
const activityBuffer = new Float32Array(1000); // Real-time state

// Animation loop
function render() {
  updateNodeActivities();  // From Rust core
  updateSynapticFlows();   // Animate signals
  neuralField.update();      // GPU batch update
}
```

---

### 2. BRAIN REGION OVERLAYS (FNC-Aligned)

**rio_roue regions:**
```
META CONTROL    46.1%
WORKING MEMORY   4.3%
PREDICTIVE      15.0%
MOTOR CORTEX     2.3%
CEREBELLUM       7.0%
REFLEX ARC      19.4%
BRAINSTEM        4.6%
```

**NoUse FNC regions:**
```
┌─────────────────────────────────────────┐
│  PREFRONTAL CORTEX (Working Memory)     │  7 slots
│  └── Current context, active reasoning   │
│                                         │
│  TEMPORAL LOBE (Episodic Memory)        │  Past events
│  └── When, where, what happened          │
│                                         │
│  PARIETAL LOBE (Semantic Network)       │  Knowledge
│  └── Facts, concepts, relations           │
│                                         │
│  LIMBIC SYSTEM (Emotional Layer)        │  ⚡ NEW
│  └── Saliency, urgency, dopamine          │
│                                         │
│  PREDICTIVE CORTEX (Projection)           │  ⚡ NEW
│  └── Pattern prediction, anticipation     │
└─────────────────────────────────────────┘
```

**Visual:**
- **Color-coded regions** (olika färger per lobe)
- **Transparency** (visa flera lager samtidigt)
- **Zoom-to-region** (fokusera på specifik area)
- **Cross-region connections** (synapser mellan lober)

---

### 3. NEUROTRANSMITTER ANALOGY (NEW)

**Concept:** Simulera "kemiska" tillstånd för systemets hälsa.

| Analogi | Function | Visual |
|---------|----------|--------|
| **DA** (Dopamine) | Motivation, reward | 🟢 Activity level |
| **ACH** (Acetylcholine) | Attention, learning | 🔵 Focus intensity |
| **NE** (Norepinephrine) | Alertness, urgency | 🔴 System load |
| **5HT** (Serotonin) | Stability, mood | 🟡 Confidence score |

**Dashboard:**
```
DA  [████████░░] 80%  Active
ACH [██████░░░░] 60%  Learning
NE  [███░░░░░░░] 30%  Low load
5HT [██████████] 100% Stable
```

**Implementation:**
```rust
struct SystemState {
    dopamine: f32,      // Activity rate (queries/sec)
    acetylcholine: f32, // Learning rate (new nodes/sec)
    norepinephrine: f32, // Queue depth (pending tasks)
    serotonin: f32,     // Confidence (avg claim strength)
}
```

---

### 4. ACTIVITY METRICS DISPLAY

**rio_roue style:**
```
Step: 2.00M          Rate: 0.55 steps/sec
Status: JUVENILE
```

**NoUse metrics:**
```
Nodes:     3,247      Active:    7/7 WM slots
Edges:    11,096      Rate:      42 queries/sec
Episodes:  3,276      Status:    MATURE
Facts:    10,996      Health:    ●●●●○ (80%)
Cycles:  334,000+     Load:      45%
```

**Status labels:**
- **SPAWNING** → Initializing
- **JUVENILE** → Learning (first 1000 nodes)
- **MATURE** → Operational
- **SAGE** → Highly connected (>10k nodes)
- **OVERLOAD** → Working memory full, need rest

---

### 5. INTERACTIVE TOOLTIPS & LAYERS

**Hover over node:**
```
┌─────────────────────┐
│ Node #4,721         │
│ Type: Concept       │
│ Region: Temporal    │
│                     │
│ "Consciousness"     │
│ Confidence: 0.89    │
│ Last used: 3s ago   │
│ Depth: Layer 2/4    │
│                     │
│ [Click to expand]   │
└─────────────────────┘
```

**Click to expand (Layer 3):**
- Full context
- Source citations
- Related hypotheses
- Falsification criteria
- Axon connections (related nodes)

---

### 6. AXON ACTIVITY VISUALIZATION

**BEFORE:** Static edges
**AFTER:** Active seeking

```
Node A ----→ Node B  (strong connection, solid)
      ~~→ Node C    (weak, searching, dashed)
      ~~→ [?]       (axon seeking, animated)
```

**Visual cues:**
- **Solid lines** = Confirmed connections
- **Dashed** = Weak/temporal
- **Animated pulses** = Signal transmission
- **Glowing endpoints** = Active axon search

---

## 🛠️ TECHNICAL STACK (Updated)

### Backend (Rust)
```
crates/
├── nouse-core/       # FNC implementation
├── nouse-mcp/        # MCP server
├── nouse-storage/    # Zulu DB
├── nouse-realtime/   # ⚡ NEW - WebSocket server
│   ├── state_stream.rs    # Live state broadcast
│   ├── activity_calc.rs   # Neurotransmitter analogs
│   └── region_mapper.rs   # Brain region classification
└── nouse-cli/
```

### Frontend (TypeScript + WebGL)
```
frontend/
├── dashboard/
│   ├── NeuralField.tsx      # Three.js 3D view
│   ├── RegionOverlay.tsx    # Brain region layers
│   ├── MetricsPanel.tsx     # Real-time stats
│   ├── Neurotransmitters.tsx # DA/ACH/NE/5HT bars
│   └── NodeInspector.tsx    # Tooltip + depth navigation
├── shared/
│   └── WebSocketClient.ts   # Real-time connection
└── public/
    └── shaders/             # Custom GLSL shaders
```

---

## 📊 UI LAYOUT

```
┌──────────────────────────────────────────────────────────┐
│  NoUse Neural Field                 [Metrics] [Status]  │
│  ┌─────────────────────────────────┐  ┌──────────────┐   │
│  │                                 │  │ Nodes: 3,247 │   │
│  │    🧠  3D NEURAL GRAPH          │  │ Edges: 11K   │   │
│  │                                 │  │ Active: 7/7  │   │
│  │  ○───○        ○                 │  │ Status: SAGE │   │
│  │  │╲  ╱│      ╱│╲               │  └──────────────┘   │
│  │  ●───●     ○───○              │                     │
│  │                                 │  [DA:████░░░░] 80%  │
│  │   (Prefrontal)   (Temporal)     │  [ACH:██░░░░░] 40% │
│  │                                 │  [NE:███░░░░░] 30% │
│  │  Click node → Expand layers     │  [5HT:██████░] 60% │
│  │                                 │                     │
│  └─────────────────────────────────┘                     │
│  [Regions ▼] [Filter ▼] [Time: Real-time ▼]             │
└──────────────────────────────────────────────────────────┘
```

---

## 🎯 IMPLEMENTATION PRIORITY

### Phase 1: Core (v1.0)
- ✅ Basic graph (nodes + edges)
- ✅ Working memory (7 slots)
- ✅ Query system

### Phase 2: Real-time (v1.5) ⚡
- [ ] WebSocket connection
- [ ] Live activity updates
- [ ] Basic neurotransmitters (4 bars)
- [ ] Status labels

### Phase 3: Visualization (v2.0) 🎨
- [ ] 3D Three.js graph
- [ ] Brain region overlays
- [ ] Animated axons
- [ ] Interactive tooltips

### Phase 4: Polish (v2.5) ✨
- [ ] Custom shaders
- [ ] Advanced metrics
- [ ] Performance optimization
- [ ] Mobile responsive

---

*Enhancement based on: rio_roue "Ocean Neural Network" visualization*
*Date: 2026-04-02 08:11*
