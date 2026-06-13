from .helpers import fstr_matcher
from .basics.common_classes import DataBase
from pathlib import Path
from typing import Any

import pandas as pd


class EloSQL(DataBase):
    pass


class EloCSV(DataBase):
    def __init__(
            self, config: dict
            , working_directory: Path
    ) -> None:
        super().__init__(
            config
        )
        self.write_loc = config['write_loc']
        self.read_loc = config.get('read_loc', self.write_loc)
        self.extension = config.get('extension', '.csv')
        self.wd = working_directory
        # Ensure the ratings (output) directory exists before any publish.
        self.out_dir = Path(self.wd, self.write_loc)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        # Input directory for load_frames (defaults to the output directory).
        self.in_dir = Path(self.wd, self.read_loc)

    def _publish_dynasty_elo(self, frame: pd.DataFrame) -> None:
        file_path = Path(self.out_dir, self.dynasty_fstr.format(ext=self.extension))
        frame.to_csv(file_path, index=True)

    def _publish_indexed_frame(self, destination: str, num: int, frame: pd.DataFrame) -> None:
        if destination == 'seasonal_elo':
            final_destination = self.elo_fstr.format(ext=self.extension, num=num)
        elif destination == 'roto_history':
            final_destination = self.roto_fstr.format(ext=self.extension, num=num)
        else:
            raise KeyError('Unknown destination: {}'.format(destination))
        file_path = Path(self.out_dir, final_destination)
        frame.to_csv(file_path, index=True)

    def _read_csv(self, file_path: Path) -> pd.DataFrame:
        # index=True on publish writes the member id index; restore it here.
        return pd.read_csv(file_path, index_col=0)

    def _load_single(self, fstr: str) -> pd.DataFrame | None:
        file_path = Path(self.in_dir, fstr.format(ext=self.extension))
        if not file_path.exists():
            return None
        return self._read_csv(file_path)

    def _load_indexed_set(self, fstr: str) -> dict[Any, pd.DataFrame]:
        # Recovers the per-season key embedded in each filename. Under the
        # default seasons_by='year' that key is the season year; under
        # 'order' it is the ordinal the file was written with.
        glob, matcher = fstr_matcher(fstr, self.extension)
        frames: dict[Any, pd.DataFrame] = {}
        if not self.in_dir.exists():
            return frames
        for file_path in sorted(self.in_dir.glob(glob)):
            m = matcher.match(file_path.name)
            if m is None:
                continue
            num = m.group('num')
            key = int(num) if num.lstrip('-').isdigit() else num
            frames[key] = self._read_csv(file_path)
        return frames

    def load_frames(self, frame_set: str | list[str] | None = None) -> dict[str, Any]:
        loaders = {
            'dynasty_elo': lambda: self._load_single(self.dynasty_fstr),
            'seasonal_elo': lambda: self._load_indexed_set(self.elo_fstr),
            'roto_history': lambda: self._load_indexed_set(self.roto_fstr),
        }
        if frame_set is None:
            frame_set = list(loaders.keys())
        elif isinstance(frame_set, str):
            frame_set = [frame_set]

        out: dict[str, Any] = {}
        for fs in frame_set:
            if fs not in loaders:
                raise KeyError('Unknown frame set: {}'.format(fs))
            loaded = loaders[fs]()
            # Omit sets with no data on disk so FrameManager.load_frames never
            # has to iterate a missing/None entry.
            if loaded is not None and (not isinstance(loaded, dict) or loaded):
                out[fs] = loaded
        return out
