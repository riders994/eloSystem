from typing import Any
import time

import pandas as pd


class LeagueBase:
    """
    Base class for all Elo System related functionality
    """

    level = None


    def __init__(self, config: dict | None = None) -> None:
        self.config = dict()
        self.loaded = False
        self.current_sports_year = None
        self.league_type = None
        if config:
            self._load_config(config)

    def _load_config(self, config: dict, level: str | None = None) -> None:
        if level is None:
            level = self.level
        if level is None:
            self.config = config
        else:
            self.config = config[level]

    def load_config(self, config: dict) -> None:
        self._load_config(config)

    def update_config(self, new: dict) -> dict[str, Any]:
        self.config.update(new)
        return self.config

    def get_current_sports_year(self):
        t = time.localtime()
        y = t.tm_year
        m = t.tm_mon
        if self.league_type == 'nba':
            if m < 7:
                y -= 1
        if self.league_type == 'nfl':
            if m < 3:
                y -= 1
        return y

    def set_current_sports_year(self, year: int | None) -> None:
        if isinstance(year, int):
            self.current_sports_year = year
        else:
            self.current_sports_year = self.get_current_sports_year()
        return

    def _load(self) -> None:

        self.current_sports_year = self.config.get('current_sports_year', self.get_current_sports_year())

    def _dump(self) -> None:
        self.config.update({
            'current_sports_year': self.current_sports_year,
        })

    def load(self) -> dict[str, Any]:
        self._load()
        self.loaded = True
        return self.config

    def dump(self) -> dict[str, Any]:
        self._dump()
        return self.config

    def _publish(self) -> dict[str, Any]:
        payload = {}
        payload.update({'config': self.config})
        return payload

    def publish(self) -> dict[str, Any]:
        payload = self._publish()
        return payload

class DataBase:

    def __init__(
            self, config: dict
    ) -> None:

        self.seasons_by = config.get('seasons_by', 'year')
        self.dynasty_fstr = config.get('dynasty_fstr', 'dynasty_elo{ext}')
        self.elo_fstr = config.get('elo_fstr', '{num}_season_elo{ext}')
        self.roto_fstr = config.get('roto_fstr', '{num}_roto_elo{ext}')

    def _publish_dynasty_elo(self, frame: pd.DataFrame) -> None:
        pass

    def _publish_indexed_frame(self, destination: str, num: int, frame: pd.DataFrame) -> None:
        pass

    def _publish_indexed_frames(self, frames: dict[str, pd.DataFrame], destination: str) -> None:
        sorted_keys = sorted(frames)
        ranks = {k: i for i, k in enumerate(sorted_keys)}
        for k, v in frames.items():
            if self.seasons_by == 'year':
                self._publish_indexed_frame(destination, k, v)
            elif self.seasons_by == 'order':
                self._publish_indexed_frame(destination, ranks[k], v)

    def publish(self, payload: dict[str, Any]) -> None:
        if (delo := payload.get('dynasty_elo')) is not None:
            self._publish_dynasty_elo(delo)
        if (selo := payload.get('seasonal_elo')) is not None:
            self._publish_indexed_frames(selo, 'seasonal_elo')
        if (roto := payload.get('roto_history')) is not None:
            self._publish_indexed_frames(roto, 'roto_history')
