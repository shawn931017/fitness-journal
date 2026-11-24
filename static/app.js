/* 健身月記：少量前端互動（加減按鈕、組間送出與重送、圖表點選） */
(function () {
  "use strict";
  var FJ = (window.FJ = {});

  /* ---------- 加減按鈕 ---------- */
  document.addEventListener("click", function (e) {
    var b = e.target.closest("button.step");
    if (!b) return;
    var input = document.getElementById(b.dataset.target);
    if (!input) return;
    var raw = (input.value || "").replace(",", ".").trim();
    var delta = parseFloat(b.dataset.delta);
    var v;
    if (raw === "" && b.dataset.empty) {
      v = parseFloat(b.dataset.empty);
    } else {
      v = (parseFloat(raw) || 0) + delta;
    }
    var min = b.dataset.min ? parseFloat(b.dataset.min) : 0;
    v = Math.max(min, Math.round(v * 100) / 100);
    input.value = String(v);
  });

  /* ---------- 複製網址 ---------- */
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-copy]");
    if (!b) return;
    var el = document.querySelector(b.dataset.copy);
    if (!el || !navigator.clipboard) return;
    navigator.clipboard.writeText(el.textContent.trim()).then(function () {
      var old = b.textContent;
      b.textContent = "已複製";
      setTimeout(function () { b.textContent = old; }, 1500);
    });
  });

  /* ---------- 提示訊息自動淡出 ---------- */
  document.querySelectorAll(".flash-ok").forEach(function (el) {
    setTimeout(function () { el.classList.add("fade"); }, 2500);
  });

  /* ---------- 組間記錄：送出失敗時保留內容、標示「尚未儲存」 ---------- */
  var form = document.getElementById("set-form");
  if (form) initSetForm(form);

  function newId() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
  }

  function initSetForm(form) {
    var key = "fj-unsaved-" + form.dataset.ex;
    var status = document.getElementById("save-status");
    var btn = document.getElementById("save-btn");
    var f = form.elements;
    var pending = false;

    function show(kind, html) {
      status.className = "save-status " + (kind || "");
      status.innerHTML = html || "";
    }

    // 上次沒送出成功（例如關掉 App）→ 放回欄位
    var draft = null;
    try { draft = JSON.parse(localStorage.getItem(key) || "null"); } catch (err) { draft = null; }
    if (draft) {
      f.weight.value = draft.weight;
      f.reps.value = draft.reps;
      f.is_warmup.checked = !!draft.warm;
      f.client_id.value = draft.client_id;
      show("unsaved", "<strong>尚未儲存</strong>上次這一組沒有存進去，數值已放回欄位，請按「重新送出」。");
      btn.textContent = "重新送出";
    } else {
      f.client_id.value = newId();
    }

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      if (pending) return;
      pending = true;
      var data = new FormData(form);
      localStorage.setItem(key, JSON.stringify({
        weight: f.weight.value, reps: f.reps.value, warm: f.is_warmup.checked, client_id: f.client_id.value,
      }));
      btn.disabled = true;
      btn.textContent = "儲存中…";
      show("", "");

      var ctrl = window.AbortController ? new AbortController() : null;
      var timer = setTimeout(function () { if (ctrl) ctrl.abort(); }, 15000);

      fetch(form.action, {
        method: "POST", body: data, credentials: "same-origin",
        headers: { "X-Requested-With": "fetch" }, signal: ctrl ? ctrl.signal : undefined,
      })
        .then(function (res) {
          return res.json().catch(function () { return null; }).then(function (json) {
            return { res: res, json: json };
          });
        })
        .then(function (r) {
          if (r.res.ok && r.json && r.json.ok) {
            localStorage.removeItem(key);
            document.getElementById("today-sets").innerHTML = r.json.html;
            document.getElementById("next-label").textContent = r.json.next_label;
            f.client_id.value = newId();
            f.is_warmup.checked = false;
            btn.textContent = "儲存這一組";
            show("ok", "已儲存 ✓");
            if (navigator.vibrate) navigator.vibrate(30);
            setTimeout(function () { if (status.classList.contains("ok")) show("", ""); }, 2500);
          } else if (r.res.status === 400 && r.json) {
            localStorage.removeItem(key);
            btn.textContent = "儲存這一組";
            show("error", r.json.error);
          } else {
            var msg = (r.json && r.json.error) || "伺服器沒有回應（" + r.res.status + "）。";
            throw new Error(msg);
          }
        })
        .catch(function (err) {
          var reason = err && err.name === "AbortError" ? "連線逾時。"
            : (err && err.message && err.message.indexOf("登入") >= 0 ? err.message : "網路連線失敗。");
          btn.textContent = "重新送出";
          show("unsaved", "<strong>尚未儲存</strong>" + reason + "數值仍在欄位中，網路恢復後按「重新送出」。");
        })
        .then(function () {
          clearTimeout(timer);
          pending = false;
          btn.disabled = false;
        });
    });
  }

  /* ---------- 飲食短記：邊打字邊試算熱量與營養素 ---------- */
  var foodBox = document.querySelector("textarea[data-nutrition-preview]");
  if (foodBox) {
    var target = document.getElementById("nutrition-preview");
    var timer = null, seq = 0;
    var draftKey = "fj-food-draft-" + ((foodBox.form.elements.date || {}).value || "");
    // 尚未儲存就跑去新增食物 → 回來時把剛才打的內容放回去
    var foodDraft = localStorage.getItem(draftKey);
    localStorage.removeItem(draftKey);
    if (foodDraft !== null && foodDraft !== foodBox.value) {
      foodBox.value = foodDraft;
      var note = document.createElement("p");
      note.className = "hint unsaved-note";
      note.textContent = "已放回剛才輸入的內容，記得按「儲存」。";
      foodBox.parentNode.insertBefore(note, foodBox.nextSibling);
      setTimeout(function () { foodBox.dispatchEvent(new Event("input")); }, 0);
    }
    var initialFood = foodBox.value;
    document.addEventListener("click", function (e) {
      if (e.target.closest("#nutrition-preview a") && foodBox.value !== initialFood) {
        localStorage.setItem(draftKey, foodBox.value);
      }
    });
    foodBox.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        var mine = ++seq;
        var body = new FormData();
        body.append("food", foodBox.value);
        body.append("date", (foodBox.form.elements.date || {}).value || "");
        fetch(foodBox.dataset.nutritionPreview, {
          method: "POST", body: body, credentials: "same-origin", headers: { "X-Requested-With": "fetch" },
        })
          .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
          .then(function (html) { if (mine === seq) target.innerHTML = html; })
          .catch(function () { /* 離線時不試算，儲存後仍會計算 */ });
      }, 450);
    });
  }

  /* ---------- 月回顧：畫圖、點資料點看當天全部組別 ---------- */
  FJ.initReview = function () {
    var reviewForm = document.getElementById("review-form");
    if (reviewForm) reviewForm.addEventListener("change", function () { reviewForm.submit(); });

    var cfg = { responsive: true, displayModeBar: false };
    ["train", "weight", "food"].forEach(function (name) {
      var holder = document.getElementById("fig-" + name);
      var el = document.getElementById("chart-" + name);
      if (!holder || !el || !window.Plotly) return;
      var fig = JSON.parse(holder.textContent);
      Plotly.newPlot(el, fig.data, fig.layout, cfg).then(function () {
        el.on("plotly_click", function (ev) {
          var p = ev.points && ev.points[0];
          if (p && p.customdata) FJ.showDay(p.customdata);
        });
      });
    });

    document.addEventListener("click", function (e) {
      var a = e.target.closest("[data-day]");
      if (a) { e.preventDefault(); FJ.showDay(a.dataset.day); return; }
      if (e.target.closest("[data-close-panel]")) {
        var panel = document.getElementById("day-panel");
        if (panel) panel.hidden = true;
      }
    });
  };

  FJ.showDay = function (day) {
    var panel = document.getElementById("day-panel");
    if (!panel) { location.href = "/day/" + day; return; }
    panel.hidden = false;
    panel.innerHTML = '<p class="muted">載入中…</p>';
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    fetch(panel.dataset.url.replace("DAY", encodeURIComponent(day)), {
      credentials: "same-origin", headers: { "X-Requested-With": "fetch" },
    })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (html) {
        panel.innerHTML = html;
        panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
      })
      .catch(function () { panel.innerHTML = '<p class="muted">載入失敗，請稍後再試。</p>'; });
  };
})();
