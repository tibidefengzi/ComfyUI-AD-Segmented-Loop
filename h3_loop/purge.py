"""彻底重置当前工作流会话（2026-11-09 用户确认的 A 范围）。

只清“当前工作流任务”的生成数据，永久删除、不放回收站：

- 删除：会话进度/历史组/执行轮快照、试跑（抽卡）子会话、本会话结果文件
  （segment_*.mp4、尾帧/音频 npy、合并中间文件等）、本会话潜桥 stage 目录；
- 保留：素材、时间线分段、提示词、参考图、节点参数；input 源素材；
  导出成品目录（output/AD-Segmented-Loop-output、AD-Segmented-Loop-final）；
  其它工作流的会话。

`plan()` 只读统计供前端确认弹窗展示；`purge()` 执行删除并写回全新状态。
"""
from __future__ import annotations

import copy
import json
import shutil
import uuid
from pathlib import Path

from . import layout
from .storage import STORE, identifier

# 需要从会话状态里清掉的结果/临时键；素材与设置键（template、max_frames 等）保留。
_TRANSIENT_KEYS = (
    "execution_round", "resume_round", "draft_trial", "preview_hold", "sequential_stop",
    "run_return", "affected_run", "run_origins", "draft_candidates", "trial_notice",
    "retired_segments", "merged", "manifest",
)


def relay_root() -> Path | None:
    """潜桥 stage 根目录（output/relay_kit）；非 ComfyUI 环境下返回 None。"""
    base = layout.output_base()
    return None if base is None else base / "relay_kit"


def relay_directories(session_id: str) -> list[Path]:
    """本会话的潜桥链目录：output/relay_kit/ad_<会话>_*（含 _v* 子目录与旧版遗留）。"""
    root = relay_root()
    if root is None or not root.is_dir():
        return []
    prefix = "ad_%s_" % str(session_id)
    try:
        children = list(root.iterdir())
    except OSError:
        return []
    directories = []
    for child in children:
        try:
            if child.is_dir() and not child.is_symlink() and child.name.startswith(prefix):
                directories.append(child)
        except OSError:
            continue
    return directories


def _walk_files(directory: Path):
    if not directory.is_dir():
        return
    try:
        entries = list(directory.rglob("*"))
    except OSError:
        return
    for path in entries:
        try:
            if path.is_symlink() or not path.is_file():
                continue
        except OSError:
            continue
        yield path


def _dir_usage(directory: Path) -> tuple[int, int]:
    files = total = 0
    for path in _walk_files(directory):
        try:
            info = path.stat()
        except OSError:
            continue
        files += 1
        total += info.st_size
    return files, total


def _child_sessions(state: dict) -> set[str]:
    """抽卡试跑子会话 id；只接受合法进度名，避免误删目录。"""
    ids: set[str] = set()
    parent = str(state.get("id") or "")

    def add(value):
        raw = str(value or "")
        if not raw or raw == parent:
            return
        try:
            clean = identifier(raw)
        except (ValueError, TypeError):
            return
        ids.add(clean)

    trial = state.get("draft_trial") or {}
    if isinstance(trial, dict):
        add(trial.get("session_id"))
    for key in ("segments", "retired_segments"):
        for row in state.get(key) or []:
            for version in row.get("versions") or []:
                if not isinstance(version, dict):
                    continue
                if version.get("preview_only") or version.get("trial_session"):
                    add(version.get("trial_session"))
    return ids


def _session_usage(session_id: str, state: dict | None) -> tuple[int, int]:
    """会话目录中会被删除的文件数与字节数（progress.json 会重写，不计）。"""
    files, total = _dir_usage(STORE.directory(session_id))
    try:
        progress = (STORE.directory(session_id) / "progress.json")
        if progress.is_file():
            files -= 1
            total -= progress.stat().st_size
    except OSError:
        pass
    if state is not None:
        for child in _child_sessions(state):
            child_files, child_total = _dir_usage(STORE.directory(child))
            files += child_files
            total += child_total
    return max(0, files), max(0, total)


def _snapshot_versions(session_id: str, state: dict) -> int:
    """历史组快照里仍保留的生成版本数（当前轮版本已清空时也有意义的统计）。"""
    directory = STORE.directory(session_id)
    total = 0
    for name in (state.get("group_snapshots") or {}).values():
        try:
            path = (directory / str(name)).resolve()
            if not path.is_relative_to(directory.resolve()) or not path.is_file():
                continue
            snapshot = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(snapshot, dict):
            continue
        for key in ("segments", "retired_segments"):
            for row in snapshot.get(key) or []:
                if isinstance(row, dict):
                    total += len(row.get("versions") or [])
    return total


