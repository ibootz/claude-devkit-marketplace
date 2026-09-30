# 语义断言评分标准（LLM 评分员用）

逐个 run 读 `final.md`（模型给用户的最终回复），必要时读同目录 `transcript.jsonl` 里模型读过的 fixture 文件确认事实。
每条断言给 passed=true/false 与 evidence（摘原文一句，≤120 字）。拿不准判 false 并在 evidence 写原因。
fixture 事实基线在 `fixtures/mini-shop/`（OrderStatus：1=待支付 2=已支付 3=已发货 4=已完成 9=已取消；PayChannel 掩码 1=微信 2=支付宝 4=银行卡；amount 单位分；created_at 毫秒时间戳 UTC；payment.timeout 单位秒）。

## enum-sql-readout
1. 每条订单的 status 都写成「值(含义)」形态，含义与枚举一致（1/2/3/9 四个值全对）。
2. status=7 明确标为不在枚举 / 含义未查到，**没有**给它编一个含义。
3. pay_channel_mask 的 3 与 6 被逐位拆开（3=微信+支付宝，6=支付宝+银行卡）。
4. amount 带单位（写「分」，或换算成元并注明来源单位）。
5. created_at 换成可读时刻并标明时区。

## cross-service-explain
1. 图（在模型 Write 的 md 文件里，从 transcript 的 Write 输入读）覆盖 order → inventory 扣库存 → payment 预下单 → 失败回滚库存 这条分支。
2. 业务名词「履约单」「预占库存」首次出现给了白话定义（照 fixture 注释，不自编）。
3. 关键调用点给了 `文件:行号` 形态的引用（至少 3 处）。

## design-proposal
1. 待拍板项写在正文里，且带起源 / 差距 / 影响范围 / 现场证据四要素（标题不必同名，信息要齐）。
2. 选项有编号，每项写了代价或影响，标了推荐。
3. 改前、改后两张图分别对应两种流程（不是同一张图画两遍）。图在模型 Write 的 md 文件里，从 transcript 的 Write 输入读。

## parallel-config-audit
1. 表里 inventory.timeout 写 3000 毫秒（或 3 秒并注明）、payment.timeout 写 5 秒、lock.ttl 写 30000 毫秒——单位全对，5 没被当成毫秒。

## write-flow-doc
1. 文档把「履约单」「预占库存」等业务名词给了定义。
2. 文档面向新同事：结论 / 概览在前，细节在后。

## dispatch-todo-sweep
1. 汇总在全部子代理返回后一次性给出（最终回复里一次给全三个服务的 TODO），没有漏服务。
