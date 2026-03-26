---
name: cobol-spec
description: >
  解析 AS/400 COBOL 程式並產出標準化中文規格書。
  支援單檔分析或整資料夾批次處理多支程式。
  支援 AS/400 遠端連線自動撈取（PATH B）或本地 spool 解析（PATH A）。
  涵蓋線上互動、批次、副程式、報表等所有程式類型。
  觸發：使用者提到 /cobol-spec、分析 COBOL、產生規格書、翻譯 COBOL、
  或提供 .txt spool file / 資料夾 / 程式名 進行分析。
license: MIT
compatibility: Kiro, Claude Code
metadata:
  category: cobol-analysis
  complexity: advanced
  author: ian
  version: "4.0.0"
---

# COBOL Spec Generator v4.0

支援兩條路徑：本地 spool 解析（PATH A）或 AS/400 遠端撈取（PATH B）。
不管使用者給什麼輸入，產出格式一致：7 章節規格書。

## 目標讀者

規格書的讀者是 **Java 工程師**。他們不懂 COBOL，但要根據這份規格書寫出邏輯完全相同的 Java 程式。因此：

- 所有 COBOL 特有概念必須翻譯成通用程式概念
- 每段邏輯要清楚到「照著寫就對了」的程度
- 檔案操作、畫面流程、錯誤處理都要完整，不能有模糊地帶
- 副程式的呼叫時機、傳入參數、回傳值要寫清楚

## 使用方式

```
/cobol-spec your_spool.txt                    # PATH A: 本地 spool 檔案
/cobol-spec --batch /path/to/folder           # PATH A: 批次模式
/cobol-spec --batch a.txt b.txt c.txt         # PATH A: 多檔批次
/cobol-spec PFD0062                           # PATH B: 程式名（遠端撈取）
```

## 雙路徑架構

```
使用者輸入
  │
  ├── 是 .txt 檔案？ ──────────────────── PATH A（本地）
  │   │
  │   ├── 偵測 AS/400 連線？
  │   │   ├── 有 → 混合模式：本地 source + 遠端補齊缺少的 DDS/副程式
  │   │   └── 無 → 純本地（現有流程，缺的就推斷）
  │   │
  │   └── 產出 7 章節 spec
  │
  └── 是程式名？ ──────────────────────── PATH B（遠端）
      │
      ├── 自動偵測連線方式（SSH > ODBC > DB2 CLI）
      ├── 自動發現 Library
      ├── DSPPGMREF → 所有引用檔案 + 程式清單
      ├── 撈 source code
      ├── 撈所有檔案 schema（DSPFFD）
      ├── 撈檔案關聯（DSPDBR）→ ERD
      ├── 撈副程式 source
      │
      └── 產出 7 章節 spec
```

## 互動原則

**不管哪條路徑，使用者說了就直接跑。**

### 何時不打擾使用者
- 檔案內只有一支 COBOL → 直接分析
- 檔案內有多支 COBOL → 全部都分析
- DDS 在 spool 裡 / 同資料夾 / 遠端可撈 → 自動取得
- 副程式在 spool 裡 / 同資料夾 / 遠端可撈 → 自動分析
- CL 程式 → 寫進 spec

### 何時才打擾使用者
- **未提供檔名也未提供程式名**：請使用者指定
- **AS/400 連線失敗（PATH B）**：提示設定連線
- **商業邏輯不明確**：這是唯一「必須」打擾使用者的情況
- **DDS/副程式找不到且無遠端**：告知缺少哪些，從 WORKING-STORAGE 推斷並標註

### 打擾格式
```
⚠️ 需要確認
📌 [具體問題]
💡 我目前的理解：[你的推斷]
```

## 可用腳本

