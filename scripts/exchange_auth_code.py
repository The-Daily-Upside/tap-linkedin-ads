#!/usr/bin/env python3
"""Exchange a LinkedIn OAuth authorization code for access and refresh tokens.

LinkedIn Marketing APIs do not support service accounts. Approved Marketing
Developer Platform apps get a member access token (60 days) and a refresh
token (365 days from this consent). Refreshing does not extend the refresh
token. Re-run this after the member re-authorizes, then replace the Meltano
env values and delete the old token file so the new grant wins.

Example:
  python scripts/exchange_auth_code.py --print-auth-url \\
    --client-id ID --redirect-uri https://www.google.com

  python scripts/exchange_auth_code.py \\
    --client-id ID --client-secret SECRET \\
    --redirect-uri https://www.google.com --code CODE \\
    --out /path/to/linkedin-ads-tokens.json
"""

import argparse
import json
import os
import secrets
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
DEFAULT_SCOPES = "r_ads r_ads_reporting"


def _print_auth_url(args):
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": args.client_id,
            "redirect_uri": args.redirect_uri,
            "scope": args.scopes,
            "state": args.state,
        },
        quote_via=urllib.parse.quote,
    )
    print(AUTH_URL + "?" + query)


def _exchange(args):
    body = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": args.code,
            "client_id": args.client_id,
            "client_secret": args.client_secret,
            "redirect_uri": args.redirect_uri,
        }
    ).encode()
    request = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        print("LinkedIn token exchange failed: HTTP {} {}".format(exc.code, detail), file=sys.stderr)
        return 1

    if "refresh_token" not in payload:
        print(
            "LinkedIn did not return a refresh_token. The app needs Marketing "
            "Developer Platform approval before unattended refresh works.",
            file=sys.stderr,
        )
        return 1

    now = datetime.now(timezone.utc)
    # LinkedIn's refresh token is 365 days from this consent when the field is present.
    refresh_seconds = int(payload.get("refresh_token_expires_in") or 365 * 24 * 3600)
    refresh_expires = now + timedelta(seconds=refresh_seconds)
    token_file = {
        "access_token": payload["access_token"],
        "refresh_token": payload["refresh_token"],
        "refresh_token_expires_at": refresh_expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    directory = os.path.dirname(os.path.abspath(args.out)) or "."
    os.makedirs(directory, exist_ok=True)
    # Unique 0600 file. A fixed "<out>.tmp" name can be replaced with a symlink
    # before chmod, and open() would follow it.
    fd, tmp_path = tempfile.mkstemp(prefix=".linkedin-ads-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(token_file, handle, indent=2)
            handle.write("\n")
        os.replace(tmp_path, args.out)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    print("Wrote tokens to {} (mode 0600).".format(args.out), file=sys.stderr)
    print("Put these in the Meltano environment. Do not commit them.")
    print("Copy access_token and refresh_token from that file.")
    print("Set TAP_LINKEDIN_ADS_CLIENT_SECRET from the LinkedIn app Auth tab (it is not printed here).")
    print("TAP_LINKEDIN_ADS_CLIENT_ID={}".format(args.client_id))
    print("TAP_LINKEDIN_ADS_REFRESH_TOKEN_EXPIRES_AT={}".format(token_file["refresh_token_expires_at"]))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--client-secret")
    parser.add_argument("--redirect-uri", required=True)
    parser.add_argument("--scopes", default=DEFAULT_SCOPES)
    parser.add_argument("--state", default=None, help="CSRF token. A random value is used when omitted.")
    parser.add_argument("--code", help="Authorization code from the redirect URL")
    parser.add_argument("--out", help="Token file path the tap reads via token_file_path")
    parser.add_argument("--print-auth-url", action="store_true")
    args = parser.parse_args()
    if not args.state:
        args.state = secrets.token_hex(16)

    if args.print_auth_url:
        _print_auth_url(args)
        return 0
    if not args.out:
        parser.error("--out is required so tokens are written to a file before the one-time code is spent")
    if not args.code or not args.client_secret:
        parser.error("--code and --client-secret are required unless --print-auth-url is set")
    return _exchange(args)


if __name__ == "__main__":
    sys.exit(main())
