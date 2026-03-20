#!/bin/bash
set -euo pipefail

# COBOL Spec Skill — 一鍵安裝
# 自動偵測 Claude Code / Kiro / GitHub Copilot 並安裝到正確目錄

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_NAME="cobol-spec"

CLAUDE_SKILLS="$HOME/.claude/skills/$SKILL_NAME"
KIRO_SKILLS="$HOME/.kiro/skills/$SKILL_NAME"
KIRO_AGENTS="$HOME/.kiro/agents"
KIRO_STEERING="$HOME/.kiro/steering"
COPILOT_SKILLS="$HOME/.github/copilot-skills/$SKILL_NAME"

# 核心檔案（兩個平台共用）
CORE_DIRS=(scripts references assets)
CORE_FILES=(SKILL.md)

installed=0

install_core() {
    local target="$1"
    echo "  安裝到 $target ..."

    mkdir -p "$target"

    # 複製核心目錄
    for dir in "${CORE_DIRS[@]}"; do
        rm -rf "$target/$dir"
        cp -R "$SCRIPT_DIR/$dir" "$target/$dir"
    done

    # 移除 __pycache__
    find "$target" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

    # 複製核心檔案
    for file in "${CORE_FILES[@]}"; do
        cp "$SCRIPT_DIR/$file" "$target/$file"
    done

    # 將 SKILL.md 中的 __SKILL_DIR__ 替換為實際安裝路徑
    sed -i '' "s|__SKILL_DIR__|$target|g" "$target/SKILL.md"

    echo "  ✓ 核心檔案已安裝"
}

echo "═══════════════════════════════════════"
echo "  COBOL Spec Skill 安裝程式 v3.0"
echo "═══════════════════════════════════════"
echo ""

# Claude Code
if [ -d "$HOME/.claude" ]; then
    echo "▸ 偵測到 Claude Code"
    install_core "$CLAUDE_SKILLS"
    installed=$((installed + 1))
    echo ""
fi

# Kiro IDE
if [ -d "$HOME/.kiro" ]; then
    echo "▸ 偵測到 Kiro IDE"
    install_core "$KIRO_SKILLS"

    # Kiro 專用：agents + steering
    mkdir -p "$KIRO_AGENTS" "$KIRO_STEERING"
    cp "$SCRIPT_DIR"/agents/*.md "$KIRO_AGENTS/"
    cp "$SCRIPT_DIR"/steering/*.md "$KIRO_STEERING/"
    echo "  ✓ Kiro agents + steering 已安裝"

    installed=$((installed + 1))
    echo ""
fi

# GitHub Copilot（無標準 config 目錄，永遠安裝）
echo "▸ 安裝 GitHub Copilot Skills"
mkdir -p "$HOME/.github/copilot-skills"
install_core "$COPILOT_SKILLS"
installed=$((installed + 1))
echo ""

# 結果摘要
echo "═══════════════════════════════════════"
if [ $installed -eq 0 ]; then
    echo "  ✗ 未偵測到 Claude Code、Kiro IDE 或 GitHub Copilot"
    echo "    請先安裝其中一個，再重新執行此腳本。"
    exit 1
else
    echo "  ✓ 安裝完成（$installed 個平台）"
    echo ""
    if [ -d "$CLAUDE_SKILLS" ]; then
        echo "  Claude Code: $CLAUDE_SKILLS"
    fi
    if [ -d "$KIRO_SKILLS" ]; then
        echo "  Kiro IDE:    $KIRO_SKILLS"
        echo "  Agents:      $KIRO_AGENTS"
        echo "  Steering:    $KIRO_STEERING"
    fi
    if [ -d "$COPILOT_SKILLS" ]; then
        echo "  Copilot:     $COPILOT_SKILLS"
    fi
    echo ""
    echo "  使用方式：/cobol-spec your_spool.txt"
fi
echo "═══════════════════════════════════════"
