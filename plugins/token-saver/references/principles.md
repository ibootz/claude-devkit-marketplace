# token 节用原则（frugal）

本文档是 token-saver 插件的详细原则参考。hook 在检测到高耗行为时会引导你读对应章节。
每条给**做法**、**为什么省 token**、**边界（什么时候不该省）**、**信源**。按需读你需要的
部分，不必整读。

## 1. 读前定位（最高杠杆）

**做法**：读大文件前先 `grep -n` / `Glob` 定位目标符号的行号，再 `Read` 带 `offset`/`limit`
只读必要段落。仅在需要核对整份规范/协议/纪律全文时才整读。

**为什么**：整读一个 2000 行文件 ≈ 数千 token 进上下文；定点读 50 行省 90%+。基于图的文件
选择实测可省 65-70% token。

**边界**：核对整份规范、协议、纪律全文时该整读就整读——分片会漏跨段冲突。「禁止的是无检索
目标就整读」，不是禁止整读。

**信源**：Anthropic context engineering；vexp.dev（基于图的文件选择省 65-70%）。

## 2. 大输出收窄

**做法**：测试/日志/dump 等大输出命令先收窄——加 `| wc -l` / `head -n 40` / `grep` /
`--oneline -n 20`，只取判断所需部分。收窄后仍 >200 行且须逐条分析的，交子代理只回摘要。

**为什么**：`npm test` 全量输出可上万行；收窄到失败段省 95%+。

**边界**：正在调试一条特定失败、需要完整堆栈时，短暂看全输出合理——别为省 token 丢掉诊断
信息。

**信源**：Claude Code costs 文档（PreToolUse 过滤测试输出省 95%+）。

## 3. 独立操作并发

**做法**：发起工具调用前先盘点「这批里哪些互不依赖」，不依赖的一律并发进同一条消息。串行
只在三情形：后步依赖前步输出 / 写同一资源 / 待用户拍板。

**为什么**：串行 N 次独立调用 = N 次各自重传上下文；并发合并进一条消息 = 一次。每次串行
往返都把完整上下文重新计费一次。

**信源**：Anthropic context engineering；codeant.ai（并行减少往返计费）。

## 4. 子代理隔离 verbose 输出

**做法**：探索性、高输出任务（文档调研、代码库探索、日志分析、全量测试）派子代理，要它
只回结构化摘要；verbose 原始过程留在子代理隔离上下文，不进主对话。

**为什么**：子代理在隔离窗口执行 verbose 操作，主上下文只留浓缩结果。研究实测多领域任务
省 ~40%。

**边界**：子代理摘要丢失了细节、需要原文佐证时，该自己读原文。第 2 层子代理不得再派。

**信源**：mindstudio（sub-agent 修 context rot）；Claude Code costs。

## 5. 模型档位匹配任务（最高杠杆之一）

**做法**：机械执行与常规语义任务用低档；跨层追根因、安全/并发/资金等极高正确性要求才升
高档。简单任务降 effort / 禁 extended thinking。

**为什么**：同任务高低档成本可差 15x；thinking tokens 计为输出 token，默认预算可达数万。
模型选择是省 token 最高杠杆决策。

**边界**：不确定时一档一档升，别预防性堆模型——升错档反而多烧。

**信源**：levelup.gitconnected（Haiku vs Opus 同任务差 15x）。

## 6. prompt caching 友好

**做法**：静态内容（system prompt、文档、代码库）置于 prompt 顶部并保持稳定；勿频繁变更
reasoning level / 工具配置（每次变更都破坏缓存）。

**为什么**：缓存命中成本降 90-98%、延迟降 85%。缓存读取价 $0.0028/百万 token（98% 折扣）。

**信源**：Anthropic prompt caching；InfoWorld。

## 7. context 限度：rot 与 lost-in-the-middle

**context rot**：context 填充超 ~65% 时性能静默退化（不是到上限才崩）。长会话每轮重传历史，
token 二次方增长——第 30 轮一个简单问可耗 50,000+ token。及时 `/compact`（phase 边界主动
压缩，自定义压缩指令）或 `/clear` 重开会话。

**lost-in-the-middle**：LLM 对 context 开头与结尾处理更好，中段信息易被忽略（U 型曲线）。
关键信息勿埋在长 context 正中间。

**反直觉**：更长 context window 反掩糟糕的 memory 设计，可能让结果更糟——不是窗口越大越好。

**信源**：Vincent Van deeth（context rot 65%）；arXiv 2307.03172（lost-in-the-middle）。

## 8. 长会话分段

**做法**：每 15-20 轮或里程碑处，总结关键决策（写进 NOTES.md / 待办）后 `/clear` 开新会话，
携摘要继续。phase 边界（如规划完成转实施）主动 `/compact`。

**为什么**：避免二次方增长；被动压缩（到上限才触发）准确度下降，主动压缩可保留架构决策、
丢弃探索噪声。

**信源**：pub.towardsai；augmentcode。

## 9. 请求具体化

**做法**：给具体请求「在 auth.ts 的 login 函数增加输入验证」，而非「改进这个代码库」。
具体请求减少 broad scanning，只读必需文件。

**为什么**：模糊请求触发广泛探索，读大量无关文件。

**信源**：Claude Code costs。

## 10. 什么时候不该省（避免过度）

省 token 是手段不是目的——省到丢掉正确性或诊断信息，得不偿失。下列场景该花就花：

- **核对整份规范/协议/纪律全文**：该整读就整读，分片漏跨段冲突。
- **调试特定失败需要完整堆栈**：短暂看全输出合理。
- **安全/并发/资金/权限相关**：正确性优先于省 token，该升档升档、该深挖深挖。
- **一次性、秒级短命令**：直接跑，不必收窄。

## 信源

- Anthropic · Effective context engineering for AI agents · https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Anthropic · Prompting best practices · https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices
- Claude Code · Costs · https://code.claude.com/docs/en/costs
- arXiv · Lost in the Middle · https://arxiv.org/abs/2307.03172
- Microsoft · LLMLingua · https://github.com/microsoft/LLMLingua
- Vincent Van deeth · context rot · https://vincentvandeth.nl/blog/context-rot-claude-code-automatic-rotation
- Redis · Context Pruning · https://redis.io/blog/context-pruning-llm-tokens/
