"""快速檢查：用暫存資料庫把主要流程跑一遍。

python tests/smoke_test.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp()
os.environ["FJ_DATABASE"] = os.path.join(tmp, "test.db")
os.environ["FJ_SECRET_KEY"] = "test"

from werkzeug.security import generate_password_hash  # noqa: E402

import app as fj  # noqa: E402
import db  # noqa: E402

flask_app = fj.app
flask_app.config["TESTING"] = True
client = flask_app.test_client()
ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1


# 未登入一律導向登入頁
r = client.get("/")
check(r.status_code == 302 and "/login" in r.location, "未登入應導向 /login")
check(client.get("/manifest.webmanifest").status_code == 200, "manifest 應公開")

with flask_app.app_context():
    db.set_setting("username", "tester")
    db.set_setting("password_hash", generate_password_hash("password123"))

r = client.post("/login", data={"username": "tester", "password": "wrong"})
check("帳號或密碼不正確" in r.get_data(as_text=True), "錯誤密碼應失敗")
r = client.post("/login?next=/life", data={"username": "tester", "password": "password123"})
check(r.status_code == 302 and r.location.endswith("/life"), "登入後回到 next")

# 首頁與動作選單
check("尚未記錄" in client.get("/").get_data(as_text=True), "首頁顯示尚未記錄")
check("上斜臥推" in client.get("/log").get_data(as_text=True), "預設動作")

with flask_app.app_context():
    conn = db.get_db()
    db_ex = conn.execute("SELECT id FROM exercises WHERE movement='上斜臥推' AND equipment='啞鈴'").fetchone()["id"]
    mc_ex = conn.execute("SELECT id FROM exercises WHERE movement='上斜臥推' AND equipment='上斜胸推機'").fetchone()["id"]

page = client.get(f"/log/{db_ex}").get_data(as_text=True)
check("首次記錄" in page, "沒有紀錄時顯示首次記錄")

# 組間記錄（fetch）與重送去重
H = {"X-Requested-With": "fetch"}
r = client.post(f"/log/{db_ex}/sets", data={"weight": "10", "reps": "12", "is_warmup": "1", "client_id": "a"}, headers=H)
check(r.json["ok"] and r.json["next_label"] == "第 1 組", "熱身組不計入組數")
r = client.post(f"/log/{db_ex}/sets", data={"weight": "20", "reps": "10", "client_id": "b"}, headers=H)
check(r.json["next_label"] == "第 2 組", "第二組")
r = client.post(f"/log/{db_ex}/sets", data={"weight": "20", "reps": "10", "client_id": "b"}, headers=H)
check(r.json["next_label"] == "第 2 組", "同一 client_id 重送不重複")
r = client.post(f"/log/{db_ex}/sets", data={"weight": "abc", "reps": "10"}, headers=H)
check(r.status_code == 400 and not r.json["ok"], "格式錯誤回 400")

# 換器材時畫面跟著改變
check("首次記錄" in client.get(f"/log/{mc_ex}").get_data(as_text=True), "另一台器材有自己的紀錄")

# 把今天的紀錄挪到昨天，確認「前次紀錄」查得到
with flask_app.app_context():
    from datetime import timedelta
    y = (fj.today() - timedelta(days=1)).isoformat()
    conn = db.get_db()
    conn.execute("UPDATE sets SET date = ?", (y,))
    conn.commit()
page = client.get(f"/log/{db_ex}").get_data(as_text=True)
check("單手 20 kg × 10 下" in page and "昨天" in page, "前次紀錄逐組顯示、啞鈴標單手")
check('value="20"' in page, "預填前次第一個正式組")

# 生活簡記
r = client.post("/life", data={"body_weight": "75.4", "sleep_hours": "7", "food": "雞胸便當"})
check(r.status_code == 302, "簡記儲存")
check("已記錄" in client.get("/").get_data(as_text=True), "首頁標示已記錄")
r = client.post("/life", data={"body_weight": "999"}, follow_redirects=True)
check("體重請填" in r.get_data(as_text=True), "體重範圍檢查")

# 飲食估算
with flask_app.app_context():
    def est(text):
        return {(i["name"], round(i["servings"], 2)) for i in db.estimate(text)["items"]}, db.estimate(text)["unknown"]

    check(est("早餐蛋餅、午餐雞腿便當、晚餐鍋貼20顆")[0] == {("蛋餅", 1), ("雞腿便當", 1), ("鍋貼", 20)}, "基本拆解")
    check(est("兩碗白飯")[0] == {("白飯", 2)}, "數量在前")
    check(est("白飯半碗")[0] == {("白飯", 0.5)}, "半碗")
    check(est("滷肉飯加蛋")[0] == {("滷肉飯", 1), ("蛋", 1)}, "加蛋")
    check(est("雞胸肉200g")[0] == {("雞胸肉", 2)}, "公克換算")
    check(est("蛋餅三明治")[0] == {("蛋餅", 1), ("三明治", 1)}, "三明治的三不是數量")
    check(est("鍋貼一杯豆漿")[0] == {("鍋貼", 1), ("豆漿", 1)}, "數量留給下一個食物")
    check(est("麻辣燙、高蛋白一杯") == ({("高蛋白", 1)}, ["麻辣燙"]), "查不到列為未知")
    check(est("練完高蛋白、下午大杯豆漿")[1] == [], "時間與杯型的字不當成食物")
    r = db.estimate("鍋貼20顆")
    check(round(r["total"]["kcal"]) == 1300 and round(r["total"]["protein"]) == 46, "熱量與蛋白質相乘")

page = client.get("/life").get_data(as_text=True)
check("營養估算" in page and "健康餐盒" in page, "簡記頁顯示估算（雞胸便當 → 健康餐盒）")
check("今日飲食估算" in client.get("/").get_data(as_text=True), "首頁顯示今日估算")
r = client.post("/nutrition/preview", data={"food": "麻辣燙、白飯一碗"}, headers=H)
check("查不到" in r.get_data(as_text=True) and "280" in r.get_data(as_text=True), "即時試算")
r = client.post("/foods", data={"name": "麻辣燙", "unit": "碗", "kcal": "600", "carb": "60",
                                "protein": "25", "fat": "28", "next": "/life"})
check(r.status_code == 302 and r.location.endswith("/life"), "新增食物後回到簡記")
with flask_app.app_context():
    check(not db.estimate("麻辣燙")["unknown"], "新增後查得到")
r = client.post("/foods", data={"name": "麻辣燙", "unit": "碗", "kcal": "1", "carb": "1", "protein": "1", "fat": "1"},
                follow_redirects=True)
check("已經有" in r.get_data(as_text=True), "重複名稱")
r = client.post("/foods", data={"name": "怪東西", "unit": "碗", "kcal": "abc"}, follow_redirects=True)
check("請填寫" in r.get_data(as_text=True), "食物欄位檢查")
check(client.get("/foods").status_code == 200, "食物表頁")

# 每日目標：增重是下限、減重是上限、維持是範圍；蛋白質都是下限
import goals  # noqa: E402

prof = {"mode": "auto", "sex": "m", "height": 175, "age": 22, "activity": "1.55", "kcal_manual": None,
        "protein_per_kg": 1.6, "target_weight": 80}
tg = goals.targets(prof, 75.6)
check(tg["mode"] == "gain" and tg["maintenance"] == 2700 and tg["kcal"] == 3000 and tg["protein"] == 121,
      "自動判斷增重、維持熱量與建議值")
check(goals.resolve_mode(prof, 79.5) == "maintain" and goals.resolve_mode(prof, 82) == "lose", "自動判斷維持與減重")


def fake(kcal, protein, unknown=()):
    return {"items": [1], "unknown": list(unknown), "total": {"kcal": kcal, "protein": protein, "carb": 0, "fat": 0}}


c = goals.compare(fake(2500, 130), tg, in_progress=False)
check(c["kcal"]["state"] == "under" and c["kcal"]["text"] == "少了 500 kcal" and c["protein"]["state"] == "ok",
      "增重：熱量不足、蛋白質夠")
check(goals.compare(fake(2500, 80), tg, in_progress=True)["kcal"]["state"] == "progress", "今天還沒結束只顯示進度")
check(goals.compare(fake(2500, 80, ["麻辣燙"]), tg, False)["kcal"]["state"] == "unknown", "增重＋查不到：無法判斷")
check(goals.compare(fake(3100, 80, ["麻辣燙"]), tg, False)["kcal"]["state"] == "ok", "增重：已知部分就夠了")
check(goals.compare(fake(3600, 130), tg, False)["kcal"]["note"], "增重超過很多會溫和提醒")
lose = goals.targets(dict(prof, mode="lose"), 75.6)
check(lose["kcal"] == 2200, "減重 −500")
check(goals.compare(fake(2500, 130), lose, True)["kcal"]["state"] == "over", "減重：超過上限")
check(goals.compare(fake(2000, 130, ["麻辣燙"]), lose, False)["kcal"]["state"] == "unknown", "減重＋查不到：無法判斷")
check(goals.compare(fake(2000, 130), lose, False)["kcal"]["state"] == "ok", "減重：在上限內")
keep = goals.targets(dict(prof, mode="maintain"), 75.6)
check((keep["kcal_low"], keep["kcal_high"]) == (2430, 2970), "維持 ±10%")
check(goals.compare(fake(2600, 130), keep, False)["kcal"]["state"] == "ok", "維持：在範圍內")
check(goals.compare(fake(3100, 130), keep, False)["kcal"]["state"] == "over", "維持：超過範圍")
check(goals.targets(dict(prof, kcal_manual=2800), 75.6)["kcal"] == 2800, "手動熱量優先")
check(goals.targets(dict(prof, height=None), 75.6)["kcal"] is None, "沒填身高不算熱量")
days = ["2026-01-01", "2026-01-02", "2026-01-03"]
by_day = goals.targets_by_day(prof, days, [("2025-12-30", 70), ("2026-01-02", 72)])
check(by_day["2026-01-01"]["bw"] == 70 and by_day["2026-01-03"]["bw"] == 72, "每天用當時最近的體重")

page = client.get("/").get_data(as_text=True)
check("到設定填身高、年齡" in page and "至少 121" in page, "沒填身高時首頁仍比較蛋白質")
r = client.post("/settings", data={"target_weight": "80", "protein_per_kg": "1.6", "goal_mode": "auto",
                                   "sex": "m", "height_cm": "175", "age": "22", "activity": "1.55", "kcal_manual": ""})
check(r.status_code == 302, "儲存目標設定")
page = client.get("/settings").get_data(as_text=True)
check("現在：增重" in page and "至少 3000 kcal" in page, "設定頁顯示目標（體重 75.4）")
page = client.get("/").get_data(as_text=True)
check("增重目標" in page and "今天還沒結束" in page and "還差" in page, "首頁顯示今天進度")
r = client.post("/settings", data={"target_weight": "80", "protein_per_kg": "1.6", "age": "300"},
                follow_redirects=True)
check("年齡請填" in r.get_data(as_text=True), "目標設定欄位檢查")

# 測試資料、回顧圖表、當天詳情
r = client.post("/demo/seed", follow_redirects=True)
check("已加入測試資料" in r.get_data(as_text=True), "載入測試資料")
# 指定測試資料裡練最多次的動作；預設的「最近練過的動作」會隨執行日期而不同
with flask_app.app_context():
    demo_ex = db.get_db().execute(
        "SELECT exercise_id FROM sets WHERE is_demo = 1 GROUP BY exercise_id ORDER BY COUNT(*) DESC, exercise_id"
    ).fetchone()["exercise_id"]
for pick in ("1", "2", "top"):
    for days in ("30", "90", "all"):
        page = client.get(f"/review?exercise_id={demo_ex}&days={days}&pick={pick}").get_data(as_text=True)
        check('id="fig-train"' in page and 'id="fig-weight"' in page and 'id="fig-food"' in page,
              f"回顧圖表 {days}/{pick}")
page = client.get("/review?days=60").get_data(as_text=True)
check("這段期間的進步" in page, "列出進步紀錄")
check("吃夠了嗎" in page and "達標" in page, "回顧頁統計達標天數")
check("mark-" in client.get("/life").get_data(as_text=True), "簡記頁標示過去幾天有沒有吃夠")
check(client.get(f"/day/{y}?partial=1&exercise_id={db_ex}").status_code == 200, "當天詳情")
r = client.get("/vendor/plotly.min.js", headers={"Accept-Encoding": "gzip"})
check(r.status_code == 200 and r.headers.get("Content-Encoding") == "gzip", "plotly.js")

# 修改與刪除
with flask_app.app_context():
    sid = db.get_db().execute("SELECT id FROM sets WHERE is_demo = 0 ORDER BY id DESC").fetchone()["id"]
r = client.post(f"/sets/{sid}/edit", data={"date": y, "weight": "22", "reps": "9"})
check(r.status_code == 302, "修改")
r = client.post(f"/sets/{sid}/delete")
check(r.status_code == 302, "刪除")

# 匯出、設定、新增器材
csv_text = client.get("/export/sets.csv").get_data(as_text=True)
check(csv_text.startswith("﻿日期") and "測試資料" in csv_text, "CSV 匯出")
daily_csv = client.get("/export/daily.csv").get_data(as_text=True)
check("體重kg" in daily_csv and "估算蛋白質g" in daily_csv and "熱量判斷" in daily_csv, "生活 CSV 含營養估算與判斷")
check(client.get("/settings").status_code == 200, "設定頁")
r = client.post("/exercises/add", data={"body_part": "胸", "movement": "上斜臥推", "equipment": "上斜胸推機（2F）", "step": "5"})
check(r.status_code == 302 and "/log/" in r.location, "新增器材後進入記錄頁")
r = client.post("/demo/clear")
with flask_app.app_context():
    check(not db.has_demo_data(), "清除測試資料")
    check(db.get_db().execute("SELECT COUNT(*) FROM daily").fetchone()[0] == 1, "真實簡記保留")

print(f"全部通過：{ok} 項檢查")
