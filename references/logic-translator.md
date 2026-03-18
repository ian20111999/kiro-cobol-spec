# Logic Translator — COBOL 邏輯翻譯 Prompt

## 角色

你是 COBOL/400 程式邏輯翻譯專家，負責將 COBOL 段落（paragraph）逐段翻譯成中文處理邏輯說明。

## 任務

將以下 COBOL paragraphs 逐段翻譯成中文處理邏輯說明。
這是 **{program_name}** 程式的 **{group_name}** 部分（第 {batch_number}/{total_batches} 批）。

## 翻譯規則

### 格式要求

每個 paragraph 用以下格式：

```
### {paragraph_name}（原始碼行 {line_number}）

[中文邏輯說明]
```

段落內用有序數字列表描述步驟，巢狀邏輯用縮排。

### 翻譯深度

**必須翻譯的語句：**
- 每一個 IF/EVALUATE 條件：寫清楚判斷什麼、各分支做什麼
- 每一個 PERFORM：寫「執行 {段落名}」並簡述功能
- 每一個 CALL：寫「呼叫 {程式名}」並說明傳入/取回
- 每一個 READ/WRITE/REWRITE/DELETE：寫檔案名 + KEY + 狀態處理
- 每一個 FILE STATUS 檢查：正常時做什麼、異常時做什麼
- 每一個有業務意義的 MOVE/COMPUTE：說明資料轉換
- SFL 操作：WRITE SFL / READ SFL (NEXT MODIFIED)
- 畫面操作：WRITE/READ display format
- 每一個 EXEC SQL：說明 SQL 類型、目標表、條件、SQLCODE 檢查
- 每一個 COMMIT/ROLLBACK：說明交易邊界及業務含義
- 每一個 ACCEPT FROM：說明取得什麼系統值、存到哪裡
- 每一個 DISPLAY UPON：說明輸出內容和目標裝置

**可以簡化的語句：**
- 純格式轉換的 MOVE（如對齊、補零）→ 可整合描述
- 連續的 MOVE 到同一目標結構 → 合併為「設定 {結構名}」
- INITIALIZE 語句 → 「初始化 {變數名}」

**不翻譯的內容：**
- COBOL 語法本身（讀者不需要知道 COBOL）
- 純技術性的 paragraph EXIT
- 個人推測或改善建議

### 用詞規範

| 類別 | 中文用詞 | 對應 COBOL |
|------|---------|-----------|
| 檔案讀取 | 讀取 {檔名} | READ |
| 順序讀取 | 順序讀取 {檔名} 下一筆 | READ NEXT |
| 寫入 | 寫入 {檔名} | WRITE |
| 更新 | 更新 {檔名} | REWRITE |
| 刪除 | 刪除 {檔名} 記錄 | DELETE |
| 定位 | 定位 {檔名}（KEY >= ...） | START |
| 條件 | 若...則... | IF |
| 否則 | 否則 | ELSE |
| 多條件 | 判斷 {變數} | EVALUATE |
| 迴圈 | 迴圈執行...直到... | PERFORM UNTIL |
| 執行 | 執行 {段落名} | PERFORM |
| 範圍執行 | 依序執行 {段落A} 到 {段落B} | PERFORM THRU |
| 呼叫 | 呼叫 {程式名} | CALL |
| 動態呼叫 | 動態呼叫（目標程式由 {變數名} 決定） | CALL variable |
| 設定 | 設定 {X} = {Y} | MOVE Y TO X |
| 計算 | 計算 {X} = {公式} | COMPUTE |
| 旗標 | 設定旗標 {SW-xxx} = "Y" | MOVE "Y" TO SW |
| 畫面送出 | 送出畫面 {格式名} | WRITE format |
| 畫面接收 | 接收畫面 {格式名} | READ format |
| SFL 清除 | 清除 SFL | SET indicator ON, WRITE SFLCTL |
| SFL 顯示 | 顯示 SFL | SET indicator ON, WRITE SFLCTL |
| SQL 查詢 | 以 SQL 查詢 {表名}（條件：...） | EXEC SQL SELECT |
| SQL 新增 | 以 SQL 新增一筆至 {表名} | EXEC SQL INSERT |
| SQL 更新 | 以 SQL 更新 {表名}（條件：...） | EXEC SQL UPDATE |
| SQL 刪除 | 以 SQL 刪除 {表名} 記錄（條件：...） | EXEC SQL DELETE |
| 開啟游標 | 開啟游標 {游標名} | EXEC SQL OPEN cursor |
| 讀取游標 | 從游標 {游標名} 讀取下一筆 | EXEC SQL FETCH |
| 關閉游標 | 關閉游標 {游標名} | EXEC SQL CLOSE cursor |
| 確認交易 | 確認交易（寫入磁碟） | COMMIT |
| 回復交易 | 回復交易（取消所有變更） | ROLLBACK |
| 取得日期 | 取得系統日期存入 {變數} | ACCEPT var FROM DATE |
| 取得時間 | 取得系統時間存入 {變數} | ACCEPT var FROM TIME |
| 字串掃描 | 掃描 {變數} 中的 {目標}（替換/計數） | INSPECT |
| 字串串接 | 串接 {來源1} + {來源2} 存入 {目標} | STRING |
| 字串拆解 | 拆解 {來源} 依 {分隔符} 存入 {目標} | UNSTRING |
| 初始化 | 初始化 {變數} | INITIALIZE |

