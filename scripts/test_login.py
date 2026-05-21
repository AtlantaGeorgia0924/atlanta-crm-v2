#!/usr/bin/env python3
"""Test Supabase login with anon key."""

import sys
import os
from dotenv import load_dotenv

ROOT = os.path.join(os.path.dirname(__file__), "..")
load_dotenv(os.path.join(ROOT, "backend", ".env"))
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
email = os.getenv("TEST_LOGIN_EMAIL")
password = os.getenv("TEST_LOGIN_PASSWORD")

if not SUPABASE_URL or not SUPABASE_ANON_KEY or not email or not password:
    print("Missing required env vars: SUPABASE_URL, SUPABASE_ANON_KEY, TEST_LOGIN_EMAIL, TEST_LOGIN_PASSWORD")
    sys.exit(1)

print(f"Testing login with:")
print(f"  URL: {SUPABASE_URL}")
print(f"  Email: {email}")
print("  Password: ********")
print()

try:
    sb = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    result = sb.auth.sign_in_with_password({"email": email, "password": password})
    print("✓ Login successful!")
    print(f"  User ID: {result.user.id}")
    print(f"  Email: {result.user.email}")
    print(f"  Access Token: {result.session.access_token[:50]}...")
except Exception as e:
    print(f"✗ Login failed: {str(e)}")
    import traceback
    traceback.print_exc()
