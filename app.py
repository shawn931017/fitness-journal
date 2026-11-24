"""健身月記｜從每一組，看見一個月的進步。

Flask 主程式：頁面、表單、登入保護、CSV 匯出與管理指令。
本機執行：python -m flask --app app run
"""
import csv
import gzip
import io
import json
import os
import re
import secrets
import sqlite3
import time
from collections import OrderedDict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import click
from flask import (Flask, Response, abort, flash, jsonify, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import charts
import db
import demo
import goals
import mascot
import nutrition

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TZ = ZoneInfo(os.environ.get("FJ_TIMEZONE", "Asia/Taipei"))
WEEKDAYS = "一二三四五六日"
ASSET_VERSION = "9"

app = Flask(__name__, instance_path=os.path.join(BASE_DIR, "instance"))
os.makedirs(app.instance_path, exist_ok=True)


def _secret_key():
    if os.environ.get("FJ_SECRET_KEY"):
        return os.environ["FJ_SECRET_KEY"]
    path = os.path.join(app.instance_path, "secret_key")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(secrets.token_hex(32))
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


app.config.update(
    DATABASE=os.environ.get("FJ_DATABASE", os.path.join(app.instance_path, "fitness.db")),
    SECRET_KEY=_secret_key(),
    PERMANENT_SESSION_LIFETIME=timedelta(days=365),  # 登入後保持登入
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("FJ_SECURE_COOKIE") == "1",
)
db.init_app(app)


# ================================================================ 小工具

def today():
    return datetime.now(TZ).date()


def now_iso():
    return datetime.now(TZ).isoformat(timespec="seconds")


def parse_day(value, default=None):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return default


def parse_number(value, lo, hi):
    """空白回傳 None；格式錯誤或超出範圍丟 ValueError。"""
    value = (value or "").strip().replace(",", ".")
    if not value:
        return None
    number = float(value)
    if not lo <= number <= hi:
        raise ValueError(value)
    return round(number, 2)


def safe_next(default):
    nxt = request.values.get("next") or ""
    if nxt.startswith("/") and not nxt.startswith("//"):
        return nxt
    return default


def next_label(today_sets):
    n = sum(1 for s in today_sets if not s["is_warmup"])
    return f"第 {n + 1} 組"


def is_fetch():
    return request.headers.get("X-Requested-With") == "fetch"


@app.template_filter("kg")
def fmt_kg(x):
    return "" if x is None else f"{x:g}"


@app.template_filter("wlabel")
def weight_label(weight, per_hand=False):
    if not weight:
        return "自體重"
    return f"單手 {weight:g} kg" if per_hand else f"{weight:g} kg"


@app.template_filter("mdw")
def month_day_weekday(value):
    d = value if isinstance(value, date) else parse_day(value)
    if not d:
        return value
    return f"{d.month}/{d.day}（{WEEKDAYS[d.weekday()]}）"


@app.template_filter("ago")
def days_ago(value):
    d = value if isinstance(value, date) else parse_day(value)
    if not d:
        return ""
    n = (today() - d).days
    return {0: "今天", 1: "昨天", 2: "前天"}.get(n, f"{n} 天前")


@app.context_processor
def inject_globals():
    has_demo = False
    if session.get("auth"):
        has_demo = db.has_demo_data()
    return {"today_str": today().isoformat(), "has_demo": has_demo, "asset_v": ASSET_VERSION}


# ================================================================ 登入保護

PUBLIC_ENDPOINTS = {"login", "static", "manifest", "plotly_js"}


@app.before_request
def require_login():
    if request.endpoint is None or request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if session.get("auth"):
        return None
    if is_fetch():
        return jsonify(ok=False, error="登入已失效，請重新整理頁面後再登入。"), 401
    nxt = request.full_path.rstrip("?") if request.method == "GET" else None
    return redirect(url_for("login", next=nxt))


@app.route("/login", methods=["GET", "POST"])
def login():
    configured = db.get_setting("password_hash") is not None
    error = None
    if request.method == "POST" and configured:
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if username == db.get_setting("username") and check_password_hash(db.get_setting("password_hash"), password):
            session.clear()
            session["auth"] = True
            session.permanent = True
            return redirect(safe_next(url_for("index")))
        time.sleep(1)  # 拖慢暴力猜密碼
        error = "帳號或密碼不正確。"
    return render_template("login.html", configured=configured, error=error)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# ================================================================ 首頁

@app.route("/")
def index():
    t = today()
    ts = t.isoformat()
    conn = db.get_db()
    workout = db.day_workout(ts)
    life = db.get_daily(ts)
    latest_weight = conn.execute(
        "SELECT date, body_weight FROM daily WHERE body_weight IS NOT NULL ORDER BY date DESC LIMIT 1"
    ).fetchone()
    recent = conn.execute(
        "SELECT s.date, COUNT(*) AS n_sets, GROUP_CONCAT(DISTINCT e.body_part) AS parts, MAX(s.is_demo) AS demo"
        " FROM sets s JOIN exercises e ON e.id = s.exercise_id"
        " WHERE s.date < ? GROUP BY s.date ORDER BY s.date DESC LIMIT 4", (ts,)
    ).fetchall()
    est = db.estimate(life["food"]) if life and life["food"] else None
    tg, cmp = goal_check(ts, est)
    return render_template(
        "index.html", workout=workout, total_sets=sum(len(w["sets"]) for w in workout),
        life=life, m=mascot.weekly_state(conn, t), latest_weight=latest_weight,
        target=db.target_weight(), recent=recent, est=est, tg=tg, cmp=cmp, ref_protein=tg["protein"],
    )


# ================================================================ 組間記錄

@app.route("/log")
def log_pick():
    return render_template("log_pick.html", groups=db.grouped_movements(),
                           todays=db.day_workout(today().isoformat()))


@app.route("/log/<int:ex_id>")
def log_exercise(ex_id):
    ex = db.get_exercise(ex_id) or abort(404)
    ts = today().isoformat()
    variants = db.variants_of(ex["movement"])
    if not any(v["id"] == ex["id"] for v in variants):
        variants = list(variants) + [ex]
    prev_date, prev_sets = db.previous_session(ex_id, ts)
    today_sets = db.sets_on(ex_id, ts)

    # 預填：今天已有就沿用上一組；否則帶入前次第一個正式組，由使用者自行調整
    base = None
    if today_sets:
        base = today_sets[-1]
    elif prev_sets:
        working = [s for s in prev_sets if not s["is_warmup"]]
        base = working[0] if working else prev_sets[0]
    prefill = {"weight": fmt_kg(base["weight"]) if base else "", "reps": base["reps"] if base else ""}

    return render_template(
        "log.html", ex=ex, variants=variants, prev_date=prev_date, prev_sets=prev_sets,
        today_sets=today_sets, prefill=prefill, next_label=next_label(today_sets),
        back=url_for("log_exercise", ex_id=ex_id),
    )


@app.route("/log/<int:ex_id>/sets", methods=["POST"])
def add_set(ex_id):
    ex = db.get_exercise(ex_id) or abort(404)
    try:
        weight = parse_number(request.form.get("weight"), 0, 500)
        reps = int((request.form.get("reps") or "").strip())
        if weight is None or not 1 <= reps <= 200:
            raise ValueError
    except ValueError:
        msg = "請輸入正確的重量（0–500 kg）與次數（1–200 下）。"
        if is_fetch():
            return jsonify(ok=False, error=msg), 400
        flash(msg, "error")
        return redirect(url_for("log_exercise", ex_id=ex_id))

    ts = today().isoformat()
    db.add_set(ex_id, ts, weight, reps, request.form.get("is_warmup") == "1",
               (request.form.get("client_id") or "")[:64], now_iso())
    if is_fetch():
        today_sets = db.sets_on(ex_id, ts)
        html = render_template("_today_sets.html", ex=ex, today_sets=today_sets,
                               back=url_for("log_exercise", ex_id=ex_id))
        return jsonify(ok=True, html=html, next_label=next_label(today_sets))
    flash("已儲存這一組。", "ok")
    return redirect(url_for("log_exercise", ex_id=ex_id))


@app.route("/sets/<int:set_id>/edit", methods=["GET", "POST"])
def edit_set(set_id):
    s = db.get_set(set_id) or abort(404)
    back = safe_next(url_for("day_view", day=s["date"]))
    if request.method == "POST":
        try:
            weight = parse_number(request.form.get("weight"), 0, 500)
            reps = int((request.form.get("reps") or "").strip())
            d = parse_day(request.form.get("date"))
            if weight is None or not 1 <= reps <= 200 or d is None or d > today():
                raise ValueError
        except ValueError:
            flash("請確認日期、重量（0–500 kg）與次數（1–200 下）。", "error")
            return redirect(url_for("edit_set", set_id=set_id, next=back))
        conn = db.get_db()
        conn.execute("UPDATE sets SET date = ?, weight = ?, reps = ?, is_warmup = ?, is_demo = 0 WHERE id = ?",
                     (d.isoformat(), weight, reps, int(request.form.get("is_warmup") == "1"), set_id))
        conn.commit()
        flash("已修改。", "ok")
        return redirect(back)
    return render_template("edit_set.html", s=s, back=back)


@app.route("/sets/<int:set_id>/delete", methods=["POST"])
def delete_set(set_id):
    s = db.get_set(set_id) or abort(404)
    conn = db.get_db()
    conn.execute("DELETE FROM sets WHERE id = ?", (set_id,))
    conn.commit()
    flash(f"已刪除 {s['movement']} 的一組紀錄。", "ok")
    return redirect(safe_next(url_for("day_view", day=s["date"])))


# ================================================================ 生活與體重簡記

def protein_reference(day):
    """蛋白質參考量 = 最近一次體重 × 每公斤幾克（設定頁可調）；沒有體重就不顯示。"""
    return db.targets_on(day)["protein"]


def goal_check(ds, est):
    """當天目標，以及吃的量和目標比較；今天還沒結束只顯示進度、不判斷不足。"""
    tg = db.targets_on(ds)
    return tg, goals.compare(est, tg, in_progress=ds >= today().isoformat())


def day_range(start, end):
    days, d = [], start
    while d <= end:
        days.append(d.isoformat())
        d += timedelta(days=1)
    return days


@app.route("/life", methods=["GET", "POST"])
def life():
    t = today()
    d = min(parse_day(request.values.get("date"), t), t)
    ds = d.isoformat()
    form = None
    if request.method == "POST":
        form = request.form
        try:
            body_weight = parse_number(form.get("body_weight"), 20, 300)
            sleep_hours = parse_number(form.get("sleep_hours"), 0, 24)
        except ValueError:
            flash("體重請填 20–300 kg，睡眠請填 0–24 小時；不記得可以留白。", "error")
        else:
            food = (form.get("food") or "").strip()[:500]
            db.save_daily(ds, body_weight, sleep_hours, food, now_iso())
            flash(f"已儲存 {month_day_weekday(d)} 的簡記。", "ok")
            return redirect(url_for("life", date=ds))

    record = db.get_daily(ds)
    food_text = form.get("food") if form else (record["food"] if record else "")
    start = t - timedelta(days=13)
    recent_rows = db.daily_between(start.isoformat(), t.isoformat())
    day_targets = goals.targets_by_day(db.goal_profile(), day_range(start, t), db.weights_until(t.isoformat()))
    recent = []
    for i in range(14):
        day = (t - timedelta(days=i)).isoformat()
        row = recent_rows.get(day)
        e = db.estimate(row["food"]) if row and row["food"] else None
        recent.append((day, row, e, goals.compare(e, day_targets[day], in_progress=i == 0)))
    est = db.estimate(food_text)
    tg, cmp = goal_check(ds, est)
    return render_template(
        "life.html", d=d, ds=ds, record=record, form=form, recent=recent, short=goals.SHORT,
        last_weight=db.latest_body_weight(ds), est=est, tg=tg, cmp=cmp,
        ref_protein=tg["protein"], back=url_for("life", date=ds),
        prev_day=(d - timedelta(days=1)).isoformat(),
        next_day=(d + timedelta(days=1)).isoformat() if d < t else None,
        reminder_url=url_for("life", _external=True),
    )


@app.route("/nutrition/preview", methods=["POST"])
def nutrition_preview():
    """輸入飲食時即時試算（尚未儲存）。"""
    ds = min(parse_day(request.form.get("date"), today()), today()).isoformat()
    est = db.estimate(request.form.get("food", "")[:500])
    tg, cmp = goal_check(ds, est)
    return render_template("_nutrition.html", est=est, tg=tg, cmp=cmp, ref_protein=tg["protein"],
                           back=url_for("life", date=ds), preview=True)


# ================================================================ 食物營養表

def _food_form(f):
    name = (f.get("name") or "").strip()[:30]
    unit = (f.get("unit") or "").strip()[:4]
    aliases = ",".join(a.strip() for a in re.split(r"[,，、]", f.get("aliases") or "") if a.strip())[:200]
    category = f.get("category") if f.get("category") in nutrition.CATEGORIES else "自訂"
    grams = parse_number(f.get("grams"), 1, 5000)
    values = [parse_number(f.get(k), 0, 5000) for k in ("kcal", "carb", "protein", "fat")]
    if not name or not unit or any(v is None for v in values):
        raise ValueError
    return {"name": name, "unit": unit, "aliases": aliases, "category": category, "grams": grams,
            "kcal": values[0], "carb": values[1], "protein": values[2], "fat": values[3]}


@app.route("/foods", methods=["GET", "POST"])
def foods():
    if request.method == "POST":
        try:
            data = _food_form(request.form)
        except ValueError:
            flash("請填寫名稱、單位，以及每單位的熱量、碳水、蛋白質、脂肪（數字）。", "error")
            return redirect(url_for("foods", name=request.form.get("name", ""), next=safe_next("")) + "#add-food")
        conn = db.get_db()
        try:
            conn.execute(
                "INSERT INTO foods (name, aliases, category, unit, grams, kcal, carb, protein, fat)"
                " VALUES (:name, :aliases, :category, :unit, :grams, :kcal, :carb, :protein, :fat)", data)
            conn.commit()
        except sqlite3.IntegrityError:
            flash(f"食物表已經有「{data['name']}」，可以在下方清單修改它的數值或別名。", "error")
            return redirect(url_for("foods") + "#food-list")
        flash(f"已新增「{data['name']}」，之前寫過它的飲食紀錄也會一起重新估算。", "ok")
        return redirect(safe_next(url_for("foods") + "#food-list"))

    grouped = OrderedDict((c, []) for c in nutrition.CATEGORIES)
    for f in db.list_foods():
        grouped.setdefault(f["category"], []).append(f)
    return render_template("foods.html", grouped=grouped, categories=nutrition.CATEGORIES,
                           prefill_name=request.args.get("name", ""), next=safe_next(""))


@app.route("/foods/<int:food_id>/update", methods=["POST"])
def update_food(food_id):
    food = db.get_db().execute("SELECT * FROM foods WHERE id = ?", (food_id,)).fetchone() or abort(404)
    try:
        data = _food_form(request.form)
    except ValueError:
        flash("數值格式不正確，沒有儲存。", "error")
        return redirect(url_for("foods") + "#food-list")
    data["id"] = food_id
    conn = db.get_db()
    try:
        conn.execute("UPDATE foods SET name = :name, aliases = :aliases, category = :category, unit = :unit,"
                     " grams = :grams, kcal = :kcal, carb = :carb, protein = :protein, fat = :fat WHERE id = :id",
                     data)
        conn.commit()
    except sqlite3.IntegrityError:
        flash(f"已經有另一個叫「{data['name']}」的食物。", "error")
        return redirect(url_for("foods") + "#food-list")
    flash(f"已更新「{data['name']}」。", "ok")
    return redirect(url_for("foods") + f"#food-{food['id']}")


@app.route("/foods/<int:food_id>/delete", methods=["POST"])
def delete_food(food_id):
    food = db.get_db().execute("SELECT * FROM foods WHERE id = ?", (food_id,)).fetchone() or abort(404)
    if food["is_builtin"]:
        flash("內建食物不能刪除，可以改它的數值。", "error")
    else:
        conn = db.get_db()
        conn.execute("DELETE FROM foods WHERE id = ?", (food_id,))
        conn.commit()
        flash(f"已刪除「{food['name']}」。", "ok")
    return redirect(url_for("foods") + "#food-list")


# ================================================================ 月度與長期曲線

RANGES = OrderedDict([("30", "近 30 天"), ("60", "近 60 天"), ("90", "近 90 天"),
                      ("180", "近半年"), ("365", "近一年"), ("all", "全部")])
PICKS = OrderedDict([("1", "第 1 個正式組"), ("2", "第 2 個正式組"), ("3", "第 3 個正式組"),
                     ("top", "當天最重的一組")])


def _choose_set(working, pick):
    if not working:
        return None
    if pick == "top":
        return max(working, key=lambda s: (s["weight"], s["reps"]))
    idx = int(pick) - 1
    return working[idx] if len(working) > idx else None


def _mark_progress(points):
    """和前一次比：加重 → 公斤圖標星；同重量多做 → 次數圖標星。"""
    prev = None
    for p in points:
        p["progress_kind"], p["progress_text"] = None, ""
        if prev:
            if p["weight"] > prev["weight"]:
                p["progress_kind"], p["progress_text"] = "weight", f"+{p['weight'] - prev['weight']:g} kg"
            elif p["weight"] == prev["weight"] and p["reps"] > prev["reps"]:
                p["progress_kind"], p["progress_text"] = "reps", f"+{p['reps'] - prev['reps']} 下"
        prev = p


@app.route("/review")
def review():
    t = today()
    conn = db.get_db()
    trained = conn.execute(
        "SELECT e.*, MAX(s.date) AS last_date FROM exercises e JOIN sets s ON s.exercise_id = e.id"
        " GROUP BY e.id ORDER BY last_date DESC, e.id"
    ).fetchall()
    ex_id = request.args.get("exercise_id", type=int) or (trained[0]["id"] if trained else None)
    ex = db.get_exercise(ex_id) if ex_id else None
    rng = request.args.get("days", "30")
    rng = rng if rng in RANGES else "30"
    pick = request.args.get("pick", "1")
    pick = pick if pick in PICKS else "1"

    if rng == "all":
        first = conn.execute(
            "SELECT MIN(d) FROM (SELECT MIN(date) AS d FROM sets UNION ALL SELECT MIN(date) FROM daily)"
        ).fetchone()[0]
        start = min(parse_day(first, t), t - timedelta(days=29))
    else:
        start = t - timedelta(days=int(rng) - 1)
    s, e = start.isoformat(), t.isoformat()
    x_range = [(start - timedelta(days=1)).isoformat(), (t + timedelta(days=1)).isoformat()]

    daily = db.daily_between(s, e)
    estimates = db.estimates_between(s, e)
    sessions, points = [], []
    if ex:
        rows = conn.execute(
            "SELECT * FROM sets WHERE exercise_id = ? AND date BETWEEN ? AND ? ORDER BY date, id",
            (ex["id"], s, e),
        ).fetchall()
        by_date = OrderedDict()
        for r in rows:
            by_date.setdefault(r["date"], []).append(r)
        for d, rs in by_date.items():
            labeled = db.label_sets(rs)
            chosen = _choose_set([x for x in labeled if not x["is_warmup"]], pick)
            sessions.append({"date": d, "sets": labeled, "chosen": chosen,
                             "is_demo": any(x["is_demo"] for x in labeled), "life": daily.get(d),
                             "est": estimates.get(d)})
            if chosen:
                points.append({"date": d, "weight": chosen["weight"], "reps": chosen["reps"],
                               "is_demo": bool(chosen["is_demo"])})
        _mark_progress(points)
        progress_by_date = {p["date"]: p for p in points}
        for sess in sessions:
            sess["progress"] = progress_by_date.get(sess["date"], {}).get("progress_text", "")

    target = db.target_weight()
    has_weight = any(r["body_weight"] is not None for r in daily.values())
    stats = {
        "days": (t - start).days + 1,
        "sessions": len(sessions),
        "weight": sum(1 for r in daily.values() if r["body_weight"] is not None),
        "sleep": sum(1 for r in daily.values() if r["sleep_hours"] is not None),
        "food": sum(1 for r in daily.values() if r["food"]),
    }
    # 飲食估算：只平均「有飲食紀錄、且每一項都查得到」的日子，避免漏算的日子把平均拉低
    complete = [est for est in estimates.values() if est["items"] and not est["unknown"]]
    nutri = {
        "days": len(complete),
        "partial": sum(1 for est in estimates.values() if est["unknown"]),
        "kcal": sum(x["total"]["kcal"] for x in complete) / len(complete) if complete else None,
        "protein": sum(x["total"]["protein"] for x in complete) / len(complete) if complete else None,
        "carb": sum(x["total"]["carb"] for x in complete) / len(complete) if complete else None,
        "fat": sum(x["total"]["fat"] for x in complete) / len(complete) if complete else None,
    }
    # 每天和「當天的目標」比較（體重會變，目標也跟著變）；今天還沒結束，不列入達標統計
    day_targets = goals.targets_by_day(db.goal_profile(), day_range(start, t), db.weights_until(e))
    comparisons = {d: goals.compare(est, day_targets[d], in_progress=d == e) for d, est in estimates.items()}
    goal_stats = goals.summarize(comparisons.values())
    tg = day_targets[e]
    return render_template(
        "review.html", trained=trained, ex=ex, rng=rng, pick=pick, ranges=RANGES, picks=PICKS,
        fig_train=charts.training_figure(points, ex["per_hand"], x_range) if points else None,
        fig_weight=charts.body_weight_figure(daily, start, t, target) if has_weight else None,
        fig_food=charts.nutrition_figure(estimates, daily, start, t, day_targets, comparisons)
        if any(x["items"] for x in estimates.values()) else None,
        nutri=nutri, ref_protein=tg["protein"], tg=tg, goal_stats=goal_stats,
        progress=[p for p in points if p["progress_kind"]], sessions=list(reversed(sessions)),
        stats=stats, plotly_version=_plotly_version(),
    )


@app.route("/day/<day>")
def day_view(day):
    d = parse_day(day) or abort(404)
    ds = d.isoformat()
    focus = request.args.get("exercise_id", type=int)
    workout = db.day_workout(ds)
    workout.sort(key=lambda w: w["exercise_id"] != focus)  # 目前查看的動作排最前面
    tpl = "_day_detail.html" if request.args.get("partial") else "day.html"
    life_row = db.get_daily(ds)
    est = db.estimate(life_row["food"]) if life_row and life_row["food"] else None
    _tg, cmp = goal_check(ds, est)
    return render_template(tpl, d=d, ds=ds, workout=workout, life=life_row, focus=focus, est=est, cmp=cmp,
                           partial=bool(request.args.get("partial")))


# ================================================================ 設定、動作管理、匯出

@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        f = request.form
        checks = [
            ("target_weight", 30, 300, True, "目標體重請填 30–300 kg"),
            ("protein_per_kg", 0.5, 4, True, "蛋白質請填每公斤 0.5–4 g"),
            ("height_cm", 100, 250, False, "身高請填 100–250 cm"),
            ("age", 10, 100, False, "年齡請填 10–100 歲"),
            ("kcal_manual", 800, 6000, False, "手動熱量請填 800–6000 kcal，或留白用建議值"),
        ]
        values, errors = {}, []
        for key, lo, hi, required, msg in checks:
            try:
                v = parse_number(f.get(key), lo, hi)
                if v is None and required:
                    raise ValueError
            except ValueError:
                errors.append(msg)
                continue
            values[key] = "" if v is None else (str(int(v)) if key in ("age", "kcal_manual") else f"{v:g}")
        if errors:
            flash("、".join(errors) + "。", "error")
            return redirect(url_for("settings") + "#goal")
        values["goal_mode"] = f.get("goal_mode") if f.get("goal_mode") in goals.MODES else "auto"
        values["sex"] = f.get("sex") if f.get("sex") in goals.SEXES else ""
        values["activity"] = f.get("activity") if f.get("activity") in goals.ACTIVITY else "1.55"
        for key, v in values.items():
            db.set_setting(key, v)
        flash("已更新目標。", "ok")
        return redirect(url_for("settings") + "#goal")

    all_ex = db.list_exercises(active_only=False)
    grouped = OrderedDict((bp, []) for bp in db.BODY_PARTS)
    for ex in all_ex:
        grouped.setdefault(ex["body_part"], []).append(ex)
    return render_template(
        "settings.html", target=db.target_weight(), protein_per_kg=db.protein_per_kg(),
        profile=db.goal_profile(), tg=db.targets_on(today().isoformat()), modes=goals.MODES,
        activities=goals.ACTIVITY, sexes=goals.SEXES,
        food_count=len(db.list_foods()), grouped=grouped, body_parts=db.BODY_PARTS,
        movements=sorted({x["movement"] for x in all_ex}), equipments=sorted({x["equipment"] for x in all_ex}),
        prefill_movement=request.args.get("movement", ""), prefill_body_part=request.args.get("body_part", "胸"),
        username=db.get_setting("username", ""), site_url=url_for("index", _external=True),
    )


@app.route("/exercises/add", methods=["POST"])
def add_exercise():
    f = request.form
    body_part = f.get("body_part") if f.get("body_part") in db.BODY_PARTS else "其他"
    movement = (f.get("movement") or "").strip()[:30]
    equipment = (f.get("equipment") or "").strip()[:30]
    try:
        step = parse_number(f.get("step"), 0.25, 50) or 2.5
    except ValueError:
        step = 2.5
    if not movement or not equipment:
        flash("請填寫動作與器材名稱。", "error")
        return redirect(url_for("settings", movement=movement, body_part=body_part) + "#add-exercise")
    conn = db.get_db()
    existing = conn.execute("SELECT * FROM exercises WHERE movement = ? AND equipment = ?",
                            (movement, equipment)).fetchone()
    if existing:
        conn.execute("UPDATE exercises SET active = 1 WHERE id = ?", (existing["id"],))
        new_id = existing["id"]
        flash(f"「{movement}｜{equipment}」已存在，已重新啟用。", "ok")
    else:
        sort_order = conn.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM exercises").fetchone()[0]
        try:
            new_id = conn.execute(
                "INSERT INTO exercises (body_part, movement, equipment, per_hand, step, sort_order)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (body_part, movement, equipment, int(f.get("per_hand") == "1"), step, sort_order),
            ).lastrowid
        except sqlite3.IntegrityError:
            abort(400)
        flash(f"已新增「{movement}｜{equipment}」。", "ok")
    conn.commit()
    return redirect(url_for("log_exercise", ex_id=new_id))


@app.route("/exercises/<int:ex_id>/update", methods=["POST"])
def update_exercise(ex_id):
    ex = db.get_exercise(ex_id) or abort(404)
    try:
        step = parse_number(request.form.get("step"), 0.25, 50) or ex["step"]
    except ValueError:
        step = ex["step"]
    conn = db.get_db()
    conn.execute("UPDATE exercises SET step = ?, per_hand = ?, active = ? WHERE id = ?",
                 (step, int(request.form.get("per_hand") == "1"), int(request.form.get("active") == "1"), ex_id))
    conn.commit()
    flash(f"已更新「{ex['movement']}｜{ex['equipment']}」。", "ok")
    return redirect(url_for("settings") + "#exercises")


@app.route("/demo/<action>", methods=["POST"])
def demo_data(action):
    if action == "seed":
        if db.has_demo_data():
            flash("已經有測試資料了。", "error")
        else:
            n_sets, n_days = demo.seed(db.get_db(), today())
            flash(f"已加入測試資料：{n_sets} 組訓練、{n_days} 天生活簡記。", "ok")
    elif action == "clear":
        db.clear_demo_data()
        flash("已清除所有測試資料，真實紀錄不受影響。", "ok")
    else:
        abort(404)
    return redirect(url_for("settings") + "#demo")


@app.route("/export/<kind>.csv")
def export_csv(kind):
    conn = db.get_db()
    buf = io.StringIO()
    w = csv.writer(buf)
    if kind == "sets":
        w.writerow(["日期", "部位", "動作", "器材", "組別", "重量kg", "單手重量", "次數", "熱身", "測試資料", "建立時間"])
        rows = conn.execute(
            "SELECT s.*, e.body_part, e.movement, e.equipment, e.per_hand FROM sets s"
            " JOIN exercises e ON e.id = s.exercise_id ORDER BY s.date, s.exercise_id, s.id"
        ).fetchall()
        groups = OrderedDict()
        for r in rows:
            groups.setdefault((r["date"], r["exercise_id"]), []).append(r)
        for rs in groups.values():
            for r in db.label_sets(rs):
                w.writerow([r["date"], r["body_part"], r["movement"], r["equipment"], r["label"],
                            f"{r['weight']:g}", "是" if r["per_hand"] else "", r["reps"],
                            "是" if r["is_warmup"] else "", "是" if r["is_demo"] else "", r["created_at"]])
    elif kind == "daily":
        w.writerow(["日期", "體重kg", "昨晚睡眠小時", "飲食", "估算熱量kcal", "估算碳水g", "估算蛋白質g",
                    "估算脂肪g", "未知食物", "方向", "熱量目標kcal", "熱量判斷", "蛋白質目標g", "蛋白質判斷",
                    "測試資料", "更新時間"])
        rows = conn.execute("SELECT * FROM daily ORDER BY date").fetchall()
        ts = today().isoformat()
        day_targets = goals.targets_by_day(db.goal_profile(), [r["date"] for r in rows], db.weights_until(ts))
        for r in rows:
            est = db.estimate(r["food"]) if r["food"] else None
            tot = est["total"] if est and est["items"] else None
            tg = day_targets[r["date"]]
            cmp = goals.compare(est, tg, in_progress=r["date"] >= ts)
            w.writerow([r["date"], fmt_kg(r["body_weight"]), fmt_kg(r["sleep_hours"]), r["food"] or "",
                        round(tot["kcal"]) if tot else "", round(tot["carb"], 1) if tot else "",
                        round(tot["protein"], 1) if tot else "", round(tot["fat"], 1) if tot else "",
                        "、".join(est["unknown"]) if est else "",
                        tg["mode_label"], tg["kcal"] or "", cmp["kcal"]["text"] if cmp else "",
                        tg["protein"] or "", cmp["protein"]["text"] if cmp else "",
                        "是" if r["is_demo"] else "", r["updated_at"]])
    else:
        abort(404)
    filename = f"fitness-{kind}-{today().isoformat()}.csv"
    return Response("﻿" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ================================================================ 加入主畫面與圖表程式庫

@app.route("/manifest.webmanifest")
def manifest():
    icon = lambda name, size, purpose="any": {  # noqa: E731
        "src": url_for("static", filename=f"icons/{name}"), "sizes": f"{size}x{size}",
        "type": "image/png", "purpose": purpose}
    data = {
        "name": "健身月記", "short_name": "健身月記", "lang": "zh-Hant-TW",
        "start_url": url_for("index"), "scope": "/", "display": "standalone",
        "background_color": "#f4f7f6", "theme_color": "#2f7d6d",
        "icons": [icon("icon-192.png", 192), icon("icon-512.png", 512),
                  icon("icon-maskable-512.png", 512, "maskable")],
    }
    return Response(json.dumps(data, ensure_ascii=False), mimetype="application/manifest+json")


_PLOTLY_CACHE = {}


def _plotly_version():
    import plotly
    return plotly.__version__


@app.route("/vendor/plotly.min.js")
def plotly_js():
    """直接由已安裝的 plotly 套件提供 plotly.js，不依賴外部 CDN。"""
    if not _PLOTLY_CACHE:
        from plotly.offline import get_plotlyjs
        raw = get_plotlyjs().encode("utf-8")
        _PLOTLY_CACHE["raw"], _PLOTLY_CACHE["gz"] = raw, gzip.compress(raw, 6)
    if "gzip" in request.headers.get("Accept-Encoding", ""):
        resp = Response(_PLOTLY_CACHE["gz"], mimetype="application/javascript")
        resp.headers["Content-Encoding"] = "gzip"
    else:
        resp = Response(_PLOTLY_CACHE["raw"], mimetype="application/javascript")
    resp.headers["Vary"] = "Accept-Encoding"
    resp.headers["Cache-Control"] = "public, max-age=2592000, immutable"
    return resp


# ================================================================ 管理指令

@app.cli.command("set-password")
@click.option("--username", prompt="帳號", help="登入帳號")
@click.password_option("--password", prompt="密碼", confirmation_prompt="再輸入一次密碼")
def set_password_command(username, password):
    """設定（或更改）唯一的登入帳號密碼。"""
    if len(password) < 8:
        raise click.UsageError("密碼至少 8 個字元。")
    db.set_setting("username", username.strip())
    db.set_setting("password_hash", generate_password_hash(password))
    click.echo(f"已設定帳號「{username.strip()}」。")


@app.cli.command("seed-demo")
@click.option("--days", default=45, show_default=True, help="往前產生幾天的測試資料")
def seed_demo_command(days):
    """加入標記為「測試」的跨月測試資料。"""
    if db.has_demo_data():
        raise click.UsageError("已經有測試資料，請先執行 clear-demo。")
    n_sets, n_days = demo.seed(db.get_db(), today(), days)
    click.echo(f"已加入 {n_sets} 組訓練、{n_days} 天生活簡記（皆標記為測試資料）。")


@app.cli.command("clear-demo")
def clear_demo_command():
    """刪除所有測試資料（真實紀錄不受影響）。"""
    db.clear_demo_data()
    click.echo("已清除測試資料。")
