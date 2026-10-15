---
name: env-probe
description: 探针 skill。用户说「调用 env-probe」时使用：执行一条 Python 命令并把输出原样贴回。
---

# env-probe

用 Bash 工具原样执行下面这一条命令，一个字符都不要改（包括单引号与双引号），然后把命令的完整输出原样贴给用户，不加解释：

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/probe.py" --dq-data "${CLAUDE_PLUGIN_DATA}" --sq-data '${CLAUDE_PLUGIN_DATA}' --dq-root "${CLAUDE_PLUGIN_ROOT}" --sq-root '${CLAUDE_PLUGIN_ROOT}'
```
