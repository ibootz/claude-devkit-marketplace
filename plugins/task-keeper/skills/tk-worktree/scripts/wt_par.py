#!/usr/bin/env python3
"""wt_par.py —— 批量 `init` 的并发底座：输出收集、按源仓互斥、线程池调度。

为什么单独一个文件
------------------
批量 `init --ids A,B,C` 要同时解决三件与 git 语义无关的事：多个 id 共享 stdout 时
不能交错、多个 id 抢同一个源仓的 refs 时要有进程内互斥、以及线程池调度本身。
这三件都是**纯并发机制**，与 `wt_git.py`（问 git 要事实）和 `wt_levels.py`
（层级供给判据）都不同类，故拆成一个只依赖标准库的叶子模块——它不 import 任何
`wt_*`，因此不可能参与循环 import。

为什么用线程不用进程
--------------------
本工具的每个任务几乎全是 `subprocess.run` 等 git 退出，是 I/O 密集型，GIL 在
`subprocess.run` 阻塞期间是释放的，多线程能真正并行。用 `multiprocessing` 反而要把
输出收集、`Fail` 异常、以及下面这个「按源仓 realpath 的互斥锁」全部跨进程序列化——
而进程间共享不了 `threading.Lock`，就得退化成文件锁，复杂度陡增且没有收益。
"""

from __future__ import annotations

import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# ---------------------------------------------------------------- 输出收集

_tl = threading.local()
_stdout_lock = threading.Lock()


class Sink:
    """一个 id 的输出缓冲区。`tag` 为 None 时 flush 不加前缀。"""

    def __init__(self, tag: str | None):
        self.tag = tag
        self.lines: list[str] = []


def emit(msg: str = "") -> None:
    """打印一行。

    当前线程装了 sink（`attach()`）就先攒着、由 `flush()` 统一吐出；没装就直接
    `print`——单 id 路径与 `status` / `remove` / `merge-back` 因此行为完全不变，
    不需要为并行化改动那几条链路。
    """
    sink = getattr(_tl, "sink", None)
    if sink is None:
        print(msg)
    else:
        sink.lines.append(msg)


def attach(tag: str | None) -> Sink:
    sink = Sink(tag)
    _tl.sink = sink
    return sink


def detach() -> None:
    _tl.sink = None


def flush(sink: Sink) -> None:
    """把一个 id 的全部输出作为**连续一段**吐出，每行带 `[<id>] ` 前缀。

    为什么选「按 id 分组缓冲」而不是「实时打印 + 每行加前缀」：本工具的逐层输出靠
    缩进表达嵌套深度（`Level.label` / `supply_level` 的 `indent`），实时交错时缩进
    仍在、但相邻两行可能属于不同的 id，树形结构被打散、人和 AI 都要靠前缀逐行重排
    才能读。分组后每个 id 是一整块连续文本，树形完好；前缀照旧逐行加，用来对抗
    「stderr 与 stdout 交错」这种缓冲管不到的情况。
    代价是一个 id 跑完才见到它的输出——批量场景的调用方是 subagent、不是盯屏的人，
    这个延迟没有成本。
    """
    with _stdout_lock:
        for entry in sink.lines:
            # 一条 emit 可能自带内嵌 `\n`（正文里有 `emit(f"\\n  ...")` 这种写法），
            # 必须拆成物理行后逐行加前缀，否则只有第一行带前缀、后续行看起来像别的
            # id 的输出。
            for line in (entry.split("\n") if entry else [""]):
                print(f"[{sink.tag}] {line}".rstrip() if sink.tag else line)
        sys.stdout.flush()


def say(msg: str = "") -> None:
    """绕过 sink、直接打到 stdout（批量层的汇总行用它，不进任何 id 的缓冲）。"""
    with _stdout_lock:
        print(msg)
        sys.stdout.flush()


# ---------------------------------------------------------------- 按源仓互斥

_locks_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}


def repo_lock(repo) -> threading.Lock:
    """取「这个源仓路径」专属的进程内互斥锁（按 realpath 做 key）。

    用途见 `wt_levels.supply_level`：`pick_branch()` 是 check-then-act
    （先 `branch_exists` / `branch_in_use` 判可用、再建分支），两个并行 id 可能同时
    判到「可用」，后者撞 `already exists`。并行任务全在同一个 Python 进程内，
    `threading.Lock` 就够，不需要文件锁。
    """
    key = str(Path(repo).resolve())
    with _locks_guard:
        lk = _locks.get(key)
        if lk is None:
            lk = threading.Lock()
            _locks[key] = lk
        return lk


# ---------------------------------------------------------------- 调度

def run_parallel(items: list, worker, jobs: int) -> list:
    """并发跑 worker(item)，按 **items 的原始顺序** 返回 [result]。

    `jobs <= 1` 时压根不建线程池、直接串行 for 循环——这样 `--jobs 1` 的行为与并行
    实现无关，可以用它把「是并行引入的问题还是本来就有的问题」一刀切开。
    worker 必须自己吃掉业务异常并把失败编码进返回值；这里只让 `KeyboardInterrupt`
    这类 BaseException 往上冒。
    """
    if jobs <= 1:
        return [worker(it) for it in items]
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = [pool.submit(worker, it) for it in items]
        return [f.result() for f in futures]
