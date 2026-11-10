// Canvas-only status: no widget, port, node size or workflow data changes.
const viewers = new Map();
let installed = false, currentPrompt = "";
const clamp = value => Math.max(0, Math.min(1, value));
const phases = {
    queued: {text: "排队中", color: "#8fb8e8"},
    running: {text: "生成中", color: "#35e0a0"},
    merging: {text: "合并中", color: "#5cc8ff"},
    review: {text: "已完成待继续", color: "#e6c15e"},
    paused: {text: "已停止", color: "#93a4b5"},
    error: {text: "出错了", color: "#ff7070"},
    completed: {text: "已完成", color: "#5cc8ff"},
    ready: {text: "待生成", color: "#8fb8e8"},
};
const phaseOf = p => phases[p?.phase] || phases.ready;
const fmtIndex = value => String(Math.max(0, Number(value) || 0)).padStart(2, "0");

function roundRect(ctx, x, y, width, height, radius) {
    const r = Math.max(0, Math.min(radius, Math.abs(width) / 2, Math.abs(height) / 2));
    ctx.beginPath();
    if (typeof ctx.roundRect === "function") {
        ctx.roundRect(x, y, width, height, r);
        return;
    }
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + width - r, y);
    ctx.quadraticCurveTo(x + width, y, x + width, y + r);
    ctx.lineTo(x + width, y + height - r);
    ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
    ctx.lineTo(x + r, y + height);
    ctx.quadraticCurveTo(x, y + height, x, y + height - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
}

function fillRound(ctx, x, y, width, height, radius) {
    roundRect(ctx, x, y, width, height, radius);
    ctx.fill();
}

function strokeRound(ctx, x, y, width, height, radius) {
    roundRect(ctx, x, y, width, height, radius);
    ctx.stroke();
}

function fitText(ctx, text, width) {
    const value = String(text || "");
    if (!value || typeof ctx.measureText !== "function") return value;
    if (ctx.measureText(value).width <= width) return value;
    let cut = value;
    while (cut.length > 1 && ctx.measureText(cut + "…").width > width) cut = cut.slice(0, -1);
    return cut + "…";
}

// 大尺寸“分段进度面板”：只保留大号段号与“当前段/总段数”，其余全部去掉并放大。
function drawSegmentProgress(ctx, node, progress) {
    const detail = progress.detail;
    const width = node.size?.[0] || 0;
    const height = node.size?.[1] || 0;
    const index = Math.max(0, Number(detail.index) || 0);
    const total = Math.max(0, Number(detail.total) || 0);
    const green = "#3ee6a4";

    // 窄节点仍退化为标题栏紧凑提示，避免没有位置放大。
    const panelX = 8;
    const panelW = Math.max(0, width - 134);
    if (panelW < 150 || height < 220) {
        drawCompactBadge(ctx, node, progress, green, index, total);
        return;
    }

    const left = panelX;
    const right = panelX + panelW;
    const hero = `${fmtIndex(index + 1)} / ${fmtIndex(total)}`;
    // 放大：按可用宽度和节点高度同时约束，最多 68px。
    const heroFont = Math.max(36, Math.min(68, Math.min(panelW * 0.24, height * 0.13)));
    // 固定在节点上部第一块留白区（黄框位置）；节点拉高时也不再下移。
    const heroY = Math.max(90, Math.min(130, height * 0.22));
    ctx.save();
    try {
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.font = `700 ${heroFont}px 'Microsoft YaHei', 'Segoe UI', sans-serif`;
        const heroGradient = ctx.createLinearGradient(left, heroY, right, heroY);
        heroGradient.addColorStop(0, "#d9ffe9");
        heroGradient.addColorStop(0.5, green);
        heroGradient.addColorStop(1, "#8effc6");
        ctx.fillStyle = heroGradient;
        ctx.fillText(hero, panelX + panelW / 2, heroY);
        ctx.fillStyle = "rgba(160,255,209,0.62)";
        ctx.font = "14px 'Microsoft YaHei', sans-serif";
        ctx.fillText("当前段 / 总段数", panelX + panelW / 2, heroY + heroFont * 0.72);
    } finally {
        ctx.restore();
    }
}

