"""Convenience script to manually set up or renew Gmail watch.

Usage: python -m scripts.setup_gmail_watch
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings
from app.db.database import init_db
from app.gmail.watcher import setup_gmail_watch

if __name__ == "__main__":
    init_db(settings.database_path)
    result = setup_gmail_watch()
    print(f"Gmail watch set up successfully!")
    print(f"  Expiration: {result.get('expiration')}")
    print(f"  History ID: {result.get('historyId')}")
