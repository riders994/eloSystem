WEEK_STR = 'week_{}'
PLAYOFF_START = 3

ROTO_COLS = {
    'FG%', 'FT%', '3PTM', 'PTS', 'REB', 'AST', 'ST', 'BLK', 'TO'
}

APPROVED_SQL_FLAVORS = {
    'postgresql',
    None,
}

ELO_DIMS = {
    'league',
    'manager',
    'online_league',
    'team',
}

# Write order for the dims: dim_team has foreign keys into dim_manager and
# dim_online_league, and dim_online_league into dim_league, so parents have to
# land first. ELO_DIMS is a set, and its iteration order would not respect that.
ELO_DIM_ORDER = (
    'league',
    'online_league',
    'manager',
    'team',
)

ELO_DIM_COLS = {
    'league': ['league_id', 'discord_server_id', 'platform', 'league_name'],
    'manager': ['manager_id', 'player_name', 'display_name', 'discord_id', 'is_comanager'],
    'online_league': ['online_league_id', 'league_id', 'platform_league_id', 'league_year'],
    'team': ['team_id', 'team_name', 'manager_id', 'online_league_id', 'platform_team_id', 'league_year', 'is_commish', 'is_champion', 'comanager_id', 'place_finish'],
}

# Fact-table column lists, in the order the tables declare them. Dynasty elos
# hang off the league (they span seasons); seasonal elos and rotos hang off the
# online league (one per season).
RATING_DB_COLS = [
    'team_id',
    'online_league_id',
    'manager_id',
    'manager_name',
    'week',
    'elo'
]

DYNASTY_DB_COLS = [
    'team_id',
    'league_id',
    'manager_id',
    'manager_name',
    'week',
    'elo'
]

ROTO_DB_COLS = [
    'team_id',
    'online_league_id',
    'manager_id',
    'manager_name',
    'week',
    'score'
]

# Which dim columns the anonymizer replaces, and the category each is tokenised
# under -- 'Nate' in a 'manager' category becomes 'manager_0'. Keyed by dim, so
# each dim gets its own reversal map and one anonymize() call per push (the
# function rewrites its whole map file per call, and numbers tokens from zero).
# Columns sharing a category share tokens, which is how a manager reads the same
# in dim_manager as in the fact tables. Override or extend via the SQL config's
# anon_columns.
ANON_COLS = {
    'manager': {
        'display_name': 'manager',
        'player_name': 'person',
    },
}

# The category carrying the member identity: the one the fact tables' denormalised
# manager_name has to agree with.
ANON_MEMBER_COL = 'display_name'

ANON_MAP_FSTR = 'anon_{dim}.json'

# Where the reversal maps go by default, relative to the resources directory.
# They hold the real values, so they belong with the rest of the local data
# rather than wherever the process happened to be started.
DEFAULT_ANON_DIR = 'anon'

# Maps each publish destination (the payload keys FrameManager emits) onto the
# fact table it lands in, the column that scopes a publish/load to one league or
# season, and the column the rating itself is stored under.
FACT_SPECS = {
    'dynasty_elo': {
        'table': 'fact_dynasty_elos',
        'scope': 'league_id',
        'value': 'elo',
        'columns': DYNASTY_DB_COLS,
        # Dynasty ratings outlive any one season's roster, so a row is
        # identified by its manager. A manager who has departed keeps a
        # rating but owns no team in the seasons they were not in.
        'member_key': 'manager_id',
    },
    'seasonal_elo': {
        'table': 'fact_seasonal_elos',
        'scope': 'online_league_id',
        'value': 'elo',
        'columns': RATING_DB_COLS,
    },
    'roto_history': {
        'table': 'fact_rotos',
        'scope': 'online_league_id',
        'value': 'score',
        'columns': ROTO_DB_COLS,
    },
}
