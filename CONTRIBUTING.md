# Contributing

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

For an exact, reproducible environment (matching CI/dev, including the pinned
`fantraxapi` fork commit), use the lock file instead:

```bash
pip install -r requirements.frozen
```

## Running tests and lint

Run both from the repository root:

```bash
python -m pytest        # full suite (no network access; the Fantrax/Sleeper
                        # layers are mocked)
python -m pyflakes elo_system tests
```

Keep the suite green and pyflakes clean before opening a PR. New behavior
should come with tests; the Elo math and calculators are pure functions and
easy to cover with hand-computed expectations.

## Conventions

- **Imports are relative within the `elo_system` package** (e.g.
  `from ..basics import LeagueBase`). Run and test from the repo root so
  `elo_system` resolves as a package; avoid absolute `from basics import ...`
  style (it breaks `pytest` and packaging). If your IDE marks a subdirectory as
  a "sources root", it may rewrite these on save — turn that off.
- **No network in tests.** Patch the scraper/league layer (see
  `tests/mocks/fantrax.py` and the monkeypatched `ft.League` in the scraper
  tests) rather than hitting a live API.
- Update `CHANGELOG.md` (the `Unreleased` section) for any user-facing change.

## Architecture pointers

- **Adding a platform** (e.g. Sleeper): subclass `LeagueScraper` and implement
  its five abstract methods (`login`, `get_members`, `get_scoreboard`,
  `get_playoff_start`, `get_current_season_length`), and add a corresponding
  `League` subclass that wires it up via `_generate_scraper`. `get_members`
  must return the canonical member map keyed by stable owner id.
- **Adding a persistence backend** (e.g. SQL): subclass `DataBase` and
  implement the `_publish_*` hooks plus `load_frames`, mirroring `EloCSV`.

## The fantraxapi fork

The PyPI release of `fantraxapi` is broken for H2H-rotisserie (category)
leagues. This project depends on a fork
(`riders994/FantraxAPI`) that fixes matchup parsing, playoff handling, and
cross-season team identity. The exact commit is pinned in
`requirements.frozen`.
