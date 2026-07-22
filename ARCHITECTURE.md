# From Row‑Picking to Shipment Understanding

**Architecture proposal — container tracking control tower**
Draft 2026‑07‑13

A redesign of the MSC container tracking automation: replacing hardcoded description‑matching with an event interpretation engine that infers each shipment's operational state, carrier‑agnostic and built entirely on open‑source Python.

---

## The inversion

The current script answers *"which scraped row do I keep?"* by testing scraped text against a fixed list of English phrases. The moment MSC rewords an event, or a second carrier uses different terminology, that logic silently breaks or silently mis‑selects.

This design answers a different question: *"given everything this container has done, what phase is it in?"* Row selection becomes a byproduct of state inference, not the goal of it. Wording becomes an input to a classifier, not a key the code branches on.

---

## 01 — Overall system architecture

A ports‑and‑adapters (hexagonal) architecture. A carrier‑agnostic **domain core** — the taxonomy, the canonical timeline, the state engine, comparison, and exceptions — has zero knowledge of Selenium, Excel, or MSC's DOM. Everything that talks to the outside world (SPS exports, carrier websites, output files) is an adapter that plugs into that core through a narrow, stable interface.

```
SPS export → Ingestion → Cleaning → Carrier router → Scraping adapters
   → [Event classifier] → [State engine] → [Comparison] → [Exceptions] → Reporting
```

Bracketed stages are the **domain core** — carrier‑ and format‑agnostic, unit‑testable without a browser. The rest are adapters and are expected to change as sources and outputs change.

