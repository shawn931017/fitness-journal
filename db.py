"""資料庫：sqlite3 單一檔案，所有查詢集中在這裡。"""
import sqlite3
from collections import OrderedDict

from flask import current_app, g

import goals
import nutrition

SCHEMA = """
CREATE TABLE IF NOT EXISTS exercises (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    body_part   TEXT    NOT NULL,              -- 胸 / 背 / 腿 / 其他
    movement    TEXT    NOT NULL,              -- 動作，例如「上斜臥推」
    equipment   TEXT    NOT NULL,              -- 器材，例如「啞鈴」「上斜胸推機」
    per_hand    INTEGER NOT NULL DEFAULT 0,    -- 1 = 重量為單手重量（啞鈴）
    step        REAL    NOT NULL DEFAULT 2.5,  -- 加減按鈕每次調整的公斤數
    active      INTEGER NOT NULL DEFAULT 1,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    UNIQUE (movement, equipment)
);

CREATE TABLE IF NOT EXISTS sets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    exercise_id INTEGER NOT NULL REFERENCES exercises(id),
    date        TEXT    NOT NULL,              -- YYYY-MM-DD（台灣時間）
    weight      REAL    NOT NULL,
    reps        INTEGER NOT NULL,
    is_warmup   INTEGER NOT NULL DEFAULT 0,
    is_demo     INTEGER NOT NULL DEFAULT 0,    -- 1 = 測試資料
    client_id   TEXT UNIQUE,                   -- 防止網路重送時重複寫入
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sets_ex_date ON sets (exercise_id, date);
CREATE INDEX IF NOT EXISTS idx_sets_date ON sets (date);

CREATE TABLE IF NOT EXISTS daily (
    date        TEXT PRIMARY KEY,              -- 睡眠歸在起床日
    body_weight REAL,
    sleep_hours REAL,
    food        TEXT,
    is_demo     INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS foods (              -- 食物營養表，數值皆為「每一單位」
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    aliases     TEXT    NOT NULL DEFAULT '',   -- 逗號分隔的別名
    category    TEXT    NOT NULL DEFAULT '自訂',
    unit        TEXT    NOT NULL,              -- 顆 / 碗 / 個 / 杯 …
    grams       REAL,                          -- 每單位約幾公克（可空白，用於 200g 這類換算）
    kcal        REAL    NOT NULL,
    carb        REAL    NOT NULL,
    protein     REAL    NOT NULL,
    fat         REAL    NOT NULL,
    is_builtin  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

BODY_PARTS = ["胸", "背", "腿", "其他"]

# (部位, 動作, 器材, 單手重量, 每次加減公斤)
DEFAULT_EXERCISES = [
    ("胸", "槓鈴臥推", "槓鈴", 0, 2.5),
    ("胸", "槓鈴臥推", "史密斯機", 0, 2.5),
    ("胸", "啞鈴臥推", "啞鈴", 1, 2),
    ("胸", "上斜臥推", "啞鈴", 1, 2),
    ("胸", "上斜臥推", "上斜胸推機", 0, 5),
    ("胸", "上斜臥推", "史密斯機", 0, 2.5),
    ("胸", "坐姿胸推", "胸推機", 0, 5),
    ("胸", "夾胸", "蝴蝶機", 0, 5),
    ("胸", "夾胸", "滑輪", 0, 2.5),
    ("胸", "雙槓撐體", "自體重", 0, 2.5),
    ("背", "引體向上", "自體重", 0, 2.5),
    ("背", "引體向上", "輔助機", 0, 5),
    ("背", "滑輪下拉", "下拉機", 0, 5),
    ("背", "坐姿划船", "滑輪", 0, 5),
    ("背", "坐姿划船", "划船機", 0, 5),
    ("背", "槓鈴划船", "槓鈴", 0, 2.5),
    ("背", "單臂划船", "啞鈴", 1, 2),
    ("背", "硬舉", "槓鈴", 0, 5),
    ("腿", "深蹲", "槓鈴", 0, 2.5),
    ("腿", "深蹲", "史密斯機", 0, 2.5),
    ("腿", "腿推", "推腿機", 0, 10),
    ("腿", "羅馬尼亞硬舉", "槓鈴", 0, 2.5),
    ("腿", "羅馬尼亞硬舉", "啞鈴", 1, 2),
    ("腿", "保加利亞分腿蹲", "啞鈴", 1, 2),
    ("腿", "腿伸展", "腿伸展機", 0, 5),
    ("腿", "腿彎舉", "腿彎舉機", 0, 5),
    ("腿", "提踵", "提踵機", 0, 5),
]


# ---------------------------------------------------------------- 連線

def get_db():
    if "db" not in g:
        conn = sqlite3.connect(current_app.config["DATABASE"])
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM exercises").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO exercises (body_part, movement, equipment, per_hand, step, sort_order)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [(*row, i) for i, row in enumerate(DEFAULT_EXERCISES)],
        )
    # 內建食物：只補上還沒有的名稱，不覆蓋使用者改過的數值
    conn.executemany(
        "INSERT OR IGNORE INTO foods (category, name, aliases, unit, grams, kcal, carb, protein, fat, is_builtin)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
        nutrition.BUILTIN_FOODS,
    )
    conn.commit()


def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()


# ---------------------------------------------------------------- 設定

def get_setting(key, default=None):
    row = get_db().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    conn = get_db()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


def target_weight():
    try:
        return float(get_setting("target_weight", "80"))
    except ValueError:
        return 80.0


def protein_per_kg():
    try:
        return float(get_setting("protein_per_kg", "1.6"))
    except ValueError:
        return 1.6


def latest_body_weight(on_or_before):
    row = get_db().execute(
        "SELECT body_weight FROM daily WHERE body_weight IS NOT NULL AND date <= ? ORDER BY date DESC LIMIT 1",
        (on_or_before,),
    ).fetchone()
    return row["body_weight"] if row else None


def weights_until(end):
    """[(日期, 體重)]，依日期遞增，含 end 當天。"""
    rows = get_db().execute(
        "SELECT date, body_weight FROM daily WHERE body_weight IS NOT NULL AND date <= ? ORDER BY date", (end,)
    ).fetchall()
    return [(r["date"], r["body_weight"]) for r in rows]


# ---------------------------------------------------------------- 每日目標

def goal_profile():
    if "goal_profile" not in g:
        g.goal_profile = goals.load_profile(get_setting)
    return g.goal_profile


def targets_on(day):
    return goals.targets(goal_profile(), latest_body_weight(day))


# ---------------------------------------------------------------- 食物營養

def list_foods():
    return get_db().execute(
        "SELECT * FROM foods ORDER BY is_builtin, category, name"
    ).fetchall()


def food_index():
    """同一個請求內只建一次索引。"""
    if "food_index" not in g:
        g.food_index = nutrition.FoodIndex(list_foods())
    return g.food_index


def estimate(text):
    return nutrition.parse(text, food_index())


def estimates_between(start, end):
    """{日期: 估算結果}，只含有飲食短記的日子。"""
    return {d: estimate(r["food"]) for d, r in daily_between(start, end).items() if r["food"]}


# ---------------------------------------------------------------- 動作與器材

def get_exercise(ex_id):
    return get_db().execute("SELECT * FROM exercises WHERE id = ?", (ex_id,)).fetchone()


def list_exercises(active_only=True):
    sql = "SELECT * FROM exercises"
    if active_only:
        sql += " WHERE active = 1"
    sql += " ORDER BY CASE body_part WHEN '胸' THEN 0 WHEN '背' THEN 1 WHEN '腿' THEN 2 ELSE 3 END, sort_order, id"
    return get_db().execute(sql).fetchall()


def variants_of(movement, active_only=True):
    sql = "SELECT * FROM exercises WHERE movement = ?"
    if active_only:
        sql += " AND active = 1"
    return get_db().execute(sql + " ORDER BY sort_order, id", (movement,)).fetchall()


def last_dates_by_exercise():
    rows = get_db().execute("SELECT exercise_id, MAX(date) AS d FROM sets GROUP BY exercise_id").fetchall()
    return {r["exercise_id"]: r["d"] for r in rows}


def grouped_movements(active_only=True):
    """{部位: [ {movement, variants:[row...], last_date, default_id} ]}"""
    last = last_dates_by_exercise()
    groups = OrderedDict((bp, OrderedDict()) for bp in BODY_PARTS)
    for ex in list_exercises(active_only):
        bp = ex["body_part"] if ex["body_part"] in groups else "其他"
        mv = groups[bp].setdefault(ex["movement"], {"movement": ex["movement"], "variants": [], "last_date": None})
        mv["variants"].append(ex)
        d = last.get(ex["id"])
        if d and (mv["last_date"] is None or d > mv["last_date"]):
            mv["last_date"] = d
            mv["default_id"] = ex["id"]
    out = OrderedDict()
    for bp, mvs in groups.items():
        items = []
        for mv in mvs.values():
            mv.setdefault("default_id", mv["variants"][0]["id"])
            items.append(mv)
        if items:
            out[bp] = items
    return out


# ---------------------------------------------------------------- 逐組紀錄

def label_sets(rows):
    """依儲存順序編號：熱身組標「熱身」，正式組為第 1、2、3… 組。"""
    out, n = [], 0
    for r in rows:
        d = dict(r)
        if d["is_warmup"]:
            d["label"] = "熱身"
        else:
            n += 1
            d["label"] = f"第 {n} 組"
            d["work_no"] = n
        out.append(d)
    return out


def sets_on(ex_id, day):
    rows = get_db().execute(
        "SELECT * FROM sets WHERE exercise_id = ? AND date = ? ORDER BY id", (ex_id, day)
    ).fetchall()
    return label_sets(rows)


def previous_session(ex_id, before_day):
    row = get_db().execute(
        "SELECT MAX(date) AS d FROM sets WHERE exercise_id = ? AND date < ?", (ex_id, before_day)
    ).fetchone()
    if not row or not row["d"]:
        return None, []
    return row["d"], sets_on(ex_id, row["d"])


def get_set(set_id):
    return get_db().execute(
        "SELECT s.*, e.movement, e.equipment, e.per_hand, e.step FROM sets s"
        " JOIN exercises e ON e.id = s.exercise_id WHERE s.id = ?",
        (set_id,),
    ).fetchone()


def add_set(ex_id, day, weight, reps, is_warmup, client_id, now):
    conn = get_db()
    if client_id:
        dup = conn.execute("SELECT id FROM sets WHERE client_id = ?", (client_id,)).fetchone()
        if dup:
            return dup["id"]
    cur = conn.execute(
        "INSERT INTO sets (exercise_id, date, weight, reps, is_warmup, client_id, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ex_id, day, weight, reps, int(is_warmup), client_id or None, now),
    )
    conn.commit()
    return cur.lastrowid


def day_workout(day):
    """某天所有動作的逐組紀錄，依第一次記錄的先後排列。"""
    rows = get_db().execute(
        "SELECT s.*, e.movement, e.equipment, e.per_hand, e.body_part FROM sets s"
        " JOIN exercises e ON e.id = s.exercise_id WHERE s.date = ? ORDER BY s.id",
        (day,),
    ).fetchall()
    groups = OrderedDict()
    for r in rows:
        groups.setdefault(r["exercise_id"], []).append(r)
    return [
        {"exercise_id": ex_id, "movement": rs[0]["movement"], "equipment": rs[0]["equipment"],
         "per_hand": rs[0]["per_hand"], "body_part": rs[0]["body_part"], "sets": label_sets(rs)}
        for ex_id, rs in groups.items()
    ]


# ---------------------------------------------------------------- 生活簡記

def get_daily(day):
    return get_db().execute("SELECT * FROM daily WHERE date = ?", (day,)).fetchone()


def save_daily(day, body_weight, sleep_hours, food, now):
    conn = get_db()
    if body_weight is None and sleep_hours is None and not food:
        conn.execute("DELETE FROM daily WHERE date = ?", (day,))
    else:
        conn.execute(
            "INSERT INTO daily (date, body_weight, sleep_hours, food, is_demo, updated_at)"
            " VALUES (?, ?, ?, ?, 0, ?)"
            " ON CONFLICT(date) DO UPDATE SET body_weight = excluded.body_weight,"
            " sleep_hours = excluded.sleep_hours, food = excluded.food, is_demo = 0,"
            " updated_at = excluded.updated_at",
            (day, body_weight, sleep_hours, food or None, now),
        )
    conn.commit()


def daily_between(start, end):
    rows = get_db().execute(
        "SELECT * FROM daily WHERE date BETWEEN ? AND ? ORDER BY date", (start, end)
    ).fetchall()
    return {r["date"]: r for r in rows}


def has_demo_data():
    conn = get_db()
    return bool(
        conn.execute("SELECT 1 FROM sets WHERE is_demo = 1 LIMIT 1").fetchone()
        or conn.execute("SELECT 1 FROM daily WHERE is_demo = 1 LIMIT 1").fetchone()
    )


def clear_demo_data():
    conn = get_db()
    conn.execute("DELETE FROM sets WHERE is_demo = 1")
    conn.execute("DELETE FROM daily WHERE is_demo = 1")
    conn.commit()
