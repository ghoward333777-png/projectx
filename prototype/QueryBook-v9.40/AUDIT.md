# QueryBook — Full Application Audit
**Build audited:** v9.32 · 2026-10-01
**Purpose:** feature inventory + UX / transparency / accuracy review, indexed to page and location, as the basis for a future SaaS.

Legend — **Status:** ✅ works · 🟡 works but needs polish · 🔶 partial / honest-stub · ❌ broken/missing
**Index notation:** `page → section → control`

---

## 1. App map (7 pages)

| # | Page | Routes | Mission (one line) | Verdict |
|---|------|--------|--------------------|---------|
| 1 | **Chat** | `/`, `/chat` | Ask questions; answer ONLY from verified facts, with citations, else UNKNOWN. | 🟡 thin UI |
| 2 | **Console** | `/console`, `/dashboards` | Rich tabbed demo/explainer of the whole engine (chat, fact studio, dashboards, scaffolds, harvester, languages, pipeline). | 🟡 overlaps dashboard |
| 3 | **Dashboard** | `/dashboard`, `/live` | Operate the engine: harvest, create facts, verify, agents, providers, health. | 🟡 dense |
| 4 | **Language Lab** | `/language`, `/lang` | Learn, translate, and speak languages. | 🟡 improved, still long |
| 5 | **Guide** | `/guide`, `/help`, `/docs` | User manual for every feature. | ✅ good |
| 6 | **Monitor** | `/monitor`, `/status` | Live system health + reach-from-another-device. | ✅ good |
| 7 | **Voice** | `/voice` | Two-way voice, tone/volume, voiceprint, camera. | 🔶 browser-dependent |

**Cross-page finding #1 — redundancy.** Console and Dashboard both expose fact-creation, harvesting, domains, languages, and a chatbot. For SaaS this is two answers to the same question. **Recommend:** make **Console = marketing/explainer (read-only demo)** and **Dashboard = the operator app**; remove operational duplicates from Console.

**Cross-page finding #2 — navigation inconsistency.** Nav label/paths differ per page ("Console" vs "Live status", relative vs absolute hrefs, Voice/Monitor missing from some navs). **Recommend:** one shared header component with identical items and active-state.

---

## 2. Chat — `/` (chat.html)

| Feature | Index | Status | Notes |
|---|---|---|---|
| Ask question | Chat → main → `#q` + `#send` | ✅ | Answers from verified facts or UNKNOWN. |
| LLM status indicator | Chat → header → `#llm` | ✅ | Shows on/off. |
| Citations / provenance in answers | Chat → log | 🟡 | Works but formatting is plain; no copy-citation, no confidence shown. |

**Gaps for SaaS:** no history, no example prompts, no streaming, no empty-state guidance. **Recommend:** starter prompts, message history, visible per-answer trust + source links.

---

## 3. Console — `/console` (console.html)

| Feature | Index | Status | Notes |
|---|---|---|---|
| Demo walkthrough | Console → `#demo-btn` | ✅ | Good for explaining the engine. |
| Light/dark toggle | Console → `#themeBtn` | ✅ | Only page with a manual theme toggle — should be app-wide. |
| Tabs: Chatbot / Fact Studio / Ingestion Dashboard / Live Trace / Recurrence Scaffold / Time Scaffold / Domain Harvester / Live Ingestion / Languages / Pipeline Stages | Console → `#tab-*` | 🟡 | 10 tabs = overwhelming; duplicates Dashboard + Language Lab. |
| Translate (demo) | Console → Fact Studio → `#tr-in`/`#tr-go` | 🟡 | A *second, older* translate UI separate from Language Lab's — inconsistent. |
| Create Fact Unit | Console → `#mk-*` | 🟡 | Duplicates Dashboard "Create Fact Unit". |
| Storage estimator | Console → `#st-*` | ✅ | Useful, unique. |

**Finding:** Console is a powerful explainer but overlaps two other pages and holds a stale translate panel. **Recommend:** reposition as the public demo; delete the duplicate translate/fact tools or make them read-only.

---

## 4. Dashboard — `/dashboard` (dashboard.html)