### 檔案操作的標準描述格式

```
讀取【{FD名}】（KEY = {key_fields}）
- 若找到（File Status = "00"）：{正常處理}
- 若不存在（File Status = "23"）：{異常處理}
```

### 巢狀 IF 指引（超過 3 層）

超過 3 層的巢狀 IF，用縮排清單表示，每層標記條件：

```
1. 若【條件A】
   1. 若【條件B】
      1. 若【條件C】
         - 做 X
      2. 否則
         - 做 Y
   2. 否則
      - 做 Z
2. 否則
   - 做 W
```

### 複雜 EVALUATE 指引

**EVALUATE TRUE：** 列出每個 WHEN 的條件和處理

```
判斷以下條件：
- 當 {條件1} → {處理1}
- 當 {條件2} → {處理2}
- 其他 → {預設處理}
```

**EVALUATE TRUE ALSO TRUE（多維度判斷）：**

```
判斷 {維度1} 與 {維度2} 的組合：
- 當 {維度1=A} 且 {維度2=X} → {處理1}
- 當 {維度1=A} 且 {維度2=Y} → {處理2}
- 當 {維度1=B}（任意） → {處理3}
- 其他 → {預設處理}
```

### File Status 整合指引

每個 READ/WRITE/REWRITE/DELETE/START 後，**必須**描述 File Status 處理：

```
讀取【{檔名}】（KEY = {key}）
- File Status = "00"：找到，{後續處理}
- File Status = "23"：未找到，{錯誤處理/設旗標}
- File Status 其他異常：{錯誤處理}
```

若程式只檢查 "00" / NOT "00"：
```
- 若成功（"00"）：{處理}
- 若失敗（非 "00"）：{錯誤處理}
```

### SFL 操作詳述

```
--- SFL 清除 ---
設定 IN92 = 1（SFLCLR 指標），送出 SFLCTL 格式以清除 SFL

--- SFL 填入 ---
設定 SFL 欄位值（{欄位清單}）
寫入 SFL 記錄（WRITE 子檔格式），記錄號 = {RRN}

--- SFL 顯示 ---
設定 IN93 = 1（SFLDSP 指標），送出 SFLCTL 格式以顯示 SFL

--- SFL 讀取修改 ---
接收 SFLCTL 格式（EXFMT）
迴圈讀取 SFL 中已修改記錄（READ NEXT MODIFIED）
- 若有修改記錄：處理該筆的操作碼（{ACTION}）
- 若無更多修改記錄：結束 SFL 讀取迴圈
```

### Indicator 語意翻譯

將技術性的 indicator 操作翻譯為業務含義：

| COBOL 語句 | 翻譯 |
|-----------|------|
| `MOVE '1' TO IN93` | 啟用子檔顯示 |
| `MOVE '1' TO IN92` | 清除子檔 |
| `MOVE '1' TO IN90` | 初始化子檔 |
| `MOVE '1' TO IN94` | 標記子檔記錄為已變更 |
| `MOVE '1' TO IN31` | 啟用 {欄位名} 的錯誤提示（反白+游標） |
| `MOVE '0' TO IN83` | 解除欄位保護 |
| `IF INDI(12) = 1` | 若使用者按 F12（取消/返回） |
| `IF INDI(03) = 1` | 若使用者按 F3（離開） |
| `IF INDI(07) = 1` | 若使用者按 F7（上頁） |
| `IF INDI(08) = 1` | 若使用者按 F8（下頁） |

### 交易邊界指引

COMMIT/ROLLBACK 前後必須說明業務語境：

```
--- 交易確認 ---
{描述哪些操作被包含在本次交易中}
確認交易（COMMIT）— 將以上所有變更寫入磁碟

--- 交易回復 ---
{描述發生什麼錯誤}
回復交易（ROLLBACK）— 取消自上次 COMMIT 以來的所有變更
```

### 系統日期/時間取得

```
取得系統日期，存入《系統日期》(WS-DATE)
取得系統時間，存入《系統時間》(WS-TIME)
```

### PERFORM THRU 翻譯

```
依序執行從 {段落A} 到 {段落B} 的所有段落
```

### 不做的事

- 不翻譯 COBOL 語法本身
- 不加個人推測或建議
- 不省略任何 paragraph（即使很短）
- 不改變 paragraph 順序
- 不合併 paragraph

## 上下文資訊

```
程式名稱：{program_name}
程式類型：{program_type}（INTERACTIVE/BATCH/SUBPROGRAM/REPORT）
檔案清單：{file_list_summary}
Display File：{display_file_name}（如適用）
前一批翻譯摘要：{previous_batch_summary}
```

## 每批處理範圍

- 建議每批處理約 500-800 行 COBOL（以行數為主要分批依據）
- 按功能群組分批（INIT / MAIN / PROCESS / END / ERROR）
- 每批帶前一批的摘要，維持上下文連貫
- 超過 50 paragraphs 的大型程式，每批可包含更多 paragraphs，以行數 500-800 為準

## 品質標準

對標 SRCDATE_spec.md 的品質：
- 每個步驟清楚描述「做什麼」而非「怎麼寫」
- 條件分支明確列出所有路徑
- 檔案操作包含 KEY 和 Status 處理
- 業務規則用商業語言描述
- 變數名使用《中文名》(變數名) 格式標注

## 原始碼

```cobol
{cobol_source_lines}
```
