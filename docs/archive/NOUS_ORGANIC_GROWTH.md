> **SUPERSEDED, 2026-08-25.** Describes an early speculative architecture (a Rust/"Zulu DB" system at 10M+ node scale) that was never built. The actual implementation is SQLite WAL + NetworkX (see README.md, CHANGELOG.md). Kept for history, not current status.

# Nous Organic Growth Architecture
## Start Small, Grow Organically
**Date:** 2026-04-02 08:41
**Author:** Björn Wikström
**Status:** Architecture Concept

---

## 🎯 KÄRNIDÉ

**Starta inte med 10M noder. Starta med 1000. Låt det växa organiskt.**

```
┌─────────────────────────────────────────────────────────┐
│           NOUSE ORGANIC GROWTH MODEL                    │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  FASE 1: SEED (1000 noder)                            │
│  └── Litet NN i RAM                                   │
│  └── Symlinks till filsystem                            │
│  └── Deskription = semantisk innehåll                   │
│                                                         │
│      📁 documents/                                      │
│      ├── 📄 README.md  ← "Academic papers on AI"      │
│      ├── 📁 fnc/                                       │
│      │   ├── 📄 README.md ← "FNC Theory"              │
│      │   └── 📄 consciousness.md                      │
│      └── 📁 nouse/                                     │
│          └── 📄 architecture.md                        │
│                                                         │
│      NN Node #1: "documents" → symlinks to ./documents  │
│      NN Node #2: "fnc" → symlinks to ./documents/fnc/ │
│      Deskription: "FNC Theory, papers on consciousness"│
│                                                         │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  FASE 2: GROWTH (10k → 100k noder)                      │
│  └── Nya folders → nya noder                            │
│  └── Deskription indexerad                              │
│  └── Symlinks skapas automatiskt                        │
│                                                         │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  FASE 3: MATURE (1M+ noder)                             │
│  └── Övergång till Zulu DB (om behov)                   │
│  └── Hybrid: NN i RAM, data på disk                     │
│  └── Plastisitet aktiverad fullt ut                     │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 🔗 SYMLINK ARKITEKTUR

### Varje Nod = En Folder

```
~/.nouse/neural_graph/           # Root: NN topology
├── node_0001/                   # Each folder = one node
│   ├── README.md                # Deskription (semantic content)
│   ├── metadata.json            # Node properties
│   ├── edges/                   # Symlinks to connected nodes
│   │   ├── node_0002 -> ../node_0002/
│   │   ├── node_0047 -> ../node_0047/
│   │   └── node_0156 -> ../node_0156/
│   └── content/                 # Actual data (optional)
│       └── files...
│
├── node_0002/
│   ├── README.md
│   ├── metadata.json
│   └── edges/
│       ├── node_0001 -> ../node_0001/  # Bidirectional!
│       └── node_0089 -> ../node_0089/
│
└── ... (1000 nodes initially)
```

### Metadata Format (`metadata.json`)

```json
{
  "node_id": 1,
  "uuid": "550e8400-e29b-41d4-a716-446655440000",
  "deskription": "Academic papers on AI consciousness and FNC theory",
  "node_type": "concept",
  "created_at": "2026-04-02T08:41:00Z",
  "access_count": 0,
  "last_accessed": null,
  "synaptic_strength": 0.5,
  "working_memory_slot": null,
  "depth": 1,
  "region": "temporal_lobe"
}
```

### Deskription Format (`README.md`)

```markdown
# documents

## Deskription
Academic papers on AI consciousness and FNC theory.

## Content
- FNC papers
- Consciousness research
- Nous architecture docs

## Connections
- Related to: fnc, consciousness, nouse
- Created by: user
- Date: 2026-04-02

