// Only user edits trigger timed import; programmatic restore/undo never does.
export function hasTimedPrompt(text) {
    return /^\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}[ \t]*-->/m.test(String(text || ""));
}

export function bindTimedPromptInput(area, node, native, {syncOrdinary, importText}) {
    let pending = false;
    let snapshot = "";
    let attempted = null;
    const commit = () => {
        const text = area.value;
        if (!pending || !hasTimedPrompt(text) || attempted === text) return;
        attempted = text;
        if (importText(text, snapshot) === true) {
            pending = false;
            node._adH3TimedPromptEditing = false;
        }
    };
    area.addEventListener("input", event => {
        if (!pending) snapshot = String(native.value ?? "");
        pending = hasTimedPrompt(area.value);
        node._adH3TimedPromptEditing = pending;
        attempted = null;
        native.value = area.value;
        try { native.callback?.(area.value); } catch {}
        if (!pending) syncOrdinary();
        if (event.inputType === "insertFromPaste") queueMicrotask(commit);
    });
    // Native paste completes after this event, before the deferred commit.
    area.addEventListener("paste", () => setTimeout(commit, 0));
    area.addEventListener("blur", commit);
}
