"""每日熱量與蛋白質目標，以及「有沒有吃夠」的判斷。

- 方向：增重 / 維持 / 減重；選「自動」時依目前體重與目標體重的差距判斷。
- 熱量：Mifflin-St Jeor 基礎代謝 × 活動量 = 維持熱量，再依方向加減；也可以直接手動填一個數字。
- 蛋白質：最近一次體重 × 每公斤幾克，三種方向都是「至少吃到」。
- 熱量規則依方向相反：增重是下限、減重是上限、維持是 ±10% 範圍。
- 當天還沒結束只顯示進度，不判斷「不足」；有查不到的食物時，只在已知部分就能確定時才下結論。
"""
from collections import OrderedDict

MODES = OrderedDict([("auto", "自動（依目標體重）"), ("gain", "增重"), ("maintain", "維持"), ("lose", "減重")])
MODE_LABELS = {"gain": "增重", "maintain": "維持", "lose": "減重"}
ACTIVITY = OrderedDict([
    ("1.2", "幾乎不運動"),
    ("1.375", "每週動 1–2 天"),
    ("1.55", "每週動 3–5 天"),
    ("1.725", "每週動 6–7 天"),
])
SEXES = OrderedDict([("m", "男"), ("f", "女")])
ADJUST = {"gain": 300, "maintain": 0, "lose": -500}   # 相對維持熱量的加減（kcal）
AUTO_TOLERANCE = 1.0      # 自動判斷：和目標差 1 kg 以內視為「維持」
MAINTAIN_BAND = 0.10      # 維持：目標 ±10% 都算達標
GAIN_OVER_NOTE = 500      # 增重：超過目標這麼多才溫和提醒
LOSE_UNDER_RATIO = 0.75   # 減重：低於目標 75% 才提醒吃太少


