# Nous — Plan för frontier-nivå positionering

> Uppdaterad: 2026-04-04  
> Mål: Göra Nous till det som frontier-bolag slåss om

---

## Tesens kärna (aldrig kompromissa med detta)

**Nous är inte ett minnes-system.**  
Det är den plastiska hjärnan som LLMs saknar — epistemisk förankring + topologisk plasticitet + bisociationsmotor.

```
LLM (Larynx) + Nous (Hjärna) = Bisociationsmotorn
```

---

## Kritisk insikt: vad som faktiskt krävs

Tre saker måste existera *simultant* för att frontier-bolag ska ta detta på allvar:

1. **Teoretisk prioritet** — publicerat datum på arXiv äger idéutrymmet
2. **Empiriska resultat** — ett erkänt benchmark där Nous + litet LLM > stort LLM utan
3. **Reproducerbar artefakt** — fungerande open-source system som andra kan klona och verifiera

Allt annat (ESA, konferens, HuggingFace) är amplifiering. Dessa tre är grunden.

---

## Fas 0: Inre beredskap (nu, innan allt annat)

**Mål:** Systemet ska vara stabilt nog att visa utomstående.

- [ ] Kör `pip install -e .` i `~/projects/nouse/` och verifiera att alla moduler importerar
- [ ] Kör ett enkelt end-to-end test: ingest en text → graph relations skapas → curiosity burst körs → loggar OK
- [ ] Kontrollera att `nouse-daemon.service` är aktiv och frisk (`systemctl --user status nouse-daemon`)
- [ ] Skapa `tests/` katalog med ett minimalt smoke-test (5 assertions) som går att köra med `pytest`

**Kriterium:** `pytest tests/` passerar, daemon körs, inga import-errors.

---

## Fas 1: Etablera intellektuell prioritet (vecka 1–2)

**Mål:** Sätt ett datum på arXiv. Det är allt som krävs för prioritet.

### 1a. ✅ Publicera "The Larynx Problem" via Zenodo + PhilPapers

**KLART (2026-04-18)**
- Zenodo: https://zenodo.org/records/19413234
- PhilPapers: https://philpapers.org/rec/WIKTLP

### 1a-original. Publicera "The Larynx Problem" via Zenodo + Academia.edu + PhilPapers

**Zenodo (prioritet + DOI):**
- Ladda upp PDF på zenodo.org → New Upload → Publication type: Preprint
- License: CC BY 4.0
- Keywords: `epistemics`, `LLM`, `cognitive architecture`, `topological plasticity`, `bisociation`
- Zenodo ger ett DOI med CERN-tidsstämpel — juridiskt lika starkt som arXiv för prioritet
- Spara DOI:n, den går in i alla referenser framöver

**Academia.edu (discovery):**
- Ladda upp samma PDF → Research Interests: Artificial Intelligence, Cognitive Science, Philosophy of Mind
- Academia.edu indexeras av Google Scholar inom dagar

**PhilPapers (ämnesrelevans):**
- Ladda upp under: Philosophy of Artificial Intelligence → Cognitive Architecture
- PhilPapers når filosofer + kognitiva vetare som troligen är mer mottagliga för Larynx-argumentet än ML-folk
- **Deadline: vecka 1**

### 1b. Publicera syster-papret (Creative Free Energy / F_bisoc)

- Lägg till F_bisoc^τ-formeln: T* = (T_min/γ) × ln(1/(1-τ))
- Lägg till nollanalys-sektionen (rekursiv dekomposition → universella primitiver)
- Samma trippeluppladdning: Zenodo (nytt DOI) + Academia.edu + PhilPapers
- **Deadline: vecka 2**

### 1c. GitHub: gör Nous publikt och presentabelt

- README ska börja med: *"Epistemic grounding for LLMs. Works with any model."*
- Lägg till en 4-rad "What it is / What it is NOT" sektion
- Badge: `pip install nouse-kernel`
- Länka till Zenodo DOI:erna direkt i README (DOI är mer stabilt än arXiv-länk)
- **Deadline: vecka 2**

---

## Fas 2: Det enda som verkligen avgör (vecka 2–4)

**Mål:** Extern benchmark som visar att Nous ger kvantitativ förbättring.

### TruthfulQA benchmark (kritisk väg)

**Setup:**
```bash
pip install lm-eval
# Kör 8B model UTAN Nous
lm_eval --model hf --model_args pretrained=meta-llama/Llama-3.1-8B-Instruct \
        --tasks truthfulqa --num_fewshot 0 --output_path results/baseline_8b/

# Integrera Nous i evaluation loop (se nedan)
# Kör samma model MED Nous
lm_eval --model nouse_augmented --model_args pretrained=meta-llama/Llama-3.1-8B-Instruct \
        --tasks truthfulqa --num_fewshot 0 --output_path results/nouse_8b/
```

