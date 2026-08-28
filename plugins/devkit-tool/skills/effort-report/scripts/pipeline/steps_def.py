# -*- coding: utf-8 -*-
"""AI-SDLC 明细步骤定义表（左半边：流程要求）+ 实测锚点规则（右半边：会话日志证据）。

步骤清单来源为插件自身的 SKILL / rules 文件，逐条带出处行号；
锚点规则是本报告自己定的映射方法，用来把会话日志里的动作归到步骤上。

锚点三类，命中任一即归属：
  f  产物文件路径片段（会话日志里 Write/Edit 的 file_path 后缀匹配）
  a  子代理派发的 description 关键词
  q  拍板问题的 header / question 关键词
"""

# ---------- fusion 侧 ----------
FUSION = [
 # (阶段key, 阶段名, 步骤id, 步骤名, MUST?, 出处, 锚点dict)
 ("f-convert", "需求生成（转换）", "FC1", "验证 requirement 存在", 1, "skills/req/SKILL.md:125", {}),
 ("f-convert", "需求生成（转换）", "FC2", "检测重复 / 前身（全地面 reconcile）", 1, "skills/req/SKILL.md:143", {"q": ["重复", "前身"]}),
 ("f-convert", "需求生成（转换）", "FC3", "需求批判性通读（禁零批判忠实打包）", 1, "skills/req/SKILL.md:216", {"q": ["需求纠偏", "批判"], "a": ["核验", "核 udp"]}),
 ("f-convert", "需求生成（转换）", "FC4", "自动跨域分析（能力索引 + Ontology 验证 + 置信度）", 1, "skills/req/SKILL.md:235", {"q": ["判域", "跨域"], "a": ["ontology", "cctx-registry", "撤挂"]}),
 ("f-convert", "需求生成（转换）", "FC5", "创建 fusion backlog 条目", 1, "skills/req/SKILL.md:350", {"f": ["fusion:sdlc/backlog/fix-succession-map-dept-headcount/_index.md", "fusion:sdlc/backlog/fix-succession-map-dept-headcount/stories.md"]}),
 ("f-convert", "需求生成（转换）", "FC6", "回写 requirement 状态（走写入器，禁手改）", 1, "skills/req/SKILL.md:474", {"f": ["fusion:sdlc/requirements/"]}),
 ("f-convert", "需求生成（转换）", "FC7", "Git 分层提交 + 推送远端", 1, "skills/req/SKILL.md:485", {"q": ["gitlink", "settings 处置"]}),
 ("f-g1",      "fusion · G1 门禁",  "FG1", "G1 · 值不值得做（dc:qualify 三镜头冷审 + Human 决策）", 1, "rules/flow-lifecycle.md:13", {"a": ["G1 冷审", "G1 复审"], "q": ["类型判定", "OQ-02", "工期估算"]}),
 ("f-define",  "fusion · Define",   "FD1", "Delivery 启动（建目录 / 收集 builder / scope.md / 关联 backlog）", 1, "sdlc-rules/base-fusion-discipline.md:66", {"f": ["fusion:sdlc/deliveries/D-040", "scope.md"], "q": ["下发路径", "联系人字段", "是否进 Define"]}),
 ("f-define",  "fusion · Define",   "FD2", "产出 storyline 骨架（Step 清单 / Seam 契约 / 验收准则）", 1, "skills/delivery/SKILL.md:111", {"f": ["storyline"], "a": ["storyline"], "q": ["storyline"]}),
 ("f-define",  "fusion · Define",   "FD3", "Ontology 上下文加载与对齐（§2–§6）", 1, "sdlc-rules/flow-fusion-define.md:24", {"a": ["ontology", "本体"]}),
 ("f-g2",      "fusion · G2 门禁",  "FG2", "G2 · spec 完整吗（storyline + behaviors 完整性）", 1, "sdlc-rules/base-fusion-discipline.md:128", {"a": ["G2"], "q": ["manual-cases 锚点", "OQ-02 已知限制", "抽象分工"]}),
 ("f-design",  "fusion · Design",   "FS1", "cctx 平台能力依赖识别", 1, "skills/delivery/SKILL.md:171", {"a": ["cctx"], "q": ["aPaaS", "dPaaS"]}),
 ("f-design",  "fusion · Design",   "FS2", "单域路径：manual-cases + STC 规格 + procedure 双件", 1, "skills/delivery/SKILL.md:205", {"f": ["manual-cases"], "q": ["covers 拼接", "manual-cases"]}),
 ("f-design",  "fusion · Design",   "FS3", "创建 breakdown.md + 版本规划", 1, "skills/delivery/SKILL.md:313", {"f": ["breakdown"], "q": ["version 字段", "车次"]}),
 ("f-g3",      "fusion · G3 门禁",  "FG3", "G3 · 方案可行吗（四件套齐全 + dc:qualify 两 checkpoint）", 1, "sdlc-rules/base-fusion-discipline.md:129", {"a": ["G3"], "q": ["权限+分页", "参照措辞", "ES边界"]}),
 ("f-dispatch","需求下发（dispatch）","FP1", "域工作区就绪预检", 1, "skills/delivery/SKILL.md:487", {"a": ["dispatch 前置", "单域下发通道"]}),
 ("f-dispatch","需求下发（dispatch）","FP2", "在 domain submodule 内建 backlog + upstream/（透传快照与切片）", 1, "skills/delivery/SKILL.md:491", {"f": ["backlog/fix-succession-map-dept-headcount/upstream"], "q": ["前移snapshot", "执行dispatch"]}),
 ("f-dispatch","需求下发（dispatch）","FP3", "提交 domain submodule 并 cascade 推主仓", 1, "skills/delivery/SKILL.md:505", {"q": ["gitlink"], "b": ["gitlink", "cascade"]}),
 ("f-dispatch","需求下发（dispatch）","FP4", "回写需求 frontmatter 的 fusion_status", 1, "skills/delivery/SKILL.md:518", {"q": ["requirements行回写"]}),
 ("f-dispatch","需求下发（dispatch）","FP5", "写 QA 摄入层（每个 feat）", 1, "skills/delivery/SKILL.md:534", {"f": ["tests/api/storylines", "tests/browser/storylines"]}),
 ("f-dispatch","需求下发（dispatch）","FP6", "fusion:notify distribute（发送前须 Human 确认）", 1, "sdlc-rules/base-fusion-discipline.md:109", {"a": ["notify", "通知"]}),
 ("f-wrap",    "需求收尾（fusion）", "FW1", "check-ready · 所有 domain state=verified", 1, "skills/delivery/SKILL.md:401", {}),
 ("f-wrap",    "需求收尾（fusion）", "FW2", "deploy-tf · 部署 TF 环境", 1, "skills/delivery/SKILL.md:586", {}),
 ("f-wrap",    "需求收尾（fusion）", "FW3", "Verify · 跑 manual-cases + automation 双证据", 1, "sdlc-playbooks/fusion-verify/PLAYBOOK.md:77", {"f": ["fusion:sdlc/deliveries/D-040-fix-succession-map-dept-headcount/validation-report.md"]}),
 ("f-wrap",    "需求收尾（fusion）", "FW4", "G4 · 验证通过吗", 1, "sdlc-rules/flow-fusion-delivery.md:34", {}),
 ("f-wrap",    "需求收尾（fusion）", "FW5", "backfill · 版本矩阵三坐标回填", 1, "skills/delivery/SKILL.md:397", {}),
 ("f-wrap",    "需求收尾（fusion）", "FW6", "G5 · 可合入交付吗 + notify deliver", 1, "sdlc-rules/flow-fusion-delivery.md:138", {}),
]

