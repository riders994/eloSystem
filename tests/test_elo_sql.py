"""Tests for elo_system.tools.elo_data.EloSQL.

No real database is touched: a fake connector stands in for the psycopg2
connection, pandas' read path is monkeypatched to serve in-memory dim tables,
and the write helpers record what they were handed instead of executing SQL.
"""
from pathlib import Path

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
    'dim_league': ['league_id', 'discord_server_id', 'league_name'],
    'dim_manager': ['manager_id', 'player_name', 'discord_id'],
    'dim_manager_platform': ['manager_id', 'platform', 'platform_user_id',
                             'display_name'],
    'dim_online_league': ['online_league_id', 'league_id', 'platform',
                          'platform_league_id', 'league_year'],
    'dim_team': ['team_id', 'team_name', 'manager_id', 'online_league_id',
                 'platform_team_id', 'league_year', 'is_commish', 'is_champion',
                 'comanager_id', 'place_finish'],
}

# The league/manager bridge is a table, not a dim: no surrogate id, and the
# publish rewrites one league's rows at a time.
BRIDGE_COLUMNS = {'mvw_fact_league_managers': ['league_id', 'manager_id']}

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
                       for name, cols in {**DIM_COLUMNS, **BRIDGE_COLUMNS}.items()}
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
            # Honour whichever id the query actually selected: seasonal facts
            # come back by team, dynasty facts by manager.
            member_col = sql.split('SELECT')[1].split(',')[0].strip()
            frame = frame[[member_col, 'week', 'rating']]
        if index_col is not None:
            frame = frame.set_index(index_col)
        return frame

    def upsert(self, conn, df, table, match_columns, schema='public'):
        self.upserts.append((table, df.copy()))
        kept = self.tables.get(table)
        if kept is None or kept.empty:
            self.tables[table] = df.copy()
        else:
            incoming = set(df[match_columns].apply(tuple, axis=1))
            keys = kept[match_columns].apply(tuple, axis=1)
            self.tables[table] = pd.concat(
                [kept[~keys.isin(incoming)], df], ignore_index=True)
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


def _fact_writes(db):
    """The replaces that landed in a fact table.

    Every sync also replaces the league's rows in mvw_fact_league_managers, so
    the raw log is not just the ratings.
    """
    return [(table, frame) for table, frame in db.replaces
            if table != 'mvw_fact_league_managers']


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


def test_init_pulls_nothing(db):
    # Construction must stay offline: EloSystem builds every configured
    # backend up front, so an unreachable DB would otherwise break the CSV
    # workflow too.
    obj = make_elosql(db)
    assert obj.dim_tables == {}


def test_init_does_not_connect(db, monkeypatch):
    # With no connector handed in, the backend still must not dial out until
    # something actually reads from it.
    monkeypatch.setattr(elo_data, 'connect',
                        lambda *a, **k: pytest.fail('connect() at construction'))
    obj = EloSQL({'conn_dict': VALID_CONN}, LEAGUE_CONFIG, connector=None)
    assert obj._conn is None


def test_connection_opens_on_first_use(db, monkeypatch):
    opened = []

    def fake_connect(conn_dict):
        opened.append(conn_dict)
        return FakeConn()

    monkeypatch.setattr(elo_data, 'connect', fake_connect)
    obj = EloSQL({'conn_dict': VALID_CONN}, LEAGUE_CONFIG, connector=None)
    assert opened == []
    assert isinstance(obj.conn, FakeConn)
    assert len(opened) == 1
    obj.conn                       # reused, not reopened
    assert len(opened) == 1


def test_dims_pull_on_first_read(db):
    obj = make_elosql(db)
    obj._dim('team')
    assert 'dim_team' in obj.dim_tables
    # Only what was asked for; the rest stay unfetched until they are needed.
    assert 'dim_manager' not in obj.dim_tables


def test_every_dim_pulls_when_reached(db):
    obj = make_elosql(db)
    for dim in DIM_COLUMNS:
        obj._dim(dim.removeprefix('dim_'))
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
    obj._dim('team')          # first read fetches it
    monkeypatch.setattr(elo_data.pd, 'read_sql_query', lambda *a, **k: pytest.fail('read'))
    assert obj._pull_dim('team', overwrite=False) is True


def test_pull_dim_reads_when_overwrite(db):
    obj = make_elosql(db)
    obj._dim('team')
    obj.dim_tables['dim_team'] = pd.DataFrame({'sentinel': [1]})
    assert obj._pull_dim('team', overwrite=True) is True
    assert 'sentinel' not in obj.dim_tables['dim_team'].columns


