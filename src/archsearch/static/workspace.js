"use strict";
const ArchSearchWorkspace = (() => {
    "use strict";
    const storageKey = "archsearch.workspace.layout.v1";
    const defaultWidth = 350;
    const minimumWidth = 280;
    const maximumWidth = 580;
    function layoutWidth(value, available) {
        const upper = Math.max(minimumWidth, Math.min(maximumWidth, available - 532));
        const width = typeof value === "number" && Number.isFinite(value) ? value : defaultWidth;
        return Math.round(Math.max(minimumWidth, Math.min(upper, width)));
    }
    function create() {
        const node = (id) => {
            const value = document.getElementById(id);
            if (!value)
                throw new Error(`工作台控件不存在：${id}`);
            return value;
        };
        const grid = node("workspace"), divider = node("workspace-divider");
        const sidebar = node("workspace-sidebar"), search = document.querySelector(".search-section");
        const resultTab = node("workspace-tab-results"), catalogueTab = node("workspace-tab-catalogue");
        const resultPanel = node("workspace-results-view"), cataloguePanel = node("workspace-catalogue-view");
        const dialog = node("detail-dialog"), detail = node("detail-panel"), close = node("close-detail");
        let width = defaultWidth;
        let drag = null;
        let returnFocus = null;
        let restoreFocus = true;
        const narrow = () => window.matchMedia("(max-width: 900px)").matches;
        const changed = () => window.dispatchEvent(new Event("archsearch:workspacechange"));
        function persist() {
            try {
                localStorage.setItem(storageKey, JSON.stringify({ sidebar_width: width }));
            }
            catch { /* Layout remains usable when storage is unavailable. */ }
        }
        function resize(value, save = false) {
            width = layoutWidth(value, grid.getBoundingClientRect().width);
            grid.style.setProperty("--sidebar-width", `${width}px`);
            divider.setAttribute("aria-valuemin", String(minimumWidth));
            divider.setAttribute("aria-valuemax", String(layoutWidth(maximumWidth, grid.getBoundingClientRect().width)));
            divider.setAttribute("aria-valuenow", String(width));
            divider.setAttribute("aria-valuetext", `资料侧栏 ${width} 像素`);
            if (save)
                persist();
            changed();
        }
        function measure() {
            const available = Math.max(430, window.innerHeight - grid.getBoundingClientRect().top - 14);
            grid.style.setProperty("--workspace-height", `${Math.round(available)}px`);
            resize(width);
        }
        try {
            const saved = JSON.parse(localStorage.getItem(storageKey) ?? "null");
            if (saved && typeof saved === "object" && "sidebar_width" in saved)
                width = layoutWidth(saved.sidebar_width, grid.getBoundingClientRect().width);
        }
        catch { /* A stale or malformed preference never blocks the maps. */ }
        function activate(which, options = {}) {
            const results = which === "results";
            const hidesFocusedControl = (results ? cataloguePanel : resultPanel).contains(document.activeElement);
            resultPanel.hidden = !results;
            cataloguePanel.hidden = results;
            for (const [tab, selected] of [[resultTab, results], [catalogueTab, !results]]) {
                tab.setAttribute("aria-selected", String(selected));
                tab.tabIndex = selected ? 0 : -1;
            }
            sidebar.dataset.activeTab = which;
            if (options.focus || hidesFocusedControl)
                (results ? resultTab : catalogueTab).focus({ preventScroll: true });
            changed();
        }
        resultTab.addEventListener("click", () => activate("results"));
        catalogueTab.addEventListener("click", () => activate("catalogue"));
        for (const tab of [resultTab, catalogueTab])
            tab.addEventListener("keydown", (event) => {
                if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key))
                    return;
                event.preventDefault();
                activate(event.key === "Home" ? "results" : event.key === "End" ? "catalogue" : tab === resultTab ? "catalogue" : "results", { focus: true });
            });
        divider.addEventListener("keydown", (event) => {
            if (narrow() || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key))
                return;
            event.preventDefault();
            resize(event.key === "Home" ? minimumWidth : event.key === "End" ? maximumWidth : width + (event.key === "ArrowRight" ? 16 : -16), true);
        });
        divider.addEventListener("pointerdown", (event) => {
            if (narrow() || event.button !== 0 || !event.isPrimary)
                return;
            event.preventDefault();
            drag = event.pointerId;
            divider.setPointerCapture(drag);
            grid.classList.add("is-resizing");
        });
        divider.addEventListener("pointermove", (event) => {
            if (drag === event.pointerId)
                resize(event.clientX - grid.getBoundingClientRect().left);
        });
        function endDrag(event) {
            if (drag !== event.pointerId)
                return;
            if (divider.hasPointerCapture(drag))
                divider.releasePointerCapture(drag);
            drag = null;
            grid.classList.remove("is-resizing");
            persist();
        }
        divider.addEventListener("pointerup", endDrag);
        divider.addEventListener("pointercancel", endDrag);
        divider.addEventListener("lostpointercapture", () => { drag = null; grid.classList.remove("is-resizing"); });
        function openDetail(opener = null) {
            if (!dialog.open) {
                returnFocus = opener ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null);
                restoreFocus = true;
                detail.hidden = false;
                dialog.showModal();
            }
            close.focus({ preventScroll: true });
        }
        function closeDetail(options = {}) {
            restoreFocus = options.restoreFocus !== false;
            if (dialog.open)
                dialog.close();
            else
                detail.hidden = true;
        }
        close.addEventListener("click", () => closeDetail());
        dialog.addEventListener("click", (event) => {
            if (event.target !== dialog)
                return;
            const bounds = dialog.getBoundingClientRect();
            if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom)
                closeDetail();
        });
        dialog.addEventListener("close", () => {
            if (dialog.open)
                return;
            detail.hidden = true;
            if (restoreFocus) {
                const target = returnFocus?.isConnected && !returnFocus.closest("[hidden]") ? returnFocus : sidebar.dataset.activeTab === "catalogue" ? catalogueTab : resultTab;
                target.focus({ preventScroll: true });
            }
            returnFocus = null;
            restoreFocus = true;
            window.dispatchEvent(new Event("archsearch:detailclose"));
        });
        const menus = ["workspace-examples", "llm-settings"].map(id => node(id));
        for (const menu of menus)
            menu.addEventListener("toggle", () => { if (menu.open)
                for (const other of menus)
                    if (other !== menu)
                        other.open = false; });
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && !dialog.open)
                for (const menu of menus)
                    menu.open = false;
        });
        window.addEventListener("resize", measure);
        if (typeof ResizeObserver !== "undefined" && search)
            new ResizeObserver(measure).observe(search);
        activate("results");
        measure();
        return { openDetail, closeDetail, activateResults: (options = {}) => activate("results", options), activateCatalogue: (options = {}) => activate("catalogue", options) };
    }
    const controls = create();
    return { ...controls, layoutWidth };
})();
//# sourceMappingURL=workspace.js.map