def plan(session_id: str) -> dict:
    """只读统计：将要清除的历史组/版本/卡片数量与文件体积。"""
    session_id = identifier(str(session_id))
    stats = {
        "session": session_id,
        "exists": False,
        "groups": 0,
        "versions": 0,
        "segments": 0,
        "cards": 0,
        "files": 0,
        "bytes": 0,
        "relay_dirs": 0,
        "relay_files": 0,
        "relay_bytes": 0,
        "trial_sessions": 0,
        "bytes_total": 0,
    }
    state = None
    try:
        state = STORE.read(session_id)
    except (FileNotFoundError, ValueError):
        state = None
    if state is not None:
        rows = list(state.get("segments") or []) + list(state.get("retired_segments") or [])
        stats.update(
            exists=True,
            groups=len(state.get("group_snapshots") or {}),
            versions=sum(len(row.get("versions") or []) for row in rows) + _snapshot_versions(session_id, state),
            segments=len(state.get("segments") or []),
            trial_sessions=len(_child_sessions(state)),
        )
        files, total = _session_usage(session_id, state)
        stats["files"] = files
        stats["bytes"] = total
    relay = relay_directories(session_id)
    stats["relay_dirs"] = len(relay)
    relay_files = relay_bytes = 0
    for directory in relay:
        files, total = _dir_usage(directory)
        relay_files += files
        relay_bytes += total
    stats["relay_files"] = relay_files
    stats["relay_bytes"] = relay_bytes
    stats["bytes_total"] = stats["bytes"] + relay_bytes
    return stats


def _fresh_state(old: dict) -> dict:
    """在原状态上清空所有生成数据，保留素材/分段/提示词/参数，供下一轮从第 1 段开始。"""
    state = copy.deepcopy(old)
    state["segments"] = []
    for row in old.get("segments") or []:
        state["segments"].append({
            "entry": copy.deepcopy(row.get("entry") or {}),
            "signature": row.get("signature", ""),
            "segment_key": row.get("segment_key", ""),
            "versions": [],
            "reroll": 0,
            "selected": None,
            "valid": False,
            "accepted": False,
            "boundary_changed": False,
        })
    for key in _TRANSIENT_KEYS:
        state.pop(key, None)
    state.update(
        cursor=0,
        status="ready",
        auto=False,
        pause_after=False,
        active=None,
        error="",
        group_snapshots={},
        group_seq=1,
        round_no=1,
        epoch=int(old.get("epoch", 0) or 0) + 1,
        reset_id=uuid.uuid4().hex,
        # 每轮独立潜桥链；彻底重置后旧 stage 已删除，必须换新链。
        relay_run_id=uuid.uuid4().hex,
    )
    return state


def _remove_tree(path: Path, failures: list[str]) -> None:
    try:
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
    except OSError as exc:
        failures.append("%s (%s)" % (path, exc))


def purge(session_id: str) -> tuple[dict, dict | None]:
    """执行彻底重置；返回 (统计, 新状态或 None)。同一会话重复调用是幂等的。"""
    session_id = identifier(str(session_id))
    stats = plan(session_id)
    failures: list[str] = []
    fresh = None
    with STORE.lock(session_id):
        state = None
        try:
            state = STORE._load(session_id)
        except FileNotFoundError:
            state = None
        # 先算出新状态，再删文件，避免删到一半出错拿不到旧数据。
        if state is not None:
            fresh = _fresh_state(state)
        # 抽卡试跑子会话（整目录）。
        trials = _child_sessions(state) if state is not None else set()
        for child in trials:
            _remove_tree(STORE.directory(child), failures)
        # 本会话目录：progress.json 与所有结果/快照/中间文件。
        directory = STORE.directory(session_id)
        if directory.is_dir():
            try:
                children = list(directory.iterdir())
            except OSError as exc:
                children = []
                failures.append("%s (%s)" % (directory, exc))
            for child in children:
                _remove_tree(child, failures)
        # 本会话潜桥 stage 链。
        for relay in relay_directories(session_id):
            _remove_tree(relay, failures)
        # 写回全新状态；没有旧状态时不凭空建会话（前端只做本地清理）。
        if fresh is not None:
            STORE._save(fresh)
    stats["failures"] = failures
    return stats, fresh
