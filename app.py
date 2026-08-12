import os
import urllib.request

from dotenv import load_dotenv
from flask import Flask, jsonify
from supabase import create_client

load_dotenv()

app = Flask(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY) if SUPABASE_URL and SUPABASE_ANON_KEY else None


@app.get("/health")
def health():
    db_status = "not_configured"
    if SUPABASE_URL and SUPABASE_ANON_KEY:
        try:
            req = urllib.request.Request(
                f"{SUPABASE_URL}/auth/v1/health",
                headers={"apikey": SUPABASE_ANON_KEY},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                db_status = "connected" if resp.status == 200 else "error"
        except Exception:
            db_status = "error"
    return jsonify({"status": "ok", "db": db_status})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
