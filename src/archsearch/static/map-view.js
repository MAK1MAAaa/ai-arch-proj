"use strict";
const ArchSearchMapView = (() => {
    "use strict";
    function markers(candidate) {
        return [...(candidate.marker ? [candidate.marker] : []), ...(candidate.additionalMarkers ?? [])];
    }
    function containsPoint(point, size) {
        return point !== null
            && Number.isFinite(point.x) && Number.isFinite(point.y)
            && Number.isFinite(size.x) && Number.isFinite(size.y)
            && size.x > 0 && size.y > 0
            && point.x >= 0 && point.x <= size.x
            && point.y >= 0 && point.y <= size.y;
    }
    function wrapLongitude(longitude, center) {
        return longitude + 360 * Math.round((center - longitude) / 360);
    }
    function locationStatus(coordinate) {
        if (!coordinate || coordinate.length !== 2 || !coordinate.every(Number.isFinite)
            || Math.abs(coordinate[0]) > 180 || Math.abs(coordinate[1]) > 90)
            return "unknown";
        return Math.abs(coordinate[1]) > 85.0511287798 ? "polar" : "mapped";
    }
    function wrapCoordinates(coordinates) {
        if (coordinates.length < 2)
            return coordinates;
        const longitudes = coordinates.map((coordinate) => ((coordinate[1] % 360) + 360) % 360).sort((a, b) => a - b);
        let gap = -1;
        let start = longitudes[0];
        for (let index = 0; index < longitudes.length; index++) {
            const next = longitudes[(index + 1) % longitudes.length] + (index + 1 === longitudes.length ? 360 : 0);
            if (next - longitudes[index] > gap) {
                gap = next - longitudes[index];
                start = next % 360;
            }
        }
        const center = start + (360 - gap) / 2;
        const shift = 360 * Math.floor((center + 180) / 360);
        return coordinates.map(([latitude, longitude]) => [latitude, wrapLongitude(longitude, center) - shift]);
    }
    function create({ map, countLabel, scopeLabel = "当前地图范围内" }) {
        let candidates = [];
        let pointerSource = null;
        let focusSource = null;
        let preview = null;
        let cleanup = [];
        function setPreview(candidate) {
            if (preview === candidate) {
                candidate?.marker?.openTooltip();
                return;
            }
            if (preview !== null) {
                preview.card.classList.remove("is-preview");
                for (const marker of markers(preview)) {
                    marker.getElement()?.classList.remove("is-preview");
                    marker.closeTooltip();
                }
            }
            preview = candidate;
            if (candidate !== null) {
                candidate.card.classList.add("is-preview");
                for (const marker of markers(candidate)) {
                    marker.getElement()?.classList.add("is-preview");
                    marker.openTooltip();
                }
            }
        }
        function renderPreview() {
            setPreview((focusSource ?? pointerSource)?.candidate ?? null);
        }
        function enterPointer(source) {
            pointerSource = source;
            renderPreview();
        }
        function leavePointer(source) {
            if (pointerSource === source)
                pointerSource = null;
            renderPreview();
        }
        function enterFocus(source) {
            focusSource = source;
            renderPreview();
        }
        function leaveFocus(source) {
            if (focusSource === source)
                focusSource = null;
            renderPreview();
        }
        function bindDom(source, node, pointerEvents) {
            const focus = () => enterFocus(source);
            const blur = () => leaveFocus(source);
            node.addEventListener("focus", focus);
            node.addEventListener("blur", blur);
            cleanup.push(() => {
                node.removeEventListener("focus", focus);
                node.removeEventListener("blur", blur);
                node.classList.remove("is-preview");
            });
            if (node.ownerDocument?.activeElement === node)
                enterFocus(source);
            if (pointerEvents) {
                const enter = () => enterPointer(source);
                const leave = () => leavePointer(source);
                node.addEventListener("mouseenter", enter);
                node.addEventListener("mouseleave", leave);
                cleanup.push(() => {
                    node.removeEventListener("mouseenter", enter);
                    node.removeEventListener("mouseleave", leave);
                });
            }
        }
        function updateViewport() {
            let inside = 0;
            const size = map?.getSize() ?? null;
            for (const candidate of candidates) {
                if (map === null || size === null) {
                    candidate.hint.textContent = "";
                    candidate.hint.hidden = true;
                    continue;
                }
                if (candidate.marker === null) {
                    candidate.hint.textContent = candidate.locationStatus === "polar"
                        ? "超出主地图投影范围，请查看极区定位"
                        : candidate.locationStatus === "unknown" ? "当前资料无可用代表点" : "无可用代表点";
                    candidate.hint.hidden = false;
                    continue;
                }
                const location = candidate.marker.getLatLng();
                if (typeof map.getCenter === "function" && typeof candidate.marker.setLatLng === "function") {
                    const longitude = wrapLongitude(location.lng, map.getCenter().lng);
                    if (location.lng !== longitude)
                        candidate.marker.setLatLng([location.lat, longitude]);
                }
                const coordinate = map.latLngToContainerPoint(candidate.marker.getLatLng());
                const inView = containsPoint(coordinate, size);
                if (inView)
                    inside += 1;
                candidate.hint.textContent = inView ? "" : "当前地图范围外";
                candidate.hint.hidden = inView;
            }
            countLabel.hidden = map === null;
            countLabel.textContent = map === null
                ? "" : `${scopeLabel} ${inside} / 本次返回 ${candidates.length}`;
        }
        function setCandidates(nextCandidates) {
            setPreview(null);
            for (const remove of cleanup)
                remove();
            cleanup = [];
            for (const candidate of candidates)
                for (const marker of markers(candidate))
                    marker.closeTooltip();
            pointerSource = null;
            focusSource = null;
            candidates = [...nextCandidates];
            for (const candidate of candidates) {
                const cardSource = { candidate, origin: "card" };
                bindDom(cardSource, candidate.card, true);
                for (const marker of markers(candidate)) {
                    const markerSource = { candidate, origin: "marker" };
                    const enter = () => enterPointer(markerSource);
                    const leave = () => leavePointer(markerSource);
                    const suppressPointerTooltip = () => {
                        if (focusSource !== null && focusSource.candidate !== candidate)
                            marker.closeTooltip();
                    };
                    marker.on("mouseover", enter);
                    marker.on("mouseout", leave);
                    marker.on("tooltipopen", suppressPointerTooltip);
                    cleanup.push(() => {
                        marker.off("mouseover", enter);
                        marker.off("mouseout", leave);
                        marker.off("tooltipopen", suppressPointerTooltip);
                    });
                    const markerElement = marker.getElement();
                    if (markerElement)
                        bindDom(markerSource, markerElement, false);
                }
            }
            updateViewport();
        }
        map?.on("moveend", updateViewport);
        map?.on("zoomend", updateViewport);
        map?.on("resize", updateViewport);
        updateViewport();
        return { setCandidates };
    }
    return { create, containsPoint, wrapLongitude, wrapCoordinates, locationStatus };
})();
//# sourceMappingURL=map-view.js.map