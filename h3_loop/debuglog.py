"""调试日志开关：默认静默，只在排查时打开。

背景：分段生成时潜桥/接缝/修色等明细会逐段打印，控制台噪声很大。
现在这些明细统一走 debug()，默认不输出；需要排查时：

- 设置环境变量 `ADSEG_DEBUG=1` 后启动 ComfyUI；或
- 用 ComfyUI 自带的 `--verbose` 启动。

真正的失败与警告（迁移失败、缓存清理失败、最终保存结果等）仍直接打印，
避免“干净”把问题也一起藏掉。

注：dialogs.py 的 print 是它与父进程之间的 JSON 协议，不属于日志，不能改。
"""
from __future__ import annotations

import os

_OFF = {"", "0", "false", "off", "no"}
_verbose_cache = None


def _comfy_verbose():
    """ComfyUI 启动参数 --verbose；导入失败（测试环境）时视为关闭。"""
    global _verbose_cache
    if _verbose_cache is None:
        try:
            from comfy.cli_args import args
            _verbose_cache = bool(getattr(args, "verbose", False))
        except Exception:
            _verbose_cache = False
    return _verbose_cache


def enabled():
    value = os.environ.get("ADSEG_DEBUG")
    if value is not None and value.strip().lower() not in _OFF:
        return True
    return _comfy_verbose()


def debug(*args, **kwargs):
    """分段/潜桥/接缝等明细：默认不打印，ADSEG_DEBUG=1 或 --verbose 时输出。"""
    if enabled():
        print(*args, **kwargs)
