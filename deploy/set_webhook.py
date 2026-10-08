"""Point the LINE channel's webhook at the deployed bot and ask LINE to test it.

    python -m deploy.set_webhook https://asobi-agent-123.asia-northeast1.run.app/webhook
"""

import asyncio
import sys

from dotenv import dotenv_values

from services.line_api import HttpLineApi


async def main(url: str) -> None:
    token = dotenv_values(".env").get("LINE_CHANNEL_ACCESS_TOKEN") or ""
    if not token:
        sys.exit("LINE_CHANNEL_ACCESS_TOKEN is empty in .env (Developers Console → Messaging API → Issue)")
    line = HttpLineApi(token)
    info = await line.bot_info()
    print(f"bot: {info.get('displayName')} ({info.get('basicId')})")
    if not await line.set_webhook(url):
        sys.exit("LINE refused the webhook URL")
    result = await line.test_webhook()
    print(f"webhook set to {url}; LINE test: success={result.get('success')} status={result.get('statusCode')} "
          f"{result.get('reason') or ''}")
    print("Now turn Webhook ON in LINE Official Account Manager → 設定 → 応答設定 (if it isn't already).")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
