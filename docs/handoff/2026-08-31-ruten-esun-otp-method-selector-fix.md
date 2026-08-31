# Ruten 玉山 3DS OTP 驗證方式定位修正

## 問題與根因

- `ruten/fee.py` 在玉山 3DS 驗證方式頁拋出「OTP 驗證方式不唯一」。
- 真實頁面證實舊 XPath 會同時匹配同一選項的外層 `li` 與內層 `label`，因此候選數量為 2；頁面並非提供兩個 OTP 選項。
- 第一版修正後的真實執行顯示 `label=1, radio=0`。同一頁面先前已證實直接點 radio 會逾時、點可見 label 才能成功；原因是客製樣式 radio 不應以 Selenium `is_displayed()` 作為存在條件。
- selector 修正後，relay 的第一個 `200 OK` 事件只有 OTP code，沒有金額與網頁識別碼；`OTPRelayClient.wait_for_event()` 立即回傳，導致 `fee.py` 立刻以「玉山簡訊缺少金額或網頁識別碼」中止，而不是繼續等待完整事件。

## 本階段修改

- 以唯一、可見的「傳送OTP驗證密碼」`label` 取得 `for`，再綁定唯一的 `challengeValue` radio；radio 本身允許因客製樣式而隱藏。
- radio 尚未選取時點擊可見 label，點擊後再次確認 radio 的 selected 狀態。
- 無法唯一綁定時仍 fail-closed，錯誤只記錄脫敏的 label/radio 數量。
- 回歸 fixture 模擬真實的 `li + label + radio` DOM，證明相同文字的父子節點不再中止流程。
- `OTPRelayClient.wait_for_event()` 新增 opt-in `require_correlation`；啟用時忽略缺少金額或識別碼的事件，並在原本總 timeout 內繼續 long-poll。
- 只有 Esun 3DS 路徑啟用 `require_correlation=True`；一般 code-only consumer 與 `wait_for_code()` 維持原行為。
- correlation 規則未放寬；不完整事件永遠不會進入 OTP 欄位或送出按鈕。
- Esun correlation 等待新增固定的脫敏狀態 log：開始等待、尚未收到、收到但缺 correlation、收到完整 correlation。
- 狀態 log 不包含 OTP、網頁識別碼、交易金額、sender 或 SMS 內容；一般 code-only consumer 不輸出這組訊息。

## 真實付款頁驗證狀態

- 已由使用者明確授權送出一筆 TWD 64.00 的露天付款表單。
- 已選擇「傳送OTP驗證密碼」並點擊「下一步」，銀行已進入 OTP 輸入階段。
- 使用者其後再次執行 `fee.py`，該次在驗證方式頁以 `label=1, radio=0` 中止；未由本次修正再建立付款或重跑真實交易。
- 再下一次真實執行已進入 OTP 輸入頁，但因第一筆 relay 事件缺 correlation metadata 而中止；本次 client 修正未再建立或重跑真實付款。
- 未讀取、未輸入、未送出 OTP；未確認付款成功，當前付款結果必須視為 `UNKNOWN`。
- 不得因頁面逾時或關閉而自動重送付款；後續應先由使用者確認本筆交易狀態。

## 驗證紀錄

- TDD RED：隱藏 radio／可見 label fixture 精準重現 `label=1, radio=0`。
- TDD RED：code-only 事件後接完整事件時，舊 client 不支援 correlation-only 等待並立即失敗。
- TDD RED：`204 → code-only 200 → correlated 200` 序列的 client log 原本為空，且第一次 long-poll 前沒有開始等待訊息。
- TDD GREEN：focused regression test 通過。
- `python -m unittest discover -s tests -v`：26 tests passed。
- `python -m py_compile fee.py main.py otp_client.py scheduled_run.py sms.py`：通過。
- `git diff --check`：通過；Git 僅提示既有 Windows 行尾轉換警告。

## 下一次接手起點

1. 不要重送本筆付款。
2. 先確認露天／玉山是否已取消、失敗或仍等待 OTP。
3. 下一筆受控應繳款再用更新後的 `fee.py` 驗證 Selenium 能透過可見 label 由驗證方式頁進入 OTP 輸入頁。
4. 只有露天回到 `paybillok.php` 且同時出現兩個既定成功文字時，才能判定付款完成。
5. 若只收到 code-only 事件後逾時，需檢查 SmsForwarder 是否依 README 傳送 `[org_content]`，或提供移除 OTP／識別碼後的實際 SMS 格式以更新 parser；在取得證據前不得猜 regex。
