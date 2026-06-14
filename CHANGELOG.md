# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/riders994/eloSystem/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/riders994/eloSystem/releases/tag/v1.0.0
