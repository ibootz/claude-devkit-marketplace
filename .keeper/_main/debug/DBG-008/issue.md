---
id: DBG-008
summary: vim 打开 .json 文件报 E10（FileType json 自动命令出错）
status: open
priority: P1
difficulty: easy
type: config
spec_status: violation
reported_at: '2026-08-28'
reopen_count: 0
---

## 用户原话

> fix vim 打开时报错

（附截图一张，已随件落盘为本条目目录下 `.keeper/_main/debug/DBG-008/01-vim-json-E10.png`）

origin_path: /Users/zhangq/.claude/image-cache/6b4985f0-e39c-438e-aadf-d9b29ed763be/1.png

## 现场截图转录（以截图为准）

在 vim 中打开 `~/.claude/settings.glm.json`（13 行，501 字节）时，vim 报：

> 处理 BufRead 自动命令 "*"..function dist#ft#DetectFromExt[9]..FileType 自动命令 "json" 时发生错误:
> E10: \ 后面应该跟有 /、? 或 &

## Triage（已核实，2026-08-28）

**结论**：根因为本机 [.vimrc:127](vscode://file/Users/zhangq/.vimrc:127) 行尾多余的续行反斜杠；与本仓（claude-devkit-marketplace）无关，不建 worktree（§10 豁免：单行 easy 修复，直接改本机配置）。原「初步推断」的方向（坏命令在用户 vim 配置的 FileType autocmd 里）成立，但坏命令形态不是 `:s` 误用，而是命令文本以 `\` 开头。

**坏命令原文**（[.vimrc:127-128](vscode://file/Users/zhangq/.vimrc:127)，修复前）：

```vim
  autocmd FileType javascript,javascriptreact,typescript,typescriptreact,json,yaml,yml \
        \ setlocal expandtab shiftwidth=2 tabstop=2 softtabstop=2
```

**机制**：vim 行继续规则（`:help line-continuation`）只删除「下一行的前导空白 + `\`」，第一行**行尾**的 `\` 不是续行标记、原样保留。拼接后注册的自动命令文本为 `\ setlocal expandtab shiftwidth=2 tabstop=2 softtabstop=2`（以 `\` 开头；实测 `autocmd FileType` 清单中 json/yaml/yml 及 js/ts 各条目均带 `\` 前缀，java/python/sh 等正常条目无）。触发执行时，do_one_cmd 对 `\` 开头的命令仅接受 `\/` `\?` `\&`（`:s/` `:s?` `:s&` 的历史简写），其余抛 E10（`:help E10`）。

**实测证据**（修复前，两条独立通道复现）：

- `vim --not-a-term /tmp/dbg008-test.json -c 'qa!'` → stderr 报「处理 BufRead 自动命令 "*"..function dist#ft#DetectFromExt[9]..FileType 自动命令 "json" 时发生错误: E10: \ 后面应该跟有 /、? 或 &」，与截图逐字一致。
- `vim -u /Users/zhangq/.vimrc -es -c 'doautocmd FileType json' ...` 后 `v:errmsg` = `E10: \ 后面应该跟有 /、? 或 &`。
- 环境注记：用户实际 vim 为 `/opt/homebrew/bin/vim`（9.2, patches 1-950）；`/usr/bin/vim` 为 Apple 打包版。`vim -es`（不带 `-u`）在该 Homebrew vim 下**不加载用户 vimrc**（`-V15` 启动日志无 sourcing ~/.vimrc 记录、`&cp` 为真），此通道不能用于本条复现，验证须用 `--not-a-term` 或显式 `-u ~/.vimrc`。

**受影响面**：javascript / javascriptreact / typescriptreact / typescript / json / yaml / yml 七种文件类型打开必报 E10（不止用户碰到的 json）；java / python / sh / bash / zsh / make / gitcommit 不受影响。

**规格依据**（spec_status: violation）：vim 官方文档 `:help line-continuation`（行继续的正确写法）与 `:help E10`（`\` 开头命令仅限 `\/` `\?` `\&`）。错误行为有权威判据，非规格空白。

**修复**：删除 127 行行尾 `\`，保留下一行行首 `\` 续行。备份：`/Users/zhangq/.vimrc.bak-20260828-135758`。

**验证场景**（穷举，修复后逐项实测）：

- A. 打开 .json 文件（`--not-a-term` 完整加载配置）：E10 消失，且 `shiftwidth` 实际变为 2（命令真执行，非仅不报错）。
- B. `doautocmd FileType json` 后 `v:errmsg` 保持 NOERR。
- C. 同类受影响类型逐个开文件：javascript / typescript / yaml 均 E10 消失且 `sw=2` 生效。
- D. 对照组：java 文件打开不报错、`sw=4` 生效（修复不波及原正常条目）。

**验证结果**（2026-08-28 修复后实测，四项全过）：

- A 过：`vim --not-a-term /tmp/dbg008-test.json -c 'qa!' 2>&1 | grep -c 'E10'` → `0`；同方式取选项 → `ft=json sw=2 ts=2`（setlocal 真实生效，非仅不报错）。
- B 过：`vim -u /Users/zhangq/.vimrc -es -c 'let v:errmsg="NOERR"' -c 'doautocmd FileType json' ...` 后 `v:errmsg=NOERR`、exit 0。
- C 过：js → `ft=javascript sw=2 E10count=0`；ts → `ft=typescript sw=2 E10count=0`；yaml → `ft=yaml sw=2 E10count=0`。
- D 过：java → `ft=java sw=4 E10count=0`。
- 用户原始触发文件复测：`vim --not-a-term /Users/zhangq/.claude/settings.glm.json -c 'qa!' 2>&1 | grep -c 'E10'` → `0`。
- 结构复查：修复后 `autocmd FileType` 注册文本中 `json`/`yaml` 条目为 `setlocal expandtab shiftwidth=2 tabstop=2 softtabstop=2`（`\` 前缀消失）。

**状态**：修复完成、验证全过，status 暂留 open，待用户 accept 后标 done 并归档；不接受可回滚（备份 `/Users/zhangq/.vimrc.bak-20260828-135758`）。
