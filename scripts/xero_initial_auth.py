"""Convenience script to print Xero auth URL for first-time setup.

Usage: python -m scripts.xero_initial_auth
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.xero.auth import get_login_url

if __name__ == "__main__":
    url = get_login_url()
    print("Open this URL in your browser to authorize Xero:")
    print(f"\n  {url}\n")
    print("After authorizing, you'll be redirected to your callback URL.")
    print("Make sure your server is running to handle the callback.")
