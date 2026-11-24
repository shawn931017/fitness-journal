"""飲食短記 → 熱量與三大營養素（估算）。

做法：把一句話（例如「早餐蛋餅、午餐雞腿便當、晚餐鍋貼20顆」）拆成
「食物、數量、單位」，再到食物表查「每一單位」的熱量、碳水、蛋白質、脂肪後相乘加總。
食物表找不到的部分列為「未知」，不猜數字，由使用者自行新增到食物表。

內建數值參考衛福部食藥署「食品營養成分資料庫」與常見外食份量估算，
同一種食物各家份量差異很大，只適合看趨勢，不是精確值。
"""
import re
from collections import OrderedDict

# (分類, 名稱, 別名, 單位, 每單位約幾公克/毫升, 熱量kcal, 碳水g, 蛋白質g, 脂肪g)
BUILTIN_FOODS = [
    # ---- 飯類與便當
    ("飯類便當", "白飯", "飯,白米飯", "碗", 160, 280, 62, 4.5, 0.5),
    ("飯類便當", "糙米飯", "五穀飯,紫米飯", "碗", 160, 270, 56, 5.5, 1.5),
    ("飯類便當", "滷肉飯", "魯肉飯", "碗", None, 420, 55, 11, 17),
    ("飯類便當", "雞肉飯", "火雞肉飯", "碗", None, 380, 60, 15, 8),
    ("飯類便當", "便當", "自助餐", "個", None, 800, 100, 32, 30),
    ("飯類便當", "雞腿便當", "雞腿飯", "個", None, 850, 105, 40, 30),
    ("飯類便當", "排骨便當", "排骨飯", "個", None, 900, 105, 35, 38),
    ("飯類便當", "控肉便當", "控肉飯,焢肉飯", "個", None, 950, 100, 30, 48),
    ("飯類便當", "鯖魚便當", "魚排便當", "個", None, 800, 100, 35, 28),
    ("飯類便當", "健康餐盒", "健身餐,雞胸便當,舒肥餐盒", "個", None, 550, 60, 40, 15),
    ("飯類便當", "炒飯", "蛋炒飯,蝦仁炒飯", "盤", None, 650, 85, 18, 25),
    ("飯類便當", "咖哩飯", "咖哩", "盤", None, 700, 95, 20, 25),
    ("飯類便當", "燴飯", "牛肉燴飯,豬肉燴飯", "盤", None, 700, 90, 25, 25),
    ("飯類便當", "壽司", "握壽司", "個", 40, 50, 8, 2.5, 0.6),
    ("飯類便當", "火鍋", "小火鍋,麻辣鍋", "份", None, 900, 70, 50, 45),
    # ---- 麵類
    ("麵類", "牛肉麵", "紅燒牛肉麵", "碗", None, 650, 75, 35, 22),
    ("麵類", "陽春麵", "湯麵", "碗", None, 380, 65, 12, 7),
    ("麵類", "乾麵", "麻醬麵,炸醬麵", "碗", None, 450, 70, 12, 13),
    ("麵類", "義大利麵", "義麵", "盤", None, 650, 85, 22, 23),
    ("麵類", "拉麵", "豚骨拉麵", "碗", None, 750, 85, 28, 32),
    ("麵類", "炒麵", "炒烏龍,炒米粉", "盤", None, 600, 75, 15, 25),
    ("麵類", "鍋燒意麵", "鍋燒麵,鍋燒烏龍", "碗", None, 500, 65, 20, 17),
    # ---- 水餃點心
    ("水餃點心", "水餃", "餃子", "顆", 25, 50, 5.5, 2.2, 2.0),
    ("水餃點心", "鍋貼", "煎餃", "顆", 30, 65, 6.5, 2.3, 3.3),
    ("水餃點心", "小籠包", "湯包", "顆", 25, 45, 4, 2, 2.3),
    ("水餃點心", "餛飩", "抄手", "顆", 15, 25, 2.5, 1.3, 1.0),
    ("水餃點心", "肉包", "包子,菜包", "個", 120, 250, 35, 9, 8),
    ("水餃點心", "饅頭", "白饅頭", "個", 110, 280, 55, 8, 2),
    # ---- 早餐
    ("早餐", "蛋餅", "原味蛋餅", "份", None, 280, 30, 9, 13),
    ("早餐", "起司蛋餅", "培根蛋餅,火腿蛋餅", "份", None, 350, 30, 13, 19),
    ("早餐", "三明治", "總匯三明治", "個", None, 300, 30, 12, 14),
    ("早餐", "吐司", "白吐司,土司", "片", 35, 80, 14, 2.7, 1.2),
    ("早餐", "漢堡", "早餐店漢堡", "個", None, 400, 40, 16, 19),
    ("早餐", "蘿蔔糕", "煎蘿蔔糕", "份", None, 300, 40, 4, 14),
    ("早餐", "飯糰", "台式飯糰", "個", None, 450, 65, 10, 16),
    ("早餐", "御飯糰", "三角飯糰", "個", 110, 200, 38, 5, 3),
    ("早餐", "燒餅油條", "燒餅", "份", None, 450, 50, 10, 23),
    ("早餐", "燕麥", "燕麥片,燕麥粥", "份", 40, 155, 26, 5.5, 3),
    # ---- 蛋白質
    ("蛋白質", "蛋", "雞蛋,水煮蛋,茶葉蛋,溫泉蛋", "顆", 55, 75, 0.5, 6.5, 5),
    ("蛋白質", "荷包蛋", "煎蛋", "顆", 55, 100, 0.5, 6.5, 8),
    ("蛋白質", "雞胸肉", "雞胸", "份", 100, 165, 0, 31, 3.6),
    ("蛋白質", "舒肥雞胸", "即食雞胸", "包", 100, 120, 2, 24, 1.5),
    ("蛋白質", "雞腿", "滷雞腿,烤雞腿", "隻", None, 300, 2, 30, 19),
    ("蛋白質", "排骨", "炸排骨", "片", None, 350, 15, 25, 21),
    ("蛋白質", "鮭魚", "鮭魚排", "片", 100, 210, 0, 20, 14),
    ("蛋白質", "鯖魚", "烤鯖魚", "片", 100, 250, 0, 18, 20),
    ("蛋白質", "牛排", "沙朗", "份", 200, 500, 0, 50, 33),
    ("蛋白質", "豆腐", "板豆腐", "份", 100, 88, 3, 8.5, 4.5),
    ("蛋白質", "高蛋白", "乳清,蛋白粉,高蛋白飲", "杯", 30, 120, 3, 24, 1.5),
    ("蛋白質", "蛋白棒", "高蛋白棒", "條", 60, 200, 22, 20, 7),
    ("蛋白質", "希臘優格", "無糖優格", "杯", 150, 130, 6, 15, 5),
    # ---- 蔬果
    ("蔬果", "燙青菜", "青菜,地瓜葉,高麗菜,花椰菜", "份", None, 60, 5, 2, 4),
    ("蔬果", "沙拉", "生菜沙拉", "份", None, 120, 10, 3, 8),
    ("蔬果", "地瓜", "烤地瓜", "條", 200, 230, 54, 2, 0.4),
    ("蔬果", "香蕉", "", "根", 120, 105, 27, 1.3, 0.4),
    ("蔬果", "蘋果", "", "顆", 200, 95, 25, 0.5, 0.3),
    ("蔬果", "芭樂", "", "顆", 250, 90, 20, 2, 0.3),
    # ---- 飲料
    ("飲料", "豆漿", "甜豆漿,微糖豆漿", "杯", 400, 240, 32, 12, 7),
    ("飲料", "無糖豆漿", "", "杯", 400, 140, 6, 14, 7),
    ("飲料", "牛奶", "鮮奶,全脂牛奶", "杯", 240, 150, 12, 8, 8),
    ("飲料", "珍珠奶茶", "珍奶,波霸奶茶", "杯", 700, 550, 95, 4, 17),
    ("飲料", "奶茶", "紅茶拿鐵", "杯", 500, 350, 55, 3, 13),
    ("飲料", "拿鐵", "咖啡拿鐵,那堤", "杯", 360, 190, 15, 10, 10),
    ("飲料", "黑咖啡", "美式,美式咖啡", "杯", 360, 10, 1.5, 0.5, 0),
    ("飲料", "含糖飲料", "紅茶,綠茶,手搖飲", "杯", 700, 250, 62, 0, 0),
    ("飲料", "可樂", "汽水", "罐", 330, 140, 35, 0, 0),
    ("飲料", "運動飲料", "寶礦力,舒跑", "瓶", 600, 160, 40, 0, 0),
    ("飲料", "啤酒", "", "罐", 330, 145, 11, 1.6, 0),
    # ---- 零食炸物
    ("零食炸物", "鹽酥雞", "炸物", "份", None, 550, 25, 30, 37),
    ("零食炸物", "雞排", "炸雞排", "片", None, 650, 35, 40, 38),
    ("零食炸物", "炸雞", "炸雞腿", "塊", None, 280, 10, 18, 18),
    ("零食炸物", "薯條", "", "份", None, 330, 42, 4, 16),
    ("零食炸物", "披薩", "pizza", "片", None, 280, 33, 12, 11),
    ("零食炸物", "蛋糕", "", "塊", None, 350, 45, 5, 17),
    ("零食炸物", "洋芋片", "", "包", 50, 270, 26, 3, 17),
    ("零食炸物", "堅果", "綜合堅果,杏仁", "份", 30, 180, 6, 5, 16),
]
CATEGORIES = ["飯類便當", "麵類", "水餃點心", "早餐", "蛋白質", "蔬果", "飲料", "零食炸物", "自訂"]

