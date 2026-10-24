# 来源与依据强度

本 skill 的规则来自 2026-10-23 至 10-24 的两轮调研：一轮 deep-research（19 个来源、94 条论断、核实 25 条，21 条通过）加一轮定点补查（配图、解释类、分析报告类）。2026-10-24 由子代理逐个打开下表原页复核过一遍（取的是 WebFetch 摘要，不是逐字原文），按复核结果修正了出处页与强度。

**依据强度三档**：
- **【有出处】**：一手资料原文支持。标「二手」的是转述来源。
- **【推断】**：由几条来源合起来推出，规则旁写了所依来源。
- **【判断】**：经验看法，无来源支撑；在两份样板文档（AI 基础设施全景图 v2、人发 AI 混部前整备导读）上用过一次，未做对照实验。

---

## 一手来源

| 来源 | 支撑的规则 | 原文要点 | 约束强度 |
|---|---|---|---|
| [Diátaxis · Compass](https://diataxis.fr/compass/) | 四类划分 | 两个问题：*action or cognition?*、*acquisition or application?* | 方法论 |
| [Diátaxis · How to use](https://diataxis.fr/how-to-use-diataxis/) | 不先搭四类空目录 | 不应为四类先建空结构；起步不需要先把文档分成四部分 | 作者建议，非规则 |
| [Diátaxis · Explanation](https://diataxis.fr/explanation/) | 解释类原则 | make connections；provide context；talk *about* the subject；admit opinion；keep explanation closely bounded | 方法论 |
| [Diátaxis · Tutorials](https://diataxis.fr/tutorials/) | 教程原则 | 先说会做出什么；每步有可见结果；少解释；不讲替代做法；每次都要能成功 | 方法论 |
| [Kubernetes · Page content types](https://kubernetes.io/docs/contribute/style/page-content-types/) | 教程、操作指南骨架 | Task：overview / prerequisites / steps / discussion / whatsnext；Tutorial 多 objectives、lessoncontent、cleanup | 原文未写 must / should |
| [OpenStack · API reference guideline](https://docs.openstack.org/placement/2025.2/contributor/api-ref-guideline.html) | API 参考骨架 | 每接口依次写方法 URL、描述、状态码、请求、响应；按 HTTP 方法排序 | 单个项目惯例 |
| [Rust API Guidelines · Documentation](https://rust-lang.github.io/api-guidelines/documentation.html) | 示例讲为什么；失败情况小节 | C-EXAMPLE；C-FAILURE 的 Errors / Panics / Safety | should 级，不是 must |
| [Rust RFC 模板](https://github.com/rust-lang/rfcs/blob/master/0000-template.md) | 设计文档骨架；反方必写 | Summary → Motivation（*one of the most important sections*）→ Guide-level → Reference-level → Drawbacks → Rationale and alternatives → Prior art → Unresolved questions → Future possibilities | 模板；[RubyGems](https://github.com/rubygems/rfcs/blob/master/0000-template.md) 沿用，[Unkey](https://engineering.unkey.com/architecture/rfcs/0000-template) 精简版（10-24 复核时 Unkey 页未能打开） |
| [Standard Readme](https://github.com/RichardLitt/standard-readme/blob/main/spec.md) | README 章节顺序 | 标题、简述、目录、安装、用法、贡献、许可证（放最后） | must 级顺序 |
| [GitHub · About READMEs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes) | README 回答五问 | README 通常包含：做什么、为什么有用、怎么上手、去哪求助、谁在维护；更长的文档适合放 wiki | 官方描述，非要求 |
| [Google Technical Writing · Illustrating](https://developers.google.com/tech-writing/two/illustrations) | 图注先行；一图一段；先全景后子系统；标注 | *write the caption first*（*often helpful*）；一张图的信息量不超过一段文字，或解释它不需要超过五条要点；先全景再分别画子系统；callouts 引注意力 | 课程建议；「方框 ≤7」「图注放图前」不在原文，是本 skill 的判断 |
| [Google Technical Writing · Audience](https://developers.google.com/tech-writing/one/audience) | 知识的诅咒 | *Experts often suffer from the curse of knowledge* | 课程建议 |
| [Google Technical Writing · Words](https://developers.google.com/tech-writing/one/words) | 术语先定义后使用 | 文档引入术语时先定义；生僻缩写首次出现时写全称 | 课程建议 |
| [C4 · System context](https://c4model.com/diagrams/system-context) 与 [review checklist](https://c4model.com/diagrams/checklist) | 选图；标题、图例、箭头标注 | 系统上下文图的受众：*everybody, both technical and non-technical*；清单问：有标题吗、有图例吗、每条箭头都标了关系意图吗 | 审查清单（Yes/No 问句） |
| [DORA · Documentation quality](https://dora.dev/capabilities/documentation-quality/) 与 [2022 问卷](https://dora.dev/research/2022/questions/) | 更正改回原处（推断）；试读问卷 | 8 项：可靠、易懂、容易找到、大部分代码有文档、组织得好、随变更及时更新、准确反映能力与要求、遇到问题会去查 | 问卷指标。「问卷横断面只能说明相关」是本 skill 的判断，DORA 页面没有这句 |

## 二手与缺口

- **Mayer 多媒体学习原则**（多媒体、去冗余、信号、就近、分段、预训练）：来自二手博客转述，原书为 Richard Mayer《Multimedia Learning》，未读原书。
- **Minto 金字塔 / BLUF**：只部分有出处——BLUF 的 army.mil 与 Wikipedia 页面抓取失败，Minto 官网页面 404。「结论先行」本身是业界共识，「并列结论超过 5 条要分组」是推断。
- **未覆盖**：能落到单篇文档上、可客观测量的判据（链接失效率、示例能否运行、文档与代码版本是否一致）；DORA 2023 年后的测量方式变化。

---

## 用 DORA 8 项做试读问卷【判断】

请一位对项目零上下文的人读完后，按 1 到 5 分评下面 8 句，并复述全景图。复述不出来的地方、低于 3 分的项，就是要改的地方。

1. 这份文档我信得过。
2. 我读得懂。
3. 我要找的内容找得到。
4. 它覆盖了我关心的部分。
5. 它组织得好。
6. 它是最新的。
7. 它是准确的。
8. 出了问题我会来查它。
