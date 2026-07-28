# elo-system

An Elo rating system for fantasy sports leagues. It scrapes weekly scoreboards
from a fantasy platform, converts them into per-week Elo ratings, and supports
multi-season **dynasty** ratings with an offseason regression-to-mean
adjustment.

- **Platforms:** Fantrax (NBA, head-to-head categories) and Sleeper (NFL,
  head-to-head points). Sleeper needs its optional extra: `pip install -e
  .[sleeper]`.
- **Scoring:** football is rated against the league median by default
  (`scoring: median`), so a team's week stands or falls on its own score
  rather than on who it was scheduled against; `scoring: default` rates each
  matchup head to head on the two teams' share of the points instead.
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

## Configuration

`resources/configs/` holds one shared config for each backend and one *ratings*
config per league:

```
resources/configs/
  sys_config.yml           reader/writer, and the ratings config of each league
  csv_config.yml           shared: where CSV frames are written
  sql_config.yml           shared: the Postgres connection
  ratings_macho_mandarins.yml  one league
  ratings_die_nasty.yml      another
```

`sys_config.yml` names the leagues, and one `EloSystem` drives one of them:

```yaml
ratings_configs:
  macho_mandarins: ratings_macho_mandarins.yml
  die_nasty: ratings_die_nasty.yml
default_league: macho_mandarins
```

```python
EloSystem('resources/configs/sys_config.yml')                # default_league
EloSystem('resources/configs/sys_config.yml', 'die_nasty') # a named league
```

Each league's CSV frames go in their own subdirectory of the CSV config's
`write_loc`, named for the league key, since the frames are named by season
alone and would otherwise collide:

```
resources/ratings/
  macho_mandarins/2024_season_elo.csv  ...  dynasty_elo.csv
  die_nasty/2022_season_elo.csv  ...  dynasty_elo.csv
```

Override one league's subdirectory with `ratings_dir` in its ratings config.

## Tests

```bash
python -m pytest          # run from the repo root
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for development notes and conventions,
and [CHANGELOG.md](CHANGELOG.md) for release history.
