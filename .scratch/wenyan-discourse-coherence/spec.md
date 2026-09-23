Status: ready-for-agent

# Wenyan discourse coherence and decision communication

## Problem Statement

在业务开发前的讨论中，AI 的回答经常出现“每句都能读懂，但整段难以理解”的问题。读者需要自行补足句子之间的因果、条件、转折、比较、时序和范围关系；还需要猜测哪些内容是已确认事实、哪些是推断、哪些是建议、哪些仍待核实。结果是读者难以复述结论、判断证据强度、比较方案代价，也难以知道下一步应做什么。

现有输出风格主要解决句子层面的压缩和格式问题，尚未系统解决篇章层面的连贯性与决策沟通问题，具体表现为：

- 结论、现状、待决项和下一步常埋在长段落或长列表中，读者不能快速建立最小情境模型。
- 相邻句和相邻段落之间的关系没有显式表达，读者必须自己补桥接推论。
- 事实、推断、建议、未知项和范围外内容混在一起，确定性边界不清。
- 关键概念、基础设施、配置、源码、测试和文档之间缺少带语义的可点击导航。
- 裸路径或裸章节引用没有说明“它是什么、与当前结论有什么关系、点击后能看到什么”。
- 多方案比较缺少稳定的共同准则，关键代价、风险、可逆性和跨团队影响容易被遗漏。
- 向用户提问时，弹窗式交互可能遮蔽提问前的研判上下文；即使用户作出选择，选定范围、未选项、下一步和重开条件也可能没有形成完整闭环。
- 输出风格规则与业务正确性、机械授权、文件链接格式之间的职责边界尚未充分显化，容易出现重复约束或把自然语言误当成权限凭据。

这不是单纯的“去 AI 味”或缩短文本问题。成功标准应是读者能建立正确的情境模型、恢复论证关系、判断不确定性、作出知情决策，并在不点击任何链接时理解核心结论；链接和格式只能降低核验成本，不能替代正文解释。

## Solution

扩展 `wenyan-output-style` 的主会话输出规则，使其在保持技术信息完整的前提下，按任务复杂度选择合适的篇章结构：

1. **建立最小情境模型**：复杂说明先交代目标、现状、已证实依据、未知项、约束和下一步；简单问答保持低成本，不机械套用完整模板。
2. **显化篇章关系**：在因果、条件、转折、比较、时序、并列、例证和范围切换处使用足够清楚的连接语或结构，让读者无需自行猜测句段关系。
3. **分离断言类型**：区分已确认事实、基于证据的推断、建议、待核实项和范围外内容；不把推断写成事实，也不把建议写成既定决定。
4. **采用结论前置和渐进披露**：首层提供读者作判断所需的结论、关键依据、代价和边界；次层提供验证坐标、推理细节和背景材料。
5. **提供带信息气味的知识导航**：对承重的文件、源码行、配置、测试、章节和基础设施生成可点击引用时，说明节点角色、与当前论点的关系、点击所得内容；正文仍须自足。具体链接协议和锚点算法继续由现有链接插件负责。
6. **规范决策包**：方案比较使用相同的评估准则；需要用户拍板时，在正文中先呈现起源、现状与期望的差距、影响范围和现场证据，再提出一个边界明确的问题。多个选项使用小写字母编号，每项描述真实代价与影响面，推荐项说明依据。
7. **形成答后闭环**：用户选择后，明确记录选定项、适用范围、未选项、下一步、残余不确定性和重新打开决策的条件。正文决策沟通不改变现有机械授权状态机。
8. **保留白话降级**：安全告警、不可逆操作、复杂多步顺序、用户要求解释和容易因压缩产生歧义的内容使用现代白话；代码、命令、路径、标识符、错误原文和落盘产物不套文言输出风格。
9. **保持职责单一**：`wenyan-output-style` 负责篇章形状和人可理解的呈现；业务正确性、状态核实、并发收口和外部写后回读继续由 `working-discipline` 负责；文件与源码链接继续由 `clickable-paths` 负责；章节引用继续由 `readable-citations` 负责。

## User Stories

