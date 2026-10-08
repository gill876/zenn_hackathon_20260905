# Time Out Japan: what it adds (deep dive, 2026-10-09)

**Rules.** Time Out's terms forbid copying, reposting or translating their content without permission
(無断で複製、転載、翻訳することを禁じます). robots.txt allows the venue pages. So the crawler keeps facts only
(name, coordinates, address, phone, opening hours, URL), and the bot always links to Time Out. It never shows their
reviews or photos. To show excerpts or images, ask Time Out Tokyo for permission or a partnership.

**What's there.** Venue pages carry structured data (schema.org Review → itemReviewed: name, geo, address, telephone),
and opening hours are in the page. Tokyo has about 12,000 venue pages (レストラン 9,842, バー 1,309, …). The Osaka
edition is new and small (~270 venue pages). Nothing covers the rest of Japan, where HotPepper and Ekispert still work.

**Index built** (pages updated since 2024, 1 request every 2 s, 0 errors): **1,793 places** (Tokyo 1,555, Osaka 238).
1,252 have a phone number and 1,737 have opening hours.

**Coverage around meeting stations** (`python -m jobs.timeout_report`):

| Station | Time Out ≤1 km | ≤500 m | HotPepper top 30 also on Time Out |
|---|---|---|---|
| 渋谷 | 116 | 57 | 0 |
| 銀座 | 108 | 56 | 1 |
| 表参道 | 107 | 26 | 1 |
| 有楽町 | 95 | 36 | 2 |
| 中目黒 | 71 | 31 | 0 |
| 新宿 | 66 | 29 | 0 |
| 東京 | 63 | 30 | 1 |
| 恵比寿 | 56 | 26 | 0 |
| 六本木 / 神田 / 浅草 / 梅田 | 53 / 50 / 44 / 40 | 21 / 11 / 19 / 18 | 1 / 0 / 0 / 0 |
| 池袋 / 秋葉原 / 高円寺 / 吉祥寺 / 下北沢 / 三軒茶屋 | 20–28 | 10–21 | 0 |
| 上野 / 横浜 / 品川 | 20 / 10 / 6 | 4 / 6 / 2 | 1 / 0 / 0 |

**Conclusion.** The two sources barely overlap (badge on 7 of 630 = 1.1% of HotPepper's top results): HotPepper is mostly
chains and izakaya that pay to be listed; Time Out picks independent places. So Time Out is worth more as a **second
source of candidates** (one per page of three, already built) than as a badge. It's strongest in central Tokyo.

**Ideas not built:** a wider crawl (2022–2023 pages, ~2,000 more, ~2 h); Time Out's things-to-do / art / music pages
for outings that aren't meals; asking Time Out for a partnership so cards can show their photos and blurbs.
