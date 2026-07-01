import os
from fastapi import APIRouter, Depends, HTTPException, Header
import httpx

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Anonymous user ID used when no token is provided (local-first mode)
ANONYMOUS_USER_ID = "local-user"

async def get_current_user_id(authorization: str = Header(None)) -> str:
    """FastAPI dependency to verify Supabase JWT and return the user ID.
    
    Falls back to a local anonymous user if:
    - No authorization header is provided (user not logged in)
    - Supabase is not configured
    """
    # If no auth header — user is browsing without logging in.
    # Return a stable anonymous local user so the app still works.
    if not authorization or not authorization.startswith("Bearer "):
        return ANONYMOUS_USER_ID

    # If Supabase not configured, skip verification
    if not SUPABASE_URL:
        return ANONYMOUS_USER_ID

    token = authorization.split(" ")[1]

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{SUPABASE_URL}/auth/v1/user",
                headers={"Authorization": f"Bearer {token}", "apikey": SUPABASE_KEY or ""},
                timeout=5.0
            )

            if response.status_code != 200:
                # Token invalid — still allow as anonymous rather than blocking
                return ANONYMOUS_USER_ID

            user_data = response.json()
            return user_data.get("id") or ANONYMOUS_USER_ID
    except Exception as e:
        print(f"Auth check error (falling back to local): {e}")
        return ANONYMOUS_USER_ID
