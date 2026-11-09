# VeriWave — the QueryBook AI model (prototype 0.1)

VeriWave is an AI model built on QueryBook technology. It presents a **chat**, plus an alternative screen for each
thing it does:

| Screen | What it does |
|---|---|
| **Chat** (default) | One conversation for everything. Each message is routed to Answer, Code, Create or a QueryBook screen; `/answer`, `/code`, `/text`, `/image`, `/video`, `/audio`, `/open` choose explicitly. Follow-ups ("when was *it* founded?") reuse the last subject. |
| **Answer** | QueryBook's cite-or-refuse Q&A (registry #1). The verdict is VERIFIED, CONTRADICTED or UNKNOWN, with numbered citations, their trust, an adjustable trust threshold (default 50%) and a SHA-256 provenance hash. A question with no QueryBook fact behind it gets "I don't know". |
| **Code** | Describe an application and get its files, a live sandboxed preview and a .zip. Locally there are eleven kinds: to-do, calculator, timer, notes, quiz, unit converter, guessing game, sketch pad, landing page, record keeper with your fields, and a Python command-line tool. |
| **Create: Text / Image / Video / Audio** | Text: stories, poems, haiku, letters, articles grounded in QueryBook facts, lists and slogans. Images: vector scenes. Video: a storyboard and an animated film with captions. Audio: music, rain, ocean, wind, alarm and beep, and speech via espeak-ng. |
| **QueryBook** | Every QueryBook screen (67 interfaces: every tab of the Language Builder, STEM, History & News, Video Studio and Control Panel, the Book Studio, QueryBook's own window) with live status. Open any one, tick several, or open all. |
| **Workspace** | Any set of those screens at once: as tabs, side by side or in a grid. They stay loaded while you switch. |
| **Feature Registry** | All 407 features of the QueryBook Composite Feature Registry v71: rule, formula, status, where each lives, and a button to open the screen that serves it. |

The Reader / Author / Instructor / Admin switch works as it does in QueryBook: the Operate screens and admin tabs are
for Admin only.

## Start it

```bash
python veriwave.py
```

Or double-click `START-VeriWave-WINDOWS.bat` or `START-VeriWave-MAC.command`. It opens http://127.0.0.1:8095/.

- If a QueryBook window is already running (port 8090), VeriWave uses its applications. Otherwise VeriWave starts them
  itself with QueryBook's own launcher, so `data-folder.txt` (e.g. `D:\QB`) and the ports are QueryBook's.
- The Book Intelligence Studio (this repository's PHP app) is started with `php -S` when PHP is installed.
- Options: `--no-querybook` (run alone), `--attach`, `--start`, `--no-books`, `--no-browser`, `--port N`.
- Creations are kept in `$VERIWAVE_DATA`, else `<QueryBook data folder>/veriwave`, else `veriwave/data-local/`.

### Engines

- **Local** (always on, offline, no keys, deterministic): the same prompt makes the same output. Answers come only
  from QueryBook facts and exact arithmetic. Creations come from VeriWave's own generators: a template app builder,
  a composer, a vector painter, an animator and a synthesiser. The local text and code are serviceable but templated.
- **Claude** (optional): set `ANTHROPIC_API_KEY` before starting. Chat, writing, code, SVG drawing and storyboards then
  come from Claude (default model `claude-opus-5-5`, override with `VERIWAVE_MODEL`). Answers stay cite-or-refuse:
  Claude only rewords the facts QueryBook found, and the verdict and citations remain VeriWave's. Claude's output
  goes through the same checks as local output: safe file paths, and SVG with no scripts or links. The window's
  Engine menu can force *Local only*.

## Python ready for Rust, fused with Lean

- **Rust-ready Python**: standard library only, every function fully annotated, no reflection, no `*args`/`**kwargs`,
  no regular expressions. Trust is a whole percentage and arithmetic uses exact rationals bounded by 2^62, so
  Python, Rust and Lean give identical results. `tests/test_rust_compat.py` enforces this.
- **Lean in every function**: every module, class, method and function docstring in `vw/` carries a `Lean:`
  section. It holds the Lean 4 definition that mirrors the Python, theorems about it, and `#guard` vectors, each with a
  `-- py:` twin. `tools/gen_lean.py` extracts these into `lean/VeriWave/*.lean` (core Lean 4, no Mathlib).
  `tests/test_fused_lean.py` fails if any function lacks Lean, if the Lean files are stale, if a `py:` twin is false,
  or if `sorry`, `admit` or `native_decide` appear. `lake build` (in CI) checks every theorem and evaluates every guard.
  Proofs cover things like: the trust gate only offers facts at or above the threshold, every gated fact is counted
  exactly once, an answer with no citation is UNKNOWN and one with citations never is, samples stay in 16-bit range,
  registry searches respect their limit, and non-admins never see admin screens. I/O functions (HTTP, processes,
  files) carry Lean for the decisions they make; SHA-256 and floating-point synthesis are named as external primitives.
- **Rust port**: `rust/vwcore` ports the core, the router and the verdict/calculator. It must equal the Python on
  `contracts/vectors.tsv` (`tools/gen_vectors.py`).

## Check it

```bash
python -m unittest discover -s tests -t .
```

```bash
python tools/gen_lean.py --check && python tools/gen_vectors.py --check
```

```bash
cd rust/vwcore && cargo test --release
```

```bash
cd lean && lake build
```

`.github/workflows/veriwave.yml` runs all four: Lean, Rust, and Python on Windows, macOS and Linux.

## Layout

| Path | What it is |
|---|---|
| `veriwave.py` | Starts VeriWave |
| `vw/model.py` | The VeriWave model: one entry point per capability, engine choice |
| `vw/router.py` | Which capability a chat message asks for |
| `vw/answer.py`, `vw/verdict.py` | Cite-or-refuse answers: trust gate, verdict, conflicts, provenance, exact arithmetic |
| `vw/codegen.py`, `vw/textgen.py`, `vw/imagegen.py`, `vw/videogen.py`, `vw/audiogen.py` | The generators |
| `vw/interfaces.py`, `vw/registry.py` | Every QueryBook screen, and the 407-feature registry |
| `vw/querybook.py` | Attaching to, or starting, QueryBook one and the Book Studio |
| `vw/backends.py` | The optional Claude engine (Messages API over `urllib`) |
| `vw/store.py`, `vw/server.py` | Creations folder; HTTP window and API |
| `ui/` | The window |
| `lean/`, `rust/vwcore/`, `contracts/`, `tools/` | Lean project, Rust port, golden vectors, generators |

## Not yet built (next stages)

- Photoreal images and real MP4 video. Locally, pictures are vector scenes and films are animated SVG. Video Studio
  (one click from a film) renders MP4 with personas and narration.
- Speech without espeak-ng installed. The Language Builder's Speech tab has more voices.
- Most of the 223 registry features marked "Not built yet". The Feature Registry screen lists them; VeriWave adds
  #1 (cited Q&A over every application), #2 (follow-ups keep their subject) and #3 (disagreements shown side by side).
