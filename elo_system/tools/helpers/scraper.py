from typing import Any
from abc import ABC, abstractmethod

from ..basics import LeagueBase, PLAYOFF_START
from elo_system._vendor import fantraxapi as ft



class LeagueScraper(LeagueBase, ABC):
    """Abstract base for platform scrapers.

    Holds the shared config/state plumbing (league id, managers, playoff
    start, season length) and defines the interface every platform scraper
    (e.g. FantraxScraper, a future SleeperScraper) must implement.
    """

    def __init__(self, config: dict) -> None:
        self.standings = dict()
        self.league_id = None
        self.league_wrapper = None
        self.managers = dict()
        self.playoff_start = PLAYOFF_START
        self.current_season_length = 0
        super().__init__(config)

    def _load(self) -> None:
        super()._load()
        self.league_id = self.config['league_id']
        self.playoff_start = self.config.get('playoff_start', PLAYOFF_START)

    def _dump(self):
        super()._dump()
        self.config['members'].update(self.managers)
        self.config.update({
            'playoff_start': self.playoff_start
        })

    @abstractmethod
    def login(self):
        """Connect to the platform and fetch the league wrapper + scoreboards."""
        raise NotImplementedError

    @abstractmethod
    def get_members(self) -> dict[str, Any]:
        """Return the canonical member map keyed by stable owner id:
        {owner_id: {'team_id', 'curr_name', 'curr_short', 'commish', 'standing'}}.

        'standing' is the team's current season standing rank (int), or None
        if the team is not present in the standings table."""
        raise NotImplementedError

    @abstractmethod
    def get_league_name(self) -> str | None:
        """Return the league's display name on the platform, if it has one."""
        raise NotImplementedError

    @abstractmethod
    def get_scoreboard(self, week: int):
        """Return the scoreboard object for the given week."""
        raise NotImplementedError

    @abstractmethod
    def get_playoff_start(self) -> int:
        """Return the first playoff week for the loaded season."""
        raise NotImplementedError

    @abstractmethod
    def get_current_season_length(self) -> int:
        """Return the number of scored periods in the season."""
        raise NotImplementedError


class FantraxScraper(LeagueScraper):

    def __init__(self, config: dict) -> None:
        self.current_matchup = None
        self.league_wrapper = None
        self.scoring_periods = None

        super().__init__(config)

    def login(self) -> ft.League:
        self.load()
        self.league_wrapper = ft.League(league_id=self.league_id)
        self.standings = self.league_wrapper.standings()
        self.scoring_periods = self.league_wrapper.scoring_period_results()
        return self.league_wrapper

    def get_current_season_length(self) -> int:
        return len(self.scoring_periods)

    def get_playoff_start(self) -> int:
        if self.loaded:
            i = self.get_current_season_length() + 1
            po = True
            while po:
                i -= 1
                po = self.scoring_periods[i].playoffs
                if i == 1:
                    po = False
            return i + 1
        else:
            return PLAYOFF_START

    def get_league_name(self) -> str | None:
        return getattr(self.league_wrapper, 'name', None)

    def get_members(self) -> dict[str, Any]:
        rank_by_team = {record.team.id: rank for rank, record in self.standings.ranks.items()}
        return {
            team.owners: {
                'team_id': team.id,
                'curr_name': team.name,
                'curr_short': team.short,
                'commish': team.commissioner,
                'standing': rank_by_team.get(team.id, 100),
            } for team in self.league_wrapper.teams
        }

    def get_scoreboard(self, week: int):
        self.current_matchup = None
        self.current_matchup = self.scoring_periods[week]

        return self.current_matchup


