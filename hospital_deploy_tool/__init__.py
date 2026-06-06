"""Hospital deployment tool package."""

__all__ = ["run"]


def __getattr__(name: str):
    if name == "run":
        from .main import run

        return run
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
