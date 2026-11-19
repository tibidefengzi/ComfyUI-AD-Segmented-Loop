"""提交前的素材准入：区分「本段必需」与「可选」素材。

必需 = 本段真正会读取的文件：取音片段、本段视频、参考视频片段、参考图/分镜图。
可选 = 清单里记录、但本段不读取的文件（禁止输出、指定给其它段等）。
这里只按路径判断，不读素材内容，也不改变分段、端口顺序或生成规则。
"""
from __future__ import annotations

from .timeline import (audio_pieces, output_timeline,
                       priority_sources, segment_intervals, video_range)

_ASSET_ORIGINS = {"input", "output", "media", "session"}


def _is_asset(value):
    return (isinstance(value, dict)
            and value.get("origin") in _ASSET_ORIGINS
            and isinstance(value.get("file"), str) and bool(value.get("file")))


def _collect(values, found, seen):
    for value in values:
        if _is_asset(value):
            key = (value["origin"], value["file"])
            if key not in seen:
                seen.add(key)
                found.append(value)
        elif isinstance(value, dict):
            _collect(list(value.values()), found, seen)
        elif isinstance(value, (list, tuple)):
            _collect(value, found, seen)


def segment_assets(state, index):
    """本段会读取的素材（按来源去重，顺序稳定）；取不到分段时返回空列表。

    与 timeline.derive_segments 的 `used` 同源：本段音频片段、参考视频片段、
    本段选用视频、全局/本段参考图、分镜图。禁止输出(-2)与其它段专属图不算本段必需。
    """
    if not isinstance(state, dict):
        return []
    state = output_timeline(state)
    try:
        index = max(0, int(index or 0))
    except (TypeError, ValueError):
        index = 0
    batch = priority_sources(state)
    if batch:
        # 路径批处理：一段一个完整原文件，只读取该文件。
        return [batch[index % len(batch)]]
    try:
        intervals, _ = segment_intervals(state)
    except (ValueError, TypeError, KeyError):
        return []
    if not intervals:
        return []
    index = min(index, len(intervals) - 1)
    start, end = intervals[index]
    sources = {source["id"]: source for source in state.get("sources") or []}
    refs = []
    muted = (state.get("muted_tracks") or {}).get("audio_tracks") or []
    for lane_index, lane in enumerate(state.get("audio_tracks") or []):
        if lane_index < len(muted) and muted[lane_index]:
            continue  # 静音轨道本段不取音
        refs.extend(audio_pieces(lane, sources, start, end))
    for lane in state.get("video_tracks") or []:
        refs.extend(audio_pieces(lane, sources, start, end))
    selected = video_range(state.get("video_tracks") or [], sources, start, end, index)
    if selected:
        refs.append(selected)
    # 参考图：全局(-1)、仅参考口(0)、本段专属(N)；其它段专属与禁止输出不参与本段。
    for image in state.get("images") or []:
        if image.get("segment") in (-1, 0, index + 1):
            source = sources.get(image.get("source"))
            if source:
                refs.append(source)
    boards = state.get("board_images") or []
    if index < len(boards) and boards[index]:
        board_sources = {source["id"]: source for source in state.get("board_sources") or []}
        source = board_sources.get(boards[index])
        if source:
            refs.append(source)
    found, seen = [], set()
    _collect(refs, found, seen)
    return found


def asset_label(source):
    """提示里用的素材名：优先用户可见名称，其次文件名。"""
    name = str((source or {}).get("name") or "").strip()
    if name:
        return name
    file = str((source or {}).get("file") or "")
    return file.replace("\\", "/").rsplit("/", 1)[-1] or "素材"


def required_paths(state, index):
    """本段必需素材：绝对路径 → 显示名。解析失败的来源交给执行期报错，这里先跳过。"""
    from .assets import resolve_source
    result = {}
    for source in segment_assets(state, index):
        try:
            path = resolve_source(source)  # 已是绝对路径
        except (ValueError, OSError):
            continue
        result[str(path)] = asset_label(source)
    return result


def material_paths(state):
    """清单里登记的素材路径（用于区分「清单素材缺失」与其它缺失文件）。"""
    from .assets import resolve_source
    found = set()
    for source in (state or {}).get("sources") or []:
        try:
            found.add(str(resolve_source(source)))  # 已是绝对路径
        except (ValueError, OSError):
            continue
    return found