| 腳本 | 功能 | CLI 用法 |
|------|------|----------|
| `scripts/encoding.py` | 偵測 Big5/UTF-8 編碼 | `python3 encoding.py <file>` |
| `scripts/format_normalizer.py` | 格式偵測 + 標註清理 + member 拆分 | `python3 format_normalizer.py <file_or_dir>` |
| `scripts/spool_splitter.py` | Spool → inventory JSON | `python3 spool_splitter.py <spool_file>` |
| `scripts/cobol_skeleton.py` | COBOL → skeleton JSON | `python3 cobol_skeleton.py <spool_file> [--program NAME]` |
| `scripts/dds_parser.py` | DDS → field list JSON | `python3 dds_parser.py <file> [--dspf] [--spool --start N --end M]` |
| `scripts/spec_validator.py` | 驗證 spec 完整性（13 checks） | `python3 spec_validator.py <spec.md> <skeleton.json>` |
| `scripts/md2html.py` | Markdown → HTML | `python3 md2html.py <input.md> [output.html]` |
| `scripts/batch_inventory.py` | 批次掃描多 .txt | `python3 batch_inventory.py <dir_or_files...>` |
| `scripts/as400_connector.py` | AS/400 連線管理 | `python3 as400_connector.py --test / --setup / --run-cl "..."` |
| `scripts/as400_fetcher.py` | AS/400 資料撈取 | `python3 as400_fetcher.py <program_name> [--output file.json]` |

所有腳本路徑前綴：`/Users/ian/.claude/skills/cobol-spec/scripts/`
所有腳本均支援 `--help`。

## 工作流程

### Step 0: 判斷輸入類型（自動）

```
輸入 → 判斷
  ├── 以 .txt 結尾 or 是檔案路徑 → PATH A
  ├── 是資料夾路徑 → PATH A（批次模式）
  └── 其他（如 PFD0062）→ PATH B
```

---

## PATH A：本地 Spool 分析

使用者提供 .txt spool file 時走此路徑。

### Step A1: 前處理（自動）

```bash
python3 /Users/ian/.claude/skills/cobol-spec/scripts/format_normalizer.py <spool_file> --json
```

- 偵測編碼（Big5 / UTF-8）
- 偵測格式（SEU / COPY_FILE / DSPFFD / MSGFILE）
- 清理 SEU 標註殘留
- 拆分多 member 檔案

### Step A2: Spool 拆解（自動）

```bash
python3 /Users/ian/.claude/skills/cobol-spec/scripts/spool_splitter.py <spool_file>
```

產出 JSON inventory（DDS/COBOL/CL 區塊 + 行號範圍）。
存為 `output/{program_id}/{spool}_inventory.json`。

### Step A3: 骨架解析（自動）

```bash
python3 /Users/ian/.claude/skills/cobol-spec/scripts/cobol_skeleton.py <spool_file> --program <program_name>
```

產出 JSON skeleton（files, paragraphs, calls, linkage, type）。
存為 `output/{program_id}/{program}_skeleton.json`。

### Step A4: 嘗試 AS/400 連線補齊（自動）

嘗試偵測 AS/400 連線：

```bash
python3 /Users/ian/.claude/skills/cobol-spec/scripts/as400_connector.py --test
```

| 結果 | 動作 |
|------|------|
| 有連線 | **混合模式**：用遠端 DSPFFD 補齊缺少的 DDS schema、用 DSPOBJD TEXT 取得副程式說明、用 DSPDBR 取得檔案關聯做 ERD |
| 無連線 | **純本地**：從 spool DDS 或 WORKING-STORAGE 推斷（現有行為），ERD 從程式邏輯推斷 |

混合模式的遠端補齊：
```python
# 對 skeleton.files 中缺少 DDS 的檔案
fetcher.get_file_schema(library, filename)   # DSPFFD
fetcher.get_file_relations(library, filename) # DSPDBR
# 對 skeleton.calls 中的副程式
fetcher.get_program_text(library, program)   # DSPOBJD TEXT
```

### Step A5-A8: 分析 + 組裝

同 PATH B 的 Step B4-B7（見下方）。

---

## PATH B：AS/400 遠端撈取

使用者提供程式名（非 .txt 路徑）時走此路徑。

### Step B1: AS/400 連線（自動）

