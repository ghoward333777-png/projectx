# QueryBook

Four separate apps (**Language**, **STEM**, **History** and **Video Studio**)
on **one shared FQL database**, fed by **continuous and real-time harvesting**.
Each app has its own interface, designed around the kind of answer its domain
needs: a dictionary entry, a worked solution, a timeline, or a storyboard and
rendered video.

Runs on Windows and macOS with only the Python standard library (3.10+). The
core is structured for a module-by-module Rust port; the first modules are
already ported (`rust/querybook-core`). Full design: [docs/DESIGN.md](docs/DESIGN.md).

## Start

Windows: double-click `run_windows.bat`, or run:

```bash
py -3 -m querybook serve --open
```

macOS: double-click `run_mac.command`, or run:

```bash
python3 -m querybook serve --open
```

The hub opens at http://127.0.0.1:8090/. The first run loads a small sample
library. To add material, drop `.txt`, `.md`, `.json`, `.jsonl` or `.csv` files
into the inbox (`python3 -m querybook info` prints where it is). Use
`inbox/history/`, `inbox/stem/` and so on to choose the domain, or leave files
at the top level to auto-classify them. Open pages update live.

## Run an app on its own

Each app can run in its own process on its own port, sharing the same database:

```bash
python3 -m querybook app language      # :8091
```

```bash
python3 -m querybook app history --no-harvest    # :8093
```

```bash
python3 -m querybook harvest           # ingestion only, in its own process
```

## Command line

```bash
python3 -m querybook ask stem "F = m * a where m = 70, a = 9.81"
```

```bash
python3 -m querybook fql 'History.where(.start_year < 0) { title, start_year }'
```

```bash
python3 -m querybook fql --write 'Source.create({ kind: "feed", url: "https://example.org/rss", domain: "history", interval: 600 })'
```

```bash
python3 -m querybook ingest ~/Documents/notes --domain language
```

## Video rendering

Storyboards and captions work as is. To render MP4s, install ffmpeg
(`winget install ffmpeg` on Windows, `brew install ffmpeg` on macOS).

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

```bash
cd rust/querybook-core && cargo test --release && cargo build --release
```

With the Rust binary built, the Python suite also checks Rust/Python parity.
`QUERYBOOK_TEST_RENDER=1` adds an end-to-end MP4 render test.
