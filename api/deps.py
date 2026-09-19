"""Shared dependencies: DB session, and cached loaders for the same config/data the
scripts read. Caching only avoids re-reading YAML/CSV on every request -- it does not
change what gets computed.
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

import yaml

from planner.db import get_session  # noqa: F401  (re-exported for routers)

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


class _Args:
    elasticity = None
    growth = None
    capacity = None


@lru_cache(maxsize=1)
def get_network_config() -> dict:
    from optimize_network import load_config
    return load_config(_Args())


@lru_cache(maxsize=1)
def get_economics_config() -> dict:
    return yaml.safe_load(open("config/economics.yaml", encoding="utf-8"))


@lru_cache(maxsize=8)
def get_city_inputs(city: str):
    from optimize_network import city_inputs
    return city_inputs(city, get_network_config())
