"""
Builds a small index of places Time Out Japan has written about: name, coordinates, address and the URL of
Time Out's page. Facts only. Time Out's terms forbid copying, reposting or translating their content
without permission, so no review text or photos are stored, and the bot only links to their page.

Polite by default: obeys robots.txt, one request every 2 seconds, newest pages first, and resumable
(already-fetched URLs are skipped). Output: data/timeout_venues.jsonl (git-ignored).

    python -m jobs.timeout_crawl --since 2024-01-01 --max 2000
"""

import argparse
import gzip
import json
import pathlib
import re
import time
import urllib.robotparser
from urllib.parse import unquote

import httpx

UA = "AsobiAgentBot/0.1 (+venue matching only; obeys robots.txt)"
SITES = ["https://www.timeout.jp/tokyo/ja", "https://www.timeout.jp/osaka/ja"]
VENUE_SECTIONS = {"レストラン", "バー", "restaurant", "restaurants", "ナイトライフ"}
OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "timeout_venues.jsonl"
DONE = OUT.with_suffix(".done")


def _get(client: httpx.Client, url: str) -> bytes:
    resp = client.get(url, follow_redirects=True)
    resp.raise_for_status()
    return resp.content


def _sitemap_entries(client: httpx.Client, index_url: str, delay: float) -> list[tuple[str, str]]:
    raw = _get(client, index_url)
    try:
        raw = gzip.decompress(raw)
    except OSError:
        pass
    entries = []
    for loc in re.findall(r"<loc>([^<]+)</loc>", raw.decode("utf-8", "replace")):
        time.sleep(delay)
        part = _get(client, loc)
        try:
            part = gzip.decompress(part)
        except OSError:
            pass
        entries += re.findall(r"<loc>([^<]+)</loc>\s*<lastmod>([^<]+)</lastmod>", part.decode("utf-8", "replace"))
    return entries


_HOURS = re.compile(r"営業時間[^<]{0,4}</[^>]+>\s*<[^>]+>([^<]{1,80})")


def parse_place(html: str, url: str, lastmod: str = "") -> dict | None:
    """Facts about the reviewed place: never the review text or photos."""
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        for item in data if isinstance(data, list) else [data]:
            place = item.get("itemReviewed") if isinstance(item, dict) else None
            if not isinstance(place, dict) or not place.get("name"):
                continue
            geo = place.get("geo") or {}
            if geo.get("latitude") is None or geo.get("longitude") is None:
                return None
            address = place.get("address") or {}
            hours = _HOURS.search(html)
            return {"name": place["name"], "type": place.get("@type"),
                    "lat": float(geo["latitude"]), "lng": float(geo["longitude"]),
                    "address": address.get("streetAddress") if isinstance(address, dict) else None,
                    "telephone": place.get("telephone"),
                    "hours": hours.group(1).strip() if hours else None,
                    "section": unquote(url).split("/ja/", 1)[-1].split("/")[0],
                    "city": "osaka" if "/osaka/" in url else "tokyo",
                    "lastmod": lastmod, "url": url}
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2024-01-01", help="only pages modified on or after this date")
    ap.add_argument("--max", type=int, default=2000, help="stop after this many page fetches")
    ap.add_argument("--delay", type=float, default=2.0, help="seconds between requests")
    args = ap.parse_args()

    robots = urllib.robotparser.RobotFileParser("https://www.timeout.jp/robots.txt")
    robots.read()
    OUT.parent.mkdir(exist_ok=True)
    done = set(DONE.read_text().split("\n")) if DONE.exists() else set()

    with httpx.Client(headers={"User-Agent": UA}, timeout=20) as client:
        candidates: list[tuple[str, str]] = []
        cache = OUT.with_name("timeout_sitemaps.json")
        if cache.exists() and time.time() - cache.stat().st_mtime < 86400:
            entries = [tuple(e) for e in json.loads(cache.read_text())]
        else:
            entries = []
            for site in SITES:
                index = f"{site}/sitemap.xml.gz"
                if robots.can_fetch(UA, index):
                    entries += _sitemap_entries(client, index, args.delay)
            cache.write_text(json.dumps(entries, ensure_ascii=False))
        for url, lastmod in entries:
            section = unquote(url).split("/ja/", 1)[-1].split("/")[0]
            if section in VENUE_SECTIONS and lastmod >= args.since and url not in done:
                candidates.append((url, lastmod))
        candidates.sort(key=lambda c: c[1], reverse=True)
        print(f"{len(candidates)} venue pages to fetch (since {args.since})", flush=True)

        fetched = found = 0
        with OUT.open("a", encoding="utf-8") as out, DONE.open("a", encoding="utf-8") as done_file:
            for url, lastmod in candidates[:args.max]:
                if not robots.can_fetch(UA, url):
                    continue
                time.sleep(args.delay)
                try:
                    html = _get(client, url).decode("utf-8", "replace")
                    place = parse_place(html, url, lastmod)
                except httpx.HTTPError as e:
                    print(f"skip {url}: {e}", flush=True)
                    place = None
                fetched += 1
                if place:
                    out.write(json.dumps(place, ensure_ascii=False) + "\n")
                    found += 1
                done_file.write(url + "\n")
                if fetched % 50 == 0:
                    out.flush()
                    done_file.flush()
                    print(f"{fetched} fetched, {found} places", flush=True)
    print(f"done: {fetched} fetched, {found} places → {OUT}", flush=True)


if __name__ == "__main__":
    main()
