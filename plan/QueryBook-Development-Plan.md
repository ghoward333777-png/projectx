# QueryBook — Foolproof Phased Development Plan
**Version 0.1 (draft for approval) · 2026‑09‑30**
Owner sign‑off required at every gate. No work crosses a gate without evidence + your approval.

---

## 1. North Star
QueryBook is the **technology substrate** for three product surfaces:
1. **Grounded Q&A application** — ask → retrieve verified Fact Units → gate → cited answer, or an honest **UNKNOWN**.
2. **Chatbot** — the same engine; an LLM may *phrase* verified facts, never assert them.
3. **A competitor to LLM engines** — winning on the one axis probabilistic LLMs cannot hold:
   **every answer is deterministic, provenance‑tracked, reproducible, and cannot hallucinate.**

Everything in this plan exists to protect that guarantee while getting to a Rust production SaaS.

**Scope decision (confirmed):** the language phases (SLPL / structural, semantic grounding, multilingual delta, speech) and the core knowledge engine are **one integrated system** — all of it exists to enhance QueryBook in **language, speech, and communication** in service of the Q&A app, the chatbot, and the LLM‑competitor positioning. Therefore there is **one Canonical Engine Spec**, not two; the language/speech capability is a first‑class part of it, not a side track.

## 2. Why this process (the problem it fixes)
The prior mode was *edit → ship → user finds a break → repeat* (dead links, a flaky stop‑test, "old version" churn). For patent‑bearing IP with a hard correctness covenant, that is unacceptable. This plan replaces it with **specification‑first, gated, evidence‑before‑advance** engineering.

## 3. Governing Principles (apply to every gate)
1. **Spec before code.** Testable acceptance criteria are written first; code is measured against them.
2. **The covenant is an invariant, not a feature.** No LLM grounds meaning or asserts a fact; every asserted fact carries a traceable source; identical inputs produce identical output. Every gate re‑proves this.
3. **One source of truth, updated in lockstep.** Code ⇄ Bible ⇄ Registry ⇄ Provisional Patent (spec, drawings, descriptions) never drift; a change is not "done" until all agree.
4. **No silent edits.** Every change names what it changes, why, and the criterion it satisfies.
5. **Reproducibility is the deliverable.** A green, flake‑free automated suite — not anyone's say‑so.
6. **Refuse rather than fabricate.** Any capability that cannot be done soundly declines, visibly, and is marked roadmap.

## 4. The Covenant — invariants every gate must verify
| # | Invariant | How it is checked |
|---|-----------|-------------------|
| C1 | No LLM grounds meaning or asserts a fact | code path audit + `LLM_LOCKOUT` test; zero `means_llm`/LLM‑sourced asserted facts |
| C2 | Every asserted fact has a traceable source | provenance audit over the store |
| C3 | Deterministic: same input → same output | property test on fingerprints / md5 of exports |
| C4 | Unknown → refuse (no invention) | gate returns UNKNOWN with no fabricated content |
| C5 | Dedup: identical meaning → identical fingerprint → stored once | dedup test |
| C6 | LLM allowed only to phrase verified facts, or propose (hypothesis/simulation) subject to store verification | non‑assertion test on those agents |

## 5. Gate Protocol (unchanging)
For every gate: **I present evidence → you review → you approve or return it → only then the next gate.** No shipping between gates without your sign‑off.

---

## 6. The Gates

