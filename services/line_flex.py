"""
LINE Flex Message Builder
Generates valid LINE Flex Message JSON objects for LINE Messaging API.
Styled cleanly for both real LINE chats and the Web Simulator.
"""

from typing import List, Dict, Any

def create_schedule_summary_flex(members: List[str], origins: Dict[str, str], date_time: str, preference: str) -> Dict[str, Any]:
    """Summary of group availability, origins, and preferences."""
    member_boxes = []
    for m in members:
        orig = origins.get(m, "未定")
        member_boxes.append({
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {"type": "text", "text": f"👤 {m}", "size": "sm", "color": "#555555", "flex": 3},
                {"type": "text", "text": f"📍 出発: {orig}駅", "size": "sm", "color": "#111111", "weight": "bold", "flex": 4, "align": "end"}
            ]
        })

    return {
        "type": "flex",
        "altText": "【AsobiAgent】スケジュール・出発駅を確認しました",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#06C755",
                "paddingAll": "15px",
                "contents": [
                    {"type": "text", "text": "AsobiAgent スケジュール同期", "weight": "bold", "color": "#FFFFFF", "size": "sm"},
                    {"type": "text", "text": "🎯 グループ希望を抽出しました", "weight": "bold", "color": "#FFFFFF", "size": "lg", "margin": "xs"}
                ]
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    {
                        "type": "box",
                        "layout": "vertical",
                        "backgroundColor": "#F7F9FA",
                        "paddingAll": "12px",
                        "cornerRadius": "8px",
                        "contents": [
                            {"type": "text", "text": f"📅 希望日時: {date_time}", "size": "sm", "weight": "bold", "color": "#1A365D"},
                            {"type": "text", "text": f"🍴 気分・希望: {preference}", "size": "sm", "color": "#4A5568", "margin": "xs"}
                        ]
                    },
                    {
                        "type": "text",
                        "text": "メンバー出発地:",
                        "size": "xs",
                        "color": "#888888",
                        "weight": "bold",
                        "margin": "sm"
                    },
                    {
                        "type": "box",
                        "layout": "vertical",
                        "spacing": "xs",
                        "contents": member_boxes
                    }
                ]
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": "⚡ 駅すぱあとAPIで全員の中間駅を公平に計算中...",
                        "size": "xs",
                        "color": "#06C755",
                        "align": "center",
                        "weight": "bold"
                    }
                ]
            }
        }
    }

def create_midpoint_flex(hub_data: Dict[str, Any]) -> Dict[str, Any]:
    """Flex message displaying the optimal fair midpoint station and member travel times."""
    hub_station = hub_data.get("hub_station", "渋谷")
    fairness = hub_data.get("fairness_score", 95)
    members = hub_data.get("members", {})
    alternatives = hub_data.get("alternatives", [])

    member_rows = []
    for name, info in members.items():
        time_min = info.get("travel_time", 25)
        transfers = info.get("transfers", 0)
        orig = info.get("origin", "")
        lines = " / ".join(info.get("lines", []))
        member_rows.append({
            "type": "box",
            "layout": "vertical",
            "margin": "md",
            "backgroundColor": "#F8FAFC",
            "paddingAll": "10px",
            "cornerRadius": "6px",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {"type": "text", "text": f"{name}（{orig}）", "weight": "bold", "size": "sm", "color": "#2D3748", "flex": 5},
                        {"type": "text", "text": f"⏱ 約{time_min}分", "weight": "bold", "size": "sm", "color": "#06C755", "align": "end", "flex": 3}
                    ]
                },
                {
                    "type": "text",
                    "text": f"乗換{transfers}回 • {lines[:25]}",
                    "size": "xxs",
                    "color": "#718096",
                    "margin": "xs"
                }
            ]
        })

    alt_text = f"候補駅: {' / '.join(alternatives[:3])}" if alternatives else ""

    return {
        "type": "flex",
        "altText": f"【AsobiAgent】公平な中間駅は「{hub_station}駅」です",
        "contents": {
            "type": "bubble",
            "size": "giga",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#1E293B",
                "paddingAll": "15px",
                "contents": [
                    {"type": "text", "text": "駅すぱあと (Ekispert) 中間地点バランサー", "color": "#38BDF8", "size": "xs", "weight": "bold"},
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "margin": "sm",
                        "contents": [
                            {"type": "text", "text": f"🚉 最適駅: {hub_station}駅", "color": "#FFFFFF", "size": "xl", "weight": "bold", "flex": 7},
                            {"type": "text", "text": f"公平度: {fairness}点", "color": "#FACC15", "size": "sm", "align": "end", "weight": "bold", "flex": 3}
                        ]
                    },
                    {"type": "text", "text": "※ダイヤ情報不使用・平均移動時間で公平に算出", "color": "#94A3B8", "size": "xxs", "margin": "xs"}
                ]
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "全員の移動時間バランス（公平差 ±5分以内）:", "size": "xs", "color": "#64748B", "weight": "bold"},
                    {"type": "box", "layout": "vertical", "contents": member_rows},
                    {
                        "type": "text",
                        "text": alt_text,
                        "size": "xxs",
                        "color": "#94A3B8",
                        "margin": "md",
                        "align": "center"
                    }
                ]
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "button",
                        "style": "primary",
                        "color": "#06C755",
                        "action": {
                            "type": "postback",
                            "label": f"✨ {hub_station}駅周辺の穴場スポットを探す",
                            "data": f"action=find_spots&station={hub_station}"
                        }
                    }
                ]
            }
        }
    }