```bash
python3 /Users/ian/.claude/skills/cobol-spec/scripts/as400_connector.py --test
```

連線偵測順序：SSH → ODBC → ibm_db

若連線失敗：
```
⚠️ 無法連線 AS/400
📌 請先設定連線：python3 as400_connector.py --setup
💡 或提供 spool .txt 檔案改走本地分析
```

### Step B2: 資料撈取（自動）

```bash
python3 /Users/ian/.claude/skills/cobol-spec/scripts/as400_fetcher.py <program_name> --output /tmp/fetcher_result.json
```

fetcher 會自動：
1. 用 DSPOBJD 發現程式所在 Library
2. 用 CPYTOSTMF 撈 source code
3. 用 DSPPGMREF 取得所有引用檔案和程式
4. 用 DSPFFD 取得每個檔案的欄位定義
5. 用 DSPDBR 取得檔案關聯（做 ERD）
6. 取得副程式的 DSPOBJD TEXT

產出 JSON 包含所有資料。

### Step B3: 轉換為 Pipeline 格式（自動）

fetcher 已將 source 存為 spool 相容的 .txt 格式。

執行 cobol_skeleton.py 解析程式結構：
```bash
python3 /Users/ian/.claude/skills/cobol-spec/scripts/cobol_skeleton.py <source_file_path> --program <program_name>
```

### Step B4 + B5: 分析 + 組裝（極細粒度 Agent 架構）

**⚠️ 防 timeout 鐵律 — 任何單一 AI context 的總輸入不得超過 800 行。**

超過就會 API timeout。不管是主對話還是 Agent subagent 都一樣。

---

#### 主對話的角色：純調度員

主對話只做：
1. 執行 Python 腳本（輸出 JSON）
2. 讀取 skeleton JSON（~50 行）計算批次
3. 派出 Agent subagent
4. 用 **bash cat 組裝**最終 spec

**主對話絕對禁止：**
- ❌ 讀取任何 `references/*.md` 檔案
- ❌ 讀取 `assets/cobol-dictionary.json`
- ❌ 讀取 COBOL source code
- ❌ 做邏輯翻譯
- ❌ 用 Write/Edit 寫 spec 內容（改用 bash cat）

---

#### Step B4a: 計算批次（主對話）

從 skeleton JSON 取得 PROCEDURE DIVISION 行範圍，分成 **每批最多 300 行**：

```python
# 虛擬碼，主對話用 skeleton JSON 手動計算
proc_start = skeleton["procedure_division_line"]  # 或從 paragraphs 推算
proc_end = skeleton["source_lines"]               # 或最後一個 paragraph 的行號
total_lines = proc_end - proc_start

batch_size = 300
num_batches = ceil(total_lines / batch_size)

batches = []
for i in range(num_batches):
    start = proc_start + i * batch_size
    end = min(proc_start + (i+1) * batch_size, proc_end)
    batches.append((start, end))
```

---

#### Step B4b: 派出所有 Agent（並行）

**所有 Agent 同時啟動，互不依賴。**

##### Agent-Front: Section 1-5（結構資料）

```
subagent_type: "general-purpose"
prompt: |
  你是 COBOL 規格書撰寫專家。只處理 Section 1-5（結構章節）。

  讀取以下檔案：
  1. skeleton JSON：{skeleton_path}
  2. {PATH A: DDS parser 結果 | PATH B: fetcher JSON}
  3. 副程式分析規則：/Users/ian/.claude/skills/cobol-spec/references/callsite-analyzer.md
  4. source code 的 CALL 語句（只搜尋含 "CALL " 的行，用 Grep tool）

  ⚠️ 禁止讀取完整 source code。只用 Grep 搜尋 CALL 語句。
  ⚠️ 禁止讀取 cobol-dictionary.json。

  寫入檔案 output/{program_id}/_01_front.md，內容：

  # {PROGRAM_ID} 程式規格書

  ## 1. 簡述
  {1-3 句商業語言描述}

  ## 2. 程式分類
  | 項目 | 說明 |
  |------|------|
  | 程式代號 | {ID} |
  | 程式名稱 | {NAME} |
  | 程式類型 | {TYPE} |
  | 分類依據 | {WHY} |

  ## 3. 參數說明
  ### CALL USING 參數
  {從 skeleton.linkage 提取}
  ### LDA
  {若有}

  ## 4. 使用檔案清單
  {從 skeleton.files + DDS/fetcher schema 提取}
  ### 檔案欄位定義
  {每個檔案的欄位表格}

  ## 5. 使用程式清單
  {從 skeleton.calls + callsite 分析}

  完成後回報檔案路徑和行數。
```

