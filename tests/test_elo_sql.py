"""Tests for elo_system.tools.elo_data.EloSQL.

No real database is touched: a fake connector stands in for the psycopg2
connection, pandas' read path is monkeypatched to serve in-memory dim tables,
and the write helpers record what they were handed instead of executing SQL.
"""
import pandas as pd
import pytest

import elo_system.tools.elo_data as elo_data
from elo_system.tools.elo_data import EloSQL
from elo_system.tools.basics.constants import (
    DYNASTY_DB_COLS,
    RATING_DB_COLS,
    ROTO_DB_COLS,
)


VALID_CONN = {
    'dbname': 'mydb',
    'user': 'alice',
    'password': 'secret',
    'port': 5432,
    'host': 'localhost',
}

DIM_COLUMNS = {
    'dim_league': ['league_id', 'discord_server_id', 'platform', 'league_name'],
    'dim_manager': ['manager_id', 'player_name', 'display_name', 'discord_id',
                    'is_comanager'],
    'dim_online_league': ['online_league_id', 'league_id', 'platform_league_id',
                          'league_year'],
    'dim_team': ['team_id', 'team_name', 'manager_id', 'online_league_id',
                 'platform_team_id', 'league_year', 'is_commish', 'is_champion',
                 'comanager_id', 'place_finish'],
}

LEAGUE_CONFIG = {
    'platform': 'fantrax',
    'current_sports_year': 2025,
    'seasons': {
        2024: {
            'league_id': 'plat2024',
            'current_season_length': 2,
            'league_members': {
                'Nate': {'team_id': 't1', 'curr_name': 'Nate FC',
                         'short_name': 'NAT', 'is_commish': True},
                'abrieff': {'team_id': 't2', 'curr_name': 'Abe FC',
                            'short_name': 'ABE', 'is_commish': False},
            },
        },
        2025: {
            'league_id': 'plat2025',
            'current_season_length': 1,
            'league_members': {
                'Nate': {'team_id': 't1', 'curr_name': 'Nate FC',
                         'short_name': 'NAT', 'is_commish': True},
                'abrieff': {'team_id': 't3', 'curr_name': 'Abe FC',
                            'short_name': 'ABE', 'is_commish': False},
            },
        },
    },
}


class FakeConn:
    """Stand-in for a psycopg2 connection; never actually used by these tests
    because every read/write path is monkeypatched."""
    pass


class FakeDB:
    """In-memory stand-in for the schema.

    ``tables`` holds one DataFrame per table name. Reads are served by parsing
    the table name out of the query; writes are recorded as (table, DataFrame).
    """

    def __init__(self, dims=None, facts=None):
        self.tables = {name: pd.DataFrame(columns=cols)
                       for name, cols in DIM_COLUMNS.items()}
        self.tables.update(dims or {})
        self.tables.update(facts or {})
        self.upserts = []
        self.replaces = []

    def read_sql_query(self, sql, con, index_col=None):
        table = sql.split('FROM ')[1].split()[0].split('.')[-1]
        frame = self.tables.get(table, pd.DataFrame()).copy()
        # The load queries filter on a scope column; honour it so a fact table
        # holding two seasons does not come back whole.
        if 'WHERE' in sql and not frame.empty:
            condition = sql.split('WHERE')[1].strip()
            column, value = (part.strip() for part in condition.split('='))
            frame = frame[frame[column] == int(value)]
            frame = frame.rename(columns={'elo': 'rating', 'score': 'rating'})
            frame = frame[['team_id', 'week', 'rating']]
        if index_col is not None:
            frame = frame.set_index(index_col)
        return frame

    def upsert(self, conn, df, table, match_columns, schema='public'):
        self.upserts.append((table, df.copy()))
        return len(df)

    def replace(self, conn, df, table, scope_column, scope_value, schema='public'):
        self.replaces.append((table, df.copy()))
        kept = self.tables.get(table)
        if kept is None or kept.empty:
            kept = df.iloc[:0]  # empty, but with the column dtypes intact
        else:
            kept = kept[kept[scope_column] != scope_value]
        self.tables[table] = pd.concat([kept, df], ignore_index=True)
        return len(df)


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(elo_data.pd, 'read_sql_query', fake.read_sql_query)
    monkeypatch.setattr(elo_data, 'upsert_dataframe', fake.upsert)
    monkeypatch.setattr(elo_data, 'replace_dataframe', fake.replace)
    return fake


