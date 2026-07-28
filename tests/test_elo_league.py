"""Tests for elo_system.elo_system.EloLeague and EloSystem.

The scraper / league layer is fully monkeypatched (FantraxLeague is replaced
with a local fake); no network access ever happens. The fake scoreboard
objects below expose only the attributes fantrax_formatter touches
(matchups -> .home/.away.owners and .home_categories/.away_categories).
"""

import pandas as pd
import pytest

import elo_system.tools.elo_league as ell_mod
from elo_system.elo_system import EloLeague, EloSystem
from elo_system.tools.helpers.calculator import nba_calculator, nfl_calculator
from elo_system.tools.helpers.formatter import fantrax_formatter, sleeper_formatter
from elo_system.tools.helpers.frame_manager import FrameManager
from elo_system.tools.helpers import set_calculator, set_formatter

MEMBERS = ['alice', 'bob', 'cara', 'dan']
K = 60


# ---------------------------------------------------------------------------
# fakes (defined locally on purpose; tests/mocks belongs to another suite)
# ---------------------------------------------------------------------------

class FakeTeamSide:
    def __init__(self, owners):
        self.owners = owners


class FakeMatchup:
    def __init__(self, home_owner, away_owner, home_score, away_score):
        self.home = FakeTeamSide(home_owner)
        self.away = FakeTeamSide(away_owner)
        # fantrax_formatter divides 'Pts' by 9 to get true_score, and the
        # 'opponent' column carries the opposing *team id* (mapped back to a
        # member id by EloLeague._rename).
        self.home_categories = {'Pts': home_score * 9, 'opponent': f't_{away_owner}'}
        self.away_categories = {'Pts': away_score * 9, 'opponent': f't_{home_owner}'}


class FakeScoreboard:
    def __init__(self, *matchups):
        self.matchups = {i: m for i, m in enumerate(matchups)}


def build_scoreboards():
    return {
        2024: {
            1: FakeScoreboard(FakeMatchup('alice', 'bob', 1, 0),
                              FakeMatchup('cara', 'dan', 0, 1)),
            2: FakeScoreboard(FakeMatchup('alice', 'bob', 1, 0),
                              FakeMatchup('cara', 'dan', 1, 0)),
        },
        2025: {
            # cara and dan are idle in 2025: their elo should carry over.
            1: FakeScoreboard(FakeMatchup('alice', 'bob', 1, 0)),
            2: FakeScoreboard(FakeMatchup('alice', 'bob', 0, 1)),
            3: FakeScoreboard(FakeMatchup('alice', 'bob', 0.5, 0.5)),
        },
    }


def make_fake_league_cls(scoreboards):
    class FakeFantraxLeague:
        created = []

        def __init__(self, year, seasons):
            self.year = year
            self.seasons = seasons
            self.load_calls = 0
            type(self).created.append(self)

        def scrape(self):
            return dict(self.seasons[self.year])

        def load(self):
            self.load_calls += 1

        def get_week(self, week):
            return scoreboards[self.year][week]

    return FakeFantraxLeague


# ---------------------------------------------------------------------------
# config fixtures
# ---------------------------------------------------------------------------

def member_entry(mid):
    return {
        'curr_name': mid.title(),
        'names': [mid.title()],
        'short_name': mid[:3].upper(),
        'team_id': f't_{mid}',
        'is_commish': mid == 'alice',
    }


def season_entry(league_id, length):
    return {
        'league_id': league_id,
        'current_season_length': length,
        'season_length': length,
        'playoff_start': length,
        'league_members': {m: member_entry(m) for m in MEMBERS},
    }


def make_league_config():
    return {
        'league_type': 'nba',
        'platform': 'fantrax',
        'current_sports_year': 2025,
        'current_season': 2025,
        'is_dynasty': False,
        'is_roto': False,
        'osa_factor': 0.4,
        'k': K,
        'seasons': {
            2024: season_entry('lg2024', 2),
            2025: season_entry('lg2025', 3),
        },
    }


@pytest.fixture
def league(monkeypatch):
    scoreboards = build_scoreboards()
    monkeypatch.setattr(ell_mod, 'FantraxLeague', make_fake_league_cls(scoreboards))
    el = EloLeague(make_league_config())
    el.load()
    return el


# hand-rolled elo math, independent of the source implementation -------------

def expected_share(ra, rb):
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))

