---
name: multi-plugin
tags: [multi]
plugins: ["../../devkit-discipline", "../../devkit-clickable-paths"]
max_turns: 6
timeout_seconds: 240
allowed_tools: [Read, Glob, Grep]
---
当前目录的 notes.md 里哪一行写了 TODO？告诉我文件和行号。