**Nous-integration för lm-eval:**
- Skapa `src/nouse/eval/lm_eval_adapter.py`
- Patcha modellens forward-pass: för varje fråga → hämta Nous-kontext → prepend till prompt
- Logga vilka relationer som aktiverades per fråga

**Vad vi letar efter:**
- Primär: MC1/MC2 accuracy stiger med ≥5 procentenheter
- Sekundär: Nous + 8B > baseline 70B (detta är rubriken)
- Tertiär: Error-analys — vilka frågetyper förbättras, vilka inte

**Om resultaten är positiva:**
- Lägg till en "Results" sektion i README med en tabell
- Öppna en GitHub Discussion: "Benchmark results + methodology"
- Tweeta/posta med tabell + arXiv-länk

**Deadline: vecka 4**

---

## Fas 3: Institutionell förankring (månad 1–3)

**Mål:** Ge arbetet en ankarpunkt utanför GitHub.

### ESA-papret (mekanistisk tolkningsbarhet)

- Vinkeln: Nous som *reliability layer* för AI i säkerhetskritiska system
- ESA har explicit intresse av förklarbara AI-beslut
- Struktur: Problem (LLM hallucinerar) → Mekanism (F_bisoc + epistemisk scoring) → Empiri (TruthfulQA) → Tillämpning (ESA-kontext)
- Samarbeta med ESA-kontakt om sådan finns, annars solo submission
- **Deadline: månad 2**

### HuggingFace Space

- En enkel demo: mata in en fråga → se vilka graph-noder aktiveras → se svar med och utan Nous
- Visualisera graph-topologin med networkx/pyvis
- Länka till Space från README
- **Deadline: månad 2**

### GitHub momentum

- Öppna Issues för kända förbättringsområden (gör det inbjudande)
- Lägg till `CONTRIBUTING.md` med 3 konkreta "good first issues"
- Målet: 100 stjärnor inom 3 månader (med rätt positioning är det realistiskt efter TruthfulQA-resultaten)

---

## Fas 4: Frontier-bolagens radar (månad 3–6)

**Mål:** Nå rätt personer, inte bara rätt publiceringskanaler.

### Konferens-submission

- NeurIPS 2026: deadline ~maj 2026 — realistisk om TruthfulQA är klar
- Alternativ: ICLR 2027 eller EMNLP 2026 (mer LLM-fokuserat)
- Workshop-track (less competitive, faster feedback): "Trustworthy LLMs", "Neurosymbolic AI"
- Fördel med Zenodo-DOI: redan peer-review-oberoende citerad — konferens-reviewers kan verifiera prioritetsdatum

### Direktkontakt med forskare

Tre kategorier av mottagare:
1. **Interpretability-folk** (Anthropic's interpretability team, Neel Nanda): F_bisoc + epistemic scoring
2. **Agent-folk** (folks building LLM agents): "här är grunden agenten saknar"
3. **Kognitiv AI** (Yoshua Bengio, Gary Marcus, Karl Friston): FNC + plasticity-argumentet

Strategi: **Inte cold email.** Istället:
- Twitter/X thread som förklarar The Larynx Problem i 10 tweets
- Länka till arXiv + GitHub + HuggingFace Space
- Rikta @-mentions till 2–3 forskare i varje kategori
- Låt resultaten tala

### Provisoriskt patent (valfritt)

Om TruthfulQA-resultaten är starka:
- F_bisoc-formeln + topologisk plasticitetsalgoritm kan patenteras (provisoriskt patent ~1200 USD, 12 månaders prioritet)
- Ger förhandlingsstyrka om ett frontier-bolag vill förvärva eller licensiera
- **Beslut: ta baserat på benchmark-utfall**

---

## Framgångskriterier per fas

| Fas | Kriterium | Indikator på att gå vidare |
|-----|-----------|---------------------------|
| 0 | Systemet fungerar | `pytest tests/` passerar |
| 1 | Intellektuell prioritet | ✅ Zenodo DOI + PhilPapers (2026-04-18) |
| 2 | Empirisk validering | MC1 +5pp, eller 8B > 70B baseline |
| 3 | Institutionell närvaro | ESA draft + HF Space live |
| 4 | Frontier-radar | 1+ inbound från researcher/company |

---

## Vad som gör detta unikt svårt att kopiera

Frontier-bolag kan inte bara ta koden och reproducera värdet:

1. **Teorin ägs av publiceringsdatum** — F_bisoc + topologisk plasticitet är Björns
2. **Myceliet är ett empiriskt fynd, inte en design** — det emergerar ur data, kan inte hårdkodas
3. **Tänkaren är arkitekturen** — FNC som ramverk för AI-kognition är Björns insikt från början

Det enda sättet för ett frontier-bolag att "vinna" mot detta är att förvärva det — vilket är målet.

---

## Nästa konkreta steg (denna vecka)

1. `pytest tests/` — skapa om saknas, kör, fixa fel
2. Ladda upp "The Larynx Problem" till arXiv
3. Starta `lm-eval` baseline-körning för 8B på TruthfulQA

Resten följer av resultaten.