def elo_step(ra, rb, sa, sb, k=K):
    ea = expected_share(ra, rb)
    return ra + k * (sa - ea), rb + k * (sb - (1 - ea))


# ---------------------------------------------------------------------------
# construction / load / dump
# ---------------------------------------------------------------------------

def test_load_populates_fields(league):
    assert league.league_type == 'nba'
    assert league.platform == 'fantrax'
    assert league.current_season == 2025
    assert league.current_sports_year == 2025
    assert league.is_dynasty is False
    assert league.is_roto is False
    assert league.k == K
    assert league.extras == 0
    assert set(league.seasons) == {2024, 2025}


def test_dump_writes_state_back_to_config(league):
    league.current_season = 2024
    league.is_dynasty = True
    cfg = league.dump()
    assert cfg['current_season'] == 2024
    assert cfg['is_dynasty'] is True
    assert cfg['seasons'] is league.seasons or cfg['seasons'] == league.seasons
    assert cfg['k'] == K


# ---------------------------------------------------------------------------
# add_season / remove_season
# ---------------------------------------------------------------------------

def test_add_season_valid(league):
    new = season_entry('lg2026', 4)
    assert league.add_season(new, 2026) is True
    assert league.seasons[2026] is new
    assert 2026 not in league.leagues  # league=False by default


def test_add_season_invalid_without_league_id(league):
    bad = {'current_season_length': 4}
    assert league.add_season(bad, 2026) is False
    assert 2026 not in league.seasons


def test_add_season_with_league_instantiates_fake(league):
    new = season_entry('lg2026', 4)
    assert league.add_season(new, 2026, league=True) is True
    assert league.leagues[2026].year == 2026


def test_remove_season_by_year(league):
    league.add_league(2024)
    removed = league.remove_season(2024)
    assert removed['league_id'] == 'lg2024'
    assert 2024 not in league.seasons
    assert 2024 not in league.leagues


def test_remove_season_by_league_id(league):
    league.add_league(2024)
    removed = league.remove_season(league_id='lg2024')
    assert removed['league_id'] == 'lg2024'
    assert 2024 not in league.seasons


def test_remove_season_requires_year_or_id(league):
    with pytest.raises(ValueError):
        league.remove_season()


def test_remove_season_unknown_league_id(league):
    with pytest.raises(ValueError):
        league.remove_season(league_id='does-not-exist')


def test_remove_season_unknown_year(league):
    with pytest.raises(KeyError):
        league.remove_season(1999)


def test_remove_season_without_instantiated_league(league):
    removed = league.remove_season(2024)
    assert removed['league_id'] == 'lg2024'


# ---------------------------------------------------------------------------
# set_current_season
# ---------------------------------------------------------------------------

def test_set_current_season_explicit(league):
    out = league.set_current_season(2024)
    assert out == 2024
    assert league.current_season == 2024
    assert league.current_league is league.leagues[2024]
    assert league.current_league.load_calls >= 1


def test_set_current_season_none_resets_to_latest(league):
    league.add_league(2024)
    league.add_league(2025)
    league.set_current_season(2024)
    out = league.set_current_season()
    assert out == 2025
    assert league.current_league is league.leagues[2025]


def test_set_current_season_switches_to_unadded_year(league):
    league.set_current_season(2024)
    assert league.set_current_season(2025) == 2025


# ---------------------------------------------------------------------------
# component selection
# ---------------------------------------------------------------------------

def test_set_calculator_nba():
    assert set_calculator('nba') is nba_calculator


def test_set_calculator_nfl():
    assert set_calculator('nfl') is nfl_calculator


def test_set_calculator_unknown_raises():
    with pytest.raises(ValueError, match='mlb'):
        set_calculator('mlb')


def test_set_formatter_fantrax():
    assert set_formatter('fantrax') is fantrax_formatter


def test_set_formatter_sleeper():
    assert set_formatter('sleeper') is sleeper_formatter


def test_set_formatter_unknown_raises():
    # An unsupported platform raises rather than silently returning None.
    with pytest.raises(ValueError):
        set_formatter('espn')


def test_set_frame_manager_idempotent(league):
    league._set_frame_manager()
    fm = league.frame_manager
    assert isinstance(fm, FrameManager)
    league._set_frame_manager()
    assert league.frame_manager is fm


# ---------------------------------------------------------------------------
# dynasty start-week math
# ---------------------------------------------------------------------------

