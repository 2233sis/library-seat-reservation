"""pytest configuration.

Adds the repo root to sys.path so `from app import ...` works whether
pytest is run from the repo root or any subdirectory (e.g. CI runners
that don't auto-prepend cwd).
"""
import os
import sys

_REPO_ROOT = os.path.abspath(os.path.dirname(__file__))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
