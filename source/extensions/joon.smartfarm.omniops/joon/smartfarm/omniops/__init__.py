try:
    from .extension import OmniOpsExtension
except ModuleNotFoundError as exc:  # Allows pure model tests outside Kit.
    if exc.name != "omni":
        raise
    OmniOpsExtension = None  # type: ignore[assignment]

__all__ = ["OmniOpsExtension"]
