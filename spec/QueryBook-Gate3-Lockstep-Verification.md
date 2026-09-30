# QueryBook — Gate 3 Documentation Lockstep Verification

**Gate 3 deliverable · 2026‑09‑30**
Gate 3 requires that Code ⇄ Bible ⇄ Registry ⇄ Provisional Patent (spec, drawings,
descriptions) never drift, and that "update everything" lands as **one coordinated,
verified change‑set** — not piecemeal. This document records that change‑set and
proves the five artifacts agree via the traceability map.

The engine itself is **unchanged** at Gate 3: the frozen baseline
`QueryBook-baseline-v9.15` (commit `df76b58`) still passes the Gate 1 harness
17/17 across 5 runs with one signature (`937f6413…`) and 5/5 UI pages with zero
JS errors. This change‑set is documentation reconciliation only — bringing the
docs up to what the frozen code already does, plus specifying the creativity loop.

## What this change‑set reconciles

Two gaps existed after Gate 0 (named in Canonical Engine Spec §10):
1. **Phase 4 (speech)** was built in code and recorded in the Registry ([191]), but
   the **Bible had no Phase‑4 section** — it still called Phase 4 "roadmap."
2. The **LLM‑parity creativity loop** (spec §8/§8.1) was specified but **undocumented**
   in the Bible, Registry, and Patent.

Both are now closed, consistently, across every artifact.

## Coordinated edits (this change‑set)

| Artifact | File | Change |
|---|---|---|
| **Canonical Spec** | `spec/QueryBook-Canonical-Engine-Spec.md` | §8.1 answers (v1.1, earlier); §10 map updated — the three "gap → Gate 3" cells resolved with concrete cross‑refs |
| **Acceptance criteria** | `spec/QueryBook-Gate2-Acceptance-Criteria.md` | new (Gate 2); AC‑F1…F5 define the creativity‑loop criteria |
| **Bible** | `docs/QueryBook-Bible-Updated.html` | new appended amendment **"Phase 4 Speech and the LLM‑Parity Creativity Loop (2026‑09‑30)"** — records Phase 4 reduced to practice (4a analysis + 4b OS voice, no fabrication) and the named creativity loop with the EQUAL/SUPERIOR bars and covenant compliance |
| **Registry** | `docs/QueryBook-Registry-Updated.txt` | reconciled to the newest revision (now carries [191] Phase 4, which the stale `docs/` copy lacked) **and** new block **[192] 17.9 — LLM‑parity creativity loop**; feature count 195 → **196** |
| **Provisional Patent** | `patent/ppa_lel.html`, `patent/ppa_combined_print.html` | Section VII: [0024] tail corrected (Phase 4 no longer "the only roadmap phase"); new **[0025]** (Phase 4 deterministic analysis + OS voice, reduced to practice) and **[0026]** (creativity‑parity process as a **preferred/prophetic** embodiment, adds no claim); counsel flag updated to range [0019]–[0026] with an exact reduced‑to‑practice vs preferred/prophetic split |
| **Patent PDFs** | `patent/QueryBook-LEL-Provisional-Patent-Application.pdf` (18 pp), `patent/QueryBook-Provisional-Patent-Application-COMPLETE.pdf` (30 pp) | regenerated from the edited HTML via headless Chromium; both verified to contain [0025], [0026], and the creativity‑parity text |

## Traceability — every spec item maps across all artifacts

| Spec item | Code (frozen baseline) | Bible | Registry | Patent |
|---|---|---|---|---|
| Fact Unit (§3) | `ufcs_store.make_packet/fingerprint` | "1. The Fact Unit" | Domain 4 / [1xx] | FIG 8; [0019] |
| Gate/FQL (§5) | `qb_chat.gate`, `ufcs_store.fql` | Prime Directive; Reasoning‑Family "Gate note" | reasoning entries | [0023] |
| Phase 1 (§6) | `qb_language.learn/metrics` | Language amendment; Phase‑4 amendment | [184] | [0019]‑[0020] |
| Phase 2 (§6) | `qb_language.ground_words` | No‑LLM covenant amendment | [185] | [0021]; FIG 8 |
| Phase 3 (§6) | `qb_language.acquire_language` | Reasoning‑Family amendment | [190] 16.9 | [0024] |
| Phase 4 (§6) | `qb_language.speech_analyze/speak` | **Phase‑4 amendment (new)** | [191] 16.10 | **[0025] (new)** |
| Agents (§7) | `qb_agents.ROLES` (12, all built) | Agent Architecture + Reasoning‑Family | [186]‑[189] | [0023] |
| **Creativity loop (§8/§8.1)** | hypothesis/simulation + `qb_log` | **Phase‑4/creativity amendment (new)** | **[192] 17.9 (new)** | **[0026] (new, prophetic)** |

No "gap" cells remain.

## Consistency assertions (verified)

- **Status parity.** Bible, Registry, and Patent now all state Phases 1–4 reduced to
  practice deterministically, with the *neural* forms (LEL, neural grounding, neural
  cross‑lingual alignment, neural vocoder) as preferred embodiments. No artifact still
  calls Phase 4 "roadmap."
- **Covenant parity.** All three describe the creativity loop identically: the LLM only
  *proposes*; nothing it generates is asserted without independent store verification
  (C6). The patent frames the parity process as **prophetic** (not reduced to practice),
  consistent with the covenant and the counsel flag.
- **Numbers parity.** Registry feature count is internally consistent (196 = 195 + [192]);
  patent paragraph range in the counsel flag ([0019]–[0026]) matches the body.
- **PDF ↔ source parity.** Both regenerated PDFs were text‑extracted and confirmed to
  contain [0025], [0026], and the creativity‑parity language, matching the HTML sources.

## Standing flags carried forward (unchanged, for counsel/commercial review)

- **License:** the bundled bilingual data (Phase 3) is a **CC BY‑NC demo** (MUSE) — replace
  with a public‑domain/permissive source before commercial use. Stated in code, Registry
  [190], Bible, and patent [0024].
- **Counsel:** patent counsel flags on UFCS/FQL claim scope and on the reduced‑to‑practice
  vs preferred/prophetic split remain in the document for review before filing.

## Gate 3 exit criteria
1. "Update everything" landed as one coordinated change‑set (this document). ✓
2. All five artifacts agree via the traceability map (no gap cells). ✓
3. The engine still passes the Gate 1 suite (unchanged frozen baseline). ✓
4. Standing license/counsel flags are carried forward, not dropped. ✓
