> **SUPERSEDED, 2026-08-25.** Describes an early speculative architecture (a Rust/"Zulu DB" system at 10M+ node scale) that was never built. The actual implementation is SQLite WAL + NetworkX (see README.md, CHANGELOG.md). Kept for history, not current status.

# FNC Implementation Specification
## For: brain-db-core / b76 / Nous
**Date:** 2026-04-02 00:26
**Author:** Björn Wikström
**Status:** Technical Specification

---

## Core Architecture: Neural-Inspired Knowledge Graph

### 1. Installation & Training

**User Experience:**
- Clean, visual installer
- Runs entirely on user's machine (local-first)
- Training sources:
  - Local documents
  - Wikipedia scrapes
  - LLM knowledge bases (configurable)
  - User's own data (b76 compatible)

### 2. Claims Analysis — "Minsta Gemensamma Nämnare"

**Concept:** Every claim/fact is analyzed to find its **minimal common denominator** with other nodes.

**Process:**
```
New claim enters → 
  Decompose to atomic assertions →
    Find overlap with existing nodes →
      Create/merge at finest granularity
```

**Example:**
- Input: "FNC is a consciousness architecture"
- Decomposed: ["FNC", "is", "consciousness", "architecture"]
- Connected to: ["FNC"→theory], ["consciousness"→philosophy], ["architecture"→systems]

### 3. Neural Pathways (Nervbanor)

**Structure:**
- **Nodes** = Concepts, claims, episodes
- **Edges** = Relationships (bi-directional)
- **Axons** = Active connection seekers

**Each edge has:**
- Strength (0.0-1.0)
- Type (semantic, temporal, causal, associative)
- **X "axons"** = active searchers looking for related concepts
- Activation history (when used, how often)

### 4. Node Depth — Layers

**Surface Layer (Entry Point):**
- Minimal representation
- Quick retrieval
- Links to deeper layers

**Deep Layers:**
- Full context
- Source citations
- Evidence strength
- Related hypotheses
- Falsification criteria

**Access Pattern:**
```
Query → Surface node → 
  [if relevant] → Layer 2 → 
    [if highly relevant] → Layer 3 (full depth)
```

### 5. Prefrontal Cortex — Working Memory

**Architecture:**
- Capacity: **7 active workloads** (Miller's Law)
- Function: Holds current context, active reasoning

**Lifecycle:**
```
New stimulus → Enter working memory →
  [Used X times in Y period] → 
    Strengthen → Move to long-term
  [Not used] → 
    Decay → Push down priority queue
```

**Implementation:**
- Priority queue with time-decay
- Access frequency tracking
- Automatic promotion/demotion

### 6. Long-Term Memory

**Criteria for promotion:**
- Used ≥ X times
- Within time period Y
- OR: Explicitly marked important
- OR: Connected to strongly-held beliefs

**Structure:**
- Compressed representation (distillation)
- Fast retrieval path
- Cross-linked to related concepts
- Episodic tagging (when learned, from whom)

---

## Technical Implementation

### Database Schema (SQLite WAL / graph substrate)

**Nodes Table:**
```sql
node_id: UUID
type: [concept, episode, claim, hypothesis]
surface_content: TEXT
deep_content: JSON (full layers)
confidence: FLOAT
created_at: TIMESTAMP
access_count: INT
last_accessed: TIMESTAMP
working_memory_priority: INT
```

**Edges Table:**
```sql
edge_id: UUID
source_node: UUID
target_node: UUID
edge_type: [semantic, temporal, causal, associative]
strength: FLOAT
axons: INT (active searchers)
activation_history: JSON
```

**Working Memory Table:**
```sql
slot: INT (1-7)
node_id: UUID
priority_score: FLOAT
time_in_slot: TIMESTAMP
```

### Algorithms

**1. Claim Decomposition:**
```python
def decompose_claim(claim):
    # NLP parsing to atomic assertions
    # Entity extraction
    # Relation identification
    return atomic_nodes
```

**2. Minimal Common Denominator:**
```python
def find_mcd(new_node, existing_graph):
    # Find finest granularity overlap
    # Merge if >threshold similarity
    # Create new edge if partial overlap
    return merged_or_new_node
```

**3. Working Memory Management:**
```python
def update_working_memory(node_id):
    # Check if node already in WM (slots 1-7)
    # If yes: increase priority, update timestamp
    # If no: 
    #   - Find lowest priority in WM
    #   - If new node priority > lowest: swap
    #   - Else: add to priority queue
    
def decay_working_memory():
    # Time-based decay of priority scores
    # Automatic demotion to long-term queue
```

**4. Long-Term Promotion:**
```python
def evaluate_for_promotion(node_id):
    # Check access_count >= X
    # Check within time window Y
    # Check connection strength to active nodes
    # If criteria met: 
    #   - Compress (distill)
    #   - Add fast-retrieval index
    #   - Mark as long-term
```

---

## Visualization

### User Interface

**Primary View:**
- 3D/2D graph visualization (force-directed)
- Working memory slots (7 circles, glowing if active)
- Depth indicators on nodes (color = depth accessed)
- Axon activity (animated lines showing active search)

**Node Interaction:**
- Click = Surface view
- Double-click = Deep dive (Layer 2+)
- Hover = Quick preview + connection strength

**Working Memory Display:**
- 7 slots visible
- Drag-and-drop to prioritize
- Auto-arrange by priority
- Time-decay visualization

---

## Integration with Nous

**MCP Tools Exposed:**

```python
# Store with automatic MCD analysis
nouse_remember(content, context) → node_id

# Query with working memory awareness
nouse_recall(query, depth=1) → [nodes]

# Force working memory update
nouse_promote_to_wm(node_id)

# Get current WM state
nouse_get_working_memory() → [7 nodes]

# Manual long-term store
nouse_commit_to_ltm(node_id)
```

---

## Next Steps

1. **Schema design** — Finalize Zulu DB tables
2. **Algorithm implementation** — Core logic in Rust
3. **Python bindings** — Expose to b76/Nous
4. **Visualization** — Frontend (WebGL/Three.js)
5. **Training pipeline** — Wikipedia scrape → structured graph

---

*Specifikation: FNC Implementation for Nous*
*Based on: The Larynx Problem, FNC Theory, Cognitive Neuroscience*
