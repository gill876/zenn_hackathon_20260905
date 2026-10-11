"""
LINE message builders for every phase of a group plan (see the AsobiAgent Group Flow wireframe).

Buttons that change state are postbacks with a displayText, so a tap shows up in the chat as the
person's own message and the bot can stay quiet until something actually changes.
"""

from typing import Any, Optional
from urllib.parse import quote, urlencode

from bot.text_parse import short_station
from services.hotpepper_client import CREDIT_TEXT, CREDIT_URL

GREEN = "#06C755"
INK = "#1A2130"
MUTED = "#6A7486"
LINE_GREY = "#E3E8EF"
ACCENT = "#2D58A6"
WARN = "#A9590B"
CROWD_COLORS = {"低": "#25704B", "中": "#8A6D1F", "高": "#A9590B"}


# ---- primitives -------------------------------------------------------------------------------

def text(value: str, size: str = "sm", weight: Optional[str] = None, color: Optional[str] = None,
         wrap: bool = True, margin: Optional[str] = None, flex: Optional[int] = None,
         align: Optional[str] = None) -> dict:
    node: dict[str, Any] = {"type": "text", "text": value or " ", "size": size, "wrap": wrap}
    if weight:
        node["weight"] = weight
    if color:
        node["color"] = color
    if margin:
        node["margin"] = margin
    if flex is not None:
        node["flex"] = flex
    if align:
        node["align"] = align
    return node


def box(contents: list[dict], layout: str = "vertical", spacing: Optional[str] = None,
        margin: Optional[str] = None, **extra: Any) -> dict:
    node: dict[str, Any] = {"type": "box", "layout": layout, "contents": contents}
    if spacing:
        node["spacing"] = spacing
    if margin:
        node["margin"] = margin
    node.update(extra)
    return node


def postback(label: str, data: dict[str, str], display: Optional[str] = None, style: str = "primary") -> dict:
    action: dict[str, Any] = {"type": "postback", "label": label[:40], "data": urlencode(data)[:300]}
    if display:
        action["displayText"] = display[:300]
    button: dict[str, Any] = {"type": "button", "action": action, "style": style, "height": "sm"}
    if style == "primary":
        button["color"] = GREEN
    return button


def safe_uri(uri: str) -> str:
    """LINE rejects URIs with raw non-ASCII characters (e.g. Time Out's /レストラン/ paths)."""
    return quote(uri, safe=":/?#[]@!$&'()*+,;=%~")


def link(label: str, uri: str, style: str = "secondary") -> dict:
    button: dict[str, Any] = {"type": "button", "action": {"type": "uri", "label": label[:40], "uri": safe_uri(uri)},
                              "style": style, "height": "sm"}
    if style == "primary":
        button["color"] = GREEN
    return button


def bubble(body: list[dict], footer: Optional[list[dict]] = None, hero: Optional[dict] = None,
           size: str = "kilo") -> dict:
    node: dict[str, Any] = {"type": "bubble", "size": size,
                            "body": box(body, spacing="sm", paddingAll="14px")}
    if hero:
        node["hero"] = hero
    if footer:
        node["footer"] = box(footer, spacing="sm", paddingAll="10px")
    return node


def quick_postback(label: str, data: dict[str, str], display: str) -> dict:
    """A quick reply button: shown above the chat's input box until someone sends something."""
    return {"type": "action", "action": {"type": "postback", "label": label[:20], "data": urlencode(data)[:300],
                                         "displayText": display[:300]}}


def quick_message(label: str, text_value: str) -> dict:
    return {"type": "action", "action": {"type": "message", "label": label[:20], "text": text_value[:300]}}


def with_quick(messages: list[dict], items: list[dict]) -> list[dict]:
    """Attach quick reply buttons to the last message (LINE shows those of the latest message)."""
    if messages and items:
        messages = list(messages)
        messages[-1] = dict(messages[-1], quickReply={"items": items[:13]})
    return messages


def short(name: str, limit: int = 18) -> str:
    name = name or ""
    return name if len(name) <= limit else name[:limit - 1] + "…"


def flex(alt: str, contents: dict) -> dict:
    return {"type": "flex", "altText": alt[:400], "contents": contents}


def plain(value: str) -> dict:
    return {"type": "text", "text": value[:5000]}


def kicker(value: str) -> dict:
    return text(value, size="xxs", color=MUTED)