def create_venues_carousel_flex(hub_station: str, venues: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Carousel Flex message showing 2-3 crowd-avoidance curated venues."""
    bubbles = []
    for idx, v in enumerate(venues):
        name = v.get("name", "穴場レストラン")
        genre = v.get("genre", "ダイニング")
        crowd_level = v.get("crowd_level", "混雑度: 低 (穴場 ⭐⭐⭐)")
        walk_min = v.get("walk_min", 4)
        budget = v.get("budget", "¥3,000〜¥4,500")
        crowd_reason = v.get("crowd_reason", "路地裏の隠れ家で週末でも席間隔が広く落ち着く空間")
        rating = v.get("rating", 4.4)
        v_id = v.get("id", f"venue_{idx+1}")

        bubble = {
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#0F172A",
                "contents": [
                    {"type": "text", "text": f"✨ 混雑回避おすすめ #{idx+1}", "color": "#F59E0B", "size": "xs", "weight": "bold"},
                    {"type": "text", "text": name, "color": "#FFFFFF", "size": "md", "weight": "bold", "margin": "xs"}
                ]
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": f"📍 {hub_station}駅 徒歩{walk_min}分", "size": "xs", "color": "#475569", "flex": 5},
                            {"type": "text", "text": f"★ {rating}", "size": "xs", "color": "#F59E0B", "weight": "bold", "align": "end", "flex": 2}
                        ]
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": f"🍴 {genre}", "size": "xs", "color": "#475569", "flex": 1},
                            {"type": "text", "text": f"💰 {budget}", "size": "xs", "color": "#475569", "align": "end", "flex": 1}
                        ]
                    },
                    {
                        "type": "box",
                        "layout": "vertical",
                        "backgroundColor": "#ECFDF5",
                        "paddingAll": "8px",
                        "cornerRadius": "6px",
                        "contents": [
                            {"type": "text", "text": f"🌿 {crowd_level}", "size": "xs", "weight": "bold", "color": "#059669"},
                            {"type": "text", "text": f"💡 {crowd_reason}", "size": "xxs", "color": "#065F46", "wrap": True, "margin": "xs"}
                        ]
                    }
                ]
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "button",
                        "style": "primary",
                        "color": "#06C755",
                        "height": "sm",
                        "action": {
                            "type": "postback",
                            "label": "🤖 自律AI電話で予約を依頼する",
                            "data": f"action=reserve&venue_id={v_id}&venue_name={name}"
                        }
                    }
                ]
            }
        }
        bubbles.append(bubble)

    return {
        "type": "flex",
        "altText": f"【AsobiAgent】{hub_station}駅周辺の混雑回避スポット提案",
        "contents": {
            "type": "carousel",
            "contents": bubbles
        }
    }

def create_reservation_ticket_flex(venue_name: str, date_time: str, pax: int, organizer: str, booking_id: str) -> Dict[str, Any]:
    """Confirmation ticket once Agent 4 executes the voice booking call."""
    return {
        "type": "flex",
        "altText": f"【AsobiAgent】{venue_name}の予約が完了しました！",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#06C755",
                "paddingAll": "15px",
                "contents": [
                    {"type": "text", "text": "AsobiAgent 自律予約エージェント", "color": "#FFFFFF", "size": "xs", "weight": "bold"},
                    {"type": "text", "text": "✅ 予約が確定しました！", "color": "#FFFFFF", "size": "lg", "weight": "bold", "margin": "xs"}
                ]
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    {
                        "type": "box",
                        "layout": "vertical",
                        "backgroundColor": "#F8FAFC",
                        "paddingAll": "12px",
                        "cornerRadius": "8px",
                        "contents": [
                            {"type": "text", "text": venue_name, "size": "md", "weight": "bold", "color": "#1E293B"},
                            {"type": "text", "text": f"📅 日時: {date_time}", "size": "sm", "color": "#475569", "margin": "xs"},
                            {"type": "text", "text": f"👥 人数: {pax}名様（代表者: {organizer}様）", "size": "sm", "color": "#475569", "margin": "xs"},
                            {"type": "text", "text": f"🎫 予約番号: #{booking_id}", "size": "xs", "color": "#06C755", "weight": "bold", "margin": "xs"}
                        ]
                    },
                    {
                        "type": "text",
                        "text": "📞 AIエージェントが店舗へ自動架電し、席予約を完了しました。",
                        "size": "xxs",
                        "color": "#64748B",
                        "align": "center"
                    }
                ]
            }
        }
    }
