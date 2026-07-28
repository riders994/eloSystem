# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.0.0] - 2026-07-27

Sleeper football, and the rating maths that supporting it turned up.

`SleeperScraper`/`SleeperLeague`/`sleeper_formatter` bring Sleeper NFL leagues
to parity with Fantrax, verified end to end against a live five-season dynasty:
scraped over CSV, converted to a dynasty, published to Postgres and read back.

Wiring up the first NFL league exercised `nfl_calculator` and `median_elo_calc`
for the first time, and they did not hold up. The median calculation was not
conservative -- it moved the whole league's rating by the skew of each week's
scores -- and the offseason adjustment froze anyone who left, so a departed
manager could outrank the live league on a years-old result. Both are fixed,
and the league average now holds at 1500 at every week of every season and
across every dynasty boundary.

The major bump is for the config layout: the CSV and SQL configs are now
shared by every league, and per-league `elo_config.yml` becomes
`ratings_<league>.yml`, named in `sys_config.yml` under `ratings_configs`.

**Migrating from 1.1.0**

- Rename `elo_config.yml` to a `ratings_<league>.yml` and list it under
  `ratings_configs` in `sys_config.yml`, with a `default_league`. Drop
  `elo_league_config_name`.
- Move existing CSV frames into a subdirectory of `write_loc` named for the
  league key.
- `EloSystem.elo_league_config` / `.elo_league_config_loc` are now
  `.ratings_config` / `.ratings_config_loc`.
- NFL ratings computed by an earlier version are wrong and should be
  recomputed; NBA ratings are unaffected.

### Added
- **Sleeper backend.** `SleeperScraper` / `SleeperLeague` / `sleeper_formatter`
  bring Sleeper NFL leagues to parity with Fantrax: scraping, seasonal elos,
  dynasty and both the CSV and SQL publish paths. Sleeper's read API needs no
  auth, and the `sleeper` client is imported lazily, so the extra stays
  optional. Members are keyed by Sleeper's `user_id` (an account id, stable
  across seasons, which is what lets a dynasty span league ids) with the
  per-season `roster_id` as the team id. Standings, which Sleeper does not
  report, are derived from the rosters by wins, then ties, then points for.
- `scoring` config key on `EloLeague`, plumbed through to the calculator. It
  defaults per league type: `median` for `nfl`, `default` for `nba`.
- `nfl_calculator` grew a real head-to-head mode (`scoring='default'`)
  alongside the median one, sharing the pairwise loop with `nba_calculator`.

### Fixed
- **The median calculation did not conserve rating.** Elo is a closed system --
  the league total is meant to be the same every week -- and the head-to-head
  path gets that for free by moving rating between two named opponents. The
  median path did not: a move's size is driven by the distance from the
  *median*, and those distances sum to `n * (mean - median)`, not to zero. So
  every week's rating drifted by the skew of that week's scores (correlation
  +0.99 against the drift observed on a real season), a blowout inflating the
  league and a disaster deflating it. Gains and losses are now scaled to their
  common average by `balance_deltas`, which conserves the total exactly while
  leaving every sign intact -- a team that beat the median still gains. The
  league mean now holds at 1500 to floating-point precision at every week.
  Note this changes previously computed NFL ratings.
- **Departed managers froze their dynasty rating instead of regressing.** The
  offseason adjustment was applied only to the coming season's members, so a
  manager who left kept whatever they last scored, for good. They never decayed
  toward the mean while the active league did, which let someone years gone
  outrank the live table, and it put the league average permanently off 1500 --
  a frozen row off the mean cannot be pulled back. The adjustment now regresses
  every row on file. With this and the median fix in place, the league average
  holds at 1500 at every week of every season and across every dynasty
  boundary. Note this changes previously computed dynasty ratings.
- A league can now be **initialised** as a dynasty (`is_dynasty: true` in its
  config) rather than only converted into one. The run pipeline sets each
  season's dynasty start week as it reaches it, where previously only
  `change_dynasty` did, so an initialised dynasty raised `KeyError` on
  `dynasty_start_week` the moment it rated a second season. Both routes now
  produce identical ratings.
