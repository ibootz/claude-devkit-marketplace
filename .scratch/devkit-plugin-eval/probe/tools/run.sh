#!/bin/bash
# 本文件只用于 macOS 本机实测（票 01），不是交付脚本。
# 用法：run.sh <标签> <插件目录> <额外 eval 参数...>
# 产物：../out/<标签>.{json,stdout,stderr,exit,start,end,node,cmd}
TAG=$1; shift
ROOT=$1; shift
OUT=$(cd "$(dirname "$0")/../out" 2>/dev/null && pwd) || { mkdir -p "$(dirname "$0")/../out"; OUT=$(cd "$(dirname "$0")/../out" && pwd); }
ROOT=$(cd "$ROOT" && pwd) || exit 9   # 先转绝对路径：下面 cd 之后还要把它传给 eval
cd "$ROOT" || exit 9
# asdf shim 在 eval 的临时 HOME 下 exit 126 且 eval 不报错，必须让 PATH 直接命中真实 node
export PATH=$(echo "$PATH" | tr ":" "\n" | grep -v "/.asdf/shims" | paste -sd: -)
command -v node > "$OUT/$TAG.node"
echo "claude plugin eval <ROOT=$ROOT> $* --trust-plugin --no-publish --json $OUT/$TAG.json" > "$OUT/$TAG.cmd"
date +%s > "$OUT/$TAG.start"
env -u CLAUDE_CODE_SESSION_ID -u CLAUDE_CODE_CHILD_SESSION -u CLAUDE_CODE_MESSAGING_SOCKET \
    -u CLAUDE_CODE_MESSAGING_TOKEN -u CLAUDE_CODE_SESSION_ATTENDED -u CLAUDE_CODE_ENTRYPOINT \
    -u CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS \
  /Users/zhangq/.local/bin/claude plugin eval "$ROOT" "$@" \
    --trust-plugin --no-publish --json "$OUT/$TAG.json" \
  > "$OUT/$TAG.stdout" 2> "$OUT/$TAG.stderr"
echo "exit=$?" > "$OUT/$TAG.exit"
date +%s > "$OUT/$TAG.end"
