"""Keeps docs/ERRORS.md honest: every error code the API can emit must be documented,
and the docs must not list codes the API no longer emits."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CODE = re.compile(r'"([A-Z][A-Z_]{3,})"')


def emitted_codes() -> set[str]:
    return set(CODE.findall((ROOT / "app" / "api" / "errors.py").read_text(encoding="utf-8")))


def documented_codes() -> set[str]:
    summary = (ROOT / "docs" / "ERRORS.md").read_text(encoding="utf-8").split("## Details by code")[0]
    return set(re.findall(r"\| `([A-Z_]+)` \|", summary))


def test_every_emitted_code_is_documented():
    assert emitted_codes() - documented_codes() == set()


def test_no_stale_codes_in_docs():
    assert documented_codes() - emitted_codes() == set()