- `change_dynasty(True)` no longer crashes on a league with nothing to
  convert. Converting migrates ratings that already exist, so it now requires
  a league with data and returns False otherwise -- a league with no ratings
  should be initialised as a dynasty instead. A partially rated league still
  converts, filling in the seasons it is missing.
- `FrameManager.validate_season` raised `KeyError` for a season with no frame
  instead of reporting it as unrated, which is the question callers are
  actually asking.
- `EloSQL` connected, and pulled every dim table, from its constructor. Since
  `EloSystem.load_configs` builds every configured backend up front, an
  unreachable database took the CSV workflow down with it. The connection now
  opens on first use and each dim is pulled the first time it is read, so
  constructing the backend is offline and only actually touching SQL fails.
- `EloCSV` let the parser type the frame index, so all-digit member ids
  (Sleeper user ids) came back as int64 and stopped matching the string keys
  in `league_members` and in `dim_manager`. Publishing CSV-loaded Sleeper
  frames to SQL failed outright. The index is now always read back as strings.
- `EloLeague.publish` shipped `self.config` without dumping first, so state
  set since the last load -- `is_dynasty` above all -- reached neither the
  payload nor the config file. A league converted to a dynasty and published
  was persisted still calling itself redraft, and came back redraft on the
  next load.
- `nfl_calculator`'s parameter order did not match the positional call in
  `EloLeague._run_one`, so `week` was being read as `scoring`. NFL leagues
  could not be rated at all. Its signature now mirrors `nba_calculator`'s, and
  `week=None` resolves against the elo frame rather than the score frame.
- The median calculation combined a positional array with an index-keyed
  Series, silently misaligning ratings whenever the scoreboard's row order
  differed from the elo frame's. It now aligns by member, ignores scoreboard
  entries with no rating, and carries forward members absent from a week.
- `median_elo_calc` divided by zero when every team posted the same score (or
  when a single team was rated), returning NaN for the whole league.

### Changed
- **One config per backend, one ratings config per league.** The CSV and SQL
  configs are now shared by every league, and what was `elo_config.yml` is a
  per-league `ratings_<league>.yml`. `sys_config.yml` names them under
  `ratings_configs` and picks one with `default_league`; an `EloSystem` drives
  the league it is constructed with (`EloSystem(path, 'die_nasty')`).
  Configuring several leagues without a default, or naming an unknown one, is
  an error rather than a guess. Previously a second league meant duplicating
  the whole config set.
- **Each league's CSV frames get their own directory**, under the CSV config's
  `write_loc` and named for the league key -- the frames are named by season
  alone, so two leagues sharing a directory overwrote each other. Override one
  league's with `ratings_dir` in its ratings config.
- **Dynasty facts are identified by manager, not by team.** A dynasty rating
  spans seasons, and a manager who has left still holds one -- it goes on
  regressing, and the league average depends on it -- but owns no team in a
  season they were not in. Those rows previously could not be stored at all:
  the write joined every row to a team for that season, so a departed
  manager's later weeks were silently dropped (56 of 786 on a real five-season
  dynasty). `fact_dynasty_elos` rows now carry a NULL `team_id` for seasons the
  manager did not play, with `manager_id` identifying them, and are read back
  by `manager_id`. Seasonal elos and rotos are unchanged: they live inside one
  season, so a team both identifies them and must exist.
- `LOAD_ELO` / `LOAD_ROTO` take a `member_col` placeholder, supplied from the
  fact spec's new `member_key`, rather than hardcoding `team_id`.
- `EloLeague.add_league` dispatches on the configured platform through
  `LEAGUE_CLASSES` instead of hardcoding `FantraxLeague`, and season
  validation is no longer Fantrax-specific.

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

[Unreleased]: https://github.com/riders994/eloSystem/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/riders994/eloSystem/compare/v1.1.0...v2.0.0
[1.1.0]: https://github.com/riders994/eloSystem/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/riders994/eloSystem/releases/tag/v1.0.0
