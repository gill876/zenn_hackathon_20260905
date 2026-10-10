"""Register (or update) the LIFF app on the LINE Login channel and save its ID to .env.

    python -m deploy.liff_setup https://asobi-agent-558141828292.asia-northeast1.run.app/liff
"""

import pathlib
import re
import sys

import httpx
from dotenv import dotenv_values

API = "https://api.line.me/liff/v1/apps"


def main(endpoint: str) -> None:
    env = dotenv_values(".env")
    token = httpx.post("https://api.line.me/oauth2/v3/token", timeout=15, data={
        "grant_type": "client_credentials", "client_id": env["LINE_LOGIN_CHANNEL_ID"],
        "client_secret": env["LINE_LOGIN_CHANNEL_SECRET"]}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    app = {"view": {"type": "full", "url": endpoint}, "description": "AsobiAgent",
           "features": {"qrCode": False}, "permanentLinkPattern": "concat",
           "scope": ["openid", "profile", "chat_message.write"], "botPrompt": "none"}
    liff_id = env.get("LIFF_ID") or ""
    if liff_id:
        r = httpx.put(f"{API}/{liff_id}", headers=headers, json=app, timeout=15)
        print("updated" if r.status_code == 200 else f"update failed: {r.status_code} {r.text[:200]}")
    else:
        r = httpx.post(API, headers=headers, json=app, timeout=15)
        if r.status_code != 200:
            sys.exit(f"create failed: {r.status_code} {r.text[:300]}")
        liff_id = r.json()["liffId"]
        path = pathlib.Path(".env")
        text = path.read_text()
        text = re.sub(r"(?m)^LIFF_ID=.*$", f"LIFF_ID={liff_id}", text) if "LIFF_ID=" in text else text.rstrip("\n") + f"\nLIFF_ID={liff_id}\n"
        path.write_text(text)
        print("created")
    print(f"LIFF ID: {liff_id}  →  https://liff.line.me/{liff_id}/profile")


if __name__ == "__main__":
    main(sys.argv[1])
