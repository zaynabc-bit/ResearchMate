import os
from fastapi import APIRouter, Depends, HTTPException, Header
import httpx

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

async def get_current_user_id(authorization: str = Header(None)) -> str:
    """FastAPI dependency to verify Supabase JWT and return the user ID using httpx."""
    if not SUPABASE_URL:
        # Fallback for local dev if supabase not configured
        return "local-dev-user-id"
        
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
        
    token = authorization.split(" ")[1]
    
    try:
        # Verify token by fetching the user via Supabase REST API
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{SUPABASE_URL}/auth/v1/user",
                headers={"Authorization": f"Bearer {token}", "apikey": SUPABASE_KEY or ""}
            )
            
            if response.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid token")
                
            user_data = response.json()
            return user_data.get("id")
    except Exception as e:
        print(f"Auth error: {e}")
        raise HTTPException(status_code=401, detail="Could not validate credentials")
