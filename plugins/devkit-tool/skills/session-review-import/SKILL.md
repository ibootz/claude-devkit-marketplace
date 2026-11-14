---
name: session-review-import
description: "把别人上传到 NAS 的 Claude Code 会话记录导入本机 claude-devtools（Context 应用）审阅——合并多日增量切片、落位 ~/.claude/projects、子代理进 <sessionId>/subagents/。用户说「导入别人的对话记录」「审核 / 审阅他人上传的会话」「把 NAS 上的会话弄到 devtools 里看」「某人做的需求会话拉下来看看」时使用；也治「devtools 会话列表一堆碎条目 / 每条只有 1~4 条消息」「会话不能识别成唯一对话」。只看本机会话、分析 sdlc 作用源（走 gen_chat_view 脚本）不触发。"
---

# 导入他人 NAS 会话到 claude-devtools 审阅

claude-devtools（`/Applications/claude-devtools.app`，bundle id `com.claudecode.context`，下称 devtools）**没有导入入口**：它只 `fs.watch(recursive)` 扫 `~/.claude/projects` 一个目录，索引进内存（IndexedDB 落盘为空），重启必重扫。导入 = 把 NAS 切片转换后放进该目录。NAS 全程只读。

## 一、devtools 的两条铁律（2026-11-02 逆向 app.asar 证实，决定成败）

| 铁律 | 内容 | 违反后果 |
|---|---|---|
| **列表条目 = 文件** | 会话列表对项目目录做 `readdir` 后只过滤 `isFile() && endsWith('.jsonl')`，**连 `agent-` 前缀都不排除**；文件名（去 .jsonl）即条目 id | 顶层多放任何一个 .jsonl（含子代理、含备份）都显示为一条独立会话 |
| **子代理进子目录** | 子代理正确落位是 `<project>/<sessionId>/subagents/agent-*.jsonl`（新结构）；顶层平铺的「旧结构兼容」（读首行 sessionId 判归属）**只在详情页生效，列表页不调** | 平铺 → 每个子代理一条碎条目（1~4 messages、时间各异），用户以为「没识别成唯一对话」 |

推论：**项目目录顶层必须恰好只有一个 `.jsonl`**（主会话）；备份文件用非 .jsonl 后缀（如 `.bak`），否则备份也是列表条目。

不参与列表判定的字段（都实测过，别再往这些方向猜）：parentUuid 链、compact / isCompactSummary、custom-title(summary) 行、行级 sessionId、17 个以内的兄弟分叉。UI 里的「叉形图标」是 worktree 分组行，不是分支树。

## 二、NAS 导出结构（aisdlc-saas-extension:cc-session-nas-upload 上传）

```
/Volumes/AI_SDLC/exports/<域账号>/<YYYY-MM-DD>/<projectName>/
  <sessionId>.jsonl            # 主会话增量切片：同会话跨日多片，按水位不重叠
  <sessionId>.metadata.json
  agent-<id>.jsonl             # 子代理，平铺；同目录混着该人【其他会话】的子代理
  agent-<id>.metadata.json     # source.parentSessionId 是过滤键
```

- 多日多片合并：顺序拼接，按行内 `uuid` 去重防边界重叠；子代理跨日同名文件同样合并去重。
- 子代理过滤键：`metadata.json` 的 `source.parentSessionId`；agent 文件首行 `sessionId` 字段恰好也是父会话 id（devtools 旧结构判归属用的就是它）。
- 项目目录名 = 主会话行 `cwd` 按非 `[A-Za-z0-9]` 全替换为 `-`：Windows `D:\code\xxstar-ai-sparring-work` → `D--code-xxstar-ai-sparring-work`，mac `/Users/z/...` → `-Users-z-...`。

## 三、导入脚本（改三个变量后照跑）

