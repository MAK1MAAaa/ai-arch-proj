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
        const toggle = node("workspace-toggle-sidebar"), toggleLabel = node("workspace-toggle-sidebar-label");
        const sidebar = node("workspace-sidebar"), search = document.querySelector(".search-section");
        const resultTab = node("workspace-tab-results"), catalogueTab = node("workspace-tab-catalogue");
        const resultPanel = node("workspace-results-view"), cataloguePanel = node("workspace-catalogue-view");
        const dialog = node("detail-dialog"), detail = node("detail-panel"), close = node("close-detail");
        let width = defaultWidth, preferredWidth = defaultWidth;
        let drag = null;
        let returnFocus = null;
        let restoreFocus = true;
        const narrow = () => window.matchMedia("(max-width: 900px)").matches;
        let collapsed = narrow();
        const changed = () => window.dispatchEvent(new Event("archsearch:workspacechange"));
        function persist() {
            try {
                localStorage.setItem(storageKey, JSON.stringify({ sidebar_width: preferredWidth, sidebar_collapsed: collapsed }));
            }
            catch { /* Layout remains usable when storage is unavailable. */ }
        }
        function activeTab() {
            return sidebar.dataset.activeTab === "catalogue" ? catalogueTab : resultTab;
        }
        function focusTarget() {
            return collapsed ? toggle : activeTab();
        }
        function stopDrag(save = false) {
            const captured = drag;
            drag = null;
            grid.classList.remove("is-resizing");
            if (captured === null)
                return;
            if (divider.hasPointerCapture(captured))
                divider.releasePointerCapture(captured);
            if (save) {
                preferredWidth = width;
                persist();
            }
        }
        function updateVisibility() {
            sidebar.hidden = collapsed;
            divider.hidden = collapsed || narrow();
            divider.tabIndex = divider.hidden ? -1 : 0;
            grid.dataset.sidebarCollapsed = String(collapsed);
            if (collapsed)
                grid.classList.add("is-sidebar-collapsed");
            else
                grid.classList.remove("is-sidebar-collapsed");
            toggle.setAttribute("aria-expanded", String(!collapsed));
            toggle.setAttribute("aria-label", collapsed ? "展开资料面板，查看检索结果与全库目录" : "收起资料面板，扩大双图区域");
            toggle.title = collapsed ? "展开资料面板" : "收起资料面板";
            toggleLabel.textContent = collapsed ? "展开资料" : "收起资料";
        }
        function setSidebarCollapsed(next, options = {}) {
            const hidesFocusedControl = next && (sidebar.contains(document.activeElement) || document.activeElement === divider);
            const wasDragging = drag !== null;
            stopDrag();
            if (wasDragging)
                preferredWidth = width;
            const different = collapsed !== next;
            collapsed = next;
            updateVisibility();
            if (options.focus || hidesFocusedControl)
                focusTarget().focus({ preventScroll: true });
            if (different || wasDragging)
                persist();
            changed();
        }
        function resize(value, save = false) {
            const available = narrow() ? Number.MAX_SAFE_INTEGER : grid.getBoundingClientRect().width;
            width = layoutWidth(value, available);
            grid.style.setProperty("--sidebar-width", `${width}px`);
            divider.setAttribute("aria-valuemin", String(minimumWidth));
            divider.setAttribute("aria-valuemax", String(layoutWidth(maximumWidth, available)));
            divider.setAttribute("aria-valuenow", String(width));
            divider.setAttribute("aria-valuetext", `资料侧栏 ${width} 像素`);
            if (save) {
                preferredWidth = width;
                persist();
            }
            changed();
        }
        function measure() {
            const documentTop = grid.getBoundingClientRect().top + window.scrollY;
            const available = Math.max(430, window.innerHeight - documentTop - 14);
            grid.style.setProperty("--workspace-height", `${Math.round(available)}px`);
            if (narrow() || collapsed)
                stopDrag(true);
            updateVisibility();
            resize(drag === null ? preferredWidth : width);
        }
        try {
            const saved = JSON.parse(localStorage.getItem(storageKey) ?? "null");
            if (saved && typeof saved === "object") {
                if ("sidebar_width" in saved && typeof saved.sidebar_width === "number" && Number.isFinite(saved.sidebar_width))
                    preferredWidth = layoutWidth(saved.sidebar_width, Number.MAX_SAFE_INTEGER);
                if ("sidebar_collapsed" in saved && typeof saved.sidebar_collapsed === "boolean")
                    collapsed = saved.sidebar_collapsed;
            }
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
                focusTarget().focus({ preventScroll: true });
            changed();
        }
        toggle.addEventListener("click", () => setSidebarCollapsed(!collapsed));
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
            if (collapsed || narrow() || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key))
                return;
            event.preventDefault();
            resize(event.key === "Home" ? minimumWidth : event.key === "End" ? maximumWidth : width + (event.key === "ArrowRight" ? 16 : -16), true);
        });
        divider.addEventListener("pointerdown", (event) => {
            if (collapsed || narrow() || drag !== null || event.button !== 0 || !event.isPrimary)
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
            stopDrag(true);
        }
        divider.addEventListener("pointerup", endDrag);
        divider.addEventListener("pointercancel", endDrag);
        divider.addEventListener("lostpointercapture", endDrag);
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
                const target = returnFocus?.isConnected && !returnFocus.closest("[hidden]") && !(collapsed && sidebar.contains(returnFocus)) ? returnFocus : focusTarget();
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
            if (event.defaultPrevented || event.key !== "Escape" || dialog.open)
                return;
            const hadMenu = menus.some(menu => menu.open);
            for (const menu of menus)
                menu.open = false;
            if (!hadMenu && !collapsed && (sidebar.contains(document.activeElement) || document.activeElement === toggle)) {
                event.preventDefault();
                setSidebarCollapsed(true);
            }
        });
        window.addEventListener("resize", measure);
        if (typeof ResizeObserver !== "undefined" && search)
            new ResizeObserver(measure).observe(search);
        activate("results");
        measure();
        return {
            openDetail, closeDetail, setSidebarCollapsed,
            isSidebarCollapsed: () => collapsed,
            revealMaps: () => { if (narrow() && !collapsed)
                setSidebarCollapsed(true); },
            activateResults: (options = {}) => activate("results", options),
            activateCatalogue: (options = {}) => activate("catalogue", options),
        };
    }
    const controls = create();
    return { ...controls, layoutWidth };
})();
//# sourceMappingURL=workspace.js.map