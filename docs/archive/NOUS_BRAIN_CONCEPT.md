> **SUPERSEDED, 2026-08-25.** Describes an early speculative architecture (a Rust/"Zulu DB" system at 10M+ node scale) that was never built. The actual implementation is SQLite WAL + NetworkX (see README.md, CHANGELOG.md). Kept for history, not current status.

# NOUSE BRAIN: SeaCast + FNC Integration Concept
## Björn's Vision: 2026-04-02 08:37

---

## 🎯 KÄRNIDÉ

**Ta SeaCast's (eller liknande) graf-baserade neurala nätverk + Lägg till Nous's FNC-funktionalitet = En faktisk AI-hjärna**

---

## 🔧 TEKNISK ARKITEKTUR

### Layer 1: Graf-Nätverk (från SeaCast/GLONET)

```python
# Hierarchical Graph Neural Network
class OceanGraphNet:
    def __init__(self):
        self.nodes = 10_000_000    # 10M noder
        self.edges = 1_000_000_000  # 1B kopplingar
        self.layers = hierarchical  # Global → Regional → Local
    
    def forward(self, ocean_data):
        # Processar temperatur, ström, salinitet
        return prediction
```

**Vad det ger:**
- ✅ Massiv skalbarhet (10M+ noder)
- ✅ Hierarkisk struktur
- ✅ Real-time prediktion
- ✅ Effektiv GNN implementation

---

### Layer 2: Nous/FNC (Vår unika del)

```rust
// FNC-overlay på graf-nätverket
struct FNCNode {
    // Graf-nätverk identifierare
    graph_id: usize,           // Position i SeaCast
    
    // FNC-innehåll (detta är NYTT)
    semantic_content: String,   // "Ocean temperature Pacific 2026"
    episodic: EpisodicMemory,   // När/var lärde vi?
    layers: KnowledgeLayers,  // Surface → Deep
    
    // Plastisitet
    plasticity: PlasticityState,
    access_history: Vec<AccessEvent>,
    
    // Koppling till andra noder
    axons: Vec<ActiveAxon>,     // Dynamiska, sökande
}

struct PlasticityState {
    // LTP (Long-Term Potentiation)
    // LTD (Long-Term Depression)
    // Homeostatic scaling
    
    synaptic_strength: f32,      // Vikt
    stability: f32,              // Hur permanent?
    growth_rate: f32,            // Hur snabbt förändras?
}
```

---

### Layer 3: Unified Visualization

```
┌─────────────────────────────────────────────────────┐
│           NOUSE BRAIN VISUALIZATION                 │
├─────────────────────────────────────────────────────┤
│  SEACAST LAYER              FNC LAYER               │
│  ┌──────────┐              ┌──────────┐             │
│  │ ○───○    │  ← Graph    │ "Pacific │ ← Meaning │
│  │ │ ╲│     │    topology │  Temp"   │           │
│  │ ○───●    │              │ Deep:   │           │
│  │    │     │              │ Source: │           │
│  └──────────┘              │ NASA    │           │
│                            │ 2026    │           │
│                            └──────────┘           │
│                                                     │
│  [10M nodes]              [10M semantic entities]   │
│  [1B connections]         [1B meaningful relations] │
└─────────────────────────────────────────────────────┘
```

---

## 🧪 KONKRET EXEMPEL

### Scenario: "Vad är temperaturtrenden i Stilla Havet?"

**Traditionell SeaCast:**
```
Input:  [satellitdata 2026-04-02]
Process: GNN layers
Output: [prediktion 2026-04-09]
```

**Nous Brain (SeaCast + FNC):**
```
Input:  "Vad är temperaturtrenden i Stilla Havet?"
        ↓
FNC:     Parse → "Pacific" + "temperature" + "trend"
        ↓
Memory:  Hittar tidigare frågor om Pacific
         → "User asked similar on 2026-03-15"
         → "Related: El Niño pattern 2025"
        ↓
SeaCast: Kör GNN på aktuell data
         → High-res ocean forecast
        ↓
FNC:     Koppla resultat till existerande kunskap
         → "Temperature rising +2°C vs historical"
         → "Similar to 1997 El Niño pattern"
        ↓
Output:  "Stilla Havet visar +2°C trend, 
          liknar 1997 El Niño. 
          Du frågade om liknande 2026-03-15."
```

---

## 🎨 VISUALISERING (Unified)

### Real-time 3D View
```
┌──────────────────────────────────────────┐
│  NOUSE BRAIN - Pacific Ocean Focus       │
│                                          │
│     🌊 SEACAST LAYER (physics)          │
│        ○────○────○    (temperature)     │
│       ╱│    │╲   │                      │
│      ○─┼────┼─●──○    ◄── [HOT SPOT]    │
│        │    │   ╱│      pulserar         │
│       ○────○──○  ○                      │
│                                          │
│     🧠 FNC LAYER (meaning)              │
│        ┌─────────────┐                   │
│        │ "El Niño"   │                  │
│        │ Pattern     │◄── Connected     │
│        │ 1997        │    to hot spot    │
│        └─────────────┘                   │
│        ┌─────────────┐                   │
│        │ User Query  │◄── Historical     │
│        │ 2026-03-15  │    context       │
│        └─────────────┘                   │
│                                          │
│  [Physics] [Meaning] [History] [Predict]  │
└──────────────────────────────────────────┘
```

---

## 🔧 IMPLEMENTATION PATH

### Phase 1: Fork SeaCast
```bash
git clone https://github.com/deinal/seacast
cd seacast
# Analysera arkitektur
# Identifiera injektionspunkter för FNC
```

### Phase 2: FNC Overlay
```rust
// Ny modul: fnc_overlay
pub struct FNCOverlay {
    graph: Arc<Graph>,           // SeaCast's graf
    nodes: HashMap<usize, FNCNode>, // Vårt innehåll
    working_memory: WorkingMemory,  // 7 slots
}

impl FNCOverlay {
    pub fn attach_to_graph(&mut self, graph: Arc<Graph>) {
        // Koppla FNC-noder till graf-noder
    }
    
    pub fn query(&self, question: String) -> FNCResponse {
        // 1. Parse till koncept
        // 2. Sök i working memory
        // 3. Kör SeaCast om behövs
        // 4. Koppla resultat till minne
        // 5. Returnera med kontext
    }
}
```

### Phase 3: Unified Interface
```typescript
// Frontend: React + Three.js
interface BrainView {
    physicsLayer: SeaCastVisualization;
    meaningLayer: FNCVisualization;
    historyLayer: EpisodicTimeline;
}

// Real-time WebSocket från Rust
const ws = new WebSocket('ws://localhost:7676/brain');
ws.onmessage = (event) => {
    updateVisualization(JSON.parse(event.data));
};
```

---

## 💡 UNIK FÖRDEL

| System | Vad det har | Vad det saknar |
|--------|------------|----------------|
| SeaCast | Massiv skalbarhet, fysisk noggrannhet | Ingen "förståelse", ingen historia |
| Nous FNC | Meningsfull representation, minne | Ingen massiv skalbarhet (ännu) |
| **KOMBINERAT** | **Båda!** | **Inget** |

**Resultat:** En AI som både:
- ✅ Kan processa **10 miljarder** datapunkter (SeaCast)
- ✅ **Förstår** vad den processar (FNC)
- ✅ **Kommer ihåg** tidigare sammanhang (Episodic)
- ✅ **Förutser** behov (Predictive)

---

*Koncept: Björn Wikström, 2026-04-02 08:37*
*Inspiration: SeaCast, Ocean Neural Networks, FNC Theory*
