from services.hours import closed_days, open_at, parse_ranges, ranges_for_day, split_time_ok

SAT, SUN, MON, TUE, FRI = 5, 6, 0, 1, 4
HP_OPEN = "月～金: 11:00～13:45 （料理L.O. 12:45 ドリンクL.O. 12:45）17:00～23:00 （料理L.O. 22:00 ドリンクL.O. 22:00）土: 17:00～23:00 （料理L.O. 22:00 ドリンクL.O. 22:00）"


def test_hotpepper_weekday_blocks():
    assert ranges_for_day(HP_OPEN, MON) == [(660, 825), (1020, 1380)]
    assert ranges_for_day(HP_OPEN, SAT) == [(1020, 1380)]
    assert ranges_for_day(HP_OPEN, SUN) == []
    assert open_at(HP_OPEN, "日、祝日", SAT, 13 * 60) is False      # Saturday lunch: closed
    assert open_at(HP_OPEN, "日、祝日", SAT, 19 * 60) is True
    assert open_at(HP_OPEN, "日、祝日", SUN, 19 * 60) is False


def test_time_out_style():
    open_part, close = split_time_ok("17〜23時／定休日は月・火曜")
    assert parse_ranges(open_part) == [(1020, 1380)]
    assert closed_days(close) == {MON, TUE}
    assert open_at(open_part, close, TUE, 19 * 60) is False
    assert open_at(open_part, close, FRI, 19 * 60) is True
    assert open_at(open_part, close, FRI, 12 * 60) is False
    assert parse_ranges("11時30分〜15時、17〜22時") == [(690, 900), (1020, 1320)]


def test_late_night_and_unclear():
    assert parse_ranges("18:00～翌2:00") == [(1080, 1560)]
    assert open_at("18:00～02:00", None, SAT, 60) is True      # Friday night running into Saturday
    assert open_at("お問い合わせください", None, SAT, 13 * 60) is None
    assert open_at("11:00～22:00", "不定休", SAT, 13 * 60) is True
    assert open_at(None, None, None, None) is None


def test_half_hours():
    assert parse_ranges("11時半〜14時半") == [(690, 870)]
    assert parse_ranges("11:30～14:00") == [(690, 840)]


def _to(hours, weekday, hhmm):
    open_part, close = split_time_ok(hours)
    h, m = map(int, hhmm.split(":"))
    return open_at(open_part, close, weekday, h * 60 + m)


def test_real_time_out_strings():
    WED, THU = 2, 3
    weekend_lunch = "17～24時（土・日曜・祝日は12～24時）／定休日は不定休"
    assert _to(weekend_lunch, SAT, "13:00") is True
    assert _to(weekend_lunch, MON, "13:00") is False
    assert _to(weekend_lunch, MON, "19:00") is True
    late = "10〜17時（木～日曜は24時まで）"
    assert _to(late, THU, "20:00") is None          # the exception gives no clear range: don't guess
    assert _to(late, MON, "20:00") is False
    two_blocks = ("18～22時（入店は閉店の1時間前まで）、土・日曜・祝日は11時30分？14時、18～22時"
                  "（入店は閉店の1時間30分前まで）／定休日は木曜")
    assert _to(two_blocks, SAT, "12:00") is True
    assert _to(two_blocks, MON, "12:00") is False
    assert _to(two_blocks, THU, "19:00") is False
    assert _to("18〜24時（L.O.23時）／定休日は月・土・日曜", FRI, "19:00") is True
    assert _to("18〜24時（L.O.23時）／定休日は月・土・日曜", SAT, "19:00") is False
    assert _to("平日11〜15時、土日は11〜20時", SAT, "18:00") is True
    assert _to("平日11〜15時、土日は11〜20時", WED, "18:00") is False