def title(value: str, size: str = "md") -> dict:
    return text(value, size=size, weight="bold", color=INK)


def rows(pairs: list[tuple[str, str]]) -> dict:
    return box([box([text(k, size="xs", color=MUTED, flex=2), text(v, size="xs", color=INK, flex=3)],
                    layout="horizontal", spacing="sm") for k, v in pairs], spacing="xs", margin="md")


def note(value: str, color: str = MUTED) -> dict:
    return text(value, size="xxs", color=color, margin="md")


# ---- phase 0–1: activation ----------------------------------------------------------------------

def welcome() -> dict:
    return flex("AsobiAgentが参加しました。認証済みのメンバーが有効化してください。", bubble(
        [kicker("はじめまして"), title("AsobiAgentが参加しました"),
         text("このグループで使うには、認証済みのメンバーが有効化してください。", margin="md"),
         note("有効化されるまで、トークは一切読み取りません。")],
        [postback("有効化する", {"a": "activate"}, "有効化する")]))


def activated(plans: int, searches: int, until: str) -> dict:
    return flex("AsobiAgentが使えるようになりました。", bubble(
        [kicker("有効化"), title("使えるようになりました"),
         rows([("決められるお店", f"{plans}軒"), ("検索", f"{searches}回まで"), ("期限", f"{until}まで")]),
         note("予定を立てるときは @AsobiAgent で呼ぶか、下のボタンを押してください。")],
        [postback("日程を決める", {"a": "poll"}, "日程を決める"),
         postback("プランを立てる", {"a": "start"}, "プランを立てる", style="secondary")]))


# ---- phase 2–3: gathering and ready check -------------------------------------------------------

def gathering(nonce: str, max_participants: int) -> dict:
    return flex("参加する人はボタンを押して、出発駅を送ってください。", bubble(
        [kicker("募集中"), title("参加する人はボタンを押して、出発駅を送ってください"),
         text("例：「横浜から」", size="xs", color=MUTED, margin="md"),
         note(f"募集中は、参加した人のメッセージだけを読み取ります（最大{max_participants}人）。")],
        [postback("参加する", {"a": "join", "p": nonce}, "参加する"),
         postback("今回はパス", {"a": "pass", "p": nonce}, "今回はパス", style="secondary")]))


def ready_check(nonce: str, people: list[tuple[str, Optional[str]]], when: Optional[str]) -> dict:
    station_rows = [(name, short_station(station) if station else "未入力") for name, station in people]
    when_row = [("日時", when)] if when else [("日時", "未定")]
    body = [kicker("確認"), title("全員の出発駅がそろいました"), rows(station_rows + when_row)]
    if not when:
        body.append(note("日時が決まっていれば「土曜13時」のように送ってください。", color=WARN))
    body.append(note("全員がOKすると検索を始めます。幹事は「もう探して」で先に進められます。"))
    return flex("全員の出発駅がそろいました。内容を確認してOKを押してください。", bubble(body, [
        postback("✅ これでOK", {"a": "ready", "p": nonce}, "✅ OK"),
        postback("駅を直す", {"a": "fix", "p": nonce}, "駅を直す", style="secondary"),
        postback("もう探して（幹事）", {"a": "force", "p": nonce}, "もう探して", style="secondary"),
    ]))


# ---- phase 4: meeting station -------------------------------------------------------------------

def _bar(name: str, minutes: int, scale: int) -> dict:
    pct = max(4, min(100, round(minutes / scale * 100)))
    return box([
        text(name, size="xxs", color=INK, flex=4),
        box([box([], width=f"{pct}%", height="6px", backgroundColor=ACCENT, cornerRadius="3px")],
            flex=5, height="6px", backgroundColor=LINE_GREY, cornerRadius="3px", justifyContent="center"),
        text(f"{minutes}分", size="xxs", color=INK, flex=2, align="end"),
    ], layout="horizontal", spacing="sm", alignItems="center")