// 窄节点/折叠后的紧凑模式：标题栏胶囊 + 顶部细轨。
function drawCompactBadge(ctx, node, progress, accent, index, total) {
    const detail = progress.detail;
    const width = node.size?.[0] || 0;
    const text = `${fmtIndex(index + 1)}/${fmtIndex(total)} · ${(phases[progress.phase] || phases.running).text}`;
    ctx.save();
    try {
        ctx.font = "600 11px 'Microsoft YaHei', sans-serif";
        const textW = typeof ctx.measureText === "function" ? ctx.measureText(text).width : text.length * 11;
        const pillW = Math.min(Math.max(118, textW + 24), Math.max(0, width - 12));
        const x = width - pillW - 6;
        const y = -25;
        ctx.fillStyle = accent;
        ctx.beginPath();
        ctx.arc(x + 6, y + 8.5, 3, 0, Math.PI * 2);
        ctx.fill();
        ctx.textAlign = "left";
        ctx.textBaseline = "middle";
        ctx.fillStyle = "#a6ffcf";
        ctx.fillText(fitText(ctx, text, pillW - 14), x + 13, y + 9);

        // 顶部边缘的分段进度轨
        const trackX = 4, trackW = Math.max(0, width - 8);
        const count = Math.max(1, Number(detail.total) || 0);
        const states = Array.isArray(detail.segments) ? detail.segments : [];
        if (states.length === count && count <= 30) {
            const gap = 2;
            const cell = Math.max(2, (trackW - gap * (count - 1)) / count);
            for (let i = 0; i < count; i++) {
                ctx.fillStyle = states[i] === "done" ? accent : states[i] === "active" ? "#e9ffff" : "rgba(93,112,134,0.4)";
                ctx.fillRect(trackX + i * (cell + gap), 0, cell, 4);
            }
        } else {
            ctx.fillStyle = accent;
            ctx.fillRect(trackX, 0, trackW * clamp((Number(detail.done) || 0) / count), 4);
        }
    } finally {
        ctx.restore();
    }
}

// 其它节点（素材准备/分段预览）保留原来的紧凑顶部进度条。
function drawSimpleProgress(ctx, node, progress) {
    const width = Math.max(0, (node.size?.[0] || 0) - 8);
    const color = progress.phase === "error" ? "#ef6666" : progress.phase === "paused" ? "#84948b"
        : progress.phase === "review" ? "#dfbf62" : "#35d878";
    ctx.fillStyle = "#20362b";
    ctx.fillRect(4, 0, width, 4);
    ctx.fillStyle = color;
    if (progress.fraction === null) {
        for (let x = 4; x < width + 4; x += 16) ctx.fillRect(x, 0, Math.min(8, width + 4 - x), 4);
    } else ctx.fillRect(4, 0, width * clamp(progress.fraction), 4);
    ctx.font = "11px 'Microsoft YaHei', sans-serif";
    ctx.textAlign = "right";
    ctx.fillStyle = color;
    ctx.fillText(progress.text || "", node.size?.[0] - 9, -7, Math.max(0, (node.size?.[0] || 0) - 170));
}

function stopAnimation(node) {
    if (node._adH3ProgressTimer) {
        clearInterval(node._adH3ProgressTimer);
        node._adH3ProgressTimer = null;
    }
}

function syncAnimation(node, progress) {
    const busy = ["queued", "running", "merging"].includes(progress.phase) && !!progress.detail;
    if (busy && !node._adH3ProgressTimer) {
        node._adH3ProgressTimer = setInterval(() => {
            if (!node._adH3Progress) { stopAnimation(node); return; }
            // 折叠节点直接停表，不请求重绘；展开后下一次状态更新会重新启动。
            if (node.flags?.collapsed) { stopAnimation(node); return; }
            node.setDirtyCanvas?.(true, false);
        }, 120);
    } else if (!busy) stopAnimation(node);
}

export function mountNodeProgress(node) {
    if (node._adH3ProgressMounted) return;
    node._adH3ProgressMounted = true;
    const draw = node.onDrawForeground;
    node.onDrawForeground = function(ctx) {
        const result = draw?.apply(this, arguments);
        const p = this._adH3Progress;
        if (!ctx || !p || this.flags?.collapsed) return result;
        ctx.save();
        try {
            if (p.detail) drawSegmentProgress(ctx, this, p);
            else drawSimpleProgress(ctx, this, p);
        } finally {
            ctx.restore();
        }
        return result;
    };
    const removed = node.onRemoved;
    node.onRemoved = function() {
        stopAnimation(this);
        // 删除预览节点时，它关联的分段/素材节点动画也要回收，不能只停预览自己的定时器。
        for (const [viewer, group] of viewers) {
            if (viewer !== this) continue;
            stopAnimation(group.segment);
            stopAnimation(group.queue);
            viewers.delete(viewer);
        }
        return removed?.apply(this, arguments);
    };
}