## Properties
- Confidence: 0.95
- Type: semantic_cluster
- Priority: normal
```

---

## 🧠 NN INITIALISERING (Litet)

### Phase 1: Seed (1000 noder)

```rust
pub fn initialize_seed_network() -> Graph {
    let graph = Graph::new();
    
    // Skapa 1000 noder i ~/.nouse/neural_graph/
    for i in 0..1000 {
        let node_path = format!("~/.nouse/neural_graph/node_{:04}", i);
        fs::create_dir_all(&node_path)?;
        
        // Skapa metadata
        let metadata = NodeMetadata {
            node_id: i,
            deskription: "Empty node, awaiting content".to_string(),
            node_type: NodeType::Placeholder,
            created_at: Utc::now(),
            synaptic_strength: 0.1,
        };
        
        fs::write(
            format!("{}/metadata.json", node_path),
            serde_json::to_string_pretty(&metadata)?
        )?;
        
        // Skapa README
        fs::write(
            format!("{}/README.md", node_path),
            format!("# Node {}\n\n## Deskription\nEmpty placeholder node.\n", i)
        )?;
        
        // Skapa edges folder
        fs::create_dir_all(format!("{}/edges", node_path))?;
    }
    
    // Initial sparse connectivity (random)
    connect_random_nodes(&graph, 1000, 0.01)?; // 1% connectivity
    
    graph
}
```

---

## 🌱 ORGANISK VÄXT

### När användaren lägger till content:

```rust
pub fn grow_network(graph: &mut Graph, new_content: Content) -> NodeId {
    // 1. Skapa ny nod
    let node_id = graph.create_node();
    let node_path = format!("~/.nouse/neural_graph/node_{:04}", node_id);
    
    // 2. Skriv deskription
    fs::write(
        format!("{}/README.md", node_path),
        generate_deskription(&new_content)
    )?;
    
    // 3. Uppdatera metadata
    let metadata = NodeMetadata {
        node_id,
        deskription: new_content.summary(),
        node_type: classify_content(&new_content),
        created_at: Utc::now(),
        synaptic_strength: 0.5,
    };
    
    fs::write(
        format!("{}/metadata.json", node_path),
        serde_json::to_string_pretty(&metadata)?
    )?;
    
    // 4. Hitta befintliga noder att koppla till
    let related_nodes = find_related_nodes(&graph, &new_content);
    
    // 5. Skapa symlinks (edges)
    for related in related_nodes {
        create_symlink(&node_path, &related)?;
        // Bidirectional
        create_symlink(&related, &node_path)?;
    }
    
    // 6. Uppdatera NN vikter (plastisitet)
    update_synaptic_strength(&graph, node_id, &related_nodes)?;
    
    node_id
}
```

### Exempel: Indexera Folder

```bash
# Användaren har en folder:
~/Documents/research/
├── fnc/
│   ├── paper1.pdf
│   └── notes.md
├── consciousness/
│   └── essay.pdf
└── nouse/
    └── architecture.md

# Kör:
nouse index ~/Documents/research/

# Nous skapar:
~/.nouse/neural_graph/
├── node_0001/  ← "research"
│   ├── README.md: "Research documents on AI consciousness"
│   ├── metadata.json
│   └── edges/
│       ├── node_0002 -> ../node_0002/  (fnc)
│       └── node_0003 -> ../node_0003/  (consciousness)
│
├── node_0002/  ← "fnc"
│   ├── README.md: "FNC Theory papers"
│   └── edges/
│       ├── node_0001 -> ../node_0001/
│       └── node_0004 -> ../node_0004/  (nouse)
│
├── node_0003/  ← "consciousness"
│   ├── README.md: "Consciousness research"
│   └── edges/
│       └── node_0001 -> ../node_0001/
│
└── node_0004/  ← "nouse"
    ├── README.md: "Nous architecture"
    └── edges/
        └── node_0002 -> ../node_0002/
```

---

## 📊 SKALERING

### Phase 1: Seed (1000 noder)
```
Disk: ~10MB
RAM: ~50MB
Inodes: 1000 folders + 1000 symlinks
```

### Phase 2: Growth (10k noder)
```
Disk: ~100MB
RAM: ~500MB
Inodes: 10k folders + 50k symlinks
```

### Phase 3: Mature (100k noder)
```
Disk: ~1GB
RAM: ~2GB
Inodes: 100k folders + 500k symlinks
Transition to Zulu DB for performance
```

### Phase 4: Scale (1M+ noder)
```
Hybrid:
- NN topology: Zulu DB
- Metadata: Zulu DB
- Content: Filesystem (symlinks)
- Working memory: RAM
```

---

## 🎯 FÖRDELAR

| Aspect | Big Bang (10M noder) | Organic Growth (1000 → 1M) |
|--------|---------------------|---------------------------|
| **Startup time** | 5+ minutes | <5 seconds |
| **Disk usage** | 2GB+ initial | 10MB initial |
| **Komplexitet** | Hög | Låg |
| **Debugging** | Svårt | Lätt (varje nod = folder) |
| **Transparens** | Låg | Hög (alla filer synliga) |
| **Backup** | Svårt | Lätt (rsync neural_graph/) |
| **Portability** | Låg | Hög (vanligt filsystem) |

---

## 🚀 KONKRET START

```bash
# 1. Installera Nous
curl -fsSL https://nouse.base76research.com/install | bash

# 2. Initiera SEED (litet)
nouse init --seed --nodes=1000

# Output:
# ✓ Created ~/.nouse/neural_graph/
# ✓ 1000 placeholder nodes
# ✓ Sparse connectivity (1%)
# ✓ Ready for indexing

# 3. Indexera din data
nouse index ~/Documents/
nouse index ~/Projects/
nouse index ~/Research/

# 4. Starta
nouse start

# 5. Dashboard
open http://localhost:3000
```

---

*Architecture: Björn Wikström*
*Date: 2026-04-02 08:41*
*Concept: Organic growth from seed to scale*
