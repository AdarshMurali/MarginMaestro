"""Env-flag validation shared by the adapter factories."""


def choose(name: str, value: str, allowed: tuple[str, ...]) -> str:
    choice = value.strip().lower()
    if choice not in allowed:
        raise ValueError(f"{name} must be one of {allowed}, got {value!r}")
    return choice
