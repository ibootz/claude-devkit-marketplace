---
name: n2-unit-test-fail
tags: [skill-trigger]
max_turns: 10
timeout_seconds: 240
allowed_tools: [Skill, Read, Glob, Grep]
---
devkit-discipline 的 hooks/tests/bash-guard.test.js 跑挂了，node 报 AssertionError，帮我看看是哪里写错了。
