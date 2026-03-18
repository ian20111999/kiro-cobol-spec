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
  version: "2.0.0"
---

# COBOL Spec Generator

一個指令產出完整的中文規格書。支援單檔或批次模式。

## 使用方式

```
/cobol-spec <spool_file> [program_name]      # 單檔模式
/cobol-spec --batch <directory_or_files>      # 批次模式
```

**範例：**
```
/cobol-spec <spool>.txt <program>
/cobol-spec <spool>.txt               ← 自動選擇最大的 COBOL 程式
/cobol-spec --batch /path/to/folder    ← 整資料夾批次處理
/cobol-spec --batch a.txt b.txt c.txt  ← 多檔批次處理
```

## 可用腳本

| 腳本 | 功能 | CLI 用法 |
|------|------|----------|
| `scripts/spool_splitter.py` | Spool → inventory JSON | `python3 scripts/spool_splitter.py <spool_file>` |
| `scripts/cobol_skeleton.py` | COBOL → skeleton JSON | `python3 scripts/cobol_skeleton.py <spool_file> [--program NAME]` |
| `scripts/dds_parser.py` | DDS → field list JSON | `python3 scripts/dds_parser.py <file> [--dspf] [--spool --start N --end M]` |
| `scripts/spec_validator.py` | 驗證 spec 完整性 | `python3 scripts/spec_validator.py <spec.md> <skeleton.json>` |
| `scripts/md2html.py` | Markdown → HTML | `python3 scripts/md2html.py <input.md> [output.html]` |
| `scripts/batch_inventory.py` | 批次掃描多 .txt | `python3 scripts/batch_inventory.py <dir_or_files...>` |

所有腳本均支援 `--help`。

## 互動規則（重要）

本 skill 採互動式流程，在以下時機**必須暫停並詢問使用者**：

### 啟動時：確認輸入檔案

若使用者未提供 spool file 路徑，請使用者指定：
- 請提供 spool file（AS/400 COPY FILE 或 SEU SOURCE LISTING 格式的 .txt 檔）
- 說明檔案應放在工作目錄下

### Step 1 後：確認目標程式

執行 spool_splitter 後，向使用者列出找到的所有 COBOL 程式，請使用者確認要分析哪一支：
- 列出每支程式的名稱和行數
- 若使用者已指定 program_name 且存在，可直接繼續
- 若只有一支 COBOL 程式，告知使用者並直接繼續

### Step 2 後：確認骨架摘要 + 補充 DDS 檔案

向使用者報告骨架摘要後，檢查所有需要的 DDS 原始檔是否存在：

1. 對 skeleton.files 裡的每個檔案，檢查對應的 .txt 是否在工作目錄下
2. 對 INTERACTIVE 類型，額外檢查 Display File 的 .txt 是否存在
3. 將結果分成「已找到」和「缺少」兩組

若有缺少的檔案，請使用者補充：
- 列出缺少的檔案名稱清單
- 說明：「請將以下 DDS 原始碼 .txt 檔放到工作目錄下，放好後告訴我」
- 等使用者回覆後，重新檢查
- 若使用者明確表示無法提供某些檔案，標註「來源不可用」並從 WORKING-STORAGE 推斷

**不要在檔案不存在時靜默跳過或自行推斷，一定要先問使用者。**

### Step 3 中：副程式原始碼

分析 CALL 目標時，若副程式不在 spool file 中也不在工作目錄下：
- 告知使用者哪些副程式缺少原始碼
- 詢問是否能提供（獨立 spool 或 .txt）
- 若無法提供，基於呼叫點上下文推斷功能，標註「資訊來源: callsite」

## 工作流程（單檔模式）

### Step 1: Spool 拆解（自動化）

執行 `spool_splitter.py` 產出元件清單：

```bash
python3 scripts/spool_splitter.py <spool_file>
```

**產出**：JSON inventory（DDS/COBOL/CL 區塊 + 行號範圍）

**驗證**：確認目標程式存在於 inventory 中。若使用者未指定 program_name，列出所有 COBOL 程式請使用者選擇。

將 inventory 存為 `output/{program_id}/{spool}_inventory.json`。

### Step 2: 骨架解析（自動化）

執行 `cobol_skeleton.py` 產出程式結構：

```bash
python3 scripts/cobol_skeleton.py <spool_file> --program <program_name>
```

**產出**：JSON skeleton（files, paragraphs, calls, linkage, type）

**驗證**：
- 確認 type 判斷合理（INTERACTIVE/BATCH/SUBPROGRAM/REPORT）
- 確認 paragraph 數量合理
- 確認 CALL 目標清單

將 skeleton 存為 `output/{program_id}/{program}_skeleton.json`。

向使用者報告摘要：
> {program_name} 是 {type} 類型，{N} 個 paragraphs，{M} 個 CALL，{K} 個檔案。

### Step 3: 平行分析（AI + 自動化混合）

根據程式類型，分派以下工作。盡量平行執行。

#### 3a. 邏輯翻譯（AI）— 所有類型

讀取 `references/logic-translator.md` 取得翻譯 prompt。

將 PROCEDURE DIVISION 按功能群組分批（每批 ~1,000 行）：
- 使用 skeleton.paragraphs 的 group 分組
- 每批帶前一批的摘要

**每批處理流程**：
1. 從 spool file 讀取該批次的原始碼行
2. 填入 logic-translator.md 的模板
3. 產出中文邏輯說明

#### 3b. 副程式分析（AI）— 有 CALL 時

讀取 `references/callsite-analyzer.md` 取得分析 prompt。

