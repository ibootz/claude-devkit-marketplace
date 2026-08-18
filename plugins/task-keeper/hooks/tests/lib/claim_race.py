#!/usr/bin/env python3
"""并发认领编号的压测驱动（H30 用）：起 N 个真实进程同时调 `queue_files.claim_id`。

用法：`/usr/bin/python3 claim_race.py <lib目录> <队列目录> <并发数>`
输出：每行一个被认领的编号，顺序不定；调用方自己去重计数。

## 为什么必须是真实进程，不能用线程

要验的是 `os.mkdir` 的原子性——那是**内核**对同一目录项的互斥保证。Python 线程共享
一个进程的文件系统视图，且 GIL 会让两个 `os.mkdir` 事实上串行，跑绿了也证明不了
多实例场景（每个 keeper 实例是一个独立的 `Bash` 子进程）下的正确性。

## 为什么要一个起跑线文件

直接 fork 出来就各自开跑的话，先 fork 的那个往往在后一个起来之前就已经认领完了——
竞态窗口根本没被打开，用例会稳定通过而什么都没验到（这是并发测试最典型的假绿）。
所以每个子进程先自旋等一个共同的起跑标记，父进程把 N 个都 fork 完再落下标记，
让它们尽量挤在同一瞬间进入 `claim_id`。
"""
import os
import sys

sys.path.insert(0, sys.argv[1])

from queue_files import DEBUG, claim_id            # noqa: E402

QDIR = sys.argv[2]
N = int(sys.argv[3])
OUTDIR = QDIR + ".race-out"
START = OUTDIR + "/GO"

os.makedirs(OUTDIR, exist_ok=True)

pids = []
for i in range(N):
    pid = os.fork()
    if pid == 0:
        # 子进程：自旋等起跑标记，然后立刻认领。
        while not os.path.exists(START):
            pass
        iid, _d = claim_id(QDIR, DEBUG, summary="并发认领压测 #%d" % i)
        with open(os.path.join(OUTDIR, "r%d" % i), "w") as f:
            f.write(str(iid or "NONE"))
        os._exit(0)
    pids.append(pid)

with open(START, "w") as f:
    f.write("go")

for pid in pids:
    os.waitpid(pid, 0)

for i in range(N):
    path = os.path.join(OUTDIR, "r%d" % i)
    try:
        with open(path) as f:
            print(f.read().strip())
    except Exception:
        print("MISSING")
