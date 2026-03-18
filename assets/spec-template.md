# {PROGRAM_ID} ({SPOOL_ID}) — {PROGRAM_NAME}

> **程式類型**：{PROGRAM_TYPE}
> **開發日期**：{DEV_DATE}
> **原始碼**：{SOURCE_INFO}

---

## 一. 程式邏輯

{LOGIC_SECTION}

---

## 二. 副程式表格

| 程式代號 | 功能說明 | 呼叫段落 | 傳入參數 | 取回結果 |
|---------|---------|---------|---------|---------|
{CALL_TABLE}

---

## 三. Table 定義

{TABLE_SECTION}

---

{IF_HAS_SQL}
## 三之一. SQL 操作

| # | SQL 類型 | 目標表/游標 | 條件/KEY | 所在段落 | 說明 |
|---|---------|-----------|---------|---------|------|
{SQL_TABLE}

---

{END_IF_HAS_SQL}

{IF_HAS_ERROR_HANDLING}
## 三之二. 錯誤處理

### File Status 異常處理總表

| 檔案名稱 | File Status | 處理方式 | 所在段落 |
|---------|------------|---------|---------|
{ERROR_HANDLING_TABLE}

{END_IF_HAS_ERROR_HANDLING}

{IF_HAS_KEY_WS_VARS}
## 三之三. 重要 WORKING-STORAGE 變數

### 開關/旗標

| 變數名稱 | 型態 | 用途說明 |
|---------|------|---------|
{SWITCHES_TABLE}

### 計數器/狀態

| 變數名稱 | 型態 | 用途說明 |
|---------|------|---------|
{COUNTERS_TABLE}

### 工作表格（OCCURS）

| 變數名稱 | 維度 | 用途說明 |
|---------|------|---------|
{WORK_TABLES_TABLE}

{END_IF_HAS_KEY_WS_VARS}

{IF_HAS_TRANSACTION}
## 三之四. 交易控制

| # | 類型 | 所在段落 | 說明 |
|---|------|---------|------|
{TRANSACTION_TABLE}

**交易範圍說明：**
{TRANSACTION_SCOPE}

---

{END_IF_HAS_TRANSACTION}

{IF_INTERACTIVE}
## 四. 畫面規格

### 畫面排版

```
{SCREEN_LAYOUT}
```

### Record Format 欄位

{SCREEN_FIELDS}

### Function Key 對照表

| 按鍵 | 指標 | 功能說明 |
|------|------|---------|
{FK_TABLE}

### Indicator 對照表

| 指標 | 用途 | 控制欄位/動作 |
|------|------|-------------|
{INDICATOR_TABLE}

{END_IF_INTERACTIVE}

---

## 五. 參數介面

### LINKAGE SECTION

{LINKAGE_TABLE}

### LDA（Local Data Area）

| # | 位置 (起-迄) | 長度 | 欄位名稱 | 用途說明 |
|---|-------------|------|---------|---------|
{LDA_TABLE}