# ---------- domain 侧 ----------
DOMAIN = [
 ("d-supply", "需求接收与 Supply", "S1", "接收 upstream 物料 + 建 backlog 条目", 1, "rules/flow-supply.md:76", {"f": ["main:sdlc/backlog/fix-succession-map-dept-headcount/upstream", "wt:sdlc/backlog/fix-succession-map-dept-headcount/upstream"]}),
 ("d-supply", "需求接收与 Supply", "S2", "triage + 写 stories.md + 定优先级", 1, "rules/flow-supply.md:76", {"f": ["backlog/fix-succession-map-dept-headcount/stories.md"], "a": ["backlog upstream", "现有规格"]}),
 ("d-supply", "需求接收与 Supply", "S3", "粒度校准（小 Feature vs Feature）", 1, "skills/define/SKILL.md:89", {"q": ["粒度"]}),

 ("d-g1", "G1 门禁", "G1", "G1 · 值不值得做（DoD 九项自检 + dc:qualify 三镜头 + Human 决策）", 1, "skills/define/SKILL.md:170", {"a": ["冷审 backlog", "L2 lens", "对抗审计"], "q": ["G1 放行", "AC 缺口", "漏人风险", "粒度判据"], "f": ["main:sdlc/backlog/fix-succession-map-dept-headcount/_index.md"]}),
 ("d-g1", "G1 门禁", "G1b", "worktree 创建（编号占位 / acquire push / submodule 初始化）", 1, "skills/define/SKILL.md:170", {"q": ["submodule 追新", "worktree"]}),

 ("d-define", "Define 阶段", "D03", "步骤 0.3/0.4 · aPaaS / dPaaS codified-context 决策", 0, "skills/define/SKILL.md:40", {"q": ["aPaaS", "dPaaS"]}),
 ("d-define", "Define 阶段", "D0",  "步骤 0 · Feature 进入分类 + 7 维粒度校准 + 5 类反模式扫描", 1, "skills/define/SKILL.md:89", {}),
 ("d-define", "Define 阶段", "D1",  "步骤 1 · 上下文加载（四层产物扫描）", 1, "skills/define/SKILL.md:109", {"a": ["定位", "取产品愿景", "现有规格"]}),
 ("d-define", "Define 阶段", "D2",  "步骤 2 · 对话收集需求（5 项收敛条件）", 1, "skills/define/SKILL.md:139", {}),
 ("d-define", "Define 阶段", "D3",  "步骤 3 · 写 scope.md", 1, "skills/define/SKILL.md:312", {"f": ["D-003-fix-succession-map-dept-headcount/scope.md"], "a": ["scope"]}),
 ("d-define", "Define 阶段", "D35", "步骤 3.5 · 棕地影响面审计（code-grounded → coverage.md）", 0, "skills/define/SKILL.md:336", {"f": ["D-003-fix-succession-map-dept-headcount/coverage.md"], "a": ["影响面", "扫描 posQty"]}),
 ("d-define", "Define 阶段", "D37", "步骤 3.7 · storyline 草稿", 0, "skills/define/SKILL.md:364", {"f": ["succession/storylines"], "a": ["storyline"], "q": ["storyline"]}),
 ("d-define", "Define 阶段", "D4",  "步骤 4 · 展开行为契约 behaviors/", 1, "skills/define/SKILL.md:374", {"f": ["succession/behaviors/"], "a": ["behaviors", "gherkin", "行为契约"]}),
 ("d-define", "Define 阶段", "D5",  "步骤 5 · UI 契约 + prototype.html", 0, "skills/define/SKILL.md:421", {"f": ["succession/ui/"], "a": ["UI 契约", "prototype"]}),
 ("d-define", "Define 阶段", "D6",  "步骤 6 · API 契约推导 contracts.md", 0, "skills/define/SKILL.md:470", {"f": ["succession/contracts.md"], "a": ["契约", "contracts"]}),
 ("d-define", "Define 阶段", "D7",  "步骤 7 · 实体推导 entities.md", 0, "skills/define/SKILL.md:533", {"f": ["succession/entities"], "a": ["entities", "实体"]}),
 ("d-define", "Define 阶段", "D8",  "步骤 8 · NFR", 0, "skills/define/SKILL.md:571", {"f": ["nfr.md"]}),
 ("d-define", "Define 阶段", "D9",  "步骤 9 · 更新 deliveries/_index.md frontmatter", 1, "skills/define/SKILL.md:600", {"f": ["D-003-fix-succession-map-dept-headcount/_index.md"]}),

 ("d-g2", "G2 门禁", "G2", "G2 · spec 完整吗（Spec 完整性审查协议）", 1, "skills/define/SKILL.md:646", {"f": ["gate/gate-review-g2"], "a": ["G2"], "q": ["G2"]}),

 ("d-design", "Design 阶段", "X1",  "步骤 1 · 读取输入 + Spec 上下文加载", 1, "skills/design/SKILL.md:72", {}),
 ("d-design", "Design 阶段", "X2a", "步骤 2a · 架构基线检查", 1, "skills/design/SKILL.md:107", {"a": ["架构"]}),
 ("d-design", "Design 阶段", "X2b", "步骤 2b · 实体增量补技术细节", 0, "skills/design/SKILL.md:115", {}),
 ("d-design", "Design 阶段", "X2c", "步骤 2c · API 增量补技术细节", 0, "skills/design/SKILL.md:124", {}),
 ("d-design", "Design 阶段", "X2c1","步骤 2c.1 · UI 增量验证 + data-testid 审计", 0, "skills/design/SKILL.md:132", {"a": ["testid"]}),
 ("d-design", "Design 阶段", "X2d", "步骤 2d · 条件 Spec（states / cache / algorithms）", 0, "skills/design/SKILL.md:154", {"f": ["succession/algorithms/", "succession/states", "succession/cache"], "a": ["算法", "alg-"]}),
 ("d-design", "Design 阶段", "X2e", "步骤 2e · 记录 ADR → decisions.md", 1, "skills/design/SKILL.md:169", {"f": ["D-003-fix-succession-map-dept-headcount/decisions.md"], "a": ["ADR", "decisions"]}),
 ("d-design", "Design 阶段", "X2g", "步骤 2g · 行为覆盖声明 covers（Gap Analysis）", 1, "skills/design/SKILL.md:180", {"f": ["test-coverage-map"], "q": ["covers"]}),
 ("d-design", "Design 阶段", "X2h", "步骤 2h · 行为回验（反向验证 behaviors 完备性）", 1, "skills/design/SKILL.md:207", {"a": ["回验", "复核"]}),
 ("d-design", "Design 阶段", "XT0", "步骤 2T0 · 影响面映射 impact_map", 0, "skills/design/SKILL.md:212", {}),
 ("d-design", "Design 阶段", "XT1", "步骤 2T1 · test-points-design 子工作流（不可跳）", 1, "skills/design/SKILL.md:221", {"f": ["test-points"], "a": ["test-point", "测试点"]}),
 ("d-design", "Design 阶段", "XT2", "步骤 2T2 · test-review 子工作流（不可跳）", 1, "skills/design/SKILL.md:228", {"f": ["review-report"], "a": ["test-review", "测试评审"]}),
 ("d-design", "Design 阶段", "XT3", "步骤 2T3 · test-case-design 子工作流（不可跳）", 1, "skills/design/SKILL.md:236", {"f": ["test-cases"], "a": ["test-case", "用例"]}),
 ("d-design", "Design 阶段", "XT4", "步骤 2T4 · storyline-case-design 子工作流（不可跳）", 1, "skills/design/SKILL.md:242", {"f": ["storylines/"], "a": ["storyline"]}),
 ("d-design", "Design 阶段", "X2f", "步骤 2f · 任务拆分 tasks.md（7 条铁律 + 落点实证 + 四扫）", 1, "skills/design/SKILL.md:258", {"f": ["D-003-fix-succession-map-dept-headcount/tasks.md"], "a": ["tasks", "任务拆"]}),
 ("d-design", "Design 阶段", "X3",  "步骤 3 · 提炼人类文档 decisions.md（Summary / 架构概要）", 1, "skills/design/SKILL.md:416", {"f": ["design-digest"]}),
 ("d-design", "Design 阶段", "X2x", "Step 2.x · ontology spec-to-ontology drain queue", 0, "skills/design/SKILL.md:424", {"f": ["ontology"], "a": ["ontology", "本体"]}),

 ("d-g3", "G3 门禁", "G3", "G3 · 方案可行吗（contracts + decisions + tasks 审查）", 1, "skills/design/SKILL.md:501", {"f": ["gate/gate-review-g3"], "a": ["G3"], "q": ["G3"]}),

 ("d-impl", "Implement 阶段", "I0", "前置 · Spec 上下文加载 + 环境检测 + submodule worktree 就绪", 1, "skills/implement/SKILL.md:27", {}),
 ("d-impl", "Implement 阶段", "I1", "阶段一 · 按 DAG 执行 TDD（per-task review / Reuse Ladder / code-simplifier）", 1, "skills/implement/SKILL.md:115", {"f": ["/src/"], "a": ["TASK-", "实现", "修复"], "b": ["mvn ", "gradle", "javac", "spring-boot:run", "yarn build", "npm run build"]}),
 ("d-impl", "Implement 阶段", "I2", "阶段二 · 跨 task code-review + 落盘 code-review-report.md", 1, "skills/implement/SKILL.md:320", {"f": ["code-review-report"], "a": ["code-review", "评审"]}),
 ("d-impl", "Implement 阶段", "I3", "DDL 变更检查", 0, "skills/implement/SKILL.md:355", {"a": ["DDL"], "q": ["DDL"], "b": ["dbops", "information_schema", "alter table"]}),
 ("d-impl", "Implement 阶段", "I4", "阶段三 · dev→QA per-gherkin fan-out（N×K 并行 QA）", 1, "skills/implement/SKILL.md:385", {"f": ["tests/api/", "tests/browser/"], "a": ["QA", "playwright", "自动化"], "b": ["playwright", "npx ", "pytest"]}),
 ("d-impl", "Implement 阶段", "I5", "阶段四 · AI 自检门槛（双线 PASS + data-testid 审计 + 自动补漏）", 1, "skills/implement/SKILL.md:484", {"a": ["自检", "补漏"]}),

 ("d-verify", "Verify 阶段", "V0",   "Step 0 · ontology cross-cutting 聚合 + drain queue", 1, "skills/verify/SKILL.md:59", {"f": ["ontology"], "a": ["ontology"]}),
 ("d-verify", "Verify 阶段", "V1",   "Step 1 · 读取信心基线 + 测试配置", 1, "skills/verify/SKILL.md:100", {"f": ["tests/api/env.yaml"]}),
 ("d-verify", "Verify 阶段", "V15",  "Step 1.5 · 环境选择 + 切片透传（单 env per run）", 1, "skills/verify/SKILL.md:126", {"q": ["环境", "env"], "b": ["ymcas", "cred ", "env.yaml"]}),
 ("d-verify", "Verify 阶段", "V16",  "Step 1.6 · 阶段门禁判定（两阶段递进）", 1, "skills/verify/SKILL.md:157", {}),
 ("d-verify", "Verify 阶段", "V17",  "Step 1.7 · release line 组装强解析", 1, "skills/verify/SKILL.md:186", {"q": ["release", "车次", "版本"]}),
 ("d-verify", "Verify 阶段", "V18",  "Step 1.8 · test-plan 预览 + Human 确认（必走）", 1, "skills/verify/SKILL.md:278", {"q": ["test-plan", "测试计划"]}),
 ("d-verify", "Verify 阶段", "V2",   "Step 2 · 全量回归（当前 Feature api 层）", 0, "skills/verify/SKILL.md:322", {"a": ["回归", "api 测试"], "b": ["tests/api", "run_api", "curl -"]}),
 ("d-verify", "Verify 阶段", "V3",   "Step 3 · 跨 Feature 回归", 1, "skills/verify/SKILL.md:351", {"a": ["跨 Feature", "回归"]}),
 ("d-verify", "Verify 阶段", "V35",  "Step 3.5 · UI + UI 交互层验证（含 G4 Self-Check / ADR-10 退化断言）", 1, "skills/verify/SKILL.md:384", {"f": ["tests/browser/"], "a": ["UI", "playwright", "浏览器"], "b": ["playwright", "agent-browser", "chromium"]}),
 ("d-verify", "Verify 阶段", "V36",  "Step 3.6 · 覆盖率盲点条件触发推荐", 0, "skills/verify/SKILL.md:505", {}),
 ("d-verify", "Verify 阶段", "V37",  "Step 3.7 · 本地 UI 决策点（决策权在 Human）", 1, "skills/verify/SKILL.md:532", {"q": ["本地 UI", "UI 验证"]}),
 ("d-verify", "Verify 阶段", "V4",   "Step 4 · 追溯矩阵", 1, "skills/verify/SKILL.md:585", {"f": ["test-coverage-map"]}),
 ("d-verify", "Verify 阶段", "V5",   "Step 5 · 生成 validation-report.md", 1, "skills/verify/SKILL.md:600", {"f": ["D-003-fix-succession-map-dept-headcount/validation-report.md"]}),
 ("d-verify", "Verify 阶段", "V55",  "Step 5.5 · 失败 TC 自动回环分流", 1, "skills/verify/SKILL.md:623", {"a": ["失败", "回环", "debug"]}),
 ("d-verify", "Verify 阶段", "V6",   "Step 6 · 更新 deliveries/_index.md frontmatter", 1, "skills/verify/SKILL.md:668", {}),
 ("d-verify", "Verify 阶段", "V65",  "Step 6.5 · ontology delta report + fingerprint 升级", 0, "skills/verify/SKILL.md:766", {"f": ["ontology"]}),

 ("d-g4", "G4 门禁", "G4", "G4 · 验证通过吗（审 validation-report.md）", 1, "skills/verify/SKILL.md:784", {"f": ["gate/gate-review-g4"], "a": ["G4"], "q": ["G4"]}),

 ("d-deliver", "Deliver 阶段", "L1",  "Step 1 · 验证前置条件", 1, "skills/deliver/SKILL.md:66", {}),
 ("d-deliver", "Deliver 阶段", "L2",  "Step 2 · 生成 release-plan.md", 1, "skills/deliver/SKILL.md:78", {"f": ["release-plan"]}),
 ("d-deliver", "Deliver 阶段", "L27", "Step 2.7 · 正向防护网复盘收口（4 维收敛）", 1, "skills/deliver/SKILL.md:136", {"f": ["retrospectives"], "a": ["复盘", "防护网"]}),
 ("d-deliver", "Deliver 阶段", "L28", "Step 2.8 · 运维侧待办清单", 1, "skills/deliver/SKILL.md:146", {"f": ["ops-checklist"]}),
 ("d-deliver", "Deliver 阶段", "L3",  "Step 3 · G5 门禁", 1, "skills/deliver/SKILL.md:183", {"f": ["gate/gate-review-g5"], "a": ["G5"], "q": ["G5"]}),
 ("d-deliver", "Deliver 阶段", "L4",  "Step 4 · 执行 merge", 1, "skills/deliver/SKILL.md:220", {"q": ["merge", "合入"]}),
 ("d-deliver", "Deliver 阶段", "L5",  "Step 5 · 知识复合回馈 Backlog（不可跳）", 1, "skills/deliver/SKILL.md:300", {"f": ["knowledge-candidates"], "a": ["知识"]}),
 ("d-deliver", "Deliver 阶段", "L7",  "Step 7 · 归档 Backlog 条目（不可跳）", 1, "skills/deliver/SKILL.md:351", {}),
]

PLUGIN_FUSION = "/Users/zhangq/.claude/plugins/cache/aisdlc-fusion/fusion/1.19.0/"
PLUGIN_SDLC = "/Users/zhangq/.claude/plugins/cache/ai-sdlc/sdlc/3.15.0/"
