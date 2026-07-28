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
  tests, or `tests/mocks/sleeper.py` and its `patch_sleeper_api` helper)
  rather than hitting a live API.
- Update `CHANGELOG.md` (the `Unreleased` section) for any user-facing change.

## Architecture pointers

- **Adding a platform**: subclass `LeagueScraper` and implement its six
  abstract methods (`login`, `get_members`, `get_league_name`,
  `get_scoreboard`, `get_playoff_start`, `get_current_season_length`), add a
  corresponding `League` subclass that wires it up via `_generate_scraper`, a
  formatter reachable from `set_formatter`, and an entry in
  `elo_league.LEAGUE_CLASSES`. `get_members` must return the canonical member
  map keyed by a *stable* owner id -- one that survives from season to season,
  since that key is what lets a dynasty span league ids. It is also the
  `platform_user_id` the SQL side files the member under, so it must identify an
  account on the platform rather than a team; the account's own name goes in
  `display_name`, separately from the team names in `curr_name`/`curr_short`.
  `FantraxScraper`/`FantraxLeague`/`fantrax_formatter` and their Sleeper
  counterparts are the two worked examples. A formatter's job is to emit a
  frame indexed by member id carrying whatever the league type's calculator
  reads: `true_score` + `opponent` for the head-to-head calculations,
  `scores` for the median one.
- **Optional platform dependencies** should be imported lazily inside the
  scraper, not at module scope, so the extra stays optional -- see
  `SleeperScraper._api`.
- **Adding a persistence backend** (e.g. SQL): subclass `DataBase` and
  implement the `_publish_*` hooks plus `load_frames`, mirroring `EloCSV`.

## The fantraxapi fork

The PyPI release of `fantraxapi` is broken for H2H-rotisserie (category)
leagues. This project depends on a fork
(`riders994/FantraxAPI`) that fixes matchup parsing, playoff handling, and
cross-season team identity. The exact commit is pinned in
`requirements.frozen`.