1. As a business-development discussion participant, I want the current conclusion, problem, or pending decision to appear early, so that I can establish the situation before reading supporting detail.
2. As a reader, I want the goal, current state, constraints, and next step to be distinguishable, so that I know what the discussion is trying to accomplish.
3. As a reader, I want adjacent sentences to make their causal, conditional, contrasting, comparative, temporal, parallel, or evidentiary relationship clear, so that I do not have to invent the missing bridge between them.
4. As a reader, I want paragraph-level transitions to explain why the next paragraph follows, so that I can recover the global argument rather than reading isolated observations.
5. As a reader, I want facts, inferences, recommendations, unresolved questions, and out-of-scope material to be visibly distinguishable, so that I can judge certainty and authority correctly.
6. As a reader, I want an inference to identify the evidence it depends on and the assumption that connects the evidence to the conclusion, so that I can challenge the reasoning precisely.
7. As a reader, I want unknowns to be stated as unknowns with a verification route where possible, so that uncertainty does not appear to be a settled fact.
8. As a reader, I want the first occurrence of a load-bearing concept to include a concise definition and role, so that later references do not depend on hidden background knowledge.
9. As a reader, I want overloaded technical terms to retain their exact code or product identifier while also receiving a human-readable explanation, so that precision and comprehension are preserved together.
10. As a reader, I want a long explanation to expose the decision-critical layer first and defer background detail, so that I can stop once I have enough information to act.
11. As a reader, I want a short answer to remain short when no complex reasoning is needed, so that the framework does not add ceremony to routine exchanges.
12. As a reader, I want every load-bearing file, source location, configuration, test, or document section to be reachable through a clickable link when the host supports it, so that I can verify the claim without manually searching.
13. As a reader, I want each important link to say what node it points to, what role it plays in the argument, and what I will find after opening it, so that links form a useful knowledge graph instead of a list of opaque paths.
14. As a reader, I want the core explanation to remain understandable when I do not click any link, so that navigation is an aid to verification rather than a hidden dependency.
15. As a reader, I want references to use the existing link and citation capabilities instead of duplicating their protocol or anchor algorithms, so that links remain consistent across plugins.
16. As a decision-maker, I want multiple alternatives compared using the same criteria, so that the recommendation is not determined by which option received the most prose.
17. As a decision-maker, I want each alternative to state benefits, costs, risks, reversibility, prerequisites, and affected parties where relevant, so that I can choose with a realistic view of consequences.
18. As a decision-maker, I want the recommendation to state its basis and the fact that would overturn it, so that I know both why it is preferred and when to revisit it.
19. As a decision-maker, I want a decision request to explain its origin, the gap between current and desired state, its impact range, and the evidence in hand, so that I can decide without reconstructing missing context.
20. As a decision-maker, I want status, identifiers, counts, and timing claims in a decision request to come from the current source of truth or be marked unverified, so that I am not asked to decide from stale workflow information.
21. As a decision-maker, I want the question to be stated in plain language and constrained to one decision boundary, so that I can answer without interpreting compressed jargon.
22. As a decision-maker, I want options to use uniquely addressable lowercase letters and to describe trade-offs rather than merely naming implementation actions, so that I can compare them quickly and unambiguously.
23. As a decision-maker, I want the recommendation to be clearly identified without hiding the cost of choosing it, so that “recommended” does not become a substitute for reasoning.
24. As a decision-maker, I want the decision request to appear in the main conversation rather than an interaction surface that hides its context, so that the evidence and options remain visible while I decide.
25. As a decision-maker, I want the assistant to ask one decision at a time unless several items are inseparable, so that my response cannot be misapplied to a different question.
26. As a decision-maker, I want a post-decision recap to record what I selected, the scope it applies to, what I did not select, and what happens next, so that the decision remains interpretable after the conversation moves on.
27. As a decision-maker, I want residual uncertainty and reopening conditions recorded after my choice, so that future evidence can reopen the decision without guessing the original assumptions.
28. As a user authorizing an irreversible or externally visible action, I want the consequence, target, prerequisites, scope, and authorization boundary stated in plain language, so that I can understand what will happen before approving it.
29. As a user, I want a clarification request to distinguish “need information” from “need authorization,” so that I do not accidentally authorize an action by merely answering a factual question.
30. As a plugin maintainer, I want Markdown, commit messages, subagent prompts, and other persisted artifacts to use clear modern prose rather than the conversational output style, so that machine-consumed material remains precise and searchable.
31. As a plugin maintainer, I want code blocks, commands, paths, filenames, identifiers, error text, URLs, and environment names to remain exact, so that copyable technical material is not damaged by prose transformation.
32. As a plugin maintainer, I want the output rules to avoid duplicating business-discipline rules, so that a future change has one authoritative owner and does not create conflicting instructions.
33. As a plugin maintainer, I want the output rules to avoid treating natural-language approval as a mechanical permission credential, so that a readable decision cannot accidentally bypass a guard.
34. As a plugin maintainer, I want the existing structured authorization state machine to remain unchanged, so that this communication improvement does not silently change the security or branch-write boundary.
35. As a plugin maintainer, I want deterministic hook tests to detect a broken injection contract, so that a style change cannot silently stop reaching the session.
36. As a plugin maintainer, I want tests to exercise the actual hook process and JSON output, so that tests catch shell, protocol, and toggle regressions rather than only checking copied text.
37. As a plugin maintainer, I want behavior-level evaluations to compare the old and new output under the same prompts, so that apparent improvement is not confused with a changed task or model.
38. As a reviewer, I want evaluation criteria to measure conclusion recall, relation recall, certainty separation, trade-off recall, boundary recall, next-step recall, reopening-condition recall, and link information scent, so that “shorter” is not treated as the only definition of clarity.
39. As a reviewer, I want paired outputs presented with randomized order and a genuine-user readability rubric, so that preference for the new version is not caused by knowing which version is newer.
40. As a maintainer working in a long conversation, I want a compact prompt anchor to preserve the key output behavior without repeating the entire framework every turn, so that the rules survive context compression without consuming excessive context.
41. As a maintainer, I want the main session behavior and subagent behavior to remain explicitly separate unless a separate mounting mechanism is added, so that this spec does not promise style coverage where the plugin is not loaded.
42. As a maintainer, I want the root documentation’s rule-count and injection-length drift tracked separately from the core feature, so that documentation cleanup does not obscure whether discourse behavior is complete.

