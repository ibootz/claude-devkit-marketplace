#!/usr/bin/env python3
"""提交队列前的机械校验：暂存区里有没有新增的野生 gitlink。

## 为什么需要它

v4 队列文本入库，keeper 每个窗口结束会跑一次 `git add -A && git commit`。而 fixer
的 worktree 就嵌在队列目录里（`.keeper/<交付id>/debug/DBG-NNN/worktree/`）——
`.gitignore` 里那条 `.keeper/**/worktree/` 一旦缺失或写错，`git add -A` 不会报错、
只会打一行 warning 就把整个 worktree 种成一条 **gitlink**（mode `160000`，值是
子仓某次提交的 SHA）。实测：

    $ git add -A -n
    warning: adding embedded git repository: .keeper/D-001-x/debug/DBG-001/worktree

warning 会淹没在 `git add -A` 的输出里，而后果延迟到很久之后才爆：宿主是聚合仓
（真有 submodule）时，`wt_supply.merge_into` 的冲突白名单判据是「冲突文件是否
⊆ 本仓 `.gitmodules` 声明的 submodule 路径」，多出来一条不在 `.gitmodules` 里的
野生 gitlink 会让**整个 merge-back 被判定为不可自动处理**，而报错文本指向的是
merge 冲突，完全看不出根因在几十次提交之前的一次 `git add -A`。

## 判据

`git diff --cached --diff-filter=A --raw` 的每行形如：

    :000000 160000 0000000... a1b2c3d... A	path/to/thing

第二个字段是新增对象的 mode，`160000` 就是 gitlink。这是 git 自己输出的确定字段，
不需要理解语义，也没有假阳性——**只有真的是 gitlink 才会是这个 mode**。

`--diff-filter=A` 只看新增：已经在 `.gitmodules` 里登记、历史上就存在的 submodule
每次 gitlink 更新是 `M` 不是 `A`，不会被这里命中。所以「已声明的 submodule」与
「野生嵌套 worktree」被 git 自己分开了，本脚本不需要读 `.gitmodules` 去对账。

## 为什么不做成 hook

按本仓 `.claude/rules/hook-restraint.md` 的强度阶梯，判据机械≠就该做成拦截。要在
`PreToolUse(Bash)` 上拦，得先判断「这条命令是不是 git commit」——那是对整条命令
字符串做形态匹配，`git commit` 可以写成 `git -C x commit`、`git commit -m "..."`、
被 `&&` 串在中间、出现在 heredoc 正文里……误报与漏报都跑不掉，而这条脚本的价值
不依赖于「一次都不漏」。所以它是 keeper 提交流程里的一个显式步骤，不是闸门。

## 用法

    python3 check_staged_gitlink.py [--repo <path>]

exit 0 = 干净；exit 2 = 检出野生 gitlink（打印路径与修复命令）。
"""
import argparse
import os
import subprocess
import sys

GITLINK_MODE = "160000"


def main():
    ap = argparse.ArgumentParser(description="检查暂存区是否新增了野生 gitlink")
    ap.add_argument("--repo", default=".", help="仓库路径（默认当前目录）")
    args = ap.parse_args()
    repo = os.path.abspath(args.repo)

    try:
        proc = subprocess.run(
            ["git", "-C", repo, "diff", "--cached", "--diff-filter=A", "--raw"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    except Exception as e:
        sys.exit("无法执行 git diff：%s" % e)
    if proc.returncode != 0:
        sys.exit("git diff 失败（exit %d）：%s"
                 % (proc.returncode, proc.stderr.decode("utf-8", "replace").strip()))

    hits = []
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        if not line.startswith(":"):
            continue
        # :<旧mode> <新mode> <旧sha> <新sha> <状态>\t<路径>
        head, _tab, path = line.partition("\t")
        fields = head.split()
        if len(fields) >= 2 and fields[1] == GITLINK_MODE:
            hits.append(path)

    if not hits:
        print("✓ 暂存区没有新增 gitlink（检查了 %s）" % repo)
        return 0

    print("✗ 暂存区新增了 %d 条 gitlink（mode %s），几乎可以肯定是嵌套 worktree "
          "被 `git add -A` 误收：" % (len(hits), GITLINK_MODE))
    for p in hits:
        print("    %s" % p)
    print("\n修复（逐条撤出暂存区，再补 .gitignore 规则）：")
    for p in hits:
        print("    git -C %s rm --cached -r --quiet -- %s" % (repo, p))
    print("    # 确认 .gitignore 里有这三行（判据 6）：")
    print("    #   .keeper/**/worktree/")
    print("    #   .keeper/**/*.png")
    print("    #   .keeper/**/*.jpg")
    print("    # 改完重跑本脚本回读验证，不要凭 `git add` 没报错就认为好了")
    return 2


if __name__ == "__main__":
    sys.exit(main())
