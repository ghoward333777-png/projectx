# QueryBook Next

The new, Rust-compatible version of QueryBook: a Python app with four separate
apps (**Language**, **STEM**, **History** and **Video Studio**) on one shared
FQL database. It works on top of your **existing QueryBook store on `D:\QB`**:
the suite's Commons and bulk datasets, about a billion facts. It reads that
store in place and never copies or changes it.

Each app has its own page, built around the kind of answer its domain needs: a
dictionary entry, a worked solution, a timeline, or a storyboard and rendered
video. Every answer also shows what your QueryBook store already holds on the
subject.

Full design: [docs/DESIGN.md](docs/DESIGN.md).

## Start

1. Check `data-folder.txt`. It holds one line, the QueryBook data folder,
   shipped as `D:\QB` (the same file and rule as the suite's launchers).
2. Start the app:
   - Windows: double-click `run_windows.bat`
   - Mac: double-click `run_mac.command` (first time: right-click → Open)
3. The hub opens at http://127.0.0.1:8090/. Its "QueryBook store" box shows the
   Commons and every bulk dataset with its fact count.

Requirements and behaviour:
- Python 3.10 or newer; standard library only, nothing else to install.
- If `D:\QB` is on a drive that is not connected, nothing starts. Connect the
  drive and start again.
- QueryBook Next writes only to `D:\QB\querybook-next\`.

## Run an app on its own

Each app can run in its own process on its own port, sharing the same database:

```bash
python -m querybook app history
```

```bash
python -m querybook harvest
```

## Query the store

```bash
python -m querybook fql "Facts.datasets()"
```

```bash
python -m querybook fql "Facts.bySubject(\"Marie Curie\", 20)"
```

```bash
python -m querybook fql "Commons.bySubject(\"Marie Curie\")"
```

```bash
python -m querybook ask history "Marie Curie"
```

`Facts` (the bulk datasets) and `Commons` (the shared facts) are read-only.
Sets over them must be cut with `.take(n)` before sorting or counting, because a
full pass reads about a billion rows.

## Video rendering

Install ffmpeg to render MP4s (`winget install ffmpeg` on Windows,
`brew install ffmpeg` on Mac). Storyboards and captions work without it.

## Tests

```bash
python -m unittest discover -s tests -t .
```

```bash
cd rust/querybook-core && cargo test --release
```

The tests build a miniature `D:\QB` with the suite's own schema and check that
no suite file is ever modified. They also check that the Python and Rust
fingerprints match vectors produced by the suite's own code, and enforce the
Rust-compatibility rules in `tests/test_rust_compat.py`.
