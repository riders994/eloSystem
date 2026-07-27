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

# Maps each publish destination (the payload keys FrameManager emits) onto the
# fact table it lands in, the column that scopes a publish/load to one league or
# season, and the column the rating itself is stored under.
FACT_SPECS = {
    'dynasty_elo': {
        'table': 'fact_dynasty_elos',
        'scope': 'league_id',
        'value': 'elo',
        'columns': DYNASTY_DB_COLS,
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