def test_pull_dim_indexes_on_the_surrogate_id(db):
    obj = make_elosql(db)
    obj._dim('team')
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
        'platform': ['fantrax'],
        'platform_league_id': ['plat2024'],
        'league_year': [2024],
    })
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    assert obj.get_lid() == 3


def test_league_id_lookup_requires_the_platform_to_match(db):
    # A platform league id is only unique within its own platform, and one
    # Discord server can run leagues on more than one -- so the same id under a
    # different platform is a different league.
    db.tables['dim_online_league'] = pd.DataFrame({
        'online_league_id': [0],
        'league_id': [3],
        'platform': ['sleeper'],
        'platform_league_id': ['plat2024'],
        'league_year': [2024],
    })
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    assert obj.get_lid() == -1


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
    # No platform on the league itself: it is a community on a Discord server,
    # and which platform it played on belongs to each of its seasons.
    assert 'platform' not in league.columns
    assert league['league_name'].iloc[0] == obj.league_name


def test_sync_dims_creates_one_online_league_per_season(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()

    online = obj._dim('online_league').sort_values('league_year')
    assert list(online['league_year']) == [2024, 2025]
    assert list(online['platform_league_id']) == ['plat2024', 'plat2025']
    assert list(online['league_id']) == [0, 0]
    assert list(online['platform']) == ['fantrax', 'fantrax']


def test_sync_dims_records_the_platform_each_season_was_played_on(db):
    # A league that moved keeps one identity: same dim_league row, one platform
    # per season on the online leagues under it.
    moved = {
        'platform': 'fantrax',
        'current_sports_year': 2025,
        'seasons': {
            2024: dict(LEAGUE_CONFIG['seasons'][2024]),
            2025: dict(LEAGUE_CONFIG['seasons'][2025], platform='sleeper'),
        },
    }
    obj = make_elosql(db, league_config=moved)
    obj.sync_dims()

    assert len(obj._dim('league')) == 1
    online = obj._dim('online_league').sort_values('league_year')
    assert list(online['platform']) == ['fantrax', 'sleeper']


def test_sync_dims_creates_one_manager_per_member(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()

    # The member key is the account id, which lives in dim_manager_platform;
    # 'Nate' plays both seasons but is one account and so one person.
    accounts = obj._dim('manager_platform')
    assert sorted(accounts['platform_user_id']) == ['Nate', 'abrieff']
    assert list(accounts['platform']) == ['fantrax', 'fantrax']
    assert len(obj._dim('manager')) == 2


def test_sync_dims_files_the_league_managers_in_the_bridge(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()

    bridge = db.tables['mvw_fact_league_managers']
    assert set(bridge['league_id']) == {obj.get_lid()}
    assert sorted(bridge['manager_id']) == sorted(obj._dim('manager')['manager_id'])


def test_sync_dims_seeds_the_discord_owned_manager_fields(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()

    managers = obj._dim('manager')
    # player_name and discord_id belong to Discord; seed them with generated
    # ids rather than NULL so the row is complete until Discord fills them in.
    assert managers['player_name'].notna().all()
    assert managers['discord_id'].notna().all()
    accounts = obj._dim('manager_platform')
    assert set(managers['player_name']) & set(accounts['display_name']) == set()


def test_sync_dims_never_overwrites_discord_owned_manager_fields(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()
    nate_id = obj.resolve_manager_id('Nate')

    # Stand in for the Discord side filling the real values in.
    managers = obj.dim_tables['dim_manager']
    managers.loc[nate_id, 'player_name'] = 'Nathan Real'
    managers.loc[nate_id, 'discord_id'] = '99887766'

    obj.sync_dims()

    nate = obj._dim('manager').set_index('manager_id').loc[nate_id]
    assert nate['player_name'] == 'Nathan Real'
    assert nate['discord_id'] == '99887766'


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
    assert len(obj._dim('manager_platform')) == 2
    assert len(obj._dim('team')) == 4
    assert len(db.tables['mvw_fact_league_managers']) == 2


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
    nate_id = obj.resolve_manager_id('Nate')

    # Same platform team id, different owner the following scrape.
    obj.set_league_config(_config_with(2024, 'abrieff'))
    obj.sync_dims()

    abrieff_id = obj.resolve_manager_id('abrieff')
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
    assert table == 'fact_elos'
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

    scopes = [frame['online_league_id'].iloc[0] for _, frame in _fact_writes(db)]
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
    assert _fact_writes(db) == []


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
    assert _fact_writes(db)


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

    scopes = [frame['online_league_id'].iloc[0] for _, frame in _fact_writes(db)]
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


# ---------------------------------------------------------------------------
# anonymisation
# ---------------------------------------------------------------------------

def anon_config(tmp_path, **extra):
    config = {'conn_dict': VALID_CONN, 'anonymizer': True, 'anon_loc': str(tmp_path)}
    config.update(extra)
    return config


def test_anonymize_is_off_by_default(db, tmp_path):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()

    _, pushed = next(t for t in db.upserts if t[0] == 'dim_manager_platform')
    assert set(pushed['platform_user_id']) == {'Nate', 'abrieff'}
    assert list(tmp_path.glob('*.json')) == []


def test_anonymize_writes_tokens_to_the_db_not_names(db, tmp_path):
    obj = make_elosql(db, anon_config(tmp_path), LEAGUE_CONFIG)
    obj.sync_dims()

    _, accounts = next(t for t in db.upserts if t[0] == 'dim_manager_platform')
    # The account id and the name it shows under are different value spaces, so
    # they get a category each and never share a token.
    assert set(accounts['platform_user_id']) == {'account_0', 'account_1'}
    assert set(accounts['display_name']) == {'manager_0', 'manager_1'}
    # The platform itself is not a name, so it goes out as itself -- the DB's
    # uniqueness constraint on (platform, platform_user_id) is on the token.
    assert set(accounts['platform']) == {'fantrax'}

    _, managers = next(t for t in db.upserts if t[0] == 'dim_manager')
    assert all(name.startswith('person_') for name in managers['player_name'])
    # The dims held in memory are untouched -- tokens live only in the DB.
    assert set(obj._dim('manager_platform')['platform_user_id']) == {'Nate', 'abrieff'}


def test_anonymize_writes_a_reversal_map(db, tmp_path):
    obj = make_elosql(db, anon_config(tmp_path), LEAGUE_CONFIG)
    obj.sync_dims()

    import json
    mapping = json.loads((tmp_path / 'anon_manager_platform.json').read_text())
    assert set(mapping['account'].values()) == {'Nate', 'abrieff'}
    # display_name falls back to the account id when nothing was scraped, so
    # here the two categories cover the same values under different tokens.
    assert set(mapping['manager'].values()) == {'Nate', 'abrieff'}

    person = json.loads((tmp_path / 'anon_manager.json').read_text())
    assert set(person) == {'person'}


def test_fact_manager_name_carries_the_dim_token(db, tmp_path):
    obj = make_elosql(db, anon_config(tmp_path), LEAGUE_CONFIG)
    obj.publish({'config': LEAGUE_CONFIG,
                 'seasonal_elo': {2024: _frame(['Nate', 'abrieff'], 2)}})

    _, facts = db.replaces[-1]
    _, accounts = next(
        t for t in reversed(db.upserts) if t[0] == 'dim_manager_platform')
    token_by_id = dict(zip(accounts['manager_id'], accounts['display_name']))

    assert not {'Nate', 'abrieff'} & set(facts['manager_name'])
    # manager_name denormalises the account's display name, so every fact row
    # must carry the token that dim's own push minted for it.
    for _, row in facts.iterrows():
        assert row['manager_name'] == token_by_id[row['manager_id']]


def test_anonymized_frames_round_trip_through_a_fresh_reader(db, tmp_path):
    obj = make_elosql(db, anon_config(tmp_path), LEAGUE_CONFIG)
    seasonal = _frame(['Nate', 'abrieff'], 3)
    obj.publish({'config': LEAGUE_CONFIG, 'seasonal_elo': {2024: seasonal}})

    # A reader that never saw the real names, reading tokens out of the DB.
    reader = make_elosql(db, anon_config(tmp_path), LEAGUE_CONFIG)
    assert set(reader._dim('manager_platform')['platform_user_id']) == {
        'Nate', 'abrieff'}

    loaded = reader.load_frames('seasonal_elo')
    pd.testing.assert_frame_equal(
        loaded['seasonal_elo'][2024].sort_index(),
        seasonal.sort_index(),
        check_names=False,
    )


def test_reader_without_the_map_falls_back_to_tokens(db, tmp_path):
    obj = make_elosql(db, anon_config(tmp_path), LEAGUE_CONFIG)
    obj.publish({'config': LEAGUE_CONFIG,
                 'seasonal_elo': {2024: _frame(['Nate', 'abrieff'], 2)}})

    # Map left behind; a reader pointed elsewhere cannot reverse the tokens.
    elsewhere = tmp_path / 'no_map'
    reader = make_elosql(db, anon_config(elsewhere), LEAGUE_CONFIG)
    loaded = reader.load_frames('seasonal_elo')
    # Degrades to token-named members rather than failing outright. The member is
    # the account id, so it is that column's category the index comes back under.
    assert set(loaded['seasonal_elo'][2024].index) == {'account_0', 'account_1'}


def test_tokens_stay_put_when_a_member_is_added(db, tmp_path):
    obj = make_elosql(db, anon_config(tmp_path), _config_with(2024, 'Nate'))
    obj.sync_dims()
    _, first = next(
        t for t in reversed(db.upserts) if t[0] == 'dim_manager_platform')
    nate_token = first[first['manager_id'] == 0]['platform_user_id'].iloc[0]

    grown = _config_with(2024, 'Nate')
    grown['seasons'][2024]['league_members']['abrieff'] = {
        'team_id': 't2', 'curr_name': 'Abe FC', 'short_name': 'ABE',
        'is_commish': False}
    obj.set_league_config(grown)
    obj.sync_dims()

    _, second = next(
        t for t in reversed(db.upserts) if t[0] == 'dim_manager_platform')
    # A newcomer appends; it must not renumber whoever was already stored.
    assert second[second['manager_id'] == 0]['platform_user_id'].iloc[0] == nate_token


def test_anon_columns_config_extends_the_defaults(db, tmp_path):
    obj = make_elosql(
        db,
        anon_config(tmp_path, anon_columns={'team': {'team_name': 'team'}}),
        LEAGUE_CONFIG,
    )
    obj.sync_dims()

    _, teams = next(t for t in reversed(db.upserts) if t[0] == 'dim_team')
    assert all(name.startswith('team_') for name in teams['team_name'])
    # Untouched columns still go out as themselves.
    assert set(teams['platform_team_id']) == {'t1', 't2', 't3'}
    assert set(obj._dim('team')['team_name']) == {'Nate FC', 'Abe FC'}


# ---------------------------------------------------------------------------
# where the reversal maps live
# ---------------------------------------------------------------------------

def test_anon_maps_default_under_the_working_directory(db, tmp_path):
    obj = EloSQL({'conn_dict': VALID_CONN, 'anonymizer': True},
                 LEAGUE_CONFIG, FakeConn(), tmp_path)
    assert obj.anon_loc == tmp_path / 'anon'

    obj.sync_dims()
    assert (tmp_path / 'anon' / 'anon_manager.json').exists()
    # One file per dim: anonymize() rewrites its whole map per call, so the
    # platform identity cannot share dim_manager's.
    assert (tmp_path / 'anon' / 'anon_manager_platform.json').exists()


def test_relative_anon_loc_resolves_against_the_working_directory(db, tmp_path):
    obj = EloSQL({'conn_dict': VALID_CONN, 'anonymizer': True, 'anon_loc': 'secrets'},
                 LEAGUE_CONFIG, FakeConn(), tmp_path)
    assert obj.anon_loc == tmp_path / 'secrets'


def test_absolute_anon_loc_wins(db, tmp_path):
    elsewhere = tmp_path / 'elsewhere'
    obj = EloSQL({'conn_dict': VALID_CONN, 'anonymizer': True,
                  'anon_loc': str(elsewhere)},
                 LEAGUE_CONFIG, FakeConn(), tmp_path)
    assert obj.anon_loc == elsewhere


def test_without_a_working_directory_maps_stay_relative(db):
    obj = make_elosql(db, {'conn_dict': VALID_CONN, 'anonymizer': True}, LEAGUE_CONFIG)
    assert obj.anon_loc == Path('anon')


def test_elo_system_points_the_maps_at_resources(db, tmp_path, monkeypatch):
    from elo_system.elo_system import EloSystem

    monkeypatch.chdir(tmp_path)
    es = EloSystem()
    es.set_elo_sql({'conn_dict': VALID_CONN, 'anonymizer': True}, FakeConn())

    assert es.elo_sql.anon_loc == tmp_path / 'resources' / 'anon'


# ---------------------------------------------------------------------------
# dim write order
# ---------------------------------------------------------------------------

def test_push_dims_writes_parents_before_children(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()

    order = [table for table, _ in db.upserts]
    # dim_team has FKs into dim_manager and dim_online_league; dim_online_league
    # into dim_league, and dim_manager_platform into dim_manager. ELO_DIMS is a
    # set, so this cannot be left to iteration.
    assert order.index('dim_league') < order.index('dim_online_league')
    assert order.index('dim_online_league') < order.index('dim_team')
    assert order.index('dim_manager') < order.index('dim_team')
    assert order.index('dim_manager') < order.index('dim_manager_platform')


def test_the_bridge_lands_after_the_dims_it_points_at(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()

    # mvw_fact_league_managers has FKs into dim_league and dim_manager, and it is
    # replaced rather than upserted -- so it has to come after both are written.
    assert [table for table, _ in db.replaces] == ['mvw_fact_league_managers']
    assert {'dim_league', 'dim_manager'} <= {table for table, _ in db.upserts}


def test_push_dims_reorders_an_explicit_subset(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()
    db.upserts.clear()

    obj.push_dims({'team', 'manager_platform', 'manager'})
    assert [table for table, _ in db.upserts] == [
        'dim_manager', 'dim_manager_platform', 'dim_team']


# ---------------------------------------------------------------------------
# league name
# ---------------------------------------------------------------------------

def _named_config(name):
    config = {k: v for k, v in LEAGUE_CONFIG.items() if k != 'seasons'}
    config['seasons'] = {
        year: dict(season, league_name=name)
        for year, season in LEAGUE_CONFIG['seasons'].items()
    }
    return config


def test_league_name_comes_from_the_scraped_season(db):
    obj = make_elosql(db, league_config=_named_config("Mao's Macho Mandarins"))
    obj.sync_dims()

    assert obj.league_name == "Mao's Macho Mandarins"
    assert obj._dim('league')['league_name'].iloc[0] == "Mao's Macho Mandarins"


def test_league_name_falls_back_to_a_placeholder(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()
    # Nothing scraped a name, so the row still gets a usable one.
    assert obj.league_name
    assert obj._dim('league')['league_name'].iloc[0] == obj.league_name


def test_a_scraped_name_replaces_an_earlier_placeholder(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()
    placeholder = obj.league_name

    obj.set_league_config(_named_config("Mao's Macho Mandarins"))
    obj.sync_dims()

    assert obj.league_name == "Mao's Macho Mandarins"
    league = obj._dim('league')
    assert len(league) == 1
    assert league['league_name'].iloc[0] == "Mao's Macho Mandarins"
    assert placeholder not in set(league['league_name'])


def test_a_missing_name_never_blanks_a_stored_one(db):
    obj = make_elosql(db, league_config=_named_config("Mao's Macho Mandarins"))
    obj.sync_dims()

    obj.set_league_config(LEAGUE_CONFIG)  # no league_name anywhere
    obj.sync_dims()
    assert obj._dim('league')['league_name'].iloc[0] == "Mao's Macho Mandarins"


# ---------------------------------------------------------------------------
# departed managers in the dynasty facts
# ---------------------------------------------------------------------------

DEPARTED_CONFIG = {
    'platform': 'fantrax',
    'league_type': 'nba',
    'current_sports_year': 2025,
    'seasons': {
        # Lengths put dynasty weeks 0-1 in 2024 and week 2 in 2025
        # (_dynasty_week_years allots current_season_length + 1 per season).
        2024: {
            'league_id': 'lg2024',
            'current_season_length': 1,
            'league_members': {
                'Nate': {'team_id': 't1', 'curr_name': 'Nate FC',
                         'short_name': 'NAT', 'is_commish': True},
                'gone': {'team_id': 't2', 'curr_name': 'Gone FC',
                         'short_name': 'GON', 'is_commish': False},
            },
        },
        2025: {
            'league_id': 'lg2025',
            'current_season_length': 0,
            # 'gone' has left; only Nate is on the roster.
            'league_members': {
                'Nate': {'team_id': 't1', 'curr_name': 'Nate FC',
                         'short_name': 'NAT', 'is_commish': True},
            },
        },
    },
}


def _departed_dynasty():
    """A dynasty frame whose weeks span both seasons, for two members."""
    return pd.DataFrame(
        {'week_0': [1500.0, 1500.0], 'week_1': [1520.0, 1480.0],
         'week_2': [1512.0, 1488.0]},
        index=['Nate', 'gone'],
    )


def test_dynasty_row_for_a_departed_manager_carries_no_team(db):
    obj = make_elosql(db, league_config=DEPARTED_CONFIG)
    obj.publish({'config': DEPARTED_CONFIG, 'dynasty_elo': _departed_dynasty()})

    written = [f for t, f in db.replaces if t == 'fact_dynasty_elos'][-1]
    managers = obj._dim('manager_platform').set_index('platform_user_id')['manager_id']
    gone = written[written['manager_id'] == managers['gone']]

    # 'gone' played 2024 (weeks 0-1) but not 2025 (week 2).
    assert not gone.empty
    played = gone[gone['week'] < 2]
    after = gone[gone['week'] == 2]
    assert played['team_id'].notna().all(), 'a season they played must name their team'
    assert after['team_id'].isna().all() or (after['team_id'].to_numpy() == None).all(), \
        'a season they were not in must carry no team id'


def test_departed_manager_rating_survives_the_dynasty_round_trip(db):
    obj = make_elosql(db, league_config=DEPARTED_CONFIG)
    dynasty = _departed_dynasty()
    obj.publish({'config': DEPARTED_CONFIG, 'dynasty_elo': dynasty})

    loaded = obj.load_frames('dynasty_elo')['dynasty_elo']
    # Every cell comes back, including the weeks after 'gone' left -- those
    # ratings are what keeps the league average at 1500.
    aligned = loaded.reindex(index=dynasty.index, columns=dynasty.columns)
    assert int(aligned.notna().sum().sum()) == int(dynasty.notna().sum().sum())
    pd.testing.assert_frame_equal(aligned.sort_index(), dynasty.sort_index(),
                                  check_names=False)


def test_seasonal_facts_still_require_a_team_that_season(db):
    # Only the dynasty facts relax the team join; a seasonal rating belongs to
    # a team inside one season and must still resolve to one.
    obj = make_elosql(db, league_config=DEPARTED_CONFIG)
    obj.publish({'config': DEPARTED_CONFIG,
                 'seasonal_elo': {2025: _frame(['Nate', 'gone'], 2)}})

    written = [f for t, f in db.replaces if t == 'fact_elos'][-1]
    assert written['team_id'].notna().all()
    managers = obj._dim('manager_platform').set_index('platform_user_id')['manager_id']
    # 'gone' is not on the 2025 roster, so has no 2025 seasonal rating.
    assert managers.get('gone') not in set(written['manager_id'])


# ---------------------------------------------------------------------------
# several leagues on the same platform
# ---------------------------------------------------------------------------

def _nba_league(platform_league_id, members):
    return {
        'platform': 'fantrax', 'league_type': 'nba', 'current_sports_year': 2025,
        'seasons': {2025: {'league_id': platform_league_id,
                           'current_season_length': 1,
                           'league_members': members}},
    }


LEAGUE_A = _nba_league('abc123', {
    'nate': {'team_id': 't1', 'curr_name': 'A One', 'is_commish': True},
    'abe': {'team_id': 't2', 'curr_name': 'A Two', 'is_commish': False},
})
# 'nate' plays in both; the platform team id t1 is reused, deliberately.
LEAGUE_B = _nba_league('xyz789', {
    'nate': {'team_id': 't1', 'curr_name': 'B One', 'is_commish': False},
    'zoe': {'team_id': 't9', 'curr_name': 'B Two', 'is_commish': True},
})


def _publish_both(db):
    out = []
    for conf, members in ((LEAGUE_A, ['nate', 'abe']), (LEAGUE_B, ['nate', 'zoe'])):
        obj = make_elosql(db, league_config=conf)
        obj.publish({'config': conf, 'seasonal_elo': {2025: _frame(members, 2)}})
        out.append(obj)
    return out


def test_two_leagues_on_one_platform_get_their_own_league_row(db):
    a, b = _publish_both(db)
    assert a.get_lid() != b.get_lid()
    assert len(db.tables['dim_league']) == 2


def test_two_leagues_get_their_own_online_league_per_season(db):
    _publish_both(db)
    online = db.tables['dim_online_league']
    assert len(online) == 2
    assert set(online['platform_league_id']) == {'abc123', 'xyz789'}
    assert online['league_id'].nunique() == 2
    assert set(online['platform']) == {'fantrax'}


def test_a_manager_in_two_leagues_is_one_manager(db):
    # A member is an account on a platform, so the same account in two leagues is
    # the same person: one dim_manager_platform row, one dim_manager behind it.
    _publish_both(db)
    accounts = db.tables['dim_manager_platform']
    assert sorted(accounts['platform_user_id']) == ['abe', 'nate', 'zoe']
    assert accounts['manager_id'].nunique() == 3
    assert len(db.tables['dim_manager']) == 3


def test_the_bridge_records_a_shared_manager_under_both_leagues(db):
    a, b = _publish_both(db)
    accounts = db.tables['dim_manager_platform'].set_index(
        'platform_user_id')['manager_id']
    bridge = db.tables['mvw_fact_league_managers']

    by_league = {
        league_id: set(rows['manager_id'])
        for league_id, rows in bridge.groupby('league_id')
    }
    assert by_league == {
        a.get_lid(): {accounts['nate'], accounts['abe']},
        b.get_lid(): {accounts['nate'], accounts['zoe']},
    }
    # One person, two leagues -- and each league lists only its own members.
    assert accounts['abe'] not in by_league[b.get_lid()]


def test_a_manager_in_two_leagues_has_a_team_in_each(db):
    _publish_both(db)
    managers = db.tables['dim_manager_platform'].set_index(
        'platform_user_id')['manager_id']
    teams = db.tables['dim_team']
    nate = teams[teams['manager_id'] == managers['nate']]
    # One team per league, even though both reuse the platform team id 't1'.
    assert len(nate) == 2
    assert nate['online_league_id'].nunique() == 2
    assert set(nate['platform_team_id']) == {'t1'}
    assert nate['team_id'].nunique() == 2


def test_facts_stay_scoped_to_their_own_league(db):
    _publish_both(db)
    facts = db.tables['fact_elos']
    teams = db.tables['dim_team'].set_index('team_id')['online_league_id']
    # Every fact row sits under the online league its team belongs to.
    assert (facts['team_id'].map(teams) == facts['online_league_id']).all()
    assert facts['online_league_id'].nunique() == 2


# ---------------------------------------------------------------------------
# one person across several servers and platforms
# ---------------------------------------------------------------------------

def _server_league(platform, platform_league_id, server_id, members):
    """A league on its own Discord server, so the two share nothing but people."""
    return {
        'platform': platform, 'league_type': 'nba', 'current_sports_year': 2025,
        'discord_server_id': server_id,
        'seasons': {2025: {'league_id': platform_league_id,
                           'current_season_length': 1,
                           'league_members': members}},
    }


def test_a_manager_on_two_servers_is_still_one_person(db):
    # The point of splitting dim_manager from dim_manager_platform: 'nate' plays
    # the same Sleeper account in two leagues on two different Discord servers,
    # and that is one person, filed once.
    here = _server_league('sleeper', 'lg_here', 111, {
        'u_nate': {'team_id': 't1', 'curr_name': 'Here One', 'is_commish': True},
    })
    there = _server_league('sleeper', 'lg_there', 222, {
        'u_nate': {'team_id': 't4', 'curr_name': 'There One', 'is_commish': False},
    })
    lids = []
    for conf in (here, there):
        obj = make_elosql(db, league_config=conf)
        obj.publish({'config': conf, 'seasonal_elo': {2025: _frame(['u_nate'], 1)}})
        lids.append(obj.get_lid())

    assert len(db.tables['dim_manager']) == 1
    assert len(db.tables['dim_manager_platform']) == 1
    # Two leagues, two servers, two teams -- one manager under both.
    assert set(db.tables['dim_league']['discord_server_id']) == {111, 222}
    assert len(db.tables['dim_team']) == 2
    bridge = db.tables['mvw_fact_league_managers']
    assert sorted(bridge['league_id']) == sorted(lids)
    assert bridge['manager_id'].nunique() == 1


def test_the_same_member_key_on_two_platforms_is_two_people(db):
    # platform_user_id is only unique within a platform, so an identical key on
    # another one is somebody else -- which is why the DB keys the account on
    # (platform, platform_user_id) rather than the id alone.
    members = {'ambiguous': {'team_id': 't1', 'curr_name': 'One',
                             'is_commish': True}}
    for platform in ('fantrax', 'sleeper'):
        conf = _server_league(platform, 'lg_' + platform, 999, members)
        obj = make_elosql(db, league_config=conf)
        obj.sync_dims()

    accounts = db.tables['dim_manager_platform']
    assert len(accounts) == 2
    assert set(accounts['platform']) == {'fantrax', 'sleeper'}
    assert accounts['manager_id'].nunique() == 2


def test_a_manager_who_moved_platforms_with_the_league_keeps_one_person(db):
    # One league, two seasons, two platforms: the accounts differ but each is
    # resolved against its own season, and the ratings still round trip.
    moved = {
        'platform': 'fantrax', 'league_type': 'nba', 'current_sports_year': 2025,
        'seasons': {
            2024: {'league_id': 'ft2024', 'current_season_length': 1,
                   'league_members': {
                       'ft_nate': {'team_id': 't1', 'curr_name': 'Old',
                                   'is_commish': True}}},
            2025: {'league_id': 'sl2025', 'current_season_length': 1,
                   'platform': 'sleeper',
                   'league_members': {
                       'sl_nate': {'team_id': 'r1', 'curr_name': 'New',
                                   'is_commish': True}}},
        },
    }
    obj = make_elosql(db, league_config=moved)
    obj.publish({'config': moved, 'seasonal_elo': {
        2024: _frame(['ft_nate'], 1),
        2025: _frame(['sl_nate'], 1),
    }})

    assert len(obj._dim('league')) == 1
    accounts = obj._dim('manager_platform')
    assert dict(zip(accounts['platform_user_id'], accounts['platform'])) == {
        'ft_nate': 'fantrax', 'sl_nate': 'sleeper'}
    # Each season's rating resolved through the platform that season was on.
    loaded = obj.load_frames('seasonal_elo')['seasonal_elo']
    assert list(loaded[2024].index) == ['ft_nate']
    assert list(loaded[2025].index) == ['sl_nate']


# ---------------------------------------------------------------------------
# the account's display name
# ---------------------------------------------------------------------------

def _handle_config(handle=None):
    """A Sleeper-shaped season: the member key is an opaque account id, and the
    name it shows under is something else entirely."""
    info = {'team_id': 'r1', 'curr_name': 'Team Of Nightmares',
            'short_name': 'GeneralH', 'is_commish': True}
    if handle is not None:
        info['display_name'] = handle
    return {
        'platform': 'sleeper', 'current_sports_year': 2025,
        'seasons': {2025: {'league_id': 'sl1', 'current_season_length': 1,
                           'league_members': {'738089321269194752': info}}},
    }


def test_the_scraped_account_handle_lands_in_display_name(db):
    obj = make_elosql(db, league_config=_handle_config('GeneralH'))
    obj.sync_dims()

    account = obj._dim('manager_platform').iloc[0]
    assert account['platform_user_id'] == '738089321269194752'
    assert account['display_name'] == 'GeneralH'


def test_display_name_falls_back_to_the_account_id(db):
    # Nothing scraped a handle, so the column still names something usable
    # rather than going in empty.
    obj = make_elosql(db, league_config=_handle_config())
    obj.sync_dims()

    account = obj._dim('manager_platform').iloc[0]
    assert account['display_name'] == '738089321269194752'


def test_a_renamed_account_is_refreshed_in_place(db):
    obj = make_elosql(db, league_config=_handle_config('GeneralH'))
    obj.sync_dims()
    manager_id = obj.resolve_manager_id('738089321269194752')

    obj.set_league_config(_handle_config('GeneralHospital'))
    obj.sync_dims()

    accounts = obj._dim('manager_platform')
    assert len(accounts) == 1
    assert accounts['display_name'].iloc[0] == 'GeneralHospital'
    # A rename is not a new person.
    assert obj.resolve_manager_id('738089321269194752') == manager_id


def test_a_missing_handle_never_blanks_a_stored_one(db):
    obj = make_elosql(db, league_config=_handle_config('GeneralH'))
    obj.sync_dims()

    obj.set_league_config(_handle_config())   # mid-scrape, nothing reported
    obj.sync_dims()
    assert obj._dim('manager_platform')['display_name'].iloc[0] == 'GeneralH'


def test_facts_denormalise_the_handle_not_the_account_id(db):
    obj = make_elosql(db, league_config=_handle_config('GeneralH'))
    obj.publish({'config': _handle_config('GeneralH'),
                 'seasonal_elo': {2025: _frame(['738089321269194752'], 2)}})

    _, facts = _fact_writes(db)[-1]
    assert set(facts['manager_name']) == {'GeneralH'}
    # The frame still comes back indexed by the account id, which is the member.
    loaded = obj.load_frames('seasonal_elo')['seasonal_elo'][2025]
    assert list(loaded.index) == ['738089321269194752']


def test_a_league_with_no_server_id_gets_a_generated_one(db):
    # discord_server_id is seeded like dim_manager's Discord-owned columns: the
    # row goes in complete, and the Discord side replaces it with the real id.
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()

    stored = obj._dim('league')['discord_server_id']
    assert stored.notna().all()
    assert all(isinstance(int(server_id), int) for server_id in stored)


def test_a_league_row_left_without_a_server_id_is_backfilled(db):
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()

    # Stand in for a row written before the column was seeded.
    obj.dim_tables['dim_league']['discord_server_id'] = None
    obj.sync_dims()

    assert obj._dim('league')['discord_server_id'].notna().all()


def test_a_stored_server_id_survives_a_resync(db):
    # Once the Discord side has set the real id, no later sync may replace it.
    obj = make_elosql(db, league_config=LEAGUE_CONFIG)
    obj.sync_dims()
    obj.dim_tables['dim_league']['discord_server_id'] = 1251485125330982096

    obj.sync_dims()
    assert list(obj._dim('league')['discord_server_id']) == [1251485125330982096]


def test_a_configured_server_id_is_written_through(db):
    obj = make_elosql(db, league_config=dict(LEAGUE_CONFIG,
                                             discord_server_id=1251485125330982096))
    obj.sync_dims()

    assert list(obj._dim('league')['discord_server_id']) == [1251485125330982096]