def test_set_dynasty_start_week_two_seasons(league):
    league._set_dynasty_start_week()
    # First season starts at 0; second starts after length(2024)=2 plus one
    # offseason-adjustment column.
    assert league.seasons[2024]['dynasty_start_week'] == 0
    assert league.seasons[2025]['dynasty_start_week'] == 3


def test_set_dynasty_start_week_three_seasons():
    cfg = make_league_config()
    cfg['seasons'] = {
        2023: season_entry('lg2023', 2),
        2024: season_entry('lg2024', 3),
        2025: season_entry('lg2025', 4),
    }
    el = EloLeague(cfg)
    el.load()
    el._set_dynasty_start_week()
    assert el.seasons[2023]['dynasty_start_week'] == 0
    assert el.seasons[2024]['dynasty_start_week'] == 2 + 1
    assert el.seasons[2025]['dynasty_start_week'] == 2 + 1 + 3 + 1


def test_set_dynasty_start_week_single_year(league):
    league._set_dynasty_start_week(2025)
    assert league.seasons[2025]['dynasty_start_week'] == 3
    assert 'dynasty_start_week' not in league.seasons[2024]


# ---------------------------------------------------------------------------
# _rename
# ---------------------------------------------------------------------------

def test_rename_maps_team_ids_to_member_ids(league):
    sb = pd.DataFrame({'opponent': ['t_bob', 't_alice']}, index=['alice', 'bob'])
    renamed = league._rename(sb, 2025)
    assert list(renamed) == ['bob', 'alice']
    assert list(renamed.index) == ['alice', 'bob']


# ---------------------------------------------------------------------------
# run_prep / _run_one / _run_multiple / run / run_season
# ---------------------------------------------------------------------------

def test_run_prep_wires_components(league):
    league.run_prep(2025)
    assert league.current_season == 2025
    assert 2025 in league.leagues
    assert league.formatter is fantrax_formatter
    assert league.calculator is nba_calculator
    assert isinstance(league.frame_manager, FrameManager)


def test_run_prep_defaults_to_current_sports_year(league):
    league.run_prep()
    assert league.current_season == 2025


def test_run_one_week_zero_generates_frame(league):
    league.run_prep(2025)
    frame = league._run_one(0, 2025)
    assert isinstance(frame, pd.DataFrame)
    assert frame is league.frame_manager.seasonal_elo[2025]
    assert (frame['week_0'] == 1500).all()
    assert list(frame.index) == MEMBERS


def test_run_one_scored_week(league):
    league.run_prep(2025)
    league._run_one(0, 2025)
    frame = league._run_one(1, 2025)
    # alice beat bob from even 1500s: 1500 + 60*(1 - 0.5) = 1530 / 1470.
    assert frame.loc['alice', 'week_1'] == pytest.approx(1530.0)
    assert frame.loc['bob', 'week_1'] == pytest.approx(1470.0)
    # idle members carry over
    assert frame.loc['cara', 'week_1'] == pytest.approx(1500.0)
    assert frame.loc['dan', 'week_1'] == pytest.approx(1500.0)


def test_run_multiple_range(league):
    league.run_prep(2025)
    frame = league._run_multiple('0:2', 2025)
    assert {'week_0', 'week_1', 'week_2'} <= set(frame.columns)


def test_run_with_string_and_int(league):
    league.run_prep(2025)
    frame = league.run('0:2', 2025)
    assert 'week_2' in frame.columns
    frame = league.run(3, 2025)
    assert 'week_3' in frame.columns


def test_run_season_hand_computed_elos(league):
    league.run_season(2025)
    frame = league.frame_manager.seasonal_elo[2025]
    assert list(frame.columns) == ['week_0', 'week_1', 'week_2', 'week_3']

    # Week 1: alice wins.
    a1, b1 = elo_step(1500.0, 1500.0, 1, 0)
    assert frame.loc['alice', 'week_1'] == pytest.approx(a1)  # 1530
    assert frame.loc['bob', 'week_1'] == pytest.approx(b1)    # 1470
    # Week 2: bob wins.
    a2, b2 = elo_step(a1, b1, 0, 1)
    assert frame.loc['alice', 'week_2'] == pytest.approx(a2)
    assert frame.loc['bob', 'week_2'] == pytest.approx(b2)
    # Week 3: draw.
    a3, b3 = elo_step(a2, b2, 0.5, 0.5)
    assert frame.loc['alice', 'week_3'] == pytest.approx(a3)
    assert frame.loc['bob', 'week_3'] == pytest.approx(b3)
    # Idle members stay flat at 1500 all season.
    for w in range(4):
        assert frame.loc['cara', f'week_{w}'] == pytest.approx(1500.0)
        assert frame.loc['dan', f'week_{w}'] == pytest.approx(1500.0)


