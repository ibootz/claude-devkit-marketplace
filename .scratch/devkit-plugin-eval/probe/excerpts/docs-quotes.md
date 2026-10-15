# 官方文档原文摘录（2026-10-15 抓取）

由 claude-code-guide 子代理抓取 code.claude.com 全文后摘录，英文原文照抄。

## cleanupPeriodDays

https://code.claude.com/docs/en/settings-reference#cleanupperioddays

> Set how many days Claude Code keeps session transcripts and other application data before deleting them. Claude Code runs the deletion as a background sweep after a session starts, as long as it can safely determine the retention period. The sweep deletes transcripts without showing a message, so a session you haven't used for longer than the retention period no longer appears in the `/resume` picker.
> * **Type**: number of days, a whole number, minimum `1`
> * **Default**: `30`
>
> Setting `0` fails validation, so pick a large value such as `3650` for long retention.

https://code.claude.com/docs/en/claude-directory#cleaned-up-automatically

> Claude Code deletes the files in the paths below once they're older than `cleanupPeriodDays`, as long as it can safely determine the retention period. The default is 30 days and the minimum is 1; setting `0` fails with a validation error.

该表包括 `projects/<project>/<session>.jsonl`（完整会话转录）、`projects/<project>/<session>/subagents/`、`projects/<project>/<session>/tool-results/` 等。

## CLAUDE_PLUGIN_DATA 与 Bash 工具

https://code.claude.com/docs/en/plugins/manifest-reference#environment-variables（Where each variable resolves）

> | Skill, command, and agent content | Anywhere in the Markdown body | Not applicable |
>
> The variables aren't present in the environment of commands Claude runs through the Bash tool, in the main session or in a subagent. In skill, command, and agent content, write the `${...}` reference in the Markdown body instead, and Claude Code substitutes the path inline when it loads the content.

https://code.claude.com/docs/en/skills#available-string-substitutions

> In a plugin skill, Claude Code substitutes `${CLAUDE_PLUGIN_ROOT}` and `${CLAUDE_PLUGIN_DATA}` in the same two places.（同两处 = skill 的 markdown 正文，与 frontmatter `allowed-tools` 里的 Bash 规则）

https://code.claude.com/docs/en/plugins/components#path-variables-and-persistent-data

> It resolves to `~/.claude/plugins/data/<id>/` and is created when first referenced
>
> In the data directory path, `<id>` is the plugin identifier with every character other than letters, digits, `_`, and `-` replaced by `-`, so `my-plugin@my-marketplace` becomes `my-plugin-my-marketplace`.

https://code.claude.com/docs/en/plugins/loading#find-where-a-plugin-came-from

> `@inline` | You started Claude Code with `--plugin-dir` or `--plugin-url` ...
