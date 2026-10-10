"""
Taste profiles: what each person likes and doesn't, and how a group's profiles combine.

Round 1 offers 12 broad kinds of place (10 map to a HotPepper genre, 2 are moods). Later rounds offer three
specifics for each kind someone kept. People mark ♡ or なし; anything else is "fine".

Combining a group uses "average without misery" (Masthoff): never a kind anyone dropped, then the kinds
most people like. Budget is not part of a profile; it comes from the chat per outing.
"""

from collections import Counter
from typing import Any, Optional

KINDS: list[dict[str, Any]] = [
    {"id": "yakiniku", "label": "焼肉・肉料理", "emoji": "🥩", "genre": "G008",
     "subs": [("jingisukan", "ジンギスカン", "🔥", "ジンギスカン"), ("horumon", "ホルモン", "🥓", "ホルモン"), ("steak", "ステーキ", "🥩", "ステーキ")]},
    {"id": "washoku", "label": "寿司・和食", "emoji": "🍣", "genre": "G004",
     "subs": [("sushi", "寿司", "🍣", "寿司"), ("soba", "そば・うどん", "🥢", "そば"), ("tempura", "天ぷら・とんかつ", "🍤", "天ぷら")]},
    {"id": "italian", "label": "イタリアン", "emoji": "🍝", "genre": "G006",
     "subs": [("pizza", "ピッツァ", "🍕", "ピザ"), ("pasta", "パスタ", "🍝", "パスタ"), ("bistro", "ビストロ", "🍷", "ビストロ")]},
    {"id": "chinese", "label": "中華", "emoji": "🥟", "genre": "G007",
     "subs": [("gyoza", "餃子", "🥟", "餃子"), ("sichuan", "四川・麻婆", "🌶️", "四川"), ("dimsum", "点心・飲茶", "🥮", "飲茶")]},
    {"id": "korean", "label": "韓国料理", "emoji": "🍲", "genre": "G017",
     "subs": [("samgyeopsal", "サムギョプサル", "🥓", "サムギョプサル"), ("chige", "チゲ・鍋", "🍲", "チゲ"), ("kchicken", "韓国チキン", "🍗", "チキン")]},
    {"id": "cafe", "label": "カフェ", "emoji": "☕", "genre": "G014",
     "subs": [("kissa", "喫茶店", "☕", "喫茶"), ("sweets", "スイーツ", "🍰", "スイーツ"), ("bakery", "ベーカリー", "🥐", "パン")]},
    {"id": "ramen", "label": "ラーメン", "emoji": "🍜", "genre": "G013",
     "subs": [("tonkotsu", "とんこつ", "🍜", "とんこつ"), ("tsukemen", "つけ麺", "🥢", "つけ麺"), ("shoyu", "醤油・塩", "🍜", "醤油")]},
    {"id": "izakaya", "label": "居酒屋", "emoji": "🏮", "genre": "G001",
     "subs": [("yakitori", "焼き鳥", "🍢", "焼き鳥"), ("kaisen", "海鮮", "🐟", "海鮮"), ("tachinomi", "立ち飲み", "🍺", "立ち飲み")]},
    {"id": "bar", "label": "バル・ワイン", "emoji": "🍷", "genre": "G002",
     "subs": [("wine", "ワインバル", "🍷", "ワイン"), ("craftbeer", "クラフトビール", "🍺", "クラフトビール"), ("spanish", "スペインバル", "🥘", "スペイン")]},
    {"id": "asian", "label": "アジア・エスニック", "emoji": "🍛", "genre": "G009",
     "subs": [("thai", "タイ料理", "🍜", "タイ"), ("curry", "インド・カレー", "🍛", "カレー"), ("vietnam", "ベトナム料理", "🥖", "ベトナム")]},
    {"id": "quiet", "label": "静かな店", "emoji": "🤫", "mood": "quiet",
     "subs": [("private", "個室", "🚪", "個室"), ("counter", "カウンター", "🪑", "カウンター"), ("terrace", "テラス", "🌿", "テラス")]},
    {"id": "lively", "label": "にぎやかな店", "emoji": "🎉", "mood": "lively",
     "subs": [("nomihodai", "飲み放題", "🍻", "飲み放題"), ("tabehodai", "食べ放題", "🍽️", "食べ放題"), ("party", "パーティー", "🎉", "パーティー")]},
]
BY_ID = {k["id"]: k for k in KINDS}
SUB_BY_ID = {f"{k['id']}/{sid}": {"kind": k["id"], "id": f"{k['id']}/{sid}", "label": label, "emoji": em, "keyword": kw}
             for k in KINDS for sid, label, em, kw in k["subs"]}
