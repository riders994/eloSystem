# NOTE: Vendored copy of riders994/FantraxAPI (fork of meisnate12/FantraxAPI).
# Pinned to commit 4f98fa6 (master, v1.0.1). Upstream already uses relative
# imports, so the package works unmodified under ``elo_system._vendor.fantraxapi``;
# the only local change is the hardcoded ``__version__`` below (importlib.metadata
# cannot see a vendored package). See ./LICENSE (MIT).
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
