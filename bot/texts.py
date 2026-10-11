"""Japanese copy for plain-text replies. Card copy lives in services/line_flex.py."""

GREETING = "友だち追加ありがとうございます！AsobiAgentは招待制です。お持ちの招待コードを送ってください。"
GREETING_VERIFIED = "認証済みです。AsobiAgentをグループに招待して「有効化する」を押すと使えます。"
GREETING_ADMIN = "管理者として登録されています。/help でコマンドを確認できます。"
ASK_FOR_CODE = "招待コード（例：ASBI-7KQ2-M9XD）を送ってください。"
CODE_UNKNOWN = "この招待コードは見つかりませんでした。入力をご確認ください。"
CODE_USED = "この招待コードはすでに使われています。"
CODE_EXPIRED = "この招待コードは有効期限が切れています。"
ALREADY_VERIFIED = "すでに認証済みです。グループに招待して使ってください。"


def verified(groups_left: int) -> str:
    return f"認証しました ✅\nグループに招待して「有効化する」を押すと使えます。\n有効化できるグループ：あと{groups_left}つ"


ADMIN_HELP = (
    "管理者コマンド\n"
    "プロフィール … 好きなお店・出発駅を登録\n"
    "/invite 3 … 招待コードを3つ作る（最大20）\n"
    "/stats … 今日の利用状況\n"
    "/limits … 現在の上限設定"
)

NOT_VERIFIED = "有効化できるのは認証済みのメンバーだけです。AsobiAgentを友だち追加して、招待コードを送ってください。"
USER_GROUP_LIMIT = "有効化できるグループの上限に達しています。管理者にご連絡ください。"
ALREADY_ACTIVE = "このグループではすでに有効になっています。"
USE_PHONE_APP = "スマホのLINEアプリから操作してください（PC版のLINEからはボタンを受け付けられません）。"
USED_UP = "このグループは無料プラン（1回）を使い切っています。追加で使いたい場合は、管理者にご連絡ください。"
SEARCHES_USED_UP = "このグループの検索回数を使い切りました。ご利用ありがとうございました！"
PENDING_TIMEOUT = "24時間以内に有効化されなかったため、AsobiAgentはこのグループを退出します。"
ACTIVE_EXPIRED = "有効期限が過ぎたため、AsobiAgentはこのグループを退出します。ご利用ありがとうございました！"
GOODBYE = "このグループの無料プラン（1回）を使い切りました。ご利用ありがとうございました！AsobiAgentはこのグループを退出します。"
DAILY_LIMIT = "本日の受付は終了しました。明日またお試しください。"
FIX_STATION = "「〇〇から」のように、出発駅をもう一度送ってください。"
STALE_BUTTON = "このボタンは前のプランのものです。新しいカードのボタンを使ってください。"
SEARCHING = "いま検索中です。少しお待ちください。"
NO_HUB = "全員が行きやすい駅が見つかりませんでした。出発駅を見直して、もう一度「もう探して」を押してください。"
NO_VENUES = "近くに条件に合うお店が見つかりませんでした。条件を変えてもう一度お試しください。"
SEARCH_FAILED = "検索中にエラーが起きました。少し待ってから、もう一度「✅ これでOK」か「もう探して」を押してください。"
NO_MORE = "これ以上の候補はありません。条件を変えて探すか、今の候補から選んでください。"
NOT_PARTICIPANT = "投票できるのは参加メンバーだけです。"
VOTING_HINT = "気に入ったお店に投票してください。ほかの希望は「@AsobiAgent 和食がいい」のように送れます。"
NEED_TWO = "検索するには、出発駅のわかる参加者が2人以上必要です。"


def gathering_status(missing: list[str]) -> str:
    if missing:
        return "参加メンバーを募集中です。まだ出発駅がわからない人：" + "、".join(missing)
    return "参加メンバーを募集中です。参加する人はボタンを押して、出発駅を送ってください。"


def organizer_only(name: str) -> str:
    return f"この操作は幹事（{name}さん）だけが使えます。"


def full(limit: int) -> str:
    return f"参加できるのは{limit}人までです。"


def when_noted(when: str) -> str:
    return f"日時：{when} で覚えました。"


def refined(summary: str) -> str:
    return f"条件を変えて探しました（{summary}）。" if summary else "条件を変えて探しました。"

SUGGEST_HOW = ("お店のリンクか名前を、@AsobiAgent をつけて送ってください。\n"
               "例：@AsobiAgent 提案 https://www.hotpepper.jp/…\n例：@AsobiAgent 提案 利久 秋葉原")
SUGGEST_FULL = "提案できるのは1回のプランで3軒までです。今の候補から選んでください。"
SUGGEST_DUP = "そのお店はもう候補に入っています。"
SUGGEST_FAILED = "お店を調べられませんでした。少し待ってから、もう一度送ってください。"
POLL_PLAN_RUNNING = "いまプランを進めているところです。決まってから日程調整をしてください。"
POLL_UNAVAILABLE = "日程調整は準備中です。"
POLL_NO_ANSWERS = "まだ回答がありません。みんなに「回答する」から○△×をつけてもらってください。"


def need_stations(missing: list[str]) -> str:
    return "出発駅がわからない人がいます：" + "、".join(missing) + "\n「〇〇から」と送ってください。そろったらすぐにお店を探します。"

POLL_ALL_ANSWERED = "全員が回答したので、日程調整を締め切りました。"


def from_poll(date_label: str) -> str:
    return f"日程調整の結果（{date_label}）でプランを立てます。"
