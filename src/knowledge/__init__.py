"""Knowledge collection and read interface."""
from .documents import get_documents
from .out_game import get_patch_changes, sync_patch

__all__ = ["get_documents", "get_patch_changes", "sync_patch"]