## Implementation Decisions

1. The primary implementation surface is the existing `wenyan-output-style` style rule set. Extend its guidance for discourse coherence, relation signaling, evidence boundaries, semantic navigation, decision packages, and post-decision closure.
2. Keep the existing adaptive structure. Do not force every response through a fixed six-field or long-form template; select the smallest structure that preserves the reasoning needed for the task.
3. Define a “minimum situation model” as the default mental checklist for complex explanations: goal, current state, confirmed evidence, unknowns, constraints, and next step. Treat it as a reasoning aid, not a requirement to print every field every time.
4. Define local coherence as recoverable relationships between nearby statements, and global coherence as a single understandable movement from problem through evidence and decision or action. Require the output to make both visible when the task contains multi-step reasoning.
5. Relationship words that carry cause, condition, contrast, comparison, sequence, or scope are not "redundant words" and are exempt from compression. The existing wenyan compression rules (omit the subject, drop copulas, keep only essential connectives, state each fact once) must be amended so they explicitly yield to relation signaling. A rule that only says "add a connective when omission would be ambiguous" is insufficient, because the existing downgrade clause already says that and the symptom persists. Wenyan compression is itself a candidate cause of the "every sentence is clear, the paragraph is not" symptom; the evaluation includes a no-style arm to test this.
6. Preserve semantic content during compression. Do not remove the object, actor, condition, scope, time order, certainty, or causal direction merely to make prose shorter.
7. Use stable categories for epistemic status: confirmed fact, evidence-based inference, recommendation, unresolved item, and out-of-scope item. The categories are presentation aids and do not replace the existing source-verification discipline.
8. Keep the existing `working-discipline` ownership of factual verification, workflow status checking, four-element review findings, concurrency closure, and external-system write-after-read verification. The output style may present those results clearly but must not redefine their authority.
9. Treat linked references as semantic navigation. A load-bearing reference should identify its node, role, relationship to the current claim, and expected click result when that information is available.
10. Reuse `clickable-paths` for local file and source-line link shape, and reuse `readable-citations` for document-section citation shape. Do not introduce a competing URL scheme, anchor algorithm, or duplicate citation transformer.
11. Keep the body self-sufficient. A link may lower verification cost or provide background, but a reader must be able to understand the core conclusion, evidence boundary, and next action without opening it.
12. Apply progressive disclosure: first show the information needed to decide or act, then expose proof, derivation, implementation detail, and background in subordinate sections or links.
13. For alternatives, use a common comparison frame appropriate to the problem. The frame may include outcome, implementation cost, operational risk, reversibility, dependencies, ownership, and external impact; omit criteria that do not affect the current decision rather than filling empty columns.
14. For decision requests, use the four information elements required by `working-discipline`: origin, current-versus-desired gap, impact range, and evidence. Present them in plain language and retain exact status values, identifiers, counts, and timing only when verified from the current source.
15. Replace the `AskUserQuestion` interaction pattern in the output guidance with an in-conversation decision lifecycle: prepare context, ask a bounded question, receive an addressable answer, then record the decision and its remaining uncertainty. This changes communication behavior, not the host tool protocol. Remove every remaining `AskUserQuestion` instruction from the wenyan style documents (the "or `AskUserQuestion`" clause in the reply-structure section and the whole "AskUserQuestion 与声明句用白话" section of the project overrides); keep the "md audience declaration" part of that section. Do not restate the definition of the four information elements; state the wenyan presentation shape and point to `working-discipline` 3.3 as their owner, so the plugin does not become another copy of the rule.
15a. Decisions whose effect outlives the conversation (they change a spec, a ticket, a file, or a scope boundary) must be recorded in a file in the same round: the `## Comments` section of the affected spec or ticket, or `docs/adr/` for architectural decisions. A recap that exists only in the conversation is lost at compaction.
16. Do not translate free-text phrases such as “允许直写 main” into a structured authorization payload. Natural-language decisions may choose a safe workflow, such as entering a worktree, but they must not bypass the existing main-branch guard.
17. Do not change `worktree-flow`’s structured approval state machine, its source metadata requirements, its round/session binding, or its fail-closed behavior. Replacing that state machine is a separate requirement.
17a. Known conflict that the style rules must handle explicitly rather than silently pick a side: `worktree-flow`'s approval guard accepts only a genuine `AskUserQuestion` UI response as approval for a direct write to the main branch, while a user-level rule may forbid calling `AskUserQuestion`. Under such a rule the direct-write approval is unreachable. The style guidance must say: when a `worktree-flow` main-branch blocker appears, present the situation in the body and default to the worktree path; do not claim that a body answer grants direct-write approval, and do not instruct the model to call `AskUserQuestion` against a user rule that forbids it. Resolving the conflict itself belongs to the user's rule set or to `worktree-flow`, not to this plugin.
18. Keep irreversible-operation confirmations in modern plain language. State target, consequence, scope, prerequisites, and authorization boundary before asking for approval; do not compress away ordering or safety conditions.
19. Keep the existing short `UserPromptSubmit` anchor small. It should point back to the durable output rules and remind the model of the highest-value behavior, not duplicate the complete discourse framework. Injection budget, measured in characters of the injected text: the SessionStart body (header plus both style documents) stays at or below 6400 characters (1.7.0 baseline: 4259 characters for the two style documents); the per-turn anchor stays at or below 300 characters (1.7.0 baseline: 169). Exceeding either requires moving material behind a pointer, not raising the number.
20. Do not add a new hook event for this feature. Both existing hooks are currently bash scripts that run an inline Python heredoc: they hard-code `hookEventName`, cannot read the hook's stdin (the heredoc occupies it), resolve Python with `command -v python3` (which the Windows Store zero-byte stub satisfies), and suppress all errors into silent empty output. They have no environment toggle; the plugin is enabled or disabled only through `/plugin`. Before any rule change, port both hooks to Node.js, invoked as `node ${CLAUDE_PLUGIN_ROOT}/hooks/<name>.js`, following the structure of the `clickable-paths` hook: echo `hook_event_name` from stdin, tolerate empty or malformed stdin by still emitting the injection, and emit byte-identical injected text to the pre-port version. Do not invent an environment toggle.
21. Keep conversational wenyan style separate from persisted artifacts. Code, comments, docstrings, Markdown specs, README text, issue text, commit messages, subagent prompts, and external submissions use modern plain language or their required original language.
22. Preserve exact technical material: code blocks, commands, paths, filenames, identifiers, error messages, URLs, environment names, and commit type keywords remain unchanged.
23. Keep the feature scoped to main-session presentation. `wenyan-output-style` is not mounted for subagents through a `SubagentStart` hook in this change; extending subagent style is a separate decision.
24. If the implementation changes user-visible behavior, increment the plugin version according to repository versioning rules and synchronize the plugin manifest with both marketplace manifests. Do not create a Codex manifest that the plugin does not currently have.
25. Treat the root README’s stale rule-count and injection-length descriptions as a tracked documentation debt or a separate follow-up. They may be corrected as a documentation-only synchronization task, but their correction is not a prerequisite for the discourse behavior itself.
26. Keep implementation decisions at the module and responsibility level. Exact file locations, hook internals, and code snippets remain implementation details for the execution issue and are not part of this specification’s contract.