def test_run_season_both_years(league):
    league.run_season(2024)
    league.run_season(2025)
    assert set(league.frame_manager.seasonal_elo) == {2024, 2025}
    assert 'week_2' in league.frame_manager.seasonal_elo[2024].columns
    assert 'week_3' in league.frame_manager.seasonal_elo[2025].columns


def test_run_one_dynasty_without_frame_raises(league):
    league.run_prep(2025)
    league._run_one(0, 2025)
    league.is_dynasty = True
    league.seasons[2025]['dynasty_start_week'] = 0
    with pytest.raises(KeyError, match='No Dynasty frame'):
        league._run_one(1, 2025)


# ---------------------------------------------------------------------------
# dynasty end-to-end (change_dynasty after both seasons are run)
# ---------------------------------------------------------------------------

def test_change_dynasty_full_flow(league):
    league.run_season(2024)
    league.run_season(2025)
    assert league.change_dynasty(True) is True
    assert league.is_dynasty is True

    # start weeks: 2024 -> 0, 2025 -> length(2024) + 1 = 3
    assert league.seasons[2024]['dynasty_start_week'] == 0
    assert league.seasons[2025]['dynasty_start_week'] == 3

    d = league.frame_manager.dynasty_elo
    # 2024 weeks 0-2, OSA column at week_3, 2025 weeks at 4-6.
    assert list(d.columns) == [f'week_{i}' for i in range(7)]

    # 2024 final elos, hand-computed: alice beats bob twice.
    a1, b1 = elo_step(1500.0, 1500.0, 1, 0)
    a2, b2 = elo_step(a1, b1, 1, 0)
    # cara loses week 1 then wins week 2.
    c1, d1 = elo_step(1500.0, 1500.0, 0, 1)
    c2, d2 = elo_step(c1, d1, 1, 0)
    assert d.loc['alice', 'week_2'] == pytest.approx(a2)
    assert d.loc['bob', 'week_2'] == pytest.approx(b2)
    assert d.loc['cara', 'week_2'] == pytest.approx(c2)
    assert d.loc['dan', 'week_2'] == pytest.approx(d2)

    # week_3 = offseason adjustment of week_2: (elo - 1500) * 0.6 + 1500.
    for m, w2 in (('alice', a2), ('bob', b2), ('cara', c2), ('dan', d2)):
        assert d.loc[m, 'week_3'] == pytest.approx((w2 - 1500.0) * 0.6 + 1500.0)

    # week_4 continues from week_3 with the 2025 week-1 result (alice wins).
    a3 = (a2 - 1500.0) * 0.6 + 1500.0
    b3 = (b2 - 1500.0) * 0.6 + 1500.0
    a4, b4 = elo_step(a3, b3, 1, 0)
    assert d.loc['alice', 'week_4'] == pytest.approx(a4)
    assert d.loc['bob', 'week_4'] == pytest.approx(b4)

    # idle members carry their OSA value through the 2025 dynasty weeks.
    assert d.loc['cara', 'week_6'] == pytest.approx(d.loc['cara', 'week_3'])
    assert d.loc['dan', 'week_6'] == pytest.approx(d.loc['dan', 'week_3'])

    # Seasonal frames are untouched by the dynasty run.
    assert list(league.frame_manager.seasonal_elo[2025].columns) == [
        'week_0', 'week_1', 'week_2', 'week_3'
    ]


def test_change_dynasty_noop_when_already_in_state(league):
    assert league.change_dynasty(False) is False
    assert league.is_dynasty is False


# ---------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------

def test_publish_payload_shape(league):
    league.run_season(2025)
    payload = league.publish()
    assert 'seasonal_elo' in payload
    assert payload['seasonal_elo'] is league.frame_manager.seasonal_elo
    # publish() overrides the frame manager's sub-config with the league config
    assert payload['config'] is league.config


# ---------------------------------------------------------------------------
# compile_season_stats
# ---------------------------------------------------------------------------

