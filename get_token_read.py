# save as get_token_read.py — run once locally
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

flow = InstalledAppFlow.from_client_secrets_file(
    "client_secret_read.json",
    scopes=SCOPES,
)
creds = flow.run_local_server(port=0)

print("CLIENT_ID:     ", creds.client_id)
print("CLIENT_SECRET: ", creds.client_secret)
print("REFRESH_TOKEN: ", creds.refresh_token)