**Cross‑cutting layers.** Config & taxonomy feeds the router, the classifier, and the exception engine — vessel‑prefix mappings, event phrase families, and risk thresholds live as data, not code. Storage holds the per‑container state history the comparison engine needs (today's script has no memory between runs; every run starts from zero) and doubles as the scrape cache for the performance layer in §10.

---

## 02 — Folder structure

One package, one responsibility per top‑level folder. The core (`events/`, `shipment_state/`, `comparison/`, `exceptions/`) is not allowed to import from `carriers/` or `reporting/` — dependencies point inward, toward the domain.

```
tracking_control_tower/
├── ingestion/            # read & validate the SPS export
│   └── sps_reader.py
├── cleaning/              # normalize IDs, filter, dedupe
│   └── shipment_cleaner.py
├── carriers/              # adapters — one module per carrier
│   ├── base.py            # CarrierAdapter contract (see §09)
│   ├── msc.py
│   └── router.py          # vessel prefix → adapter
├── events/                # event_parser
│   ├── taxonomy.yaml       # phrase families → canonical category (data, not code)
│   ├── normalizer.py       # casing / whitespace / synonym cleanup
│   └── classifier.py       # raw text → CanonicalEvent + confidence
├── shipment_state/
│   ├── timeline.py         # canonical phase graph (§04)
│   └── engine.py           # events → ShipmentState
├── comparison/
│   ├── snapshot_diff.py    # vs last persisted state
│   └── sps_diff.py         # vs raw SPS fields
├── exceptions/             # risk / exception engine
│   ├── rules.yaml
│   └── evaluator.py
├── reporting/
│   ├── excel_renderer.py
│   └── renderer_base.py
├── storage/                # state history + scrape cache (SQLite/Parquet)
├── orchestration/          # run a batch, checkpointing, scheduling
│   └── run_daily.py
├── config/                 # prefixes, rail locations, thresholds
└── utils/
```

| Folder | Owns | May import from |
|---|---|---|
| `ingestion` | SPS schema validation, type coercion | config, utils |
| `cleaning` | Status/LFD filters, dedupe rules | config, utils |
| `carriers` | Browser automation, DOM parsing, raw event extraction | config, utils |
| `events` | Taxonomy‑driven classification | config, utils |
| `shipment_state` | Canonical timeline, phase inference | events |
| `comparison` | Snapshot & SPS diffing | shipment_state, storage |
| `exceptions` | Risk rules, reason codes | shipment_state, comparison |
| `reporting` | Rendering final output to a format | shipment_state, comparison, exceptions |
| `orchestration` | Wiring the run end‑to‑end, checkpoints | everything |

---

## 03 — Data flow, per container

§01 shows the batch pipeline. This is what happens to *one* container as it moves through the core:

```
Raw events (date · location · description · vessel_info · facility)
  → Normalize (lowercase, strip, alias‑map)
  → Classify (each event → category + confidence)
  → Order (sort chronologically, drop UI junk)
  → Place on timeline (map categories → canonical phases)
  → Infer state (current / prior / next + confidence)
  → Diff (vs last snapshot, vs SPS)
  → Evaluate risk (rules → reason codes)
  → Emit row (one structured record per container)
```

Everything from *Normalize* through *Evaluate risk* operates on the container's **entire** event history, not a single selected row — this is what makes the output resilient to a carrier adding, renaming, or reordering milestones.

---

## 04 — Shipment state engine design

A canonical phase timeline that every carrier's events get mapped onto, regardless of wording. Phase order is the ground truth; individual event descriptions are just evidence for where on that order a shipment currently sits.

```
00 Booking → 01 Export → 02 Loaded → 03 Departed origin → 04 Transshipment
  → 05 Ocean transit → 06 Arrival US port → 07 Discharged → 08 Customs
  → 09 Rail → 10 Destination terminal → 11 Delivery → 12 Delivered
```

**Transshipment** (04) can recur — a second departure/arrival pair at another port replays 04→05 without advancing rank until a US port arrival is seen. **Rail** (09–10) is only expected when `ship_to_location` resolves to a rail‑served destination (today: Denver, Kansas City Hub, SB Chicago) — otherwise the engine treats Discharged→Customs→Delivery as the expected path and never flags rail as "missing."

**Inference rule.** *Current phase* = the highest‑rank canonical phase with a supporting event above the confidence floor. *Previous event* = the classified event that produced that phase. *Next expected* = rank + 1 on the applicable branch. *Confidence* is a weighted blend of (a) the classifier's confidence on the supporting event, (b) how recently it was scraped, and (c) whether later, lower‑rank events contradict it — a contradiction (e.g. a "gate out" after a later "arrival") caps confidence rather than silently overriding phase.

**ShipmentState — output shape**

| Field | Meaning |
|---|---|
| `current_phase` | Furthest canonical phase reached |
| `current_location` / `current_vessel` | From the event supporting current_phase |
| `current_eta` / `pod_eta` | Best available port & destination ETA |
| `previous_event` / `next_expected_event` | One phase back / one phase forward |
| `days_until_arrival` / `delay_days` | Derived from ETA history, not a single field |
| `risk_level` / `confidence_score` | From §07 and the inference rule above |
| `recommended_sps_updates` | Field‑level diffs from §06 |
| `data_quality_issues` | Unclassified events, missing dates, contradictions |

---

## 05 — Event classification engine

The single change that removes the most fragility. Today: `if description == "Estimated Time of Arrival"`. Instead: every scraped description is normalized and matched against a **data‑driven taxonomy** — a config file, not code — of phrase families per canonical category.

**Classification order**

1. **Normalize.** Lowercase, strip punctuation/whitespace, collapse known synonyms via an alias table (e.g. "POD" ≡ "port of discharge").
2. **Taxonomy match.** Compare against phrase families in `taxonomy.yaml` — keyword sets and patterns, not single strings, mapped to a canonical category and a phase rank.
3. **Fuzzy fallback.** No confident rule match → fuzzy string similarity (e.g. rapidfuzz) against known phrases, with a confidence score attached.
4. **Unclassified queue.** Still below the confidence floor → tagged `unclassified` and surfaced as a data‑quality issue rather than guessed at. A human glance at the review queue extends the taxonomy; the engine never silently fabricates a phase.

A later, optional layer (§11 flags the tradeoff) can add local sentence‑embedding similarity for genuinely novel phrasing from a new carrier — still open‑source, still no API key, run entirely on‑machine — but the taxonomy‑plus‑fuzzy combination should carry MSC and most new carriers on its own.

```yaml
# taxonomy.yaml — excerpt
discharged:
  phase_rank: 7
  phrases:
    - "import discharged from vessel"
    - "discharged"
    - "offloaded from vessel"
rail_departure:
  phase_rank: 9
  phrases:
    - "import rail departure"
    - "rail departure"
    - "departed on rail"
```

Adding a carrier that says `"container offloaded"` instead of `"discharged"` is a one‑line edit to this file. No branch of code changes.

---

## 06 — Comparison engine

Two independent comparisons, both operating on canonical, normalized values — never on raw scraped text against a raw SPS cell, which is what makes today's `compare_eta`/`compare_vessels` brittle to formatting differences.

**Temporal — this run vs last run.** Every run persists each container's `ShipmentState` to `storage/`. The next run diffs against it to produce `state_changed`, `vessel_changed`, `eta_changed`, `pod_changed` — booleans with an old‑value/new‑value pair, so a change has a visible reason, not just a flag.

**Authoritative — inferred truth vs SPS.** Inferred `current_vessel`, `current_eta`, `pod_eta` are compared field‑by‑field against the SPS row's `vessel`, `port_eta`, `rail_eta` at day‑level date granularity and voyage‑stripped vessel names, producing a per‑field `recommended_sps_updates` list: field, old value, new value, reason, confidence — the direct answer to "should SPS be updated, and which fields."

---

## 07 — Exception engine

Risk rules read `ShipmentState` + the comparison diff — never raw scrape text — so a rule like "stalled" means the same thing for every carrier without carrier‑specific code.

**Example rules**

| Rule | Trigger | Severity |
|---|---|---|
| Stalled | No phase advance for N days above the phase's typical dwell time | Medium |
| Contradiction | A later‑scraped event implies an earlier phase than one already confirmed | High |
| Vessel swap near arrival | Vessel changed while phase ≥ Ocean transit | High |
| Rail expected, missing | Rail‑served destination, discharged > N days, no rail event | Medium |
| Unclassified events present | One or more raw events below the confidence floor | Low |
| Container not found | Adapter returned no history at all | High |

Rule output feeds `risk_level` and `data_quality_issues` / `missing_information` directly — every risk flag carries a reason code back to the rule that raised it, so a reviewer can see *why*, not just a red pill.

---

## 08 — Reporting engine

Renderers consume the finished, structured output — `ShipmentState` + comparison + exception results — and never see a raw scraped string. That boundary is what lets output formats multiply without the domain core knowing or caring.

Today's four workbooks (filtered/scraped/merged/final) collapse into one Excel renderer with multiple sheet strategies over the same structured input. Future renderers — a CSV shaped for SPS bulk‑import, a same‑page HTML risk dashboard, an email digest of high‑ and medium‑risk shipments — are new files in `reporting/` implementing the same narrow `render(states)` contract.

---

## 09 — Future scalability

Everything carrier‑specific lives behind one interface. Adding Maersk, CMA, COSCO, Hapag, or ONE means writing a new adapter and, if needed, a few taxonomy aliases — nothing else in the system changes.

**CarrierAdapter contract**

| Method | Responsibility |
|---|---|
| `search(container)` | Drive the carrier's tracking UI, return raw page content for that container |
| `parse(raw)` | Extract a list of `RawEvent` — date, location, description, vessel_info, facility — with zero interpretation |
| `vessel_prefixes` | Which vessel‑name prefixes route to this adapter (replaces the hardcoded `prefixes` list with a per‑adapter declaration) |

The classifier, timeline, state engine, comparison, exception, and reporting layers only ever see `RawEvent` objects — they cannot tell whether a given event came from MSC's DOM or Maersk's, which is exactly the point.

---

## 10 — Performance optimizations

- **Browser context pooling.** Reuse a small pool of persistent Playwright/Selenium contexts across containers instead of one driver per run — the current script pays full driver startup cost once per run, which is fine, but per‑container searches still re‑render the whole tracking page each time; a pooled, tab‑reused approach cuts that overhead.
- **Bounded concurrency.** Scrape several containers in parallel behind a semaphore — enough to cut wall‑clock time, not so much it reads as automated abuse to MSC's servers.
- **Change‑aware scheduling.** Skip re‑scraping containers already at a terminal phase (Delivered), and throttle check frequency by proximity to the next expected transition — a container 20 days from arrival doesn't need a daily check; one 3 days out does.
- **Local cache.** Key scrape results by (container, date) in the storage layer; a same‑day re‑run reads cache instead of hitting the network.
- **Smart retries.** Distinguish transient failures (timeout, stale element) — retry with backoff — from permanent ones (container genuinely not found) — fail fast, don't retry.
- **Checkpoint / resume.** Persist progress per batch so a killed run resumes from the last completed container instead of restarting the whole list.

---

## 11 — Risks and tradeoffs

- **Scraping fragility is insulated, not eliminated.** A DOM/XPath change in MSC's site still breaks the `carriers/msc.py` adapter. The taxonomy only protects against *wording* changes in the text that adapter successfully extracts.
- **Confidence scores are heuristic.** They are decision‑support, not statistically calibrated probabilities — treat low confidence as "route to a human," not as a hard number to trust blindly.
- **Over‑engineering risk.** This is a lot of structure for a system that scrapes exactly one carrier today. The phased plan in §12 exists specifically so the multi‑carrier registry, taxonomy config, and exception engine get built against real, validated need rather than speculative generality.
- **Site ToS / detection risk is unchanged.** Stealth automation against a public site carries the same legal and technical exposure regardless of how the code behind it is organized.
- **Optional embedding fallback adds weight.** A local semantic‑similarity layer for classification (§05) pulls in a model dependency and inference latency for a long‑tail benefit — keep it off by default until the taxonomy‑plus‑fuzzy layer proves insufficient.
- **Exception thresholds need real tuning.** "Stalled for N days" and similar rules will produce noisy false positives until tuned against historical data — see §12 Phase 5, which tunes them against the existing `merged_validation_output_*.xlsx` archive before trusting the rules live.

---

## 12 — Implementation plan

Each phase ends with a concrete comparison against the current script's output on real historical files already sitting in `OLD/` — this is a regression‑tested cutover, not a rewrite‑and‑hope.

**P01 — Foundations**
Repo skeleton from §02. Define the taxonomy config schema and the `RawEvent` / `ShipmentState` data models. No scraping yet.
*Exit: schema reviewed, no runtime code depends on a browser.*

**P02 — Ingestion & cleaning parity**
Port the existing load/rename/filter/dedupe logic into `ingestion/` and `cleaning/`, unchanged in behavior.
*Exit: output matches today's cleaned `df` row‑for‑row against a saved `1RAW.xlsx`.*

**P03 — Taxonomy & classifier — offline**
Build the taxonomy from the real event descriptions already captured across the `msc_scraped_results_*.xlsx` history in `OLD/`. Validate classification against that archive without touching a browser at all.
*Exit: every distinct description seen historically classifies with acceptable confidence or lands in the review queue by design, not by accident.*

**P04 — State engine & comparison**
Build the canonical timeline, phase inference, and both comparison axes. Run them side‑by‑side against the existing `select_best_row` / `compare_eta` / `compare_vessels` logic on the same historical inputs and diff the two outputs.
*Exit: outputs agree on the historical archive, or disagreements are understood and are the new logic's deliberate improvement.*

**P05 — Carrier adapter refactor**
Extract the existing MSC Selenium flow behind `CarrierAdapter`. Behavior‑identical to today; now swappable.
*Exit: live scrape of a small container batch produces the same raw events as the current script.*

**P06 — Exception engine**
Implement the rules from §07 and tune thresholds against the historical `merged_validation_output_*.xlsx` archive before trusting them on live data.
*Exit: rule firing rate on historical data is reviewed and judged non‑noisy.*

**P07 — Reporting engine**
Reproduce today's four workbooks through the new renderer with column‑for‑column parity.
*Exit: side‑by‑side workbook comparison against the current script's output matches.*

**P08 — Performance layer**
Add pooling, caching, and change‑aware scheduling from §10 — only once correctness is proven, since optimizing an unverified pipeline is wasted effort.
*Exit: measured wall‑clock improvement on a full daily batch.*

**P09 — Second carrier as proof**
Pick the next‑highest‑volume vessel prefix already visible in the data (HL or CMA) and onboard it purely through a new adapter and taxonomy aliases.
*Exit: no change required outside `carriers/` and `events/taxonomy.yaml` — the scalability claim in §09, verified.*

---

*Container Tracking Control Tower — architecture proposal, not implementation. See §12 for how this gets built without a risky big‑bang rewrite.*