# ---------------------------------------------------------------- 數量與單位

UNITS = ["公克", "毫升", "克", "cc", "ml", "g", "顆", "個", "粒", "隻", "支", "條", "根", "片", "塊", "串",
         "碗", "盤", "份", "杯", "盒", "包", "瓶", "罐", "球", "捲", "匙", "湯匙", "樣", "口"]
GRAM_UNITS = {"公克", "克", "g", "毫升", "cc", "ml"}
SMALL_UNITS = {"顆", "個", "粒", "隻", "支", "條", "根", "片", "塊", "串", "捲"}
SERVING_UNITS = {"碗", "盤", "份", "個", "杯", "盒", "包", "瓶", "罐"}
COUNT_ONLY = {"樣", "口"}  # 只表示數量，不改變單位

CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
NUM = r"(\d+(?:\.\d+)?|半|[零〇一二兩三四五六七八九十百]+半?)"
UNIT_RE = "|".join(sorted((re.escape(u) for u in UNITS), key=len, reverse=True))
AFTER_RE = re.compile(rf"\s*(?:[x×*])?\s*{NUM}\s*({UNIT_RE})?", re.I)
BEFORE_RE = re.compile(rf"{NUM}\s*({UNIT_RE})?\s*$", re.I)
SPLIT_RE = re.compile(r"[、，,；;。.!！?？\n/／()（）\[\]【】+＋]+")
NOISE_RE = re.compile(
    r"早午餐|早餐|午餐|中餐|晚餐|宵夜|消夜|點心|下午茶|訓練後|訓練前|練完|練後|練前|運動完|運動後|睡前|"
    r"早上|中午|下午|晚上|半夜|大杯|中杯|小杯|大份|小份|大碗|小碗|"
    r"吃了|喝了|還有|然後|大概|左右|一些|一點|吃|喝|和|跟|配|加|約|的|了|再|又|都"
)


