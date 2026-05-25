from google_auth_oauthlib.flow import InstalledAppFlow
import json

SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube'
]

client_config = {
    "installed": {
        "client_id": "367346182418-vlqj2gu4pnmpo80a8skmnvb8ogshpeac.apps.googleusercontent.com",
        "client_secret": "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",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob"]
    }
}

flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
creds = flow.run_local_server(port=8080)

print("\n✅ YOUR REFRESH TOKEN:")
print(creds.refresh_token)