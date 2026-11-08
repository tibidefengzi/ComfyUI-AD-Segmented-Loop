import {app} from "../../scripts/app.js";
import {currentTaskId} from "./workflow_task.js";
import {api} from "../../scripts/api.js";
import {executeQueueOnce,interruptOwnedPrompt} from "./queue_runner.js";
import {bindWidgetWidth} from "./dom_layout.js";
import {previewSources,finalSubmission,finalRecords} from "./final_queue.js";

const style = document.createElement("style");
style.textContent = `
.ad-final{box-sizing:border-box;width:100%;height:auto!important;min-height:0!important;max-height:none!important;flex:0 0 auto!important;align-self:start;min-width:0;padding:12px;background:transparent;border:1px solid #43536b;color:var(--ad-text,#e6e9ef);font:13px/1.5 var(--ad-font,"Microsoft YaHei",sans-serif);border-radius:12px}
.ad-final *{box-sizing:border-box}.ad-final button{font:inherit;cursor:pointer;border:1px solid var(--ad-accent-border,#4d7ed8);border-radius:var(--ad-radius-sm,5px);background:var(--ad-accent,#3769c7);color:#fff;padding:5px 12px;min-height:30px}.ad-final button:hover{background:var(--ad-accent-hover,#2f5cb2)}.ad-final button:disabled{opacity:.45;cursor:default}
.ad-final-tools,.ad-final-tabs{display:flex;gap:7px;flex-wrap:wrap;margin:8px 0}.ad-final-tabs{gap:6px}.ad-final-tabs button{background:var(--ad-surface-deep,#1e1e1e);border-color:var(--ad-border,#454545);color:var(--ad-text-dim,#aab3c2);border-radius:var(--ad-radius-sm,5px)}.ad-final-tabs button.on{background:var(--ad-accent,#3769c7);border-color:var(--ad-accent-border,#4d7ed8);color:#fff}
.ad-final-screen{width:100%;aspect-ratio:16/9;background:var(--ad-screen,#0d0d0d);position:relative;overflow:hidden;display:flex;align-items:center;justify-content:center;border:1px solid var(--ad-border-soft,#3a3a3a);border-radius:var(--ad-radius-sm,5px)}.ad-final-screen img,.ad-final-screen video{width:100%;height:100%;object-fit:contain}.ad-final-screen audio{width:90%}.ad-final-screen [hidden]{display:none}
.ad-final-ab{position:absolute;inset:0;overflow:hidden;background:#000;z-index:3;touch-action:none}
.ad-final-ab>img,.ad-final-ab>video{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;background:#000;pointer-events:none}
.ad-final-ab-b{clip-path:inset(0 0 0 50%)}
.ad-final-ab-divider{position:absolute;top:0;bottom:0;left:50%;width:2px;margin-left:-1px;background:#fff;box-shadow:0 0 0 1px #0009;cursor:ew-resize;z-index:5;touch-action:none}
.ad-final-ab-divider::after{content:"";position:absolute;left:50%;top:50%;width:34px;height:34px;border-radius:50%;background:#fff;border:2px solid #1b2430;box-shadow:0 2px 8px #0008;transform:translate(-50%,-50%)}
.ad-final-ab-labels{position:absolute;left:8px;right:8px;top:6px;display:flex;justify-content:space-between;color:#fff;font-size:12px;font-weight:700;text-shadow:0 1px 3px #000;pointer-events:none;z-index:6}
.ad-final-ab-hint{position:absolute;left:10px;right:10px;bottom:44px;color:var(--ad-warn,#e8c26a);font-size:12px;line-height:1.45;text-shadow:0 1px 3px #000;pointer-events:none;z-index:6}
.ad-final-ab-bar{position:absolute;left:0;right:0;bottom:0;display:flex;align-items:center;gap:8px;padding:6px 10px;background:#000b;z-index:7}
.ad-final-ab-bar button{min-height:28px;padding:3px 10px}
.ad-final-ab-bar input[type=range]{flex:1;min-width:80px}
.ad-final-ab-bar [data-ab-time]{color:#dfe7f3;font-size:12px;white-space:nowrap;min-width:112px;text-align:right}
.ad-final-ab[data-mode=image] .ad-final-ab-bar [data-ab-play],.ad-final-ab[data-mode=image] .ad-final-ab-bar [data-ab-seek],.ad-final-ab[data-mode=image] .ad-final-ab-bar [data-ab-time]{display:none}
.ad-final-ab[data-mode=image] .ad-final-ab-bar{justify-content:flex-end;background:#0008}
.ad-final-status{min-height:24px;overflow-wrap:anywhere;color:var(--ad-warn,#e8c26a);font-size:15px;font-weight:700;letter-spacing:.2px}.ad-final-status.error{color:var(--ad-danger-text,#ffb4b9)}.ad-final-row{display:flex;gap:8px;align-items:flex-start;width:100%;border:1px solid var(--ad-border-soft,#3a3a3a);border-radius:8px;background:var(--ad-surface,#252525);padding:4px 8px;min-height:104px;margin-top:6px}.ad-final-row>span{flex:0 0 72px;color:var(--ad-text-dim,#aab3c2);font-size:13px;padding-top:6px}.ad-final-list{display:flex;flex-wrap:wrap;gap:6px;max-height:340px;overflow:auto;flex:1;min-height:96px;padding:2px 0}.ad-final-list>span{color:var(--ad-text-mute,#8b95a3);font-size:12px;padding:6px}.ad-final-card{position:relative;padding:0!important;background:var(--ad-surface-deep,#1e1e1e)!important;flex:0 0 160px;width:160px;min-height:96px;overflow:hidden;border-color:var(--ad-border,#454545)!important;border-radius:7px}.ad-final-card img,.ad-final-card .audio{width:158px;height:89px;object-fit:contain;background:var(--ad-screen,#0d0d0d);display:block}.ad-final-card .audio{font-size:40px;line-height:89px}.ad-final-card span:last-child{display:block;font-size:12px;overflow-wrap:anywhere;padding:2px 4px}.ad-final-card .remove{position:absolute;right:3px;top:2px;background:#151b24bb;border-radius:3px;padding:0 5px;color:#fff}.ad-final-card.selected{outline:2px solid var(--ad-accent-soft,#92b7ff)}.ad-final-title{margin-top:8px;color:var(--ad-text-dim,#aab3c2)}.ad-h3-media-card.merge-selected{outline:2px solid var(--ad-accent-soft,#92b7ff)}
.ad-final-tools button.on{background:var(--ad-accent,#3769c7);border-color:var(--ad-accent-border,#4d7ed8);color:#fff;outline:2px solid var(--ad-accent-soft,#92b7ff)}
`;
document.head.append(style);
// 媒体地址统一走 ComfyUI 的 api.apiURL，origin/file 逐段编码（部署在子路径时也能正确访问）。
const mediaUrl = record => api.apiURL(`/aiden_h3/media/${encodeURIComponent(record.origin || "media")}/${String(record.file).split("/").map(encodeURIComponent).join("/")}`);
const thumbnailUrl = record => api.apiURL(`/aiden_h3/thumbnail/${encodeURIComponent(record.origin || "media")}/${String(record.file).split("/").map(encodeURIComponent).join("/")}`);
// 大分辨率/高帧率/非安全编码视频不再直接播放原文件：走后台预览代理。
// quality=lite（默认 720p/30fps）或 high（原分辨率/原帧率、yuv420p，硬件解码更接近原画）。
// 判断同时考虑尺寸、帧率、编码、像素格式、容器与码率，避免 4:4:4/10bit/高码率/H.265 直接播放。
const previewProxyUrl = (record, quality = "lite") => api.apiURL(`/aiden_h3/preview_proxy/${encodeURIComponent(record.origin || "media")}/${String(record.file).split("/").map(encodeURIComponent).join("/")}${quality === "high" ? "?quality=high" : ""}`);
const PROXY_SAFE_CODECS = new Set(["h264","av1","vp9"]);
const PROXY_SAFE_PIX_FMTS = new Set(["yuv420p","yuvj420p","nv12","nv21"]);
const PROXY_SAFE_CONTAINERS = new Set(["mp4","m4v","webm"]);
const PROXY_BITRATE_LIMIT = 16_000_000;
const needsPreviewProxy = record => {
    if(record?.kind !== "video")return false;
    if(Number(record.width) > 1920 || Number(record.height) > 1920 || Number(record.fps) > 30.5)return true;
    const pix = String(record.pix_fmt || "").trim().toLowerCase();
    if(pix && !PROXY_SAFE_PIX_FMTS.has(pix))return true;
    const codec = String(record.codec || "").trim().toLowerCase();
    if(codec && !PROXY_SAFE_CODECS.has(codec))return true;
    const container = String(record.container || String(record.file || "").split(".").pop() || "").trim().toLowerCase();
    if(container && !PROXY_SAFE_CONTAINERS.has(container))return true;
    const bitrate = Number(record.bitrate) || 0;
    if(bitrate > PROXY_BITRATE_LIMIT)return true;
    return false;
};
const label = record => record.label || record.file?.split("/").at(-1) || "成果";
const getWidget = (node,name) => node.widgets?.find(widget => widget.name === name);
async function request(path,body) {
    const response = await api.fetchApi(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) {const error = new Error(data.error || "操作失败");error.code=data.code;throw error;}
    return data;
}

