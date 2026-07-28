"""Tests for elo_system.tools.frame_manager.FrameManager."""
import pandas as pd
import pytest

from elo_system.tools.helpers.frame_manager import FrameManager

MEMBERS_2024 = ['alice', 'bob', 'cara', 'dan']
MEMBERS_2025 = ['alice', 'bob', 'cara', 'erin']  # dan leaves, erin joins


def make_members(ids):
    return {m: {'team_id': f't_{m}'} for m in ids}


def make_config(is_dynasty=False, is_roto=False, osa_factor=0.4, seasons=None):
    if seasons is None:
        seasons = {
            2024: {
                'league_members': make_members(MEMBERS_2024),
                'current_season_length': 3,
                'dynasty_start_week': 0,
            },
            2025: {
                'league_members': make_members(MEMBERS_2025),
                'current_season_length': 3,
                'dynasty_start_week': 4,
            },
        }
    return {
        'is_dynasty': is_dynasty,
        'is_roto': is_roto,
        'osa_factor': osa_factor,
        'seasons': seasons,
    }


# ---------------------------------------------------------------------------
# construction / config indexing
# ---------------------------------------------------------------------------

def test_level_indexes_seasons_sub_config():
    cfg = make_config()
    fm = FrameManager(cfg)
    # FrameManager.level == 'seasons' so config is the seasons sub-dict.
    assert fm.config is cfg['seasons']
    assert set(fm.config) == {2024, 2025}


def test_flags_read_from_top_level_config():
    fm = FrameManager(make_config(is_dynasty=True, is_roto=True, osa_factor=0.25))
    assert fm.is_dynasty is True
    assert fm.is_roto is True
    assert fm.osa_factor == 0.25


def test_member_dict_built_per_season():
    fm = FrameManager(make_config())
    assert list(fm.member_dict[2024]) == MEMBERS_2024
    assert list(fm.member_dict[2025]) == MEMBERS_2025


def test_get_current_sports_year_is_max_season():
    fm = FrameManager(make_config())
    assert fm.get_current_sports_year() == 2025


def test_set_is_dynasty_toggle_and_explicit():
    fm = FrameManager(make_config(is_dynasty=False))
    fm.set_is_dynasty()           # toggle
    assert fm.is_dynasty is True
    fm.set_is_dynasty()           # toggle back
    assert fm.is_dynasty is False
    fm.set_is_dynasty(True)
    assert fm.is_dynasty is True
    fm.set_is_dynasty(False)
    assert fm.is_dynasty is False


# ---------------------------------------------------------------------------
# generate / _gen_elo
# ---------------------------------------------------------------------------

def test_generate_creates_week0_at_1500():
    fm = FrameManager(make_config())
    fm.generate(2024)
    frame = fm.seasonal_elo[2024]
    assert list(frame.index) == MEMBERS_2024
    assert list(frame.columns) == ['week_0']
    assert (frame['week_0'] == 1500).all()


def test_generate_default_season_uses_current_sports_year():
    fm = FrameManager(make_config())
    fm.load()  # sets current_sports_year = max season key = 2025
    assert fm.current_sports_year == 2025
    fm.generate()
    assert 2025 in fm.seasonal_elo
    assert list(fm.seasonal_elo[2025].index) == MEMBERS_2025


def test_gen_elo_overwrite_false_preserves_existing_frame():
    fm = FrameManager(make_config())
    fm.generate(2024)
    original = fm.seasonal_elo[2024]
    original['week_1'] = 1600
    fm._gen_elo(2024, overwrite=False)
    assert fm.seasonal_elo[2024] is original
    assert 'week_1' in fm.seasonal_elo[2024].columns


def test_gen_elo_overwrite_true_regenerates():
    fm = FrameManager(make_config())
    fm.generate(2024)
    fm.seasonal_elo[2024]['week_1'] = 1600
    fm._gen_elo(2024, overwrite=True)
    assert list(fm.seasonal_elo[2024].columns) == ['week_0']


def test_generate_before_load_uses_config_year():
    fm = FrameManager(make_config())
    fm.generate()
    assert 2025 in fm.seasonal_elo


def test_gen_elo_none_generates_all_seasons():
    fm = FrameManager(make_config())
    fm._gen_elo(None)
    assert set(fm.seasonal_elo) == {2024, 2025}


def test_gen_elo_unknown_season_raises():
    fm = FrameManager(make_config())
    with pytest.raises(KeyError, match='Unknown season: 1999'):
        fm._gen_elo(1999)
    assert fm.seasonal_elo == {}


