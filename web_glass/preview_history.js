export const HISTORY_GROUP_LIMIT = 10;
export const HISTORY_PAGE_SIZE = 200;
export const historyRound = record => Number(record?.round_no) || 0;
export function retainedHistoryRounds(records, currentRound, limit = HISTORY_GROUP_LIMIT) {
    const rounds = new Set(records.filter(record => record?.file).map(historyRound));
    if (Number(currentRound) > 0) rounds.add(Number(currentRound));
    return new Set([...rounds].sort((a,b) => b-a).slice(0,limit));
}
// 每个分区（图片/音频/视频/分段A/分段B/合并）各自保留最近 N 组：
// 合并组和生成组会交替出现，按“全局最近10组”会把生成组挤到只剩几个。
// 只按该分区实际有记录的组计数，不额外占用一个当前组名额。
export function retainedHistoryRoundsByStrip(lists, currentRound, limit = HISTORY_GROUP_LIMIT) {
    const keep = new Set();
    for (const list of lists || []) {
        const rounds = new Set((list || []).filter(record => record?.file).map(historyRound));
        [...rounds].sort((a,b) => b-a).slice(0,limit).forEach(round => keep.add(round));
    }
    return keep;
}
export function previewHistoryGroups(records, currentRound, expanded, pages, prefix, pageSize = HISTORY_PAGE_SIZE) {
    const grouped = new Map();
    for (const record of records) {
        const round = historyRound(record);
        if (!grouped.has(round)) grouped.set(round, []);
        grouped.get(round).push(record);
    }
    const current = Number(currentRound) || Math.max(0,...grouped.keys());
    const order = [...grouped.keys()].sort((a,b) => (a===current)-(b===current) || a-b);
    const groups = order.map(round => {
        const all = grouped.get(round), key = `${prefix}:${round}`;
        const page = Math.max(0,Math.min(Number(pages.get(key))||0,Math.ceil(all.length/pageSize)-1));
        pages.set(key,page);
        const open = round===current || expanded.has(round);
        return {round,current:round===current,open,all,page,key,
            visible:open?all.slice(page*pageSize,(page+1)*pageSize):[]};
    });
    // 显示上限：只画最近 N 组（current 永远排在最后，不会被切掉）。
    return groups.length > HISTORY_GROUP_LIMIT ? groups.slice(groups.length - HISTORY_GROUP_LIMIT) : groups;
}
