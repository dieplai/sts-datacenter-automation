"""Data Loader application layer."""

__all__ = ["run_data_loader"]


def __getattr__(name: str):
    if name == "run_data_loader":
        from data_loader.application.entrypoints import run_data_loader

        return run_data_loader
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
