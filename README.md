# COBOL Spec Skill for Kiro IDE

AS/400 COBOL/400 程式自動分析工具，一個指令產出完整的中文規格書。

從 [Claude Code](https://claude.ai/claude-code) 版 v2.0 移植到 [Kiro IDE](https://kiro.dev)，新增批次處理能力。

## 功能

- **Spool 拆解** — 解析 AS/400 COPY FILE / SEU SOURCE LISTING，辨識 DDS (PF/LF/JOIN LF/DSPF)、COBOL、CL 程式邊界
- **骨架解析** — 提取 COBOL 程式結構（Paragraphs、CALL、SQL、LINKAGE、檔案定義）
- **DDS 解析** — A-spec 欄位定義解析，支援 PF/LF/JOIN LF/DSPF
- **規格書驗證** — 10 項交叉檢查（段落覆蓋率、檔案對應、CALL 完整性等）
- **批次處理** — 整個資料夾一次掃描，產出多支程式的規格書
- **HTML 輸出** — Markdown 轉 styled HTML，支援 CJK 字型

## 安裝

將檔案放到 Kiro 對應目錄：

```bash
# Skill 本體
cp -R SKILL.md scripts/ references/ assets/ ~/.kiro/skills/cobol-spec/

# Steering（自動載入 COBOL/400 通用知識）
cp steering/cobol-conventions.md ~/.kiro/steering/

# Custom Agents（專職邏輯翻譯 + 畫面分析）
cp agents/*.md ~/.kiro/agents/
```

## 使用

```
/cobol-spec your_spool.txt                  # 單檔模式
/cobol-spec --batch /path/to/folder         # 批次模式
```

互動式流程會在關鍵步驟暫停確認（選擇目標程式、補充 DDS 檔案、確認副程式來源）。

## 腳本一覽

| 腳本 | 功能 | 用法 |
|------|------|------|
| `spool_splitter.py` | Spool → inventory JSON | `python3 scripts/spool_splitter.py <spool>` |
| `cobol_skeleton.py` | COBOL → skeleton JSON | `python3 scripts/cobol_skeleton.py <spool> [--program NAME]` |
| `dds_parser.py` | DDS → field list JSON | `python3 scripts/dds_parser.py <file> [--dspf]` |
| `spec_validator.py` | 驗證 spec 完整性 | `python3 scripts/spec_validator.py <spec.md> <skeleton.json>` |
| `md2html.py` | Markdown → HTML | `python3 scripts/md2html.py <input.md> [output.html]` |
| `batch_inventory.py` | 批次掃描多 .txt | `python3 scripts/batch_inventory.py <dir_or_files>` |

所有腳本均支援 `--help`。

## 目錄結構

```
├── SKILL.md                    # 主流程（含批次模式）
├── scripts/                    # 6 個 Python 腳本
├── references/                 # AI 分析用 prompt
│   ├── logic-translator.md     #   邏輯翻譯規則
│   ├── callsite-analyzer.md    #   副程式分析規則
│   └── screen-analyzer.md      #   畫面分析規則
├── assets/
│   ├── cobol-dictionary.json   # 200+ 術語對照（File Status / API / Edit Code / Indicator）
│   └── spec-template.md        # 規格書模板
├── steering/
│   └── cobol-conventions.md    # COBOL/400 通用知識（auto inclusion）
└── agents/
    ├── cobol-translator.md     # 專職邏輯翻譯 agent
    └── cobol-screen-analyst.md # 專職畫面分析 agent
```

## 支援的程式類型

| 類型 | 邏輯翻譯 | 畫面分析 | 副程式分析 | DDS 解析 | 參數介面 |
|------|:--------:|:--------:|:----------:|:--------:|:--------:|
| INTERACTIVE | V | V | V | V | V |
| BATCH | V | - | V | V | 視情況 |
| SUBPROGRAM | V | - | 視情況 | 視情況 | V |
| REPORT | V | - | V | V | 視情況 |

## 相容性

- **Kiro IDE** — 完整支援（steering + custom agents）
- **Claude Code** — 相容（忽略 steering/agents 目錄即可）

## License

MIT