def make_elosql(db, config=None, league_config=None):
    config = {'conn_dict': VALID_CONN} if config is None else config
    return EloSQL(config, league_config, connector=FakeConn())


def _config_with(year, owner, team='t1', **member_fields):
    """A one-season, one-member config, for exercising the sync's update pass."""
    info = {'team_id': team, 'curr_name': 'Nate FC', 'short_name': 'NAT',
            'is_commish': True}
    info.update(member_fields)
    return {
        'platform': 'fantrax',
        'current_sports_year': year,
        'seasons': {year: {'league_id': f'plat{year}', 'current_season_length': 1,
                           'league_members': {owner: info}}},
    }


def _frame(members, weeks, base=1500.0):
    return pd.DataFrame(
        {f'week_{w}': [base + w] * len(members) for w in range(weeks)},
        index=members,
    )


# ---------------------------------------------------------------------------
# __init__ connection resolution
# ---------------------------------------------------------------------------

def test_init_with_conn_dict(db):
    obj = make_elosql(db)
    assert obj.conn_dict == VALID_CONN
    assert isinstance(obj.conn, FakeConn)


def test_init_with_conn_uri(db):
    uri = 'postgresql://alice:secret@localhost:5432/mydb'
    obj = make_elosql(db, {'conn_uri': uri})
    assert obj.conn_dict == VALID_CONN


def test_init_no_connection_details_raises(db):
    with pytest.raises(KeyError, match='No connection details supplied'):
        EloSQL({}, connector=FakeConn())


def test_init_incomplete_connection_details_raises(db):
    with pytest.raises(ValueError, match='Incomplete connection details'):
        EloSQL({'conn_dict': {'dbname': 'mydb'}}, connector=FakeConn())


def test_init_default_schema(db):
    assert make_elosql(db).schema == 'fantasy_sports'


def test_init_schema_override_from_config(db):
    obj = make_elosql(db, {'conn_dict': VALID_CONN, 'schema': 'custom_schema'})
    assert obj.schema == 'custom_schema'


def test_init_pulls_every_dim(db):
    obj = make_elosql(db)
    assert set(obj.dim_tables) == set(DIM_COLUMNS)


def test_init_does_not_call_connect_when_connector_given(db, monkeypatch):
    def boom(*a, **k):
        raise AssertionError('connect() should not be called when connector given')

    monkeypatch.setattr(elo_data, 'connect', boom)
    assert isinstance(make_elosql(db).conn, FakeConn)


# ---------------------------------------------------------------------------
# _pull_dim caching behaviour
# ---------------------------------------------------------------------------

def test_pull_dim_skips_when_present_and_not_overwrite(db, monkeypatch):
    obj = make_elosql(db)
    monkeypatch.setattr(elo_data.pd, 'read_sql_query', lambda *a, **k: pytest.fail('read'))
    assert obj._pull_dim('team', overwrite=False) is True


def test_pull_dim_reads_when_overwrite(db):
    obj = make_elosql(db)
    obj.dim_tables['dim_team'] = pd.DataFrame({'sentinel': [1]})
    assert obj._pull_dim('team', overwrite=True) is True
    assert 'sentinel' not in obj.dim_tables['dim_team'].columns


def test_pull_dim_indexes_on_the_surrogate_id(db):
    obj = make_elosql(db)
    assert obj.dim_tables['dim_team'].index.name == 'team_id'


# ---------------------------------------------------------------------------
# league resolution
# ---------------------------------------------------------------------------

def test_league_id_is_unresolved_against_an_empty_db(db):
    assert make_elosql(db, league_config=LEAGUE_CONFIG).get_lid() == -1