def hub_card(hub: dict, people: list[tuple[str, str, int]], summary: str) -> dict:
    scale = max(10, ((max((m for _, _, m in people), default=0) + 9) // 10) * 10)
    hub_name = short_station(hub["name"])
    body = [kicker("集合駅"), text(hub_name, size="xxl", weight="bold", color=INK),
            text(f"移動時間の差は最大{hub['spread']}分です。", size="sm", margin="sm"),
            box([_bar(f"{name}・{short_station(station)}", minutes, scale) for name, station, minutes in people],
                spacing="sm", margin="md")]
    if summary:
        body.append(rows([("希望", summary)]))
    body.append(note("駅すぱあとの平均所要時間で計算しています（時刻表は使っていません）。"))
    return flex(f"集合駅は{hub_name}です。", bubble(body, size="mega"))


# ---- phase 5: venues and vote -------------------------------------------------------------------

def _time_out_bubble(nonce: str, label: str, shop: dict, pick: dict) -> dict:
    crowd = (pick.get("crowd") or {}).get("level", "中")
    walk = f"徒歩約{pick['walk_min']}分" if pick.get("walk_min") else ""
    body = [
        text(f"{label}  {shop['name']}", size="md", weight="bold", color=INK),
        text(" · ".join(x for x in ("Time Out 掲載", shop.get("genre"), walk) if x), size="xs", color=ACCENT, weight="bold"),
    ]
    if shop.get("open"):
        body.append(text(f"営業時間 {shop['open'][:40]}", size="xs", color=INK))
    body += [
        text(f"混雑度（推定）{crowd}", size="xs", weight="bold", color=CROWD_COLORS.get(crowd, INK)),
        text(pick.get("reason") or "", size="xs", color=INK, margin="sm"),
        text("お店の情報：Time Out（くわしくはリンク先）", size="xxs", color=MUTED, margin="md"),
    ]
    footer = [_vote_button(nonce, label, shop), link("Time Outの記事", shop["url"])]
    return bubble(body, footer)


def _vote_button(nonce: str, label: str, shop: dict) -> dict:
    return postback("🗳 ここがいい", {"a": "vote", "p": nonce, "v": shop["id"]}, f"🗳 {label} {short(shop['name'], 22)}")


def suggestion_bubble(nonce: str, label: str, shop: dict, pick: dict) -> dict:
    walk = f"集合駅から徒歩約{pick['walk_min']}分" if pick.get("walk_min") else None
    body = [text(f"💡 {label}  {shop['name']}", size="md", weight="bold", color=INK),
            text(" · ".join(x for x in (shop.get("genre"), walk) if x) or "提案されたお店", size="xs", color=MUTED),
            text(f"{pick.get('suggested_by', 'メンバー')}さんの提案", size="xs", color=ACCENT, weight="bold", margin="sm")]
    if shop.get("address"):
        body.append(text(shop["address"][:40], size="xxs", color=MUTED))
    if shop.get("source") == "hotpepper" or shop["id"].startswith("J"):
        body.append(text(CREDIT_TEXT, size="xxs", color=MUTED, margin="md"))
    footer = [_vote_button(nonce, label, shop)]
    if shop.get("url"):
        footer.append(link("お店の詳細" if shop["id"].startswith("J") else "地図で見る", shop["url"]))
    hero = None
    if shop.get("photo"):
        hero = {"type": "image", "url": shop["photo"], "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"}
    return bubble(body, footer, hero=hero)


def suggestion_card(nonce: str, label: str, shop: dict, pick: dict) -> dict:
    return flex(f"{pick.get('suggested_by', 'メンバー')}さんの提案：{shop['name']}",
                {"type": "carousel", "contents": [suggestion_bubble(nonce, label, shop, pick)]})


def _venue_bubble(nonce: str, label: str, shop: dict, pick: dict, featured: Optional[dict] = None) -> dict:
    if pick.get("suggested_by"):
        return suggestion_bubble(nonce, label, shop, pick)
    if shop.get("source") == "timeout":
        return _time_out_bubble(nonce, label, shop, pick)
    crowd = pick.get("crowd") or {"level": "中"}
    level = crowd.get("level", "中")
    walk = f"徒歩約{pick['walk_min']}分" if pick.get("walk_min") else (shop.get("station_name") or "")
    body = [
        text(f"{label}  {shop['name']}", size="md", weight="bold", color=INK),
        text(" · ".join(x for x in (shop.get("genre"), walk) if x), size="xs", color=MUTED),
        text(f"予算 {shop.get('budget_average') or shop.get('budget') or '—'}", size="xs", color=INK),
        text(f"混雑度（推定）{level}", size="xs", weight="bold", color=CROWD_COLORS.get(level, INK)),
        text(pick.get("reason") or "", size="xs", color=INK, margin="sm"),
    ]
    if featured:
        body.append(text("Time Out で紹介されています", size="xxs", weight="bold", color=ACCENT, margin="sm"))
    body.append(text(CREDIT_TEXT, size="xxs", color=MUTED, margin="md"))
    hero = None
    if shop.get("photo"):
        hero = {"type": "image", "url": shop["photo"], "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"}
    footer = [_vote_button(nonce, label, shop)]
    if shop.get("url"):
        footer.append(link("お店の詳細", shop["url"]))
    if featured:
        footer.append(link("Time Outの記事", featured["url"], style="link"))
    return bubble(body, footer, hero=hero)


def venues_carousel(nonce: str, shops: list[dict], picks: list[dict], labels: list[str],
                    more_left: int, searches_left: int, featured: Optional[list[Optional[dict]]] = None,
                    leader: Optional[str] = None, can_suggest: bool = True) -> dict:
    featured = featured or [None] * len(shops)
    bubbles = [_venue_bubble(nonce, label, shop, pick, f)
               for label, shop, pick, f in zip(labels, shops, picks, featured)]
    options: list[dict] = []
    if more_left > 0:
        options.append(postback(f"別の候補を見る（あと{more_left}回）", {"a": "more", "p": nonce}, "別の候補を見る",
                                style="secondary"))
    if can_suggest:
        options.append(postback("💡 お店を提案する", {"a": "suggest", "p": nonce}, "💡 お店を提案する", style="secondary"))
    options += [postback("📊 結果を見る", {"a": "results", "p": nonce}, "📊 結果を見る", style="secondary"),
                postback("決める（幹事）", {"a": "close", "p": nonce}, "決める", style="link")]
    hint = ("条件を変えるなら「@AsobiAgent 和食がいい」のように送ってください"
            f"（あと{searches_left}回）。" if searches_left > 0 else "このグループの検索回数を使い切りました。")
    tail_body = [kicker("ほかの候補"), title("いいと思うお店に、いくつでも投票してください"),
                 text(f"いまの1位：{leader}" if leader else "いまの1位：まだ投票がありません", size="xs", color=INK, margin="md"),
                 note(hint)]
    bubbles.append(bubble(tail_body, options))
    return flex("お店の候補です。いいと思うお店にいくつでも投票してください。", {"type": "carousel", "contents": bubbles})


def _vote_row(name: str, count: int, scale: int) -> dict:
    pct = max(4, min(100, round(count / max(1, scale) * 100)))
    return box([
        text(short(name, 26), size="xs", color=INK, wrap=False),
        box([box([box([], width=f"{pct}%", height="6px", backgroundColor=ACCENT, cornerRadius="3px")],
                 flex=6, height="6px", backgroundColor=LINE_GREY, cornerRadius="3px", justifyContent="center"),
             text(f"{count}票", size="xxs", color=INK, flex=1, align="end")],
            layout="horizontal", spacing="sm", alignItems="center"),
    ], spacing="xs")


def results_card(rows: list[tuple[str, int]], voters: int, total: int, missing: list[str], heading: str,
                 nonce: Optional[str] = None) -> dict:
    body = [kicker(f"{'投票結果' if voters >= total else '途中結果'} · {voters}/{total}人が投票"), title(heading),
            box([_vote_row(name, count, total) for name, count in rows[:6]], spacing="md", margin="md")
            if rows else text("まだ投票がありません。", size="sm")]
    if missing:
        body.append(note("まだの人：" + "・".join(missing[:8])))
    footer = [postback("決める（幹事）", {"a": "close", "p": nonce}, "決める", style="secondary")] if nonce and voters < total else None
    return flex(f"{short(heading, 40)}（{voters}/{total}人が投票）", bubble(body, footer, size="mega"))


# ---- profiles and date poll ---------------------------------------------------------------------

def profile_offer(liff_url: str) -> dict:
    return flex("好きなお店を登録しておくと、グループで自動で使われます。", bubble(
        [kicker("プロフィール"), title("好きなお店を登録しませんか？"),
         text("登録しておくと、グループでお店を探すときに自動で使われます。", size="sm", margin="md"),
         note("タップするだけ。あとから変更・削除できます。")],
        [link("プロフィールを作る", liff_url, style="primary")]))


def poll_start(calendar_url: str, organizer: str) -> dict:
    return flex("日程調整：候補日をカレンダーでえらんでください。", bubble(
        [kicker("日程調整"), title("候補日をカレンダーでえらんでください"),
         note(f"幹事（{organizer}さん）がえらぶと、ここに○△×の表が届きます。")],
        [link("候補日をえらぶ", calendar_url, style="primary")]))


def poll_card(nonce: str, date_labels: list[str], slot: str, answer_url: str, answered: int) -> dict:
    body = [kicker("日程調整"), title("候補日に○△×をつけてください"),
            rows([("候補", "・".join(date_labels)), ("時間帯", slot), ("回答", f"{answered}人")])]
    return flex("日程調整：候補日に○△×をつけてください。", bubble(body, [
        link("回答する", answer_url, style="primary"),
        postback("📊 結果を見る", {"a": "pollres", "p": nonce}, "📊 日程の結果を見る", style="secondary"),
        postback("締め切る（幹事）", {"a": "pollclose", "p": nonce}, "締め切る", style="link"),
    ], size="mega"))


def poll_result(nonce: str, best: Optional[str], yes: list[str], maybe: list[str], runner_up: Optional[str],
                table: list[tuple[str, int, int, int]], closed: bool) -> dict:
    head = (f"{best} に決まりました" if closed else f"いまの1位：{best}") if best else "まだ回答がありません"
    body = [kicker("日程が決まりました" if closed else "日程調整の途中結果"), title(head)]
    if table:
        body.append(box([box([text(d, size="xs", color=INK, flex=4), text(f"○{o} △{t} ×{x}", size="xs", color=MUTED, flex=4, align="end")],
                             layout="horizontal") for d, o, t, x in table[:8]], spacing="xs", margin="md"))
    if best:
        body.append(rows([("○", "・".join(yes) or "—"), ("△", "・".join(maybe) or "—")]))
    if runner_up and closed:
        body.append(note(f"次点：{runner_up}"))
    footer = [postback("このメンバーでプランを立てる", {"a": "pollplan", "p": nonce}, "このメンバーでプランを立てる")] \
        if closed and best else None
    return flex(head, bubble(body, footer, size="mega"))


# ---- phase 6: decision --------------------------------------------------------------------------

def decision_card(shop: dict, when: Optional[str], pax: int, walk_min: Optional[int],
                  hub_name: str, agent_url: Optional[str]) -> dict:
    hub_name = short_station(hub_name)
    place = f"{hub_name}駅から徒歩約{walk_min}分" if walk_min else f"{hub_name}駅の近く"
    from_time_out = shop.get("source") == "timeout"
    body = [kicker("決定"), text(shop["name"], size="xl", weight="bold", color=INK),
            rows([("日時", when or "未定"), ("人数", f"{pax}名"), ("場所", place)]),
            text("まだ予約は完了していません。", size="sm", weight="bold", color=WARN, margin="md")]
    if from_time_out or shop.get("source") == "places":
        body.append(note("営業時間と予約方法は、リンク先かお電話でご確認ください。"))
    else:
        body.append(note(CREDIT_TEXT))
    footer = []
    if from_time_out:
        footer.append(link("お店の情報（Time Out）", shop["url"], style="primary"))
    elif shop.get("source") == "places" and shop.get("url"):
        footer.append(link("地図で見る", shop["url"], style="primary"))
    elif shop.get("url"):
        footer.append(link("ホットペッパーで予約", shop["url"], style="primary"))
    if agent_url:
        footer.append(link("AIに入力を任せる（デモ）", agent_url))
    return flex(f"{shop['name']}に決まりました。まだ予約は完了していません。", bubble(body, footer or None, size="mega"))


def script_card(script: dict, phone: Optional[str], shop_url: Optional[str]) -> dict:
    body = [kicker("電話で予約する場合"), title("電話用の台本")]
    body += [text(line, size="sm", color=INK, margin="md") for line in script["lines"]]
    body.append(note(f"満席なら：{script['if_full']}"))
    footer = []
    if phone:
        digits = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
        footer.append(link(f"📞 {phone} に電話", f"tel:{digits}", style="primary"))
    elif shop_url:
        footer.append(link("お店のページで電話番号を見る", shop_url))
    return flex("電話で予約するときの台本です。", bubble(body, footer or None, size="mega"))


def credit_link() -> dict:
    return link(CREDIT_TEXT, CREDIT_URL, style="link")
