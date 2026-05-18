"""Admin email resolution for bootstrap (ADMIN_CHAT_ID / ADMIN_EMAIL)."""
import os


def resolve_admin_email() -> str:
    """
    Resolve bootstrap admin email from environment.

    - ADMIN_EMAIL: preferred explicit address
    - ADMIN_CHAT_ID: if contains '@', treated as email; else ``{id}@admin.veltrixia.local``
    """
    explicit = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
    if explicit:
        return explicit

    chat_id = (os.getenv("ADMIN_CHAT_ID") or "admin").strip().lower()
    if "@" in chat_id:
        return chat_id
    return f"{chat_id}@admin.veltrixia.local"
