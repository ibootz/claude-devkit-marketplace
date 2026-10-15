#!/bin/bash
# 本文件只用于 macOS 本机实测（票 01），不是交付脚本。
# 用法：realsession.sh <envprobe 插件目录> <空工作目录>
# 在真实用户配置下（非 eval 沙箱）用 --plugin-dir 加载 envprobe，让模型调用 env-probe skill。
# 产物：../out/realsession.{out,exit}
PLUGIN=$1; WORK=$2
OUT=$(cd "$(dirname "$0")/.." && pwd)/out
mkdir -p "$OUT" "$WORK"
PLUGIN=$(cd "$PLUGIN" && pwd) || exit 9   # 先转绝对路径：下面 cd 之后还要把它传给 --plugin-dir
cd "$WORK" || exit 9
export PATH=$(echo "$PATH" | tr ":" "\n" | grep -v "/.asdf/shims" | paste -sd: -)
env -u CLAUDE_CODE_SESSION_ID -u CLAUDE_CODE_CHILD_SESSION -u CLAUDE_CODE_MESSAGING_SOCKET \
    -u CLAUDE_CODE_MESSAGING_TOKEN -u CLAUDE_CODE_SESSION_ATTENDED -u CLAUDE_CODE_ENTRYPOINT \
  /Users/zhangq/.local/bin/claude -p --plugin-dir "$PLUGIN" --model sonnet \
    --permission-mode bypassPermissions --output-format text \
    '请调用 env-probe 这个 skill，照它的指示执行，把命令输出原样贴给我。' \
  > "$OUT/realsession.out" 2>&1
echo "exit=$?" > "$OUT/realsession.exit"