| Feature | Index | Status | Notes |
|---|---|---|---|
| Domain Navigator | Dashboard → "Domain Navigator" | ✅ | |
| Start / 24×7 / Stop harvest | Dashboard → Harvest Workspace → `#startbtn`/`#run247`/`#stopbtn` | ✅ | |
| 24×7 keep-awake toggle | Dashboard → `#awake247` | ✅ | |
| Create Fact Unit | Dashboard → `#f-*`/`#f-add` | ✅ | |
| Verify / Query | Dashboard → `#q`/`#go` | ✅ | |
| Parallel domain harvest | Dashboard → `#start-all` | ✅ | |
| Insight Visualizer | Dashboard → "Insight Visualizer" | 🟡 | Label says "live"; verify it renders with data. |
| Sources / AI Strategies / Geo | Dashboard → three cards | 🔶 | Marked **planned** — honest, but looks like dead UI; should be visually set apart. |
| Quality Control | Dashboard → `#qc-run` | ✅ | |
| Store Health + Re-check | Dashboard → `#h-refresh` | ✅ | |
| Harvest Meter | Dashboard → "Harvest Meter" | ✅ | |
| Drive Offload | Dashboard → `#mir-start`/`#mir-stop` | ✅ | |
| Event Log + clear | Dashboard → `#log-clear` | ✅ | |
| Agents (create/prune/control) | Dashboard → `#a-*` | 🟡 | Powerful but raw (kind/target/interval/chunk) — not idiot-proof. |
| LLM Providers (add Claude/custom, test) | Dashboard → `#claude-*`/`#p-*` | ✅ | API key entry — **must be masked + never logged** (verify). |
| Hypotheses & Simulations | Dashboard → bottom | ✅ | |

**Findings:** (a) 17 cards on one page — no grouping/tabs. (b) "planned" cards mix with live ones. (c) Agent creation exposes internals. **Recommend:** group into tabs (Harvest / Knowledge / Agents / Integrations / Health); visually badge planned; wrap agent-creation in presets.

---

## 5. Language Lab — `/language` (language.html)  *(most-worked page)*

| Feature | Index | Status | Notes |
|---|---|---|---|
| **Do everything** (English P1–4 + all languages) | Lang → "Do everything" → `#go-btn` | ✅ | The headline flow. |
| Live activity feed + words/sec | Lang → "Live activity" → `#go-feed`/`#go-rate` | ✅ | Streams word · IPA · translation. |
| Legend (which phase → which language) | Lang → hero → `#lang-legend` | ✅ | |
| Teach one language | Lang → "Just one language?" → `#teach-lang`/`#teach-go` | ✅ | |
| Teach ALL | Lang → `#teach-all` | ✅ | Parallel; overlaps "Do everything" (sequential) — two ways to mass-teach. |
| All-languages status table | Lang → "All languages" → `#readiness` | ✅ | Per-row Teach. |
| Translate + auto-detect + speak | Lang → "Translate" → `#tr-src`/`#tr-dst`/`#tr-go`/`#tr-speak` | ✅ | Word-by-word, honest coverage %. |
| English P1 progress + gate | Lang → "Phase 1 progress" | ✅ | |
| Feed your own material | Lang → Phase 1 → `#text`/`#url`/`#files`/`#learn` | ✅ | |
| Build English all 4 / Phase 1 only | Lang → `#run-all-english`/`#start-phase1` | ✅ | Overlaps "Do everything". |
| Live learning detail | Lang → `#detail-lang` | ✅ | Per-word table + phoneme inventory. |
| Analyze & Speak box | Lang → `#speak-text`/`#speak-lang`/`#speak-btn` | 🟡 | Overlaps Translate's speak + Voice page. |
| Diagnostics + copy report | Lang → `#run-diag`/`#copy-diag` | ✅ | All-languages matrix, live write/read test. |
| Language agents table | Lang → "Language agents" | 🟡 | Raw agent view; fine for power users. |
| Hover call-outs | all controls `data-tip` | ✅ | |

**Findings:** fixed the duplicate card (v9.32), but there are still **three ways to start learning** (Do-everything, Teach-all, Teach-one) and **three places that speak** (Translate, Analyze&Speak, Voice page). Page is very long. **Recommend:** keep "Do everything" as the hero; collapse "English details", "Analyze & Speak", "Language agents", and "Diagnostics" into an **Advanced** accordion; make speech one shared component.

---

## 6. Guide — `/guide` (guide.html)
✅ Accurate and current (updated through v9.28). Sections: what it is, install, four screens, harvesting, domains, create, verify, chat, Language Lab (teach/translate/phases/speech/diagnostics), agents, keep-awake, LLM, HTTP API, built-vs-roadmap, troubleshooting. **Minor:** "four screens" now understates it (7 pages) — update count; add screenshots for SaaS.

