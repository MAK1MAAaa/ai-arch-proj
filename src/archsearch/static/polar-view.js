"use strict";
const ArchSearchPolarView = (() => {
    "use strict";
    const mercatorLimit = 85.0511287798;
    const svgNamespace = "http://www.w3.org/2000/svg";
    function coordinate(value) {
        return Array.isArray(value) && value.length === 2
            && typeof value[0] === "number" && Number.isFinite(value[0]) && Math.abs(value[0]) <= 180
            && typeof value[1] === "number" && Number.isFinite(value[1]) && value[1] >= -90 && value[1] <= 90;
    }
    function project(value) {
        if (!coordinate(value) || value[1] > -60)
            throw new Error("南极定位示意只接受南纬60度以内的源WGS84坐标。");
        const radius = 200 * (value[1] + 90) / 30;
        const angle = value[0] * Math.PI / 180;
        return [250 + radius * Math.sin(angle), 250 - radius * Math.cos(angle)];
    }
    function clipRing(value) {
        if (!Array.isArray(value) || value.length < 4 || !value.every(coordinate))
            throw new Error("本地陆地轮廓包含无效坐标环。");
        const ring = value;
        if (ring[0][0] !== ring.at(-1)[0] || ring[0][1] !== ring.at(-1)[1])
            throw new Error("本地陆地轮廓坐标环未闭合。");
        const result = [];
        const vertices = ring.slice(0, -1);
        let previous = vertices.at(-1);
        for (const current of vertices) {
            const inside = current[1] <= -60;
            if (inside !== (previous[1] <= -60)) {
                const ratio = (-60 - previous[1]) / (current[1] - previous[1]);
                result.push([previous[0] + ratio * (current[0] - previous[0]), -60]);
            }
            if (inside)
                result.push([...current]);
            previous = current;
        }
        if (result.length < 3)
            return [];
        result.push([...result[0]]);
        return result;
    }
    function ringPath(ring) {
        if (!ring.length)
            return "";
        const positions = [];
        for (let index = 0; index < ring.length - 1; index++) {
            const current = ring[index];
            const next = ring[index + 1];
            positions.push(project(current));
            if (current[1] === -60 && next[1] === -60) {
                const distance = ((next[0] - current[0] + 540) % 360) - 180;
                const steps = Math.ceil(Math.abs(distance) / 2);
                for (let step = 1; step < steps; step++) {
                    const longitude = ((current[0] + distance * step / steps + 540) % 360) - 180;
                    positions.push(project([longitude, -60]));
                }
            }
        }
        return positions.map((position, index) => `${index ? "L" : "M"}${position[0].toFixed(3)} ${position[1].toFixed(3)}`).join("") + "Z";
    }
    function record(value) {
        return value !== null && typeof value === "object" && !Array.isArray(value);
    }
    function landPaths(value) {
        if (!record(value) || value.type !== "FeatureCollection" || !Array.isArray(value.features) || value.features.length > 10_000)
            throw new Error("本地陆地轮廓格式无效。");
        const paths = [];
        for (const feature of value.features) {
            if (!record(feature) || feature.type !== "Feature" || !record(feature.geometry))
                throw new Error("本地陆地轮廓缺少几何。");
            const geometry = feature.geometry;
            if (!Array.isArray(geometry.coordinates) || !["Polygon", "MultiPolygon"].includes(String(geometry.type)))
                throw new Error("本地陆地轮廓应为多边形。");
            const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
            for (const polygon of polygons) {
                if (!Array.isArray(polygon) || polygon.length === 0)
                    throw new Error("本地陆地轮廓缺少坐标环。");
                const rings = polygon.map((ring) => clipRing(ring));
                if (rings[0].length)
                    paths.push(rings.map(ringPath).join(""));
            }
        }
        return paths;
    }
    function antarcticSites(value) {
        if (!Array.isArray(value))
            throw new Error("南极目录格式无效。");
        const result = [];
        const ids = new Set();
        for (const item of value) {
            if (!record(item))
                throw new Error("南极目录记录格式无效。");
            if (item.source_kind !== "ats" && !(Array.isArray(item.regions) && item.regions.includes("antarctica")))
                continue;
            if (typeof item.id !== "string" || !/^ats:hsm:[1-9]\d*$/u.test(item.id) || ids.has(item.id)
                || typeof item.title !== "string" || !item.title.trim()
                || !(item.repr_point === null || coordinate(item.repr_point))
                || (item.repr_point !== null && item.repr_point[1] > -60))
                throw new Error("南极目录身份或源坐标无效，保留上次成功示意。");
            const status = item.repr_point === null ? "unknown" : Math.abs(item.repr_point[1]) > mercatorLimit ? "polar" : "mapped";
            if (item.location_status !== status)
                throw new Error("南极目录定位状态与源坐标不一致，保留上次成功示意。");
            ids.add(item.id);
            result.push({ id: item.id, title: item.title, repr_point: item.repr_point === null ? null : [...item.repr_point],
                location_status: status, regions: ["antarctica"], source_kind: "ats" });
        }
        return result.sort((left, right) => Number(left.id.split(":").at(-1)) - Number(right.id.split(":").at(-1)));
    }
    function coordinateText(value) {
        return `源WGS84经度 ${value[0]}°，纬度 ${value[1]}°`;
    }
    function create({ onSelect }) {
        const get = (id) => {
            const node = document.getElementById(id);
            if (!node)
                throw new Error(`南极定位组件缺少 ${id}。`);
            return node;
        };
        const ui = { panel: get("polar-panel"), summary: get("polar-summary"), count: get("polar-count"),
            map: get("polar-map"), points: get("polar-points"), selection: get("polar-selection"), unknown: get("polar-unknown"),
            feedback: get("polar-feedback"), retry: get("polar-retry") };
        const land = (() => {
            const node = document.getElementById("polar-land");
            if (!node)
                throw new Error("南极定位组件缺少 polar-land。");
            return node;
        })();
        let sites = [];
        let selectedId = null;
        let focusedId = null;
        const buttons = new Map();
        let landController = null;
        let landSequence = 0;
        let landReady = false;
        let completeCatalogue = false;
        ui.feedback.tabIndex = -1;
        function hideRetry() {
            if (document.activeElement === ui.retry)
                ui.feedback.focus({ preventScroll: true });
            ui.retry.hidden = true;
        }
        function describe(site) {
            ui.selection.textContent = site ? `${site.id.replace("ats:hsm:", "HSM ")} · ${site.title}。${site.repr_point === null
                ? "位置未知；来源未给出可确认的遗址坐标，未绘制点位。" : `${coordinateText(site.repr_point)}。${site.location_status === "polar" ? "超过主图投影范围，使用本示意保留真实纬度。" : "此点也可在主图查看。"}`}`
                : "选择目录条目或图上圆点，查看来源。";
        }
        function roving() {
            const known = sites.filter((site) => site.repr_point !== null);
            const active = known.find((site) => site.id === focusedId) ?? known.find((site) => site.id === selectedId) ?? known[0];
            for (const site of sites) {
                const button = buttons.get(site.id);
                if (!button)
                    continue;
                button.tabIndex = site.repr_point === null || site.id === active?.id ? 0 : -1;
                button.setAttribute("aria-pressed", String(site.id === selectedId));
            }
        }
        async function loadLand(force = false) {
            if ((landReady && !force) || (landController && !force))
                return;
            landController?.abort();
            const current = ++landSequence;
            const controller = new AbortController();
            landController = controller;
            ui.feedback.textContent = landReady ? "正在重读本地自然地理轮廓；保留上次成功轮廓。" : "正在读取本地自然地理轮廓；点位与网格已可使用。";
            hideRetry();
            try {
                const response = await fetch("/static/data/land.geojson", { signal: controller.signal, headers: { Accept: "application/geo+json, application/json" } });
                if (!response.ok)
                    throw new Error(`HTTP ${response.status}`);
                const raw = await response.json();
                if (controller.signal.aborted || current !== landSequence)
                    return;
                const paths = landPaths(raw);
                if (!paths.length)
                    throw new Error("轮廓未包含南纬60度以内陆地");
                const nodes = paths.map((path) => { const node = document.createElementNS(svgNamespace, "path"); node.setAttribute("d", path); return node; });
                if (controller.signal.aborted || current !== landSequence)
                    return;
                land.replaceChildren(...nodes);
                landReady = true;
                ui.feedback.textContent = "本地 Natural Earth 现代陆地轮廓已加载；点位与轮廓均无需外网。";
                ui.panel.classList.toggle("has-error", false);
            }
            catch (error) {
                if (controller.signal.aborted || current !== landSequence)
                    return;
                ui.feedback.textContent = `轮廓未加载（${error instanceof Error ? error.message : "本地资源不可用"}）；${landReady ? "保留上次成功轮廓，" : ""}已知点位与网格仍可使用。`;
                ui.retry.hidden = false;
                ui.panel.classList.toggle("has-error", true);
            }
            finally {
                if (current === landSequence)
                    landController = null;
            }
        }
        function open() {
            ui.panel.open = true;
            void loadLand();
        }
        function select(id) {
            selectedId = id;
            const site = sites.find((item) => item.id === id);
            focusedId = site?.id ?? null;
            if (site && site.location_status !== "mapped")
                open();
            roving();
            describe(site);
        }
        function applySites(next, complete) {
            const previousFocus = document.activeElement;
            const keepFocus = previousFocus instanceof HTMLElement && (ui.points.contains(previousFocus) || ui.unknown.contains(previousFocus));
            sites = next;
            completeCatalogue = complete;
            ui.panel.dataset.scope = complete ? "complete" : "details-only";
            ui.panel.hidden = sites.length === 0;
            if (!sites.length) {
                landController?.abort();
                landController = null;
                landSequence++;
                ui.panel.open = false;
            }
            const ids = new Set(sites.map((site) => site.id));
            for (const id of buttons.keys())
                if (!ids.has(id))
                    buttons.delete(id);
            const known = [];
            const unknown = [];
            for (const site of sites) {
                let button = buttons.get(site.id);
                if (!button) {
                    button = document.createElement("button");
                    button.type = "button";
                    button.dataset.siteId = site.id;
                    const id = site.id;
                    const opener = button;
                    button.addEventListener("click", () => onSelect(id, opener));
                    button.addEventListener("focus", () => { focusedId = id; roving(); describe(sites.find((item) => item.id === id)); });
                    buttons.set(id, button);
                }
                button.dataset.locationStatus = site.location_status;
                button.className = site.repr_point === null ? "polar-unknown-button" : "polar-point";
                const label = `${site.id.replace("ats:hsm:", "HSM ")} · ${site.title}。${site.repr_point === null ? "位置未知，打开来源资料" : `${coordinateText(site.repr_point)}，打开来源资料`}`;
                button.setAttribute("aria-label", label);
                button.title = label;
                if (site.repr_point === null) {
                    button.textContent = `${site.id.replace("ats:hsm:", "HSM ")} · ${site.title} · 位置未知，查看来源`;
                    unknown.push(button);
                }
                else {
                    const position = project(site.repr_point);
                    button.style.left = `${position[0] / 5}%`;
                    button.style.top = `${position[1] / 5}%`;
                    button.dataset.longitude = String(site.repr_point[0]);
                    button.dataset.latitude = String(site.repr_point[1]);
                    known.push(button);
                }
            }
            ui.points.replaceChildren(...known);
            ui.unknown.replaceChildren(...unknown);
            ui.count.textContent = `${complete ? "" : "仅已读详情，完整目录未就绪 · "}${sites.length} 条来源记录 · ${known.length} 处有源坐标 · ${unknown.length} 处位置未知`;
            roving();
            describe(sites.find((site) => site.id === selectedId));
            if (keepFocus && previousFocus instanceof HTMLElement && (ui.points.contains(previousFocus) || ui.unknown.contains(previousFocus)))
                previousFocus.focus({ preventScroll: true });
            if (ui.panel.open && sites.length)
                void loadLand();
        }
        function catalogueError(error) {
            ui.feedback.textContent = error instanceof Error ? error.message : "南极目录无效，保留上次成功示意。";
            ui.panel.classList.toggle("has-error", true);
        }
        function setSites(value) {
            try {
                applySites(antarcticSites(value), true);
            }
            catch (error) {
                catalogueError(error);
            }
        }
        function ensureSite(value) {
            if (!record(value) || value.source_kind !== "ats")
                return false;
            try {
                const verified = antarcticSites([value]);
                if (verified.length !== 1)
                    return false;
                if (completeCatalogue)
                    return sites.some((site) => site.id === verified[0].id);
                applySites(antarcticSites([...sites.filter((site) => site.id !== verified[0].id), verified[0]]), false);
                return true;
            }
            catch (error) {
                catalogueError(error);
                return false;
            }
        }
        function focusSelected() {
            const button = selectedId === null ? undefined : buttons.get(selectedId);
            if (!button)
                return;
            open();
            button.focus({ preventScroll: true });
            ui.map.scrollIntoView({ block: "nearest", behavior: "auto" });
        }
        function locate(id) {
            if (!sites.some((site) => site.id === id))
                return false;
            select(id);
            focusSelected();
            return true;
        }
        ui.points.addEventListener("keydown", (event) => {
            if (!["ArrowLeft", "ArrowUp", "ArrowRight", "ArrowDown", "Home", "End"].includes(event.key))
                return;
            const known = sites.filter((site) => site.repr_point !== null);
            if (!known.length)
                return;
            const current = known.findIndex((site) => buttons.get(site.id) === document.activeElement);
            if (current < 0)
                return;
            event.preventDefault();
            event.stopPropagation();
            const next = event.key === "Home" ? 0 : event.key === "End" ? known.length - 1
                : (current + (["ArrowLeft", "ArrowUp"].includes(event.key) ? -1 : 1) + known.length) % known.length;
            buttons.get(known[next].id)?.focus({ preventScroll: true });
        });
        ui.panel.addEventListener("keydown", (event) => {
            if (event.key !== "Escape" || !ui.panel.open)
                return;
            event.preventDefault();
            event.stopPropagation();
            ui.panel.open = false;
            ui.summary.focus({ preventScroll: true });
        });
        ui.panel.addEventListener("toggle", () => { if (ui.panel.open && sites.length)
            void loadLand(); });
        ui.retry.addEventListener("click", () => { void loadLand(true); });
        return { setSites, ensureSite, select, focusSelected, locate };
    }
    return { create, project, clipRing, landPaths, antarcticSites };
})();
//# sourceMappingURL=polar-view.js.map