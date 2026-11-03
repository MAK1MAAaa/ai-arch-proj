"use strict";
const ArchSearchExplore = (() => {
    "use strict";
    const pageSize = 50;
    const regionLabels = {
        "africa": "非洲",
        "arab-states": "阿拉伯国家",
        "asia-pacific": "亚太地区",
        "europe-north-america": "欧洲和北美洲",
        "latin-america-caribbean": "拉丁美洲和加勒比地区",
        "antarctica": "南极",
    };
    const sourceLabels = {
        pleiades: "Pleiades 罗马资料", global: "已策展全球资料", unesco: "世界遗产名录", ats: "ATS 南极历史遗址",
    };
    const chronologyLabels = {
        reviewed: "已有来源支持的阶段", insufficient: "已核验，断代未确定", not_reviewed: "断代尚未核验",
    };
    function normalizeState(value) {
        const country = value.country ?? null;
        const region = value.region ?? null;
        const offset = value.offset ?? 0;
        const visible = value.visible ?? true;
        if (country !== null && (typeof country !== "string" || !/^[A-Z]{2}$/u.test(country)))
            throw new Error("目录国家／地区代码应为来源中的大写双字母代码。");
        if (region !== null && (typeof region !== "string" || !Object.hasOwn(regionLabels, region)))
            throw new Error("目录分区代码不在来源分区中。");
        if (!Number.isSafeInteger(offset) || offset < 0 || offset > 1_000_000)
            throw new Error("目录起始位置应为0至1000000的整数。");
        if (typeof visible !== "boolean")
            throw new Error("目录点位开关无效。");
        return { country, region, offset, visible };
    }
    function matches(point, state) {
        return (state.country === null || point.countries.includes(state.country))
            && (state.region === null || point.regions.includes(state.region));
    }
    function coordinate(value) {
        return Array.isArray(value) && value.length === 2
            && typeof value[0] === "number" && Number.isFinite(value[0]) && value[0] >= -180 && value[0] <= 180
            && typeof value[1] === "number" && Number.isFinite(value[1]) && value[1] >= -90 && value[1] <= 90;
    }
    function displayCoordinates(value) {
        return [-360, 0, 360].map((offset) => [value[1], value[0] + offset]);
    }
    const mercatorLimit = 85.0511287798;
    const locationLabels = { mapped: "主图可定位", polar: "极区定位示意", unknown: "位置未知" };
    function locationStatus(value) {
        return value === null ? "unknown" : Math.abs(value[1]) > mercatorLimit ? "polar" : "mapped";
    }
    function coordinateKey(value) { return JSON.stringify(value); }
    function placements(point) {
        const seen = new Map();
        point.source_points.forEach((value, index) => {
            if (locationStatus(value) !== "mapped")
                return;
            const key = coordinateKey(value);
            const existing = seen.get(key);
            if (existing)
                existing.sourceIndexes.push(index);
            else
                seen.set(key, { coordinate: [...value], sourceIndexes: [index], representative: false });
        });
        if (point.repr_point && locationStatus(point.repr_point) === "mapped") {
            const key = coordinateKey(point.repr_point);
            if (!seen.has(key))
                seen.set(key, { coordinate: [...point.repr_point], sourceIndexes: [], representative: true });
        }
        return [...seen.values()];
    }
    function sourcePoints(value) {
        if (value === undefined)
            return [];
        if (!Array.isArray(value) || value.length > 10_000 || !value.every(coordinate))
            throw new Error("来源定位点坐标或数量无效。");
        return value.map((point) => [...point]);
    }
    function sourceRecords(value, points) {
        if (value === undefined)
            return [];
        if (!Array.isArray(value) || value.length !== points.length)
            throw new Error("来源定位记录数量与源点不一致。");
        return value.map((item, index) => {
            if (!record(item) || item.source_index !== index || !coordinate(item.coordinate)
                || coordinateKey(item.coordinate) !== coordinateKey(points[index])
                || typeof item.name !== "string" || typeof item.ref !== "string" || item.name.length > 10_000 || item.ref.length > 10_000)
                throw new Error("来源定位记录的坐标、顺序或标签无效。");
            return { source_index: index, coordinate: [...item.coordinate], name: item.name, ref: item.ref };
        });
    }
    function record(value) {
        return value !== null && typeof value === "object" && !Array.isArray(value);
    }
    function element(tag, className, text) {
        const node = document.createElement(tag);
        if (className)
            node.className = className;
        if (text !== undefined)
            node.textContent = text;
        return node;
    }
    function text(value) { return typeof value === "string" && Boolean(value.trim()); }
    function count(value) { return typeof value === "number" && Number.isSafeInteger(value) && value >= 0; }
    function version(value) { return text(value) && value.length <= 128; }
    function countryLabel(facet) {
        try {
            const translated = new Intl.DisplayNames(["zh-CN"], { type: "region" }).of(facet.id);
            if (translated && translated !== facet.id)
                return `${translated}（${facet.id}）`;
        }
        catch { /* Keep the source label when locale display names are unavailable. */ }
        return `${facet.label}（${facet.id}）`;
    }
    function httpUrl(value) {
        if (!text(value))
            throw new Error("覆盖统计来源链接缺失。");
        const url = new URL(value);
        if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password)
            throw new Error("覆盖统计来源链接无效。");
        return url.href;
    }
    function parseAuthority(value) {
        if (value === null || value === undefined)
            return null;
        if (!record(value) || !text(value.dataset) || !text(value.source_modified) || !text(value.source_sha256)
            || !/^[a-f0-9]{64}$/u.test(value.source_sha256) || !text(value.license) || typeof value.note !== "string"
            || !count(value.eligible_total) || !count(value.covered) || !count(value.missing) || !count(value.excluded_natural)
            || value.covered + value.missing !== value.eligible_total)
            throw new Error("官方名录覆盖分母或来源元数据无效。");
        return { dataset: value.dataset, source_uri: httpUrl(value.source_uri), source_modified: value.source_modified,
            source_sha256: value.source_sha256, license: value.license, license_uri: httpUrl(value.license_uri),
            eligible_total: value.eligible_total, covered: value.covered, missing: value.missing, excluded_natural: value.excluded_natural, note: value.note };
    }
    function parsePolarAuthority(value) {
        if (value === null || value === undefined)
            return null;
        if (!record(value) || !text(value.dataset) || !text(value.source_accessed) || !text(value.source_sha256)
            || !/^[a-f0-9]{64}$/u.test(value.source_sha256) || !text(value.license) || typeof value.note !== "string"
            || !count(value.eligible_total) || !count(value.covered) || !count(value.missing) || !record(value.excluded_types)
            || Object.values(value.excluded_types).some((amount) => !count(amount))
            || value.covered + value.missing !== value.eligible_total)
            throw new Error("南极历史名录覆盖分母或来源元数据无效。");
        return { dataset: value.dataset, source_uri: httpUrl(value.source_uri), source_accessed: value.source_accessed,
            source_sha256: value.source_sha256, license: value.license, license_uri: httpUrl(value.license_uri),
            eligible_total: value.eligible_total, covered: value.covered, missing: value.missing,
            excluded_types: { ...value.excluded_types }, note: value.note };
    }
    function parseSpatial(value) {
        if (value === null || value === undefined)
            return null;
        if (!record(value) || typeof value.ready !== "boolean" || !count(value.records) || !count(value.points)
            || !count(value.distinct_points) || !count(value.duplicate_points) || !count(value.display_points)
            || value.distinct_points + value.duplicate_points !== value.points)
            throw new Error("来源定位统计格式或数量无效。");
        if (!value.ready) {
            if (!text(value.reason) || value.version !== null || value.source !== null
                || value.records !== 0 || value.points !== 0 || value.distinct_points !== 0 || value.duplicate_points !== 0)
                throw new Error("来源定位未就绪状态与版本不一致。");
            return { ready: false, reason: value.reason, version: null, source: null, records: 0, points: 0, distinct_points: 0, duplicate_points: 0, display_points: value.display_points };
        }
        const source = value.source;
        if (value.reason !== null || !version(value.version) || !record(source) || !text(source.name) || !text(source.version)
            || !text(source.license) || !text(source.sha256) || !/^[a-f0-9]{64}$/u.test(source.sha256)
            || value.records < 1 || value.points < 1 || value.distinct_points < 1)
            throw new Error("来源定位版本或许可元数据无效。");
        return { ready: true, reason: null, version: value.version,
            source: { name: source.name, uri: httpUrl(source.uri), version: source.version, license: source.license,
                license_uri: httpUrl(source.license_uri), sha256: source.sha256 },
            records: value.records, points: value.points, distinct_points: value.distinct_points, duplicate_points: value.duplicate_points, display_points: value.display_points };
    }
    function facets(value, kind) {
        if (!Array.isArray(value))
            throw new Error("覆盖统计缺少来源分组。");
        const seen = new Set();
        return value.map((item) => {
            if (!record(item) || !text(item.id) || !text(item.label) || !count(item.count) || seen.has(item.id)
                || (kind === "country" && !/^[A-Z]{2}$/u.test(item.id)) || (kind === "region" && !Object.hasOwn(regionLabels, item.id)))
                throw new Error("覆盖统计分组格式无效。");
            seen.add(item.id);
            return { id: item.id, label: item.label, count: item.count };
        });
    }
    function parseCoverage(value) {
        if (!record(value) || !version(value.corpus_version) || !count(value.total) || !record(value.chronology)
            || !count(value.chronology.reviewed) || !count(value.chronology.insufficient) || !count(value.chronology.not_reviewed)
            || !count(value.geography_unknown) || !count(value.country_unknown) || !record(value.locations)
            || !count(value.locations.mapped) || !count(value.locations.polar) || !count(value.locations.unknown))
            throw new Error("覆盖统计格式无效。");
        const result = {
            corpus_version: value.corpus_version, total: value.total, countries: facets(value.countries, "country"),
            regions: facets(value.regions, "region"), sources: facets(value.sources, "source"),
            chronology: { reviewed: value.chronology.reviewed, insufficient: value.chronology.insufficient, not_reviewed: value.chronology.not_reviewed },
            geography_unknown: value.geography_unknown, country_unknown: value.country_unknown,
            authority: parseAuthority(value.authority),
            polar_authority: parsePolarAuthority(value.polar_authority),
            locations: { mapped: value.locations.mapped, polar: value.locations.polar, unknown: value.locations.unknown },
            spatial_locations: parseSpatial(value.spatial_locations),
        };
        if (Object.values(result.chronology).reduce((sum, amount) => sum + amount, 0) !== result.total
            || result.sources.reduce((sum, item) => sum + item.count, 0) !== result.total
            || Object.values(result.locations).reduce((sum, amount) => sum + amount, 0) !== result.total
            || result.country_unknown > result.total || result.geography_unknown > result.total)
            throw new Error("覆盖统计总数不一致。");
        return result;
    }
    function stringArray(value, kind) {
        if (!Array.isArray(value) || value.some((item) => typeof item !== "string"
            || (kind === "country" ? !/^[A-Z]{2}$/u.test(item) : !Object.hasOwn(regionLabels, item)))
            || new Set(value).size !== value.length)
            throw new Error("目录来源地域标签无效。");
        return value;
    }
    function parsePoint(value, fullSite = false) {
        if (!record(value) || !text(value.id) || !/^(?:[1-9]\d*|wd:Q[1-9]\d*|whc:[1-9]\d*|ats:hsm:[1-9]\d*)$/u.test(value.id)
            || !text(value.title) || !(value.repr_point === null || coordinate(value.repr_point)) || !text(value.source_kind))
            throw new Error("目录地点编号、标题或代表点无效。");
        const geography = fullSite ? record(value.geography) ? value.geography : { countries: [], regions: [] } : value;
        const status = fullSite ? record(value.chronology) ? value.chronology.status : undefined : value.chronology_status;
        if (status !== "reviewed" && status !== "insufficient" && status !== "not_reviewed")
            throw new Error("目录断代核验状态无效。");
        const placement = locationStatus(value.repr_point);
        if (!fullSite && value.location_status !== placement)
            throw new Error("目录定位状态与原始坐标不一致。");
        const points = fullSite ? [] : sourcePoints(value.source_points);
        const locations = fullSite ? [] : sourceRecords(value.source_location_records, points);
        return { id: value.id, title: value.title, repr_point: value.repr_point === null ? null : [...value.repr_point], location_status: placement, countries: stringArray(geography.countries, "country"),
            regions: stringArray(geography.regions, "region"), source_kind: value.source_kind, chronology_status: status, source_points: points, source_location_records: locations };
    }
    function parseCatalogue(value, coverage) {
        if (!record(value) || value.corpus_version !== coverage.corpus_version || value.total !== coverage.total
            || !Array.isArray(value.points) || value.points.length !== coverage.total)
            throw new Error("全库点目录与覆盖统计版本或总数不一致。");
        const spatial = coverage.spatial_locations;
        if ((value.spatial_version ?? null) !== (spatial?.version ?? null))
            throw new Error("来源定位目录与统计版本不一致。");
        if (spatial?.ready && value.points.some((point) => !record(point) || !Array.isArray(point.source_points) || !Array.isArray(point.source_location_records)))
            throw new Error("来源定位就绪目录缺少源点或逐点记录。");
        const points = value.points.map((item) => parsePoint(item));
        if (new Set(points.map((item) => item.id)).size !== points.length
            || points.some((item) => item.countries.some((id) => !coverage.countries.some((facet) => facet.id === id))
                || item.regions.some((id) => !coverage.regions.some((facet) => facet.id === id))))
            throw new Error("全库点目录存在重复编号或未登记地域标签。");
        for (const state of ["mapped", "polar", "unknown"]) {
            if (points.filter((point) => point.location_status === state).length !== coverage.locations[state])
                throw new Error("全库定位状态数量与覆盖统计不一致。");
        }
        if (spatial) {
            const rawCount = points.reduce((sum, point) => sum + point.source_points.length, 0);
            const distinct = points.reduce((sum, point) => sum + new Set(point.source_points.map(coordinateKey)).size, 0);
            const displayCount = points.reduce((sum, point) => sum + placements(point).length, 0);
            if (rawCount !== spatial.points || distinct !== spatial.distinct_points || displayCount !== spatial.display_points
                || points.filter((point) => point.source_points.length > 0).length > spatial.records || spatial.records > coverage.total)
                throw new Error("来源定位点序列与覆盖统计数量不一致。");
        }
        else if (points.some((point) => point.source_points.length > 0))
            throw new Error("来源定位点缺少版本与许可统计，未替换已有地图。");
        return { corpus_version: coverage.corpus_version, spatial_version: spatial?.version ?? null, total: coverage.total, points };
    }
    function parsePage(value, catalogue, state) {
        const points = catalogue.points.filter((point) => matches(point, state));
        if (!record(value) || value.corpus_version !== catalogue.corpus_version || value.total !== points.length
            || value.offset !== state.offset || value.limit !== pageSize || !Array.isArray(value.sites)
            || value.sites.length !== Math.min(pageSize, Math.max(0, points.length - state.offset)))
            throw new Error("目录分页与点位范围或版本不一致。");
        const byId = new Map(points.map((point) => [point.id, point]));
        const sites = value.sites.map((item) => {
            const site = parsePoint(item, true);
            const point = byId.get(site.id);
            return { ...site, source_points: point?.source_points ?? [], source_location_records: point?.source_location_records ?? [] };
        });
        if (new Set(sites.map((site) => site.id)).size !== sites.length || sites.some((site, index) => {
            const point = byId.get(site.id);
            return site.id !== points[state.offset + index]?.id || !point || JSON.stringify(point) !== JSON.stringify(site);
        }))
            throw new Error("目录分页与点位来源记录不一致。");
        return { corpus_version: catalogue.corpus_version, total: points.length, offset: state.offset, limit: pageSize, sites };
    }
    function create({ map, onSelect, onFilterChange, onStateChange, onCommittedState, onCatalogue, onFeedback }) {
        const get = (id) => {
            const node = document.getElementById(id);
            if (!node)
                throw new Error(`目录组件缺少 ${id}。`);
            return node;
        };
        const ui = {
            panel: get("explore-panel"), summary: get("explore-summary"), country: get("explore-country"),
            authority: get("explore-authority"),
            polarAuthority: get("explore-polar-authority"),
            spatial: get("explore-spatial-source"),
            region: get("explore-region"), clear: get("explore-clear"),
            points: get("explore-points"), fit: get("explore-fit"),
            count: get("explore-count"), list: get("explore-list"),
            previous: get("explore-previous"), next: get("explore-next"),
            page: get("explore-page"), feedback: get("explore-feedback"), retry: get("explore-retry"),
            limit: get("explore-limit-note"),
        };
        const limitNote = ui.limit.textContent ?? "";
        let desired = normalizeState({});
        let applied = null;
        let coverage = null;
        let catalogue = null;
        let page = null;
        let controller = null;
        let sequence = 0;
        let loading = false;
        let failed = false;
        let layer = null;
        let markers = new Map();
        let selectedId = null;
        const buttons = new Map();
        let renderer = null;
        if (map && typeof L !== "undefined") {
            const pane = map.getPane("catalogue-points") ?? map.createPane("catalogue-points");
            pane.style.zIndex = "450";
            renderer = L.canvas({ pane: "catalogue-points", padding: 0.5 });
        }
        function feedback(message, error = false) {
            failed = error;
            ui.panel.classList.toggle("has-error", error);
            ui.feedback.textContent = message;
            ui.retry.hidden = !error;
            onFeedback?.(message);
        }
        function getCommittedState() {
            return applied ? { ...applied, visible: desired.visible } : null;
        }
        function committed() {
            const state = getCommittedState();
            if (state)
                onCommittedState?.(state);
        }
        function renderAuthority() {
            const source = coverage?.authority;
            ui.authority.hidden = source === null || source === undefined;
            if (!source) {
                ui.authority.replaceChildren();
                return;
            }
            const summary = element("span", undefined, `当前官方文化／混合名录 ${source.covered.toLocaleString("zh-CN")} / ${source.eligible_total.toLocaleString("zh-CN")} 条已覆盖`);
            const link = element("a", undefined, "UNESCO 官方来源");
            link.href = source.source_uri;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            const license = element("a", undefined, source.license);
            license.href = source.license_uri;
            license.target = "_blank";
            license.rel = "noopener noreferrer";
            const note = element("span", "explore-authority-note", `来源更新：${source.source_modified.split("T")[0]} · ${source.missing} 条待覆盖 · ${source.excluded_natural} 条纯自然遗产不在本语料范围。`);
            note.title = `${source.dataset}\nSHA256: ${source.source_sha256}\n${source.note}`;
            ui.authority.replaceChildren(summary, link, license, note);
        }
        function renderPolarAuthority() {
            const source = coverage?.polar_authority;
            ui.polarAuthority.hidden = source === null || source === undefined;
            if (!source) {
                ui.polarAuthority.replaceChildren();
                return;
            }
            const summary = element("span", undefined, `ATS 历史名录 ${source.covered} / ${source.eligible_total} 条已收录（包含位置未知记录）`);
            const link = element("a", undefined, "ATS 官方来源");
            link.href = source.source_uri;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            const license = element("a", undefined, source.license);
            license.href = source.license_uri;
            license.target = "_blank";
            license.rel = "noopener noreferrer";
            const excluded = Object.entries(source.excluded_types).map(([kind, amount]) => `${kind} ${amount}`).join("、");
            const note = element("span", "explore-authority-note", `来源核对：${source.source_accessed} · 未收录 ${source.missing} 条；排除其他保护区：${excluded || "无"}。`);
            note.title = `${source.dataset}\nSHA256: ${source.source_sha256}\n${source.note}`;
            ui.polarAuthority.replaceChildren(summary, link, license, note);
        }
        function renderSpatial() {
            const spatial = coverage?.spatial_locations;
            ui.spatial.hidden = spatial === null || spatial === undefined;
            if (!spatial) {
                ui.spatial.replaceChildren();
                return;
            }
            if (!spatial.ready || !spatial.source) {
                ui.spatial.replaceChildren(element("span", undefined, `来源多点资料未就绪：${spatial.reason ?? "请检查本地数据版本"}。保留可用代表点；目录和检索仍按资料条目展示。`));
                return;
            }
            const source = spatial.source;
            const summary = element("span", undefined, `${spatial.records.toLocaleString("zh-CN")} 条遗产资料包含 ${spatial.points.toLocaleString("zh-CN")} 个来源定位点记录`);
            const link = element("a", undefined, source.name);
            link.href = source.uri;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            const license = element("a", undefined, source.license);
            license.href = source.license_uri;
            license.target = "_blank";
            license.rel = "noopener noreferrer";
            const note = element("span", "explore-authority-note", `来源版本：${source.version.split("T")[0]} · 同一遗产内 ${spatial.duplicate_points.toLocaleString("zh-CN")} 个同坐标记录保留在来源序列，地图仅绘一次；定位点数不等于遗址数。`);
            note.title = `${spatial.version}\nSHA256: ${source.sha256}`;
            ui.spatial.replaceChildren(summary, link, license, note);
        }
        function renderControls() {
            ui.panel.setAttribute("aria-busy", String(loading));
            ui.country.disabled = coverage === null;
            ui.region.disabled = coverage === null;
            ui.clear.disabled = desired.country === null && desired.region === null && desired.offset === 0;
            ui.points.checked = desired.visible;
            ui.points.disabled = !map || !catalogue;
            ui.fit.disabled = !map || !catalogue || !catalogue.points.some((point) => matches(point, applied ?? desired) && placements(point).length > 0);
            ui.previous.disabled = loading || page === null || page.offset === 0;
            ui.previous.textContent = page && page.offset >= page.total && page.total > 0 ? "回到首页" : "上一页";
            ui.next.disabled = loading || page === null || page.offset + page.limit >= page.total;
            ui.retry.disabled = loading;
            if (layer && map) {
                if (desired.visible && !map.hasLayer(layer))
                    layer.addTo(map);
                else if (!desired.visible && map.hasLayer(layer))
                    map.removeLayer(layer);
            }
        }
        function renderOptions() {
            if (!coverage)
                return;
            const populate = (select, values, label, selected, isRegion = false) => {
                const all = element("option", undefined, label);
                all.value = "";
                const options = values.map((item) => {
                    const option = element("option", undefined, `${isRegion ? regionLabels[item.id] : countryLabel(item)} · ${item.count}`);
                    option.title = item.label;
                    option.value = item.id;
                    return option;
                });
                if (selected !== null && !values.some((item) => item.id === selected)) {
                    const missing = element("option", undefined, `${selected}（当前来源无此标签）`);
                    missing.value = selected;
                    missing.disabled = true;
                    options.push(missing);
                }
                select.replaceChildren(all, ...options);
                select.value = selected ?? "";
            };
            populate(ui.country, coverage.countries, "全部国家／地区", desired.country);
            populate(ui.region, coverage.regions, "全部来源分区", desired.region, true);
        }
        function select(id) {
            selectedId = id;
            for (const [pointId, button] of buttons)
                button.setAttribute("aria-pressed", String(pointId === id));
            for (const [pointId, copies] of markers)
                for (const marker of copies) {
                    const active = pointId === id;
                    marker.setRadius(active ? 5 : 3.2);
                    marker.setStyle({ color: active ? "#813d29" : "#586f60", fillColor: active ? "#a55339" : "#66745b", fillOpacity: active ? 0.95 : 0.5, weight: active ? 1.5 : 0.7 });
                }
        }
        function buildLayer(points) {
            const nextMarkers = new Map();
            if (!map || !renderer || typeof L === "undefined")
                return { layer: null, markers: nextMarkers };
            const next = L.layerGroup();
            for (const point of points) {
                const copies = placements(point).flatMap((placement) => displayCoordinates(placement.coordinate).map((location) => {
                    const marker = L.circleMarker(location, { pane: "catalogue-points", renderer: renderer ?? undefined, radius: 3.2,
                        color: "#586f60", fillColor: "#66745b", fillOpacity: 0.5, weight: 0.7 });
                    marker.bindTooltip(() => {
                        const tooltip = element("span", "explore-point-tooltip");
                        tooltip.append(element("span", undefined, point.title), element("span", "explore-point-kind", placement.representative
                            ? "原始代表点 · 非精确发掘坐标" : `来源定位点 · 源序 ${placement.sourceIndexes.map((index) => index + 1).join("、")}`));
                        for (const index of placement.sourceIndexes) {
                            const source = point.source_location_records[index];
                            if (source && (source.name || source.ref))
                                tooltip.append(element("span", "explore-point-kind", [source.name, source.ref].filter(Boolean).join(" · ")));
                        }
                        return tooltip;
                    }, { direction: "top", offset: [0, -4] });
                    marker.on("click", () => onSelect(point.id, map.getContainer(), { moveMap: false }));
                    marker.addTo(next);
                    return marker;
                }));
                nextMarkers.set(point.id, copies);
            }
            return { layer: next, markers: nextMarkers };
        }
        function renderPage() {
            if (!coverage || !page || !applied)
                return;
            const focused = ui.list.contains(document.activeElement);
            buttons.clear();
            const countryLabels = new Map(coverage.countries.map((item) => [item.id, countryLabel(item)]));
            const nodes = page.sites.map((site) => {
                const item = element("li");
                const button = element("button", "explore-item");
                button.type = "button";
                button.dataset.siteId = site.id;
                button.dataset.locationStatus = site.location_status;
                button.setAttribute("aria-pressed", String(site.id === selectedId));
                const title = site.title.trim().toLowerCase() === "untitled" ? `未命名地点 · #${site.id}` : site.title;
                button.setAttribute("aria-label", `${title}，打开目录资料，不属于检索排名`);
                const countries = site.countries.length ? site.countries.map((id) => countryLabels.get(id) ?? id).join(" · ") : "国家／地区未标注";
                button.append(element("span", "explore-item-title", title), element("span", "explore-item-meta", countries), element("span", "explore-item-meta", `${sourceLabels[site.source_kind] ?? site.source_kind} · ${chronologyLabels[site.chronology_status]} · ${locationLabels[site.location_status]}`));
                button.addEventListener("click", () => onSelect(site.id, button));
                buttons.set(site.id, button);
                item.append(button);
                return item;
            });
            if (!nodes.length)
                nodes.push(element("li", "explore-empty", page.total === 0 ? "所选国家／地区与分区组合暂无资料，可清除地域后继续浏览。" : "此目录位置超出当前筛选范围，可用上一页返回首页。"));
            ui.list.replaceChildren(...nodes);
            ui.list.scrollTop = 0;
            ui.count.textContent = `${page.total.toLocaleString("zh-CN")} 条符合地域条件`;
            const start = page.sites.length ? page.offset + 1 : 0;
            const end = page.offset + page.sites.length;
            ui.page.textContent = `${page.sites.length ? `第 ${start}—${end} 条` : "本页无资料"} / 共 ${page.total.toLocaleString("zh-CN")} 条 · 按来源标题排序，无相关性分数`;
            if (focused)
                ui.page.focus({ preventScroll: true });
        }
        async function json(path, signal) {
            const response = await fetch(path, { signal, headers: { Accept: "application/json" } });
            const value = await response.json();
            if (!response.ok)
                throw new Error(record(value) && typeof value.detail === "string" ? value.detail : `目录请求失败（HTTP ${response.status}）。`);
            return value;
        }
        async function request(refresh) {
            controller?.abort();
            const current = ++sequence;
            const abort = new AbortController();
            controller = abort;
            const wanted = { ...desired };
            const parameters = new URLSearchParams({ offset: String(wanted.offset), limit: String(pageSize) });
            if (wanted.country)
                parameters.set("country", wanted.country);
            if (wanted.region)
                parameters.set("region", wanted.region);
            loading = true;
            feedback(page ? "正在更新目录；列表与全库点位保留上次成功范围，检索排名和年份不变。" : "正在读取本地全库点位与覆盖统计。");
            renderControls();
            let pendingLayer = null;
            try {
                const reload = refresh || !coverage || !catalogue;
                const [coverageRaw, catalogueRaw, pageRaw] = await Promise.all([
                    reload ? json("/api/coverage", abort.signal) : Promise.resolve(null),
                    reload ? json("/api/catalogue", abort.signal) : Promise.resolve(null),
                    json(`/api/sites?${parameters}`, abort.signal),
                ]);
                if (abort.signal.aborted || current !== sequence)
                    return;
                const nextCoverage = reload ? parseCoverage(coverageRaw) : coverage;
                if (!nextCoverage)
                    throw new Error("覆盖统计尚未准备。");
                if ((wanted.country && !nextCoverage.countries.some((item) => item.id === wanted.country))
                    || (wanted.region && !nextCoverage.regions.some((item) => item.id === wanted.region)))
                    throw new Error("所选地域标签不在当前资料版本中，未放宽筛选。");
                const nextCatalogue = reload ? parseCatalogue(catalogueRaw, nextCoverage) : catalogue;
                if (!nextCatalogue)
                    throw new Error("全库点位尚未准备。");
                const nextPage = parsePage(pageRaw, nextCatalogue, wanted);
                const replacePoints = nextCatalogue !== catalogue || !applied || applied.country !== wanted.country || applied.region !== wanted.region;
                const next = replacePoints ? buildLayer(nextCatalogue.points.filter((point) => matches(point, wanted))) : { layer, markers };
                pendingLayer = replacePoints ? next.layer : null;
                if (abort.signal.aborted || current !== sequence)
                    return;
                if (replacePoints) {
                    if (next.layer && desired.visible && map)
                        next.layer.addTo(map);
                    if (layer && map && map.hasLayer(layer))
                        map.removeLayer(layer);
                }
                coverage = nextCoverage;
                catalogue = nextCatalogue;
                page = nextPage;
                applied = { ...wanted };
                layer = next.layer;
                markers = next.markers;
                ui.summary.textContent = `${coverage.total.toLocaleString("zh-CN")} 条资料 · ${coverage.countries.length} 个国家／地区 · ${coverage.regions.length} 个来源分区`;
                ui.limit.textContent = `${limitNote} 当前 ${coverage.country_unknown.toLocaleString("zh-CN")} 条未标注国家／地区；${coverage.chronology.not_reviewed.toLocaleString("zh-CN")} 条断代尚未核验。`;
                renderAuthority();
                renderPolarAuthority();
                renderSpatial();
                renderOptions();
                renderPage();
                if (selectedId !== null)
                    select(selectedId);
                const scoped = nextCatalogue.points.filter((point) => matches(point, wanted));
                const mapped = scoped.filter((point) => point.location_status === "mapped").length;
                const polar = scoped.filter((point) => point.location_status === "polar").length;
                const unknown = scoped.filter((point) => point.location_status === "unknown").length;
                const positions = scoped.flatMap(placements);
                const sourceCount = positions.filter((position) => position.sourceIndexes.length > 0).length;
                const representativeCount = positions.length - sourceCount;
                feedback(`当前地域范围 ${page.total.toLocaleString("zh-CN")} 条资料 / 主图 ${sourceCount.toLocaleString("zh-CN")} 个源定位点 + ${representativeCount.toLocaleString("zh-CN")} 个必要代表点。代表点状态：主图可定位 ${mapped}、极区 ${polar}、位置未知 ${unknown}。${map ? "同一遗产内同坐标源记录只绘一点；编号为检索候选。" : "地图组件不可用，可使用目录列表。"}`);
                if (reload)
                    onCatalogue?.(nextCatalogue.points.map((point) => ({ ...point,
                        repr_point: point.repr_point === null ? null : [...point.repr_point], countries: [...point.countries], regions: [...point.regions],
                        source_points: point.source_points.map((value) => [...value]), source_location_records: point.source_location_records.map((source) => ({ ...source, coordinate: [...source.coordinate] })) })));
                committed();
            }
            catch (error) {
                if (abort.signal.aborted || current !== sequence)
                    return;
                if (pendingLayer && map?.hasLayer(pendingLayer))
                    map.removeLayer(pendingLayer);
                if (layer && desired.visible && map && !map.hasLayer(layer))
                    layer.addTo(map);
                abort.abort();
                feedback(`${error instanceof Error ? error.message : "目录加载失败。"}${page ? " 保留上次成功目录与点位。" : " 可重试本地目录；基础检索仍独立可用。"}`, true);
                throw error;
            }
            finally {
                if (current === sequence) {
                    loading = false;
                    controller = null;
                    renderControls();
                }
            }
        }
        function load() { return request(true); }
        async function setState(value, options = {}) {
            let next;
            try {
                next = normalizeState({ ...desired, ...value });
            }
            catch (error) {
                feedback(error instanceof Error ? error.message : "目录条件无效。", true);
                throw error;
            }
            const filterChanged = next.country !== desired.country || next.region !== desired.region;
            const pageChanged = next.offset !== desired.offset;
            const visibilityChanged = next.visible !== desired.visible;
            const changed = filterChanged || pageChanged || next.visible !== desired.visible;
            desired = next;
            renderOptions();
            renderControls();
            if (options.notify && changed) {
                if (filterChanged)
                    onFilterChange?.({ ...desired });
                onStateChange?.({ ...desired });
            }
            if (filterChanged || pageChanged || !catalogue)
                await request(false);
            else if (visibilityChanged)
                committed();
        }
        ui.country.addEventListener("change", () => { void setState({ country: ui.country.value || null, offset: 0 }, { notify: true }).catch(() => undefined); });
        ui.region.addEventListener("change", () => { void setState({ region: ui.region.value || null, offset: 0 }, { notify: true }).catch(() => undefined); });
        ui.clear.addEventListener("click", () => { void setState({ country: null, region: null, offset: 0 }, { notify: true }).catch(() => undefined); });
        ui.points.addEventListener("change", () => { void setState({ visible: ui.points.checked }, { notify: true }).catch(() => undefined); });
        ui.previous.addEventListener("click", () => { void setState({ offset: page && page.offset >= page.total ? 0 : Math.max(0, desired.offset - pageSize) }, { notify: true }).catch(() => undefined); });
        ui.next.addEventListener("click", () => { if (page && page.offset + page.limit < page.total)
            void setState({ offset: page.offset + page.limit }, { notify: true }).catch(() => undefined); });
        ui.retry.addEventListener("click", () => { void load().catch(() => undefined); });
        ui.fit.addEventListener("click", () => {
            if (!map || !catalogue)
                return;
            const points = catalogue.points.filter((point) => matches(point, applied ?? desired)).flatMap(placements)
                .map((point) => [point.coordinate[1], point.coordinate[0]]);
            if (points.length)
                map.fitBounds(L.latLngBounds(ArchSearchMapView.wrapCoordinates(points)), { padding: [40, 40], maxZoom: 9, animate: false });
        });
        renderControls();
        return { load, getState: () => ({ ...desired }), getCommittedState, setState, select,
            getPoint: (id) => {
                const point = catalogue?.points.find((item) => item.id === id);
                return point?.repr_point ? [...point.repr_point] : null;
            },
            getLocationStatus: (id) => catalogue?.points.find((point) => point.id === id)?.location_status ?? null,
            getSourcePoints: (id) => catalogue?.points.find((point) => point.id === id)?.source_points.map((value) => [...value]) ?? [],
            getSourceLocationRecords: (id) => catalogue?.points.find((point) => point.id === id)?.source_location_records.map((source) => ({ ...source, coordinate: [...source.coordinate] })) ?? [],
            getDisplayPoints: (id) => {
                const point = catalogue?.points.find((item) => item.id === id);
                return point ? placements(point).map((placement) => [...placement.coordinate]) : [];
            },
            getSpatialMetadata: () => coverage?.spatial_locations ? JSON.parse(JSON.stringify(coverage.spatial_locations)) : null,
        };
    }
    return { create, normalizeState, matches, coordinate, displayCoordinates, locationStatus, placements, parseSpatial, parseCoverage, parseCatalogue, parsePage };
})();
//# sourceMappingURL=explore.js.map