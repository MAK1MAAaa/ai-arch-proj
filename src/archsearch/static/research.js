"use strict";
const ArchSearchResearch = (() => {
    "use strict";
    function descriptionLabel(site, language) {
        if (language === "zh") {
            if (site.source_refs?.some((source) => source.id === `translation:wikidata:${site.id.slice(3)}`))
                return "中文译文（据 Wikidata 英文）";
            return site.source_kind === "supplement" ? "中文摘要（依据所列来源）" : "中文来源描述";
        }
        if (site.source_kind === "supplement") {
            if (site.id.startsWith("wd:"))
                return "Wikidata 来源描述";
            if (site.id.startsWith("auth:sg-nhb:"))
                return "来源英文原文（NHB资料集）";
            return "英文描述（出处见来源）";
        }
        return "来源描述原文";
    }
    function normalizeCamera(value, maximum) {
        if (value === null)
            return null;
        if (!Array.isArray(value.center) || value.center.length !== 2 || !value.center.every(Number.isFinite)
            || Math.abs(value.center[0]) > 180 || Math.abs(value.center[1]) > 85.0511287798
            || !Number.isFinite(value.zoom) || value.zoom < 1 || value.zoom > maximum)
            throw new Error("对照地图视野坐标或缩放无效。");
        return { center: [...value.center], zoom: value.zoom };
    }
    function parseComparison(url) {
        const empty = { modern_basemap: "osm", sync_centers: false, modern_view: null, history_view: null };
        try {
            for (const name of ["maps", "modern_base", "sync_centers", "modern_view", "history_view"]) {
                if (url.searchParams.getAll(name).length > 1)
                    throw new Error(`链接中的 ${name} 参数不能重复。`);
            }
            const layout = url.searchParams.get("maps");
            if (layout !== null && layout !== "compare")
                throw new Error("对照地图链接中的 maps 仅支持 compare。");
            const base = url.searchParams.get("modern_base") ?? "osm";
            const sync = url.searchParams.get("sync_centers") ?? "0";
            if (base !== "osm" && base !== "natural")
                throw new Error("现代地图底图参数无效。");
            if (sync !== "0" && sync !== "1")
                throw new Error("地图同步参数须为 0 或 1。");
            const read = (name, maximum) => {
                const raw = url.searchParams.get(name);
                if (raw === null)
                    return null;
                if (raw.length > 120)
                    throw new Error("地图视野参数过长。");
                const parts = raw.split(",");
                if (parts.length !== 3 || parts.some((part) => !/^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/u.test(part)))
                    throw new Error("地图视野须为经度、纬度、缩放三个数字。");
                return normalizeCamera({ center: [Number(parts[0]), Number(parts[1])], zoom: Number(parts[2]) }, maximum);
            };
            return { state: { modern_basemap: base, sync_centers: sync === "1", modern_view: read("modern_view", 18), history_view: read("history_view", 9) }, error: null };
        }
        catch (error) {
            return { state: empty, error: error instanceof Error ? error.message : "对照地图视图无法恢复。" };
        }
    }
    function normalizeComparison(value, map) {
        if (value === null)
            return null;
        if (!["side-by-side", "stacked"].includes(value.layout) || typeof value.sync_centers !== "boolean" || value.modern.role !== "modern-location"
            || !["osm", "natural", "loading", "unavailable"].includes(value.modern.basemap)
            || value.historical.role !== "historical-polities" || (value.historical.basemap !== null && value.historical.basemap !== "natural")
            || value.historical.year !== (map?.year ?? null) || value.historical.boundaries !== (map?.boundaries ?? false)
            || value.historical.frame_id !== (map?.frame_id ?? null) || value.historical.source_version !== (map?.source_version ?? null)
            || value.historical.basemap !== (map ? "natural" : null))
            throw new Error("对照地图快照与实际成功历史视图不一致。");
        return { layout: value.layout, sync_centers: value.sync_centers,
            modern: { role: "modern-location", basemap: value.modern.basemap, view: normalizeCamera(value.modern.view, 18) },
            historical: { role: "historical-polities", basemap: value.historical.basemap, view: normalizeCamera(value.historical.view, 9),
                year: value.historical.year, boundaries: value.historical.boundaries, frame_id: value.historical.frame_id, source_version: value.historical.source_version } };
    }
    const minasSourceFields = ["processo_ano", "denominacao", "denominacao_completa", "categoria", "classe_subclasse", "municipio", "distrito", "ato_legal", "livro_de_tombo"];
    function compactSourceJson(value) {
        let compact = "", quoted = false, escaped = false;
        for (const character of value) {
            if (quoted) {
                compact += character;
                if (escaped)
                    escaped = false;
                else if (character === "\\")
                    escaped = true;
                else if (character === '"')
                    quoted = false;
            }
            else if (character === '"') {
                quoted = true;
                compact += character;
            }
            else if (!/[\t\n\r ]/u.test(character))
                compact += character;
        }
        return compact;
    }
    function parseMinasSource(site) {
        const prefix = "Original source fields (Portuguese):\n";
        if (typeof site.id !== "string" || !/^auth:br-iepha-mg:scope-[a-f0-9]{64}$/u.test(site.id)
            || typeof site.details !== "string" || !site.details.startsWith(prefix))
            return null;
        try {
            const original = site.details.slice(prefix.length);
            const rows = JSON.parse(original);
            if (!Array.isArray(rows) || rows.length < 1 || rows.length > 153)
                return null;
            let previousIndex = 0;
            for (const row of rows) {
                if (row === null || typeof row !== "object" || Array.isArray(row))
                    return null;
                const record = row;
                if (Object.keys(record).length !== minasSourceFields.length + 1
                    || !Number.isSafeInteger(record.record_index) || record.record_index <= previousIndex
                    || record.record_index > 153
                    || !minasSourceFields.every((field) => typeof record[field] === "string"))
                    return null;
                previousIndex = record.record_index;
            }
            // Only source serialization is structured; duplicate keys or alternate encodings retain the original fallback.
            if (compactSourceJson(original) !== JSON.stringify(rows))
                return null;
            return rows;
        }
        catch {
            return null;
        }
    }
    const merimeeSourceFields = [
        "Reference",
        "Destination_actuelle_de_l_edifice",
        "Adresse_forme_index",
        "Etablissement_affectataire_de_l_edifice",
        "Autre_appellation_de_l_edifice",
        "Nature_de_la_protection",
        "Auteur_de_l_edifice",
        "Cadastre",
        "Commune_forme_index",
        "Copyright",
        "Type_de_couverture",
        "Datation_de_l_edifice",
        "Denomination_de_l_edifice",
        "Lieu_de_conservation_d_un_element_architectural_deplace",
        "Description_de_l_edifice",
        "Dimensions_normalisees_des_edicules_uniquement",
        "Date_de_Label",
        "Date_de_la_derniere_mise_a_jour",
        "Date_de_creation_de_la_notice",
        "Domaine",
        "Typologie_du_dossier",
        "Date_et_typologie_de_la_protection",
        "Departement_format_numerique",
        "Departement_en_lettres",
        "Partie_d_elevation_exterieure",
        "Source_de_l_energie_utilisee_par_l_edifice",
        "Emplacement__forme_et_structure_de_l_escalier",
        "Description_de_l_elevation_interieure",
        "etat_de_conservation",
        "Cadre_de_l_etude",
        "Genre_du_destinataire",
        "Historique",
        "Nom_du_cours_d_eau_traversant_ou_bordant_l_edifice",
        "Identifiant_Agregee",
        "COG_Insee_lors_de_la_protection",
        "Justification_attribution",
        "Justification_de_la_datation",
        "Liens_externes",
        "Lieudit",
        "Lien_vers_la_base_Archiv_MH",
        "Materiaux_du_gros_oeuvre",
        "Nom_du_redacteur",
        "Observations",
        "Precision_affectataire",
        "Partie_constituante_non_etudiee",
        "Partie_constituante",
        "Precision_sur_la_denomination",
        "Personnes_liees_a_l_edifice",
        "Typologie_de_plan",
        "Precision_de_la_localisation",
        "Precision_de_la_protection",
        "Description_de_l_iconographie",
        "Typologie_de_la_protection",
        "Precision_sur_le_statut_de_l_edifice",
        "Reference_a_un_ensemble",
        "Lien_vers_la_base_Joconde",
        "Lien_vers_la_base_Palissy",
        "References_des_parties_constituantes_etudiees",
        "Region",
        "Elements_remarquables_dans_l_edifice",
        "Remploi",
        "Renvoi_vers_une_notice_de_la_base_Merimee_ou_Palissy",
        "Indexation_iconographique_normalisee",
        "Siecle_de_campagne_secondaire_de_construction",
        "Siecle_de_la_campagne_principale_de_construction",
        "Format_abrege_du_siecle_de_construction",
        "Typologie_de_la_zone_de_protection",
        "Statut_juridique_de_l_edifice",
        "Technique_du_decor_porte_de_l_edifice",
        "Titre_editorial_de_la_notice",
        "Materiaux_de_la_couverture",
        "Couverts_ou_decouverts_du_jardin_de_l_edifice",
        "Vocable___pour_les_edifices_cultuels",
        "Typologie_du_couvrement",
        "Adresse_forme_editoriale",
        "Commune_forme_editoriale",
        "coordonnees_au_format_WGS84",
        "Producteur",
    ];
    function parseMerimeeSource(site) {
        const prefix = "Original source fields (French):\n";
        if (typeof site.id !== "string" || typeof site.details !== "string" || !site.details.startsWith(prefix))
            return null;
        const identity = /^auth:fr-merimee:(PA[0-9]{8})$/u.exec(site.id);
        if (!identity)
            return null;
        try {
            const original = site.details.slice(prefix.length);
            const parsed = JSON.parse(original);
            if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed))
                return null;
            const value = parsed;
            if (Object.keys(value).length !== 4 || value.schema_version !== 1 || value.reference !== identity[1])
                return null;
            const record = value.source_record, scope = value.scope;
            if (record === null || typeof record !== "object" || Array.isArray(record)
                || scope === null || typeof scope !== "object" || Array.isArray(scope))
                return null;
            const fields = record, range = scope;
            if (Object.keys(fields).length !== merimeeSourceFields.length || fields.Reference !== value.reference
                || !merimeeSourceFields.every((field) => typeof fields[field] === "string"))
                return null;
            if (Object.keys(range).length !== 3
                || typeof range.kind !== "string"
                || !["whole_notice_scope", "specified_parts", "composite_protected_scope"].includes(range.kind)
                || typeof range.source_field !== "string"
                || !merimeeSourceFields.some((field) => field === range.source_field)
                || typeof range.literal !== "string" || fields[range.source_field] !== range.literal)
                return null;
            // Ambiguous JSON preserves the complete original text instead of selecting one duplicate value.
            if (compactSourceJson(original) !== JSON.stringify(parsed))
                return null;
            return parsed;
        }
        catch {
            return null;
        }
    }
    function normalizeBBox(value) {
        if (value === null || value === undefined)
            return null;
        if (!Array.isArray(value) || value.length !== 4 || !value.every((item) => typeof item === "number" && Number.isFinite(item)))
            throw new Error("地图范围须为四个有限数字。");
        const [west, south, east, north] = value;
        if (west < -180 || west > 180 || east < -180 || east > 180 || south < -90 || north > 90
            || south >= north || west === east || (west === 180 && east === -180))
            throw new Error("地图范围经纬度越界或范围宽度／高度为零。");
        return [west, south, east, north];
    }
    function parseBBox(value) {
        if (value === null)
            return null;
        if (value.length < 1 || value.length > 200)
            throw new Error("地图范围参数长度应为1至200个字符。");
        const parts = value.split(",").map((part) => part.trim());
        if (parts.length !== 4 || parts.some((part) => !/^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/u.test(part)))
            throw new Error("地图范围应为西、南、东、北四个十进制数字。");
        return normalizeBBox(parts.map(Number));
    }
    const regions = ["africa", "arab-states", "asia-pacific", "europe-north-america", "latin-america-caribbean", "antarctica", "nps-pacific"];
    function normalizeSubdivision(country, value) {
        if (value === null || value === undefined || value === "")
            return null;
        if (typeof value !== "string" || !/^[A-Z]{2}:[a-z0-9][a-z0-9-]{0,63}$/u.test(value)
            || !country || !value.startsWith(`${country}:`))
            throw new Error("来源省区须使用所选国家／地区对应的项目标识。");
        return value;
    }
    function subdivisionVersion(value) {
        return typeof value === "string" && value.trim().length > 0 && value.length <= 128;
    }
    function validateSubdivisionResponse(request, response, expectedVersion) {
        const subdivision = normalizeSubdivision(request.country, request.subdivision);
        if (!subdivision)
            return null;
        if (response.subdivision !== subdivision || !subdivisionVersion(response.subdivision_version)
            || (expectedVersion !== undefined && response.subdivision_version !== expectedVersion))
            throw new Error("来源省区响应的条件或资料版本不一致，未替换成功视图。");
        return response.subdivision_version;
    }
    function geography(country, region) {
        const normalizedCountry = country || null;
        const normalizedRegion = region || null;
        if (normalizedCountry !== null && !/^[A-Z]{2}$/u.test(normalizedCountry))
            throw new Error("国家／地区代码应为来源中的两位大写ISO代码。");
        if (normalizedRegion !== null && !regions.includes(normalizedRegion))
            throw new Error("来源分区参数无效。");
        return { country: normalizedCountry, region: normalizedRegion };
    }
    function parseBrowse(url) {
        const empty = { country: null, region: null, offset: 0, visible: true, bbox: null };
        try {
            for (const name of ["browse_country", "browse_region", "browse_subdivision", "browse_offset", "points", "browse_bbox"]) {
                if (url.searchParams.getAll(name).length > 1)
                    throw new Error(`链接中的 ${name} 参数不能重复。`);
            }
            const scope = geography(url.searchParams.get("browse_country"), url.searchParams.get("browse_region"));
            const subdivision = normalizeSubdivision(scope.country, url.searchParams.get("browse_subdivision"));
            const rawOffset = url.searchParams.get("browse_offset") ?? "0";
            const points = url.searchParams.get("points") ?? "1";
            if (!/^(?:0|[1-9]\d{0,6})$/u.test(rawOffset) || Number(rawOffset) > 1_000_000)
                throw new Error("目录页码无效。");
            if (points !== "0" && points !== "1")
                throw new Error("全库点图层参数无效。");
            return { state: { ...scope, ...(subdivision ? { subdivision } : {}), offset: Number(rawOffset), visible: points === "1", bbox: parseBBox(url.searchParams.get("browse_bbox")) }, error: null };
        }
        catch (error) {
            return { state: empty, error: error instanceof Error ? error.message : "目录链接无效。" };
        }
    }
    function validYear(year) {
        return Number.isInteger(year) && year !== 0;
    }
    function automaticPhaseYear(phase) {
        return phase.precision === "exact_year" && phase.start_year !== null
            && validYear(phase.start_year) && phase.start_year === phase.end_year ? phase.start_year : null;
    }
    function parseView(url) {
        const empty = { site: null, phase: null };
        const parameters = url.searchParams;
        const names = ["year", "basemap", "boundaries", "site", "phase"];
        try {
            for (const name of names) {
                if (parameters.getAll(name).length > 1)
                    throw new Error(`链接中的 ${name} 参数不能重复。`);
            }
            const rawYear = parameters.get("year");
            const basemap = parameters.get("basemap") ?? "historical";
            const boundaries = parameters.get("boundaries") ?? "1";
            if (basemap !== "historical" && basemap !== "modern")
                throw new Error("链接中的 basemap 无效。");
            if (boundaries !== "0" && boundaries !== "1")
                throw new Error("链接中的 boundaries 无效。");
            if (rawYear !== null && (!/^-?[1-9]\d*$/u.test(rawYear) || !validYear(Number(rawYear))
                || Number(rawYear) < -3400 || Number(rawYear) > 2024))
                throw new Error("链接年份应为公元前3400至公元2024年，不能为0。");
            const site = parameters.get("site");
            const phase = parameters.get("phase");
            if (site !== null && !/^(?:[1-9]\d*|wd:Q[1-9]\d*|whc:[1-9]\d*|ats:hsm:[1-9]\d*|auth:[a-z][a-z0-9-]{0,39}:[A-Za-z0-9][A-Za-z0-9._-]{0,79})$/u.test(site))
                throw new Error("链接中的 site 无效。");
            if (phase !== null && (!site || !phase || phase.length > 160 || /[\u0000-\u001f\u007f]/u.test(phase)))
                throw new Error("链接中的 phase 无效或缺少 site。");
            const hasView = ["year", "basemap", "boundaries"].some((name) => parameters.has(name));
            return { view: hasView ? { year: rawYear === null ? 117 : Number(rawYear), basemap, boundaries: boundaries === "1", frame_id: null, source_version: null } : null, selection: { site, phase }, error: null };
        }
        catch (error) {
            return { view: null, selection: empty, error: error instanceof Error ? error.message : "地图链接无效。" };
        }
    }
    function validateEnhancement(request, value) {
        if (request.enhance !== true) {
            if (value !== null && value !== undefined)
                throw new Error("基础检索响应不能冒充已请求的 LLM 增强。");
            return null;
        }
        if (!value || typeof value !== "object" || Array.isArray(value))
            throw new Error("LLM 增强响应缺少实际模型与查询快照。");
        const item = value;
        if (item.requested !== true || typeof item.applied !== "boolean"
            || (item.provider !== "ollama" && item.provider !== "openai")
            || typeof item.model !== "string" || !item.model || item.model.length > 512 || /[\u0000-\u001f\u007f]/u.test(item.model)
            || !Array.isArray(item.queries) || item.queries.length < 1 || item.queries.length > 3
            || !item.queries.every((query) => typeof query === "string" && query.trim() && Array.from(query).length <= 500)
            || item.queries[0] !== request.query || new Set(item.queries).size !== item.queries.length
            || typeof item.elapsed_ms !== "number" || !Number.isFinite(item.elapsed_ms) || item.elapsed_ms < 0
            || (item.applied && (item.ranking_method !== "rrf" || item.queries.length < 2 || item.reason !== null))
            || (!item.applied && (item.ranking_method !== "original" || item.queries.length !== 1
                || typeof item.reason !== "string" || !item.reason || item.reason.length > 1000)))
            throw new Error("LLM 增强响应与本次实际检索不一致，保留原成功结果。");
        return { requested: true, applied: item.applied, provider: item.provider, model: item.model,
            queries: [...item.queries], elapsed_ms: item.elapsed_ms,
            ranking_method: item.applied ? "rrf" : "original", reason: item.reason };
    }
    const parameterNames = ["q", "mode", "type", "limit", "country", "region", "subdivision", "enhance"];
    function normalizeRequest(request) {
        const query = request.query.trim();
        if (!query || Array.from(query).length > 500) {
            throw new Error("链接中的 q 必须包含 1 至 500 个字符。");
        }
        if (request.mode !== "semantic" && request.mode !== "bm25") {
            throw new Error("链接中的 mode 仅支持 semantic 或 bm25。");
        }
        if (request.limit !== 10 && request.limit !== 20 && request.limit !== 50) {
            throw new Error("链接中的 limit 仅支持 10、20 或 50。");
        }
        const type = request.type === "" ? null : request.type;
        if (type !== null && (Array.from(type).length > 128 || /[\u0000-\u001f\u007f-\u009f]/u.test(type))) {
            throw new Error("链接中的 type 必须是不超过 128 个字符且不含控制字符的类型 ID。");
        }
        const scope = geography(request.country, request.region);
        const subdivision = normalizeSubdivision(scope.country, request.subdivision);
        if (request.enhance !== undefined && typeof request.enhance !== "boolean")
            throw new Error("LLM 增强参数必须是布尔值。");
        return { query, mode: request.mode, type, limit: request.limit,
            ...(scope.country ? { country: scope.country } : {}), ...(scope.region ? { region: scope.region } : {}), ...(subdivision ? { subdivision } : {}),
            ...(request.enhance === true ? { enhance: true } : {}) };
    }
    function parseLink(url) {
        const parameters = url.searchParams;
        if (!parameterNames.some((name) => parameters.has(name)))
            return { request: null, error: null };
        for (const name of parameterNames) {
            if (parameters.getAll(name).length > 1) {
                return { request: null, error: `链接中的 ${name} 参数不能重复。` };
            }
        }
        for (const name of ["country", "region", "subdivision"]) {
            if (parameters.has(name) && parameters.get(name) === "")
                return { request: null, error: `链接中的 ${name} 不能是空筛选值。` };
        }
        const mode = parameters.get("mode") ?? "semantic";
        if (parameters.has("enhance") && parameters.get("enhance") !== "1")
            return { request: null, error: "链接中的 enhance 仅支持 1，关闭增强时请省略此参数。" };
        if (mode !== "semantic" && mode !== "bm25") {
            return { request: null, error: "链接中的 mode 仅支持 semantic 或 bm25。" };
        }
        const limit = parameters.get("limit") ?? "10";
        if (limit !== "10" && limit !== "20" && limit !== "50") {
            return { request: null, error: "链接中的 limit 仅支持 10、20 或 50。" };
        }
        try {
            const request = normalizeRequest({
                query: parameters.get("q") ?? "",
                mode,
                type: parameters.get("type"),
                limit: Number(limit),
                country: parameters.get("country"), region: parameters.get("region"),
                subdivision: parameters.get("subdivision"),
                ...(parameters.get("enhance") === "1" ? { enhance: true } : {}),
            });
            return { request, error: null };
        }
        catch (error) {
            return { request: null, error: error instanceof Error ? error.message : "检索链接参数无效。" };
        }
    }
    function buildLink(base, request, view = null, selection = { site: null, phase: null }, browse = null, comparison = null) {
        const normalized = request ? normalizeRequest(request) : null;
        if (base.protocol !== "http:" && base.protocol !== "https:") {
            throw new Error("检索链接仅支持 HTTP 或 HTTPS 页面。");
        }
        const url = new URL(base.origin);
        url.pathname = base.pathname;
        if (normalized) {
            url.searchParams.set("q", normalized.query);
            url.searchParams.set("mode", normalized.mode);
            url.searchParams.set("type", normalized.type ?? "");
            url.searchParams.set("limit", String(normalized.limit));
            if (normalized.country)
                url.searchParams.set("country", normalized.country);
            if (normalized.region)
                url.searchParams.set("region", normalized.region);
            if (normalized.subdivision)
                url.searchParams.set("subdivision", normalized.subdivision);
            if (normalized.enhance)
                url.searchParams.set("enhance", "1");
        }
        if (view) {
            if (!validYear(view.year) || view.year < -3400 || view.year > 2024)
                throw new Error("地图年份无效。");
            url.searchParams.set("year", String(view.year));
            url.searchParams.set("basemap", view.basemap);
            url.searchParams.set("boundaries", view.boundaries ? "1" : "0");
        }
        if (selection.site)
            url.searchParams.set("site", selection.site);
        if (selection.site && selection.phase)
            url.searchParams.set("phase", selection.phase);
        if (browse) {
            const scope = geography(browse.country, browse.region);
            const subdivision = normalizeSubdivision(scope.country, browse.subdivision);
            const bbox = normalizeBBox(browse.bbox);
            if (!Number.isInteger(browse.offset) || browse.offset < 0 || browse.offset > 1_000_000)
                throw new Error("目录页码无效。");
            url.searchParams.set("browse_country", scope.country ?? "");
            url.searchParams.set("browse_region", scope.region ?? "");
            if (subdivision)
                url.searchParams.set("browse_subdivision", subdivision);
            if (browse.offset)
                url.searchParams.set("browse_offset", String(browse.offset));
            if (!browse.visible)
                url.searchParams.set("points", "0");
            if (bbox !== null)
                url.searchParams.set("browse_bbox", bbox.join(","));
        }
        if (comparison) {
            if (!["osm", "natural"].includes(comparison.modern_basemap) || typeof comparison.sync_centers !== "boolean")
                throw new Error("对照地图设置无效。");
            url.searchParams.set("maps", "compare");
            url.searchParams.set("modern_base", comparison.modern_basemap);
            url.searchParams.set("sync_centers", comparison.sync_centers ? "1" : "0");
            const modern = normalizeCamera(comparison.modern_view, 18), historical = normalizeCamera(comparison.history_view, 9);
            if (modern)
                url.searchParams.set("modern_view", [...modern.center, modern.zoom].join(","));
            if (historical)
                url.searchParams.set("history_view", [...historical.center, historical.zoom].join(","));
        }
        return url.href;
    }
    function createExport(request, response, exportedAt, map = null, selection = { site: null, phase: null }, selectedSite = null, browse = null, spatial = null, registeredAreas = null, currentCorpusVersion = response.corpus_version, currentRegisteredAreasVersion = registeredAreas?.version ?? null, comparison = null) {
        const normalized = normalizeRequest(request);
        if (normalized.query !== response.query || normalized.mode !== response.mode) {
            throw new Error("导出请求必须与成功响应的查询和检索方式一致。");
        }
        validateSubdivisionResponse(normalized, response);
        const enhancement = validateEnhancement(normalized, response.enhancement);
        if (browse?.subdivision && !subdivisionVersion(browse.subdivision_version))
            throw new Error("尚未成功应用的来源省区不能加入目录导出。");
        if (browse)
            normalizeSubdivision(browse.country, browse.subdivision);
        const selectedMatches = selectedSite !== null && typeof selectedSite === "object" && "id" in selectedSite && selectedSite.id === selection.site;
        const areas = registeredAreas?.displayed === true && selectedMatches && selection.site === registeredAreas.site_id
            && registeredAreas.corpus_version === response.corpus_version && registeredAreas.corpus_version === currentCorpusVersion && registeredAreas.version === currentRegisteredAreasVersion
            ? { ...ArchSearchRegisteredAreas.parseAreas(registeredAreas, registeredAreas.site_id, currentCorpusVersion, currentRegisteredAreasVersion), displayed: true } : null;
        if (areas && (!areas.ready || areas.features.length === 0))
            throw new Error("未实际显示的登记范围不能加入导出。");
        return {
            schema_version: 2,
            exported_at: exportedAt,
            request: normalized,
            response: enhancement ? { ...response, enhancement } : response,
            map: map ? { ...map } : null,
            ...(comparison ? { comparison: normalizeComparison(comparison, map) } : {}),
            selection: { ...selection },
            selected_site: selectedSite,
            spatial: spatial === null ? null : JSON.parse(JSON.stringify(spatial)),
            registered_areas: areas,
            browse: browse ? { ...browse, bbox: normalizeBBox(browse.bbox) } : null,
            sources: [
                { name: "Pleiades", version: "v4.1", license: "CC BY 3.0", uri: "https://pleiades.stoa.org/" },
                { name: "UNESCO World Heritage descriptions", license: "CC BY-SA 3.0 IGO", uri: "https://whc.unesco.org/en/disclaimer/", note: "Individual record references retain attribution and revisions; other linked documents retain their own rights." },
                { name: "UNESCO DataHub World Heritage List", license: "CC BY-SA 4.0", uri: "https://data.unesco.org/explore/dataset/whc001/", note: "Frozen cultural and mixed catalogue, HTML-to-text processing; individual records retain snapshot hashes and attribution. No images redistributed." },
                { name: "Antarctic Treaty Secretariat — Historic Sites and Monuments", license: "CC BY 4.0", uri: "https://www.ats.aq/devph/en/apa-database", note: "Frozen active HSM records. Unknown true locations remain null; polar coordinates retain their original values. Proposing parties do not establish sovereignty." },
                { name: "Wikidata", license: "CC0", uri: "https://www.wikidata.org/wiki/Wikidata:Licensing" },
                { name: "Country cultural supplement", version: "country-supplement-v1", license: "Mixed rights — see individual source_refs", uri: "https://github.com/MAK1MAAaa/ai-arch-proj/blob/main/src/archsearch/data/SUPPLEMENT-LICENSE.md", note: "Wikidata structured fields CC0; authority excerpts retain individual rights. Proposed heritage is not relabelled as protected or inscribed. Three records lack verified public digital coordinates. No new historical phases inferred." },
                { name: "Regional cultural supplement", version: "regional-supplement-v1", license: "Mixed rights — see individual source_refs", uri: "https://github.com/MAK1MAAaa/ai-arch-proj/blob/main/src/archsearch/data/REGIONAL-LICENSE.md", note: "Source-reviewed cultural places in sparse northern, island and interior regions. Original site coordinates are separate from museum display locations. Source qualification and country association do not establish historical dates or sovereignty. No new historical phases inferred." },
                { name: "South America cultural supplement", version: "southamerica-supplement-v1", license: "Mixed rights — see individual source_refs", uri: "https://github.com/MAK1MAAaa/ai-arch-proj/blob/main/src/archsearch/data/SOUTHAMERICA-LICENSE.md", note: "Source-reviewed cultural places in six South American countries. Public representative coordinates retain source limits; absent or conflicting coordinates remain null. Wikidata English short descriptions and separately attributed Chinese translations are CC0. Identity review does not establish historical stages or a complete regional inventory." },
                { name: "Africa cultural supplement", version: "africa-supplement-v1", license: "Mixed rights — see individual source_refs", uri: "https://github.com/MAK1MAAaa/ai-arch-proj/blob/main/src/archsearch/data/AFRICA-LICENSE.md", note: "Five source-reviewed cultural identities from State Party tentative submissions, not World Heritage inscriptions or a complete African inventory. Wikidata metadata is CC0; authority excerpts retain individual rights. Unadopted representative coordinates remain null; no new historical phases are inferred." },
                { name: "Pacific and interior cultural supplement", version: "pacific-interior-supplement-v1", license: "Mixed rights — see individual source_refs", uri: "https://github.com/MAK1MAAaa/ai-arch-proj/blob/main/src/archsearch/data/PACIFIC-LICENSE.md", note: "Seven independently source-reviewed cultural identities from Pacific registers and African archaeological research. An address-restricted place remains unmapped; unadopted or conflicting representative coordinates remain null. Tentative submissions are not World Heritage inscriptions. No listing, excavation or publication year becomes a historical phase." },
                { name: "NPS Pacific register supplement", version: "nps-pacific-v1", license: "NPS government structured metadata; other source rights retained", uri: "https://www.nps.gov/aboutus/disclaimer.htm", note: "Project grouping of seven source State labels, not a UNESCO region or sovereignty classification. Government metadata does not relicense third-party nomination text, photos or attachments. Viewer text, feature edits and newer downloads have separate version clocks. Source points may be generated reference positions; restricted locations remain unmapped. No registration or publication date becomes a site phase." },
                { name: "Canadian Federal Heritage Designations historic-place supplement", version: "canada-dfhd-v1", license: "Open Government Licence - Canada; Wikidata structured claims CC0", license_uri: "https://open.canada.ca/en/open-government-licence-canada", uri: "https://open.canada.ca/data/en/dataset/49d5ba7d-d860-40d9-9183-892979e4acbe", note: "Parks Canada / Government of Canada. Contains information licensed under the Open Government Licence – Canada. Released NHS identities, original narrative and province fields retain their source version. Adopted public reference points retain separate source statements and roles; no generated centroids or ancient footprints. Commemorative-reason or plaque review notices are separate from project identity approval and chronology. Other webpages and third-party materials retain their own rights." },
                { name: "Source-associated province, district, municipality and commune memberships", version: "source-subdivisions-v7", license: "Mixed rights — DFHD fields OGL-Canada; CSDI custom terms; Iepha-MG fields CC BY 4.0; Mérimée fields Open Licence 2.0; other webpages retain individual rights", uri: "https://github.com/MAK1MAAaa/ai-arch-proj/blob/main/src/archsearch/data/SUBDIVISIONS-LICENSE.md", note: "Only the986 DFHD objects' province fields use Open Government Licence – Canada. CRHP and Parks Canada short location facts retain webpage rights. Canadian whole-object provinces and aliases are unchanged. Hong Kong districts associate source features with an explicitly reviewed whole and do not assert that every shape belongs to that district. CSDI Terms apply to those original fields, not all AMO contents. Earlier versions retain all original source memberships, including Iepha-MG original-record municipio and the first Mérimée Commune_forme_editoriale values in GP, BL, MF, MQ and RE, and appends GF, YT and PM original Commune_forme_editoriale values; version7 binds global-v19 and the additional named cultural record without assigning it an inferred source province. All202 existing definitions and1836 memberships remain unchanged. The first five-area Mérimée cohort and the GF/YT/PM extension keep separate source pins. Literal spelling variants are not merged by COG, and one component notice adds no membership. Compound locality values stay intact; record-to-composite associations do not assert whole-object jurisdiction. Project label IDs are not statutory administrative IDs. Each request/response and browse retains its actual successful version. No coordinate geocoding, inferred parent membership, borders or historical phases." },
                { name: "Iepha-MG protected cultural registration scopes", version: "minas-tombados-v1", license: "CC BY 4.0", license_uri: "https://creativecommons.org/licenses/by/4.0/", uri: "https://dados.mg.gov.br/dataset/bens-tombados", accessed: "2026-11-05", note: "Instituto Estadual do Patrimônio Histórico e Artístico de Minas Gerais, via dados.mg.gov.br; fixed original Portuguese registration fields, grouped by exact process and complete designation after independent source review. Project scope IDs are derived identities, not legal registration numbers. Original process, legal-act and book fields are retained without interpreting them as construction or use dates. The source has no coordinates; representative points and precision remain null. Original municipality values support record-associated browsing without geocoding or asserting a complete regional inventory. Linked documents and photographs are not redistributed." },
                { name: "Mérimée overseas protected-notice scopes", version: "merimee-overseas-v1", license: "Licence Ouverte / Open Licence version 2.0", license_uri: "https://www.data.gouv.fr/pages/legal/licences/etalab-2-0", uri: "https://www.data.gouv.fr/datasets/immeubles-proteges-au-titre-des-monuments-historiques-2", accessed: "2026-11-05", source_updated: "2026-10-29T02:16:04+00:00", processed: "2026-11-05", note: "Ministère de la Culture, Immeubles protégés au titre des Monuments Historiques, via data.gouv.fr; source updated on2026-10-29T02:16:04+00:00, accessed and processed on2026-11-05. Original French notice fields and protection-scope text retain source qualification: the catalogue includes formerly or currently protected records, without asserting current legal status. Partial protection is not expanded to a whole estate; notice references and record-associated Commune values are not statutory parcels or jurisdiction boundaries. The project uses reviewed published WGS84 points only as reference positions, without a whole-centre or precision claim; the provider did not state point-generation method or precision. Missing points stay null. Original protection dates do not create historical phases. Processing retains original fields and separately reviewed modern area associations; it does not translate names or fabricate historical facts. The dataset licence does not automatically cover linked photographs or third-party contents." },
                { name: "Mérimée GF/YT/PM notice extension", version: "merimee-extension-v1", license: "Licence Ouverte / Open Licence version 2.0", license_uri: "https://www.data.gouv.fr/pages/legal/licences/etalab-2-0", uri: "https://www.data.gouv.fr/datasets/immeubles-proteges-au-titre-des-monuments-historiques-2", accessed: "2026-11-05", source_updated: "2026-10-29T02:16:04+00:00", processed: "2026-11-05", note: "Ministère de la Culture, via data.gouv.fr. Fixed original GF/YT/PM notice fields extend the unchanged earlier corpus; 123 reviewed notices yield122 accepted source scopes, with the earlier Susky rock-shelter notice linked to the Mamilipann whole instead of adding a new site or inherited point. Published WGS84 references retain unknown generation method and precision. Current INSEE and UN M49 associations support browsing, not sovereignty, jurisdiction boundaries or historical political ownership; PM belongs to Northern America. Original commune spellings stay distinct source options. Former or revised protection is not asserted current, and legal dates are not historical phases. No names are translated or aliases generated. Open Licence2.0 applies to this dataset information, not automatically to linked photographs or third-party materials." },
                { name: "Australian National Heritage List public spatial database", version: "australia-nhl-v1", license: "CC BY 3.0 Australia", license_uri: "https://creativecommons.org/licenses/by/3.0/au/", uri: "https://gis.environment.gov.au/gispubmap/rest/services/ogc_services/National_Heritage_List/FeatureServer/0", note: "Public factual register fields and provider registered ranges only. Modern heritage registration is not an ancient footprint, political boundary, access permission or a representative point. Individual feature source URIs, versions, hashes and licences remain with registered_areas; linked third-party materials retain their own rights." },
                { name: "Hong Kong monument source facts and CSDI polygons", version: "hong-kong-monuments-v1", license: "CSDI Portal Terms and Conditions of Use; separate AMO short-fact and linked-content rights", uri: "https://portal.csdi.gov.hk/csdi-webpage/doc/TNC", note: "Data from the Government of the Hong Kong Special Administrative Region, CSDI Portal and Antiquities and Monuments Office; their intellectual property rights are acknowledged. Original January2026 CSDI attributes/polygons and later October2026 official whole-object facts retain separate source dates. Source polygons are not asserted legal or ancient boundaries and never create representative points. AMO introductions, photos and other third-party contents have no blanket CSDI licence." },
                { name: "Singapore NHB Monuments (GEOJSON)", version: "singapore-monuments-v1", license: "Singapore Open Data Licence version 1.0", license_uri: "https://data.gov.sg/open-data-licence", uri: "https://data.gov.sg/datasets/d_b29c230ec6b609e29ed42f71ca9a8767/view", accessed: "2026-11-05", note: "Contains information from Monuments (GEOJSON), National Heritage Board, accessed on2026-11-05 via data.gov.sg, made available under the Singapore Open Data Licence version1.0. Original licensed descriptions and provider Point coordinates retain their source fields and release clocks. The project uses the original provider Point as a reference position and makes no whole-centre or precision claim; the provider did not state the point-generation method or precision. It is not an excavation or legal-boundary assertion. Feature updates and protection dates are not historical phases. The licence does not automatically cover linked webpages, images or third-party rights." },
                { name: "UNESCO Hague cultural properties", version: "protection-supplement-v1", license: "CC BY-SA 4.0", uri: "https://data.unesco.org/explore/dataset/chp001/", note: "Reviewed cultural places from a fixed protection register; source rows and component locations are not new-site counts. Source protection years do not establish historical phases. Unresolved or storage-only locations remain in the source audit and are not mapped as archaeological places." },
                { name: "Cliopatria", version: map?.source_version ?? null, license: "CC BY 4.0", uri: "https://github.com/Seshat-Global-History-Databank/cliopatria", note: "Historical polity approximations; valid source intervals, no interpolation or point-based political attribution." },
                { name: "Natural Earth", license: "Public domain", uri: "https://www.naturalearthdata.com/about/terms-of-use/", note: "Modern natural-geography reference; no ancient coastline reconstruction." },
                { name: "Source-verified named cultural places", version: "named-places-v1", license: "Mixed rights — Holy Trinity Church and Folger source facts/short excerpts retain individual rights; Wikidata structured church point CC0", uri: "https://github.com/MAK1MAAaa/ai-arch-proj/blob/main/src/archsearch/data/NAMED-PLACES-LICENSE.md", note: "Source identity and original-language evidence retained. The1616 event is Shakespeare's burial, not a construction date. Published church position is a reference point, not an exact grave coordinate. No linked photographs or images redistributed; source records retain separate attribution." },
                { name: "OpenStreetMap contributors", license: "ODbL", uri: "https://www.openstreetmap.org/copyright", displayed: comparison ? comparison.modern.basemap === "osm" : map?.basemap === "modern" },
            ],
            source: {
                name: "Pleiades: A Gazetteer of Past Places",
                version: "v4.1",
                uri: "https://pleiades.stoa.org/",
                release_uri: "https://github.com/isawnyu/pleiades.datasets/releases/tag/v4.1",
                commit: "b6a6790f71c45e4a4ef60fce296c506f28f458bf",
                license: "CC BY 3.0",
                license_uri: "https://creativecommons.org/licenses/by/3.0/",
                attribution: "Copyright The Contributors. Pleiades, Ancient World Mapping Center and Institute for the Study of the Ancient World.",
            },
            provenance: {
                processing: "来源资料经 HTML 转纯文本和空白规范化；别名、类型、分期证据、原文出处和贡献者随结果保留，未生成历史事实或补造坐标。",
                scope: "保留原有策展资料、固定文化／混合名录与南极历史资料，另有逐条核验的国家文化补充；资格来源可能是预备名录、国家文保或考古研究，不一概表示正式世界遗产。不是全世界所有遗址清单。response为成功检索快照，selected_site可为独立目录选择，没有虚构排名或分数。",
                coordinates: "repr_point 为 WGS84 [经度, 纬度] 代表点，用于地图定位；不等同于实测发掘坐标，location_precision 不承诺米级精度。",
                scores: "检索分数不是相关概率，不同检索方式的分数不可直接比较；本导出不包含人工相关性判断或评测指标。",
                enhancement: "enhancement保存成功响应实际使用的模型、查询改写、耗时与排序方法；RRF为多个查询排名融合，失败明确保留原查询与原因。查询改写不是来源证据，不生成遗址事实或历史阶段。API地址、密钥和服务内存revision不写入分享请求或导出。",
                periods: "分期来自名称或位置记录的来源关联；不等同于建造年代或连续使用证明，start/end 保留原始记录时间范围。",
                chronology: "历史阶段独立记录事件类型、精度、证据和代理核验方式；区间或时期不证明连续存在，未标成人工专家确认。",
                map: "map保存最后成功显示的年份与疆域版本；null表示尚无成功地图快照，待加载或失败年份不冒充已显示年份。",
                comparison: "comparison区分现代位置与历史政权两张地图，保存实际底图、视野及成功历史年/版本；历史图使用Cliopatria与现代自然地理参照，不是古海岸或街道复原。同步中心须用户明确打开，目录bbox始终只由现代图显式捕获；历史拖图不重筛资料，也不据代表点判定历史政治归属。",
                locations: "repr_point为null表示本记录无可用代表点：可能真实位置不明，也可能尚未取得可信公开数字坐标，来源说明保留区别；不等于零坐标。有效极区坐标超出Web Mercator时使用独立极区示意，不截断或伪造纬度。极区底图为现代自然地理参照，不生成历史国界。",
                source_points: "spatial保留最后成功目录的组合源点版本、source_groups对应的来源／版本／许可与地点身份，以及独立选中资料经审核纳入地图的定位序列、重复记录与来源标签。原代表点单独保存；多个定位记录不增加遗址条目数或承诺发掘精度。世界遗产原始序列保持不变；海牙名录排除的仓储、标签冲突等原记录仍保留在来源审计中，不混作考古原址点。",
                registered_areas: "registered_areas只保存当前实际显示、且与选中资料和当前语料/检索版本一致的来源范围；label区分现代遗产登记范围与来源古迹多边形，后者不承诺法定边界。null表示未显示或上下文不匹配。保留原WGS84闭环与来源版本/许可，不推内外环、代表点、古址轮廓、准入或点计数。范围显隐不写入分享链接，重新打开后仍须主动点击查看。",
                browse: "browse保存成功应用的独立目录条件；bbox为[西,南,东,北]闭区间，西大于东表示跨日期变更线，仅筛目录和全库点层，不改变request中的检索语义。spatial_match_mode及spatial_version记录当时的来源点匹配能力；representative-only可能遗漏无代表点落入框内的组成地点。选中资料纳入地图的来源序列完整导出；海牙名录未纳入地图的保护设施仍留在冻结来源审计中。",
                subdivisions: "加拿大采用整体省区原字段；香港采用有明确整体／要素关联的来源要素地区；巴西Iepha-MG采用原登记行municipio全文值；Mérimée采用原记录Commune_forme_editoriale全文值，多地值不自动拆分。来源要素／原记录关联不表示整体或全部组成部分都属于该地区，不由坐标、省界或历史政权推断。request/response与browse各保存其独立成功条件；subdivision_version为各自实际应用的来源索引版本，未成功的待选条件不冒充已显示范围。",
            },
        };
    }
    function createExampleIntent() {
        let sequence = 0;
        return {
            invalidate() { sequence++; },
            async run(prepare, isReady, submit, onError) {
                const request = ++sequence;
                try {
                    await prepare();
                    if (request !== sequence)
                        return;
                    if (!isReady())
                        throw new Error("目录条件尚未成功切换为全库，请重试。");
                    submit();
                }
                catch (error) {
                    if (request === sequence)
                        onError(error);
                }
            },
        };
    }
    return { parseLink, parseView, parseBrowse, parseComparison, buildLink, createExport, descriptionLabel, createExampleIntent, validYear, automaticPhaseYear, normalizeBBox, parseBBox, normalizeSubdivision, validateSubdivisionResponse, validateEnhancement, parseMinasSource, minasSourceFields, parseMerimeeSource, merimeeSourceFields };
})();
//# sourceMappingURL=research.js.map