```python
import json, glob, os
OWNER, PROJ = 'wangpengfei', 'xxstar-ai-sparring-work'
SID = '13d173a2-10c2-4b37-8497-88c87dc6d612'          # 主会话 id
DAYS = sorted(glob.glob(f'/Volumes/AI_SDLC/exports/{OWNER}/*/{PROJ}'))  # 跨日全取
dst = os.path.expanduser(f'~/.claude/projects/D--code-{PROJ}')           # 目录名按 cwd 转义
os.makedirs(os.path.join(dst, SID, 'subagents'), exist_ok=True)

def merge(paths):                       # 按行 uuid 去重拼接
    seen, out = set(), []
    for p in paths:
        for line in open(p):
            try: u = json.loads(line).get('uuid')
            except Exception: u = None
            if u and u in seen: continue
            if u: seen.add(u)
            out.append(line.rstrip('\n'))
    return out

main = merge([f'{d}/{SID}.jsonl' for d in DAYS if os.path.exists(f'{d}/{SID}.jsonl')])
open(os.path.join(dst, SID + '.jsonl'), 'w').write('\n'.join(main) + '\n')
n = 0
for jp in sorted(glob.glob(DAYS[0] + '/agent-*.jsonl') + glob.glob(DAYS[-1] + '/agent-*.jsonl')):
    m = json.load(open(jp[:-6] + '.metadata.json'))
    if m.get('source', {}).get('parentSessionId') != SID: continue      # 剔除其他会话的子代理
    merged = merge(sorted(glob.glob(DAYS[0] + '/' + os.path.basename(jp)) +
                          glob.glob(DAYS[-1] + '/' + os.path.basename(jp))))
    open(os.path.join(dst, SID, 'subagents', os.path.basename(jp)), 'w').write('\n'.join(merged) + '\n')
    n += 1
print(f'主会话 {len(main)} 行, 子代理 {n} 个 → {dst}')
```

注意：上面的子代理收集段只看了首末两天目录，跨 ≥3 天时把 DAYS 里所有日期目录 glob 进去（本次两天故简化）。

## 四、验证与收尾

1. **数据自检**：主会话逐行 `json.loads` 零失败；首末行 timestamp 与 metadata 的 coversFrom/coversTo 对得上；顶层 `ls` 恰好一个 `.jsonl`。
2. **列表自检**：重启（或等 30s watch 兜底）后 devtools 列表该会话**只有一条**；出现碎条目 → 回第一节查顶层文件。
3. **详情页自检**：子代理挂载在新结构子目录，理论上详情页可见——此点外部不可观测，以用户看到的为准。
4. **回滚**：`rm -rf ~/.claude/projects/<转义目录>`，本机会话零影响。
5. 用完提醒用户可整体删除；NAS 侧绝不写。

## 五、教训（为什么不是小题大做）

- **「存在兼容代码」≠「该用兼容形态」**：devtools 明明写了旧结构平铺兼容（`getProjectRootSubagentFiles` 读首行 sessionId 判归属），我照它平铺 33 个 agent 文件，结果列表页根本不调那段代码——每文件一条碎条目。选落位形态前先看**列表构建**逻辑，不是详情页。
- **jsonl 行结构天然有兄弟并列**：同一回复拆成多行块（assistant 续块与 tool_result 回填并列挂同一 parentUuid），十几个「分叉」是正常结构不是 rewind 废弃分支。链完整性判据是**断链数=0 且消息链头=0**，不是分叉数=0；用「单链回溯」删兄弟块会误删一半以上消息行（实测 4139 → 1472，回滚了）。
- **备份后缀别用 .jsonl**：`xxx-full-with-branches.jsonl.bak` 不进列表，`xxx.bak.jsonl` 会进。

## 什么时候不触发

- 审阅对象是**本机自己的会话**——devtools 本来就能看到，无需导入。
- 目的是**sdlc / 插件作用源分析**（技能手册注入、每轮 UserPromptSubmit 路由注入、hook 拦截、常驻规则底座）——devtools 的 asar 里九个 attachment 子类型关键字（nested_memory / hook_additional_context / api-request-shape 等）全部零命中，它不解析 attachment 层；用 gen_chat_view.py 生成动态切片 HTML 那条路。
- 会话在 NAS 上只有单日单片、无子代理——脚本照跑，只是合并退化为复制。
