# QueryBook (one window)

The new version of QueryBook, built from the QueryBook suite itself, so every feature it has keeps working:

- Language Builder: translation, speech, avatars, lip reading and the rest.
- Math, Science & Engineering.
- History & News.
- Video Studio.
- The Control Panel's harvesting.

They now open in **one window**, with one start file and Python inside.

Stage 1 of the rebuild planned in `docs/querybook-rebuild/` (the 407-feature inventory and screen blueprint).

## For the user

1. Unzip `QueryBook.zip`.
2. Close the old QueryBook windows; they use the same data and the same ports.
3. Double-click `START-QueryBook.bat`.

Your data stays on `D:\QB`, as named in `data-folder.txt`, following the same rule as the suite. If the drive isn't connected, nothing starts.

## What's here

| Folder | What it is |
|---|---|
| `apps/` | The suite's applications (from `claude/lucid-brahmagupta-ak4f6m`, Control Panel 1.36) plus `shell/`, the one window |
| `apps/shell/` | Starts every application in the background, follows `data-folder.txt`, and serves the window with its area rail, role switch and Ask box (`ask.py`) |
| `apps/_core/qbmath.py` | The network-memory and routing arithmetic as pure functions; `qbsynapse` and `qbdsn` call it |
| `lean/` | Lean 4 + Mathlib proofs; see below |
| `rust/qbcore/` | Rust port: every STEM formula, `qbmath`, and Python's exact `round()` |
| `tools/` | `gen_lean.py` and `gen_rust.py` generate the proofs, the Rust formulas and the test vectors from the Python; `build_bundle.py` builds `QueryBook.zip` |
| `tests/` | Ask logic, Lean/Rust kept in step with the Python, and the Rust-compatibility guard |

## Changes made to the suite's code

- The Control Panel's tabs can be opened by link (`#bulk`, `#facts`), so the window's areas land on the right tab.
- Language Builder falls back to the whole of Webster's 1913 for words outside its 5,052 common words. It holds 101,080 headwords and is built by `apps/tools/build_webster_full.py` from Project Gutenberg #29765; "obsequious" now has a meaning.
- `qbsynapse` and `qbdsn` compute through `qbmath.py`. The results are identical and their self-tests pass.
- The test runner works on Windows: it uses UTF-8 output, and test temporary folders tolerate files Windows still has open. This applies to test runs only.

## Verified formula math

| Lean file | Proves | Mirrors |
|---|---|---|
| `Formulas.lean` (generated) | Every solution of the 35 STEM formulas, put back into its formula, gives the original quantity (76 theorems) | `apps/stem/science.py` |
| `Units.lean`, `UnitExamples.lean` (generated) | Conversions round-trip, converting through another unit changes nothing, temperature scales invert; 16 of STEM's own exact conversions | `apps/stem/units.py` |
| `Synapse.lean` | Network-memory strength stays in [0, 1] under any sequence of events; consolidated connections fade more slowly; the threshold stays within 0.30–0.70 | `apps/_core/qbmath.py`, `qbsynapse.py` |
| `Routing.lean` | Pathway strengths stay in [0, 1] under any sequence of lookups; recovery never overshoots 0.5; every new pathway is asked | `apps/_core/qbmath.py`, `qbdsn.py` |
| `Degrees.lean` | Sine in degrees is positive between 0° and 180°; `asind` inverts `sind` | STEM's degree functions |

`.github/workflows/querybook-one.yml` runs on every push:
- `lake build` (the Lean proofs);
- `cargo test` (the Rust port must equal the Python exactly);
- every application's self-test on Windows, macOS and Linux;
- the Windows bundle test: unzip, start with the bundled Python only, ask a word and a conversion.

## Developing

```bash
python -m unittest discover -s tests -t .
```

```bash
cd apps && python -B tools/run_all_tests.py
```

```bash
python tools/gen_lean.py && python tools/gen_rust.py
```

```bash
cd rust/qbcore && cargo test --release
```

After editing `apps/_core`, run `python apps/tools/sync_core.py` (the suite keeps a copy of the core in each application).