## Testing Decisions

1. A good test checks externally observable behavior at the highest stable seam. It should not assert internal wording order, helper names, regular-expression structure, or a particular implementation when several outputs satisfy the communication contract.
2. The first test layer is a deterministic regression of the real hook process. Invoke the Node.js hook as a subprocess, provide JSON on standard input, parse the JSON on standard output, and fail with a non-zero exit code when a case does not satisfy the contract.
3. Follow the repository’s existing `spawnSync` plus `cases` test pattern used by the `clickable-paths` hook test. The suite covers: valid protocol output; event echo; empty stdin; malformed stdin; a golden comparison proving the port changed no injected text (golden captured from the bash version before it is removed); and the two character budgets. There is no enable/disable toggle to test.
4. Deterministic hook cases should verify that both durable style documents are injected, the new discourse rules are reachable, the main-session guidance no longer directs the user interaction through `AskUserQuestion`, and the injected output remains within the intended contract. The test must not mistake the presence of a phrase for proof that a model will follow it.
5. Deterministic cases should verify responsibility boundaries: the style rules refer to existing link and citation capabilities rather than cloning their algorithms; natural-language decisions are not described as mechanical authorization; and persisted artifacts are not instructed to use conversational wenyan style.
6. The second test layer is a behavior-level evaluation of real model outputs. Run the same scenario in three arms: baseline (wenyan 1.7.0, git commit `303e719`), new, and no-style (wenyan and every other output-style plugin disabled). Hold the model, entrypoint, prompt, available files, session isolation, and rubric constant.
6a. Run every arm as a separate headless `claude -p` main session (the CLI accepts `--plugin-dir` and `--settings`). Do not use subagents as the evaluation vehicle: wenyan injects only through the main session's SessionStart and UserPromptSubmit, so a subagent receives neither and both arms would silently run without the plugin. Before collecting any output, prove per arm that the injection is present or absent as intended, for example by checking the SessionStart header text in the session's hook output.
6b. The baseline and no-style arms are captured before any rule change lands.
6c. Go/no-go threshold: the new arm must score at least equal to baseline on the rubric mean in at least five of the six core scenarios, lose clearly in none, and pass every hard negative case in every run. Length is recorded but never decides the result. If the no-style arm scores at or above the new arm on relation recall, record it as evidence that wenyan compression is a cause of the symptom; this triggers the reopening condition of the layer decision recorded under Comments.
7. The behavior suite should include at least these scenarios:
   - explaining a cross-file root cause;
   - introducing an unfamiliar infrastructure component;
   - comparing alternatives with known and unknown evidence;
   - presenting a正文 decision package with origin, gap, impact, and evidence;
   - closing a decision after the user selects an option;
   - confirming an irreversible action in plain language;
   - writing Markdown, a commit message, or a subagent prompt where conversational style must not leak into the artifact;
   - preserving the behavior through a long conversation or context compaction;
   - navigating a concept through related files and document sections;
   - handling the absence of `AskUserQuestion` with an in-conversation decision lifecycle.