function setProgress(node, progress) {
    if (!node) return;
    mountNodeProgress(node);
    node._adH3Progress = {...progress, fraction: Number.isFinite(progress.fraction) ? clamp(progress.fraction) : null};
    syncAnimation(node, node._adH3Progress);
    node.setDirtyCanvas?.(true, false);
}

export function setMaterialProgress(node, progress) {
    node._adH3LocalProgress = {busy: !!progress.busy};
    setProgress(node, progress);
}

export function updateSessionProgress(viewer, segment, queue, state) {
    const total = state.segments?.length || 0;
    if (!total) return;
    const rawIndex = Number(state.execution?.index ?? state.cursor) || 0;
    const index = Math.min(Math.max(rawIndex, 0), Math.max(0, total - 1));
    const done = state.segments.filter(row => row.valid && row.accepted).length;
    const busy = ["queued", "running", "merging"].includes(state.status);
    const names = {queued: "排队中", running: "生成中", merging: "合并中", review: "已完成待继续",
        paused: "已停止", error: "出错了", completed: "已完成", ready: "待生成"};
    const prefix = state.draft_trial ? `试跑第 ${index+1} 段` : `第 ${index + 1}/${total} 段`;
    const promptId = state.execution?.prompt_id || "";
    const previous = viewers.get(viewer);
    const sampling = busy && state.status !== "merging" && promptId && previous?.promptId === promptId ? previous.sampling : null;
    const fraction = sampling ?? (state.status === "completed" ? 1 : busy ? null : state.segments[index]?.valid ? 1 : 0);
    const segmentStates = state.segments.map((row, i) => {
        if (i === index && busy) return "active";
        if (row.valid && row.accepted) return "done";
        if (row.boundary_changed) return "invalid";
        return "pending";
    });
    setProgress(segment, {
        phase: state.status, fraction,
        text: sampling !== null ? `${prefix} · 执行 ${Math.round(sampling * 100)}%` : `${prefix} · ${names[state.status] || state.status}`,
        detail: {index, total, done, segments: segmentStates, trial: !!state.draft_trial},
    });
    const summary = {phase: state.status, fraction: done / total,
        text: `完成 ${done}/${total} · ${names[state.status] || state.status}`};
    setProgress(viewer, summary);
    if (!queue?._adH3LocalProgress?.busy) setProgress(queue, summary);
    viewers.set(viewer, {segment, queue, promptId, busy, state, sampling});
}

export function installProgressEvents(api) {
    if (installed) return;
    installed = true;
    api.addEventListener("execution_start", event => { currentPrompt = event.detail?.prompt_id || ""; });
    api.addEventListener("progress", event => {
        const data = event.detail || {}, promptId = data.prompt_id || currentPrompt;
        if (!promptId || !(Number(data.max) > 0) || !Number.isFinite(Number(data.value))) return;
        for (const [viewer, group] of viewers) {
            if (!group.busy || group.promptId !== promptId) continue;
            group.sampling = clamp(Number(data.value) / Number(data.max));
            updateSessionProgress(viewer, group.segment, group.queue, group.state);
        }
    });
    for (const name of ["execution_error", "execution_interrupted", "execution_success"]) api.addEventListener(name, event => {
        const promptId = event.detail?.prompt_id || "";
        if (currentPrompt === promptId) currentPrompt = "";
        for (const [viewer, group] of viewers) {
            if (!promptId || group.promptId !== promptId) continue;
            group.busy = false; group.sampling = null;
            // 任务成功也要先回收呼吸/重绘定时器；最终完成/待审核状态由持久化进度轮询更新。
            if (name === "execution_success") {
                stopAnimation(group.segment);
                stopAnimation(group.queue);
                stopAnimation(viewer);
                continue;
            }
            const phase = name === "execution_error" ? "error" : "paused";
            updateSessionProgress(viewer, group.segment, group.queue, {...group.state, status: phase});
        }
    });
}
