LOAD_ELO = '''SELECT
    team_id
  , week
  , elo AS rating
FROM {schema}.fact_elos
WHERE is_dynasty = {is_dynasty} AND league_id = {league_id} {year_end}
'''

LOAD_ROTO = '''SELECT
    team_id
  , week
  , score AS rating
FROM {schema}.fact_rotos
WHERE 
         league_id   = {league_id}
    {year_end}
'''