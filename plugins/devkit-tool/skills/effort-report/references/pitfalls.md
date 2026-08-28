# 实测疤痕（每条都真实撞过）

## 1. 生成顺序：build_timeline 先于 gen_timeline / gen_md

gen_timeline/gen_md 顶层 `import` 时读 timeline.json——build 没跑（或失败）就跑生成器，读到的是**上一次的旧 timeline**，产出静默过期。跑生成器前确认 timeline.json 的 mtime 晚于 acts.json。

## 2. 管道吞 exit code

`python3 x.py 2>&1 | tail -1` 的 exit code 是 tail 的——链式 `&&` 串联九个脚本时，**中间脚本失败链子照走**，最后拿到的产物是新旧混合。回归复跑一律 `python3 x.py > log 2>&1 || { echo FAIL; break; }` 逐个重定向。

## 3. 生成器 OUT 直写正式产物

gen_timeline/gen_md 的 OUT 指向 docs/ 正式路径，**跑一次覆盖一次**。实测事故：调试期用中间版 build 跑了 gen_timeline，正式 HTML 被中间版覆盖（1,080,622 → 1,033,319 字节），恢复靠 transcript-replay 重放脚本历史。防御：调试图层先 sed 出 `_test` 副本改 OUT，正式路径只跑已过回归门的版本。

## 4. transcript-replay 恢复配方（脚本被覆盖/丢失时）

四种写入通道都要枚举：① Write/Edit 工具调用；② bash heredoc 创建（`python3 - <<'PY'` 内联补丁）；③ 「Write patchN.py → python3 patchN.py」两步通道（只搜内联会漏）；④ cp/mv。三个坑：
- **单趟 has_result 幽灵 bug**：jsonl 里 tool_result 行在对应 tool_use 行**之后**；单趟循环边扫边查 `id in has_result` 会把后置结果误判为 miss。必须**双趟**（第一趟专收 tool_result id）
- Edit miss（有 tool_use 无 tool_result）= 中止尝试，重放跳过；但也可能是「已应用过的重试」——对 miss 的 old_string 做「已含则跳过」判断
- **自匹配**：当前命令的 tool_use 在执行前已写入同一 jsonl，搜索串会命中自己。用时间戳上限 + 特定标记规避

## 5. 会话 jsonl 是活文件（本流水线最大的不可复现源）

`~/.claude/projects/<项目>/*.jsonl` 会被后续会话 **compact 重写**：早期事件文本被摘要化，窗口内（历史时段）的原始 ask/消息内容会漂移甚至丢失。D-003 实证：08-27 产出的报告里 6 个 ask 事件与 3 条真人指令，在 08-28 重扫后**永久不可复现**（acts 里全局零命中），造成 9 处事件归属残差 + 2 处 0.01 舍入传播差。**报告产出后立即冻结 acts.json/events.jsonl 快照**与产物 md 一起作回归基准；活文件只用于增量分析，不用于复现历史数字。

## 6. `echo ===` 被 zsh 当 `=cmd` 展开

zsh 里 `echo ===XXX===` 报 `not found`，后面的命令整段不执行（且报错容易被淹没）。分隔线一律 `echo ---`。

## 7. cd 守卫与裸 cd

cd-guard 拦一切裸 `cd`（含 `cd() { return; }` 这类花招——拦得更狠）。子 shell `(cd /abs && cmd)` 或 `git -C <path>`；python 脚本全绝对路径，不依赖 cwd。**被 L1-BLOCKER 拦掉的整条命令（含前面的 cp/sed）都没执行**，重试时别假设前半已生效。

## 8. 检索「没有」先自证

断言「不存在/零命中」前，用同一条命令搜一个确知存在的串确认能命中。三个已撞形态：NFC/NFD 路径形态差（macOS 中文目录）、被 gitignore 静默吞、grep 命中注释里的反引号路径被当成规则。JSON 转义同理：对 jsonl 原始行 grep 中文关键词前，先确认该文件不转义（或逐行 json.loads 后再匹配）。

## 9. 常量与数据结构漂移

- timeline.json 的 phase dict 字段集变更（如终态删掉 cross_h/none_h 顶层键）后，所有读方必须同步——gen_md 里留 `W["cross_h"] = 0` 类守卫只会掩盖漂移，报 KeyError 才是正确行为
- 别名脚本（`*_test.py`）与本体只有 OUT 一行之差时，本体改了别名没同步会在回归时暴露为「数据差异」而非「代码差异」——diff 本体与别名确认只差 OUT 再下结论
