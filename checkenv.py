from dotenv import load_dotenv
import os
load_dotenv()
print("APP_ID:", os.getenv("FB_APP_ID"))
print("APP_SECRET:", os.getenv("FB_APP_SECRET")[:5] if os.getenv("FB_APP_SECRET") else "MISSING")
print("PAGE_ID:", os.getenv("FB_PAGE_ID"))