def parse_number(s):
    s = s.strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    half = s.endswith("半") and len(s) > 1
    if half:
        s = s[:-1]
    if s == "半":
        return 0.5
    total, cur = 0, 0
    for ch in s:
        if ch in CN_DIGITS:
            cur = CN_DIGITS[ch]
        elif ch == "十":
            total += (cur or 1) * 10
            cur = 0
        elif ch == "百":
            total += (cur or 1) * 100
            cur = 0
        else:
            return None
    value = total + cur
    return value + 0.5 if half else value


def unit_compatible(unit, food_unit):
    if not unit or unit in COUNT_ONLY or unit == food_unit:
        return True
    if unit in SMALL_UNITS and food_unit in SMALL_UNITS:
        return True
    return unit in SERVING_UNITS and food_unit in SERVING_UNITS


# ---------------------------------------------------------------- 解析

class FoodIndex:
    """把食物表整理成「別名 → 食物」，比對時優先用最長的名稱（「雞腿便當」先於「雞腿」）。"""

    def __init__(self, foods):
        self.lookup = {}
        for f in foods:
            names = [f["name"]] + [a.strip() for a in (f["aliases"] or "").split(",") if a.strip()]
            for n in names:
                self.lookup.setdefault(n.lower(), f)
        self.names = sorted(self.lookup, key=len, reverse=True)
        self.max_len = max((len(n) for n in self.names), default=0)

    def match_at(self, text, i):
        low = text.lower()
        for length in range(min(self.max_len, len(text) - i), 0, -1):
            f = self.lookup.get(low[i:i + length])
            if f is not None:
                return f, i + length
        return None, i