class SleeperScraper(LeagueScraper):
    """Scraper for Sleeper (https://sleeper.app) leagues.

    Sleeper's read API is public and unauthenticated, so there is no login
    step as such -- ``login()`` just fetches the league, its rosters and its
    users and caches them, since every other method is a view over those.

    Members are keyed by Sleeper's ``user_id``, which is an account id rather
    than a per-season league id: it survives from one season to the next,
    which is what lets a dynasty span league ids. ``team_id`` is the
    per-season ``roster_id``.
    """

    def __init__(self, config: dict) -> None:
        self.current_matchup = None
        self.league_wrapper = None
        self.rosters = None
        self.users = None

        super().__init__(config)

    @staticmethod
    def _api():
        """Import the optional Sleeper client, lazily.

        ``sleeper`` is an optional extra, so importing it at module scope
        would make it mandatory for Fantrax-only installs.
        """
        try:
            from sleeper.api import (
                get_league,
                get_matchups_for_week,
                get_rosters,
                get_users_in_league,
            )
        except ImportError as e:
            raise ImportError(
                'The Sleeper backend needs the `sleeper` package: '
                'pip install elo-system[sleeper]'
            ) from e
        return get_league, get_matchups_for_week, get_rosters, get_users_in_league

    @staticmethod
    def _roster_points(roster: dict) -> float:
        """Season points-for, which Sleeper splits across two integer fields."""
        settings = roster.get('settings') or dict()
        return settings.get('fpts', 0) + settings.get('fpts_decimal', 0) / 100

    def _rank_rosters(self) -> dict[str, int]:
        """Rank rosters 1..N, keyed by (stringified) roster id.

        Sleeper reports no standing of its own, so this reproduces its default
        ordering: wins, then ties, then points for.
        """
        ordered = sorted(
            self.rosters or [],
            key=lambda r: (
                (r.get('settings') or {}).get('wins', 0),
                (r.get('settings') or {}).get('ties', 0),
                self._roster_points(r),
            ),
            reverse=True,
        )
        return {str(r['roster_id']): rank for rank, r in enumerate(ordered, start=1)}

    def login(self) -> dict:
        get_league, _, get_rosters, get_users_in_league = self._api()
        self.load()
        self.league_wrapper = get_league(league_id=self.league_id)
        self.rosters = get_rosters(league_id=self.league_id)
        self.users = get_users_in_league(league_id=self.league_id)
        self.standings = self._rank_rosters()
        return self.league_wrapper

    def _settings(self) -> dict:
        return (self.league_wrapper or {}).get('settings') or dict()

    def get_current_season_length(self) -> int:
        # last_scored_leg is the last week Sleeper has scored for this league,
        # which is exactly the number of scored periods. It is absent before a
        # season has scored anything.
        #
        # Deliberately not falling back to the neighbouring 'leg': that is the
        # week the league is *on*, not the number it has scored, so it counts
        # the week in progress. A league in its preseason reports leg 1 with
        # nothing played, and rating that week would invent a result.
        return self._settings().get('last_scored_leg') or 0

    def get_playoff_start(self) -> int:
        # Sleeper reports 0 until the schedule is set.
        if self.loaded:
            if (start := self._settings().get('playoff_week_start')):
                return start
        return PLAYOFF_START

    def get_league_name(self) -> str | None:
        return (self.league_wrapper or {}).get('name')

    def get_members(self) -> dict[str, Any]:
        roster_by_owner = {
            r['owner_id']: r for r in (self.rosters or []) if r.get('owner_id')
        }
        members = dict()
        for user in self.users or []:
            roster = roster_by_owner.get(user['user_id'])
            if roster is None:
                # A user with no roster is in the league chat but not playing.
                continue
            team_id = str(roster['roster_id'])
            metadata = user.get('metadata') or dict()
            members[user['user_id']] = {
                'team_id': team_id,
                # Sleeper only stores a team name once the manager sets one.
                'curr_name': metadata.get('team_name') or user['display_name'],
                'curr_short': user['display_name'],
                # is_owner is None rather than False for most members.
                'commish': bool(user.get('is_owner')),
                'standing': self.standings.get(team_id, 100),
            }
        return members

    def get_scoreboard(self, week: int) -> list[dict]:
        _, get_matchups_for_week, _, _ = self._api()
        owner_by_roster = {
            str(r['roster_id']): r.get('owner_id') for r in (self.rosters or [])
        }
        matchups = get_matchups_for_week(league_id=self.league_id, week=week)
        # The formatter is handed the scoreboard alone, so the roster -> owner
        # mapping has to travel with it. Copy rather than mutate the payload.
        self.current_matchup = [
            dict(m, owner_id=owner_by_roster.get(str(m['roster_id'])))
            for m in matchups
        ]
        return self.current_matchup
