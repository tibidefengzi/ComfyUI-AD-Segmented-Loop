// 分段预览节点旧工作流的控件值迁移。
//
// 早期预览节点有两个控件：[video_oasis_ui, save_config]；视频预览界面改为自绘后，
// video_oasis_ui 已不再声明为输入，只剩 save_config。旧存档按位置存的值会在加载时
// 错位（UI JSON 落到 save_config），这里在节点配置阶段纠正一次。
export function looksSaveConfig(value) {
    try {
        const config = JSON.parse(String(value ?? "{}"));
        return !!config && typeof config === "object" && ("dir" in config || "template" in config);
    } catch {
        return false;
    }
}

export function migratePreviewWidgetValues(values) {
    if (!Array.isArray(values) || values.length < 2) return values;
    if (looksSaveConfig(values[0]) || !looksSaveConfig(values[1])) return values;
    return [values[1], ...values.slice(2)];
}
