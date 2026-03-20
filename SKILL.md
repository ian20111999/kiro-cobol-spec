---
name: cobol-spec
description: >
  解析 AS/400 COBOL 程式並產出標準化中文規格書。
  支援單檔分析或整資料夾批次處理多支程式。
  涵蓋線上互動、批次、副程式、報表等所有程式類型。
  觸發：使用者提到 /cobol-spec、分析 COBOL、產生規格書、翻譯 COBOL、
  或提供 .txt spool file / 資料夾進行分析。
license: MIT
compatibility: Kiro, Claude Code
metadata:
  category: cobol-analysis
  complexity: advanced
  author: ian
  version: "3.0.0"
---

# COBOL Spec Generator

一個指令產出完整的中文規格書。支援單檔或批次模式。

## 目標讀者

規格書的讀者是 **Java 工程師**。他們不懂 COBOL，但要根據這份規格書寫出邏輯完全相同的 Java 程式。因此：

- 所有 COBOL 特有概念必須翻譯成通用程式概念
- 每段邏輯要清楚到「照著寫就對了」的程度
- 檔案操作、畫面流程、錯誤處理都要完整，不能有模糊地帶
- 副程式的呼叫時機、傳入參數、回傳值要寫清楚

## 使用方式

```
/cobol-spec your_spool.txt                    # 單檔模式
/cobol-spec --batch /path/to/folder           # 批次模式
/cobol-spec --batch a.txt b.txt c.txt         # 多檔批次處理
```

## 互動原則

**一個檔案 = 一份完整的 spec。使用者說了檔名就直接跑，不問廢話。**

### 何時不打擾使用者
- 檔案內只有一支 COBOL → 直接分析
- 檔案內有多支 COBOL → 全部都分析，全寫進同一份 spec
- DDS 在 spool 裡面 → 直接從 spool 裡解析
- DDS 有獨立 .txt 在同資料夾 → 自動找到並使用
- 副程式在 spool 裡或同資料夾 → 自動分析
- CL 程式 → 寫進 spec 的前處理章節

### 何時才打擾使用者
- **未提供檔名**：請使用者指定 .txt 路徑
- **某段 COBOL 邏輯的商業意圖不明確**：描述看到的程式碼，問使用者這段在做什麼
- **DDS 不在 spool 也不在同資料夾**：告知缺少哪些，問使用者是否能補充；若不能，從 WORKING-STORAGE 推斷並標註
- **副程式原始碼完全找不到**：列出缺少的副程式，問使用者；若不能提供，從 callsite 上下文推斷並標註

### 打擾格式
```
⚠️ 需要確認
📌 [具體問題]
💡 我目前的理解：[你的推斷]
```

## 可用腳本

| 腳本 | 功能 | CLI 用法 |
|------|------|----------|
| `scripts/encoding.py` | 偵測 Big5/UTF-8 編碼 | `python3 scripts/encoding.py <file>` |
| `scripts/format_normalizer.py` | 格式偵測 + 標註清理 + member 拆分 | `python3 scripts/format_normalizer.py <file_or_dir>` |
| `scripts/spool_splitter.py` | Spool → inventory JSON | `python3 scripts/spool_splitter.py <spool_file>` |
| `scripts/cobol_skeleton.py` | COBOL → skeleton JSON | `python3 scripts/cobol_skeleton.py <spool_file> [--program NAME]` |
| `scripts/dds_parser.py` | DDS → field list JSON | `python3 scripts/dds_parser.py <file> [--dspf] [--spool --start N --end M]` |
| `scripts/spec_validator.py` | 驗證 spec 完整性 | `python3 scripts/spec_validator.py <spec.md> <skeleton.json>` |
| `scripts/md2html.py` | Markdown → HTML | `python3 scripts/md2html.py <input.md> [output.html]` |
| `scripts/batch_inventory.py` | 批次掃描多 .txt | `python3 scripts/batch_inventory.py <dir_or_files...>` |

所有腳本均支援 `--help`。

## 工作流程（單檔模式）