def test_gen_roto_none_generates_all_seasons():
    fm = FrameManager(make_config(is_roto=True))
    fm._gen_roto(None)
    assert set(fm.roto_history) == {2024, 2025}


def test_gen_roto_unknown_season_raises():
    fm = FrameManager(make_config(is_roto=True))
    with pytest.raises(KeyError, match='Unknown season: 1999'):
        fm._gen_roto(1999)
    assert fm.roto_history == {}


def test_generate_first_season_with_dynasty_enabled():
    fm = FrameManager(make_config(is_dynasty=True))
    fm.generate(2024, overwrite=True)
    assert 2024 in fm.seasonal_elo


# ---------------------------------------------------------------------------
# validate_season / can_dynasty
# ---------------------------------------------------------------------------

def test_validate_season_false_until_final_week_present():
    fm = FrameManager(make_config())
    fm.generate(2024)
    assert fm.validate_season(2024) is False  # only week_0, length is 3
    frame = fm.seasonal_elo[2024]
    for w in (1, 2, 3):
        frame[f'week_{w}'] = 1500.0
    assert fm.validate_season(2024) is True


def test_validate_season_uses_roto_history_when_roto():
    fm = FrameManager(make_config(is_roto=True))
    fm._gen_roto(2024)
    assert fm.validate_season(2024) is False
    fm.roto_history[2024]['week_3'] = 1.0
    assert fm.validate_season(2024) is True


def test_can_dynasty_consecutive_seasons():
    fm = FrameManager(make_config())
    assert fm.can_dynasty() is True


def test_can_dynasty_false_with_gap():
    seasons = {
        2024: {
            'league_members': make_members(MEMBERS_2024),
            'current_season_length': 3,
        },
        2026: {
            'league_members': make_members(MEMBERS_2025),
            'current_season_length': 3,
        },
    }
    fm = FrameManager(make_config(seasons=seasons))
    assert fm.can_dynasty() is False


# ---------------------------------------------------------------------------
# dynasty elo generation
# ---------------------------------------------------------------------------

def _played_2024_frame_manager(osa_factor=0.4):
    """FrameManager with a finished 2024 season at hand-picked elos."""
    fm = FrameManager(make_config(osa_factor=osa_factor))
    fm.generate(2024, overwrite=True)
    frame = fm.seasonal_elo[2024]
    # Final week of the 2024 season (index order: alice, bob, cara, dan).
    frame['week_3'] = [1600.0, 1400.0, 1500.0, 1550.0]
    return fm


def test_gen_dynasty_first_call_copies_seasonal_frame():
    fm = _played_2024_frame_manager()
    seasonal = fm.seasonal_elo[2024]
    fm._gen_dynasty_elo(2024)
    assert fm.dynasty_elo is not seasonal
    pd.testing.assert_frame_equal(fm.dynasty_elo, seasonal)
    # Mutating the dynasty frame must not touch the seasonal frame.
    fm.dynasty_elo.loc['alice', 'week_3'] = 0.0
    assert seasonal.loc['alice', 'week_3'] == 1600.0


def test_gen_dynasty_second_season_offseason_adjustment():
    fm = _played_2024_frame_manager()
    fm._gen_dynasty_elo(2024)
    fm._gen_dynasty_elo(2025)  # dynasty_start_week = 4 -> new col week_4
    d = fm.dynasty_elo

    assert 'week_4' in d.columns
    # offseason_adjustment with default factor 0.4: (elo - 1500) * 0.6 + 1500
    assert d.loc['alice', 'week_4'] == pytest.approx(1560.0)
    assert d.loc['bob', 'week_4'] == pytest.approx(1440.0)
    assert d.loc['cara', 'week_4'] == pytest.approx(1500.0)
    # New member joins at 1500 (NaN -> fillna(1500) -> adjustment is a no-op).
    assert 'erin' in d.index
    assert d.loc['erin', 'week_4'] == pytest.approx(1500.0)
    # A departed member is regressed like everyone else: 1550 -> 1530. Left
    # frozen, they would never decay toward the mean while the active league
    # did, and the league average could never hold at 1500.
    assert d.loc['dan', 'week_4'] == pytest.approx(1530.0)
    # Everyone (old and new) is present.
    assert set(d.index) == {'alice', 'bob', 'cara', 'dan', 'erin'}


