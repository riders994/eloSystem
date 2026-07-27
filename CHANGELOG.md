# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0] - 2026-07-27

The Postgres backend, landing as the additive minor release 1.0.0 anticipated.
`EloSQL` is now a working twin of `EloCSV` — same payload in, same frame shapes
out — so either can serve as `EloSystem`'s reader or writer. Verified end to
end against a live league: two Fantrax seasons scraped as redraft over CSV,
converted to dynasty, then republished through SQL and read back bit-exactly.

### Added
- `EloSQL` connected to the pipeline: publishes the FrameManager payload into
  the `dim_*`/`fact_*` star schema and reads it back in the shape `EloCSV`
  returns. Dynasty elos hang off the league, seasonal elos and rotos off the
  online league (one per season).
- Dimension sync: `EloSystem.sync_dims(years, scrape)` registers a season's
  managers and teams on their own, before any elos exist for them; `publish()`
  runs the same path first so the fact-table foreign keys always resolve.
  Rows already on file have their scraped columns refreshed rather than skipped.
- `EloSQL.set_champion()` / `set_comanager()`, with `resolve_team_id()` and
  `resolve_manager_id()`, for the `dim_team` columns the sync deliberately does
  not own (a standing of 1 mid-season is not a champion, and co-manager links
  come from Discord).
- Optional anonymization, via `anonymizer` in the SQL config: names are
  tokenised at the storage boundary, so the dim tables held in memory keep real
  values and only the DB sees tokens. Reversal maps default to `resources/anon`
  (`anon_loc`); coverage is `anon_columns`, defaulting to the manager identity.
- Team standings: `LeagueScraper.get_members` reports `standing`, `League`
  stores it in `league_members`, and the sync carries it to
  `dim_team.place_finish`.
- The platform's own league name reaches `dim_league.league_name`, via a new
  `LeagueScraper.get_league_name`.
- `replace_dataframe` for the fact tables, which carry no unique constraint and
  so cannot be reached by `upsert_dataframe`'s `ON CONFLICT`.
- `EloSystem.set_reader()` / `set_writer()` to select a backend by name.
- `rv_pytools>=1.2.1` declared as a dependency; it was imported but never
  listed, and 1.2.0 is where `anonymize`/`deanonymize` arrived.

### Changed
- **Breaking:** `LeagueScraper` gains an abstract `get_league_name`; platform
  backends must implement it.
- **Breaking:** `RATING_DB_COLS` and `ROTO_DB_COLS` now match the real fact
  tables (no `league_year`, no `is_dynasty`), `DYNASTY_DB_COLS` is new, and
  `ELO_DB_COLS` is gone.
- **Breaking:** `LOAD_ELO` / `LOAD_ROTO` take `schema`, `table`, `scope_col`
  and `scope_id`; one template now serves every elo fact table.
- `EloCSV` reads with `float_precision='round_trip'`. The default parser is up
  to an ulp out, which made a frame read from CSV differ from the same frame
  read from Postgres, where `float8` is exact.
- `FrameManager.member_dict` is a property, read live off the config.
- Dimension pushes go parents first (`ELO_DIM_ORDER`); `ELO_DIMS` is a set and
  its iteration order does not respect the foreign keys.

### Fixed
- `EloCSV` matched `'roto'` where `DataBase.publish` emits `'roto_history'`, so
  roto publishes raised `Unknown destination` and loads used the wrong key.
- `EloSystem._assign_rw` was never called, leaving `reader`/`writer` `None` and
  `publish()` raising `AttributeError`.
- `toggle_reader`/`toggle_writer` used two `if`s rather than `if`/`elif`, so a
  CSV→SQL toggle immediately toggled back, and the SQL→CSV branch assigned
  `elo_league` instead of `elo_csv`.
- `write_configs`/`dump` wrote the reader and writer *objects* into the sys
  config, under keys `__init__` does not read back.
- `FrameManager.member_dict` was snapshotted at construction, leaving every
  season scraped after the first without members.
- `EloLeague.load_frames` assumed a frame manager existed, so restoring ratings
  from a backend failed unless a season had been run first.
- `League._update_member` appended the current team name to the history on
  every scrape, growing it by a duplicate each time.
- `_gen_elo` seeded week 0 with Python ints, so a CSV round trip returned an
  `int64` column where the SQL backend returns float.
- Row building casts through `object` first: psycopg2 cannot adapt
  `numpy.int64` (`numpy.float64` slips through as a `float` subclass).

## [1.0.0] - 2026-06-14

First packaged release. The public API (the `EloSystem` / `EloLeague` /
`DataBase` surface) is considered stable from here; planned work such as the
SQL backend is additive and will land as minor releases.

### Added
- Packaging via `pyproject.toml` (setuptools build backend), `LICENSE` (MIT),
  this changelog, and `CONTRIBUTING.md`.
- Fantrax NBA scraping (`FantraxScraper`) on top of a forked `fantraxapi`,
  with stable cross-season team identity keyed on owner id.
- Elo pipeline: scrape → format → calculate → manage frames → publish, with
  head-to-head (score/binary/trinary) and roto/median scoring variants.
- Multi-season **dynasty** ratings with an offseason regression-to-mean
  adjustment.
- `EloCSV` persistence backend: writes per-season, roto, and dynasty rating
  frames to CSV and reads them back (`load_frames`).
- `EloSystem` orchestrator with on-disk config loading, bootstrap directory
  creation, and reader/writer selection.
- Test suite (pytest) covering the Elo math, calculators, formatter, scraper,
  league, frame manager, persistence round-trips, and orchestration.

### Notes
- `LeagueScraper` is an abstract base defining the platform interface; a
  Sleeper backend (`sleeper` optional dependency) is planned but not yet wired
  in.
- The Postgres backend (`EloSQL`, `upsert_dataframe`) is scaffolded but not
  yet connected to the pipeline.

[Unreleased]: https://github.com/riders994/eloSystem/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/riders994/eloSystem/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/riders994/eloSystem/releases/tag/v1.0.0
