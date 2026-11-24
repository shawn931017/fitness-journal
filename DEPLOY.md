# 部署到 PythonAnywhere（免費方案）

以下的 `<帳號>` 請換成你的 PythonAnywhere 使用者名稱，網址會是 `https://<帳號>.pythonanywhere.com`。

## 1. 上傳程式

1. 到 <https://www.pythonanywhere.com> 註冊 Beginner（免費）帳號。
2. 把整個 `fitness-journal` 資料夾壓成 zip（**不要**包含 `instance/` 資料夾）。
3. 進入 **Files** 分頁，上傳 zip 到 `/home/<帳號>/`。
4. 開一個 **Bash console**（Consoles → Bash），解壓縮：

   ```bash
   cd ~
   unzip fitness-journal.zip
   ls fitness-journal      # 應該看得到 app.py
   ```

   （若程式放在 GitHub，也可以直接 `git clone <repo 網址> fitness-journal`。）

## 2. 安裝套件、設定帳號密碼

先決定要用的 Python 版本（第 3 步 Web 分頁會選同一版，以下以 3.13 為例；若沒有就改成清單裡最新的版本）。

```bash
cd ~/fitness-journal
pip3.13 install --user -r requirements.txt
python3.13 -m flask --app app set-password
```

依提示輸入帳號與密碼（至少 8 碼，輸入時畫面不會顯示）。之後要改密碼也是同一個指令。

## 3. 建立 Web App

1. **Web** 分頁 → **Add a new web app** → 下一步 → 選 **Manual configuration**（不要選 Flask 範本）→ 選 **Python 3.13**。
2. 在 Web 分頁的 **Code** 區：
   - Source code：`/home/<帳號>/fitness-journal`
   - Working directory：`/home/<帳號>/fitness-journal`
3. 點 **WSGI configuration file** 的連結，把內容**全部刪掉**換成：

   ```python
   import os
   import sys

   path = "/home/<帳號>/fitness-journal"
   if path not in sys.path:
       sys.path.insert(0, path)

   os.environ["FJ_SECURE_COOKIE"] = "1"   # 只透過 HTTPS 傳送登入 cookie

   from app import app as application
   ```

   存檔。
4. **Static files** 區新增一列：URL 填 `/static/`，Directory 填 `/home/<帳號>/fitness-journal/static`。
5. **Security** 區把 **Force HTTPS** 打開。
6. 按最上方綠色的 **Reload**，打開 `https://<帳號>.pythonanywhere.com` 應該會看到登入頁。

## 4. iPhone 加入主畫面

1. 用 **Safari** 開啟網址並登入。
2. 點分享按鈕 → **加入主畫面**。
3. 從主畫面的「健身月記」圖示開啟。iOS 的主畫面 App 和 Safari 分開儲存登入狀態，**第一次從圖示開啟要再登入一次**，之後會保持登入。

## 5. 每晚提醒（iPhone「提醒事項」）

網頁推播需要 Service Worker、免費主機也無法排程，所以改用 iPhone 內建的提醒：

1. 「提醒事項」新增一則「睡前簡記」。
2. 點 ⓘ：開啟日期與時間（例如 22:30），重複選「每天」。
3. URL 欄貼上 `https://<帳號>.pythonanywhere.com/life`（App 的「簡記」頁最下方也有可複製的網址）。

## 6. 測試資料

- 想先看月曲線效果：App 的「設定 → 測試資料 → 載入測試資料」，或在 Bash console 執行
  `python3.13 -m flask --app app seed-demo`。
- 測試資料全部標示「測試」。正式開始記錄前到「設定」按「清除測試資料」（或 `clear-demo` 指令），真實紀錄不受影響。

## 7. 維護

- **免費方案每個月要延長一次**：登入 PythonAnywhere → Web 分頁 → 按 **Run until 1 month from today**，否則網站會停用。
- **備份**：每週在 App 的「設定 → 匯出備份」下載兩份 CSV；也可以在 Files 分頁下載
  `/home/<帳號>/fitness-journal/instance/fitness.db`（完整資料庫）。
- **更新程式**：上傳新檔案覆蓋（保留 `instance/` 資料夾不要動），再到 Web 分頁按 **Reload**。
- **出錯時**：Web 分頁下方的 **Error log** 會有錯誤訊息。
- 時區預設台灣時間（`Asia/Taipei`），日期一律以台灣時間判斷；若要更改可在 WSGI 檔加 `os.environ["FJ_TIMEZONE"] = "..."`。
