"""跨月測試資料：所有資料列都標記 is_demo = 1，畫面上會顯示「測試」。

模擬胸／背／腿每週三練（一、三、五），採「次數做到 12 下就加重」的雙重漸進，
偶爾因訓練椅被占用改做上斜胸推機，並隨機漏記體重、睡眠與飲食。
"""
import random
from datetime import timedelta

PLAN = {
    0: [("槓鈴臥推", "槓鈴"), ("上斜臥推", "啞鈴"), ("夾胸", "蝴蝶機")],
    2: [("滑輪下拉", "下拉機"), ("坐姿划船", "滑輪"), ("單臂划船", "啞鈴")],
    4: [("深蹲", "槓鈴"), ("腿推", "推腿機"), ("腿彎舉", "腿彎舉機")],
}
SWAP = {("上斜臥推", "啞鈴"): ("上斜臥推", "上斜胸推機")}  # 訓練椅被占用時的替代器材
START = {
    ("槓鈴臥推", "槓鈴"): 60, ("上斜臥推", "啞鈴"): 20, ("上斜臥推", "上斜胸推機"): 40,
    ("夾胸", "蝴蝶機"): 35, ("滑輪下拉", "下拉機"): 50, ("坐姿划船", "滑輪"): 45,
    ("單臂划船", "啞鈴"): 22, ("深蹲", "槓鈴"): 80, ("腿推", "推腿機"): 140, ("腿彎舉", "腿彎舉機"): 35,
}
FOODS = [
    "早餐蛋餅、豆漿，午餐雞腿便當，晚餐牛肉麵",
    "早餐三明治、午餐自助餐、晚餐火鍋",
    "早餐飯糰、午餐滷肉飯加蛋、燙青菜，晚餐雞胸沙拉、高蛋白一杯",
    "早餐燕麥、牛奶，午餐咖哩飯，晚餐鍋貼十顆",
    "早餐吐司加蛋、午餐炒飯、晚餐便當，宵夜鹽酥雞",
    "早餐蛋餅、午餐義大利麵、晚餐壽司八個，訓練後高蛋白",
    "早餐饅頭夾蛋、午餐牛肉燴飯、晚餐水餃十五顆",
    "早餐御飯糰、無糖豆漿，午餐麻辣燙，晚餐白飯兩碗、雞腿",
    "早餐蛋餅、午餐健身餐、晚餐鍋貼20顆、無糖豆漿",
    # 吃得比較多的日子（增重時熱量、蛋白質可能達標）
    "早餐蛋餅、豆漿，午餐雞腿便當、白飯一碗，練完高蛋白一杯、香蕉，晚餐牛肉麵、滷蛋兩顆，宵夜鍋貼十顆",
    "早餐飯糰、大杯豆漿，午餐排骨便當，下午高蛋白一杯，晚餐雞腿便當、白飯一碗，宵夜鹽酥雞",
    "早餐吐司加蛋、牛奶，午餐炒飯、滷肉飯，晚餐火鍋、白飯兩碗，練完高蛋白",
]


def _round_to(x, step):
    return round(round(x / step) * step, 2)


def seed(conn, today, days=45, rng_seed=20261110):
    rng = random.Random(rng_seed)
    ex_ids = {(r["movement"], r["equipment"]): (r["id"], r["step"])
              for r in conn.execute("SELECT id, movement, equipment, step FROM exercises")}
    real_set_days = {r[0] for r in conn.execute("SELECT DISTINCT date FROM sets WHERE is_demo = 0")}
    real_daily_days = {r[0] for r in conn.execute("SELECT date FROM daily WHERE is_demo = 0")}

    state = {k: {"w": w, "r": rng.choice([9, 10])} for k, w in START.items()}
    set_rows, daily_rows = [], []
    start = today - timedelta(days=days)

    for i in range(days):
        d = start + timedelta(days=i)
        ds = d.isoformat()

        # ---- 訓練
        if d.weekday() in PLAN and ds not in real_set_days and rng.random() > 0.1:
            minute = 0
            for key in PLAN[d.weekday()]:
                if key in SWAP and rng.random() < 0.3:
                    key = SWAP[key]
                if key not in ex_ids:
                    continue
                ex_id, step = ex_ids[key]
                st = state[key]
                stamp = lambda: f"{ds}T19:{minute:02d}:00+08:00"
                # 熱身一組
                set_rows.append((ex_id, ds, _round_to(st["w"] * 0.5, step), 10, 1, stamp()))
                minute += 3
                reps = st["r"]
                for n in range(3):
                    set_rows.append((ex_id, ds, st["w"], max(5, reps - n - rng.choice([0, 0, 1])), 0, stamp()))
                    minute += 3
                # 雙重漸進：第一組做到 12 下就加重（次數掉回 8～9），否則下次多 0～2 下
                if reps >= 12:
                    st["w"] = round(st["w"] + step, 2)
                    st["r"] = rng.choice([8, 9])
                else:
                    st["r"] = min(12, reps + rng.choice([0, 1, 1, 2]))

        # ---- 生活簡記
        if ds not in real_daily_days:
            bw = round(74.2 + 0.03 * i + rng.uniform(-0.35, 0.35), 1) if rng.random() < 0.65 else None
            sleep = rng.choice([5.5, 6, 6.5, 7, 7, 7.5, 8]) if rng.random() < 0.85 else None
            food = rng.choice(FOODS) if rng.random() < 0.7 else None
            if bw is not None or sleep is not None or food is not None:
                daily_rows.append((ds, bw, sleep, food, f"{ds}T23:00:00+08:00"))

    conn.executemany(
        "INSERT INTO sets (exercise_id, date, weight, reps, is_warmup, is_demo, created_at)"
        " VALUES (?, ?, ?, ?, ?, 1, ?)", set_rows)
    conn.executemany(
        "INSERT INTO daily (date, body_weight, sleep_hours, food, is_demo, updated_at)"
        " VALUES (?, ?, ?, ?, 1, ?)", daily_rows)
    conn.commit()
    return len(set_rows), len(daily_rows)