export function mountFinalSave(node) {
    if (node._adFinal) return;
    // 与三个主节点统一外观：节点底色/边框/标签色和 AD-分段预览 保持一致。
    node.color="#414957";node.bgcolor="#2b303b";node.boxcolor="#6b8ec6";
    node.constructor.title_text_color="#eef3fa";
    const root=document.createElement("div"); root.className="ad-final";
    root.innerHTML=`<div class="ad-final-screen"><img hidden><video hidden controls controlslist="nodownload" playsinline preload="metadata"></video><audio hidden controls preload="metadata"></audio><span data-idle>在来源预览中选择成果，再点加工所选</span>
<div class="ad-final-ab" data-ab hidden><img data-ab-img-a alt="源" hidden><img data-ab-img-b class="ad-final-ab-b" alt="成品" hidden><video data-ab-video-a class="ad-final-ab-a" muted playsinline preload="auto" hidden></video><video data-ab-video-b class="ad-final-ab-b" muted playsinline preload="auto" hidden></video>
<div class="ad-final-ab-divider" data-ab-divider></div><div class="ad-final-ab-labels"><span>源 · 分段预览</span><span>成品 · 最终保存</span></div><div class="ad-final-ab-hint" data-ab-hint hidden></div>
<div class="ad-final-ab-bar"><button type="button" data-ab-play>播放</button><input type="range" data-ab-seek min="0" max="0" step="0.001" value="0" aria-label="对比播放位置"><span data-ab-time>0:00.00 / 0:00.00</span><button type="button" data-ab-retry hidden>重试</button><button type="button" data-ab-exit>退出对比</button></div></div>
</div>
<div class="ad-final-tools"><button data-start>加工所选</button><button data-stop>停止</button><button data-resume>继续剩余</button><button data-merge>合并片段</button><button data-ab-source hidden title="对比这条成品的源预览与最终成品">源/成品 A/B</button><button data-quality title="打开后预览/对比使用原分辨率、原帧率、yuv420p 高画质代理（硬件解码，接近原画）；关闭使用 720p/30fps 轻量预览">高画质预览</button><button data-download hidden title="保存当前成果的母版文件（最终_*.mp4），不是预览代理">下载母版</button></div>
<div class="ad-final-status" aria-live="polite"></div><div class="ad-final-tabs"><button data-kind="image">图片</button><button data-kind="audio">音频</button><button data-kind="video">视频</button></div>
<div class="ad-final-row"><span>最终成果</span><div class="ad-final-list" data-results></div></div><div class="ad-final-row"><span>合并成果</span><div class="ad-final-list" data-merges></div></div>`;
    const $=selector=>root.querySelector(selector);
    const hidden=getWidget(node,"source_record");
    if (hidden) {hidden.type="hidden";hidden.computeSize=()=>[0,-4];}
    if (getWidget(node,"帧序列帧率")) getWidget(node,"帧序列帧率").options.tooltip="仅用于直接输入的视频帧序列；0使用所选视频原帧率。VIDEO输入始终采用自身帧率。";
    const widgetTip=(name,tip)=>{const widget=getWidget(node,name);if(widget)widget.options.tooltip=tip;};
    widgetTip("母版画质","母版文件编码：默认 4:4:4 / CRF14（约21MB/5秒，保留色度）；CRF12 更保真，CRF16 更小；小文件档为 4:2:0/CRF19，仅分享用。不提供 CRF0。");
    // 旧字段（视频格式/像素格式/CRF）保留用于旧工作流兼容，但隐藏起来，只显示「母版画质」下拉。
    for (const name of ["视频格式","像素格式","CRF"]) {
        const widget=getWidget(node,name);
        if(widget){widget.type="hidden";widget.computeSize=()=>[0,-4];widget.hidden=true;}
    }
    // 旧工作流（v0.5.16 之前）里可能保存了「帧序列配套音频」输入口；后端已删除该输入，
    // 载入时把这条残留口和连线一起移除，避免用户看到一条无效 AUDIO 输入。
    const dropLegacyAudioInput = () => {
        const inputs = node.inputs || [];
        for (let index = inputs.length - 1; index >= 0; index--) {
            const input = inputs[index];
            if (!input || input.name !== "audio" || input.widget) continue;
            try { node.disconnectInput?.(index); } catch {}
            try { node.removeInput?.(index); } catch {}
            node.setDirtyCanvas?.(true, true);
        }
    };
    dropLegacyAudioInput();
    for (const input of node.inputs || []) if (input.name === "media") input.label = "处理后媒体（图片/音频/视频）";
    node.properties ||= {};
    let previewQuality = node.properties.ad_final_quality === "high" ? "high" : "lite";
    let records=node.properties.ad_final_records || [],kind=node.properties.ad_final_tab || "video",selected=new Map(),busy=false,preparing=false,stopped=false,disposed=false;
    let batch=node.properties.ad_final_batch || null,active=null,owner={};
    // 仅当渲染数据真正变化时才保存并标脏工作流，避免每次 render 都把工作流标记为已修改。
    let renderedStateKey="";
    const finalCards=new Map(),pages=new Map();
    const PAGE_SIZE=200;
    const video=$("video"),image=$("img"),audio=$("audio");video.muted=true;audio.muted=true;
    const abOverlay=$("[data-ab]"),abImgA=$("[data-ab-img-a]"),abImgB=$("[data-ab-img-b]");
    const abVideoA=$("[data-ab-video-a]"),abVideoB=$("[data-ab-video-b]");
    const abDivider=$("[data-ab-divider]"),abHint=$("[data-ab-hint]");
    const abPlay=$("[data-ab-play]"),abSeek=$("[data-ab-seek]"),abTime=$("[data-ab-time]"),abExit=$("[data-ab-exit]"),abRetry=$("[data-ab-retry]");
    let abOpen=false,abMode="",abRatio=.5,abDragging=false,abToken=0,abDuration=0;
    let abReadyA=false,abReadyB=false,abFailedA=false,abFailedB=false,abBuffering=false,abRecord=null,abSource=null;
    const qualityButton=$("[data-quality]"),downloadButton=$("[data-download]");
    const abClock=value=>{
        const total=Math.max(0,Number(value)||0),minutes=Math.floor(total/60),seconds=Math.floor(total%60),cents=Math.floor((total%1)*100);
        return `${minutes}:${String(seconds).padStart(2,"0")}.${String(cents).padStart(2,"0")}`;
    };
    const abSetHint=text=>{if(!abHint)return;abHint.textContent=text||"";abHint.hidden=!text;};
    const abSetRatio=value=>{
        abRatio=Math.min(.95,Math.max(.05,Number(value)||.5));
        const clip=`inset(0 0 0 ${(abRatio*100).toFixed(3)}%)`;
        for(const el of [abImgB,abVideoB])if(el)el.style.clipPath=clip;
        if(abDivider)abDivider.style.left=`${(abRatio*100).toFixed(3)}%`;
    };
    const abPause=()=>{try{abVideoA.pause();abVideoB.pause();}catch{}if(abPlay)abPlay.textContent="播放";};
    const abToggleControls=ready=>{if(abPlay)abPlay.disabled=!ready;if(abSeek)abSeek.disabled=!ready;};
    const abSideLabel=(record,fallback)=>record?label(record):fallback;
    // 根据“两路是否就绪/是否失败/是否缓冲”统一刷新按钮、进度条和提示文案。
    const abRefresh=()=>{
        if(!abOpen||abMode!=="video")return;
        if(abFailedA||abFailedB){
            abPause();abToggleControls(false);
            if(abRetry)abRetry.hidden=false;
            
            const sides=[abFailedA?`源（${abSideLabel(abSource,"源")}）`:null,abFailedB?`成品（${abSideLabel(abRecord,"成品")}）`:null].filter(Boolean).join("、");
            const other=abFailedA&&abFailedB?"":"另一路可退出对比后单独查看；";
            abSetHint(`对比视频加载失败：${sides}。${other}可点「重试」重新加载，或退出对比。`);
            return;
        }
        if(abReadyA&&abReadyB){
            const durations=[abVideoA.duration,abVideoB.duration].map(Number).filter(value=>Number.isFinite(value)&&value>0);
            abDuration=durations.length?Math.min(...durations):0;
            abSeek.max=abDuration||1;abSeek.value=0;abSeek.disabled=false;abPlay.disabled=false;
            if(abRetry)abRetry.hidden=true;
            
            abTime.textContent=`0:00.00 / ${abClock(abDuration)}`;
            abSetHint("按时间同步播放；超分/插帧后帧号不对应，可用分界线看画面差异，或点「原画细节」做 1:1 静帧对比");
            return;
        }
        abPause();abToggleControls(false);
        
        const waiting=[];
        if(!abReadyA)waiting.push(`源（${abSideLabel(abSource,"源")}）`);
        if(!abReadyB)waiting.push(`成品（${abSideLabel(abRecord,"成品")}）`);
        abSetHint(`正在加载${waiting.join("、")}…（${previewQuality==="high"?"高画质":"轻量"}预览生成中，请稍候或退出对比）`);
    };
    const abResetView=()=>{
        abOpen=false;abToken++;abPause();abDragging=false;
        
        abReadyA=false;abReadyB=false;abFailedA=false;abFailedB=false;abBuffering=false;abRecord=null;abSource=null;
        if(abRetry)abRetry.hidden=true;
        
        abToggleControls(false);
        if(abOverlay)abOverlay.hidden=true;
        for(const el of [abImgA,abImgB,abVideoA,abVideoB]){
            if(!el)continue;el.onerror=null;el.onloadedmetadata=null;el.hidden=true;
            if(el.hasAttribute("src")){el.removeAttribute("src");try{el.load?.();}catch{}}
        }
        abSetHint("");abSeek.value=0;abSeek.max=0;abTime.textContent="0:00.00 / 0:00.00";abDuration=0;
        buttons();
    };
    // 方案 A：只用最终成果记录自带的 source_record 做“源 → 成品”对比，不新增输入口。
    const canAB=record=>{
        const source=record?.source_record;
        if(!record||!["image","video"].includes(record.kind)||!source?.origin||!source?.file)return false;
        return (source.kind||record.kind)===record.kind;
    };
    const abUrl=record=>record.kind==="video"&&needsPreviewProxy(record)?previewProxyUrl(record,previewQuality):mediaUrl(record);
    const updateQualityButton=()=>{
        if(!qualityButton)return;
        qualityButton.classList.toggle("on",previewQuality==="high");
        qualityButton.textContent=previewQuality==="high"?"高画质预览：开":"高画质预览";
    };
    const reloadActivePreview=()=>{
        
        if(abOpen){const record=active;abResetView();active=record;openAB();}
        else if(active)show(active);
        buttons();
    };
    const dirty=()=>{node.graph?.change?.();node.setDirtyCanvas?.(true,true);};
    const saveState=()=>{node.properties.ad_final_records=records;node.properties.ad_final_batch=batch;node.properties.ad_final_tab=kind;dirty();};
    const say=(text,error=false)=>{const box=$(".ad-final-status");box.textContent=text;box.classList.toggle("error",error);};
    // 进度行后面附带已选预览的信息（一直高亮显示，不自动收起）。
    const selectionSummary=()=>{
        const chosen=batch?.plan?.records||[];
        if(!chosen.length)return "";
        const text=chosen.map(record=>`${record.source_record?.role?record.source_record.role+" · ":""}${label(record)}`).join("、");
        return `（已选 ${chosen.length} 条：${text}）`;
    };
    const buttons=()=>{$("[data-start]").disabled=busy||preparing;$("[data-stop]").disabled=!busy;$("[data-resume]").disabled=busy||preparing||!batch||batch.cursor>=batch.plan.records.length;$("[data-merge]").disabled=busy||preparing;const ab=$("[data-ab-source]");if(ab){ab.hidden=!canAB(active);ab.disabled=busy||preparing||abOpen;}if(downloadButton){downloadButton.hidden=!(active&&!busy&&!preparing);downloadButton.disabled=!active||busy||preparing;}};
    const show=(record,{keepTime=0,autoPlay=false}={})=>{
        if(abOpen)abResetView();
        active=record;video.pause();audio.pause();
        video.onerror=null;video.onloadedmetadata=null;
        for(const media of [video,audio,image])media.hidden=true;
        $("[data-idle]").hidden=true;
        const media=record.kind==="video"?video:record.kind==="audio"?audio:image;
        const meta=`${label(record)}${record.width?` · ${record.width}×${record.height} · ${record.fps} FPS`:""}`;
        const useProxy=needsPreviewProxy(record);
        const proxyQuality=previewQuality;
        const qualityLabel=proxyQuality==="high"?"高画质":"轻量";
        const restoreTime=Number(keepTime)>0?Number(keepTime):0;
        if(record.kind==="video"){
            const restore=()=>{
                if(restoreTime>0){try{video.currentTime=Math.min(restoreTime,Math.max(0,(video.duration||0)-0.05));}catch{}}
                if(autoPlay)void video.play().catch(()=>{});
            };
            video.onloadedmetadata=()=>{
                if(media!==video)return;
                say(useProxy?`${meta} · ${qualityLabel}预览 ${video.videoWidth}×${video.videoHeight}（预览代理）`:meta);
                restore();
            };
            video.onerror=()=>{
                if(media!==video)return;
                // 方案1：节点内永不回退播放原文件；大文件代理失败只提示，避免浏览器解码卡死。
                video.pause();
                media.hidden=true;
                $("[data-idle]").hidden=false;
                say(useProxy?`${meta} · ${qualityLabel}预览生成失败，请稍后重试；原文件已保存，可下载/外部播放查看。`
                           :`${meta} · 视频加载失败，请稍后重试。`,true);
            };
            video.oncontextmenu=useProxy?(event=>{event.preventDefault();say("当前播放的是预览代理；请用「下载母版」保存原文件。",true);return false;}):null;
            media.src=useProxy?previewProxyUrl(record,proxyQuality):mediaUrl(record);
            say(useProxy?`${meta} · 正在生成${qualityLabel}预览…（预览代理，下载请用「下载母版」）`:meta);
        }else{
            media.src=mediaUrl(record);
            say(meta);
        }
        media.hidden=false;
        buttons();
    };
    const openAB=()=>{
        if(!canAB(active)||abOpen)return;
        
        const record=active,source=record.source_record;
        abRecord=record;abSource=source;
        abOpen=true;abToken++;abMode=record.kind;abDuration=0;
        abReadyA=false;abReadyB=false;abFailedA=false;abFailedB=false;abBuffering=false;
        abOverlay.hidden=false;abOverlay.dataset.mode=abMode;
        video.pause();audio.pause();
        for(const media of [video,audio,image])media.hidden=true;
        $("[data-idle]").hidden=true;
        abImgA.hidden=true;abImgB.hidden=true;abVideoA.hidden=true;abVideoB.hidden=true;
        abSeek.value=0;abSeek.max=0;abTime.textContent="0:00.00 / 0:00.00";abSetRatio(.5);abSetHint("");abToggleControls(false);
        if(abRetry)abRetry.hidden=true;
        
        buttons();
        if(abMode==="image"){
            abImgA.hidden=false;abImgB.hidden=false;
            abImgA.onerror=()=>{if(abOpen){abSetHint(`源图加载失败：${abSideLabel(source,"源")}。可点「重试」或退出对比后单独查看。`);if(abRetry)abRetry.hidden=false;}};
            abImgB.onerror=()=>{if(abOpen){abSetHint(`成品图加载失败：${abSideLabel(record,"成品")}。可点「重试」或退出对比后单独查看。`);if(abRetry)abRetry.hidden=false;}};
            abImgA.src=abUrl(source);abImgB.src=abUrl(record);
            abSetHint("源（左）vs 成品（右）：拖动中间分界线对比");
            return;
        }
        const token=abToken;
        abVideoA.hidden=false;abVideoB.hidden=false;
        abVideoA.onloadedmetadata=()=>{if(!abOpen||token!==abToken||abMode!=="video")return;abReadyA=true;abRefresh();};
        abVideoB.onloadedmetadata=()=>{if(!abOpen||token!==abToken||abMode!=="video")return;abReadyB=true;abRefresh();};
        abVideoA.onerror=()=>{if(!abOpen||token!==abToken||abMode!=="video")return;abFailedA=true;abRefresh();};
        abVideoB.onerror=()=>{if(!abOpen||token!==abToken||abMode!=="video")return;abFailedB=true;abRefresh();};
        abVideoA.src=abUrl(source);abVideoB.src=abUrl(record);
        abRefresh();
    };
    const closeAB=()=>{
        const record=active;
        abResetView();
        if(record)show(record);
    };
    abExit.onclick=()=>closeAB();
    if(abRetry)abRetry.onclick=()=>{
        if(!abOpen||!canAB(active))return;
        abResetView();
        openAB();
    };
    for(const [element,side] of [[abVideoA,"源"],[abVideoB,"成品"]]){
        element.addEventListener("waiting",()=>{
            if(!abOpen||abMode!=="video"||abFailedA||abFailedB)return;
            abBuffering=true;abSetHint(`对比播放缓冲中…（${side}）`);
        });
        element.addEventListener("playing",()=>{
            if(!abOpen||abMode!=="video"||abFailedA||abFailedB)return;
            // 缓冲结束只恢复提示，不重置进度条，避免播放中读数跳回 0。
            if(abBuffering){abBuffering=false;abSetHint("按时间同步播放；超分/插帧后帧号不对应，可用分界线看画面差异");}
        });
    }
    abDivider.addEventListener("pointerdown",event=>{
        if(!abOpen)return;abDragging=true;abDivider.setPointerCapture?.(event.pointerId);event.preventDefault();
    });
    abDivider.addEventListener("pointermove",event=>{
        if(!abOpen||!abDragging)return;
        const rect=abOverlay.getBoundingClientRect();
        if(rect.width>0)abSetRatio((event.clientX-rect.left)/rect.width);
    });
    abDivider.addEventListener("pointerup",()=>{abDragging=false;});
    abDivider.addEventListener("pointercancel",()=>{abDragging=false;});
    const abTogglePlay=()=>{
        if(!abOpen||abMode!=="video"||abFailedA||abFailedB||!abReadyA||!abReadyB)return;
        if(abVideoB.paused){
            if(abDuration>0&&abVideoB.currentTime>=abDuration-.05){abVideoB.currentTime=0;abVideoA.currentTime=0;}
            void abVideoB.play().catch(()=>{});
            void abVideoA.play().catch(()=>{});
        }else{
            abPause();
        }
    };
    abPlay.onclick=()=>abTogglePlay();
    // 点击对比画面 = 播放/停止；拖动分界线或点底部控件不触发。
    abOverlay.addEventListener("click",event=>{
        if(!abOpen||abMode!=="video")return;
        if(event.target?.closest?.(".ad-final-ab-bar, .ad-final-ab-divider, [data-ab-divider]"))return;
        abTogglePlay();
    });
    abVideoB.addEventListener("play",()=>{
        if(!abOpen||abMode!=="video")return;
        abPlay.textContent="暂停";
        void abVideoA.play().catch(()=>{});
    });
    abVideoB.addEventListener("pause",()=>{
        if(!abOpen||abMode!=="video")return;
        try{abVideoA.pause();}catch{}
        abPlay.textContent="播放";
    });
    abVideoB.addEventListener("timeupdate",()=>{
        if(!abOpen||abMode!=="video"||abFailedA||abFailedB)return;
        const duration=abDuration||abVideoB.duration||0;
        const time=Math.min(abVideoB.currentTime,duration||abVideoB.currentTime);
        abSeek.value=time;abTime.textContent=`${abClock(time)} / ${abClock(duration)}`;
        // 到两路较短时长：播放中则两路一起回到 0 一直循环；暂停中则停在末帧。
        if(abDuration>0&&abVideoB.currentTime>=abDuration-0.02){
            if(abVideoB.paused){
                try{abVideoB.currentTime=abDuration;abVideoA.currentTime=abDuration;}catch{}
                abSeek.value=abDuration;abTime.textContent=`${abClock(abDuration)} / ${abClock(abDuration)}`;abPlay.textContent="播放";
            }else{
                try{abVideoB.currentTime=0;abVideoA.currentTime=0;}catch{}
                abSeek.value=0;abTime.textContent=`0:00.00 / ${abClock(abDuration)}`;
                void abVideoB.play().catch(()=>{});void abVideoA.play().catch(()=>{});
            }
            return;
        }
        if(abVideoA.readyState>=1&&Math.abs(abVideoA.currentTime-time)>0.18){try{abVideoA.currentTime=time;}catch{}}
    });
    abVideoB.addEventListener("ended",()=>{
        if(!abOpen||abMode!=="video")return;
        if(!abVideoB.paused){
            try{abVideoB.currentTime=0;abVideoA.currentTime=0;}catch{}
            void abVideoB.play().catch(()=>{});void abVideoA.play().catch(()=>{});
            return;
        }
        abSeek.value=abDuration;abTime.textContent=`${abClock(abDuration)} / ${abClock(abDuration)}`;
    });
    abSeek.addEventListener("input",()=>{
        if(!abOpen||abMode!=="video"||abFailedA||abFailedB)return;
        const time=Number(abSeek.value)||0;
        try{abVideoB.currentTime=time;abVideoA.currentTime=time;}catch{}
        abTime.textContent=`${abClock(time)} / ${abClock(abDuration)}`;
    });
    $("[data-ab-source]").onclick=()=>openAB();
    if(qualityButton)qualityButton.onclick=()=>{
        if(busy||preparing)return;
        previewQuality=previewQuality==="high"?"lite":"high";
        node.properties.ad_final_quality=previewQuality;dirty();
        updateQualityButton();reloadActivePreview();
    };
    // 下载母版：只保存当前成果的最终文件（最终_*.mp4 / final_*.mp4），绝不下发 preview_* 代理。
    if(downloadButton)downloadButton.onclick=async()=>{
        const record=active;
        if(!record||busy||preparing)return;
        const defaultName=String(record.archive||record.file||"AD-final.mp4").split(/[\\/]/).pop();
        try{
            let target="";
            const picked=await api.fetchApi("/aiden_h3/pick_save_path",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({default_name:defaultName,initial_dir:"",kind:record.kind||"video",title:"下载母版：选择保存位置"})});
            if(picked&&picked.ok){const data=await picked.json();target=String(data.path||"").trim();}
            if(!target){say("已取消下载母版。");return;}
            const saved=await api.fetchApi("/aiden_h3/save_media",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({origin:record.origin||"media",file:record.file,target})});
            const result=await saved.json();
            if(!saved.ok)throw new Error(result.error||"保存母版失败");
            say(`母版已保存：${result.path}`);
        }catch(error){say(error.message||"下载母版失败",true);}
    };
    const key=record=>record.final_id || record.file;
    const paintSelection=()=>{for(const card of root.querySelectorAll(".ad-final-card"))card.classList.toggle("selected",selected.has(card.dataset.key));};
    const render=()=>{
        for(const button of root.querySelectorAll("[data-kind]"))button.classList.toggle("on",button.dataset.kind===kind);
        for(const [selector,merged] of [["[data-results]",false],["[data-merges]",true]]){
            const target=$(selector),all=records.filter(record=>record.kind===kind&&!!record.merged===merged),pageKey=`${kind}:${merged}`;
            const page=Math.min(pages.get(pageKey)||0,Math.max(0,Math.ceil(all.length/PAGE_SIZE)-1));pages.set(pageKey,page);
            const visible=all.slice(page*PAGE_SIZE,(page+1)*PAGE_SIZE),wanted=new Set(visible.map(key));
            for(const child of [...target.children])if(!wanted.has(child.dataset.key))child.remove();
            for(const [index,record] of visible.entries()){
                let card=finalCards.get(key(record));
                if(!card){
                    card=document.createElement("button");card.className="ad-final-card";card.dataset.key=key(record);
                    if(record.kind==="audio"){const icon=document.createElement("span");icon.className="audio";icon.textContent="♪";card.append(icon);}
                    else{const thumb=document.createElement("img");thumb.loading="lazy";thumb.decoding="async";thumb.src=thumbnailUrl(record);thumb.alt="";card.append(thumb);}
                    const remove=document.createElement("span");remove.className="remove";remove.textContent="×";remove.title="移除这条最终预览记录（文件保留）";
                    remove.onclick=event=>{event.stopPropagation();const wasActive=!!active&&key(active)===key(record);if(wasActive&&abOpen)abResetView();records=records.filter(item=>key(item)!==key(record));selected.delete(key(record));finalCards.delete(key(record));if(wasActive){video.pause();audio.pause();for(const media of [video,audio,image])media.hidden=true;$("[data-idle]").hidden=false;active=null;}render();};card.append(remove);
                    const text=document.createElement("span");text.textContent=`${record.source_record?.role?record.source_record.role+" · ":""}${label(record)}`;card.append(text);card.title=record.archive || label(record);
                    card.onclick=event=>{if(event.ctrlKey||event.metaKey){if(selected.has(key(record)))selected.delete(key(record));else selected.set(key(record),record);}else{selected.clear();selected.set(key(record),record);show(record);}paintSelection();};finalCards.set(key(record),card);
                }
                if(target.children[index]!==card)target.insertBefore(card,target.children[index]||null);
            }
            if(!visible.length){const empty=document.createElement("span");empty.textContent=merged?"暂无合并成果":"暂无最终成果";target.append(empty);}
            if(all.length>PAGE_SIZE){
                const pager=document.createElement("div");pager.className="ad-final-pager";pager.style.cssText="display:flex;align-items:center;gap:8px;flex-basis:100%;padding:4px 0";
                const previous=document.createElement("button"),next=document.createElement("button"),text=document.createElement("span");
                previous.textContent="上一页";next.textContent="下一页";previous.disabled=page===0;next.disabled=(page+1)*PAGE_SIZE>=all.length;
                text.textContent=`第 ${page+1}/${Math.ceil(all.length/PAGE_SIZE)} 页 · ${all.length} 条`;
                previous.onclick=()=>{pages.set(pageKey,page-1);render();};next.onclick=()=>{pages.set(pageKey,page+1);render();};pager.append(previous,text,next);target.append(pager);
            }
        }
        // 仅缓存本页卡片；完整成果与跨页选择仍保存在数据里。
        for(const [id,card] of finalCards)if(!root.contains(card))finalCards.delete(id);
        paintSelection();buttons();
        // 数据（记录/批次游标/分类）真正变化时才写属性并标脏工作流。
        const nextStateKey=JSON.stringify([kind,records.map(key),batch?.cursor??-1,batch?.status||""]);
        if(nextStateKey!==renderedStateKey){renderedStateKey=nextStateKey;saveState();}
    };
    const followPage=record=>{
        const list=records.filter(item=>item.kind===record.kind&&!!item.merged===!!record.merged);
        pages.set(`${record.kind}:${!!record.merged}`,Math.floor(Math.max(0,list.findIndex(item=>key(item)===key(record)))/PAGE_SIZE));
    };
    const accept=(job,token)=>{
        const result=finalRecords(job,batch.plan.final_id,token);
        for(const record of result)if(!records.some(item=>key(item)===key(record)))records.push(record);
        kind=result[0].kind;followPage(result[0]);show(result[0]);batch.cursor++;batch.pending=null;batch.status="ready";render();
    };
    const recover=async()=>{
        const pending=batch?.pending;if(!pending?.promptId)return false;
        const deadline=Date.now()+60000;
        while(!stopped&&!disposed){
            const response=await api.fetchApi('/history/'+encodeURIComponent(pending.promptId));if(!response.ok)throw Error('无法核对上次加工任务');
            const history=await response.json(),job=history[pending.promptId];
            if(job?.status?.status_str==="success"&&job.status.completed){accept(job,pending.token);return true;}
            if(job?.status?.status_str==="error"){batch.pending=null;saveState();return false;}
            const queueResponse=await api.fetchApi('/queue');if(!queueResponse.ok)throw Error('无法核对上次任务是否仍在执行');
            const queue=await queueResponse.json();
            const queued=[...(queue.queue_running||[]),...(queue.queue_pending||[])].some(row=>String(row[1])===pending.promptId);
            if(!queued){batch.pending=null;saveState();return false;}
            if(Date.now()>deadline)throw Error('上次加工任务尚未结束，请稍后点击继续剩余');
            say('等待上次加工任务结束后继续…');
            await new Promise(resolve=>setTimeout(resolve,400));
        }
        return false;
    };
    const run=async()=>{
        if(busy||!batch)return;busy=true;stopped=false;buttons();
        try{
            await recover();
            while(!stopped&&!disposed&&batch.cursor<batch.plan.records.length){
                const record=batch.plan.records[batch.cursor],token=crypto.randomUUID();
                batch.status="running";batch.pending={index:batch.cursor,token,promptId:null};saveState();
                say(`正在加工 ${label(record)}${selectionSummary()}`);
                owner={};Object.defineProperty(owner,"_adH3PromptId",{configurable:true,get:()=>batch?.pending?.promptId,set:id=>{batch.pending.promptId=id;saveState();}});
                const result=await executeQueueOnce(app,api,batch.plan.final_id,{serialized:finalSubmission(batch.plan,batch.cursor,token),owner,isStopped:()=>stopped||disposed});
                if(result.stopped)break;
                accept(result.job,token);
            }
            batch.status=batch.cursor>=batch.plan.records.length?"completed":"paused";
            if(!disposed)say((batch.status==="completed"?"所选成果已逐个加工并保存。":`已停止，保留已保存成果。`)+selectionSummary());
        }catch(error){if(batch)batch.status=stopped?"paused":"error";if(!disposed)say(stopped?"已停止，保留已保存成果。":error.message,!stopped);}
        finally{busy=false;buttons();saveState();}
    };
    $("[data-start]").onclick=async()=>{
        if(busy||preparing)return;
        preparing=true;buttons();
        try{
            const serialized=await app.graphToPrompt();
            const sources=previewSources(serialized.output,node.id);
            if(sources.length!==1)throw Error('请将一个分段预览的媒体输出接入处理链，再连接到最终保存');
            const preview=node.graph?.getNodeById?.(Number(sources[0])) || node.graph?.getNodeById?.(sources[0]);
            const chosen=preview?._adH3Preview?.processingSelection?.() || [];
            if(!chosen.length)throw Error('请先在来源预览中单击或Ctrl选择成果');
            const plan=await request('/aiden_h3/final/prepare',{prompt:serialized.output,final_id:String(node.id),records:chosen});
            plan.task_id=currentTaskId(node.graph);
            batch={plan,cursor:0,pending:null,status:"ready"};saveState();void run();
        }catch(error){say(error.message,true);}
        finally{preparing=false;buttons();}
    };
    $("[data-resume]").onclick=async()=>{
        if(busy||preparing||!batch)return;
        preparing=true;buttons();
        try{
            // 文件清单不变；重试采用用户当前修好的处理分支，不强迫使用失败时的参数。
            if(node.graph!==app.graph)throw Error('请回到该最终保存节点所在工作流再继续');
            const serialized=await app.graphToPrompt();
            const remaining=batch.plan.records.slice(batch.cursor);
            if(!remaining.length)return;
            const updated=await request('/aiden_h3/final/prepare',{prompt:serialized.output,final_id:String(node.id),records:remaining});
            updated.task_id=currentTaskId(node.graph);
            if(updated.source_id!==batch.plan.source_id)throw Error('来源预览已经改变，请重新选择成果并点击加工所选');
            batch.plan={...updated,records:[...batch.plan.records.slice(0,batch.cursor),...updated.records]};saveState();void run();
        }catch(error){say(error.message,true);}
        finally{preparing=false;buttons();}
    };
    $("[data-stop]").onclick=()=>{stopped=true;say('正在停止本次加工…');void interruptOwnedPrompt(api,owner).catch(error=>say(error.message,true));};
    for(const button of root.querySelectorAll('[data-kind]'))button.onclick=()=>{if(abOpen)abResetView();video.pause();audio.pause();kind=button.dataset.kind;selected.clear();active=null;for(const media of [video,audio,image])media.hidden=true;$("[data-idle]").hidden=false;render();};
    $("[data-merge]").onclick=async()=>{
        if(busy||preparing)return;
        const chosen=selected.size?[...selected.values()]:records.filter(record=>record.kind===kind&&!record.merged);
        if(chosen.some(record=>record.kind!==kind)){say('请在同一分类中选择合并成果',true);return;}
        const body={records:chosen,directory:getWidget(node,'保存目录')?.value||'',prefix:getWidget(node,'文件名前缀')?.value||'最终合并'};
        preparing=true;buttons();
        try{
            let result;
            try{result=await request('/aiden_h3/final/merge',body);}catch(error){if(error.code!=='spec_mismatch'||!window.confirm(error.message))throw error;result=await request('/aiden_h3/final/merge',{...body,normalize:true});}
            const record={...result.record,merged:true};records.push(record);selected.clear();followPage(record);render();show(record);
        }catch(error){say(error.message,true);}
        finally{preparing=false;buttons();}
    };
    const widget=node.addDOMWidget('ad_final_ui','custom',root,{serialize:false,hideOnZoom:false});
    widget.computeSize=()=>[Math.max(300,Number(node.size?.[0])||760),root.offsetHeight+12];bindWidgetWidth(node,widget);
    node.size=[Math.max(760,Number(node.size?.[0])||760),Number(node.size?.[1])||800];
    let resizeFrame=0;
    // 高度统一由 scheduleLayout 合并计算（ResizeObserver 只负责调度，不直接 setSize），避免多次回调反复改高度。
    const scheduleLayout=()=>{if(resizeFrame)return;resizeFrame=requestAnimationFrame(()=>{resizeFrame=0;if(disposed||!root.isConnected)return;const height=node.computeSize?.()[1];if(height&&Math.abs(node.size[1]-height)>2)node.setSize([node.size[0],height]);node.setDirtyCanvas?.(true,true);});};
    const observer=new ResizeObserver(scheduleLayout);observer.observe(root);
    const executed=node.onExecuted;node.onExecuted=function(message){const result=executed?.apply(this,arguments);const incoming=(message?.ad_final||[]).filter(r=>!r.source_record?.final_task_id||!this.properties.ad_task_id||r.source_record.final_task_id===this.properties.ad_task_id);for(const record of incoming)if(!records.some(item=>key(item)===key(record)))records.push(record);if(incoming.length){kind=incoming[0].kind;followPage(incoming[0]);render();show(incoming[0]);}return result;};
    const configured=node.onConfigure;node.onConfigure=function(){const result=configured?.apply(this,arguments);dropLegacyAudioInput();busy=false;preparing=false;finalCards.clear();pages.clear();records=this.properties.ad_final_records||[];batch=this.properties.ad_final_batch||null;kind=this.properties.ad_final_tab||'video';previewQuality=this.properties.ad_final_quality==="high"?"high":"lite";selected.clear();renderedStateKey=JSON.stringify([kind,records.map(key),batch?.cursor??-1,batch?.status||""]);render();updateQualityButton();return result;};
    const removed=node.onRemoved;node.onRemoved=function(){disposed=true;stopped=true;busy=false;preparing=false;observer.disconnect();if(resizeFrame)cancelAnimationFrame(resizeFrame);try{}catch{}try{if(abOpen)abResetView();}catch{}for(const media of [video,audio]){media.pause();if(media.hasAttribute("src")){media.removeAttribute("src");media.load();}}for(const image of root.querySelectorAll("img"))image.removeAttribute("src");finalCards.clear();root.remove();delete node._adFinal;return removed?.apply(this,arguments);};
    node._adFinal={root,run,selection:()=>[...selected.values()],get batch(){return batch;},resetTask(){if(abOpen)abResetView();records=[];batch=null;selected.clear();finalCards.clear();pages.clear();active=null;video.pause();audio.pause();for(const media of [video,audio,image])media.hidden=true;$("[data-idle]").hidden=false;render();}};
    render();updateQualityButton();if(batch&&batch.status!=="completed")say('上次加工记录已保留，可点击继续剩余。');
}

app.registerExtension({name:"AD.SegmentedLoop.FinalSave",nodeCreated(node){if((node.comfyClass||node.type)==="AD_FinalSave")mountFinalSave(node);}});
