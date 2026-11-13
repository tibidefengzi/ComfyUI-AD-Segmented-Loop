"""Per-segment RGB exposure/color matching to the reference video's first frame.

只做“整段一个固定校正”（不对逐帧自动增益），避免段内闪烁；
目标是参考视频首帧的逐通道均值，校正生成帧的整体亮度/白平衡。
不经过 VAE 往返，不改变生成过程。

v0.5.60 起精简为 3 档：
- 关闭；
- 跟随源片：逐段往本段参考首帧拉，并对相邻段的校正偏移做跨段平滑（保留真实明暗变化）；
- 全链统一（第1段）：所有段固定往第 1 段参考首帧拉（仅适合光照/色温恒定的素材）。
旧工作流里的“0.5·半强 / 1·全强 / 0.5·全链统一 / 1·全链统一”仍可解析并自动映射。
"""
from __future__ import annotations

import numpy as np

from .spec import FPS

COLOR_MATCH_CHOICES = (
    "0 · 关闭",
    "跟随源片",
    "全链统一（第1段）",
)
COLOR_MATCH_VALUES = {"0 · 关闭": 0.0, "跟随源片": 1.0}
# 全链统一目标：所有段都往“第 1 段参考首帧”的同一色彩目标拉，避免逐段目标不同造成段间台阶。
COLOR_MATCH_CHAIN_VALUES = {
    "全链统一（第1段）": 1.0,
}
# 旧工作流兼容映射：加载/执行时把旧的强度×目标组合折算到新三档。
COLOR_MATCH_LEGACY = {
    "0.5 · 半强": "跟随源片",
    "1 · 全强": "跟随源片",
    "0.5 · 全链统一（第1段）": "全链统一（第1段）",
    "1 · 全链统一（第1段）": "全链统一（第1段）",
}
MAX_OFFSET = 0.18
MIN_REF_MEAN = 0.015
# 跟随源片：相邻段校正偏移每通道最多变化该值；超过场景切换阈值时允许一次跳变。
SMOOTH_STEP = 0.03
SCENE_CHANGE_MEAN = 0.06


def migrate_choice(raw):
    """把旧选项字符串折算成新三档之一；无法识别时原样返回。"""
    if isinstance(raw, (int, float)):
        return raw
    text = str(raw or "").strip()
    return COLOR_MATCH_LEGACY.get(text, text)


def parse_blend(raw):
    """解析下拉/数字：关闭=0，跟随/全链=1；旧数值半强仍返回 0.5 兼容。"""
    if isinstance(raw, (int, float)):
        value = float(raw)
    else:
        text = migrate_choice(raw)
        if text in COLOR_MATCH_VALUES:
            return COLOR_MATCH_VALUES[text]
        if text in COLOR_MATCH_CHAIN_VALUES:
            return COLOR_MATCH_CHAIN_VALUES[text]
        try:
            value = float(text.split()[0]) if text else 0.0
        except (TypeError, ValueError):
            return 0.0
    if value <= 0:
        return 0.0
    return 1.0 if value >= 0.75 else 0.5


def parse_config(raw):
    """解析下拉/数字：返回 {"blend": 0/0.5/1, "chain": bool}。chain=True 表示目标取全链第 1 段。"""
    if isinstance(raw, (int, float)):
        return {"blend": parse_blend(raw), "chain": False}
    text = migrate_choice(raw)
    if text in COLOR_MATCH_CHAIN_VALUES:
        return {"blend": COLOR_MATCH_CHAIN_VALUES[text], "chain": True}
    if text in COLOR_MATCH_VALUES:
        return {"blend": COLOR_MATCH_VALUES[text], "chain": False}
    return {"blend": parse_blend(text), "chain": False}


def reference_frame_stats(frame, source, frame_index):
    """使用已经解码的正文首个参考画面，只向提交节点传递统计值。"""
    import torch
    mean = frame.detach().mean(dim=(0, 1), dtype=torch.float32).cpu().tolist()
    return {"path": source.get("file"), "frame_index": frame_index, "frame_time": frame_index / FPS, "mean": mean}


def _scene_changed(target, previous_target, threshold=SCENE_CHANGE_MEAN):
    if target is None or previous_target is None:
        return False
    try:
        current = np.asarray(target, dtype=np.float32).reshape(-1)[:3]
        previous = np.asarray(previous_target, dtype=np.float32).reshape(-1)[:3]
        if current.size < 3 or previous.size < 3:
            return False
        return float(np.abs(current - previous).mean()) > float(threshold)
    except Exception:
        return False


def apply_reference_color_match(body, stats, blend, previous=None, smooth=False,
                                smooth_step=SMOOTH_STEP, scene_threshold=SCENE_CHANGE_MEAN):
    """body: torch [N,H,W,3] 0..1；返回 (body, info)。

    对整段使用同一个逐通道偏移：target_mean - generated_mean，乘 blend 并限幅；
    不改对比度/锐度，不做逐帧增益。参考缺失/黑帧时原样返回。

    smooth=True（跟随源片）时，若上一段有校正记录，则限制相邻段的偏移变化；
    检测到真实场景切换（参考目标差超过 scene_threshold）时允许一次跳变。
    """
    try:
        blend = float(blend)
    except (TypeError, ValueError):
        blend = 0.0
    if body is None or blend <= 0 or not stats:
        return body, None
    target = np.asarray(stats["mean"], dtype=np.float32).reshape(-1)[:3]
    if target.size < 3 or float(target.mean()) < MIN_REF_MEAN:
        return body, None
    import torch

    step = max(1, int(body.shape[0]) // 8)
    sample = body[::step].detach()
    generated = sample.mean(dim=(0, 1, 2), dtype=torch.float32).cpu().numpy()
    raw_offset = np.clip((target - generated) * blend, -MAX_OFFSET, MAX_OFFSET)
    offset = raw_offset
    smoothing = "none"
    if smooth and isinstance(previous, dict):
        previous_offset = previous.get("offset")
        previous_target = previous.get("target_mean")
        if (isinstance(previous_offset, (list, tuple)) and len(previous_offset) >= 3
                and not _scene_changed(target, previous_target, scene_threshold)):
            try:
                base = np.asarray(previous_offset, dtype=np.float32).reshape(-1)[:3]
                delta = raw_offset - base
                offset = base + np.clip(delta, -smooth_step, smooth_step)
                smoothing = "smooth"
            except Exception:
                offset = raw_offset
                smoothing = "none"
        elif isinstance(previous_offset, (list, tuple)):
            smoothing = "scene_cut"
    if float(np.abs(offset).max()) < 0.002:
        return body, None
    correction = torch.as_tensor(offset, device=body.device, dtype=body.dtype).view(1, 1, 1, 3)
    corrected = torch.empty_like(body)
    chunk = max(1, (32 * 1024 * 1024) // (body[0].numel() * body.element_size()))
    for start in range(0, len(body), chunk):
        destination = corrected[start:start + chunk]
        torch.add(body[start:start + chunk].detach(), correction, out=destination)
        destination.clamp_(0.0, 1.0)
    info = {
        "blend": float(blend if blend in (0.5, 1.0) else parse_blend(blend)),
        "reference": stats["path"],
        "reference_track": stats.get("track"),
        "reference_frame_index": stats.get("frame_index"),
        "frame_time": float(stats["frame_time"]),
        "target_mean": [round(float(v), 5) for v in target],
        "generated_mean": [round(float(v), 5) for v in generated],
        "raw_offset": [round(float(v), 5) for v in raw_offset],
        "offset": [round(float(v), 5) for v in offset],
        "smoothing": smoothing,
    }
    return corrected, info