FOOD_KINDS = [k["id"] for k in KINDS if "genre" in k]
GENRE_TO_KIND = {k["genre"]: k["id"] for k in KINDS if "genre" in k}


def taxonomy() -> dict[str, Any]:
    """What the profile page shows: round 1 kinds and each kind's specifics."""
    return {"kinds": [{"id": k["id"], "label": k["label"], "emoji": k["emoji"],
                       "subs": [{"id": f"{k['id']}/{sid}", "label": label, "emoji": em} for sid, label, em, _ in k["subs"]]}
                      for k in KINDS]}


def clean_choices(ids: list[str]) -> list[str]:
    valid = set(BY_ID) | set(SUB_BY_ID)
    return list(dict.fromkeys(i for i in ids if i in valid))[:60]


def label(choice_id: str) -> str:
    if choice_id in BY_ID:
        return BY_ID[choice_id]["label"]
    return SUB_BY_ID.get(choice_id, {}).get("label", choice_id)


def group_taste(people: list[dict[str, Any]]) -> dict[str, Any]:
    """people: [{"name", "profile": {"likes": [...], "dislikes": [...]} or None}]"""
    dropped_kinds: set[str] = set()
    dropped_subs: set[str] = set()
    likers: dict[str, list[str]] = {}
    sub_likes: dict[str, Counter] = {}
    moods = Counter()
    tops: list[Optional[str]] = []
    for person in people:
        prof = person.get("profile") or {}
        for d in prof.get("dislikes", []):
            (dropped_subs if "/" in d else dropped_kinds).add(d)
        for like in prof.get("likes", []):
            if "/" in like:
                kind = like.split("/")[0]
                sub_likes.setdefault(kind, Counter())[like] += 1
                likers.setdefault(kind, [])
                if person["name"] not in likers[kind]:
                    likers[kind].append(person["name"])
            elif like in BY_ID:
                if BY_ID[like].get("mood"):
                    moods[BY_ID[like]["mood"]] += 1
                else:
                    likers.setdefault(like, [])
                    if person["name"] not in likers[like]:
                        likers[like].append(person["name"])
    kinds = [k for k in likers if k not in dropped_kinds and k in FOOD_KINDS]
    kinds.sort(key=lambda k: (-len(likers[k]), FOOD_KINDS.index(k)))
    for person in people:
        prof = person.get("profile") or {}
        own = [k for k in kinds if k in prof.get("likes", []) or any(l.startswith(k + "/") for l in prof.get("likes", []))]
        tops.append(own[0] if own else None)
    keywords = {}
    for kind, counts in sub_likes.items():
        best = [(s, n) for s, n in counts.most_common() if s not in dropped_subs]
        # Narrow a kind to one specific only when at least half of the people who like the kind chose it.
        if best and best[0][1] * 2 >= len(likers.get(kind, [])):
            keywords[kind] = SUB_BY_ID[best[0][0]]["keyword"]
    private = any("quiet/private" in (p.get("profile") or {}).get("likes", []) for p in people)
    return {
        "kinds": [{"id": k, "label": BY_ID[k]["label"], "genre": BY_ID[k]["genre"], "likers": likers[k],
                   "keyword": keywords.get(k)} for k in kinds],
        "dropped": sorted(dropped_kinds), "dropped_genres": sorted(BY_ID[k]["genre"] for k in dropped_kinds if "genre" in BY_ID[k]),
        "tops": tops,
        "quiet": moods["quiet"] >= moods["lively"],
        "private": private,
        "has_profiles": any(p.get("profile") for p in people),
    }


def allocate(taste: dict[str, Any], slots: int = 6) -> list[str]:
    """Which kind fills each slot: everyone's top kind first, then the most-liked kinds, round robin."""
    order: list[str] = []
    for top in taste["tops"]:
        if top and top not in order:
            order.append(top)
    for k in taste["kinds"]:
        if k["id"] not in order:
            order.append(k["id"])
    if not order:
        return []
    out = []
    i = 0
    while len(out) < slots:
        out.append(order[i % len(order)])
        i += 1
    return out
