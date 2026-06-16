WEEK_STR = 'week_{}'
PLAYOFF_START = 3

ROTO_SCORING = {
    'FG%', 'FT%', '3PTM', 'PTS', 'REB', 'AST', 'ST', 'BLK', 'TO'
}

APPROVED_SQL_FLAVORS = {
    'postgresql',
    None,
}

ELO_DIMS = {
    'league',
    'manager',
    'team',
}

ELO_COLS = [
    'team_id',
    'league_id',
    'league_year',
    'manager_id',
    'manager_name',
    'is_dynasty',
    'week',
    'elo'
]

ROTO_COLS = [
    'team_id',
    'league_id',
    'league_year',
    'manager_id',
    'manager_name',
    'week',
    'roto'
]