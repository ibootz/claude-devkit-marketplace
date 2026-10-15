# 单测声明共用样例

`unit-tests.json`（单测声明）有两套实现各自解析：本仓 pre-commit 用的 `scripts/run-unit-tests.js`，与 `devkit-plugin-eval` 闸门检查命令里的 Python 实现。本目录是两边共用的判定样例，两边对每个样例给出的结论必须一致。

每个子目录相当于一个插件根：里面的 `unit-tests.json` 是被测声明（`undeclared` 故意没有），`ok.js` 等是声明要跑的小脚本，`expected.json` 是 JS 实现的判定结果。

## expected.json

```json
{
  "platform": "linux",
  "declaration": "ok",
  "errors": [],
  "tests": [{ "index": 0, "status": "skipped-platform" }, { "index": 1, "status": "passed" }],
  "precommit": "pass"
}
```

- `platform`：判定时假定的当前平台，只影响 `platforms` 过滤。Python 实现必须同样能覆盖平台，否则 `platform-skip` 在不同机器上结论不同。
- `declaration`：`undeclared` / `invalid` / `ok`。
- `errors`：声明不合法时的错误码，去重后按字典序排列。码表：`not-json`、`not-object`、`unknown-field`、`bad-tests`、`bad-test`、`bad-run`、`bad-timeout`、`bad-platforms`。错误码之外的提示文字两边各写各的，不比对。
- `tests[].status`：`passed` / `failed` / `timeout` / `skipped-platform` / `interpreter-missing`。声明不合法时为空数组。
- `precommit`：pre-commit 口径的结论，`pass` 或 `block`。闸门检查命令口径不同（未声明要提示、解释器缺失判失败），由 Python 实现按 `declaration` 与 `tests[].status` 自行推出，不另存。

## 两个容易在 Python 里判错的样例

- `invalid-nan`：`json.loads` 默认接受 `NaN`，JS 的 `JSON.parse` 不接受。期望是 `not-json`，Python 要传 `parse_constant` 拒掉 `NaN` / `Infinity` / `-Infinity`。
- `invalid-timeout-bool`：Python 的 `bool` 是 `int` 的子类，`isinstance(True, (int, float))` 为真。期望是 `bad-timeout`，要先排除 `bool`。

## 前提与更新

- 样例脚本用 `node` 跑，`python3-resolve` 另要一个能用的 Python；缺了会判成 `interpreter-missing`，与期望不符。
- 改判定规则时：先改 `scripts/run-unit-tests.js`，再跑 `node scripts/tests/run-unit-tests.test.js --update` 重写各 `expected.json`，并同步 Python 实现。只跑对齐不加 `--update`。
