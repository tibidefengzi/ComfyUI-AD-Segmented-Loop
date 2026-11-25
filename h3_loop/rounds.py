"""每次提交的执行副本：已提交段稳定，下一段读取当前素材和设置。"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import uuid
import hashlib
from pathlib import Path

from .spec import relay_parent_stage, relay_reanchor_interval, relay_reanchors
from .storage import STORE, atomic_json, contained, identifier


def _relay_choice(graph, node_id):
    """生成方式=1 · 潜桥续接 时返回默认上下文 22；旧 0/5/22/39 值继续兼容。"""
    raw = ((graph or {}).get(str(node_id)) or {}).get("inputs", {}).get("生成方式")
    text = str(raw or "").strip()
    if "潜桥" in text or text.startswith(("1", "2")):
        return 22
    if "逐段" in text or text.startswith("0"):
        return 0
    match = re.match(r"^(\d+)", text)
    value = int(match.group(1)) if match else 0
    return value if value in (0, 5, 22, 39) else 0


def _stable_run(sid, relay_id):
    return "ad_%s_%s" % (str(sid), str(relay_id or ""))


def _stage_path(run_id, stage):
    import folder_paths
    return (Path(folder_paths.get_output_directory()) / "relay_kit" / str(run_id)
            / ("stage_%05d.safetensors" % int(stage)))


def _copy_stage(source_run, stage_index, target_run):
    source = _stage_path(source_run, stage_index)
    if not source.is_file():
        return False
    target = _stage_path(target_run, stage_index)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".ad_tmp")
    shutil.copy2(source, temporary)
    os.replace(temporary, target)
    return True


def _anchor_signature(entry):
    """回抽锚点：只取分段结构/源范围等“这段画面是谁”的字段，参考与提示词不参与。"""
    entry = entry or {}
    video = entry.get("video_source") or {}
    source = entry.get("source_video") or {}

    def number(value):
        try:
            return round(float(value), 6)
        except (TypeError, ValueError):
            return value

    images = entry.get("images") or []
    try:
        image_key = hashlib.sha256(
            json.dumps(images, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]
    except Exception:
        image_key = str(images)
    return {"video": (video.get("origin"), video.get("file"),
                      number(video.get("src_in")), number(video.get("src_out"))),
            "source_video": (source.get("id"), source.get("kind"), source.get("file")),
            "source_start": number(entry.get("source_start")),
            "seconds": number(entry.get("seconds_float")),
            "images": image_key}


def _validate_old_round_plan(origin_segments, child_segments, trial_round):
    hint = ("当前时间线/分段与第 %d 轮不一致，无法按该轮回抽；"
            "请先恢复第 %d 轮再抽卡，或撤销分段改动。"
            % (int(trial_round), int(trial_round)))
    if len(origin_segments or []) != len(child_segments or []):
        raise ValueError(hint)
    for index, (old, new) in enumerate(zip(origin_segments, child_segments)):
        if _anchor_signature(old.get("entry")) != _anchor_signature(new.get("entry")):
            raise ValueError("（第 %d 段）%s" % (index + 1, hint))


def _version_from_preview(segments, preview):
    if not isinstance(preview, dict) or not preview.get("file"):
        return None
    name = str(preview.get("file") or "").replace("\\", "/")
    scope = ""
    session_id = preview.get("session_id")
    if preview.get("origin") == "session":
        scope, separator, name = name.partition("/")
        if not separator:
            return None
    child = scope if scope.startswith("trial_") else (
        session_id if str(session_id or "").startswith("trial_") else "")
    for row in segments or []:
        for version in row.get("versions") or []:
            file = str(version.get("file") or "").replace("\\", "/")
            normal = file == name or file.rsplit("/", 1)[-1].endswith("_" + name.rsplit("/", 1)[-1])
            trial = (bool(child) and version.get("preview_only") and version.get("trial_request")
                     and file == "trial_" + str(version.get("trial_request")) + "_" + name)
            if normal or trial:
                return version
    return None


def _pick_parent_version(origin_segments, target, target_version):
    """旧轮父 latent 的来源：优先该轮选用版本，其次只在“目标生成之前存在”的版本里取。

    不能兜底选“最新版本”：目标版本可能是旧记录，之后才生成的版本不可能是它的父 latent，
    选错会导致回抽取到未来版本的父 latent，接缝/连续性错位。
    """
    row = origin_segments[int(target) - 1]
    candidates = [version for version in row.get("versions") or []
                  if version.get("relay_save_run_id") and version.get("relay_stage_index") is not None]
    if not candidates:
        return None
    selected = row.get("selected")
    if selected:
        for version in candidates:
            if version.get("id") == selected:
                return version

    def created(version):
        try:
            return float(version.get("created_at") or 0)
        except (TypeError, ValueError):
            return 0.0

    timed = [version for version in candidates if created(version) > 0]
    try:
        anchor = float(target_version.get("created_at") or 0)
    except (TypeError, ValueError):
        anchor = 0.0
    if anchor > 0:
        before = [version for version in timed if created(version) <= anchor]
        if not before:
            return None
        candidates = before
    elif len(candidates) != 1:
        # 没有时间锚点且候选不唯一：无法确定当时用的是哪一版，交给上层明确报错。
        return None
    return max(candidates, key=created)


def _recover_old_round_chain(sid, parent, origin_state, target, trial_round, target_version, reanchor=False):
    """为旧轮恢复实际依赖的稳定 latent：上一段或第 1 段外观锚。"""
    from . import group_history
    origin_segments = origin_state.get("segments") or []
    relay_id = str(origin_state.get("relay_run_id") or "")
    chain = _stable_run(sid, relay_id) if relay_id else ""
    # 历史轮与当前轮共用旧目录时必须恢复：只查历史快照会漏掉“历史链 == 当前链”。
    shared = bool(relay_id) and (
        relay_id == str(parent.get("relay_run_id") or "")
        or relay_id in group_history.shared_relay_run_ids(STORE, parent))
    # 重锚定已改为软重置：依赖上一段的 latent/成片，不再依赖第 1 段外观锚。
    stage = relay_parent_stage(target, False)
    new_chain_required = not relay_id or shared
    if not new_chain_required and (stage is None or _stage_path(chain, stage).is_file()):
        return chain
    new_relay = uuid.uuid4().hex if new_chain_required else relay_id
    new_chain = _stable_run(sid, new_relay)
    if stage is not None:
        parent_version = _pick_parent_version(origin_segments, stage + 1, target_version)
        dependency = f"第 {stage + 1} 段的 latent"
        if not parent_version:
            raise ValueError(
                f"第 {trial_round} 轮第 {target + 1} 段回抽无法确定{dependency}的版本。"
                f"请先恢复该轮并重跑第 {stage + 1} 段。")
        saved_stage = int(parent_version["relay_stage_index"])
        if saved_stage != stage or not _copy_stage(str(parent_version["relay_save_run_id"]), stage, new_chain):
            raise ValueError(f"第 {trial_round} 轮{dependency} 文件缺失或段号不一致，回抽已取消。"
                             f"请先恢复该轮并重跑第 {stage + 1} 段。")
    if new_chain_required:
        origin_state["relay_run_id"] = new_relay
        group_history.save_snapshot(STORE, parent, trial_round, origin_state)
    return new_chain


def _plan_old_round_reroll(sid, parent, origin_state, target, preview, trial_round, relay_on, reanchor=False):
    from . import group_history
    group_history.ensure_rerollable(parent, trial_round)
    target_version = _version_from_preview(origin_state.get("segments") or [], preview)
    if target_version is None:
        raise ValueError("所选卡片不属于第 %d 轮快照，无法回抽；请重新选择该轮卡片。"
                         % int(trial_round))
    if not relay_on:
        return ""
    return _recover_old_round_chain(sid, parent, origin_state, target, trial_round, target_version, reanchor)


def _plan_current_reroll(sid, parent, target, preview, relay_on, reanchor=False):
    if not relay_on:
        return ""
    chain = _stable_run(sid, parent.get("relay_run_id") or "")
    target_version = _version_from_preview(parent.get("segments") or [], preview)
    if target_version is not None and target_version.get("archived"):
        version_chain = str(target_version.get("relay_run_id") or "")
        if version_chain and version_chain != chain:
            raise ValueError(
                "该卡片属于上一批次的旧结果，还没有归档为独立轮次，不能直接接到当前轮。"
                "请先点一次「新建一组」（会把当前批次归档成历史轮且保留结果），再回到该轮抽卡。")
    # 重锚定已改为软重置：需要上一段的 latent/成片（不再是第 1 段外观锚）。
    stage = relay_parent_stage(target, False)
    if stage is not None and not _stage_path(chain, stage).is_file():
        raise ValueError(
            "第 %d 段抽卡需要第 %d 段的 latent，但当前新一轮还没有 stage_%05d。"
            "请先在新一轮生成并通过第 %d 段，再抽第 %d 段。"
            % (int(target) + 1, int(target), int(target) - 1, int(target), int(target) + 1))
    return chain


def session_for(prompt, node_id):
    inputs = prompt[str(node_id)].get("inputs", {})
    if inputs.get("session_id"):
        return identifier(inputs["session_id"])
    link = inputs.get("queue")
    if not isinstance(link, list) or len(link) != 2 or str(link[0]) not in prompt:
        return None
    queue = prompt[str(link[0])]
    if queue.get("class_type") != "AidenH3AudioQueue":
        return None
    raw = queue.get("inputs", {}).get("queue_state", {})
    raw = json.loads(raw) if isinstance(raw, str) else raw
    return identifier(raw.get("session_id") or f"AD-H3-{node_id}")


def component(prompt, node_id):
    """保留本循环全部下游预览及其上游，不把其它独立输出纳入本轮。"""
    downstream = {str(node_id)}
    def links(node):
        return [v[0] for v in node.get("inputs", {}).values()
                if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and v[0] in prompt]
    changed = True
    while changed:
        changed = False
        for key, node in prompt.items():
            if key not in downstream and any(key2 in downstream for key2 in links(node)):
                downstream.add(key)
                changed = True
    keep = set()
    def visit(key):
        if key in keep:
            return
        keep.add(key)
        for parent in links(prompt[key]):
            visit(parent)
    for key in downstream:
        visit(key)
    return {key: copy.deepcopy(prompt[key]) for key in keep}


def read_snapshot(state):
    ref = state.get("execution_round")
    if not ref:
        return None
    path = contained(STORE.directory(state["id"]), ref["file"])
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def scan_assets(graph):
    """一次遍历：解析素材路径并记录大小/修改时间，同一路径只 stat 一次。

    返回 (entries, missing)。缺失不再拦住提交，这里只如实记录；
    由提交前的素材准入决定「跳过」还是「按段报错」，避免重复扫描与重复 stat。
    """
    from .assets import resolve_source
    paths = set()

    def visit(value):
        if isinstance(value, dict):
            if value.get("origin") in {"input", "output", "media", "session"} and value.get("file"):
                try:
                    paths.add(str(resolve_source(value)))  # 已是绝对路径，不再重复 resolve/stat
                except (ValueError, OSError):
                    pass
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    for node in graph.values():
        if node["class_type"] == "AidenH3AudioQueue":
            raw = node.get("inputs", {}).get("queue_state", {})
            visit(json.loads(raw) if isinstance(raw, str) else raw)
        field = {"LoadImage": "image", "LoadAudio": "audio", "LoadVideo": "file"}.get(node["class_type"])
        if field and isinstance(node.get("inputs", {}).get(field), str):
            import folder_paths
            try:
                paths.add(str(Path(folder_paths.get_annotated_filepath(node["inputs"][field]))))
            except (OSError, ValueError):
                pass

    entries, missing = [], []
    for raw in sorted(paths):
        try:
            stat = Path(raw).stat()
        except OSError:
            missing.append(raw)
            continue
        entries.append({"path": raw, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns})
    return entries, missing


def asset_manifest(graph):
    """只返回仍存在的素材条目（兼容旧调用）。"""
    return scan_assets(graph)[0]


def asset_changes(previous, current):
    """同一路径的大小/修改时间变了：内容已换，沿用新内容继续，但提示接缝风险。"""
    before = {item.get("path"): (item.get("size"), item.get("mtime_ns")) for item in previous or []}
    changed = []
    for item in current or []:
        old = before.get(item.get("path"))
        if old is not None and old != (item.get("size"), item.get("mtime_ns")):
            changed.append(item.get("path"))
    return changed


def fingerprint_changes(before, current):
    """按会话留存的上次素材指纹对比：同一路径内容/修改时间变了就记为变化。"""
    changed = []
    for item in current or []:
        old = (before or {}).get(item.get("path"))
        if old is not None and tuple(old) != (item.get("size"), item.get("mtime_ns")):
            changed.append(item.get("path"))
    return changed


def validate_assets(snapshot):
    """素材被移走/改过时不拦截提交：剔除失效项，按现有素材继续本轮。"""
    valid = []
    for item in snapshot.get("assets", []) or []:
        path = Path(item.get("path", ""))
        try:
            ok = path.is_file() and (path.stat().st_size, path.stat().st_mtime_ns) == (item.get("size"), item.get("mtime_ns"))
        except OSError:
            ok = False
        if ok:
            valid.append(item)
    if "assets" in snapshot:
        snapshot["assets"] = valid
    return valid


def seed_policies(graph, workflow):
    """冻结种子变化方式；randomize/increment 等原生规则继续逐段生效。"""
    policies = []
    saved = {str(node["id"]): node for node in (workflow or {}).get("nodes", [])}
    for key, node in graph.items():
        values = saved.get(key, {}).get("widgets_values", [])
        values = values if isinstance(values, list) else []
        for field in ("seed", "noise_seed"):
            seed = node.get("inputs", {}).get(field)
            if type(seed) is not int:
                continue
            mode = node.get("inputs", {}).get("control_after_generate")
            for index in range(len(values) - 1):
                if values[index] == seed and values[index + 1] in ("fixed", "randomize", "increment", "decrement"):
                    mode = values[index + 1]
                    break
            if mode in ("randomize", "increment", "decrement"):
                policies.append({"node": key, "field": field, "seed": seed, "mode": mode})
    return policies


def execution_prompt(state, snapshot):
    graph = copy.deepcopy(snapshot["prompt"])
    segments = state.get("segments") or []
    try:
        index = int((state.get("active") or {}).get("index", state.get("cursor")))
    except (TypeError, ValueError):
        index = int(state.get("cursor") or 0)
    if segments and not 0 <= index < len(segments):
        # 段被切分/删除后旧上下文可能越界：回退到当前游标，不能抛 IndexError。
        index = int(state.get("cursor") or 0)
    index = min(max(0, index), len(segments) - 1) if segments else 0
    reroll = segments[index].get("reroll", 0) if segments else 0
    step = index + int(reroll)
    for policy in snapshot.get("seed_policies", []):
        if policy["mode"] == "randomize":
            value = int(hashlib.sha256(f'{state["execution_round"]["id"]}/{policy["node"]}/{index}/{reroll}'.encode()).hexdigest()[:16], 16)
        else:
            value = (policy["seed"] + step * (1 if policy["mode"] == "increment" else -1)) % (2**64)
        graph[policy["node"]]["inputs"][policy["field"]] = value
    return graph


def capture_materials(prompt, node_id):
    """仅固定本轮素材及素材端口对应，生成参数仍取最新提交。"""
    node_id = str(node_id)
    graph = component(prompt, node_id)
    media_types = {"AidenH3AudioQueue", "AidenH3VideoQueue", "LoadImage", "LoadAudio", "LoadVideo"}
    nodes = {key: copy.deepcopy(node) for key, node in graph.items() if node.get("class_type") in media_types}
    segment = graph[node_id].get("inputs", {})
    fixed = {name: copy.deepcopy(segment[name]) for name in ("queue", "ref_counts") if name in segment}
    bindings = []
    for key, node in graph.items():
        for name, value in node.get("inputs", {}).items():
            if not isinstance(value, list) or len(value) != 2:
                continue
            origin, slot = str(value[0]), value[1]
            material_port = origin == node_id and isinstance(slot, int) and (slot in {2, 9, 10, 11, 12, 13} or slot >= 14)
            if origin in nodes or material_port:
                bindings.append({"node": key, "input": name, "link": copy.deepcopy(value)})
    return {"nodes": nodes, "segment_inputs": fixed, "bindings": bindings}


def apply_materials(prompt, node_id, materials, fallback=None):
    """把当前轮素材合入提交副本，不写回编辑器，不固定提示词/采样/尺寸等参数。"""
    result = copy.deepcopy(prompt)
    fallback = fallback or {}
    node_id = str(node_id)
    seen = set()
    def ensure(key):
        if key in result or key in seen or key not in fallback:
            return
        seen.add(key)
        result[key] = copy.deepcopy(fallback[key])
        for value in result[key].get("inputs", {}).values():
            if isinstance(value, list) and len(value) == 2:
                ensure(str(value[0]))
    ensure(node_id)
    live_queue_link = result.get(node_id, {}).get("inputs", {}).get("queue")
    live_queue = result.get(str(live_queue_link[0]), {}) if isinstance(live_queue_link, list) and live_queue_link else {}
    live_fields = {"prompts", "aspect_ratio", "megapixels", "sequence_mode", "reanchor_every", "max_frames", "overlap_frames", "guard_frames"}
    for key, original in materials.get("nodes", {}).items():
        frozen = copy.deepcopy(original)
        if original.get("class_type") == "AidenH3AudioQueue":
            latest = result.get(key) or live_queue
            for field in ("queue_state", "h3_editor_state"):
                try:
                    old_raw = frozen.get("inputs", {}).get(field)
                    new_raw = latest.get("inputs", {}).get(field)
                    old = json.loads(old_raw) if isinstance(old_raw, str) else copy.deepcopy(old_raw)
                    new = json.loads(new_raw) if isinstance(new_raw, str) else new_raw
                    if isinstance(old, dict) and isinstance(new, dict):
                        old.update({name: copy.deepcopy(new[name]) for name in live_fields if name in new})
                        frozen["inputs"][field] = json.dumps(old, ensure_ascii=False) if isinstance(old_raw, str) else old
                except (TypeError, ValueError):
                    pass
        result[key] = frozen
    segment = result[node_id].setdefault("inputs", {})
    for name in ("queue", "ref_counts"):
        if name in materials.get("segment_inputs", {}):
            segment[name] = copy.deepcopy(materials["segment_inputs"][name])
        else:
            segment.pop(name, None)
    for binding in materials.get("bindings", []):
        ensure(binding["node"])
        if binding["node"] in result:
            result[binding["node"]].setdefault("inputs", {})[binding["input"]] = copy.deepcopy(binding["link"])
    return result


def freeze(state, prompt, node_id, workflow=None, batch=False, materials=None, scanned=None):
    sid = state["id"]
    with STORE.lock(sid):
        current = STORE._load(sid)
        previous = read_snapshot(current)
        # 普通提交不继承旧组素材；显式materials仅保留为兼容适配工具。
        if materials is not None:
            validate_assets({"assets": materials.get("assets", [])})
            prompt = apply_materials(prompt, node_id, materials, (previous or {}).get("prompt"))
        # 本次提交中的素材、连线、参数固定，下一次提交会重新读取。
        token = uuid.uuid4().hex
        graph = component(prompt, node_id)
        # 快照内固定会话名，后续画布更换清单/连线不会改变当前轮归属。
        graph[str(node_id)]["inputs"]["session_id"] = sid
        graph[str(node_id)]["inputs"].pop("run_token", None)
        material_state = copy.deepcopy(materials) if materials is not None else capture_materials(graph, node_id)
        # 素材清单只扫一次：快照、缺失记录、指纹变化都复用这一次结果。
        manifest, absent = scanned if scanned is not None else scan_assets(graph)
        # 素材指纹按会话留存：上一轮的 execution_round 会在提交结束时清掉，
        # 所以对比用会话里的指纹，而不是只依赖旧快照。
        last = {str(path): tuple(value) for path, value in (current.get("asset_fingerprints") or {}).items()}
        changes = fingerprint_changes(last, manifest)
        if not last:
            changes = asset_changes((previous or {}).get("assets"), manifest)
        current["asset_fingerprints"] = {item["path"]: [item["size"], item["mtime_ns"]] for item in manifest}
        material_state.setdefault("assets", manifest)
        snapshot = {"prompt": graph, "segment_node": str(node_id), "workflow": workflow or {},
                    "assets": manifest, "missing_assets": absent,
                    "asset_changes": changes,
                    "seed_policies": seed_policies(graph, workflow),
                    "materials": material_state}
        rounds_dir = STORE.directory(sid) / "rounds"
        rounds_dir.mkdir(parents=True, exist_ok=True)
        atomic_json(rounds_dir / (token + ".json"), snapshot)
        # 旧快照可能正被另一线程 read_snapshot 读取：先写新快照，再按 mtime 只保留最近 2 份；
        # 删除失败忽略，避免并发读取时瞬时找不到文件。
        snapshots = []
        for item in rounds_dir.glob("*.json"):
            try:
                snapshots.append((item.stat().st_mtime_ns, item.name, item))
            except OSError:
                continue
        snapshots.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
        for _, _, stale in snapshots[2:]:
            try:
                stale.unlink()
            except OSError:
                pass
        current["execution_round"] = {"id": token, "file": "rounds/" + token + ".json",
                                      "segment_node": str(node_id), "batch": bool(batch)}
        current.pop("resume_round", None)
        return STORE._save(current)


def resolve_resume_anchor(state, preview, fallback):
    """优先按实际结果文件定位，显示编号不是段落身份。"""
    if not preview:
        return int(fallback)
    sid = state["id"]
    named = preview.get("session_id")
    name = str(preview.get("file") or "").replace("\\", "/")
    scope = ""
    if preview.get("origin") == "session":
        scope, separator, name = name.partition("/")
        if not separator:
            raise ValueError("所选预览缺少本轮文件身份，请重新选择分段预览")
    normal = scope in {"", sid} and named in {None, "", sid}
    child = scope if scope.startswith("trial_") else (named if str(named or "").startswith("trial_") else "")
    matches = []
    for index, row in enumerate(state.get("segments") or []):
        for version in row.get("versions") or []:
            file = str(version.get("file") or "").replace("\\", "/")
            matching = bool(file) and (file == name or file.rsplit("/", 1)[-1].endswith("_" + name.rsplit("/", 1)[-1]))
            trial_match = (child and version.get("preview_only") and version.get("trial_request")
                           and (not version.get("trial_session") or version["trial_session"] == child)
                           and file == "trial_" + str(version["trial_request"]) + "_" + name)
            if (normal and matching) or trial_match:
                matches.append(index + 1)
                break
    if len(matches) == 1:
        return matches[0]
    key = preview.get("segment_key")
    if normal and named == sid and key:
        matches = [i + 1 for i, row in enumerate(state.get("segments") or []) if row.get("segment_key") == key]
        if len(matches) == 1:
            return matches[0]
    if normal and named == sid and preview.get("segment_index"):
        return int(preview["segment_index"])
    if not normal:
        raise ValueError("所选预览不属于当前这一轮，请选择本轮分段预览")
    raise ValueError("无法在本轮进度中找到所选预览，请选择本轮已有结果")


def accept_through(state, count):
    """清空重置后从选中预览续跑：前 count 段按各自最后一次生成结果补成已通过，
    第 count 段起标记待更新（旧版本保留为历史），游标停在第 count 段。"""
    rows = state.get("segments") or []
    count = int(count)
    if count <= 0:
        raise ValueError("请先在「分段生成」里选中要从其后续跑的预览卡")
    if count > len(rows):
        raise ValueError(f"本轮没有第 {count} 段，不能继续")
    latest_prefix = []
    for index, row in enumerate(rows[:count]):
        versions = row.get("versions") or []
        if not versions:
            raise ValueError(f"第 {index + 1} 段没有已生成结果，不能从第 {count + 1} 段继续")
        latest_prefix.append(max(versions, key=lambda version: float(version.get("created_at") or 0)))
    for index, row in enumerate(rows):
        if index < count:
            latest = latest_prefix[index]
            row["selected"] = latest.get("id")
            row["valid"] = True
            row["accepted"] = True
            row["boundary_changed"] = False
        else:
            row["selected"] = None
            row["valid"] = False
            row["accepted"] = False
    state.update(cursor=count, status="completed" if count == len(rows) else "ready", auto=False, pause_after=False, active=None, error="")
    return state


def select_resume_version(state, preview, anchor):
    """把用户点选的那一版设为第 anchor 段的选用，作为下一段接力的父版本。

    与 accept_through 的分工：前 1..anchor-1 段仍按各自最新版补成已通过；
    第 anchor 段认用户点的这一版（不是最新版），下一段桥接读它的 latent，
    最终合并也用这一版。
    """
    rows = state.get("segments") or []
    try:
        anchor = int(anchor)
    except (TypeError, ValueError):
        raise ValueError("所选段号无效，请重新选择预览卡") from None
    if not 1 <= anchor <= len(rows):
        raise ValueError("所选段号超出当前分段范围，请重新选择预览卡")
    version = _version_from_preview(rows, preview)
    if version is None:
        raise ValueError("所选卡片在本轮进度里找不到对应版本；请重新选择分段预览")
    row = rows[anchor - 1]
    if version.get("id") not in {item.get("id") for item in row.get("versions") or []}:
        raise ValueError("所选卡片不属于第 %d 段，请重新选择" % anchor)
    row["selected"] = version.get("id")
    row["valid"] = True
    row["accepted"] = True
    row["boundary_changed"] = False
    return version


def promote_resume_stage(state, version, anchor):
    """第 anchor 段的接力父 latent：把点选版本的潜桥 stage 提升到稳定链。

    非潜桥版本无需提升；潜桥版本源 stage 缺失时明确报错，避免下一段接错版本。
    """
    if not isinstance(version, dict):
        return False
    target = str(version.get("relay_run_id") or "")
    source = str(version.get("relay_save_run_id") or "")
    try:
        int(version.get("relay_stage_index"))
    except (TypeError, ValueError):
        return False
    if not target or not source or target == source:
        return False  # 非潜桥或已经存在稳定链，无需复制
    row = (state.get("segments") or [])[int(anchor) - 1]
    if STORE._promote_relay_stage(state, row, version):
        return True
    raise ValueError(
        "第 %d 段所选预览的潜桥 latent 已不在（可能已清理或未落盘），"
        "无法作为下一段的接力；请重新生成该段或换一张卡。" % int(anchor))



def _prompt_active(prompt_id):
    """只看“本段自己那一单”还在不在队列/运行中，别人的任务不算。"""
    if not prompt_id:
        return False
    try:
        from server import PromptServer
        queue = getattr(PromptServer.instance, "prompt_queue", None)
        if queue is None:
            return False
        groups = queue.get_current_queue() or []
    except Exception:
        return False
    for group in groups:
        for item in group or []:
            try:
                if str(item[1]) == str(prompt_id):
                    return True
            except (TypeError, IndexError):
                continue
    return False


def prepare(data):
    """由原生排队入口调用；只替换提交副本，从不写回画布。"""
    try:
        return _prepare(data)
    except FileNotFoundError:
        # 清空进度/新工作流/缓存被清理时还没有会话文件：按“没有进度”放行，不拦截排队。
        return {"prompt": data.get("prompt") or {}, "workflow": data.get("workflow"), "rounds": [],
                "warnings": []}


def current_index(state):
    """当前段号：优先正在执行的段，其次游标（与 execution_prompt 同一口径）。"""
    try:
        return int((state.get("active") or {}).get("index", state.get("cursor")))
    except (TypeError, ValueError):
        return int(state.get("cursor") or 0)


def frozen_timeline(snapshot, node_id):
    """冻结副本里的素材清单（原始 JSON）：只用于提交前素材准入，不参与生成。"""
    graph = (snapshot or {}).get("prompt") or {}
    link = ((graph.get(str(node_id)) or {}).get("inputs") or {}).get("queue")
    if not (isinstance(link, list) and len(link) == 2 and str(link[0]) in graph):
        return None
    inputs = graph[str(link[0])].get("inputs") or {}

    def parse(value):
        try:
            data = json.loads(value) if isinstance(value, str) else value
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    state = parse(inputs.get("queue_state"))
    editor = parse(inputs.get("h3_editor_state"))
    if not state.get("version") and editor.get("version"):
        state = editor  # 与 AidenH3AudioQueue.build 的合并规则一致
    return state if state.get("version") else None


def _segment_relay_context(graph, node_id):
    """提取分段节点的潜桥上下文帧数；未启用潜桥时返回 0。"""
    inputs = ((graph or {}).get(str(node_id)) or {}).get("inputs") or {}
    mode = str(inputs.get("生成方式") or "").strip()
    if not (("潜桥" in mode) or mode.startswith(("1", "2"))):
        return 0
    raw = str(inputs.get("潜桥上下文帧数") or "22").strip()
    try:
        value = int(raw.split()[0]) if raw else 22
    except (TypeError, ValueError):
        value = 22
    return value if value > 0 else 22


def _rollback_session_state(sid, prior_state, snapshot_file=None):
    """必需素材缺失或循环冲突被跳过时，原样回滚本次提交前的会话进度与快照。"""
    with STORE.lock(sid):
        if snapshot_file:
            try:
                (STORE.directory(sid) / snapshot_file).unlink(missing_ok=True)
            except OSError:
                pass
        if prior_state is not None:
            atomic_json(STORE.directory(sid) / "progress.json", prior_state)
        else:
            directory = STORE.directory(sid)
            try:
                (directory / "progress.json").unlink(missing_ok=True)
            except OSError:
                pass
            try:
                if directory.is_dir() and not any(directory.iterdir()):
                    directory.rmdir()
            except OSError:
                pass


def _prepare(data):
    from .routes import sync_graph_now
    prompt = copy.deepcopy(data.get("prompt") or {})
    bindings = data.get("round_bindings") or []
    warnings = []
    skipped = []
    bound = {}
    for item in bindings:
        try:
            declared=session_for(prompt,str(item['segment_node'])) if str(item['segment_node']) in prompt else None
            task=((data.get('workflow') or {}).get('extra') or {}).get('ad_segmented_task')
            if task and declared!=item['session_id']:
                continue  # 不用其它工作流遗留的轮次绑定覆盖当前任务命名空间。
            if STORE.read(identifier(item["session_id"])).get("execution_round"):
                bound[str(item["segment_node"])] = item["session_id"]
        except FileNotFoundError:
            pass
    candidates = [(str(key), bound.get(str(key)) or session_for(prompt, key)) for key, node in prompt.items()
                  if node.get("class_type") == "AidenH3Segment"]
    for node_id, sid in bound.items():
        if not any(existing_sid == sid for _, existing_sid in candidates):
            candidates.append((node_id, sid))
    rounds = []
    draft = copy.deepcopy(prompt)
    replacements, removed = {}, set()
    workflow = data.get("workflow")
    for node_id, sid in candidates:
        if not sid:
            continue  # 无清单的独立模式保持原有行为。
        try:
            disk_state = STORE.read(sid)
        except FileNotFoundError:
            disk_state = None
        prior_state = copy.deepcopy(disk_state)
        state = disk_state
        from .workflow_tasks import prompt_task
        task = prompt_task(prompt, node_id, data.get("workflow"))
        if task and (state or {}).get("workflow_task_id") not in {None, task}:
            # 换了工作流/换了素材：不复用旧任务进度，按新的一轮继续，而不是拦住用户。
            state = None
        trial = (state or {}).get("draft_trial")
        created_snapshot_file = None
        if trial:
            state = STORE.read(trial["session_id"])
            snapshot = read_snapshot(state)
            if not snapshot:
                continue
            index = current_index(state)
            timeline = frozen_timeline(snapshot, node_id)
            relay_ctx = _segment_relay_context(snapshot.get("prompt"), node_id)
            if timeline is not None:
                from .material_guard import material_paths, required_paths
                required = required_paths(timeline, index, relay_context=relay_ctx)
                absent = set(snapshot.get("missing_assets") or [])
                missing_required = [(label, path) for path, label in required.items() if path in absent]
                if missing_required:
                    skipped.append((index, missing_required))
                    names = "、".join(sorted({label for label, _ in missing_required}))
                    warnings.append("第 %d 段缺 %d 个素材文件：%s，本段已跳过"
                                    % (index + 1, len(missing_required), names))
                    if node_id in draft:
                        removed.update(component(draft, node_id))
                    continue
                known = material_paths(timeline)
                optional = sorted(path for path in absent if path in known and path not in required)
                if optional:
                    warnings.append("第 %d 段可选素材缺失，已跳过：%s"
                                    % (index + 1, "、".join(Path(path).name for path in optional)))
                for path in snapshot.get("asset_changes") or []:
                    label = required.get(str(path))
                    if label:
                        warnings.append("%s 文件已变，第 %d 段起用新内容，接缝可能跳" % (label, index + 1))
        else:
            if node_id not in prompt:
                continue  # 已拆掉连线：本轮不生成这一段。
            active = (state or {}).get("active") or {}
            if (state or {}).get("status") in {"queued","running"} and active.get("prompt_id"):
                if _prompt_active(active.get("prompt_id")):
                    raise ValueError("当前段仍在执行：请等待本段完成，或先点「停止」再提交，避免修改已提交的当前段。")
                # 队列里已经没有这个任务：是上次中断留下的残留状态。清掉，按新的一轮继续。
                state["status"] = "idle"
                state["active"] = {}
                STORE._save(state)
                prior_state = copy.deepcopy(STORE.read(sid))
            # 下一段重新读取画布，不把旧组素材重新覆盖到最新编辑。

            # 本轮绑定优先于画布 queue_state 里的旧会话名，避免改线后串到别的会话。
            queue_link = (draft.get(node_id) or {}).get("inputs", {}).get("queue")
            if isinstance(queue_link, list) and queue_link and str(queue_link[0]) in draft:
                queue_node = draft[str(queue_link[0])]
                try:
                    queue_state = json.loads(queue_node.get("inputs", {}).get("queue_state") or "{}")
                except (TypeError, ValueError):
                    queue_state = {}
                if isinstance(queue_state, dict):
                    queue_state["session_id"] = sid
                    queue_node.setdefault("inputs", {})["queue_state"] = json.dumps(queue_state, ensure_ascii=False)
            else:
                draft.setdefault(node_id, {}).setdefault("inputs", {})["session_id"] = sid
            state = sync_graph_now({**data, "prompt": draft, "segment_node": node_id})
            index = current_index(state)
            graph_draft = component(draft, node_id)
            scanned = scan_assets(graph_draft)
            timeline = frozen_timeline({"prompt": graph_draft}, node_id)
            relay_ctx = _segment_relay_context(graph_draft, node_id)
            required = {}
            if timeline is not None:
                from .material_guard import material_paths, required_paths
                required = required_paths(timeline, index, relay_context=relay_ctx)
                absent = set(scanned[1] or [])
                missing_required = [(label, path) for path, label in required.items() if path in absent]
                if missing_required:
                    # 必需素材缺失：不落盘新快照、不覆盖旧指纹、不改动旧进度，只跳过该循环。
                    _rollback_session_state(sid, prior_state)
                    skipped.append((index, missing_required))
                    names = "、".join(sorted({label for label, _ in missing_required}))
                    warnings.append("第 %d 段缺 %d 个素材文件：%s，本段已跳过"
                                    % (index + 1, len(missing_required), names))
                    if node_id in draft:
                        removed.update(graph_draft)
                    continue
            state = freeze(state, draft, node_id, data.get("workflow"), scanned=scanned)
            created_snapshot_file = (state.get("execution_round") or {}).get("file")
            snapshot = read_snapshot(state)
            if not snapshot:
                continue
            if timeline is not None:
                absent = set(snapshot.get("missing_assets") or [])
                known = material_paths(timeline)
                optional = sorted(path for path in absent if path in known and path not in required)
                if optional:
                    warnings.append("第 %d 段可选素材缺失，已跳过：%s"
                                    % (index + 1, "、".join(Path(path).name for path in optional)))
                for path in snapshot.get("asset_changes") or []:
                    label = required.get(str(path))
                    if label:
                        warnings.append("%s 文件已变，第 %d 段起用新内容，接缝可能跳" % (label, index + 1))
        # 当前连线即使已拆开，也使用被冻结的端口编号和全部节点参数。
        if node_id in draft:
            removed.update(component(draft, node_id))
        frozen = execution_prompt(state, snapshot)
        # 把“当前段号”写进段节点输入：缓存键靠它区分不同段；同一段抽卡（只换种子）
        # 时段号不变，上游条件/编码即可命中缓存。浏览器直连排队的抽卡也走这里。
        try:
            frozen.setdefault(str(node_id), {}).setdefault("inputs", {})["段索引"] = int(
                (state.get("active") or {}).get("index", state.get("cursor") or 0))
        except (TypeError, ValueError, AttributeError):
            pass
        conflict = any(frozen[key] != replacements[key] for key in set(frozen) & set(replacements))
        if conflict:
            # 一个循环的冲突只跳过这个循环，不再让整次提交（含另一个循环）回退。
            if not trial:
                _rollback_session_state(sid, prior_state, created_snapshot_file)
            warnings.append("两套分段循环共享的节点设置不同，已跳过其中一个循环；请分别运行")
            continue
        replacements.update(frozen)
        workflow = snapshot.get("workflow", workflow)
        rounds.append({"session_id": sid, "segment_node": node_id,
                       "id": (STORE.read(sid).get("execution_round") or {}).get("id")})
    prompt = {key: value for key, value in draft.items() if key not in removed}
    prompt.update(replacements)
    if skipped and not rounds:
        # 只提交一个循环且必需素材缺失：明确报到段与文件，不排队、不改动旧进度。
        index, items = skipped[0]
        names = "、".join(sorted({label for label, _ in items}))
        raise ValueError("第 %d 段缺 %d 个素材文件：%s；请补回素材、调整分段或删除该段后再生成"
                         % (index + 1, len(items), names))
    # 所有校验都通过后才清旧轮次标记：被拒绝的提交不会改动任何旧进度。
    for _node_id, sid in candidates:
        if not sid:
            continue
        with STORE.lock(sid):
            try:
                current = STORE._load(sid)
            except FileNotFoundError:
                continue
            if current is not None and current.pop("execution_round", None) is not None:
                STORE._save(current)
    return {"prompt": prompt, "rounds": rounds, "workflow": workflow, "warnings": warnings}


def start_trial(data):
    from .routes import sync_graph_now
    sid = identifier(data["session_id"])
    with STORE.lock(sid):
        parent = STORE._load(sid)
        if parent["status"] in {"queued", "running", "merging"} or parent.get("draft_trial"):
            raise ValueError("请先停止分段循环，并等待本段抽卡结束")
        try:
            target = int(data.get("index", parent["cursor"]))
        except (TypeError, ValueError):
            raise ValueError("无效段号") from None
        preview = data.get("preview")
        trial_round = int(parent.get("round_no", 1) or 1)
        origin_state=parent
        if isinstance(preview, dict) and preview.get("file"):
            # 抽卡归属来自被点选卡片；素材/生成设置仍取当前编辑，不恢复旧组执行。
            if "round_no" in preview:
                trial_round = int(preview["round_no"] or 0)
                if not 0 <= trial_round <= max(int(parent.get("group_seq",1)),int(parent.get("round_no", 1) or 1)):
                    raise ValueError("所选卡片组号无效，请重新选择原预览")
            if trial_round and trial_round!=int(parent.get("round_no",1)):
                from .group_history import lookup,archive
                origin_state=lookup(STORE,parent,trial_round,data.get("group_previews") or [preview])
                archive(STORE,origin_state)
                parent.setdefault('group_snapshots',{}).update(origin_state.get('group_snapshots') or {})
            target = resolve_resume_anchor(origin_state, preview, target + 1) - 1
        parent_segments = parent.get("segments") or []
        origin_segments = origin_state.get("segments") or []
        if target < 0 or (target >= len(parent_segments) and not data.get("draft_target")):
            raise ValueError("无效段号")
        if origin_state is not parent and not 0 <= target < len(origin_segments):
            # 旧轮快照里已没有该段：不能越界取段（避免 IndexError），明确提示重新选卡。
            raise ValueError("所选预览对应的原轮分段已改变，请重新选择原预览")
        child_id = "trial_" + uuid.uuid4().hex
        node_id = str(data["segment_node"])
        graph = copy.deepcopy(data["prompt"])
        graph[node_id]["inputs"]["session_id"] = child_id
        graph[node_id]["inputs"].pop("run_token", None)
        queue_id = str(graph[node_id]["inputs"]["queue"][0])
        for name in ("queue_state", "h3_editor_state"):
            if name in graph[queue_id]["inputs"]:
                value = graph[queue_id]["inputs"][name]
                value = json.loads(value) if isinstance(value, str) else copy.deepcopy(value)
                value["session_id"] = child_id
                graph[queue_id]["inputs"][name] = json.dumps(value, ensure_ascii=False)
        child = sync_graph_now({**data, "prompt": graph, "session_id": child_id})
        if target >= len(child["segments"]):
            raise ValueError("当前编辑内容中已没有这个段号，请选择仍然存在的片段试跑")
        # 回抽锚点/潜桥链：旧轮锁该轮结构与父 latent；设置仍取当前编辑（提示词/参考/参数）。
        relay_on = _relay_choice(data.get("prompt") or {}, node_id)
        interval = relay_reanchor_interval(graph[node_id]["inputs"].get("潜桥重锚定"))
        reanchor = relay_reanchors(interval, target)
        if origin_state is not parent:
            _validate_old_round_plan(origin_segments, child.get("segments") or [], trial_round)
            chain_run = _plan_old_round_reroll(sid, parent, origin_state, target, preview,
                                               trial_round, relay_on, reanchor)
        else:
            chain_run = _plan_current_reroll(sid, parent, target, preview, relay_on, reanchor)
        request = uuid.uuid4().hex
        # 前段尾帧只读原轮选用版本；将元数据拷入独立会话，文件仍由原轮保管。
        for index in range(target):
            row = origin_segments[index] if index < len(origin_segments) else None
            if row is None:
                continue
            child["segments"][index].update(versions=copy.deepcopy(row["versions"]),
                                            selected=row["selected"], valid=row["valid"], accepted=row["accepted"])
        reset_id = origin_state.get("reset_id", "legacy")
        prior = origin_segments[target].get("versions", []) if 0 <= target < len(origin_segments) else []
        prior = [v for v in prior if v.get("preview_only") and not v.get("archived") and v.get("reset_id", "legacy") == reset_id]
        redraw_count = max([len(prior), *(int(v.get("redraw_count") or 0) for v in prior)]) + 1
        child.update(cursor=target, auto=False, status="ready", reset_id=reset_id,
                     # 保留被抽卡片的组号，即使父会话已清空进入下一组。
                     round_no=trial_round,
                     preview_parent={"session_id": sid, "epoch": parent["epoch"], "request_id": request,
                                     "index": target, "redraw_count": redraw_count,
                                     # 桥接必须读卡片所属轮次自己的潜桥链（历史轮/旧批次也不例外）。
                                     "relay_run_id": chain_run or "",
                                     "group_label": "第 %d 轮" % int(trial_round),
                                     "segment_key": parent_segments[target]["segment_key"] if 0 <= target < len(parent_segments) else None})
        if origin_state is not parent:
            child["preview_parent"]["group_file"]=(parent.get('group_snapshots') or {}).get(str(trial_round))
            child["preview_parent"]["segment_key"]=origin_segments[target]["segment_key"]
        STORE._save(child)
        freeze(child, graph, node_id, data.get("workflow"))
        parent.pop("trial_notice", None)
        parent["draft_trial"] = {"session_id": child_id, "request_id": request, "target": target}
        return STORE._save(parent)


def finish_trial(child_id, success=True):
    child = STORE.read(child_id)
    source = child.get("preview_parent")
    if not source:
        return
    sid = source["session_id"]
    with STORE.lock(sid):
        parent = STORE._load(sid)
        pending = parent.get("draft_trial") or {}
        if pending.get("request_id") != source["request_id"]:
            return  # 已停止/清空的迟到试跑只留在自己的会话中。
        if parent["epoch"] != source["epoch"]:
            return
        destination=parent
        if source.get("group_file"):
            with contained(STORE.directory(sid),source["group_file"]).open(encoding="utf-8") as handle:destination=json.load(handle)
        row = destination["segments"][source["index"]] if source.get("segment_key") else None
        if row is not None and row["segment_key"] != source["segment_key"]:
            raise ValueError("试跑对应的原段已改变；试跑文件已保留")
        if success:
            trial_row = child["segments"][source["index"]]
            version = next((v for v in trial_row["versions"] if v["id"] == trial_row["selected"]), None)
            if version:
                version = copy.deepcopy(version)
                trial_file = version.get("file")
                # 备选文件留在独立会话，用限定相对路径供历史/合并统一读取。
                # 原会话另建唯一硬链接（跨盘则独占创建），不覆盖任何历史文件。
                for key in ("file", "tail_file", "overlap_file", "audio_file", "continuum_file"):
                    if not version.get(key):
                        continue
                    src = contained(STORE.directory(child_id), version[key])
                    name = "trial_" + source["request_id"] + "_" + src.name
                    dst = contained(STORE.directory(sid), name)
                    if not dst.exists():
                        try:
                            os.link(src, dst)
                        except FileExistsError:
                            pass
                        except OSError:
                            with src.open("rb") as incoming, dst.open("xb") as output:
                                shutil.copyfileobj(incoming, output)
                    version[key] = name
                    if key == "continuum_file" and src.with_suffix(".json").is_file():
                        metadata = dst.with_suffix(".json")
                        if not metadata.exists():
                            with src.with_suffix(".json").open("rb") as incoming, metadata.open("xb") as output:
                                shutil.copyfileobj(incoming, output)
                version.update(preview_only=True, round_no=child.get("round_no", 0), trial_request=source["request_id"],
                               redraw_count=source.get("redraw_count", 0),
                               trial_session=child_id, trial_file=trial_file)
                versions = row["versions"] if row is not None else parent.setdefault("draft_candidates", [])
                version["draft_index"] = source["index"]
                if not any(v.get("trial_request") == source["request_id"] for v in versions):
                    versions.append(version)
                if parent.get("auto_accept") and row is not None and child.get("round_no")==destination.get("round_no"):
                    # 新界面生成即通过：最新抽卡结果直接成为该段当前选用/通过版本，不改变游标。
                    # 但潜桥 latent 提升必须成功才能选定；失败时不能带着旧父 latent 继续。
                    relay_version = bool(version.get("relay_run_id") and version.get("relay_save_run_id"))
                    promoted = (STORE._promote_relay_stage(destination, row, version)
                                if relay_version else True)
                    if promoted:
                        row["selected"] = version["id"]
                        row["valid"] = True
                        row["accepted"] = True
                        if destination is not parent:
                            # 回抽旧轮：后续段只加“待更新”提示，不失效、不阻断合并。
                            target_index = int(source["index"])
                            for index, after in enumerate(destination.get("segments") or []):
                                if index > target_index:
                                    after["stale_after_reroll"] = True
                            parent["trial_notice"] = (
                                "已回抽第 %d 轮第 %d 段，结果归该轮；后续段如需画面连续可自行重跑（不强制）。"
                                % (int(child.get("round_no", 0) or 0), target_index + 1))
                    else:
                        parent["error"] = (
                            "本段抽卡结果已登记，但潜桥 latent 提升失败，未作为当前选用；"
                            "请重跑该段后再继续，避免下一段接错父 latent。")
        if destination is not parent:
            atomic_json(contained(STORE.directory(sid),source["group_file"]),destination)
        parent.pop("draft_trial", None)
        STORE._save(parent)


def cancel_trial(sid, request_id=None):
    with STORE.lock(sid):
        parent = STORE._load(sid)
        pending = parent.get("draft_trial")
        if not pending or request_id and request_id != pending["request_id"]:
            return parent
        parent.pop("draft_trial", None)
        STORE._save(parent)
    STORE.action(pending["session_id"], "stop")
    return STORE.read(sid)


def prompt_handler(data):
    # /round/prepare 已经处理过的提交会带标记（工作流前端在提交副本的 extra 中写入）；
    # 这里跳过二次 prepare，避免每次排队重复 sync/freeze、重复写轮次快照。
    prepared_extra = (((data.get("extra_data") or {}).get("extra_pnginfo") or {}).get("workflow") or {}).get("extra") or {}
    if data.pop("ad_round_prepared", False) or prepared_extra.get("ad_round_prepared"):
        return data
    if not any(n.get("class_type") == "AidenH3Segment" for n in (data.get("prompt") or {}).values()):
        return data
    try:
        prepared = prepare({"prompt": data["prompt"],
                            "workflow": (data.get("extra_data") or {}).get("extra_pnginfo", {}).get("workflow", {})})
        data["prompt"] = prepared["prompt"]
        if prepared["rounds"] and prepared.get("workflow"):
            data.setdefault("extra_data", {}).setdefault("extra_pnginfo", {})["workflow"] = prepared["workflow"]
    except Exception as exc:
        # ComfyUI 的 hook 会吞异常：用已注册的“排队保护”节点阻断执行，
        # 让用户在本轮错误里看到真实原因；不能悄悄使用新编辑。
        data["prompt"] = {"AD_round_error": {"class_type": "AD_RoundBlocked",
                                             "inputs": {"reason": str(exc)}}}
        if data.get("partial_execution_targets") is not None:
            data["partial_execution_targets"] = ["AD_round_error"]
    return data
