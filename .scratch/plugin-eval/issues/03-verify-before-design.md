# 03: 先验证还是先设计

Type: grilling
Status: resolved
Blocked by: 01

## Question

`claude plugin eval` 覆盖不到的缺口有多大，目前只是读文档推断出来的。是先花一小步实测它，还是直接按「它做底座、自建补缺口」出设计，还是先只做它肯定不管的真实会话事后分析？

## Answer

**先实测**（2026-10-14 用户选 a）。

拿 devkit-discipline 写 2～3 个用例跑一次 `claude plugin eval`，重点看 hook 注入的效果能不能被判分。跑完再定自建多少。实测立为 [05](05-probe-plugin-eval-on-hook-injection.md)。

未选：b 直接出设计（缺口大小靠推断）、c 先只做真实会话事后分析（范围归 [06](06-scope.md) 决定）。

## Comments
