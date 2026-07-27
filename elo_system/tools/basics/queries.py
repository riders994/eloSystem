LOAD_ELO = '''SELECT
    team_id
  , week
  , elo AS rating
FROM {schema}.{table}
WHERE {scope_col} = {scope_id}
'''

LOAD_ROTO = '''SELECT
    team_id
  , week
  , score AS rating
FROM {schema}.{table}
WHERE {scope_col} = {scope_id}
'''

LOAD_QUERIES = {
    'elo': LOAD_ELO,
    'score': LOAD_ROTO,
}
