"""MkDocs hook: regenerate the CLI reference before every build or serve."""

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def on_pre_build(config, **kwargs):
    runpy.run_path(str(ROOT / "scripts/gen-cli-docs"))["generate"](ROOT / "docs/reference")
