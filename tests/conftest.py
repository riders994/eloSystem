"""Shared pytest configuration for the elo_system test suite.

Run from the repo root with: .venv/bin/python -m pytest
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
