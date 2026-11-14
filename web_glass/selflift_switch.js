// A front-end control for the existing, explicitly wired ComfySwitchNode.
// The native switch widget remains the serialized source of truth.
const kind = node => String(node?.comfyClass || node?.type || "");
const isSampler = node => /Sampler/.test(kind(node));
const isSelfLift = node => /SelfLift/i.test(kind(node)) && isSampler(node);
function inputLink(node, name) {
    const input = node?.inputs?.find(item => item.name === name);
    const graph = node?.graph;
    return graph?.links?.get?.(input?.link) || graph?.links?.[input?.link] || null;
}
function source(node, name) {
    const link = inputLink(node, name);
    return link ? node.graph?.getNodeById?.(link.origin_id) || null : null;
}
function controlOf(node) {
    return node?.widgets?.find(item => item.name === "switch") || null;
}
function selectedSource(node) {
    const control = controlOf(node);
    if (inputLink(node, "switch") || typeof control?.value !== "boolean") return null;
    return source(node, control.value ? "on_true" : "on_false");
}
function previous(node) {
    if (kind(node) === "ComfySwitchNode") return selectedSource(node);
    for (const name of ["samples", "latent", "images"]) {
        const upstream = source(node, name);
        if (upstream) return upstream;
    }
    if (/Reroute/i.test(kind(node)) && node.inputs?.length === 1) return source(node, node.inputs[0].name);
    return null;
}
function samplerFrom(node) {
    const seen = new Set();
    while (node && seen.size < 64 && !seen.has(node)) {
        seen.add(node);
        if (isSampler(node)) return node;
        node = previous(node);
    }
    return null;
}
function chainFor(segment) {
    const graph = segment?.graph;
    const previews = (graph?._nodes || []).filter(node => kind(node) === "AidenH3VideoPreview"
        && source(node, "context") === segment);
    const candidates = new Map();
    for (const preview of previews) {
        const create = source(preview, "media") || source(preview, "video");
        if (!kind(create).includes("CreateVideo")) continue;
        let node = source(create, "images");
        const seen = new Set();
        while (node && seen.size < 64 && !seen.has(node)) {
            seen.add(node);
            if (isSampler(node)) break;
            if (kind(node) === "ComfySwitchNode") {
                const onTrue = samplerFrom(source(node, "on_true"));
                const onFalse = samplerFrom(source(node, "on_false"));
                if (onTrue && onFalse && isSelfLift(onTrue) !== isSelfLift(onFalse)) {
                    candidates.set(node, {target: node, selfliftOnTrue: isSelfLift(onTrue)});
                    break;
                }
            }
            node = previous(node);
        }
    }
    return {previews, candidates: [...candidates.values()]};
}
export function inspectSelfLiftSwitch(segment) {
    const {previews, candidates} = chainFor(segment);
    const fail = reason => ({ok: false, previews, reason});
    if (candidates.length !== 1) return fail(candidates.length
        ? "本条生成链有多个 SelfLift 切换节点，无法确定要控制哪一个。"
        : "请保留外置切换节点，并将 SelfLift 与其它采样分支接到本条视频解码链。");
    const candidate = candidates[0];
    for (const other of segment.graph?._nodes || []) {
        if (other !== segment && kind(other) === "AidenH3Segment"
            && chainFor(other).candidates.some(item => item.target === candidate.target))
            return fail("此切换节点被多个分段生成节点共用，请为每条生成链使用独立切换节点。");
    }
    const control = controlOf(candidate.target);
    if (inputLink(candidate.target, "switch") || typeof control?.value !== "boolean")
        return fail("外置切换节点的 switch 由连线控制，请先改为固定的开启或关闭值。");
    if ([2, 4].includes(candidate.target.mode)) return fail("外置切换节点已禁用或旁路，请先恢复该节点。");
    return {...candidate, control, previews, ok: true, enabled: control.value === candidate.selfliftOnTrue};
}
export function selfLiftSwitchBusy(segment, previews = []) {
    return [segment, ...previews].some(node => node?._adH3BatchRunning || node?._adH3AffectedRunning
        || node?._adH3LocalProgress?.busy || ["queued", "running", "merging"].includes(node?._adH3Progress?.phase));
}
export function setSelfLiftEnabled(segment, enabled) {
    const binding = inspectSelfLiftSwitch(segment);
    if (!binding.ok) return {ok: false, reason: binding.reason};
    if (selfLiftSwitchBusy(segment, binding.previews)) return {ok: false, reason: "生成或分段循环运行中，请先停止再切换采样器。"};
    const value = enabled ? binding.selfliftOnTrue : !binding.selfliftOnTrue;
    if (value === binding.control.value) return {ok: true};
    const graph = segment.graph, before = binding.control.value;
    graph.beforeChange?.();
    try {
        binding.control.value = value;
        binding.control.callback?.call(binding.control, value);
    } catch (error) {
        binding.control.value = before;
        return {ok: false, reason: "切换采样器失败：" + error.message};
    } finally { graph.afterChange?.(); }
    graph.change?.();
    segment.setDirtyCanvas?.(true, true);
    binding.target.setDirtyCanvas?.(true, true);
    return {ok: true};
}
export function mountSelfLiftSwitch(node, {bindWidth = () => {}} = {}) {
    if (node._adH3SelfLiftMounted) return;
    node._adH3SelfLiftMounted = true;
    const root = document.createElement("div");
    root.className = "ad-h3-selflift-switch";
    root.style.cssText = "display:flex;align-items:center;justify-content:space-between;gap:8px;padding:2px 8px;width:100%;height:32px;box-sizing:border-box;color:#d6e2f3;font:13px/1.3 'Microsoft YaHei',system-ui,sans-serif";
    const label = document.createElement("span");
    label.textContent = "SelfLift 采样";
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("role", "switch");
    button.setAttribute("aria-label", "SelfLift 采样");
    button.style.cssText = "flex:0 0 88px;min-width:70px;height:26px;padding:0 10px;border:1px solid #516583;border-radius:6px;color:#e8f1ff;font:inherit;cursor:pointer";
    root.append(label, button);
    const sync = () => {
        const binding = inspectSelfLiftSwitch(node);
        const busy = selfLiftSwitchBusy(node, binding.previews);
        button.disabled = !binding.ok || busy;
        button.textContent = binding.ok ? (binding.enabled ? "开启" : "关闭") : "未连接";
        button.setAttribute("aria-checked", String(!!binding.enabled));
        button.style.background = binding.enabled ? "#3275be" : "#263447";
        button.style.opacity = button.disabled ? "0.55" : "1";
        button.style.cursor = button.disabled ? "not-allowed" : "pointer";
        root.title = !binding.ok ? binding.reason : busy ? "生成或分段循环运行中，请先停止再切换采样器。"
            : "开启：SelfLift 采样；关闭：当前接入的其它采样。外置切换节点与采样参数保留。";
        button.title = root.title;
    };
    button.addEventListener("click", () => {
        const current = inspectSelfLiftSwitch(node);
        const result = setSelfLiftEnabled(node, !current.enabled);
        sync();
        if (!result.ok) window.alert(result.reason);
    });
    const widget = node.addDOMWidget("ad_h3_selflift_switch", "div", root, {
        serialize: false, hideOnZoom: false, getHeight: () => 32,
    });
    widget.serialize = false;
    widget.computeSize = width => [width, 32];
    bindWidth(node, widget);
    const list = node.widgets || [], index = list.indexOf(widget);
    if (index >= 0) list.splice(index, 1);
    const modeIndex = list.findIndex(item => item.name === "生成方式");
    list.splice(modeIndex >= 0 ? modeIndex + 1 : list.length, 0, widget);
    node._adH3SyncSelfLift = sync;
    const timer = setInterval(() => {
        if (!document.hidden && node.graph && root.isConnected) sync();
    }, 1000);
    const previousRemoved = node.onRemoved;
    node.onRemoved = function () {
        clearInterval(timer);
        return previousRemoved?.apply(this, arguments);
    };
    sync();
}
