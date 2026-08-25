#!/usr/bin/env python3
"""LockedinLeads entrypoint.

    python3 server.py

Configuration is read from environment variables (and an optional .env file).
See README.md and .env.example for every supported setting.
"""

from app.server import main

if __name__ == "__main__":
    main()
