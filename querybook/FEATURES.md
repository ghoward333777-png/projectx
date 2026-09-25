# Feature map — QueryBook Feature Registry v65 → prototype

IDs and names are the registry's (v65, 293 features). **Built** = implemented and
exercised by tests or the browser run; **Partial** = the governing rule holds but
the feature is narrower than specified; everything not listed is not built in
this prototype. Paths are relative to `querybook/`.

## D0 · Prime Directive
| ID | Feature | Status | Where |
|---|---|---|---|
| QBF-C001 | Safety Substrate | Built — in-record safety class; every admission passes the gate; evaluation digest sealed into the ledger node | `src/d0/safety.rs`, `src/d2/ledger.rs` |
| QBF-C002 | Domain Transfer Matrix | Built — absent pair = DENY; denials D7→D2, D9→D2, D9→D0, D11→D0, D12→D4, D13→D4/D7/D8, D14→D13 tested | `src/d0/matrix.rs` |
| QBF-C003 | Query/Ingestion Path Separation | Built — intersection checked in tests; D4 never calls an extractor | `src/d0/matrix.rs` |
| QBF-C004 | Domain Slice Priority Ordering | Partial — ordering declared (D0 first, D13 last); no metered scheduler | `src/d0/matrix.rs` |
| QBF-C006 | Context Lock and Key | Built — key over device, entitlement+position, locale, register, audience, posture, cost table, regime, store version | `src/d0/context_lock.rs` |

## D1 · Ingestion & Sensory Intake
| ID | Feature | Status | Where |
|---|---|---|---|
| QBF-C007 | Multimodal Ingestion Pipeline | Partial — text (EPUB/DOCX/HTML/TXT/MD) and structured (UFCS) modalities; independent engines | `src/d1/parse.rs`, `src/d1/ufcs.rs` |
| QBF-C008 | Classification Fallback | Partial — unsupported formats halt with a stated reason (PDF, DRM formats) | `src/d1/parse.rs` |
| QBF-C020 | Engine-Specific Prompt Composition | Built — per-engine profile, catalogue-constrained prompt, JSON schema | `src/d1/engines/llm.rs` |
| QBF-C021 | Reply Conversion to Knowledge Records | Built — registered engines only, retries/backoff, malformed or over-bound reply yields no partial record | `src/d1/engines/llm.rs` |
| QBF-C022 | Derivation Marking and Disclosure | Built — engine + prompt hash in the record, disclosed in every citation | `src/d2/fact.rs`, `web/app.js` |
| QBF-C023 | Self-Corroboration Bar | Built — one engine = one source class; diversity = exp(entropy) (tested 1.0 vs 3.0) | `src/d2/fact.rs` |
| QBF-C024 | Citation Verification of a Reply | Built — every quoted span checked against its passage; unverified records admitted, marked, never ground an answer | `src/d1/engines/llm.rs`, `src/d4/fql.rs` |
| QBF-C025 | Specialized Feed Registration | Partial — UFCS feeds registered by mapping file with authority, ACL, cursor; auto-registered predicates take the argument slots they are used with | `src/d1/ufcs.rs` |
| — | Language pipeline, stages 1–7 (segmentation, parsing, entities/relations, FU construction, CFI anchoring, embedding, query integration) | Built — deterministic `language` engine (default); see README | `src/d1/language/`, `src/d1/pipeline.rs`, `src/d4/query.rs` |

## D2 · Knowledge Substrate
| ID | Feature | Status | Where |
|---|---|---|---|
| QBF-C030 | Fact Unit Schema | Built — FUID(content, source, time), fingerprint, type, atom, temporal/spatial/narrative anchors, evidence pair + source classes, provenance, modality, safety, ACL, typed edges, supersession, derivation, certification | `src/d2/fact.rs` |
| QBF-C031 | Provenance Ledger | Built — append-only, hash-linked, keyed checksum over the safety evaluation, Ed25519-signed, Merkle root per batch | `src/d2/ledger.rs` |
| QBF-C032 | QueryBook Format (QBF) | Built — framed records with CRC; corrupt frame costs one frame (tested) | `src/d2/fact.rs` |
| QBF-C033 | Storage Architecture | Partial — opaque blob store + retrieval index; no hot/cold tiering | `src/d2/store.rs`, `src/d2/index.rs` |
| QBF-C281 | Uncertainty decomposition | Built — epistemic (posterior variance) and aleatory components | `src/d2/fact.rs` |
| QBF-C282 | Assertion polarity field | Built — participates in the fingerprint (tested) | `src/d2/fact.rs` |
| QBF-C283 | Native n-ary assertion structure | Built — role-keyed args under one FUID/fingerprint/evidence pair | `src/d2/fact.rs` |
| QBF-C284 | Applicability-scope field | Partial — field present; not yet used in conflict slots | `src/d2/fact.rs` |
| QBF-C285 | Immutable adjustment-history layer | Built — corroborations appended to `adjustments` | `src/d1/ufcs.rs` |
| QBF-C286 | Hash-linked supersession | Partial — supersession recorded and honoured by retrieval and pre-computed answers; successor hash link not yet populated | `src/d2/store.rs` |
| QBF-C287 | Canonical compact encoding | Built — zstd frames; same FUID/fingerprint as the full form (tested) | `src/d2/fact.rs` |
| QBF-C288 | Record-fused encoding | Built — the frame is the at-rest and export form | `src/d2/fact.rs` |
| QBF-C289 | Opaque-blob storage contract | Built — SQLite holds frames it never parses | `src/d2/store.rs` |
| QBF-C290 | Internal fact query with edge translation | Built — FQL compiled at the adapter into index queries | `src/d4/fql.rs` |
| QBF-C291 | Confidentiality & integrity across the boundary | Partial — ACL, safety class and integrity travel in the record; no record encryption | `src/d2/fact.rs` |
| QBF-C292 | Fact Unit Language | Partial — governed predicate catalogue; non-conforming candidates refused at admission | `src/d3/catalog.rs` |

