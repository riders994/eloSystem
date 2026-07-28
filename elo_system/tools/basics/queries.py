LOAD_ELO = '''SELECT
    {member_col}
  , week
  , elo AS rating
FROM {schema}.{table}
WHERE {scope_col} = {scope_id}
'''

LOAD_ROTO = '''SELECT
    {member_col}
  , week
  , score AS rating
FROM {schema}.{table}
WHERE {scope_col} = {scope_id}
'''

# Keyed by the fact's value column. Which id identifies a row is supplied by
# the caller as member_col: seasonal ratings hang off a season's team, dynasty
# ratings off the manager, who outlives any one season's roster.
LOAD_QUERIES = {
    'elo': LOAD_ELO,
    'score': LOAD_ROTO,
}
