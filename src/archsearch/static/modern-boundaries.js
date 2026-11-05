"use strict";
const ArchSearchModernBoundaries = (() => {
    "use strict";
    const classes = ["International boundary (verify)", "Disputed (please verify)", "Line of control (please verify)", "Indefinite (please verify)", "Indeterminant frontier"];
    const uri = "/static/data/modern-boundaries.geojson";
    function record(value) {
        return value !== null && typeof value === "object" && !Array.isArray(value);
    }
    function parse(value) {
        const line = (input) => Array.isArray(input) && input.length >= 2
            && input.every(point => Array.isArray(point) && point.length === 2 && typeof point[0] === "number" && Number.isFinite(point[0]) && Math.abs(point[0]) <= 180
                && typeof point[1] === "number" && Number.isFinite(point[1]) && Math.abs(point[1]) <= 90)
            && input.every((point, index) => index === 0 || Math.abs(point[0] - input[index - 1][0]) <= 180);
        if (!record(value) || value.type !== "FeatureCollection" || !Array.isArray(value.features) || value.features.length === 0
            || !record(value.metadata) || value.metadata.schema_version !== 1 || value.metadata.feature_count !== value.features.length
            || !record(value.metadata.source) || value.metadata.source.version !== "5.1.0" || value.metadata.source.license !== "Public domain"
            || value.metadata.source.name !== "Natural Earth 1:50m Admin 0 land boundary lines"
            || value.metadata.source.uri !== "https://www.naturalearthdata.com/downloads/50m-cultural-vectors/50m-admin-0-boundary-lines-2/") {
            throw new Error("现代边界资料版本或元数据不匹配。");
        }
        const ids = new Set();
        for (const feature of value.features) {
            if (!record(feature) || feature.type !== "Feature" || !record(feature.properties) || !record(feature.geometry)
                || typeof feature.properties.source_id !== "number" || !Number.isSafeInteger(feature.properties.source_id)
                || typeof feature.properties.record_id !== "number" || !Number.isSafeInteger(feature.properties.record_id) || ids.has(feature.properties.record_id)
                || typeof feature.properties.classification !== "string" || !classes.includes(feature.properties.classification)
                || !(feature.geometry.type === "LineString" ? line(feature.geometry.coordinates)
                    : feature.geometry.type === "MultiLineString" && Array.isArray(feature.geometry.coordinates) && feature.geometry.coordinates.length > 0 && feature.geometry.coordinates.every(line))) {
                throw new Error("现代边界线几何或来源分类无效。");
            }
            ids.add(feature.properties.record_id);
        }
        return value;
    }
    function worldCopies(value) {
        const shift = (line, offset) => line.map(point => [point[0] + offset, point[1]]);
        return { ...value, features: [-360, 0, 360].flatMap(offset => value.features.map(feature => ({ ...feature,
                geometry: feature.geometry.type === "LineString" ? { type: "LineString", coordinates: shift(feature.geometry.coordinates, offset) }
                    : { type: "MultiLineString", coordinates: feature.geometry.coordinates.map(line => shift(line, offset)) },
            }))) };
    }
    function style(classification, halo = false) {
        return { color: halo ? "#faf7ef" : classification === "International boundary (verify)" ? "#42506a" : "#795b53",
            weight: halo ? 4.6 : 1.8, opacity: halo ? 0.96 : 0.95, fill: false, interactive: false,
            dashArray: classification === "International boundary (verify)" ? undefined : "5 4", lineCap: "round", lineJoin: "round" };
    }
    function create({ map, onStatus = () => undefined }) {
        let current = { state: map ? "loading" : "unavailable", message: map ? "正在加载本地现代边界线参照。" : "现代地图未初始化，边界线未加载。", visible: false, sourceVersion: null };
        let halo = null, ink = null;
        let pending = null;
        const publish = (next) => { current = next; onStatus({ ...current }); };
        let renderer = null;
        if (map) {
            const pane = map.getPane("modern-country-boundaries") ?? map.createPane("modern-country-boundaries");
            pane.style.zIndex = "320";
            pane.style.pointerEvents = "none";
            renderer = L.canvas({ pane: "modern-country-boundaries" });
        }
        function retry() {
            if (!map)
                return Promise.resolve();
            if (pending)
                return pending;
            publish({ ...current, state: "loading", message: "正在加载本地现代边界线参照。" });
            pending = (async () => {
                let nextHalo = null, nextInk = null;
                try {
                    const response = await fetch(uri, { headers: { Accept: "application/geo+json, application/json" } });
                    if (!response.ok)
                        throw new Error("现代边界线未能读取。");
                    const collection = parse(await response.json());
                    const copies = worldCopies(collection);
                    const options = { pane: "modern-country-boundaries", renderer: renderer ?? undefined, interactive: false,
                        attribution: "Natural Earth 1:50m Admin 0 · v5.1.0 · Public Domain" };
                    nextHalo = L.geoJSON(copies, { ...options, style: feature => style(feature?.properties.classification, true) });
                    nextInk = L.geoJSON(copies, { ...options, style: feature => style(feature?.properties.classification) });
                    nextHalo.addTo(map);
                    nextInk.addTo(map);
                    halo?.remove();
                    ink?.remove();
                    halo = nextHalo;
                    ink = nextInk;
                    publish({ state: "ready", message: "现代边界线参照 · Natural Earth 5.1.0；虚线为来源标注的争议、控制或不确定线。", visible: true, sourceVersion: collection.metadata.source.version });
                }
                catch {
                    nextHalo?.remove();
                    nextInk?.remove();
                    publish({ ...current, state: "error", message: current.visible ? "现代边界线更新失败，保留已加载线层；可重试。" : "现代边界线未能加载；底图、遗址点与历史图仍可使用，可重试。" });
                }
                finally {
                    pending = null;
                }
            })();
            return pending;
        }
        if (map)
            void retry();
        else
            onStatus({ ...current });
        return { retry, getState: () => ({ ...current }) };
    }
    return { create, parse, worldCopies, style };
})();
//# sourceMappingURL=modern-boundaries.js.map