使用者說了檔名 → 以下全自動，直到 spec 產出。

### Step 1: 前處理（自動）

先跑 `format_normalizer.py` 偵測格式和編碼：

```bash
python3 scripts/format_normalizer.py <spool_file> --json
```

- 偵測編碼（Big5 / UTF-8）
- 偵測格式（SEU / COPY_FILE / DSPFFD / MSGFILE）
- 清理 SEU 標註殘留
- 拆分多 member 檔案

### Step 2: Spool 拆解（自動）

執行 `spool_splitter.py` 產出元件清單：

```bash
python3 scripts/spool_splitter.py <spool_file>
```

**產出**：JSON inventory（DDS/COBOL/CL 區塊 + 行號範圍）

將 inventory 存為 `output/{program_id}/{spool}_inventory.json`。

### Step 3: 骨架解析（自動）

執行 `cobol_skeleton.py` 產出程式結構：

```bash
python3 scripts/cobol_skeleton.py <spool_file> --program <program_name>
```

**產出**：JSON skeleton（files, paragraphs, calls, linkage, type）

將 skeleton 存為 `output/{program_id}/{program}_skeleton.json`。

### Step 4: 平行分析（自動）

根據程式類型，分派以下工作。盡量平行執行。

#### 4a. 邏輯翻譯 + 流程圖（AI）— 所有類型

讀取 `references/logic-translator.md` 取得翻譯 prompt。

將 PROCEDURE DIVISION 按功能群組分批（每批 ~1,000 行）：
- 使用 skeleton.paragraphs 的 group 分組
- 每批帶前一批的摘要

翻譯完成後，產出 **Mermaid 流程圖**（`flowchart TD`），呈現程式主要段落的執行流程、條件分支、迴圈結構。

#### 4b. 副程式分析（AI）— 有 CALL 時

讀取 `references/callsite-analyzer.md` 取得分析 prompt。

對每個 CALL 目標：
1. 讀取呼叫點上下文（前後 10 行）
2. 若有副程式原始碼（在 spool 或同資料夾 .txt），淺讀
3. 產出：呼叫時機、傳入參數、回傳值、功能說明
4. 若無原始碼，從 callsite 上下文推斷，標註「資訊來源: callsite」

#### 4c. Table 定義（自動 + AI）— 有檔案操作時

對每個 skeleton.files：
1. 優先用 `dds_parser.py` 解析同資料夾的獨立 .txt 檔
2. 若無獨立 .txt，嘗試從 spool file 的 DDS 區段解析（用 inventory 的行號範圍）
3. 若都找不到：從 COBOL WORKING-STORAGE 推斷，標註「來源: WORKING-STORAGE 推斷」
4. 產出欄位定義表格（含中文 COLHDG）

```bash
python3 scripts/dds_parser.py <dds_file.txt>
```

#### 4d. 畫面解析（AI）— 僅 INTERACTIVE

讀取 `references/screen-analyzer.md` 取得解析 prompt。

1. 用 `dds_parser.py --dspf` 解析 Display File
2. 結合 COBOL 程式中的畫面處理段落
3. 產出：欄位表格、FK 表格、Indicator 表格、ASCII 排版

#### 4e. 參數介面（自動）— 所有類型

從 skeleton.linkage 直接提取，加上 LDA 分析（若有）。

#### 4f. CL 前處理（AI）— 有 CL 時

分析 CL 程式的邏輯：
- 環境設定（ADDLIBLE、CHGJOB）
- 檔案覆蓋（OVRDBF）
- 呼叫順序（CALL PGM、SBMJOB）
- 寫入 spec 的「前處理」章節

### Step 5: 組裝規格書（自動）

讀取 `assets/spec-template.md` 取得格式模板。

組裝順序：
1. 標題 + 基本資訊（程式名、類型、用途）
2. 一. 程式流程圖（4a 的 Mermaid 流程圖）
3. 二. 程式邏輯（4a 的段落翻譯）
4. 三. 副程式表格（4b 的產出）
5. 四. Table 定義（4c 的產出）
6. 五. 畫面規格（4d 的產出，僅 INTERACTIVE）
7. 六. 參數介面（4e 的產出）
8. 七. CL 前處理（4f 的產出，若有）