def _quantity(food, qty, unit):
    """回傳 (以食物表單位計的份數, 提醒文字)。"""
    if qty is None:
        return 1.0, ""
    if unit and unit.lower() in GRAM_UNITS:
        if food["grams"]:
            return qty / food["grams"], ""
        return 1.0, f"「{food['name']}」沒有重量換算，先以 1 {food['unit']} 計"
    if unit_compatible(unit, food["unit"]):
        return qty, ""
    return qty, f"「{unit}」和食物表的「{food['unit']}」不同，先當成 {qty:g} {food['unit']}"


def _leftover(text):
    text = NOISE_RE.sub(" ", text)
    text = re.sub(rf"{NUM}\s*({UNIT_RE})?", " ", text, flags=re.I)
    return [w for w in re.split(r"\s+", text) if len(w) >= 2]


def parse(text, index):
    items, unknown = [], []
    for seg in SPLIT_RE.split(text or ""):
        seg = seg.strip()
        if not seg:
            continue
        i, free_start = 0, 0
        while i < len(seg):
            food, end = index.match_at(seg, i)
            if food is None:
                i += 1
                continue
            before = seg[free_start:i]
            qty, unit = None, None
            # 名稱後面的數量：「鍋貼20顆」
            m = AFTER_RE.match(seg, end)
            # 「蛋餅三明治」的「三」是下一個食物名稱的開頭，不是數量
            if m and index.match_at(seg, m.start(1))[0] is not None:
                m = None
            if m:
                n, u = parse_number(m.group(1)), m.group(2)
                next_food, _ = index.match_at(seg, m.end()) if m.end() < len(seg) else (None, 0)
                # 「鍋貼一杯豆漿」：單位不合又緊接著下一個食物 → 數量留給下一個
                if n is not None and not (u and not unit_compatible(u, food["unit"])
                                          and u.lower() not in GRAM_UNITS and next_food):
                    qty, unit, end = n, u, m.end()
            # 名稱前面的數量：「兩碗白飯」
            mb = BEFORE_RE.search(before)
            if qty is None and mb:
                qty, unit = parse_number(mb.group(1)), mb.group(2)
                before = before[:mb.start()]
            unknown += _leftover(before)
            servings, note = _quantity(food, qty, unit)
            items.append({
                "food_id": food["id"], "name": food["name"], "unit": food["unit"], "servings": servings,
                "kcal": food["kcal"] * servings, "carb": food["carb"] * servings,
                "protein": food["protein"] * servings, "fat": food["fat"] * servings, "note": note,
            })
            i = free_start = end
        unknown += _leftover(seg[free_start:])

    total = {k: sum(it[k] for it in items) for k in ("kcal", "carb", "protein", "fat")}
    return {"items": items, "unknown": list(OrderedDict.fromkeys(unknown)), "total": total,
            "has_food": bool((text or "").strip())}
