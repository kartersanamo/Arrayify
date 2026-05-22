from __future__ import annotations


def bullet_prefix(cli_style: bool) -> str:
    return "- " if cli_style else ""


def sub_bullet_prefix(cli_style: bool) -> str:
    return "  - " if cli_style else "  "