def test_gen_dynasty_respects_custom_osa_factor():
    fm = _played_2024_frame_manager(osa_factor=0.2)
    fm._gen_dynasty_elo(2024)
    fm._gen_dynasty_elo(2025)
    d = fm.dynasty_elo
    # (elo - 1500) * 0.8 + 1500
    assert d.loc['alice', 'week_4'] == pytest.approx(1580.0)
    assert d.loc['bob', 'week_4'] == pytest.approx(1420.0)


def test_gen_dynasty_overwrite_false_is_idempotent():
    fm = _played_2024_frame_manager()
    fm._gen_dynasty_elo(2024)
    fm._gen_dynasty_elo(2025)
    fm.dynasty_elo.loc['alice', 'week_4'] = 9999.0
    fm._gen_dynasty_elo(2025, overwrite=False)
    assert fm.dynasty_elo.loc['alice', 'week_4'] == 9999.0


def test_gen_dynasty_overwrite_true_recomputes():
    fm = _played_2024_frame_manager()
    fm._gen_dynasty_elo(2024)
    fm._gen_dynasty_elo(2025)
    fm.dynasty_elo.loc['alice', 'week_4'] = 9999.0
    fm._gen_dynasty_elo(2025, overwrite=True)
    assert fm.dynasty_elo.loc['alice', 'week_4'] == pytest.approx(1560.0)


# ---------------------------------------------------------------------------
# roto frames
# ---------------------------------------------------------------------------

def test_gen_roto_creates_empty_member_indexed_frame():
    fm = FrameManager(make_config(is_roto=True))
    fm._gen_roto(2024)
    frame = fm.roto_history[2024]
    assert list(frame.index) == MEMBERS_2024
    assert frame.shape == (4, 0)


def test_generate_with_roto_builds_both_frames():
    fm = FrameManager(make_config(is_roto=True))
    fm.generate(2024)
    assert 2024 in fm.roto_history
    assert 2024 in fm.seasonal_elo


def test_gen_roto_overwrite_false_preserves():
    fm = FrameManager(make_config(is_roto=True))
    fm._gen_roto(2024)
    original = fm.roto_history[2024]
    fm._gen_roto(2024, overwrite=False)
    assert fm.roto_history[2024] is original


# ---------------------------------------------------------------------------
# publish payload
# ---------------------------------------------------------------------------

def test_publish_basic_payload():
    cfg = make_config()
    fm = FrameManager(cfg)
    fm.generate(2024)
    payload = fm.publish()
    assert set(payload) == {'config', 'seasonal_elo'}
    assert payload['config'] is cfg['seasons']
    assert payload['seasonal_elo'] is fm.seasonal_elo


def test_publish_includes_dynasty_when_enabled():
    fm = FrameManager(make_config(is_dynasty=True))
    payload = fm.publish()
    assert 'dynasty_elo' in payload
    assert payload['dynasty_elo'] is fm.dynasty_elo


def test_publish_includes_roto_when_enabled():
    fm = FrameManager(make_config(is_roto=True))
    fm._gen_roto(2024)
    payload = fm.publish()
    assert 'roto_history' in payload
    assert payload['roto_history'] is fm.roto_history


# ---------------------------------------------------------------------------
# _load_frame / load_frames and _validate_load_frame
# ---------------------------------------------------------------------------

def test_load_frame_installs_valid_seasonal_frame():
    fm = FrameManager(make_config())
    valid = pd.DataFrame({'week_0': [1500, 1500]}, index=['alice', 'bob'])
    fm._load_frame('seasonal_elo', valid, 2024)
    assert 2024 in fm.seasonal_elo
    pd.testing.assert_frame_equal(fm.seasonal_elo[2024], valid)


def test_load_frame_skips_invalid_frame():
    fm = FrameManager(make_config())
    invalid = pd.DataFrame({'nope': [1]}, index=['alice'])  # odd rows, no week_0
    fm._load_frame('seasonal_elo', invalid, 2024)
    assert fm.seasonal_elo == {}


def test_load_frame_dispatches_dynasty_and_roto():
    fm = FrameManager(make_config(is_dynasty=True, is_roto=True))
    frame = pd.DataFrame({'week_0': [1500, 1500]}, index=['alice', 'bob'])
    fm._load_frame('dynasty_elo', frame)
    fm._load_frame('roto_history', frame, 2025)
    pd.testing.assert_frame_equal(fm.dynasty_elo, frame)
    assert 2025 in fm.roto_history


def test_load_frames_installs_full_payload():
    fm = FrameManager(make_config(is_dynasty=True))
    seas = pd.DataFrame({'week_0': [1500, 1500]}, index=['alice', 'bob'])
    dyn = pd.DataFrame({'week_0': [1500, 1500]}, index=['alice', 'bob'])
    fm.load_frames({'dynasty_elo': dyn, 'seasonal_elo': {2024: seas}})
    assert 2024 in fm.seasonal_elo
    pd.testing.assert_frame_equal(fm.dynasty_elo, dyn)


