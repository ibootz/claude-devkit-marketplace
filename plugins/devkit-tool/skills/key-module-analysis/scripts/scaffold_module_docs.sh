#!/usr/bin/env bash
#
# scaffold_module_docs.sh - 生成模块档案文档脚手架
#
# 用法:
#   scaffold_module_docs.sh --module <名称> --path <模块路径> [--owner <负责人>] [--out <输出目录>]
#
# 选项:
#   --module   模块显示名称（必需）
#   --path     模块代码路径/包名（必需）
#   --owner    负责团队或维护者（默认: unknown）
#   --out      输出根目录（默认: docs/key-modules）
#   -h, --help 显示帮助信息
#
# 示例:
#   bash scaffold_module_docs.sh \
#     --module "订单结算" \
#     --path "backend/services/settlement" \
#     --owner "payments-team" \
#     --out "docs/key-modules"
#
set -euo pipefail

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 帮助信息
usage() {
  cat <<'USAGE'
用法:
  scaffold_module_docs.sh --module <名称> --path <模块路径> [--owner <负责人>] [--out <输出目录>]

选项:
  --module   模块显示名称（必需）
  --path     模块代码路径/包名（必需）
  --owner    负责团队或维护者（默认: unknown）
  --out      输出根目录（默认: docs/key-modules）
  -h, --help 显示帮助信息

示例:
  bash scaffold_module_docs.sh \
    --module "订单结算" \
    --path "backend/services/settlement" \
    --owner "payments-team" \
    --out "docs/key-modules"
USAGE
}

# 参数解析
MODULE_NAME=""
MODULE_PATH=""
OWNER="unknown"
OUT_ROOT="docs/key-modules"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --module)
      MODULE_NAME="${2:-}"
      shift 2
      ;;
    --path)
      MODULE_PATH="${2:-}"
      shift 2
      ;;
    --owner)
      OWNER="${2:-}"
      shift 2
      ;;
    --out)
      OUT_ROOT="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo -e "${RED}错误: 未知参数 $1${NC}" >&2
      usage
      exit 1
      ;;
  esac
done

# 验证必需参数
if [[ -z "$MODULE_NAME" || -z "$MODULE_PATH" ]]; then
  echo -e "${RED}错误: --module 和 --path 是必需参数。${NC}" >&2
  usage
  exit 1
fi

# Slugify 函数：将模块名转换为 URL 友好的标识符
slugify() {
  local s="$1"
  local result=""
  
  # 转小写
  s="$(echo "$s" | tr '[:upper:]' '[:lower:]')"
  
  # 尝试使用 Python 进行拼音转换（如果可用）
  if command -v python3 &> /dev/null 2>&1; then
    result="$(python3 -c "
import sys
import re
try:
    from pypinyin import pinyin, Style
    s = sys.argv[1]
    parts = pinyin(s, style=Style.NORMAL)
    result = '-'.join([p[0] for p in parts])
    result = re.sub(r'[^a-z0-9-]', '', result)
    result = re.sub(r'-+', '-', result).strip('-')
    print(result)
except ImportError:
    # 如果没有 pypinyin，使用简单的 slugify
    s = sys.argv[1].lower()
    result = re.sub(r'[^a-z0-9]+', '-', s)
    result = re.sub(r'-+', '-', result).strip('-')
    print(result if result else 'module')
" "$s" 2>/dev/null || echo "")"
  fi
  
  # 如果 Python 方法失败，使用基本的 sed 方法
  if [[ -z "$result" ]]; then
    result="$(echo "$s" | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//; s/-+/-/g')"
  fi
  
  # 如果结果为空，使用默认值
  if [[ -z "$result" ]]; then
    result="module"
  fi
  
  printf '%s' "$result"
}

# 获取脚本目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TEMPLATE_DIR="$SKILL_DIR/assets/templates"

# 检查模板目录
if [[ ! -d "$TEMPLATE_DIR" ]]; then
  echo -e "${RED}错误: 模板目录不存在: $TEMPLATE_DIR${NC}" >&2
  exit 1
fi

# 生成模块标识符
MODULE_SLUG="$(slugify "$MODULE_NAME")"
TARGET_DIR="$OUT_ROOT/$MODULE_SLUG"
DATE_UTC="$(date -u +%Y-%m-%d)"

# 检查目标目录是否已存在
if [[ -d "$TARGET_DIR" ]]; then
  echo -e "${YELLOW}警告: 目标目录已存在: $TARGET_DIR${NC}"
  read -p "是否覆盖? (y/N): " -n 1 -r
  echo
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${BLUE}操作已取消。${NC}"
    exit 0
  fi
fi

# 创建目标目录
mkdir -p "$TARGET_DIR"

echo -e "${BLUE}正在生成模块档案...${NC}"
echo -e "  模块名称: ${GREEN}$MODULE_NAME${NC}"
echo -e "  模块标识: ${GREEN}$MODULE_SLUG${NC}"
echo -e "  代码路径: ${GREEN}$MODULE_PATH${NC}"
echo -e "  负责团队: ${GREEN}$OWNER${NC}"
echo -e "  输出目录: ${GREEN}$TARGET_DIR${NC}"
echo

# 处理模板文件
file_count=0
for tpl in "$TEMPLATE_DIR"/*.md.tpl; do
  if [[ -f "$tpl" ]]; then
    filename="$(basename "$tpl" .tpl)"
    out="$TARGET_DIR/$filename"
    
    # 替换模板变量
    sed \
      -e "s/__MODULE_NAME__/$MODULE_NAME/g" \
      -e "s#__MODULE_PATH__#$MODULE_PATH#g" \
      -e "s/__MODULE_SLUG__/$MODULE_SLUG/g" \
      -e "s/__OWNER__/$OWNER/g" \
      -e "s/__DATE__/$DATE_UTC/g" \
      "$tpl" > "$out"
    
    file_count=$((file_count + 1))
    echo -e "  ${GREEN}✓${NC} $filename"
  fi
done

echo
echo -e "${GREEN}成功生成 $file_count 个文档文件！${NC}"
echo -e "档案位置: ${BLUE}$TARGET_DIR${NC}"
echo
echo -e "下一步操作:"
echo -e "  1. 按顺序填充各文档内容"
echo -e "  2. 从 ${YELLOW}00-module-card.md${NC} 开始"
echo -e "  3. 参考 ${YELLOW}references/methodology.md${NC} 了解方法论"
echo

# 列出生成的文件
echo -e "生成的文件:"
ls -1 "$TARGET_DIR" | while read -r f; do
  echo -e "  ${BLUE}├──${NC} $f"
done
