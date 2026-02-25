#!/usr/bin/env python3
"""
One-time script to obtain a Dropbox refresh token via OAuth2 authorization code flow.

Steps:
1. Go to your Dropbox App Console: https://www.dropbox.com/developers/apps
2. Copy your App Key and App Secret
3. Run this script and follow the prompts
4. Paste the resulting refresh token into .env.local
"""

import dropbox
from dropbox import DropboxOAuth2FlowNoRedirect


def main():
    app_key = input("Enter your Dropbox App Key: ").strip()
    app_secret = input("Enter your Dropbox App Secret: ").strip()

    auth_flow = DropboxOAuth2FlowNoRedirect(
        app_key,
        app_secret,
        token_access_type="offline",  # this gives us a refresh token
    )

    authorize_url = auth_flow.start()
    print(f"\n1. Go to: {authorize_url}")
    print("2. Click 'Allow' (you may need to log in first)")
    print("3. Copy the authorization code\n")

    auth_code = input("Enter the authorization code: ").strip()

    try:
        oauth_result = auth_flow.finish(auth_code)
    except Exception as e:
        print(f"\nError: {e}")
        return

    print("\n--- Success! Add these to your .env.local ---\n")
    print(f"DROPBOX_APP_KEY={app_key}")
    print(f"DROPBOX_APP_SECRET={app_secret}")
    print(f"DROPBOX_REFRESH_TOKEN={oauth_result.refresh_token}")
    print()

    # Verify it works
    dbx = dropbox.Dropbox(
        oauth2_refresh_token=oauth_result.refresh_token,
        app_key=app_key,
        app_secret=app_secret,
    )
    account = dbx.users_get_current_account()
    print(f"Verified: connected as {account.name.display_name} ({account.email})")


if __name__ == "__main__":
    main()
