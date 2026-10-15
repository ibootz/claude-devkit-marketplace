#!/bin/bash
# 用法：run.sh <标签> <额外 eval 参数...>
TAG=$1; shift
W=/Users/zhangq/.claude/jobs/d1a1f6eb/tmp/history-probe
L=$W/logs; mkdir -p $L
ROOT=${ROOT:-$W/devkit-discipline}
cd $ROOT || exit 9
export PATH=$(echo "$PATH" | tr ":" "\n" | grep -v "/.asdf/shims" | paste -sd: -)
command -v node > $L/$TAG.node
date +%s > $L/$TAG.start
env -u CLAUDE_CODE_SESSION_ID -u CLAUDE_CODE_CHILD_SESSION -u CLAUDE_CODE_MESSAGING_SOCKET \
    -u CLAUDE_CODE_MESSAGING_TOKEN -u CLAUDE_CODE_SESSION_ATTENDED -u CLAUDE_CODE_ENTRYPOINT \
    -u CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS \
  /Users/zhangq/.local/bin/claude plugin eval $ROOT "$@" \
    --trust-plugin --no-publish --json $L/$TAG.json \
  > $L/$TAG.stdout 2> $L/$TAG.stderr
echo "exit=$?" > $L/$TAG.exit
date +%s > $L/$TAG.end
