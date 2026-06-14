# elo-system

An Elo rating system for fantasy sports leagues. It scrapes weekly scoreboards
from a fantasy platform, converts them into per-week Elo ratings, and supports
multi-season **dynasty** ratings with an offseason regression-to-mean
adjustment.

- **Platforms:** Fantrax (NBA, head-to-head categories) is implemented. A
  Sleeper backend is planned.
- **Outputs:** per-season and combined-dynasty rating frames, written to CSV
  (a Postgres backend is scaffolded but not yet wired up).

## Installation

The project depends on a fork of `fantraxapi` (the PyPI release is broken for
H2H-rotisserie leagues), so it installs from source rather than from PyPI:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .            # add [dev] for the test/lint tooling
```

`requirements.frozen` holds the exact, reproducible dependency pins (including
the fantraxapi fork commit) used during development.

## Layout

```
elo_system/
  elo_system.py            EloSystem orchestrator (config + reader/writer wiring)
  tools/
    elo_league.py          EloLeague: season management + run/dynasty pipeline
    elo_data.py            EloCSV / EloSQL persistence backends
    basics/                LeagueBase/DataBase, Elo math, config IO, constants
    helpers/               scraper, league, formatter, calculator, frame_manager
```

## Tests

```bash
python -m pytest          # run from the repo root
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for development notes and conventions,
and [CHANGELOG.md](CHANGELOG.md) for release history.