def test_compile_season_stats(league):
    stats = league.compile_season_stats()
    assert stats['playoff_start'][2024] == 2
    assert stats['current_season_length'][2025] == 3


# ---------------------------------------------------------------------------
# EloSystem
# ---------------------------------------------------------------------------
#
# EloSystem is under active development; the reader/writer/publish surface is
# still churning, so these tests cover only the parts with a settled contract:
# the pure config validators and the path-loading constructor.

def test_validate_csv_config_requires_write_loc():
    assert EloSystem._validate_csv_config({'write_loc': 'out'}) is True
    assert EloSystem._validate_csv_config({}) is False


def test_validate_league_config_requires_core_keys():
    valid = {'platform': 'fantrax', 'league_type': 'nba',
             'current_sports_year': 2024}
    assert EloSystem._validate_league_config(valid) is True
    for missing in ('platform', 'league_type', 'current_sports_year'):
        partial = dict(valid)
        del partial[missing]
        assert EloSystem._validate_league_config(partial) is False


def test_validate_sql_config_requires_connection_details():
    # EloSQL cannot be built without either form of connection details.
    assert EloSystem._validate_sql_config({}) is False
    assert EloSystem._validate_sql_config({'conn_dict': {}}) is True
    assert EloSystem._validate_sql_config({'conn_uri': 'postgresql://x/y'}) is True


def test_constructor_loads_config_from_path(tmp_path):
    import yaml
    cfg = {'csv_config_name': 'my_csv.yml'}
    cfg_path = tmp_path / 'sys_config.yml'
    cfg_path.write_text(yaml.dump(cfg))

    es = EloSystem(str(cfg_path))
    assert isinstance(es, EloSystem)
    assert es.configs_dir == tmp_path
    # Explicit name from the config is used; the others fall back to defaults.
    assert es.csv_config_loc == 'my_csv.yml'
    assert es.sql_config_loc == 'sql_config.yml'
    assert es.ratings_config_loc == 'ratings_config.yml'


def test_constructor_with_path_does_not_create_dirs_and_errors_if_invalid(tmp_path):
    # A supplied-but-invalid path must raise, not silently bootstrap dirs.
    missing = tmp_path / 'nope' / 'sys_config.yml'
    with pytest.raises(FileNotFoundError):
        EloSystem(str(missing))
    assert not missing.parent.exists()


def test_constructor_none_bootstraps_directory_skeleton(tmp_path, monkeypatch):
    # With no config path, EloSystem creates resources/ and resources/configs/
    # relative to the CWD and starts from an empty config.
    monkeypatch.chdir(tmp_path)
    es = EloSystem()
    assert es.resources_dir == tmp_path / 'resources'
    assert es.configs_dir == tmp_path / 'resources' / 'configs'
    assert es.resources_dir.is_dir()
    assert es.configs_dir.is_dir()
    # No sys config on disk yet -> defaults apply.
    assert es.reader_key == 'csv'
    assert es.csv_config_loc == 'csv_config.yml'


# ---------------------------------------------------------------------------
# EloSystem.sync_dims
# ---------------------------------------------------------------------------

class RecordingEloSQL:
    """Stands in for EloSQL; records what the dim sync flow hands it."""

    def __init__(self):
        self.configs = []
        self.syncs = 0

    def set_league_config(self, league_config):
        self.configs.append(league_config)
        return 0

    def sync_dims(self):
        self.syncs += 1


def make_system_with_sql(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ell_mod, 'FantraxLeague', make_fake_league_cls(build_scoreboards()))

    es = EloSystem()
    es.elo_league_config = make_league_config()
    es.elo_league = EloLeague(es.elo_league_config)
    es.elo_sql = RecordingEloSQL()
    return es


def test_sync_dims_without_a_sql_writer_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    es = EloSystem()
    with pytest.raises(KeyError, match='No SQL writer available'):
        es.sync_dims()


def test_sync_dims_scrapes_every_season_then_syncs(tmp_path, monkeypatch):
    es = make_system_with_sql(tmp_path, monkeypatch)
    es.sync_dims()

    # Every configured season is re-scraped before the dims are written.
    assert sorted(l.year for l in ell_mod.FantraxLeague.created) == [2024, 2025]
    assert es.elo_sql.syncs == 1
    assert set(es.elo_sql.configs[0]['seasons']) == {2024, 2025}


