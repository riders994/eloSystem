from unittest import (
    TestCase,
    main,
)

from elo_system.tools import calculator


class TestSleeperScraper(TestCase):
    def setUp(self) -> None:
        self.scraper = SleeperScraper('1063131085976006656')

    def test_login(self):
        self.assertIsInstance(self.scraper.login(), League)

    def test_get_scoreboard(self):
        self.assertIsInstance(self.scraper.get_scoreboard(1), list)

    def test_process_scoreboard(self):
        pass