##### Agent-Logic-N: Section 6.3 邏輯翻譯（每批 300 行）

**每個批次獨立一個 Agent。** 大程式會有多個 Agent-Logic 並行。

```
subagent_type: "general-purpose"
prompt: |
  你是 COBOL 邏輯翻譯專家。只翻譯指定行範圍的段落。

  讀取以下檔案：
  1. 翻譯規則：/Users/ian/.claude/skills/cobol-spec/references/logic-translator.md
  2. source code：{source_file_path}（只讀行 {batch_start} 到 {batch_end}）

  ⚠️ 禁止讀取 cobol-dictionary.json（太大）。用以下內建術語：
  - PERFORM = 執行段落  - READ/CHAIN = 讀取  - WRITE = 寫入
  - REWRITE = 更新  - DELETE = 刪除  - SETLL/SETGT = 定位
  - File Status "00"=正常 "23"=找不到 "35"=檔案不存在
  - *INxx = 指示器  - MOVE = 設定值  - EVALUATE = 條件分支
  - STRING/UNSTRING = 字串處理  - COMPUTE = 計算

  ⚠️ 只讀指定行範圍，禁止讀完整 source。
  ⚠️ 輸出不超過 250 行。

  翻譯完成後寫入：output/{program_id}/_02_logic_{NN}.md
  （{NN} = 批次編號，01, 02, 03...）

  格式：每個段落一個 #### 標題，下方用編號列表描述邏輯。
  範例：
  #### MAIN-PROCESS（主處理）
  1. 開啟所有檔案
  2. 執行 INIT-ROUTINE 初始化
  3. PERFORM PROCESS-LOOP UNTIL END-FLAG = "Y"
  4. 關閉所有檔案，結束程式

  完成後回報：已翻譯 {N} 個段落，寫入 {檔案路徑}。
```

##### Agent-Meta: Section 6.1, 6.2, 6.4, 6.5, 6.6（非 6.3 的子章節）

```
subagent_type: "general-purpose"
prompt: |
  你是 COBOL 規格書撰寫專家。負責 Section 6 中除了 6.3 以外的子章節。

  讀取以下檔案：
  1. skeleton JSON：{skeleton_path}
  2. source code 的 ENVIRONMENT DIVISION + DATA DIVISION
     （用 Read tool 只讀行 1 到 {proc_start}，不讀 PROCEDURE DIVISION）
  {PATH B: 3. fetcher JSON 的 referenced_files}

  ⚠️ 禁止讀取 PROCEDURE DIVISION（那是 Agent-Logic 的工作）。
  ⚠️ 禁止讀取任何 references/*.md。

  產出兩個檔案：

  檔案 1: output/{program_id}/_03_sec6_top.md
  內容：
  ## 6. 處理內容

  ### 6.1 業務規則
  {從 skeleton 的 88-level 條件名、段落名推斷商業規則}
  {從 DATA DIVISION 的條件變數推斷}

  ### 6.2 檢核規則
  {從 skeleton 的段落名如 CHECK-xxx, VALID-xxx 推斷}
  {從 DATA DIVISION 的 PIC 格式推斷欄位驗證}

  檔案 2: output/{program_id}/_03_sec6_bottom.md
  內容：
  ### 6.4 檔案 I/O
  | 操作 | 檔案 | KEY | 條件 | File Status 處理 |
  |------|------|-----|------|-----------------|
  {從 skeleton.files 提取}

  ### 6.5 CALL 模組邏輯
  {從 skeleton.calls 提取呼叫時機}

  ### 6.6 例外處理
  {從 skeleton.file_status + error paragraphs 推斷}

  完成後回報兩個檔案路徑。
```