def test_sync_dims_can_skip_the_scrape(tmp_path, monkeypatch):
    es = make_system_with_sql(tmp_path, monkeypatch)
    es.sync_dims(scrape=False)

    assert ell_mod.FantraxLeague.created == []
    assert es.elo_sql.syncs == 1


def test_sync_dims_scrapes_only_the_years_asked_for(tmp_path, monkeypatch):
    es = make_system_with_sql(tmp_path, monkeypatch)
    es.sync_dims(years=[2025])

    assert [l.year for l in ell_mod.FantraxLeague.created] == [2025]
    assert es.elo_sql.syncs == 1


def test_sync_dims_needs_no_elo_frames(tmp_path, monkeypatch):
    # The whole point of the standalone flow: register a season's members and
    # teams before any elos exist for it.
    es = make_system_with_sql(tmp_path, monkeypatch)
    es.sync_dims()

    assert es.elo_league.frame_manager is None
    assert es.elo_sql.syncs == 1


def test_load_frames_works_before_any_season_has_run(league):
    # Restoring ratings from a backend is a valid first move; only run_prep
    # otherwise builds the frame manager.
    assert league.frame_manager is None
    frame = pd.DataFrame({'week_0': [1500.0] * len(MEMBERS)}, index=MEMBERS)
    league.load_frames({'seasonal_elo': {2024: frame}})

    assert league.frame_manager is not None
    pd.testing.assert_frame_equal(league.frame_manager.seasonal_elo[2024], frame)


# ---------------------------------------------------------------------------
# Platform dispatch
# ---------------------------------------------------------------------------

def test_add_league_builds_the_class_for_the_platform(monkeypatch):
    # add_league used to hardcode FantraxLeague; it now dispatches on the
    # configured platform.
    built = []

    class FakeSleeperLeague:
        def __init__(self, year, seasons):
            self.year = year

        def scrape(self):
            built.append(self.year)

    monkeypatch.setattr(ell_mod, 'SleeperLeague', FakeSleeperLeague)
    league = ell_mod.EloLeague({
        'platform': 'sleeper',
        'league_type': 'nfl',
        'current_sports_year': 2025,
        'seasons': {2025: {'league_id': '1063131085976006656'}},
    })
    league.load()
    league.add_league(2025)

    assert built == [2025]
    assert isinstance(league.leagues[2025], FakeSleeperLeague)


def test_add_league_unknown_platform_raises():
    league = ell_mod.EloLeague({
        'platform': 'espn',
        'league_type': 'nfl',
        'current_sports_year': 2025,
        'seasons': {2025: {'league_id': 'x'}},
    })
    league.load()
    with pytest.raises(ValueError, match='espn'):
        league.add_league(2025)


def test_add_season_accepts_any_known_platform():
    league = ell_mod.EloLeague({
        'platform': 'sleeper',
        'league_type': 'nfl',
        'current_sports_year': 2025,
    })
    league.load()
    assert league.add_season({'league_id': '999'}, 2025) is True
    assert league.seasons[2025] == {'league_id': '999'}


def test_add_season_rejects_unknown_platform():
    league = ell_mod.EloLeague({
        'platform': 'espn',
        'league_type': 'nfl',
        'current_sports_year': 2025,
    })
    league.load()
    assert league.add_season({'league_id': '999'}, 2025) is False
    assert league.seasons == {}


# ---------------------------------------------------------------------------
# Scoring mode
# ---------------------------------------------------------------------------

def test_scoring_defaults_per_league_type():
    nfl = ell_mod.EloLeague({'platform': 'sleeper', 'league_type': 'nfl',
                             'current_sports_year': 2025})
    nfl.load()
    assert nfl.scoring == 'median'

    nba = ell_mod.EloLeague({'platform': 'fantrax', 'league_type': 'nba',
                             'current_sports_year': 2025})
    nba.load()
    assert nba.scoring == 'default'


def test_scoring_is_configurable_and_round_trips():
    league = ell_mod.EloLeague({'platform': 'sleeper', 'league_type': 'nfl',
                               'current_sports_year': 2025,
                               'scoring': 'default'})
    league.load()
    assert league.scoring == 'default'
    assert league.dump()['scoring'] == 'default'


# ---------------------------------------------------------------------------
# Dynasty: converting an existing league vs. initialising one
# ---------------------------------------------------------------------------

