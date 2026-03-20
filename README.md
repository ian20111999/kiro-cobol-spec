# COBOL Spec Skill v3.0

AS/400 COBOL/400 程式自動分析工具，一個指令產出完整的中文規格書。

支援 [Claude Code](https://claude.ai/claude-code)、[Kiro IDE](https://kiro.dev) 和 [GitHub Copilot](https://github.com/features/copilot)。

## 功能

- **編碼偵測** — 自動識別 Big5 / UTF-8，避免亂碼
- **格式正規化** — 偵測 SEU / COPY FILE / DSPFFD / MSGFILE 格式，清理標註殘留，拆分多 member 檔案
- **Spool 拆解** — 解析 AS/400 spool，辨識 DDS (PF/LF/JOIN LF/DSPF)、COBOL、CL 程式邊界
- **骨架解析** — 提取 COBOL 程式結構（Paragraphs、CALL、SQL、LINKAGE、88-level、REDEFINES、COMMIT/ROLLBACK）
- **DDS 解析** — A-spec 欄位定義，支援 PF/LF/JOIN LF/DSPF、DATFMT/TIMFMT/DFT/CONCAT/SST
- **規格書驗證** — 10 項交叉檢查（段落覆蓋率、檔案對應、CALL 完整性等）
- **Mermaid 流程圖** — 自動產出程式主要段落的執行流程圖
- **批次處理** — 整個資料夾一次掃描，產出多支程式的規格書
- **HTML 輸出** — Markdown 轉 styled HTML，支援 CJK 字型

## 安裝

```bash
git clone https://github.com/yourusername/kiro-cobol-spec.git
cd kiro-cobol-spec
./install.sh
```

`install.sh` 會自動：
- 偵測已安裝的平台（Claude Code / Kiro IDE / GitHub Copilot）
- 複製核心檔案到對應的 skills 目錄
- 將 `SKILL.md` 中的腳本路徑轉換為絕對路徑
- （Kiro）額外安裝 agents 和 steering

## 使用

```
/cobol-spec your_spool.txt                    # 單檔模式
/cobol-spec --batch /path/to/folder           # 批次模式
/cobol-spec --batch a.txt b.txt c.txt         # 多檔批次處理
```

互動式流程會在商業邏輯不明確時暫停確認，其餘全自動。

## 腳本一覽

| 腳本 | 功能 | 用法 |
|------|------|------|
| `encoding.py` | 偵測 Big5/UTF-8 編碼 | `python3 scripts/encoding.py <file>` |
| `format_normalizer.py` | 格式偵測 + 標註清理 + member 拆分 | `python3 scripts/format_normalizer.py <file_or_dir>` |
| `spool_splitter.py` | Spool → inventory JSON | `python3 scripts/spool_splitter.py <spool>` |
| `cobol_skeleton.py` | COBOL → skeleton JSON | `python3 scripts/cobol_skeleton.py <spool> [--program NAME]` |
| `dds_parser.py` | DDS → field list JSON | `python3 scripts/dds_parser.py <file> [--dspf]` |
| `spec_validator.py` | 驗證 spec 完整性 | `python3 scripts/spec_validator.py <spec.md> <skeleton.json>` |
| `md2html.py` | Markdown → HTML | `python3 scripts/md2html.py <input.md> [output.html]` |
| `batch_inventory.py` | 批次掃描多 .txt | `python3 scripts/batch_inventory.py <dir_or_files>` |

所有腳本均支援 `--help`。

## 目錄結構

```
├── install.sh                     # 一鍵安裝腳本
├── SKILL.md                       # 主流程（含批次模式）
├── scripts/                       # 8 個 Python 腳本
│   ├── encoding.py                #   編碼偵測
│   ├── format_normalizer.py       #   格式正規化 + 前處理
│   ├── spool_splitter.py          #   Spool 拆解
│   ├── cobol_skeleton.py          #   骨架解析
│   ├── dds_parser.py              #   DDS 解析
│   ├── spec_validator.py          #   規格書驗證
│   ├── md2html.py                 #   Markdown → HTML
│   └── batch_inventory.py         #   批次掃描
├── references/                    # AI 分析用 prompt
│   ├── logic-translator.md        #   邏輯翻譯規則
│   ├── callsite-analyzer.md       #   副程式分析規則
│   └── screen-analyzer.md         #   畫面分析規則
├── assets/
│   ├── cobol-dictionary.json      #   200+ 術語對照（File Status / API / Edit Code / Indicator）
│   └── spec-template.md           #   規格書模板
├── agents/                        #   ⚠️ Kiro 專用
│   ├── cobol-translator.md        #   專職邏輯翻譯 agent
│   └── cobol-screen-analyst.md    #   專職畫面分析 agent
└── steering/                      #   ⚠️ Kiro 專用
    └── cobol-conventions.md       #   COBOL/400 通用知識（auto inclusion）
```

> `agents/` 和 `steering/` 僅 Kiro IDE 使用。Claude Code 安裝時會自動忽略。

## 支援的程式類型

| 類型 | 邏輯翻譯 | 畫面分析 | 副程式分析 | DDS 解析 | 參數介面 |
|------|:--------:|:--------:|:----------:|:--------:|:--------:|
| INTERACTIVE | V | V | V | V | V |
| BATCH | V | - | V | V | 視情況 |
| SUBPROGRAM | V | - | 視情況 | 視情況 | V |
| REPORT | V | - | V | V | 視情況 |

## 支援平台

| 平台 | 核心功能 | Agents | Steering | 安裝路徑 |
|------|:--------:|:------:|:--------:|----------|
| Claude Code | V | - | - | `~/.claude/skills/cobol-spec/` |
| Kiro IDE | V | V | V | `~/.kiro/skills/cobol-spec/` |
| GitHub Copilot | V | - | - | `~/.github/copilot-skills/cobol-spec/` |

## License

MIT
