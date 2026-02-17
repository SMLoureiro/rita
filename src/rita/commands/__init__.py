"""CLI command groups for RITA."""

from rita.commands.auth import auth
from rita.commands.chart import chart, schema
from rita.commands.config_cmd import config
from rita.commands.init_cmd import init
from rita.commands.lore import lore
from rita.commands.render import render
from rita.commands.test_cmd import test
from rita.commands.values import values

__all__ = [
    "auth",
    "chart",
    "config",
    "init",
    "lore",
    "render",
    "schema",
    "test",
    "values",
]
