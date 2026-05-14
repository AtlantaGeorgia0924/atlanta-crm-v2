from supabase import create_client, Client
from app.core.config import settings

_admin_client: Client | None = None
_auth_client: Client | None = None


def get_supabase() -> Client:
    """Get admin client (with service role key for admin operations)."""
    global _admin_client
    if _admin_client is None:
        _admin_client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    return _admin_client


def get_supabase_auth() -> Client:
    """Get auth client (with anon key for user authentication)."""
    global _auth_client
    if _auth_client is None:
        _auth_client = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)
    return _auth_client
