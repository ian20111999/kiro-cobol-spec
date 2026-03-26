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

### Step B4 + B5: 分析 + 組裝（Agent subagent 架構）

**⚠️ 防 timeout 鐵律：禁止在主對話中累積大量 context。**

**原因**：COBOL source（1000+ 行）+ reference files（logic-translator 400 行、callsite-analyzer、screen-analyzer、dictionary 400 行）+ 翻譯結果 + spec 輸出，全部累積在同一對話會超出 API 限制。

**解法**：每個分析任務用 **Agent tool（subagent_type: "general-purpose"）** 獨立執行。Agent 在隔離的 context 中工作，只回傳精簡結果。主對話保持輕量。

---

#### 主對話只做三件事

1. **執行 Python 腳本**（skeleton、dds_parser 等 — 輸出小的 JSON）
2. **派出 Agent subagent** 做重分析
3. **收到 Agent 結果後，直接寫入 spec 檔案**

**主對話禁止做的事：**
- ❌ 讀取 `references/logic-translator.md`（400 行）
- ❌ 讀取 `references/callsite-analyzer.md`
- ❌ 讀取 `references/screen-analyzer.md`
- ❌ 讀取 `assets/cobol-dictionary.json`（400 行）
- ❌ 直接讀取完整 COBOL source code
- ❌ 在主對話中做邏輯翻譯

這些全部交給 Agent subagent。

---

#### Agent 1: 邏輯翻譯（最重 — 必須隔離）

用 Agent tool 啟動，prompt 包含：

```
subagent_type: "general-purpose"
prompt: |
  你是 COBOL 邏輯翻譯專家。請完成以下任務：

  1. 讀取翻譯規則：/Users/ian/.claude/skills/cobol-spec/references/logic-translator.md
  2. 讀取術語表：/Users/ian/.claude/skills/cobol-spec/assets/cobol-dictionary.json
  3. 讀取 COBOL source：{source_file_path}（行 {proc_start} 到 {proc_end}）
  4. 讀取 skeleton：{skeleton_path}

  翻譯 PROCEDURE DIVISION，按 logic-translator.md 的規則。
  如果超過 500 行，分批翻譯（每批 ~500 行）。

  翻譯完成後，將結果寫入以下檔案：
  output/{program_id}/{program_id}_logic.md

  檔案格式：
  ## 6.1 業務規則
  {從翻譯中提取}

  ## 6.2 檢核規則
  {從翻譯中提取}

  ## 6.3 資料處理邏輯
  {主要段落翻譯}

  ## 6.4 檔案 I/O
  {檔案操作摘要表}

  ## 6.5 CALL 模組邏輯
  {CALL 相關邏輯}

  ## 6.6 例外處理
  {錯誤處理}

  ## flowchart
  ```mermaid
  flowchart TD
      {程式流程圖}
  ```

  完成後回報：已寫入 {檔案路徑}，共 {行數} 行。
```

#### Agent 2: 副程式分析（有 CALL 時）

```
subagent_type: "general-purpose"
prompt: |
  你是 COBOL 副程式分析專家。請完成以下任務：

  1. 讀取分析規則：/Users/ian/.claude/skills/cobol-spec/references/callsite-analyzer.md
  2. 讀取 COBOL source：{source_file_path}
  3. 讀取 skeleton：{skeleton_path}
  {PATH B 時加上：4. 讀取 fetcher JSON：{fetcher_path}，取 referenced_programs}

  對每個 CALL 目標分析，產出表格寫入：
  output/{program_id}/{program_id}_calls.md

  格式：
  | # | 程式代號 | 功能說明 | 呼叫段落 | 傳入參數 | 取回結果 | 資訊來源 |
  |---|---------|---------|---------|---------|---------|---------|

  完成後回報：共 {N} 個 CALL 目標。
```

#### Agent 3: 畫面解析（僅 INTERACTIVE）

```
subagent_type: "general-purpose"
prompt: |
  你是 COBOL 畫面分析專家。請完成以下任務：

  1. 讀取分析規則：/Users/ian/.claude/skills/cobol-spec/references/screen-analyzer.md
  2. 讀取 COBOL source：{source_file_path}
  3. {DDS 解析結果或 DSPFFD 資料}

  分析畫面流程，產出畫面操作邏輯寫入：
  output/{program_id}/{program_id}_screen.md

  完成後回報：共 {N} 個畫面格式。
```