@pytest.fixture
def dynasty_league(monkeypatch):
    """A league configured as a dynasty from the outset."""
    monkeypatch.setattr(ell_mod, 'FantraxLeague',
                        make_fake_league_cls(build_scoreboards()))
    config = make_league_config()
    config['is_dynasty'] = True
    el = EloLeague(config)
    el.load()
    return el


def test_initialised_dynasty_sets_start_weeks_as_it_runs(dynasty_league):
    # Nothing has computed the offsets yet.
    assert 'dynasty_start_week' not in dynasty_league.seasons[2025]

    dynasty_league.run_season(2024)
    dynasty_league.run_season(2025)

    # 2024 is the first season, so it anchors the timeline at 0; 2025 starts
    # after 2024's three columns.
    assert dynasty_league.seasons[2024]['dynasty_start_week'] == 0
    assert dynasty_league.seasons[2025]['dynasty_start_week'] == 3


def test_initialised_dynasty_builds_the_dynasty_frame(dynasty_league):
    dynasty_league.run_season(2024)
    dynasty_league.run_season(2025)

    d = dynasty_league.frame_manager.dynasty_elo
    assert d is not None
    assert list(d.columns) == [f'week_{i}' for i in range(7)]
    assert d.notna().all().all()


def test_initialised_dynasty_matches_a_converted_one(dynasty_league, league):
    # The two routes to a dynasty must agree: building one from the start and
    # converting an equivalent redraft league produce the same ratings.
    dynasty_league.run_season(2024)
    dynasty_league.run_season(2025)
    initialised = dynasty_league.frame_manager.dynasty_elo

    league.run_season(2024)
    league.run_season(2025)
    assert league.change_dynasty(True) is True
    converted = league.frame_manager.dynasty_elo

    assert list(initialised.columns) == list(converted.columns)
    for member in MEMBERS:
        assert initialised.loc[member].tolist() == pytest.approx(
            converted.loc[member].tolist()
        )


def test_change_dynasty_refuses_without_a_frame_manager(league):
    # Nothing has been run, so there is no frame manager and nothing to
    # migrate. The league should stay redraft rather than blow up.
    assert league.frame_manager is None
    assert league.change_dynasty(True) is False
    assert league.is_dynasty is False


def test_change_dynasty_refuses_without_ratings(league):
    # run_prep builds the frame manager but computes no ratings.
    league.run_prep(2024)
    assert league.frame_manager is not None
    assert league.frame_manager.has_data() is False

    assert league.change_dynasty(True) is False
    assert league.is_dynasty is False
    assert league.frame_manager.dynasty_elo is None


def test_change_dynasty_converts_a_partially_rated_league(league):
    # 2025 has never been run; converting fills it in rather than refusing.
    league.run_season(2024)
    assert league.frame_manager.validate_season(2025) is False

    assert league.change_dynasty(True) is True
    assert list(league.frame_manager.dynasty_elo.columns) == \
        [f'week_{i}' for i in range(7)]


def test_validate_season_is_false_for_an_unrated_season(league):
    league.run_prep(2024)
    # No frame for either season yet; asking is normal, not an error.
    assert league.frame_manager.validate_season(2024) is False
    assert league.frame_manager.validate_season(2025) is False


def test_has_data_tracks_whether_anything_has_been_rated(league):
    league.run_prep(2024)
    assert league.frame_manager.has_data() is False
    league.run_season(2024)
    assert league.frame_manager.has_data() is True


def test_dynasty_start_week_needs_earlier_seasons_measured(dynasty_league):
    # 2024's length is what places 2025 on the timeline; without it the
    # offset is underivable and the error should say so.
    del dynasty_league.seasons[2024]['current_season_length']
    with pytest.raises(KeyError, match='2024'):
        dynasty_league._set_dynasty_start_week(2025)


def test_publish_config_reflects_state_set_since_load(league):
    # is_dynasty (and the rest of _dump's fields) live on the instance until
    # dumped, so a publish that shipped self.config raw would persist a league
    # that still called itself redraft.
    league.run_season(2024)
    league.run_season(2025)
    assert league.change_dynasty(True) is True

    payload = league.publish()

    assert payload['config']['is_dynasty'] is True
    assert league.config['is_dynasty'] is True


# ---------------------------------------------------------------------------
# EloSystem: shared configs, one ratings config per league
# ---------------------------------------------------------------------------

