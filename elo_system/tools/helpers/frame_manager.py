import pandas as pd

from typing import Any

from ..basics import LeagueBase, WEEK_STR
from .calculator import offseason_adjustment


class FrameManager(LeagueBase):
    level = 'seasons'

    def __init__(self, config: dict[str, Any]):
        self.seasonal_elo = dict()
        self.dynasty_elo = None

        self.roto_history = dict()

        self.is_dynasty = config.get("is_dynasty", False)
        self.is_roto = config.get("is_roto", False)
        self.osa_factor = config.get("osa_factor", 0.4)

        super().__init__(config)

        self.member_dict = {k: v.get('league_members') for k, v in self.config.items()}

    @staticmethod
    def _validate_load_frame(frame) -> bool:
        s = frame.shape
        if s[0] % 2 == 1:
            return False
        for i in range(s[1]):
            if frame.get(WEEK_STR.format(i)) is None:
                return False
        return True

    def validate_season(self, season: int) -> bool:
        w = self.config[season]['current_season_length']
        if self.is_roto:
            frame = self.roto_history[season]
        else:
            frame = self.seasonal_elo[season]
        return frame.get(WEEK_STR.format(w)) is not None

    def _check_full_seasons(self) -> bool:
        if self.is_dynasty:
            return False
        return True

    def _check_consecutive_seasons(self) -> bool:
        s = min(list(self.config.keys()))
        l = len(list(self.config.keys()))
        for i in range(s, s + l):
            if self.config.get(i) is None:
                return False
        return True

    def can_dynasty(self) -> bool:
        if not self._check_consecutive_seasons():
            return False
        if not self._check_full_seasons():
            return False
        return True

    def _load_frame(self, destination: str, frame: pd.DataFrame, year: int | None = None) -> None:
        if self._validate_load_frame(frame):
            if destination == 'dynasty_elo':
                self.dynasty_elo = frame
            elif destination == 'roto_history':
                self.roto_history.update({year: frame})
            elif destination == 'seasonal_elo':
                self.seasonal_elo.update({year: frame})

    def load_frames(self, frames: dict[str | int, Any], label: str | None = None) -> None:
        if label is None:
            for k, v in frames.items():
                if k == 'dynasty_elo':
                    self._load_frame(k, v)
                if k in {'roto_history', 'seasonal_elo'}:
                    for year, frame in v.items():
                        self._load_frame(k, frame, year)
        else:
            for k, v in frames.items():
                self._load_frame(label, v, k)


    def get_current_sports_year(self):
        return max(list(self.config.keys()))

    def _reset_is_dynasty(self) -> None:
        if self.is_dynasty:
            self.is_dynasty = False
        else:
            self.is_dynasty = True

    def set_is_dynasty(self, to: bool | None = None) -> None:
        if to is None:
            self._reset_is_dynasty()
        else:
            self.is_dynasty = to

    def _gen_dynasty_elo(self, season: int | None = None, overwrite: bool = True) -> None:
        if self.dynasty_elo is None:
            self.dynasty_elo = self.seasonal_elo[season].copy()
        else:
            dynasty_week = self.config[season]['dynasty_start_week']
            if not overwrite:
                if self.dynasty_elo.get(WEEK_STR.format(dynasty_week)) is not None:
                    return None
            latest_col = WEEK_STR.format(dynasty_week - 1)
            new_col = WEEK_STR.format(dynasty_week)

            next_ids = list(self.config[season]['league_members'].keys())
            new_ids = [tid for tid in next_ids if tid not in self.dynasty_elo.index]

            df = self.dynasty_elo.reindex(self.dynasty_elo.index.union(new_ids, sort=False))

            ratings = df.loc[next_ids, latest_col].fillna(1500.0)
            updated = offseason_adjustment(ratings, self.osa_factor)

            df[new_col] = df[latest_col]
            df.loc[next_ids, new_col] = updated
            self.dynasty_elo = df
        return None

    def _gen_elo(self, season: int | None = None, overwrite: bool = True) -> None:
        if season is None:
            for s in self.config.keys():
                self._gen_elo(s, overwrite)
            return None

        if season not in self.config:
            raise KeyError('Unknown season: {}'.format(season))

        if overwrite or self.seasonal_elo.get(season) is None:
            players = self.member_dict[season]
            self.seasonal_elo[season] = pd.DataFrame(
                {'week_0': [1500] * len(players)}, index=list(players.keys())
            )

        if self.is_dynasty:
            self._gen_dynasty_elo(season, overwrite)

        return None

    def _set_dynasty_elo(self, frame: pd.DataFrame, season: int | None = None) -> None:
        if season is None:
            self.dynasty_elo = frame

    def _set_elo(self, frame: pd.DataFrame, season: int | None = None) -> None:
        self.seasonal_elo[season] = frame
        if self.is_dynasty:
            self._set_dynasty_elo(frame, season)

    def _gen_roto(self, season: int | None = None, overwrite: bool = True) -> None:
        if season is None:
            for s in self.config.keys():
                self._gen_roto(s, overwrite)
            return None

        if season not in self.config:
            raise KeyError('Unknown season: {}'.format(season))

        if not overwrite:
            if self.roto_history.get(season) is not None:
                return None
        self.roto_history[season] = pd.DataFrame(index=list(self.member_dict[season].keys()))
        return None

    def _set_roto(self, frame: pd.DataFrame, season: int | None = None) -> None:
        if season is None:
            self.roto_history[self.current_sports_year] = frame
        else:
            self.roto_history[season] = frame

    def generate(self, season: int | None = None, overwrite: bool = False) -> None:
        if season is None:
            season = self.current_sports_year
            if season is None:
                season = self.get_current_sports_year()
        if self.is_roto:
            self._gen_roto(season, overwrite)
        self._gen_elo(season, overwrite)

    def _publish(self) -> dict[str, Any]:
        payload = super()._publish()
        if self.is_dynasty:
            payload['dynasty_elo'] = self.dynasty_elo
        if self.is_roto:
            payload['roto_history'] = self.roto_history
        payload['seasonal_elo'] = self.seasonal_elo
        return payload