def _num(value, cast=float):
    try:
        return cast(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def load_profile(get_setting):
    """從設定表讀出計算需要的資料；get_setting(key, default) 由 db 提供。"""
    activity = get_setting("activity", "1.55")
    return {
        "mode": get_setting("goal_mode", "auto") if get_setting("goal_mode", "auto") in MODES else "auto",
        "sex": get_setting("sex", "") if get_setting("sex", "") in SEXES else "",
        "height": _num(get_setting("height_cm")),
        "age": _num(get_setting("age"), int),
        "activity": activity if activity in ACTIVITY else "1.55",
        "kcal_manual": _num(get_setting("kcal_manual")),
        "protein_per_kg": _num(get_setting("protein_per_kg", "1.6")) or 1.6,
        "target_weight": _num(get_setting("target_weight", "80")) or 80.0,
    }


def resolve_mode(profile, bw):
    if profile["mode"] != "auto":
        return profile["mode"]
    if bw is None:
        return "maintain"
    gap = profile["target_weight"] - bw
    if gap > AUTO_TOLERANCE:
        return "gain"
    if gap < -AUTO_TOLERANCE:
        return "lose"
    return "maintain"


def maintenance_kcal(profile, bw):
    """維持體重大約需要的熱量；缺身高、年齡、性別或體重就回傳 None。"""
    if bw is None or not profile["height"] or not profile["age"] or not profile["sex"]:
        return None
    bmr = 10 * bw + 6.25 * profile["height"] - 5 * profile["age"] + (5 if profile["sex"] == "m" else -161)
    return bmr * float(profile["activity"])


def targets(profile, bw):
    mode = resolve_mode(profile, bw)
    maint = maintenance_kcal(profile, bw)
    suggested = int(round((maint + ADJUST[mode]) / 50) * 50) if maint else None
    kcal = profile["kcal_manual"] or suggested
    return {
        "mode": mode, "mode_label": MODE_LABELS[mode], "auto": profile["mode"] == "auto", "bw": bw,
        "maintenance": int(round(maint / 10) * 10) if maint else None, "adjust": ADJUST[mode],
        "suggested": suggested, "manual": bool(profile["kcal_manual"]),
        "kcal": int(round(kcal)) if kcal else None,
        "kcal_low": int(round(kcal * (1 - MAINTAIN_BAND))) if kcal and mode == "maintain" else None,
        "kcal_high": int(round(kcal * (1 + MAINTAIN_BAND))) if kcal and mode == "maintain" else None,
        "protein": int(round(bw * profile["protein_per_kg"])) if bw else None,
    }


def targets_by_day(profile, days, weight_rows):
    """days：遞增的日期字串；weight_rows：[(日期, 體重)] 依日期遞增，可包含 days 之前的量測。
    每天用「當天或之前最近一次」的體重計算。"""
    out, i, bw = {}, 0, None
    for d in days:
        while i < len(weight_rows) and weight_rows[i][0] <= d:
            bw = weight_rows[i][1]
            i += 1
        out[d] = targets(profile, bw)
    return out


# ---------------------------------------------------------------- 比較

def _bar(value, full):
    return max(0, min(100, round(value / full * 100))) if full else 0


def _kcal(v, partial, tg, in_progress):
    T = tg["kcal"]
    base = {"value": round(v), "target": T, "rule": "", "note": ""}
    if not T:
        return dict(base, state="none", text="", pct=0)
    mode = tg["mode"]
    if mode == "gain":
        base["rule"] = f"至少 {T}"
        if v >= T:
            extra = v - T
            note = f"比目標多 {round(extra)} kcal，多出來的可能比較容易變成脂肪。" if extra > GAIN_OVER_NOTE else ""
            return dict(base, state="ok", text="已吃夠", note=note, pct=100)
        if in_progress:
            return dict(base, state="progress", text=f"還差 {round(T - v)} kcal", pct=_bar(v, T))
        if partial:
            return dict(base, state="unknown", text="有查不到的食物，無法判斷", pct=_bar(v, T))
        return dict(base, state="under", text=f"少了 {round(T - v)} kcal", pct=_bar(v, T))

    if mode == "lose":
        base["rule"] = f"上限 {T}"
        if v > T:
            return dict(base, state="over", text=f"超過 {round(v - T)} kcal", pct=100)
        if in_progress:
            return dict(base, state="progress", text=f"還可以吃 {round(T - v)} kcal", pct=_bar(v, T))
        if partial:
            return dict(base, state="unknown", text="有查不到的食物，無法判斷", pct=_bar(v, T))
        note = "吃得比目標少很多，長期可能連肌肉一起掉。" if v < T * LOSE_UNDER_RATIO else ""
        return dict(base, state="ok", text="在上限內", note=note, pct=_bar(v, T))

    lo, hi = tg["kcal_low"], tg["kcal_high"]
    base["rule"] = f"{lo}–{hi}"
    if v > hi:
        return dict(base, state="over", text=f"超過 {round(v - hi)} kcal", pct=100)
    if v >= lo:
        if in_progress:
            return dict(base, state="progress", text=f"已在範圍內，上限 {hi} kcal", pct=_bar(v, hi))
        if partial:
            return dict(base, state="unknown", text="有查不到的食物，無法判斷", pct=_bar(v, hi))
        return dict(base, state="ok", text="在範圍內", pct=_bar(v, hi))
    if in_progress:
        return dict(base, state="progress", text=f"還差 {round(lo - v)} kcal 進入範圍", pct=_bar(v, hi))
    if partial:
        return dict(base, state="unknown", text="有查不到的食物，無法判斷", pct=_bar(v, hi))
    return dict(base, state="under", text=f"少了 {round(lo - v)} kcal", pct=_bar(v, hi))


def _protein(v, partial, tg, in_progress):
    T = tg["protein"]
    base = {"value": round(v), "target": T, "rule": f"至少 {T}" if T else "", "note": ""}
    if not T:
        return dict(base, state="none", text="", pct=0)
    if v >= T:
        return dict(base, state="ok", text="已吃夠", pct=100)
    if in_progress:
        return dict(base, state="progress", text=f"還差 {round(T - v)} g", pct=_bar(v, T))
    if partial:
        return dict(base, state="unknown", text="有查不到的食物，無法判斷", pct=_bar(v, T))
    return dict(base, state="under", text=f"少了 {round(T - v)} g", pct=_bar(v, T))


def compare(est, tg, in_progress):
    """est：nutrition.parse() 結果；tg：targets()；in_progress：今天還沒結束。
    沒有任何查得到的食物就回傳 None。"""
    if not est or not est["items"]:
        return None
    partial = bool(est["unknown"])
    t = est["total"]
    return {
        "in_progress": in_progress, "partial": partial, "mode_label": tg["mode_label"],
        "kcal": _kcal(t["kcal"], partial, tg, in_progress),
        "protein": _protein(t["protein"], partial, tg, in_progress),
    }


SHORT = {"ok": "✓", "under": "不足", "over": "超過", "unknown": "?", "progress": "", "none": ""}


def summarize(comparisons):
    """回顧頁統計：只算已經結束、有目標的日子。"""
    out = {"kcal": {"ok": 0, "under": 0, "over": 0, "unknown": 0, "days": 0},
           "protein": {"ok": 0, "under": 0, "over": 0, "unknown": 0, "days": 0}}
    for c in comparisons:
        if not c or c["in_progress"]:
            continue
        for key in ("kcal", "protein"):
            state = c[key]["state"]
            if state in out[key]:
                out[key][state] += 1
                out[key]["days"] += 1
    return out