def _sys_config_file(tmp_path, **overrides):
    import yaml
    cfg = {
        'reader': 'csv', 'writer': 'csv',
        'csv_config_name': 'csv_config.yml',
        'sql_config_name': 'sql_config.yml',
        'ratings_configs': {'fantrax_nba': 'ratings_fantrax_nba.yml',
                            'sleeper_nfl': 'ratings_sleeper_nfl.yml'},
    }
    cfg.update(overrides)
    path = tmp_path / 'sys_config.yml'
    path.write_text(yaml.dump(cfg))
    return path


def test_league_selected_explicitly(tmp_path):
    es = EloSystem(str(_sys_config_file(tmp_path)), 'sleeper_nfl')
    assert es.league == 'sleeper_nfl'
    assert es.ratings_config_loc == 'ratings_sleeper_nfl.yml'


def test_league_falls_back_to_the_default(tmp_path):
    es = EloSystem(str(_sys_config_file(tmp_path, default_league='fantrax_nba')))
    assert es.league == 'fantrax_nba'
    assert es.ratings_config_loc == 'ratings_fantrax_nba.yml'


def test_single_configured_league_needs_no_default(tmp_path):
    path = _sys_config_file(tmp_path, ratings_configs={'only': 'ratings_only.yml'})
    es = EloSystem(str(path))
    assert es.league == 'only'
    assert es.ratings_config_loc == 'ratings_only.yml'


def test_ambiguous_league_is_an_error(tmp_path):
    # Two leagues, no default: guessing would publish one under the other's
    # name, so it has to be asked for.
    with pytest.raises(KeyError, match='default_league'):
        EloSystem(str(_sys_config_file(tmp_path)))


def test_unknown_league_is_an_error(tmp_path):
    with pytest.raises(KeyError, match='nope'):
        EloSystem(str(_sys_config_file(tmp_path)), 'nope')


def test_league_dir_defaults_to_the_league_key(tmp_path):
    es = EloSystem(str(_sys_config_file(tmp_path)), 'sleeper_nfl')
    assert es.league_dir == 'sleeper_nfl'


def test_league_dir_can_be_overridden_by_the_ratings_config(tmp_path):
    es = EloSystem(str(_sys_config_file(tmp_path)), 'sleeper_nfl')
    es.ratings_config = {'ratings_dir': 'somewhere_else'}
    assert es.league_dir == 'somewhere_else'


def test_sys_config_round_trips_the_league_wiring(tmp_path):
    es = EloSystem(str(_sys_config_file(tmp_path, default_league='fantrax_nba')))
    out = es._sys_config()
    assert out['ratings_configs'] == {'fantrax_nba': 'ratings_fantrax_nba.yml',
                                      'sleeper_nfl': 'ratings_sleeper_nfl.yml'}
    assert out['default_league'] == 'fantrax_nba'
    # The shared configs are named once, not per league.
    assert out['csv_config_name'] == 'csv_config.yml'
    assert out['sql_config_name'] == 'sql_config.yml'
    assert 'elo_league_config_name' not in out


def test_csv_backend_is_scoped_to_the_league(tmp_path):
    import yaml
    (tmp_path / 'csv_config.yml').write_text(yaml.dump({'write_loc': 'ratings'}))
    (tmp_path / 'ratings_sleeper_nfl.yml').write_text(yaml.dump({
        'platform': 'sleeper', 'league_type': 'nfl', 'current_sports_year': 2025}))
    es = EloSystem(str(_sys_config_file(tmp_path)), 'sleeper_nfl')
    es.load_configs({'ratings': None, 'csv': None})
    assert es.elo_csv.out_dir == tmp_path.parent / 'ratings' / 'sleeper_nfl'


def test_configs_are_read_league_first(tmp_path):
    # The CSV backend needs the league known to pick its directory, so the
    # ratings config must be read first whatever order the caller asked in.
    import yaml
    (tmp_path / 'csv_config.yml').write_text(yaml.dump({'write_loc': 'ratings'}))
    es = EloSystem(str(_sys_config_file(tmp_path)), 'sleeper_nfl')
    es.load_configs({'csv': {'write_loc': 'ratings'},
                     'ratings': {'platform': 'sleeper', 'league_type': 'nfl',
                                 'current_sports_year': 2025,
                                 'ratings_dir': 'chosen'}})
    assert es.elo_csv.out_dir.name == 'chosen'