8. Behavior evaluators should score whether a reader can: restate the conclusion; restate the relationship between key sections; distinguish facts, inferences, recommendations, and unknowns; identify the decisive cost and scope; identify the next step; state what would overturn the recommendation; understand why a link is worth opening; and determine the decision’s remaining uncertainty.
9. Do not use shorter output as the sole success criterion. Record length as an observation, but treat clarity, relation recovery, certainty separation, decision completeness, and actionability as the primary outcomes.
10. Use a genuine-user or reviewer blind comparison where practical. Randomize baseline/new output order, preserve both full outputs, allow ties, and record reasons for preference rather than asking only which output is shorter. This step needs a human reader and is tracked as a separate `ready-for-human` ticket; an agent prepares the blinded packet but does not fill in the preferences.
11. A suggested initial protocol is three runs per scenario for six core scenarios, with hard deterministic claims expected to pass every run. This is an implementation recommendation, not an existing repository-wide testing rule; the executor may adjust the sample after measuring variance and documenting the reason.
12. Keep model-judge scores subordinate to human-readable evidence. If an automated judge is used, retain the rubric, prompt, model and version, and raw paired outputs so that apparent score improvements can be audited for verbosity or position bias.
13. Add regression cases for negative behavior: a short routine answer should not acquire unnecessary ceremony; a link should not replace its surrounding explanation; an inference should not be stated as a fact; a natural-language approval should not be described as permission to bypass a guard; and a persisted artifact should not inherit the conversational style.
14. Run the repository’s existing validation and version consistency checks after implementation. No test should require browser automation, an external tracker write, deployment, or a live production system.