對每個 CALL 目標：
1. 讀取呼叫點上下文（前後 10 行）
2. 若有副程式原始碼（在 spool 或獨立 .txt），淺讀
3. 產出副程式功能表格

#### 3c. Table 定義（自動化 + AI）— 有檔案操作時

**前提**：Step 2 後已確認所有 DDS 檔案存在（缺少的已請使用者補充）。

對每個 skeleton.files：
1. 優先用 `dds_parser.py` 解析工作目錄下的獨立 .txt 檔
2. 若無獨立 .txt，嘗試從 spool file 的 DDS 區段解析（用 inventory 的行號範圍）
3. 若使用者已確認無法提供：從 COBOL WORKING-STORAGE 推斷，標註「來源: WORKING-STORAGE 推斷」
4. 產出欄位定義表格

```bash
python3 scripts/dds_parser.py <dds_file.txt>
```

#### 3d. 畫面解析（AI）— 僅 INTERACTIVE

讀取 `references/screen-analyzer.md` 取得解析 prompt。

1. 用 `dds_parser.py --dspf` 解析 Display File
2. 結合 COBOL 程式中的畫面處理段落
3. 產出：欄位表格、FK 表格、Indicator 表格、ASCII 排版

#### 3e. 參數介面（自動化）— 所有類型

從 skeleton.linkage 直接提取，加上 LDA 分析（若有）。

### Step 4: 組裝規格書

讀取 `assets/spec-template.md` 取得格式模板。

組裝順序：
1. 標題 + 基本資訊
2. 一. 程式邏輯（3a 的產出）
3. 二. 副程式表格（3b 的產出）
4. 三. Table 定義（3c 的產出）
5. 四. 畫面規格（3d 的產出，僅 INTERACTIVE）
6. 五. 參數介面（3e 的產出）

存為 `output/{program_id}/{program_id}_spec.md`。

產生 HTML：
```bash
python3 scripts/md2html.py output/{program_id}/{program_id}_spec.md
```

### Step 5: 驗證

執行 `spec_validator.py`：

```bash
python3 scripts/spec_validator.py \
  output/{program_id}/{program_id}_spec.md \
  output/{program_id}/{program}_skeleton.json
```

**交叉驗證**：
- [ ] 每個 paragraph 都在「一. 程式邏輯」中
- [ ] 每個 file 都在「三. Table 定義」中
- [ ] 每個 CALL 都在「二. 副程式表格」中
- [ ] 畫面欄位完整（如適用）
- [ ] LINKAGE 在「五. 參數介面」中
- [ ] 無「待確認」殘留

向使用者報告驗證結果。

## 批次模式

適用於一次處理整個資料夾的 spool files，產出多支程式的規格書。

### B1. 批次掃描

```bash
python3 scripts/batch_inventory.py <directory_or_files>
```

產出 JSON 清單，包含所有 spool 中的 COBOL 程式名稱、行數、類型提示。

### B2. 使用者選擇

顯示程式清單表格（名稱 / 行數 / 來源檔 / 類型提示），請使用者選擇：
- 全部處理
- 選擇特定程式（以編號或名稱指定）

### B3. 逐支處理

對每支選中的程式執行標準 Step 1-5。

**DDS 來源優先順序**：
1. 從同一 spool file 中的 DDS 區段
2. 從同資料夾其他 .txt 中尋找
3. 請使用者補充

### B4. 批次摘要

所有程式處理完畢後，列出彙總表：

| 程式名稱 | 類型 | 驗證結果 | Issues |
|----------|------|----------|--------|
| PROGAAA  | INTERACTIVE | PASS | 0 |
| PROGBBB  | BATCH | PASS | 0 |

## 檔案配置

```
~/.kiro/skills/cobol-spec/
├── SKILL.md                          ← 本檔案
├── scripts/
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
| spool_splitter | V | V | V | V |
| cobol_skeleton | V | V | V | V |
| logic-translator | V | V | V | V |
| screen-analyzer | V | - | - | - |
| callsite-analyzer | V | V | 視情況 | V |
| dds_parser | V | V | 視情況 | V |
| 參數介面 | V | 視情況 | V（重點） | 視情況 |

## 品質標準

- 每個步驟清楚描述「做什麼」而非「怎麼寫」
- 條件分支明確列出所有路徑
- 檔案操作包含 KEY 和 Status 處理
- 業務規則用商業語言描述
- 欄位名使用《中文名》(變數名) 格式

## 錯誤處理

- **使用者未提供 spool file**：請使用者指定檔案路徑
- **spool_splitter 找不到程式**：列出所有找到的程式，請使用者選擇
- **DDS 檔案不存在**：請使用者補充 .txt 檔；若使用者確認無法提供，才從 WORKING-STORAGE 推斷，標註來源
- **Display File 不存在**：請使用者補充 DSPF .txt 檔；無法提供則跳過畫面規格章節
- **CALL 目標無法分析**：告知使用者缺少哪些副程式原始碼，詢問是否能補充；無法提供則標註「功能待確認」，不猜測
- **巨大程式 (>10,000 行)**：自動增加批次數，每批 500-800 行
- **任何步驟失敗**：向使用者說明錯誤原因，詢問如何處理，不要靜默跳過

## 輸出範例

成功執行後，使用者會得到：
```
output/{spool_id}/
├── {spool_id}_inventory.json   # Spool 元件清單
├── {program}_skeleton.json     # 程式骨架
├── {spool_id}_spec.md          # 規格書 (Markdown)
└── {spool_id}_spec.html        # 規格書 (HTML，可直接開啟)
```
