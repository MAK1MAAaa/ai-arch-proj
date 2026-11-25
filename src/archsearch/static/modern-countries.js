"use strict";
const ArchSearchModernCountries = (() => {
    "use strict";
    const uri = "/static/data/modern-countries.geojson";
    const paneName = "comparison-modern-countries";
    const defaultHoverDelayMs = 5000;
    const typeLabels = {
        "Sovereign country": "主权国家",
        Country: "国家／地区",
        Dependency: "属地／海外领地",
        Disputed: "争议地区",
        Indeterminate: "未定地区",
        Sovereignty: "主权实体",
    };
    function record(value) {
        return value !== null && typeof value === "object" && !Array.isArray(value);
    }
    function element(tag, className = null, textValue = "") {
        const node = document.createElement(tag);
        if (className)
            node.className = className;
        if (textValue)
            node.textContent = textValue;
        return node;
    }
    function safeSource(href, label) {
        try {
            const url = new URL(href);
            if (url.protocol === "https:" || url.protocol === "http:") {
                const link = element("a", null, label);
                link.href = url.href;
                link.target = "_blank";
                link.rel = "noopener noreferrer";
                return link;
            }
        }
        catch { /* Non-HTTP source links degrade cleanly to text. */ }
        return element("span", null, label);
    }
    function parse(value) {
        const ring = (points) => Array.isArray(points) && points.length >= 4
            && points.every(p => Array.isArray(p) && p.length === 2 && typeof p[0] === "number" && Number.isFinite(p[0]) && Math.abs(p[0]) <= 180
                && typeof p[1] === "number" && Number.isFinite(p[1]) && Math.abs(p[1]) <= 90)
            && points[0][0] === points[points.length - 1][0] && points[0][1] === points[points.length - 1][1];
        const polygon = (rings) => Array.isArray(rings) && rings.length > 0 && rings.every(ring);
        if (!record(value) || value.type !== "FeatureCollection" || !Array.isArray(value.features) || value.features.length === 0
            || !record(value.metadata) || value.metadata.schema_version !== 1 || value.metadata.feature_count !== value.features.length
            || !record(value.metadata.source) || value.metadata.source.version !== "5.1.1" || value.metadata.source.license !== "Public domain"
            || value.metadata.source.name !== "Natural Earth 1:110m Admin 0 countries"
            || value.metadata.source.uri !== "https://www.naturalearthdata.com/downloads/110m-cultural-vectors/110m-admin-0-countries/") {
            throw new Error("现代国家与地区资料版本或元数据不匹配。");
        }
        const ids = new Set();
        for (const feature of value.features) {
            if (!record(feature) || feature.type !== "Feature" || !record(feature.properties) || !record(feature.geometry)
                || typeof feature.properties.record_id !== "number" || !Number.isSafeInteger(feature.properties.record_id) || ids.has(feature.properties.record_id)
                || typeof feature.properties.source_id !== "number" || !Number.isSafeInteger(feature.properties.source_id)
                || typeof feature.properties.name !== "string" || !feature.properties.name.trim()
                || typeof feature.properties.name_zh !== "string" || !feature.properties.name_zh.trim()
                || typeof feature.properties.formal_en !== "string"
                || typeof feature.properties.iso_a2 !== "string"
                || typeof feature.properties.continent !== "string"
                || typeof feature.properties.subregion !== "string"
                || typeof feature.properties.type !== "string" || !feature.properties.type.trim()
                || typeof feature.properties.wikidata_id !== "string" || !feature.properties.wikidata_id.trim()
                || !(feature.geometry.type === "Polygon" ? polygon(feature.geometry.coordinates)
                    : feature.geometry.type === "MultiPolygon" && Array.isArray(feature.geometry.coordinates) && feature.geometry.coordinates.length > 0 && feature.geometry.coordinates.every(polygon))) {
                throw new Error("现代国家与地区几何或属性无效。");
            }
            ids.add(feature.properties.record_id);
        }
        return value;
    }
    function worldCopies(value) {
        const shiftRing = (points, offset) => points.map(point => [point[0] + offset, point[1]]);
        const shiftPolygon = (rings, offset) => rings.map(points => shiftRing(points, offset));
        return {
            ...value,
            features: [-360, 0, 360].flatMap(offset => value.features.map(feature => ({
                ...feature,
                geometry: feature.geometry.type === "Polygon"
                    ? { type: "Polygon", coordinates: shiftPolygon(feature.geometry.coordinates, offset) }
                    : { type: "MultiPolygon", coordinates: feature.geometry.coordinates.map(rings => shiftPolygon(rings, offset)) },
            }))),
        };
    }
    function style(naturalMode, hovered = false) {
        if (!naturalMode) {
            return { fill: true, fillOpacity: 0, stroke: false, interactive: true };
        }
        return {
            fill: true,
            fillColor: hovered ? "#6d7d66" : "#7e8e76",
            fillOpacity: hovered ? 0.16 : 0.04,
            stroke: true,
            color: hovered ? "#5e6e58" : "#8c9a86",
            weight: hovered ? 1.15 : 0.6,
            opacity: hovered ? 0.72 : 0.35,
            interactive: true,
        };
    }
    function popup(properties, source) {
        const content = element("div", "history-popup modern-country-popup");
        content.append(element("strong", null, properties.name_zh));
        const secondary = properties.formal_en && properties.formal_en !== properties.name
            ? `${properties.name} · ${properties.formal_en}`
            : properties.name;
        if (secondary && secondary !== properties.name_zh) {
            content.append(element("p", "modern-country-en", secondary));
        }
        const kindLabel = typeLabels[properties.type] ? `${typeLabels[properties.type]}（${properties.type}）` : properties.type;
        content.append(element("p", null, `来源分类：${kindLabel}`));
        const region = [properties.continent, properties.subregion].filter(Boolean).join(" · ");
        if (region)
            content.append(element("p", null, `地理分区：${region}`));
        const ids = element("p");
        const hasIso = properties.iso_a2 && properties.iso_a2 !== "-99";
        if (hasIso)
            ids.append(document.createTextNode(`代码：ISO ${properties.iso_a2} · `));
        else
            ids.append(document.createTextNode("条目："));
        ids.append(safeSource(`https://www.wikidata.org/wiki/${encodeURIComponent(properties.wikidata_id)}`, `Wikidata ${properties.wikidata_id}`));
        content.append(ids);
        content.append(element("p", null, "现代国家与地区范围来自 Natural Earth 1:110m Admin 0 公开资料，仅作现代地理参照，不代表历史政治归属或法定边界主张。"));
        const license = element("p");
        license.append(safeSource(source.uri, `${source.name} v${source.version}`), document.createTextNode(" · "), safeSource(source.license_uri ?? "https://www.naturalearthdata.com/about/terms-of-use/", "Public Domain"));
        content.append(license);
        return content;
    }
    function create({ map, hoverDelayMs = defaultHoverDelayMs }) {
        let layer = null;
        let sourceInfo = null;
        let loading = false;
        let hoverTimer = null;
        let hoveredRecordId = null;
        let hoveredFeatureLayer = null;
        let hoverLatLng = null;
        let hoverOpen = false;
        const isNaturalMode = () => map?.getContainer().dataset.basemap === "natural";
        let renderer = null;
        if (map && typeof L !== "undefined") {
            const pane = map.getPane(paneName) ?? map.createPane(paneName);
            pane.style.zIndex = "250";
            renderer = L.canvas({ pane: paneName });
        }
        const detailPopup = map && typeof L !== "undefined" && typeof L.popup === "function"
            ? L.popup({ maxWidth: 310 })
            : null;
        const hoverTooltip = map && typeof L !== "undefined" && typeof L.tooltip === "function"
            ? L.tooltip({ className: "map-hover-name-preview", direction: "top", offset: [0, -10], interactive: false })
            : null;
        function clearHoverPreview() {
            if (hoverTimer !== null) {
                clearTimeout(hoverTimer);
                hoverTimer = null;
            }
            hoveredRecordId = null;
            if (hoveredFeatureLayer) {
                hoveredFeatureLayer.setStyle(style(isNaturalMode(), false));
                hoveredFeatureLayer = null;
            }
            hoverLatLng = null;
            if (hoverOpen && hoverTooltip && map) {
                map.removeLayer(hoverTooltip);
                hoverOpen = false;
            }
        }
        function refreshStyles() {
            if (!layer)
                return;
            const naturalMode = isNaturalMode();
            layer.setStyle(() => style(naturalMode, false));
            if (!naturalMode && detailPopup && map?.hasLayer(detailPopup)) {
                map.closePopup(detailPopup);
            }
        }
        async function load() {
            if (!map || typeof L === "undefined" || loading || layer)
                return;
            loading = true;
            try {
                const response = await fetch(uri, { headers: { Accept: "application/geo+json, application/json" } });
                if (!response.ok)
                    return;
                const collection = parse(await response.json());
                sourceInfo = collection.metadata.source;
                const copies = worldCopies(collection);
                const countryOptions = {
                    pane: paneName,
                    renderer: renderer ?? undefined,
                    interactive: true,
                    style: () => ({ ...style(isNaturalMode(), false), pane: paneName, renderer: renderer ?? undefined }),
                    onEachFeature: (feature, featureLayer) => {
                        const properties = feature.properties;
                        const pathLayer = featureLayer;
                        pathLayer.on("mouseover", (event) => {
                            if (hoveredRecordId !== properties.record_id) {
                                clearHoverPreview();
                                hoveredRecordId = properties.record_id;
                                hoveredFeatureLayer = pathLayer;
                                if (isNaturalMode())
                                    pathLayer.setStyle(style(true, true));
                                hoverLatLng = event?.latlng ?? featureLayer.getCenter?.() ?? null;
                                hoverTimer = setTimeout(() => {
                                    hoverTimer = null;
                                    if (!map || !hoverTooltip || hoveredRecordId !== properties.record_id || !hoverLatLng)
                                        return;
                                    if (detailPopup && map.hasLayer(detailPopup))
                                        return;
                                    const label = element("span", "map-hover-name-wrap");
                                    label.append(element("span", "map-hover-name-main", properties.name_zh));
                                    if (properties.name && properties.name !== properties.name_zh) {
                                        label.append(element("span", "map-hover-name-en", properties.name));
                                    }
                                    hoverTooltip.setLatLng(hoverLatLng).setContent(label).addTo(map);
                                    hoverOpen = true;
                                }, hoverDelayMs);
                            }
                        });
                        pathLayer.on("mousemove", (event) => {
                            if (hoveredRecordId === properties.record_id && event?.latlng) {
                                hoverLatLng = event.latlng;
                                if (hoverOpen && hoverTooltip)
                                    hoverTooltip.setLatLng(hoverLatLng);
                            }
                        });
                        pathLayer.on("mouseout", () => {
                            if (hoveredRecordId === properties.record_id)
                                clearHoverPreview();
                        });
                        pathLayer.on("click", (event) => {
                            clearHoverPreview();
                            if (!isNaturalMode() || !detailPopup || !sourceInfo || !map)
                                return;
                            L.DomEvent?.stopPropagation?.(event);
                            const targetLatLng = event?.latlng ?? featureLayer.getCenter?.();
                            if (!targetLatLng)
                                return;
                            detailPopup.setLatLng(targetLatLng).setContent(popup(properties, sourceInfo)).openOn(map);
                        });
                    },
                };
                const nextLayer = L.geoJSON(copies, countryOptions);
                nextLayer.addTo(map);
                nextLayer.bringToBack();
                layer = nextLayer;
                refreshStyles();
            }
            catch {
                /* Local country overlay failure never blocks basemaps or site markers. */
            }
            finally {
                loading = false;
            }
        }
        if (map) {
            map.on("archsearch:basemapchange", refreshStyles);
            map.on("movestart zoomstart popupopen", clearHoverPreview);
            map.getContainer()?.addEventListener("mouseleave", clearHoverPreview);
            void load();
        }
        return {
            reload: load,
            refreshStyles,
            clearHoverPreview,
        };
    }
    return { create, parse, worldCopies, style };
})();
//# sourceMappingURL=modern-countries.js.map