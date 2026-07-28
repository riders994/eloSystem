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
    'manager_platform',
    'online_league',
    'team',
}

# Write order for the dims: dim_team has foreign keys into dim_manager and
# dim_online_league, dim_manager_platform into dim_manager, and
# dim_online_league into dim_league, so parents have to land first. ELO_DIMS is
# a set, and its iteration order would not respect that.
ELO_DIM_ORDER = (
    'league',
    'online_league',
    'manager',
    'manager_platform',
    'team',
)

# The key columns of each dim, and so the conflict target its upsert matches on.
# A single column is a surrogate id minted on this side, and the cached frame is
# indexed by it. Several columns are a natural key the platform supplies, which
# is not ours to generate -- those frames are held unindexed.
ELO_DIM_KEYS = {
    'league': ('league_id',),
    'manager': ('manager_id',),
    'manager_platform': ('manager_id', 'platform'),
    'online_league': ('online_league_id',),
    'team': ('team_id',),
}

# dim_manager is the person -- the Discord side's row, one per human. Which
# account that person plays under on each platform is dim_manager_platform,
# keyed by (manager_id, platform) with a uniqueness constraint on
# (platform, platform_user_id): one account per platform per person, and one
# person per account. That split is what lets a single manager turn up in
# several leagues, on several servers, under a different account on each.
ELO_DIM_COLS = {
    'league': ['league_id', 'discord_server_id', 'league_name'],
    'manager': ['manager_id', 'player_name', 'discord_id'],
    'manager_platform': ['manager_id', 'platform', 'platform_user_id', 'display_name'],
    'online_league': ['online_league_id', 'league_id', 'platform', 'platform_league_id', 'league_year'],
    'team': ['team_id', 'team_name', 'manager_id', 'online_league_id', 'platform_team_id', 'league_year', 'is_commish', 'is_champion', 'comanager_id', 'place_finish'],
}

# Which leagues a manager belongs to is a many-to-many, so it lives in its own
# bridge table rather than on either dim. The mvw_ prefix marks it as derived --
# every row is implied by the teams a manager owns -- but it is a real table, so
# the publish maintains it, scoped by league like the fact tables.
LEAGUE_MANAGER_SPEC = {
    'table': 'mvw_fact_league_managers',
    'scope': 'league_id',
    'columns': ['league_id', 'manager_id'],
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
# in dim_manager_platform as in the fact tables. Override or extend via the SQL
# config's anon_columns.
#
# The platform identity is two separate value spaces and so two categories: the
# account id the frames are keyed by, and the name that account shows under.
# Tokenising both is what keeps the DB clear of either -- on Fantrax the account
# id *is* the owner's name.
ANON_COLS = {
    'manager': {
        'player_name': 'person',
    },
    'manager_platform': {
        'platform_user_id': 'account',
        'display_name': 'manager',
    },
}

# The dim holding a person's identity on one platform: platform_user_id is the
# member key the rating frames are indexed by, and display_name is what that
# account shows as.
ANON_MEMBER_DIM = 'manager_platform'

# The column of that dim the fact tables' denormalised manager_name copies, and
# so the one whose tokens it has to reuse.
ANON_FACT_NAME_COL = 'display_name'

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
        'table': 'fact_elos',
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
