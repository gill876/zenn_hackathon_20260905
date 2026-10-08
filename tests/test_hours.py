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
