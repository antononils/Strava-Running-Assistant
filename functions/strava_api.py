import json, time, os, requests


# Constants used in the Strava API
STRAVA_API_BASE = "https://www.strava.com/api/v3"
STRAVA_OAUTH_URL = "https://www.strava.com/oauth"
DEFAULT_TIMEOUT = 20


# Helper for loading tokens from file
def _load_tokens(token_file):
    """Read tokens from disk or return empty dict."""
    if os.path.exists(token_file):
        with open(token_file, "r") as f:
            return json.load(f)
    return {}

# Helper for saving tokens to file
def _save_tokens(tokens, token_file):
    """Write tokens to disk."""
    with open(token_file, "w") as f:
        json.dump(tokens, f)

# Helper for building the Strava login URL
def _auth_url(strava_client_id, redirect_uri):
    """Return Strava OAuth URL for user login."""
    return (
        f"{STRAVA_OAUTH_URL}/authorize"
        f"?client_id={strava_client_id}"
        "&response_type=code"
        f"&redirect_uri={redirect_uri}"
        "&scope=read,activity:read_all"
        "&approval_prompt=auto"
    )

# Helper for refreshing token if expired
def _refresh_if_needed(token_file, strava_client_id, strava_client_secret):
    """Return a valid access token, refreshing if expired."""
    tokens = _load_tokens(token_file)
    if not tokens:
        return None
    if tokens.get("expires_at", 0) <= int(time.time()):
        r = requests.post(
            f"{STRAVA_OAUTH_URL}/token",
            data={
                "client_id": strava_client_id,
                "client_secret": strava_client_secret,
                "grant_type": "refresh_token",
                "refresh_token": tokens.get("refresh_token")
            },
            timeout=DEFAULT_TIMEOUT
        )
        r.raise_for_status()
        tokens = r.json()
        _save_tokens(tokens, token_file)
    return tokens.get("access_token")

# Helper for making auth headers
def _auth_header(access_token):
    """Return HTTP Authorization header."""
    return {"Authorization": f"Bearer {access_token}"}


# Get one Strava activity by ID
def get_strava_activity(activity_id, token_file, strava_client_id, strava_client_secret):
    """Fetch one activity from Strava by ID."""
    access_token = _refresh_if_needed(token_file, strava_client_id, strava_client_secret)
    if not access_token:
        raise Exception("No access token available. Please authenticate with Strava.")
    r = requests.get(
        f"{STRAVA_API_BASE}/activities/{activity_id}",
        headers=_auth_header(access_token),
        params={"include_all_efforts": False},
        timeout=DEFAULT_TIMEOUT
    )
    r.raise_for_status()
    return r.json()

# Get recent Strava activities
def get_strava_activities(limit, token_file, strava_client_id, strava_client_secret):
    """Fetch recent activities up to given limit."""
    access_token = _refresh_if_needed(token_file, strava_client_id, strava_client_secret)
    if not access_token:
        raise Exception("No access token available. Please authenticate with Strava.")
    r = requests.get(
        f"{STRAVA_API_BASE}/athlete/activities",
        headers=_auth_header(access_token),
        params={"per_page": limit},
        timeout=DEFAULT_TIMEOUT
    )
    r.raise_for_status()
    return r.json()