## D3 · Ontology & Conceptual Structure
| ID | Feature | Status | Where |
|---|---|---|---|
| QBF-C035 | Ontology Mesh | Partial — governed predicates, canonical concept ids per work, typed edges only where records connect | `src/d3/`, `src/d1/pipeline.rs` |
| QBF-C042 | Event Type Catalogue | Partial — registered type list with construction-time validation; lattice classes carry poly-hierarchical placement (domain → subdomain → class) | `catalog/predicates.json`, `src/d3/lattice.rs` |
| QBF-C113 | World-View Model (ontological part) | Partial — the knowledge lattice: 20 domains, 158 classes, 158 slots, 15 rules, live-validated ids, ledgered registration by content digest | `src/d3/lattice.rs`, `config/lattice/` |

## D4 · Retrieval & Response
| ID | Feature | Status | Where |
|---|---|---|---|
| QBF-C046 | Standard Q&A | Built | `src/d4/query.rs` |
| QBF-C050 | Semantic Exploration | Built — neighbours ranked by co-assertion strength | `src/d4/query.rs` (`explore`) |
| QBF-C051 | Timeline Reconstruction | Built — event records in narrative order | `src/d4/query.rs` (`timeline`) |
| QBF-C053 | Flashcard Generation | Built — one card per Fact Unit | `src/d14/mod.rs` |
| QBF-C054 / C058 | QBQL / execution floor (FQL) | Built — read-only, joint structure + trust + status + scope filter, rendered with every answer | `src/d4/fql.rs` |
| QBF-C056 | Attractor Network | Built — contraction regime (unique fixed point) and capacity regime (energy descent) | `src/d4/attractor.rs` |
| QBF-C060 | Clarification Generation Engine | Built — ambiguous partial names; unresolved competing candidates | `src/d4/query.rs` |
| QBF-C064 | Attractor Load Regime Governor | Partial — load ratio reported; ceiling validated in config | `src/d4/attractor.rs`, `src/config.rs` |
| QBF-C065 | Energy Descent and Termination | Built (capacity regime) | `src/d4/attractor.rs` |
| QBF-C066 | Convergence Regime Disclosure | Built — regime returned with every answer; election ledgered with operator identity | `src/app.rs` |
| QBF-C067 / C068 | Edge-Class Traversal Cost / Reach | Built — budgeted pre-activation along typed edges | `src/d4/query.rs` (`stabilize`) |
| QBF-C074 | Competitive Candidate Resolution | Built — inhibitory weights between inconsistent candidates; unresolved pairs ask for clarification | `src/d4/query.rs`, `src/d4/attractor.rs` |

## D5 · Inference, Prediction & Calibration
| ID | Feature | Status | Where |
|---|---|---|---|
| QBF-C082 | Probable Question Generation | Built — at ingestion, over central concepts, coverage floor | `src/d4/pqg.rs` |
| QBF-C083 | Pre-Computed Answer Set | Built — stored with contributing FUIDs, confidence bounded by the weakest | `src/d4/pqg.rs` |
| QBF-C084 | Question Index Reuse and Invalidation | Built — served only if unrevised and inside the reader's scope (tested) | `src/d4/pqg.rs` |
| QBF-C089 | Bayesian Posterior Update | Built — Beta evidence pair, reliability-class priors | `src/d2/fact.rs` |
| QBF-C097 | Observation Diversity Measure | Built | `src/d2/fact.rs` |
| QBF-C094 | Discriminating Instance Selection | Partial — lattice fill orders columns by the uncertainty of the rules whose forecasts they test (Beta variance), then by expected yield | `src/d12/lattice.rs` (`fill`) |
| QBF-C101 | Confidence Band Calibration Gap | Built — per-band realized vs stated confidence over decided predictions; gaps ≥ 0.10 over ≥ 20 outcomes become proposals to the named operator; tolerance held fixed in code | `src/d5/expect.rs` |
| QBF-C102 | Predictive Level Registration | Partial — conceptual level (slot presence at census fill rate; class-mode values) and invariant level (inverse, symmetric, chain, constant rules); engine recall as a lowest-trust level; lexical and sequential levels not built | `src/d5/expect.rs` |
| QBF-C103 / C104 | Lowest-Level Error Attribution / Escalation Gate | Partial — a refutation with a multi-valued premise is attributed conceptually and does not revise the rule; otherwise to the prediction's own level | `src/d5/expect.rs` (`confirm`) |
| QBF-C105 | Unattributed Error Retention | Built — refutations by contested records revise nothing; repeated ones surface as a pattern finding | `src/d5/expect.rs` |