#### 不需要 Agent 的步驟（主對話直接做）

**4c. 檔案定義**：
- PATH B：從 fetcher JSON 的 `referenced_files[].schema` 直接提取（JSON 結構化資料，不大）
- PATH A：執行 `dds_parser.py`（腳本輸出 JSON）

**4e. 參數介面**：從 skeleton.linkage 直接提取（JSON 欄位，很小）

**4f. ERD**：
- PATH B：從 fetcher JSON 的 `referenced_files[].relations` 直接產生 Mermaid ERD
- PATH A：從 skeleton.files 推斷

---

#### Agent 執行策略

```
主對話
  │
  ├── 啟動 Agent 1（邏輯翻譯）──→ 寫入 _logic.md     ← 最重，先啟動
  ├── 啟動 Agent 2（副程式分析）──→ 寫入 _calls.md    ← 有 CALL 時
  ├── 啟動 Agent 3（畫面分析）──→ 寫入 _screen.md     ← 僅 INTERACTIVE
  │   （以上三個可並行）
  │
  ├── 同時主對話自行處理：
  │   ├── 4c 檔案定義（從 JSON 提取）
  │   ├── 4e 參數介面（從 skeleton 提取）
  │   └── 4f ERD（從 JSON/skeleton）
  │
  ├── 等 Agent 完成
  │
  └── Step B5: 組裝 spec（讀 Agent 產出的 .md 檔 + 自行處理的結果）
```

---

### Step B5: 組裝 7 章節規格書

**重要：沒有 assemble_spec.py 腳本。不要嘗試呼叫任何組裝腳本。**

**組裝方式：讀取 Agent 產出的中間檔案，分段寫入最終 spec。**

模板參考：`/Users/ian/.claude/skills/cobol-spec/assets/spec-template.md`

#### 分段寫入流程（必須嚴格遵守）

**第 1 步：Write 建立檔案**（Section 1-3，通常 < 50 行）

```
Write → output/{program_id}/{program_id}_spec.md
內容：# 標題 + Section 1 簡述 + Section 2 分類 + Section 3 參數
來源：skeleton JSON（主對話已有）
```

**第 2 步：Edit 追加 Section 4**（使用檔案清單）

```
Edit (append) → Section 4
來源：主對話的 4c 結果（dds_parser / fetcher JSON）
```

**第 3 步：Edit 追加 Section 5**（使用程式清單）

```
Edit (append) → Section 5
來源：讀取 output/{program_id}/{program_id}_calls.md（Agent 2 產出）
```

**第 4 步：Edit 追加 Section 6**（處理內容 — 最大區塊，可能需多次）

```
來源：讀取 output/{program_id}/{program_id}_logic.md（Agent 1 產出）

如果 _logic.md 超過 300 行，分次追加：
  Edit (append) → Section 6.1 + 6.2（業務規則 + 檢核）
  Edit (append) → Section 6.3 前半
  Edit (append) → Section 6.3 後半
  Edit (append) → Section 6.4 + 6.5 + 6.6
否則：
  Edit (append) → Section 6 全部
```

**第 5 步：Edit 追加 Section 7**（圖表）

```
Edit (append) → Section 7
來源：4f ERD（主對話已有）+ _logic.md 的 flowchart 區段（Agent 1 產出）
```

#### 中間檔案清單

| 檔案 | 來源 | 用於 |
|------|------|------|
| `{program_id}_skeleton.json` | cobol_skeleton.py | Section 1-4 |
| `{program_id}_logic.md` | Agent 1 | Section 6 + 7.2 |
| `{program_id}_calls.md` | Agent 2 | Section 5 |
| `{program_id}_screen.md` | Agent 3 | Section 6.3 |
| `{program_id}_fetcher.json` | as400_fetcher.py | Section 4 + 5 + 7.1 |

最終檔案：`output/{program_id}/{program_id}_spec.md`。

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