存為 `output/{program_id}/{program_id}_spec.md`。

產生 HTML：
```bash
python3 scripts/md2html.py output/{program_id}/{program_id}_spec.md
```

### Step 6: 驗證（自動）

執行 `spec_validator.py`：

```bash
python3 scripts/spec_validator.py \
  output/{program_id}/{program_id}_spec.md \
  output/{program_id}/{program}_skeleton.json
```

若驗證有問題，自動修正後重新驗證。不打擾使用者。

### Step 7: 交付

把完整 spec 給使用者看。使用者反饋 → 修改 → 再給。直到 OK。

## 批次模式

適用於一次處理整個資料夾的 spool files。

### B1. 批次掃描

```bash
python3 scripts/batch_inventory.py <directory_or_files>
```

### B2. 逐支處理

對每個 .txt 檔執行標準 Step 1-7。每支程式獨立產出一份 spec。

### B3. 批次摘要

所有程式處理完畢後，列出彙總表。

## 檔案配置

```
~/.kiro/skills/cobol-spec/
├── SKILL.md                          ← 本檔案
├── scripts/
│   ├── encoding.py                   # 編碼偵測（Big5/UTF-8）
│   ├── format_normalizer.py          # 格式偵測 + 前處理
│   ├── spool_splitter.py             # Spool → inventory.json
│   ├── cobol_skeleton.py             # COBOL → skeleton.json
│   ├── dds_parser.py                 # DDS → field list JSON
│   ├── spec_validator.py             # 驗證 spec 完整性
│   ├── md2html.py                    # Markdown → HTML
│   └── batch_inventory.py            # 批次掃描多 .txt
├── references/
│   ├── logic-translator.md           # 邏輯翻譯 prompt
│   ├── screen-analyzer.md            # 畫面解析 prompt
│   └── callsite-analyzer.md          # 副程式分析 prompt
└── assets/
    ├── cobol-dictionary.json         # 術語對照表
    └── spec-template.md              # 產出格式模板
```

## 不同程式類型的差異

| 步驟 | INTERACTIVE | BATCH | SUBPROGRAM | REPORT |
|------|:-----------:|:-----:|:----------:|:------:|
| format_normalizer | V | V | V | V |
| spool_splitter | V | V | V | V |
| cobol_skeleton | V | V | V | V |
| logic-translator | V | V | V | V |
| screen-analyzer | V | - | - | - |
| callsite-analyzer | V | V | 視情況 | V |
| dds_parser | V | V | 視情況 | V |
| 參數介面 | V | 視情況 | V（重點） | 視情況 |
| CL 前處理 | V | V | - | V |

## 品質標準

- 每個步驟清楚描述「做什麼」而非「怎麼寫」
- 條件分支明確列出所有路徑
- 檔案操作包含 KEY 和 Status 處理
- 業務規則用商業語言描述
- 欄位名使用《中文名》(變數名) 格式
- Java 工程師看完能寫出同邏輯程式，不需要回頭看 COBOL

## 錯誤處理

- **使用者未提供 spool file**：請使用者指定檔案路徑
- **DDS 檔案找不到**：先自動搜尋同資料夾，找不到才問使用者；實在沒有就從 WORKING-STORAGE 推斷並標註
- **CALL 目標無原始碼**：先自動搜尋，找不到才問使用者；實在沒有就從 callsite 推斷並標註
- **巨大程式 (>10,000 行)**：自動增加批次數，每批 500-800 行
- **商業邏輯不明確**：這是唯一「必須」打擾使用者的情況

## 輸出

成功執行後，使用者會得到：
```
output/{program_id}/
├── {spool}_inventory.json     # Spool 元件清單
├── {program}_skeleton.json    # 程式骨架
├── {program_id}_spec.md       # 規格書 (Markdown)
└── {program_id}_spec.html     # 規格書 (HTML，可直接開啟)
```
