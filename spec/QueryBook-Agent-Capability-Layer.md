# QueryBook — Agent Capability Layer

**v1.0 · 2026‑09‑30 · reference implementation in `agent-capabilities/`**
Consumers expect a modern agent to browse, use apps, create files, run tools, use
cloud compute, span devices, remember projects, collaborate, plan, and ask before
acting. QueryBook gives its agents all ten — with each one **subordinated to the
Covenant** (Canonical Engine Spec §2). That subordination is the product: the
capabilities of a general agent, under a guarantee no general agent offers.

## The one rule that governs every capability
A capability either brings data **in** or pushes an effect **out**.
- **Data in** (web, connected-app reads, tool output, another agent, another device)
  enters as a **sourced candidate** in an isolated low‑trust domain. It **cannot answer
  or assert** until the deterministic store independently verifies it. External input
  never becomes truth by arriving.
- **Effect out** (send, post, publish, delete, connector writes, irreversible ops)
  requires **explicit human approval** and is **provenance‑logged**. The agent proposes;
  the human disposes.

Determinism and content‑addressed dedup make the rest safe: the same fact from two
devices or two agents collapses to one identity, and a functional‑relation conflict is
surfaced by the gate rather than silently overwritten.

## The ten capabilities

| # | Capability | Mechanism | Covenant guard | Acceptance criterion (tested) |
|---|-----------|-----------|----------------|-------------------------------|
| 1 | Local agent uses cloud compute | `offload(job, …, adapter)` — run a job locally or dispatch to a remote worker | The job is pure over its inputs, so local and remote agree by fingerprint (C3) | local == remote fingerprint ✓ |
| 2 | Browse the web | `intake_candidate()` writes page extractions as sourced candidates; `verify_or_refuse()` answers only from the authoritative store | Web text is a candidate at trust < 0.5; it is UNKNOWN until an independent verified fact exists (C1/C4/C6) | candidate = UNKNOWN, then VERIFIED after promotion ✓ |
| 3 | Use connected apps | `Connector` reads → candidates; `Effect` writes (send/post) via `ApprovalGate` | Reads are sourced candidates; **writes never run without human approval** and are logged (C6 + approval) | effect blocked pre‑approval, executed + logged after ✓ |
| 4 | Create files | `build_file()` composes only verified claims; writes a `.provenance.json` manifest | Cite‑or‑refuse for files: an unverified claim is omitted, not written (C4) | verified claim written, unverified omitted, manifest present ✓ |
| 5 | Run tools | `ToolRegistry` with kinds `assert` / `intake` / `effect` | Deterministic tools may assert (provenance‑stamped); external tools are approval‑gated effects | deterministic tool asserts; effect tool gated ✓ |
| 6 | Track projects over time | `ProjectLedger` — append‑only JSONL of goal/step/unit/status/artifact | The ledger is itself provenance‑tracked and **replays deterministically**; state survives reload | status persists + replays identically ✓ |
| 7 | Local computer + other devices | `sync_devices()` merges stores by fingerprint | Merge is a deterministic union with dedup (C3/C5); functional conflicts stay visible to the gate | shared fact deduped, unique fact merged ✓ |
| 8 | Work with other agents | `AgentTeam` on one shared authoritative store | No agent injects an unverified fact; disagreement → CONTRADICTED, both values kept, no silent overwrite | two agents disagree → CONTRADICTED ✓ |
| 9 | Break work into steps/units | `Planner.decompose()` → ordered units; **halts on ambiguity** | The plan is a non‑asserting proposal; an underspecified goal returns a question, not a guess (C4) | ambiguous goal halts; clear goal → 3 units ✓ |
| 10 | Subject itself to human approval | `ApprovalGate` + `Effect.run()` | An effect runs only when approved; unapproved/denied effects never touch the world; every decision logged | unapproved/denied effect never executes ✓ |

All ten criteria are proven by `agent-capabilities/test_qb_capabilities.py`
(**10/10, flake‑free across repeated runs**), each test asserting the *guard*, not
merely that the feature runs.

## What is real here, and what is an adapter
The **framework** is real and tested: the approval gate, the candidate→verify boundary,
the project ledger, the planner, the tool registry, device‑sync merge, the multi‑agent
shared store, and cloud offload. The **heavy external integrations** — a real headless
browser, specific connected apps (Gmail, Drive, Slack…), a real cloud worker, real
cross‑device transport — are injected behind clean interfaces (`adapter`, `Connector`,
`Effect` functions). This is deliberate and honest: the covenant‑critical logic is
built and verified now; each real adapter plugs into an interface that already enforces
the guard, so adding one cannot widen what an agent is allowed to assert or do unapproved.

## Where it belongs in the plan
This layer is specified with acceptance criteria (Gate‑2 style) and a tested reference
implementation (Gate‑3 style), and it **does not touch the frozen baseline** — it binds
to it read‑only for the proven Fact Unit primitives and the gate. In the production
build (Gate 4/5), the same interfaces are re‑expressed in Rust with the guards in the
type system: a candidate has no path to an asserted fact except verification, and an
effect has no path to execution except an approval token.

## Run it
```bash
python agent-capabilities/test_qb_capabilities.py   # 10/10 covenant-guard tests
```