##### Agent-Chart: Section 7（圖表）

```
subagent_type: "general-purpose"
prompt: |
  你是 Mermaid 圖表專家。負責產生 ERD 和流程圖。

  讀取 skeleton JSON：{skeleton_path}
  {PATH B: 讀取 fetcher JSON 的 referenced_files[].relations}

  ⚠️ 禁止讀取 source code。只用 skeleton 結構。

  寫入 output/{program_id}/_04_chart.md：

  ## 7. 圖表

  ### 7.1 資料關聯圖（ERD）
  ```mermaid
  erDiagram
      {從 skeleton.files + relations 產生}
  ```

  ### 7.2 程式流程圖
  ```mermaid
  flowchart TD
      {從 skeleton.paragraphs 的呼叫關係產生}
  ```

  完成後回報檔案路徑。
```

##### Agent-Screen: 畫面解析（僅 INTERACTIVE 類型）

```
subagent_type: "general-purpose"
prompt: |
  你是 COBOL 畫面分析專家。

  讀取：
  1. /Users/ian/.claude/skills/cobol-spec/references/screen-analyzer.md
  2. source code 的畫面相關段落（用 Grep 搜尋 EXFMT/WRITE.*SUBFILE/READ 等關鍵字）
  3. DDS parser 結果或 DSPFFD 資料

  ⚠️ 禁止讀完整 source。只用 Grep 找畫面相關段落，再 Read 該段落。

  寫入 output/{program_id}/_02_screen.md：
  {畫面操作邏輯，會被插入 Section 6.3}

  完成後回報檔案路徑。
```

---

#### Step B5: bash cat 組裝（主對話）

**沒有 assemble_spec.py 腳本。組裝用 bash cat，不用 AI。**

```bash
cd output/{program_id}

# 組裝最終 spec
cat _01_front.md > {program_id}_spec.md

# Section 6 top（6.1 + 6.2）
cat _03_sec6_top.md >> {program_id}_spec.md

# Section 6.3 header
echo "" >> {program_id}_spec.md
echo "### 6.3 資料處理邏輯" >> {program_id}_spec.md
echo "" >> {program_id}_spec.md

# Section 6.3 content（所有邏輯翻譯批次，按順序）
cat _02_logic_01.md >> {program_id}_spec.md
cat _02_logic_02.md >> {program_id}_spec.md  # 如果有
cat _02_logic_03.md >> {program_id}_spec.md  # 如果有
# ... 對所有 _02_logic_*.md 檔案

# 畫面邏輯（如果有）
if [ -f _02_screen.md ]; then
  cat _02_screen.md >> {program_id}_spec.md
fi

# Section 6 bottom（6.4 + 6.5 + 6.6）
cat _03_sec6_bottom.md >> {program_id}_spec.md

# Section 7
cat _04_chart.md >> {program_id}_spec.md
```

或用一行：
```bash
cat _01_front.md _03_sec6_top.md > {program_id}_spec.md && \
echo -e "\n### 6.3 資料處理邏輯\n" >> {program_id}_spec.md && \
cat _02_logic_*.md >> {program_id}_spec.md && \
[ -f _02_screen.md ] && cat _02_screen.md >> {program_id}_spec.md; \
cat _03_sec6_bottom.md _04_chart.md >> {program_id}_spec.md
```

---

#### 完整流程圖