def test_validate_load_frame_accepts_even_rows_with_week_columns():
    frame = pd.DataFrame(
        {'week_0': [1500, 1500], 'week_1': [1530, 1470]},
        index=['alice', 'bob'],
    )
    assert FrameManager._validate_load_frame(frame) is True


def test_validate_load_frame_rejects_odd_row_count():
    frame = pd.DataFrame({'week_0': [1500, 1500, 1500]})
    assert FrameManager._validate_load_frame(frame) is False


def test_validate_load_frame_rejects_non_week_columns():
    frame = pd.DataFrame(
        {'foo': [1, 2], 'week_1': [1530, 1470]},
        index=['alice', 'bob'],
    )
    assert FrameManager._validate_load_frame(frame) is False


def test_generated_week_zero_is_float():
    # The SQL backend stores elo as double precision, so a seeded frame has to
    # come out with the same dtype a loaded one does.
    fm = FrameManager(make_config())
    fm.generate(2024)
    assert fm.seasonal_elo[2024]['week_0'].dtype == 'float64'


# ---------------------------------------------------------------------------
# departed managers and the league average
# ---------------------------------------------------------------------------

def test_gen_dynasty_regresses_departed_members_repeatedly():
    # A manager who leaves keeps decaying every offseason, rather than being
    # pinned to whatever they last scored.
    fm = _played_2024_frame_manager()
    fm._gen_dynasty_elo(2024)
    fm._gen_dynasty_elo(2025)
    assert fm.dynasty_elo.loc['dan', 'week_4'] == pytest.approx(1530.0)

    # A third season with the same roster regresses dan again: 1530 -> 1518.
    fm.config[2026] = {
        'current_season_length': 3,
        'dynasty_start_week': 5,
        'league_members': {'alice': {}, 'bob': {}, 'cara': {}, 'erin': {}},
    }
    fm._gen_dynasty_elo(2026)
    assert fm.dynasty_elo.loc['dan', 'week_5'] == pytest.approx(1518.0)


def test_offseason_adjustment_holds_the_league_average_at_1500():
    # The whole point: if the frame averages 1500 going into an offseason it
    # still averages 1500 coming out, whoever left and whoever joined.
    fm = _played_2024_frame_manager()
    # dan (who departs) and the rest, balanced about 1500.
    fm.seasonal_elo[2024]['week_3'] = [1600.0, 1400.0, 1450.0, 1550.0]
    fm._gen_dynasty_elo(2024)
    assert fm.dynasty_elo['week_3'].mean() == pytest.approx(1500.0)

    fm._gen_dynasty_elo(2025)   # dan leaves, erin joins
    assert fm.dynasty_elo['week_4'].mean() == pytest.approx(1500.0), (
        'a departed or joining member must not shift the league average'
    )


def test_offseason_adjustment_moves_the_average_by_the_regression_law():
    # More generally, the frame mean regresses exactly as an individual does:
    # (mean - 1500) * (1 - factor) + 1500. It is only fixed at 1500.
    fm = _played_2024_frame_manager()
    fm._gen_dynasty_elo(2024)
    before = fm.dynasty_elo['week_3'].mean()          # 1512.5 on this fixture
    fm._gen_dynasty_elo(2025)
    after = fm.dynasty_elo['week_4'].mean()
    # erin joins at 1500, so the pre-adjustment population is the 4 old rows
    # plus one at 1500.
    expected_pre = (before * 4 + 1500.0) / 5
    assert after == pytest.approx((expected_pre - 1500) * 0.6 + 1500)


def test_departed_member_cannot_outrank_the_live_league_forever():
    # dan leaves on 1550, the best rating on the board. After enough
    # offseasons he is back in the pack rather than still top.
    fm = _played_2024_frame_manager()
    fm._gen_dynasty_elo(2024)
    assert fm.dynasty_elo['week_3'].idxmax() == 'alice'

    fm._gen_dynasty_elo(2025)
    d = fm.dynasty_elo
    # alice regressed 1600 -> 1560, dan 1550 -> 1530: alice still leads, and
    # dan's lead over the field shrinks instead of being frozen in.
    assert d.loc['alice', 'week_4'] > d.loc['dan', 'week_4']
    assert abs(d.loc['dan', 'week_4'] - 1500) < abs(1550 - 1500)
