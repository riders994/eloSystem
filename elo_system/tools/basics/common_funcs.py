import pandas as pd
import numpy as np
import json
import yaml


from pathlib import Path


def elo_share(elo):
    return np.power(10, elo / 400)


def elo_expected(r1, r2):
    return np.array([r1, r2])/(r1 + r2)


def week_formatter(week: str) -> int | range:
    s = week.split(':')
    if len(s) - 1:
        return range(int(s[0]), int(s[-1]) + 1)
    else:
        return int(week)


def score_elo_calc(player_1, player_2, k=60, proba=False):
    share_a = elo_share(player_1[0])
    share_b = elo_share(player_2[0])

    expected = elo_expected(share_a, share_b)

    if proba:
        return (player_1[0] + k * (player_1[1] - expected[0]), player_2[0] + k * (player_2[1] - expected[1])),\
               (expected[0], expected[1])
    return [player_1[0] + k * (player_1[1] - expected[0]), player_2[0] + k * (player_2[1] - expected[1])]


def bin_elo_calc(player_1, player_2, k=60, proba=False):
    r1 = player_1[0]
    r2 = player_2[0]
    score1 = player_1[1]
    score2 = player_2[1]
    share_a, share_b = elo_share(r1) , elo_share(r2)

    if score1 == 0.5:
        score1 = 0
    if score2 == 0.5:
        score2 = 0
    score1 = round(score1)
    score2 = round(score2)

    expected = elo_expected(share_a, share_b)

    if proba:
        return (r1 + k * (score1 - expected[0]), r2 + k * (score2 - expected[1])), (expected[0], expected[1])
    return [r1 + k * (score1 - expected[0]), r2 + k * (score2 - expected[1])]


def trin_elo_calc(player_1, player_2, k=60, proba=False):
    r1 = player_1[0]
    r2 = player_2[0]
    score1 = player_1[1]
    score2 = player_2[1]
    share_a, share_b = elo_share(r1), elo_share(r2)

    if str(score1) != '0.5':
        score1 = round(score1)
        score2 = round(score2)

    expected = elo_expected(share_a, share_b)

    if proba:
        return (r1 + k * (score1 - expected[0]), r2 + k * (score2 - expected[1])), (expected[0], expected[1])
    return [r1 + k * (score1 - expected[0]), r2 + k * (score2 - expected[1])]


def median_elo_calc(player_scores, player_elos, k=60, proba=False) -> pd.Series:
    median_elo = np.array(len(player_scores)*[1500])
    normed_scores = (player_scores - min(player_scores)) / (max(player_scores) - min(player_scores))
    median = np.median(normed_scores)

    winners = ((np.greater(normed_scores, median).astype(int) - 0.5) * 2).astype(int)

    if proba:
        pass
    return player_elos + (k * (normed_scores - median) * np.log(1 + winners * (normed_scores - median)) * 2.2 /
            (2.2 + winners * (player_elos - median_elo) / 1000))

def str_to_path(filepath: str) -> Path:
    return Path(filepath).expanduser().resolve()

def load_config_file(file_path: Path) -> dict:
    str_path = str(file_path)
    if '.json' in str_path:
        with open(file_path, 'r') as f:
            config = json.load(f)
    elif '.yml' in str_path:
        with open(file_path, 'r') as f:
            config = yaml.safe_load(f)
    return config

def write_config_file(file_path: Path, config: dict) -> None:
    str_path = str(file_path)
    if '.json' in str_path:
        with open(file_path, 'w') as f:
            json.dump(config, f)
    elif '.yml' in str_path:
        with open(file_path, 'w') as f:
            yaml.dump(config, f)