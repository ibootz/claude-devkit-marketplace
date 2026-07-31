---
name: deps-investigator
description: "查看/读取第三方依赖（Maven jar、node_modules）源码，定位版本差异或第三方行为导致的 bug；不分析本仓库自有代码。区别于 key-module-analysis（只分析本仓库自有模块）。"
when_to_use: |
  用户需要"看依赖源码"、"查第三方库实现"、"读 jar 包源码"、"看 node_modules 代码"、"查依赖版本差异"、"排查第三方库行为"、"定位依赖中的 bug"、"查某个类的实现"。
---

# Deps Investigator Skill（依赖源码读取）

## 你要做什么

当根因可能在"依赖代码/版本差异/第三方行为"时，用脚本从本地 Maven 仓库（m2）或 node_modules 读取依赖源码，建立证据链：

- 读到对应类/文件源码
- 确认版本与行为差异（尤其是边界条件/异常处理）
- 反向提示主仓库需要检索的调用点（关键方法名/异常信息）

## 运行本 Skill 脚本

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/deps-investigator/scripts/deps_investigator.py" \
  java --group-id org.example --artifact-id example-lib --version 1.2.3 --class-fqn org.example.Foo

python "${CLAUDE_PLUGIN_ROOT}/skills/deps-investigator/scripts/deps_investigator.py" \
  node --package-name lodash --file-path fp/map.js --project-root .
```

## 输出要求（给主 agent 的最小有效信息）

- 必须包含：坐标/包名、版本、关键方法/条件分支位置
- 代码片段只保留：与结论直接相关的 20-80 行，并给出可检索的关键符号名
- 明确：是否需要进一步查看同包内其它类/资源文件（例如配置、SPI、默认值）

## 参考

- `references/configuration.md`：配置项
- `scripts/deps_investigator.py`：脚本实现
