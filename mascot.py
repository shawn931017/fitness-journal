"""吉祥物「小鈴」：一顆壺鈴，本週紀錄越多長得越大。

成長規則只看「有沒有記錄」，不判斷飲食或睡眠好不好（規則需再與受訪者確認）：
  - 本週（週一起算）每個有訓練紀錄的日子 +2 點
  - 每個有生活簡記（體重、睡眠或飲食任一項）的日子 +1 點
  - 連續 3 天（含今天）都沒有任何紀錄 → 顯示想睡的樣子
"""
from datetime import timedelta

STAGES = [
    (0, "小鈴還在睡"),
    (1, "小鈴醒了"),
    (4, "小鈴長大了"),
    (7, "小鈴練出線條"),
    (10, "小鈴滿滿能量"),
]
TRAIN_POINTS = 2
LIFE_POINTS = 1
TIRED_AFTER_DAYS = 3

COLORS = ["#a9b5b2", "#5f9e8f", "#3f8a78", "#2f7d6d", "#256b5c"]
SIZES = [26, 32, 38, 43, 47]
ORANGE = "#d9822b"
INK = "#1f2a27"


def weekly_state(conn, today):
    monday = today - timedelta(days=today.weekday())
    start, end = monday.isoformat(), today.isoformat()
    train_days = {r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM sets WHERE date BETWEEN ? AND ?", (start, end))}
    life_days = {r[0] for r in conn.execute(
        "SELECT date FROM daily WHERE date BETWEEN ? AND ?"
        " AND (body_weight IS NOT NULL OR sleep_hours IS NOT NULL OR food IS NOT NULL)", (start, end))}
    points = TRAIN_POINTS * len(train_days) + LIFE_POINTS * len(life_days)

    stage = 0
    for i, (threshold, _name) in enumerate(STAGES):
        if points >= threshold:
            stage = i
    next_at = STAGES[stage + 1][0] if stage + 1 < len(STAGES) else None

    last = conn.execute(
        "SELECT MAX(d) FROM (SELECT MAX(date) AS d FROM sets UNION ALL SELECT MAX(date) FROM daily)"
    ).fetchone()[0]
    tired = bool(last) and last <= (today - timedelta(days=TIRED_AFTER_DAYS)).isoformat()

    if tired:
        message = "好幾天沒見到你了，記一筆把小鈴叫醒吧。"
    elif stage == 0:
        message = "新的一週開始了，記下第一筆，小鈴就會醒來。"
    elif next_at is not None:
        message = f"再 {next_at - points} 點，小鈴就會再長大一點。"
    else:
        message = "這週的紀錄很完整，小鈴長到最大了！"

    return {
        "stage": stage,
        "name": STAGES[stage][1],
        "points": points,
        "train_days": len(train_days),
        "life_days": len(life_days),
        "next_at": next_at,
        "tired": tired,
        "message": message,
        "svg": render_svg(stage, tired),
    }


def render_svg(stage, tired=False, size=150):
    r = SIZES[stage]
    color = COLORS[stage]
    cx, cy = 80, 128 - r
    rx = r * 1.06
    parts = [f'<svg viewBox="0 0 160 150" width="{size}" height="{size * 150 // 160}" '
             f'xmlns="http://www.w3.org/2000/svg" role="img" aria-label="吉祥物小鈴">']
    parts.append(f'<ellipse cx="80" cy="134" rx="{r * 0.95:.1f}" ry="5" fill="#000" opacity=".08"/>')

    # 把手
    hx = r * 0.55
    hy = cy - r * 0.78
    top = cy - r * 1.6
    parts.append(f'<path d="M {cx - hx:.1f} {hy:.1f} C {cx - hx:.1f} {top:.1f}, {cx + hx:.1f} {top:.1f}, '
                 f'{cx + hx:.1f} {hy:.1f}" fill="none" stroke="{color}" stroke-width="{r * 0.3:.1f}" '
                 f'stroke-linecap="round"/>')

    # 第 5 階段：兩隻秀肌肉的手臂
    if stage >= 4 and not tired:
        for sgn in (-1, 1):
            x0 = cx + sgn * rx * 0.92
            parts.append(f'<path d="M {x0:.1f} {cy + 4:.1f} Q {x0 + sgn * 16:.1f} {cy + 2:.1f} '
                         f'{x0 + sgn * 14:.1f} {cy - 16:.1f}" fill="none" stroke="{color}" stroke-width="8" '
                         f'stroke-linecap="round"/>')
            parts.append(f'<circle cx="{x0 + sgn * 14:.1f}" cy="{cy - 19:.1f}" r="6" fill="{color}"/>')

    # 身體
    parts.append(f'<ellipse cx="{cx}" cy="{cy}" rx="{rx:.1f}" ry="{r}" fill="{color}"/>')
    parts.append(f'<ellipse cx="{cx - r * 0.45:.1f}" cy="{cy - r * 0.45:.1f}" rx="{r * 0.28:.1f}" '
                 f'ry="{r * 0.16:.1f}" fill="#fff" opacity=".22" transform="rotate(-30 {cx - r * 0.45:.1f} '
                 f'{cy - r * 0.45:.1f})"/>')

    # 頭帶
    if stage >= 3:
        bw, bh = r * 1.78, r * 0.17
        by = cy - r * 0.5
        parts.append(f'<rect x="{cx - bw / 2:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
                     f'rx="{bh / 2:.1f}" fill="{ORANGE}"/>')
        kx = cx + bw / 2 - 2
        parts.append(f'<path d="M {kx:.1f} {by + bh / 2:.1f} l 10 -6 M {kx:.1f} {by + bh / 2:.1f} l 11 4" '
                     f'stroke="{ORANGE}" stroke-width="3.5" stroke-linecap="round"/>')

    # 臉
    ey = cy - r * 0.02
    ex = r * 0.34
    sleepy = stage == 0 or tired
    for sgn in (-1, 1):
        x = cx + sgn * ex
        if sleepy:
            parts.append(f'<path d="M {x - 4.5:.1f} {ey:.1f} Q {x:.1f} {ey + 3.5:.1f} {x + 4.5:.1f} {ey:.1f}" '
                         f'fill="none" stroke="{INK}" stroke-width="2.2" stroke-linecap="round"/>')
        else:
            er = max(3.2, r * 0.095)
            parts.append(f'<circle cx="{x:.1f}" cy="{ey:.1f}" r="{er:.1f}" fill="{INK}"/>')
            parts.append(f'<circle cx="{x + er * 0.35:.1f}" cy="{ey - er * 0.35:.1f}" r="{er * 0.35:.1f}" fill="#fff"/>')
    if stage >= 2 and not tired:
        for sgn in (-1, 1):
            parts.append(f'<ellipse cx="{cx + sgn * r * 0.58:.1f}" cy="{ey + r * 0.24:.1f}" rx="{r * 0.13:.1f}" '
                         f'ry="{r * 0.08:.1f}" fill="#f4a3a3" opacity=".75"/>')

    my = cy + r * 0.3
    mw = r * 0.17
    if sleepy:
        parts.append(f'<ellipse cx="{cx}" cy="{my:.1f}" rx="{mw * 0.45:.1f}" ry="{mw * 0.35:.1f}" fill="{INK}" opacity=".7"/>')
    elif stage >= 4:
        parts.append(f'<path d="M {cx - mw * 1.3:.1f} {my - 2:.1f} Q {cx:.1f} {my + mw * 2:.1f} {cx + mw * 1.3:.1f} '
                     f'{my - 2:.1f} Z" fill="{INK}"/>')
    else:
        parts.append(f'<path d="M {cx - mw:.1f} {my:.1f} Q {cx:.1f} {my + mw:.1f} {cx + mw:.1f} {my:.1f}" '
                     f'fill="none" stroke="{INK}" stroke-width="2.2" stroke-linecap="round"/>')

    if sleepy:
        zx, zy = cx + rx * 0.75, cy - r * 1.05
        parts.append(f'<text x="{zx:.1f}" y="{zy:.1f}" font-size="13" font-weight="700" fill="#8a9895" '
                     f'font-family="sans-serif">z</text>')
        parts.append(f'<text x="{zx + 9:.1f}" y="{zy - 10:.1f}" font-size="10" font-weight="700" fill="#a9b5b2" '
                     f'font-family="sans-serif">z</text>')
    if tired:
        sx, sy = cx - rx * 0.8, cy - r * 0.55
        parts.append(f'<path d="M {sx:.1f} {sy:.1f} q -5 8 0 11 q 5 -3 0 -11 Z" fill="#9cc9e8"/>')
    if stage >= 4 and not tired:
        for (x, y, s) in ((26, 30, 7), (136, 40, 6), (128, 14, 4)):
            parts.append(f'<path d="M {x} {y - s} L {x + s * 0.3} {y - s * 0.3} L {x + s} {y} L {x + s * 0.3} '
                         f'{y + s * 0.3} L {x} {y + s} L {x - s * 0.3} {y + s * 0.3} L {x - s} {y} L {x - s * 0.3} '
                         f'{y - s * 0.3} Z" fill="{ORANGE}"/>')
    parts.append("</svg>")
    return "".join(parts)
