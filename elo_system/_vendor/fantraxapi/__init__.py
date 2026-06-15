# NOTE: Vendored copy of riders994/FantraxAPI (fork of meisnate12/FantraxAPI).
# Pinned to commit ee81bea250024cba670cd0a5a1a1849150dbb38c (@stable, v1.0.1).
# Absolute ``fantraxapi`` imports were rewritten to relative imports so the
# package works under ``elo_system._vendor.fantraxapi``. See ./LICENSE (MIT).
from .exceptions import FantraxException, NotLoggedIn, NotMemberOfLeague, NotTeamInLeague
from .objs import League
from .objs import League as FantraxAPI

__version__ = "1.0.1"
__author__ = "Nathan Taggart"
__credits__ = "meisnate12"
__package_name__ = "fantraxapi"
__project_name__ = "FantraxAPI"
__description__ = "A lightweight Python library for The Fantrax API."
__url__ = "https://github.com/meisnate12/FantraxAPI"
__email__ = "meisnate12@gmail.com"
__license__ = "MIT License"
__all__ = [
    "FantraxAPI",
    "FantraxException",
    "NotLoggedIn",
    "NotMemberOfLeague",
    "NotTeamInLeague",
    "League",
]