def test_league_id_taken_from_config_when_given(db):
    config = dict(LEAGUE_CONFIG, league_id=7)
    assert make_elosql(db, league_config=config).get_lid() == 7


def test_league_id_looked_up_from_platform_league_id(db):
    db.tables['dim_online_league'] = pd.DataFrame({
        'online_league_id': [0],
        'league_id': [3],
        'platform_league_id': ['plat2024'],
        'league_year': [2024],
    })
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    assert obj.get_lid() == 3


def test_set_league_config_tolerates_a_config_without_seasons(db):
    obj = make_elosql(db, league_config={'platform': 'fantrax'})
    assert obj.seasons == {}
    assert obj.get_lid() == -1


# ---------------------------------------------------------------------------
# dim sync
# ---------------------------------------------------------------------------

def test_sync_dims_creates_a_league_row(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()

    assert obj.get_lid() == 0
    league = obj._dim('league')
    assert list(league['platform']) == ['fantrax']
    assert league['league_name'].iloc[0] == obj.league_name


def test_sync_dims_creates_one_online_league_per_season(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()

    online = obj._dim('online_league').sort_values('league_year')
    assert list(online['league_year']) == [2024, 2025]
    assert list(online['platform_league_id']) == ['plat2024', 'plat2025']
    assert list(online['league_id']) == [0, 0]


def test_sync_dims_creates_one_manager_per_member(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()

    managers = obj._dim('manager')
    # The member key is the platform owner name, which lives in display_name;
    # 'Nate' plays both seasons but is one manager.
    assert sorted(managers['display_name']) == ['Nate', 'abrieff']
    assert list(managers['is_comanager']) == [False, False]


def test_sync_dims_seeds_the_discord_owned_manager_fields(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()

    managers = obj._dim('manager')
    # player_name and discord_id belong to Discord; seed them with generated
    # ids rather than NULL so the row is complete until Discord fills them in.
    assert managers['player_name'].notna().all()
    assert managers['discord_id'].notna().all()
    assert set(managers['player_name']) & set(managers['display_name']) == set()


def test_sync_dims_never_overwrites_discord_owned_manager_fields(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()

    # Stand in for the Discord side filling the real values in.
    managers = obj.dim_tables['dim_manager']
    managers.loc[managers['display_name'] == 'Nate', 'player_name'] = 'Nathan Real'
    managers.loc[managers['display_name'] == 'Nate', 'discord_id'] = '99887766'
    managers.loc[managers['display_name'] == 'Nate', 'is_comanager'] = True

    obj.sync_dims()

    nate = obj._dim('manager')
    nate = nate[nate['display_name'] == 'Nate'].iloc[0]
    assert nate['player_name'] == 'Nathan Real'
    assert nate['discord_id'] == '99887766'
    assert nate['is_comanager'] is True or nate['is_comanager'] == True  # noqa: E712


def test_sync_dims_creates_one_team_per_season_and_platform_team(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()

    teams = obj._dim('team')
    assert len(teams) == 4
    assert set(zip(teams['league_year'], teams['platform_team_id'])) == {
        (2024, 't1'), (2024, 't2'), (2025, 't1'), (2025, 't3'),
    }
    # Nate's two seasons are the same manager.
    nate = teams[teams['platform_team_id'] == 't1']
    assert nate['manager_id'].nunique() == 1


def test_sync_dims_is_idempotent(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()
    obj.sync_dims()

    assert len(obj._dim('league')) == 1
    assert len(obj._dim('online_league')) == 2
    assert len(obj._dim('manager')) == 2
    assert len(obj._dim('team')) == 4


def test_sync_dims_pushes_every_dim(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()
    assert {table for table, _ in db.upserts} == set(DIM_COLUMNS)


def test_sync_dims_takes_place_finish_from_the_scraped_standing(db):
    config = _config_with(2024, 'Nate', standing=3)
    obj = make_elosql(db, league_config=config)
    obj.sync_dims()

    teams = obj._dim('team')
    nate = teams[(teams['league_year'] == 2024) & (teams['platform_team_id'] == 't1')]
    assert nate['place_finish'].iloc[0] == 3


def test_sync_dims_refreshes_scraped_team_columns(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()
    before = obj._dim('team')
    team_ids = set(before['team_id'])

    # Same platform team, renamed and finished the season.
    renamed = _config_with(2024, 'Nate', curr_name='Nate United', standing=1,
                           is_commish=False)
    obj.set_league_config(renamed)
    obj.sync_dims()

    teams = obj._dim('team')
    nate = teams[(teams['league_year'] == 2024) & (teams['platform_team_id'] == 't1')]
    assert nate['team_name'].iloc[0] == 'Nate United'
    assert nate['place_finish'].iloc[0] == 1
    assert bool(nate['is_commish'].iloc[0]) is False
    # Refreshed in place -- no second row, no new surrogate id.
    assert len(nate) == 1
    assert set(obj._dim('team')['team_id']) == team_ids


def test_sync_dims_preserves_columns_it_does_not_own(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()

    teams = obj.dim_tables['dim_team']
    target = teams['platform_team_id'] == 't1'
    teams.loc[target, 'is_champion'] = True
    teams.loc[target, 'comanager_id'] = 1

    obj.sync_dims()

    teams = obj._dim('team')
    nate = teams[teams['platform_team_id'] == 't1'].iloc[0]
    assert bool(nate['is_champion']) is True
    assert nate['comanager_id'] == 1


def test_sync_dims_keeps_a_stored_standing_when_none_is_scraped(db):
    obj = make_elosql(db, league_config=_config_with(2024, 'Nate', standing=2))
    obj.sync_dims()

    # A mid-scrape config with no standing must not blank the stored one.
    obj.set_league_config(_config_with(2024, 'Nate'))
    obj.sync_dims()

    teams = obj._dim('team')
    assert teams[teams['platform_team_id'] == 't1']['place_finish'].iloc[0] == 2


def test_sync_dims_follows_a_team_changing_hands(db):
    obj = make_elosql(db, league_config=_config_with(2024, 'Nate'))
    obj.sync_dims()
    before = obj._dim('manager')
    nate_id = before[before['display_name'] == 'Nate']['manager_id'].iloc[0]

    # Same platform team id, different owner the following scrape.
    obj.set_league_config(_config_with(2024, 'abrieff'))
    obj.sync_dims()

    managers = obj._dim('manager')
    abrieff_id = managers[managers['display_name'] == 'abrieff']['manager_id'].iloc[0]
    assert abrieff_id != nate_id
    teams = obj._dim('team')
    assert teams[teams['platform_team_id'] == 't1']['manager_id'].iloc[0] == abrieff_id


# ---------------------------------------------------------------------------
# columns the sync does not own
# ---------------------------------------------------------------------------

def test_set_champion_flags_the_teams_row(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()

    team_id = obj.set_champion(2024, 'Nate')

    teams = obj._dim('team').set_index('team_id')
    assert bool(teams.loc[team_id, 'is_champion']) is True
    # Nobody else was touched.
    assert teams.drop(index=team_id)['is_champion'].isna().all()


def test_set_champion_can_clear_and_survives_a_resync(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()
    obj.set_champion(2024, 'Nate')
    obj.sync_dims()

    teams = obj._dim('team')
    assert bool(teams[teams['platform_team_id'] == 't1']['is_champion'].iloc[0]) is True

    obj.set_champion(2024, 'Nate', is_champion=False)
    teams = obj._dim('team')
    assert bool(teams[teams['platform_team_id'] == 't1']['is_champion'].iloc[0]) is False


def test_set_comanager_resolves_the_owner_name_to_a_manager_id(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()

    team_id = obj.set_comanager(2024, 'Nate', 'abrieff')

    teams = obj._dim('team').set_index('team_id')
    assert teams.loc[team_id, 'comanager_id'] == obj.resolve_manager_id('abrieff')


def test_set_comanager_accepts_an_id_and_clears_with_none(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()
    abrieff = obj.resolve_manager_id('abrieff')

    team_id = obj.set_comanager(2024, 'Nate', abrieff)
    teams = obj._dim('team').set_index('team_id')
    assert teams.loc[team_id, 'comanager_id'] == abrieff

    obj.set_comanager(2024, 'Nate', None)
    teams = obj._dim('team').set_index('team_id')
    assert teams.loc[team_id, 'comanager_id'] is None


def test_setters_push_the_dim_by_default(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()
    db.upserts.clear()

    obj.set_champion(2024, 'Nate')
    assert [table for table, _ in db.upserts] == ['dim_team']

    db.upserts.clear()
    obj.set_comanager(2024, 'Nate', 'abrieff', push=False)
    assert db.upserts == []


def test_setters_raise_on_an_unknown_team_or_comanager(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()

    with pytest.raises(KeyError, match='No team on file'):
        obj.set_champion(2024, 'stranger')
    with pytest.raises(KeyError, match='No manager on file'):
        obj.set_comanager(2024, 'Nate', 'stranger')


def test_add_league_year_returns_existing_season(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()
    first = obj._online_league_id(2024)
    assert obj.add_league_year(2024) == first
    assert len(obj._dim('online_league')) == 2


# ---------------------------------------------------------------------------
# publishing
# ---------------------------------------------------------------------------

def test_publish_seasonal_writes_the_fact_columns(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.publish({'config': LEAGUE_CONFIG,
                 'seasonal_elo': {2024: _frame(['Nate', 'abrieff'], 2)}})

    table, frame = db.replaces[-1]
    assert table == 'fact_seasonal_elos'
    assert list(frame.columns) == RATING_DB_COLS
    # two members x two weeks
    assert len(frame) == 4
    assert set(frame['manager_name']) == {'Nate', 'abrieff'}
    assert frame['online_league_id'].nunique() == 1


def test_publish_seasonal_scopes_each_season_to_its_online_league(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.publish({'config': LEAGUE_CONFIG, 'seasonal_elo': {
        2024: _frame(['Nate', 'abrieff'], 1),
        2025: _frame(['Nate', 'abrieff'], 1),
    }})

    scopes = [frame['online_league_id'].iloc[0] for _, frame in db.replaces]
    assert len(set(scopes)) == 2


def test_publish_roto_writes_score_to_fact_rotos(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.publish({'config': LEAGUE_CONFIG,
                 'roto_history': {2024: _frame(['Nate', 'abrieff'], 2, base=5.0)}})

    table, frame = db.replaces[-1]
    assert table == 'fact_rotos'
    assert list(frame.columns) == ROTO_DB_COLS
    assert set(frame['score']) == {5.0, 6.0}


def test_publish_dynasty_maps_weeks_back_onto_their_season(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    # 2024 is 3 weeks (length 2 + week 0), 2025 the following 2.
    obj.publish({'config': LEAGUE_CONFIG,
                 'dynasty_elo': _frame(['Nate', 'abrieff'], 5)})

    table, frame = db.replaces[-1]
    assert table == 'fact_dynasty_elos'
    assert list(frame.columns) == DYNASTY_DB_COLS
    assert set(frame['league_id']) == {obj.get_lid()}

    teams = obj._dim('team').set_index('team_id')
    years = frame['team_id'].map(teams['league_year'])
    assert sorted(years[frame['week'] < 3].unique()) == [2024]
    assert sorted(years[frame['week'] >= 3].unique()) == [2025]


def test_publish_drops_members_with_no_dim_row(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.publish({'config': LEAGUE_CONFIG,
                 'seasonal_elo': {2024: _frame(['Nate', 'stranger'], 1)}})

    _, frame = db.replaces[-1]
    assert list(frame['manager_name']) == ['Nate']


def test_publish_of_an_unresolvable_frame_writes_nothing(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.publish({'config': LEAGUE_CONFIG,
                 'seasonal_elo': {2024: _frame(['stranger'], 1)}})
    assert db.replaces == []


def test_publish_unknown_destination_raises(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()
    with pytest.raises(KeyError, match='Unknown destination'):
        obj._publish_indexed_frame('nonsense', 2024, _frame(['Nate'], 1))


def test_publish_picks_up_seasons_added_after_construction(db):
    obj = make_elosql(db, league_config={'platform': 'fantrax'})
    assert obj.seasons == {}

    obj.publish({'config': LEAGUE_CONFIG,
                 'seasonal_elo': {2024: _frame(['Nate', 'abrieff'], 1)}})
    assert set(obj.seasons) == {2024, 2025}
    assert db.replaces


def test_seasons_by_order_resolves_the_ordinal_to_a_year(db):
    # Under seasons_by='order' DataBase hands each frame its rank among the
    # frames being published, so the SQL side has to map that ordinal back onto
    # a real season year before it can name an online league.
    obj = make_elosql(db, {'conn_dict': VALID_CONN, 'seasons_by': 'order'},
                      LEAGUE_CONFIG)
    obj.publish({'config': LEAGUE_CONFIG, 'seasonal_elo': {
        2024: _frame(['Nate', 'abrieff'], 1),
        2025: _frame(['Nate', 'abrieff'], 1),
    }})

    scopes = [frame['online_league_id'].iloc[0] for _, frame in db.replaces]
    assert scopes == [obj._online_league_id(2024), obj._online_league_id(2025)]
    assert obj.load_frames('seasonal_elo')['seasonal_elo'].keys() == {2024, 2025}


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------

def test_load_frames_round_trips_a_published_season(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    seasonal = _frame(['Nate', 'abrieff'], 3)
    obj.publish({'config': LEAGUE_CONFIG, 'seasonal_elo': {2024: seasonal}})

    loaded = obj.load_frames('seasonal_elo')
    assert set(loaded) == {'seasonal_elo'}
    assert set(loaded['seasonal_elo']) == {2024}
    pd.testing.assert_frame_equal(
        loaded['seasonal_elo'][2024].sort_index(),
        seasonal.sort_index(),
        check_names=False,
    )


def test_load_frames_round_trips_dynasty(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    dynasty = _frame(['Nate', 'abrieff'], 5)
    obj.publish({'config': LEAGUE_CONFIG, 'dynasty_elo': dynasty})

    loaded = obj.load_frames('dynasty_elo')
    pd.testing.assert_frame_equal(
        loaded['dynasty_elo'].sort_index(), dynasty.sort_index(), check_names=False)


def test_load_frames_round_trips_roto(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    roto = _frame(['Nate', 'abrieff'], 2, base=4.0)
    obj.publish({'config': LEAGUE_CONFIG, 'roto_history': {2024: roto}})

    loaded = obj.load_frames('roto_history')
    pd.testing.assert_frame_equal(
        loaded['roto_history'][2024].sort_index(), roto.sort_index(), check_names=False)


def test_load_frames_omits_empty_sets(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.publish({'config': LEAGUE_CONFIG,
                 'seasonal_elo': {2024: _frame(['Nate'], 1)}})

    loaded = obj.load_frames()
    assert set(loaded) == {'seasonal_elo'}


def test_load_frames_on_an_empty_db_returns_nothing(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    assert obj.load_frames() == {}
    assert obj.load_frames('dynasty_elo') == {}


def test_load_unknown_frame_set_raises(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    with pytest.raises(KeyError, match='Unknown frame set'):
        obj.load_frames('not_a_set')


def test_loaded_frames_are_consumable_by_frame_manager(db):
    from elo_system.tools.helpers.frame_manager import FrameManager

    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    seasonal = _frame(['Nate', 'abrieff'], 2)
    obj.publish({'config': LEAGUE_CONFIG, 'seasonal_elo': {2024: seasonal}})

    fm = FrameManager({
        'is_dynasty': False,
        'is_roto': False,
        'seasons': {2024: {'league_members': {'Nate': {}, 'abrieff': {}},
                           'current_season_length': 1}},
    })
    fm.load_frames(obj.load_frames('seasonal_elo'))
    assert 2024 in fm.seasonal_elo
    pd.testing.assert_frame_equal(
        fm.seasonal_elo[2024].sort_index(), seasonal.sort_index(), check_names=False)