```
主對話（調度員，context < 200 行）
  │
  ├── 跑 Python 腳本 → skeleton.json（50 行）
  ├── 計算批次（300 行/批）
  │
  ├── 並行派出 Agent：
  │   ├── Agent-Front    → _01_front.md      （Section 1-5）
  │   ├── Agent-Logic-01 → _02_logic_01.md   （行 1-300 翻譯）
  │   ├── Agent-Logic-02 → _02_logic_02.md   （行 301-600 翻譯）
  │   ├── Agent-Logic-03 → _02_logic_03.md   （行 601-900 翻譯）
  │   ├── Agent-Meta     → _03_sec6_top.md   （6.1 + 6.2）
  │   │                  → _03_sec6_bottom.md（6.4 + 6.5 + 6.6）
  │   ├── Agent-Chart    → _04_chart.md      （Section 7）
  │   └── Agent-Screen   → _02_screen.md     （僅 INTERACTIVE）
  │
  ├── 等所有 Agent 完成
  │
  ├── bash cat 組裝 → {program_id}_spec.md
  │
  ├── spec_validator.py 驗證
  │
  └── md2html.py → HTML
```

#### 每個 Agent 的 context 預算

| Agent | 讀取量 | 輸出量 | 合計 | 安全？ |
|-------|--------|--------|------|--------|
| Agent-Front | skeleton(50) + DDS/fetcher(200) + callsite-analyzer(150) | ~200 | ~600 | ✅ |
| Agent-Logic-N | logic-translator(400) + source chunk(300) | ~250 | ~950 | ⚠️ 極限 |
| Agent-Meta | skeleton(50) + DATA DIV(200) | ~150 | ~400 | ✅ |
| Agent-Chart | skeleton(50) + relations(50) | ~50 | ~150 | ✅ |
| Agent-Screen | screen-analyzer(200) + 畫面段落(200) | ~150 | ~550 | ✅ |

**如果 Agent-Logic-N 仍 timeout**：把 batch_size 從 300 降到 200。

#### 中間檔案命名規則

```
output/{program_id}/
├── _01_front.md           # Agent-Front: Section 1-5
├── _02_logic_01.md        # Agent-Logic-1: 6.3 batch 1
├── _02_logic_02.md        # Agent-Logic-2: 6.3 batch 2
├── _02_logic_NN.md        # Agent-Logic-N: 6.3 batch N
├── _02_screen.md          # Agent-Screen: 畫面（optional）
├── _03_sec6_top.md        # Agent-Meta: 6.1 + 6.2
├── _03_sec6_bottom.md     # Agent-Meta: 6.4 + 6.5 + 6.6
├── _04_chart.md           # Agent-Chart: Section 7
├── {program_id}_spec.md   # 最終組裝結果
└── {program_id}_spec.html # HTML 版
```

### Step B6: 驗證（自動）

```bash
python3 /Users/ian/.claude/skills/cobol-spec/scripts/spec_validator.py \
  output/{program_id}/{program_id}_spec.md \
  output/{program_id}/{program}_skeleton.json
```

13 項驗證：paragraphs, files, calls, screen, linkage, remnants, io_modes, sql_section, cross_refs, markdown, summary, classification, erd。

若驗證有問題，自動修正後重新驗證。不打擾使用者。

### Step B7: 產出 HTML + 交付

```bash
python3 /Users/ian/.claude/skills/cobol-spec/scripts/md2html.py output/{program_id}/{program_id}_spec.md
```

把完整 spec 給使用者看。使用者反饋 → 修改 → 再給。直到 OK。

---

## 批次模式

適用於一次處理整個資料夾的 spool files。走 PATH A。

### B1. 批次掃描

```bash
python3 /Users/ian/.claude/skills/cobol-spec/scripts/batch_inventory.py <directory_or_files>
```

### B2. 逐支處理

對每個 .txt 檔執行 PATH A（Step A1-A8）。每支程式獨立產出一份 spec。

### B3. 批次摘要

所有程式處理完畢後，列出彙總表。

---

## 程式分類邏輯

| 特徵 | 分類 | 分類依據 |
|------|------|---------|
| 有 DSPF (Display File) | 畫面程式 | skeleton.type == INTERACTIVE |
| 有 PRTF (Print File) | 報表程式 | skeleton.files 中有 PRTF |
| 有 ENTRY + LINKAGE SECTION | 副程式 | skeleton.has_entry == true |
| 大量循序讀檔 + 無 DSPF | 批次程式 | 無互動特徵 + 大量 READ NEXT |
| 以上皆非 | 主程式 | 預設分類 |