## Out of Scope

- Replacing or redesigning `worktree-flow`’s structured authorization state machine.
- Treating a natural-language answer in the conversation as a machine-verifiable permission to write directly to `main` or another protected branch.
- Adding a new authorization keyword protocol, parser, session token, source metadata format, or guard bypass.
- Moving business correctness rules, status-source verification, four-element review requirements, concurrency closure, or external write-after-read verification out of `working-discipline`.
- Reimplementing local file links, source-line anchors, document-section citations, URL schemes, or citation rendering already owned by `clickable-paths` and `readable-citations`.
- Guaranteeing that all subagent responses use this style when the plugin is not mounted for subagents.
- Changing model capabilities, context-window behavior, compaction internals, or the host’s interaction API.
- Building a general-purpose knowledge graph database, indexing service, backlink engine, or cross-repository documentation crawler.
- Making every sentence or paragraph carry an explicit visible label; the target is recoverable meaning with the least useful structure, not maximal annotation.
- Requiring fixed word counts, paragraph counts, link counts, or a universal six-field response template.
- Treating readability as only a grammar, spelling, “AI flavor,” or output-length problem.
- Publishing issues or specifications to GitHub, GitLab, or another external tracker; this feature is tracked in the repository’s local Markdown tracker.
- Deploying, sending external messages, modifying production systems, or changing shared `di`/`tf` environments.
- Making root README statistics accurate as part of the core behavior change. Any synchronization is a separate documentation task unless implementation chooses to include it without changing the feature contract.
- A style-neutral discourse layer shared by `wenyan-output-style`, `plain-talk-output-style`, and `adhd-output-style`. Considered and rejected for this change; see the decision under Comments. The parallel decision-material rule inside `plain-talk-output-style` is left untouched.
- Editing the user's private global instruction files, including the conflict described in decision 17a.

## Further Notes