## D7 · Grounded Expression
| ID | Feature | Status | Where |
|---|---|---|---|
| QBF-C147 | Narrative Graph | Partial — every rendered proposition references its records | `src/d7/mod.rs` |
| QBF-C149 | Structural Groundedness Enforcement | Built — non-derivable propositions rejected (count reported) | `src/d7/mod.rs` |
| QBF-C153 | Wording-Operative Span Preservation | Built — quotes and imported renderings reproduced verbatim | `src/d7/mod.rs` |
| QBF-C159 | Sentence Aggregation | Built | `src/d7/mod.rs` |
| QBF-C160 | Referring Expression Selection | Built | `src/d7/mod.rs` |
| QBF-C161 | Connective Emission | Built — only where a typed edge joins the records | `src/d7/mod.rs` |
| QBF-C162 | Given-Before-New Ordering | Partial — available; ask answers use activation order | `src/d7/mod.rs` |

## D8 · Access, Rights & Retention
| ID | Feature | Status | Where |
|---|---|---|---|
| QBF-C165 | Reader History Interface | Built | `src/d8/mod.rs`, Account page |
| QBF-C169 | Data Export / Portability | Built | `/api/export` |
| QBF-C170 | Portal / Role Model | Partial — reader, author, instructor, researcher, operator | `src/d8/mod.rs` |
| QBF-C171 | License and Entitlement Management | Built — seat AND entitlement | `src/d8/mod.rs` |
| QBF-C172 | Live-Session Erasure | Partial — session-scope erasure | `src/d8/mod.rs` |
| QBF-C173 | Retention Policy | Built — retain by default; session/account erasure; ledgered without content | `src/d8/mod.rs` |
| QBF-C177 | Tenant-Scoped Key Custody | Partial — deployment keys in the data directory | `src/d2/ledger.rs` |
| QBF-C178 | Signed Provenance Ledger Verification | Built — `qb verify`, Account page | `src/d2/ledger.rs` |

## D9 · Interaction Surfaces
| ID | Feature | Status | Where |
|---|---|---|---|
| QBF-C179 | Fact Graph Visualization | Partial — scoped neighbour list, no graph drawing | `web/app.js` |
| QBF-C180 | Inline Fact Previews | Built — from the response, no new query | `web/app.js` |
| QBF-C182 | Personal Notes | Built — owner-only ACL records (tested) | `src/d9/mod.rs` |
| QBF-C192 | Native QueryBook Reader | Partial — paginated reader with `data-qb-*` hooks; not a full EPUB 3.3 reading system | `web/` |
| QBF-C196 | Spoiler Protection | Built — scope bound before traversal; beyond-position notice; role exemptions (tested) | `src/d8/mod.rs`, `src/d4/fql.rs` |

## D10 · Authoring, Editions & Publication
| ID | Feature | Status | Where |
|---|---|---|---|
| QBF-C205 / C216 | Manuscript Upload / Author Portal Book Upload | Built — rights declaration required before ingestion | Admin page, `src/d9/mod.rs` |
| QBF-C212 | Market Analytics | Partial — what readers ask per book, unanswered flagged | Admin page |

## D11 · Platform Governance & Evolution
| ID | Feature | Status | Where |
|---|---|---|---|
| QBF-C238 | Determinism Verification | Built — output hash under the context key (tested) | `src/d4/query.rs`, `tests/invariants.rs` |

## D14 · Learning & Assessment
| ID | Feature | Status | Where |
|---|---|---|---|
| QBF-C275 | Comprehension Check | Built — multiple choice; every option is itself a record | `src/d14/mod.rs` |
| QBF-C277 | Study and Learning Tools | Built — spaced repetition (tested) | `src/d14/mod.rs` |
| QBF-C278 | Learner Progress Tracking | Built — mastery per work | `src/d14/mod.rs` |

## Not in this prototype

D6 (world model, perception, robotics and equipment control), D12 (external
agents, forensic analysis, live feeds beyond UFCS import and the Wikidata
connector — QBF-C249 is partially built in `src/d12/`), D13 (commerce, NFTs),
media transformation (colorization, VR/3D, AR), multilingual regeneration,
audio narration, forecasting and hypothesis generation, the neuromorphic analog
realization (QBF-C070..C073), social annotations, message boards, class boards,
collaborative reading, voice navigation and the modulation layers
(QBF-C198..C202, C293). The domain boundaries they would plug into (matrix
entries, scope, permits, ledger) are in place.
