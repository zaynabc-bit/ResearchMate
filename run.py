#!/usr/bin/env python3
"""ResearchMate — Entry point."""
import uvicorn
import os
from dotenv import load_dotenv

load_dotenv()

if __name__ == "__main__":
    port = int(os.getenv("APP_PORT", 3000))
    print(f"""
╔══════════════════════════════════════════╗
║         ResearchMate is starting...      ║
║  Open your browser at:                   ║
║  → http://localhost:{port}                  ║
╚══════════════════════════════════════════╝
""")
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        reload_dirs=["app", "static"],
    )
