"""Exécuteurs factices utilisés par les tests (non référencés dans le catalogue)."""


def echo(ctx, text: str) -> dict:
    return {"echo": text}


def echo_empty(ctx) -> dict:
    return {"ok": True}