## 檔案配置

```
~/.claude/skills/cobol-spec/
├── SKILL.md                          ← 本檔案（v4.0）
├── scripts/
│   ├── encoding.py                   # 編碼偵測（Big5/UTF-8）
│   ├── format_normalizer.py          # 格式偵測 + 前處理
│   ├── spool_splitter.py             # Spool → inventory.json
│   ├── cobol_skeleton.py             # COBOL → skeleton.json
│   ├── dds_parser.py                 # DDS → field list JSON
│   ├── spec_validator.py             # 驗證 spec 完整性（13 checks）
│   ├── md2html.py                    # Markdown → HTML
│   ├── batch_inventory.py            # 批次掃描多 .txt
│   ├── as400_connector.py            # AS/400 連線管理（v4.0 新增）
│   └── as400_fetcher.py              # AS/400 資料撈取（v4.0 新增）
├── references/
│   ├── logic-translator.md           # 邏輯翻譯 prompt（含 Section 6 分類指引）
│   ├── screen-analyzer.md            # 畫面解析 prompt
│   └── callsite-analyzer.md          # 副程式分析 prompt
└── assets/
    ├── cobol-dictionary.json         # 術語對照表（含分類、outfile 欄位）
    └── spec-template.md              # 7 章節產出格式模板
```

## 不同程式類型的差異

| 步驟 | 畫面程式 | 批次程式 | 副程式 | 報表程式 |
|------|:-------:|:------:|:-----:|:------:|
| format_normalizer | V | V | V | V |
| spool_splitter | V | V | V | V |
| cobol_skeleton | V | V | V | V |
| logic-translator | V | V | V | V |
| screen-analyzer | V | - | - | - |
| callsite-analyzer | V | V | 視情況 | V |
| dds_parser / DSPFFD | V | V | 視情況 | V |
| 參數介面 (S3) | V | 視情況 | V（重點）| 視情況 |
| ERD (S7.1) | V | V | 視情況 | V |
| CL 前處理 | V | V | - | V |

## 品質標準

- 每個步驟清楚描述「做什麼」而非「怎麼寫」
- 條件分支明確列出所有路徑
- 檔案操作包含 KEY 和 Status 處理
- 業務規則用商業語言描述
- 欄位名使用《中文名》(變數名) 格式
- Java 工程師看完能寫出同邏輯程式，不需要回頭看 COBOL
- PATH B 的資料來源標註為 `DSPOBJD` / `DSPFFD` / `DSPPGMREF` / `DSPDBR`
- PATH A 的推斷結果標註為 `callsite` / `WORKING-STORAGE 推斷`

## 錯誤處理

- **使用者未提供任何輸入**：請使用者指定 .txt 路徑或程式名
- **AS/400 連線失敗（PATH B）**：提示 `as400_connector.py --setup`；或建議改用本地 spool
- **DDS 檔案找不到（PATH A）**：先自動搜尋同資料夾 → 嘗試遠端 DSPFFD → 從 WS 推斷
- **CALL 目標無原始碼**：先自動搜尋 → 嘗試遠端 DSPOBJD → 從 callsite 推斷
- **巨大程式 (>10,000 行)**：自動增加批次數，每批 500-800 行
- **商業邏輯不明確**：唯一「必須」打擾使用者的情況

## 輸出

成功執行後，使用者會得到：
```
output/{program_id}/
├── {spool}_inventory.json       # Spool 元件清單（PATH A）
├── {program}_skeleton.json      # 程式骨架
├── {program}_fetcher.json       # AS/400 撈取資料（PATH B）
├── {program_id}_spec.md         # 規格書 (Markdown, 7 章節)
└── {program_id}_spec.html       # 規格書 (HTML，可直接開啟)
```
