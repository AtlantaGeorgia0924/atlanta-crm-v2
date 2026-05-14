#!/usr/bin/env python3
"""Test Supabase login with anon key."""

import sys
import os
sys.path.insert(0, "/Users/mac/crm-app/backend")

from supabase import create_client

# Credentials from your setup
SUPABASE_URL = "https://rwyplndwzrqdsyhsyjue.supabase.co"
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY") or "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJ3eXBsbmR3enJxZHN5aHN5anVlIiwicm9sZSI6ImFub24iLCJpYXQiOjE3MTI0NDcxMjUsImV4cCI6MTkyODA4MDcyNX0.iKVp67sRf0UKnSYVCGBmSLBSGjbJUUZEfaBR0Q3NxWE"

email = "georgeayo721@gmail.com"
password = "Atlanta1"

print(f"Testing login with:")
print(f"  URL: {SUPABASE_URL}")
print(f"  Email: {email}")
print(f"  Password: {password}")
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