### Gate 0 — Freeze & Specification  *(START HERE)*
**Purpose:** stop moving parts; capture the exact truth of what exists as the fixed reference.
**Work products:**
- **Baseline freeze** — tag the current prototype `QueryBook‑baseline` (folding in the already‑written Phase‑4 + stop‑race fix as *part of the frozen baseline*, not a live ship).
- **Canonical Engine Spec** — the single source of truth: Fact Unit contract; storage/determinism; FQL + Prime‑Directive gate; the covenant as numbered testable invariants (§4); the phases and agent family with each item's status (reduced‑to‑practice vs roadmap); how the three product surfaces map onto the engine.
- **Traceability map** — table linking every spec item → code location → Bible section → Registry entry → Patent section/figure. This is what makes "lockstep" enforceable.
**Tracked capability to specify in Gate 0 (owner‑raised, 2026‑09‑30):**
- **"LLM‑parity creativity loop."** Hypothesize and *simulate LLM‑style answers*, archive them, and **analyze + graph the archived records over time** to drive QueryBook toward **equal‑or‑superior LLM‑level creativity and language skill without hallucination.** The spec must define: what "simulate an LLM answer" means operationally; what is archived and graphed; how "creativity/language parity" is *measured* (the benchmark); and how it stays inside the covenant (LLM output is a non‑asserting candidate, verified against the store; nothing generated becomes an asserted fact). Currently only *latent* across the hypothesis/simulation agents + the event/archive log; not documented as one capability. Documentation (Bible/Registry/Patent) is written at Gate 3, not before.

**Exit criteria (you approve on):** spec matches reality (no aspiration mixed in); every covenant invariant has a stated check; the LLM‑parity creativity loop is specified and measurable; freeze tag exists; traceability map complete.
**Evidence I show:** the spec text + a one‑command run of the baseline proving it behaves as specified.

### Gate 1 — Test Harness
One command, flake‑free automated suite proving §4 invariants + core behavior (fingerprint, round‑trip, dedup, gate, each phase, each agent, UI render with zero JS errors). Must pass N consecutive runs (this is what would have caught the 24×7‑stop race before you saw it).
**Exit:** suite green, repeatably. **Evidence:** runner output + reproducibility check.

### Gate 2 — Acceptance Criteria per Component
For each subsystem write explicit pass/fail criteria. Nothing is built or "fixed" without a criterion it must meet.
**Exit:** you approve the criteria set.

### Gate 3 — Prototype Hardening + Documentation Lockstep
Only now do features/fixes proceed, each tied to a criterion and verified against the suite. **This is where "update everything" happens:** Bible, Registry, Provisional Patent spec, Drawings, and Descriptions are updated **together as one coordinated change‑set**, proven consistent via the traceability map, before delivery.
**Exit:** all criteria green; all five artifacts agree; suite green.

### Gate 4 — Rust Production Specification
Architecture; the binary Fact Unit format; index/LSM design; concurrency model; RAM/storage budgets (tied to the growth projections, ~120 B/fact); the covenant enforced in the type system.
**Exit:** you approve spec + budgets before any Rust is written.

### Gate 5 — Rust Implementation (module by module)
Each module ships with **parity tests against the Python prototype** (e.g. fingerprints byte‑for‑byte identical).
**Exit:** parity green per module.

### Gate 6 — Scale, Security & Provenance Audit
Load tests at projected fact volumes; security review; provenance audit proving no asserted fact lacks a traceable source.

### Gate 7 — SaaS Deploy (Ubuntu)
Packaging, ops, monitoring, backup/restore, internal→external tiered storage, deployment runbook.

---

## 7. "Update everything" — where it lives
The pending Phase‑4 updates to **Bible, Registry, Provisional Patent, Drawings, and Descriptions** are **deferred into Gate 3** as a single coordinated, verified change‑set (after Gate 0 freezes the baseline and Gate 2 sets the criteria). They will not be edited piecemeal. This guarantees the five artifacts are mutually consistent and provable — which is the whole point of your instruction.

## 8. Definition of Done (any deliverable)
1. Meets its written acceptance criterion. 2. Covenant invariants (§4) re‑verified. 3. Automated suite green. 4. All affected artifacts (code/Bible/Registry/Patent) updated in the same change. 5. Evidence presented; you approved.

## 9. Immediate next step (awaiting your go)
Execute **Gate 0 only**: produce the **one** Canonical Engine Spec (core knowledge engine + integrated language/speech/communication) + the baseline freeze, presented in chat for your review. **No feature code, no ad‑hoc document edits.** Scope question is resolved: a single integrated spec.