- The conceptual basis combines discourse coherence, situation-model construction, common-ground management, cognitive-load reduction, progressive disclosure, information scent, and decision-argument structure. These concepts justify the behavior but do not require a new runtime dependency.
- Relevant industry references include ISO 24495-1:2023 Plain Language, Digital.gov Plain Language, CDC Clear Communication Index, W3C guidance on headings and understandable content, Information Mapping, ASD-STE100 terminology discipline, Toulmin argument structure, and cognitive-fit principles. They are design references, not claims that this plugin implements any standard in full.
- The principal seam is the existing SessionStart JSON output. A second seam is necessary because static hook assertions cannot establish whether a model’s prose is actually easier to understand; the baseline/new behavior evaluation supplies that evidence.
- Evaluation prompts should contain realistic ambiguity and cross-file reasoning rather than isolated grammar exercises. A response that is merely shorter, more heavily labeled, or more verbose should not automatically pass.
- Link quality should be judged by information scent and relation clarity: a useful reference tells the reader why to click and what the click will confirm or expand. Too many links can create disorientation, so links should be reserved for load-bearing or genuinely useful context.
- The implementation should preserve the current user preference that real decision questions appear in the response body with full context before the question. The question itself should be plain language, bounded, and addressable; the surrounding output should not hide the evidence needed to answer it.
- When a decision changes a previously written decision record, the existing stale-reference discipline still applies: the superseded written basis needs an explicit override marker in the same round, and later references must use the new effective basis.
- When a response cites a file after modifying it in the same round, line coordinates must be reacquired after the edit. The new navigation behavior does not relax this requirement.
- This spec is ready for an implementation agent. The implementation agent should create focused issues if the work is split, preserve the responsibility boundaries above, and report any conflict with an existing ADR before changing the affected behavior.
- Every ticket that writes under `plugins/**` triggers the repository rule in `CLAUDE.md`: read the `mattpocock-skills:writing-for-agents` and `skill-creator:skill-creator` skills with real `Skill` calls before the first edit.

## Comments

### 2026-09-23 · Decision: where the discourse rules live

- Selected: option a — the discourse-coherence and decision-lifecycle rules live only in `wenyan-output-style`, as this spec originally scoped.
- Scope: this spec and its tickets.
- Not selected: b — a new style-neutral discourse plugin referenced by every output style; c — placing the rules in `working-discipline` chapter 3, whose sections 3.1/3.2 are intentionally left to output-style plugins.
- Accepted residual: switching to `plain-talk-output-style` or `adhd-output-style` drops these rules; `plain-talk-output-style` keeps its own parallel decision-material rule, so two wordings coexist.
- Reopening condition: the evaluation's no-style arm scores at or above the new arm on relation recall (testing decision 6c), or the user adopts another output style as the default.

### 2026-09-23 · Review revision

A second review found: compression rules conflict with relation signaling (decision 5); the evaluation vehicle must be headless main sessions, not subagents (6a); the hook-test targets described behavior the bash hooks do not have (decision 20, testing 3); the `worktree-flow` approval conflict needed explicit handling (17a); decisions needed file persistence (15a); the injection budget was unfalsifiable (19); tickets were layered rather than vertical and lacked a pre-change baseline. The spec above incorporates these; the tickets were re-cut into seven.

### 2026-09-23 · 重开条件已触发（待用户决定如何处置）

05 号票的评测结果：在六个核心场景上合并计算，no-style 组的 relation_recall 为 3.81，new 组为 3.56，满足上面「Reopening condition」的第一条。选项 a 目前尚未被推翻，只是进入重新讨论。6c 总判定为不通过。详见 `eval/report.md`。

### 2026-09-23 · 层级决策改判：纪律条款迁入 working-discipline

- **触发**：上面那条重开条件已经触发；另外用户准备停用 `wenyan-output-style`，用户原话「先继续完成后续的改造优化，然后把那几部分挪到 working-discipline中 为后面的关闭wenyan插件做准备」。
- **选定**：部分改走原先未选的 c 方向，只迁纪律性条目。
  - 答后闭环与「正文答复不是机械授权」→ `working-discipline` 3.8
  - 承重概念与链接信息气味 → 3.9
  - 五类断言分层 → 并入 3.4
  - 以上从 `working-discipline` 3.32.0 起生效。
- **未迁**：
  - 拍板提问的具体形状（Q 标题、小写字母选项、四要素具名小标题）仍归风格侧。
  - 关系词不删、落盘产出物用白话、不可逆确认用白话，这三条专门对付文言压缩，停用 wenyan 后没有对象。
  - 「先立情境」「关系可读」「结论前置」这几条篇章条款也没迁，因为评测里不开风格插件的对照组关系回忆最高（3.81）。
- **适用范围**：本 spec 与其票。原选项 a 的残余「切到其他风格插件就丢规则」对已迁的条目不再成立。
- **重开条件**：停用 wenyan 之后，如果观察到 3.8 / 3.9 没被遵守，或篇章可读性明显退化，再议是否补篇章条款。