---

## 7. Monitor — `/monitor` (monitor.html)
✅ Tiles (uptime, facts, blocks, size, rate, LLM), "Open on another device" with copy links, store/domains, collection, agents, subsystems, languages-learned, interface Q&A. **Minor:** "Ask about the interface" duplicates Guide/help; subsystem rows are dense.

---

## 8. Voice — `/voice` (voice.html)

| Feature | Index | Status | Notes |
|---|---|---|---|
| Two-way voice (listen/speak) | Voice → `#listen`/`#speakbtn` | 🔶 | Depends on browser Speech APIs + mic permission. |
| Tone & volume (measured) | Voice → "Tone & volume" | 🔶 | Mic-dependent. |
| Voiceprint enroll/identify/clear | Voice → `#vp-*` | 🔶 | Consent-gated, local-only (good) — but accuracy is heuristic; label as experimental. |
| Camera & sensors | Voice → `#cam-btn` | 🔶 | Camera permission; "who is who" is roadmap. |

**Finding:** this is the least-deterministic, most-permission-dependent page; several features silently do nothing if the browser/OS lacks support. **Recommend:** clear capability checks + "experimental" badges + graceful "not available on this device" messaging.

---

## 9. API surface (44 endpoints)
Facts/engine: `/api/stats /api/fql /api/verify /api/get /api/fact /api/sample /api/health /api/selftest /api/perf /api/version`
Harvest/agents: `/api/harvest /api/harvest_status /api/agents /api/agents/control /api/agent_roles /api/keepawake /api/mirror /api/log /api/monitor`
Domains/knowledge: `/api/domains /api/domain_logic /api/hypotheses /api/plans`
LLM: `/api/chat /api/providers /api/provider_test /api/help`
Language: `/api/language/{go,teach,teach_all,run_all,activity,readiness,detect,translate,words,status,phases,sources,grounding,multilingual,speech,diag,ingest,speak}`

**Findings:** naming is inconsistent (`run_all` vs `teach_all` vs `go` all start learning). No `/api/` version prefix, no documented JSON error shape, no rate limiting/auth layer (security was removed per request). **Recommend for SaaS:** version the API (`/api/v1/…`), one error envelope, consolidate the three "start learning" endpoints, add an auth layer that is OFF for local but available for hosted.

---

## 10. Cross-cutting: look · ease · transparency · accuracy

**Look (visual design)**
- Each page has its own CSS; no shared design system → inconsistent spacing, buttons, colors.
- Only Console has a theme toggle. **Recommend:** one tokenized theme (light/dark) across all pages; shared header/footer; a component kit (button, card, tile, table, badge).

**Ease (UX)**
- Duplicate flows (3× start-learning, 3× speak, 2× create-fact, 2× translate). **Recommend:** one canonical path each; everything else "Advanced".
- Dense single-column stacks of 15–17 cards. **Recommend:** tabs/accordions; progressive disclosure.

**Transparency**
- Strong where it counts: provenance on facts, coverage % on translation, "no LLM" labels, honest "planned/roadmap" badges, diagnostics. This is a genuine differentiator — **keep and surface it more.**
- Weak spots: "planned" cards look live; Voice features fail silently; no global "what is deterministic vs heuristic" key.

**Accuracy**
- Deterministic core is sound (fingerprints, dedup, gate). Translation is honestly labeled word-by-word (not grammatical). Pronunciation rule-seeded. Voiceprint is heuristic. **Recommend:** a per-feature "accuracy class" badge (Deterministic / Dictionary / Heuristic / Roadmap) shown consistently.

---

## 11. Prioritized roadmap to SaaS

**P0 (clarity & trust — do first)**
1. One shared header + design tokens (light/dark app-wide).
2. Collapse duplicate flows: one "start learning", one "speak", one "create fact", one "translate".
3. Visual distinction for Deterministic / Dictionary / Heuristic / Roadmap, applied everywhere.

**P1 (operator ease)**
4. Group Dashboard into tabs; wrap agent creation in presets.
5. Language Lab: hero = "Do everything"; everything else into an Advanced accordion.
6. Capability checks + graceful messaging on Voice.

**P2 (SaaS platform)**
7. Versioned API + one error envelope + consolidated endpoints.
8. Optional auth/tenant layer (off locally, on when hosted).
9. Guide: refresh counts, add screenshots, add an onboarding tour.

---

*Generated by Claude Code for QueryBook v9.32.*
