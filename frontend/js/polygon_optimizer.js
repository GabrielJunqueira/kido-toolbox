/**
 * Event Polygon Optimizer - Main JavaScript
 * 5-step wizard: Setup → Input → Processing → Review → Export
 */

// ==========================================
// STATE
// ==========================================

const state = {
    currentStep: 1,
    totalSteps: 5,

    // Auth
    token: null,
    rootUrl: null,
    brand: null,
    countryCode: null,

    // Node file
    nodesLoaded: false,
    nodeRows: 0,

    // Input
    inputGeojson: null,     // GeoJSON Feature of the drawn/uploaded area
    bufferM: 500,

    // Job
    jobId: null,
    jobSteps: [],
    jobStartedAt: null,
    pollTimer: null,
    elapsedTimer: null,
    projectId: null,
    projectName: null,

    // Result
    result: null,
    selectedIds: null,      // Set of node ids currently selected
    currentGeometry: null,

    // Maps
    inputMap: null,
    inputDrawnItems: null,
    inputNodeLayer: null,
    inputBufferLayer: null,
    reviewMap: null,
};

// The ten job steps folded into the five groups shown in the sidebar.
const TODO_GROUPS = [
    { title: 'Collect', keys: ['collect_nodes'] },
    { title: 'Diagnostic project', keys: ['build_project_geojson', 'validate_project', 'price_project'] },
    { title: 'Platform', keys: ['create_project', 'wait_ready'] },
    { title: 'Data', keys: ['query_event_daily', 'query_event_hourly', 'query_baseline'] },
    { title: 'Analysis', keys: ['score'] },
];

const STEP_LABELS = {
    collect_nodes: 'Collect nearby nodes',
    build_project_geojson: 'Build diagnostic zones',
    validate_project: 'Validate zoning on platform',
    price_project: 'Check project price',
    create_project: 'Create project on platform',
    wait_ready: 'Wait for project to be ready',
    query_event_daily: 'Query event day totals',
    query_event_hourly: 'Query event day arrivals by hour',
    query_baseline: 'Query baseline day',
    score: 'Score nodes and build suggestion',
};

// Colours for the Decision layer, one per selection reason.
const REASON_COLORS = {
    seed_kept: '#10b981',
    seed_dropped: '#f59e0b',
    added_excess: '#6366f1',
    added_similarity: '#8b5cf6',
    added_fill: '#38bdf8',
    added_to_reach_target: '#94a3b8',
    excluded: '#475569',
};

const REASON_LABELS = {
    seed_kept: 'Kept from your polygon',
    seed_dropped: 'Yours, but no event excess',
    added_excess: 'Added — event excess',
    added_similarity: 'Added — matching curve',
    added_fill: 'Added — hole fill',
    added_to_reach_target: 'Added — reach 10 nodes',
    excluded: 'Not selected',
};

// ==========================================
// DOM ELEMENTS
// ==========================================

const el = {
    stepper: document.getElementById('stepper'),
    stepContents: document.querySelectorAll('.step-content'),
    todoGroups: document.getElementById('todo-groups'),

    // Step 1
    loginForm: document.getElementById('login-form'),
    country: document.getElementById('country'),
    username: document.getElementById('username'),
    password: document.getElementById('password'),
    btnLogin: document.getElementById('btn-login'),
    loginSpinner: document.getElementById('login-spinner'),
    loginError: document.getElementById('login-error'),
    loginErrorMsg: document.getElementById('login-error-message'),

    nodesSection: document.getElementById('nodes-section'),
    nodesCached: document.getElementById('nodes-cached'),
    nodesCachedMsg: document.getElementById('nodes-cached-message'),
    btnReplaceNodes: document.getElementById('btn-replace-nodes'),
    nodesUploadGroup: document.getElementById('nodes-upload-group'),
    nodesUploadArea: document.getElementById('nodes-upload-area'),
    nodesFile: document.getElementById('nodes-file'),
    nodesProgress: document.getElementById('nodes-progress'),
    nodesProgressText: document.getElementById('nodes-progress-text'),
    nodesError: document.getElementById('nodes-error'),
    nodesErrorMsg: document.getElementById('nodes-error-message'),
    btnNext1: document.getElementById('btn-next-1'),

    // Step 2
    geojsonUploadArea: document.getElementById('geojson-upload-area'),
    geojsonFile: document.getElementById('geojson-file'),
    areaSummary: document.getElementById('area-summary'),
    areaSummaryMsg: document.getElementById('area-summary-message'),
    eventDate: document.getElementById('event-date'),
    primaryMetric: document.getElementById('primary-metric'),
    useBaseline: document.getElementById('use-baseline'),
    baselineGroup: document.getElementById('baseline-group'),
    baselineDate: document.getElementById('baseline-date'),
    bufferM: document.getElementById('buffer-m'),
    bufferMValue: document.getElementById('buffer-m-value'),
    hourStart: document.getElementById('hour-start'),
    hourEnd: document.getElementById('hour-end'),
    hour23Warning: document.getElementById('hour-23-warning'),
    weightsHint: document.getElementById('weights-hint'),
    inputError: document.getElementById('input-error'),
    inputErrorMsg: document.getElementById('input-error-message'),
    inputWarnings: document.getElementById('input-warnings'),
    btnBack2: document.getElementById('btn-back-2'),
    btnPreview: document.getElementById('btn-preview'),
    previewSpinner: document.getElementById('preview-spinner'),
    btnRun: document.getElementById('btn-run'),

    // Step 3
    runSpinner: document.getElementById('run-spinner'),
    runHeadline: document.getElementById('run-headline'),
    runElapsed: document.getElementById('run-elapsed'),
    projectTrace: document.getElementById('project-trace'),
    projectTraceMsg: document.getElementById('project-trace-message'),
    runError: document.getElementById('run-error'),
    runErrorMsg: document.getElementById('run-error-message'),
    btnBack3: document.getElementById('btn-back-3'),

    // Step 4
    layerSelect: document.getElementById('layer-select'),
    btnModeToggle: document.getElementById('btn-mode-toggle'),
    btnModeDraw: document.getElementById('btn-mode-draw'),
    btnReset: document.getElementById('btn-reset'),
    mapLegend: document.getElementById('map-legend'),
    coverageBefore: document.getElementById('coverage-before'),
    coverageAfter: document.getElementById('coverage-after'),
    coverageDetail: document.getElementById('coverage-detail'),
    hourlyChart: document.getElementById('hourly-chart'),
    hourlyChartLegend: document.getElementById('hourly-chart-legend'),
    windowStart: document.getElementById('window-start'),
    windowEnd: document.getElementById('window-end'),
    btnRecompute: document.getElementById('btn-recompute'),
    recomputeSpinner: document.getElementById('recompute-spinner'),
    windowSource: document.getElementById('window-source'),
    reasonList: document.getElementById('reason-list'),
    reviewWarnings: document.getElementById('review-warnings'),
    btnBack4: document.getElementById('btn-back-4'),
    btnAccept: document.getElementById('btn-accept'),

    // Step 5
    exportId: document.getElementById('export-id'),
    exportName: document.getElementById('export-name'),
    exportSummary: document.getElementById('export-summary'),
    btnDownloadGeojson: document.getElementById('btn-download-geojson'),
    btnDownloadReport: document.getElementById('btn-download-report'),
    exportProjectTrace: document.getElementById('export-project-trace'),
    btnBack5: document.getElementById('btn-back-5'),
    btnRestart: document.getElementById('btn-restart'),
};

// ==========================================
// HELPERS
// ==========================================

function show(node) { if (node) node.classList.remove('hidden'); }
function hide(node) { if (node) node.classList.add('hidden'); }

function showError(box, msgNode, message) {
    if (!box || !msgNode) return;
    msgNode.textContent = message;
    show(box);
}

function clearError(box) { hide(box); }

function formatCount(value) {
    return Number(value).toLocaleString('en-US');
}

function formatAge(seconds) {
    if (seconds < 60) return 'just now';
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes} min ago`;
    const hours = Math.round(minutes / 60);
    return `${hours} h ago`;
}

function formatElapsed(seconds) {
    const s = Math.floor(seconds);
    if (s < 60) return `${s}s`;
    return `${Math.floor(s / 60)}m ${s % 60}s`;
}

function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (c) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
}

function renderWarnings(container, warnings) {
    if (!container) return;
    container.innerHTML = '';
    (warnings || []).forEach((w) => {
        const level = w.level === 'error' ? 'error' : (w.level === 'info' ? 'info' : 'warning');
        const div = document.createElement('div');
        div.className = `alert alert-${level}`;
        div.innerHTML = `
            <div class="alert-content">
                <div class="alert-title">${escapeHtml(w.code || 'Notice')}</div>
                <div class="alert-message">${escapeHtml(w.message || '')}</div>
            </div>`;
        container.appendChild(div);
    });
}

function downloadBlob(filename, content, mime) {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

// ==========================================
// STEPPER
// ==========================================

function goToStep(step) {
    state.currentStep = step;

    el.stepper.querySelectorAll('.stepper-step').forEach((node) => {
        const index = Number(node.dataset.step);
        node.classList.toggle('active', index === step);
        node.classList.toggle('completed', index < step);
    });

    el.stepContents.forEach((node) => {
        node.classList.toggle('active', node.id === `step-${step}`);
    });

    const wide = step >= 4;
    document.querySelector('.po-layout').classList.toggle('po-wide', wide);
    document.getElementById('main-container').classList.toggle('po-roomy', wide);

    window.scrollTo({ top: 0, behavior: 'smooth' });

    // Leaflet needs a nudge when its container becomes visible.
    setTimeout(() => {
        if (step === 2 && state.inputMap) state.inputMap.invalidateSize();
        if (step === 4 && state.reviewMap) state.reviewMap.invalidateSize();
    }, 60);
}

// ==========================================
// TO-DO SIDEBAR
// ==========================================

function initTodo() {
    state.jobSteps = Object.keys(STEP_LABELS).map((key) => ({
        key, label: STEP_LABELS[key], state: 'pending', detail: null,
    }));
    renderTodo();
}

function renderTodo() {
    const byKey = {};
    state.jobSteps.forEach((s) => { byKey[s.key] = s; });

    el.todoGroups.innerHTML = TODO_GROUPS.map((group) => {
        const items = group.keys.map((key) => {
            const step = byKey[key] || { label: STEP_LABELS[key], state: 'pending', detail: null };
            let mark = '<span class="po-dot"></span>';
            if (step.state === 'running') mark = '<span class="po-spin"></span>';
            else if (step.state === 'done') mark = '<span style="color: var(--success);">✓</span>';
            else if (step.state === 'error') mark = '<span style="color: var(--error);">✕</span>';
            else if (step.state === 'skipped') mark = '<span class="po-dot"></span>';

            const detail = step.detail
                ? `<span class="po-todo-detail">${escapeHtml(step.detail)}</span>` : '';

            return `
                <div class="po-todo-item state-${step.state}">
                    <span class="po-todo-mark">${mark}</span>
                    <span class="po-todo-body">${escapeHtml(step.label)}${detail}</span>
                </div>`;
        }).join('');

        return `
            <div class="po-todo-group">
                <div class="po-todo-group-title">${escapeHtml(group.title)}</div>
                ${items}
            </div>`;
    }).join('');
}

// ==========================================
// STEP 1: LOGIN AND NODE FILE
// ==========================================

el.loginForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    clearError(el.loginError);

    const countryCode = el.country.value;
    if (!countryCode) {
        showError(el.loginError, el.loginErrorMsg, 'Select the country before signing in.');
        return;
    }

    el.btnLogin.disabled = true;
    show(el.loginSpinner);

    try {
        const res = await fetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                username: el.username.value,
                password: el.password.value,
                country_code: countryCode,
            }),
        });
        const data = await res.json();

        if (!data.success) {
            showError(el.loginError, el.loginErrorMsg,
                data.error || 'Sign in failed. Check the email, the password and the country.');
            return;
        }

        state.token = data.token;
        state.rootUrl = data.root_url;
        state.brand = data.brand;
        state.countryCode = data.country_code;

        // Credentials are not needed any more.
        el.password.value = '';

        show(el.nodesSection);
        await refreshNodesStatus();
    } catch (error) {
        showError(el.loginError, el.loginErrorMsg,
            `Could not reach the Kido API (${error.message}). Check your network and try again.`);
    } finally {
        el.btnLogin.disabled = false;
        hide(el.loginSpinner);
    }
});

async function refreshNodesStatus() {
    try {
        const res = await fetch(`/api/polygon-optimizer/nodes-status/${state.countryCode}`);
        const data = await res.json();

        if (data.loaded) {
            state.nodesLoaded = true;
            state.nodeRows = data.rows;
            el.nodesCachedMsg.textContent =
                `Nodes for ${state.countryCode.toUpperCase()} already loaded ` +
                `(${formatCount(data.rows)} nodes, ${formatAge(data.age_seconds)}).`;
            show(el.nodesCached);
            hide(el.nodesUploadGroup);
            el.btnNext1.disabled = false;
        } else {
            state.nodesLoaded = false;
            hide(el.nodesCached);
            show(el.nodesUploadGroup);
            el.btnNext1.disabled = true;
        }
    } catch (error) {
        state.nodesLoaded = false;
        show(el.nodesUploadGroup);
    }
}

el.btnReplaceNodes.addEventListener('click', async () => {
    await fetch(`/api/polygon-optimizer/nodes/${state.countryCode}`, { method: 'DELETE' });
    state.nodesLoaded = false;
    hide(el.nodesCached);
    show(el.nodesUploadGroup);
    el.btnNext1.disabled = true;
});

el.nodesUploadArea.addEventListener('click', () => el.nodesFile.click());
el.nodesUploadArea.addEventListener('dragover', (e) => {
    e.preventDefault();
    el.nodesUploadArea.classList.add('dragover');
});
el.nodesUploadArea.addEventListener('dragleave', () => el.nodesUploadArea.classList.remove('dragover'));
el.nodesUploadArea.addEventListener('drop', (e) => {
    e.preventDefault();
    el.nodesUploadArea.classList.remove('dragover');
    if (e.dataTransfer.files.length) uploadNodeFile(e.dataTransfer.files[0]);
});
el.nodesFile.addEventListener('change', (e) => {
    if (e.target.files.length) uploadNodeFile(e.target.files[0]);
});

async function uploadNodeFile(file) {
    clearError(el.nodesError);
    show(el.nodesProgress);
    el.nodesProgressText.textContent =
        `Uploading ${file.name} (${(file.size / 1048576).toFixed(1)} MB)…`;
    el.btnNext1.disabled = true;

    const formData = new FormData();
    formData.append('file', file);
    formData.append('country_code', state.countryCode);

    try {
        const res = await fetch('/api/polygon-optimizer/upload-nodes', {
            method: 'POST',
            body: formData,
        });

        if (res.status === 413) {
            showError(el.nodesError, el.nodesErrorMsg,
                'The file is too large for the server to accept. Upload the zipped node file instead, ' +
                'which is around 24 MB.');
            return;
        }

        const data = await res.json();
        if (!data.success) {
            showError(el.nodesError, el.nodesErrorMsg, data.error);
            return;
        }

        state.nodesLoaded = true;
        state.nodeRows = data.rows;
        await refreshNodesStatus();
    } catch (error) {
        showError(el.nodesError, el.nodesErrorMsg,
            `The upload failed (${error.message}). Try the zipped file, which is much smaller.`);
    } finally {
        hide(el.nodesProgress);
        el.nodesFile.value = '';
    }
}

el.btnNext1.addEventListener('click', () => {
    goToStep(2);
    initInputMap();
});

// ==========================================
// STEP 2: INPUT
// ==========================================

document.querySelectorAll('.tab-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.tab-btn').forEach((b) => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach((c) => c.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
    });
});

function initInputMap() {
    if (state.inputMap) {
        state.inputMap.invalidateSize();
        return;
    }

    state.inputMap = L.map('input-map').setView([-22.91, -43.19], 13);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors',
        maxZoom: 19,
    }).addTo(state.inputMap);

    state.inputDrawnItems = new L.FeatureGroup();
    state.inputMap.addLayer(state.inputDrawnItems);

    const drawControl = new L.Control.Draw({
        draw: {
            polygon: { allowIntersection: false, shapeOptions: { color: '#6366f1' } },
            rectangle: { shapeOptions: { color: '#6366f1' } },
            polyline: false,
            circle: false,
            circlemarker: false,
            marker: false,
        },
        edit: { featureGroup: state.inputDrawnItems },
    });
    state.inputMap.addControl(drawControl);

    state.inputMap.on(L.Draw.Event.CREATED, (event) => {
        state.inputDrawnItems.clearLayers();
        state.inputDrawnItems.addLayer(event.layer);
        setInputGeometry(event.layer.toGeoJSON(), 'drawn on the map');
    });

    state.inputMap.on(L.Draw.Event.EDITED, () => {
        const layers = state.inputDrawnItems.getLayers();
        if (layers.length) setInputGeometry(layers[0].toGeoJSON(), 'edited on the map');
    });
}

function setInputGeometry(feature, source) {
    state.inputGeojson = feature;
    clearError(el.inputError);
    el.areaSummaryMsg.textContent = `Event area ${source}. Preview the nodes to see how many zones the diagnostic project will hold.`;
    show(el.areaSummary);
    updateRunAvailability();
}

el.geojsonUploadArea.addEventListener('click', () => el.geojsonFile.click());
el.geojsonUploadArea.addEventListener('dragover', (e) => {
    e.preventDefault();
    el.geojsonUploadArea.classList.add('dragover');
});
el.geojsonUploadArea.addEventListener('dragleave', () => el.geojsonUploadArea.classList.remove('dragover'));
el.geojsonUploadArea.addEventListener('drop', (e) => {
    e.preventDefault();
    el.geojsonUploadArea.classList.remove('dragover');
    if (e.dataTransfer.files.length) readGeojsonFile(e.dataTransfer.files[0]);
});
el.geojsonFile.addEventListener('change', (e) => {
    if (e.target.files.length) readGeojsonFile(e.target.files[0]);
});

function readGeojsonFile(file) {
    const reader = new FileReader();
    reader.onload = () => {
        let parsed;
        try {
            parsed = JSON.parse(reader.result);
        } catch (error) {
            showError(el.inputError, el.inputErrorMsg,
                'The file is not valid JSON. Export it again as GeoJSON and retry.');
            return;
        }

        let note = `loaded from ${file.name}`;
        if (parsed.type === 'FeatureCollection' && (parsed.features || []).length > 1) {
            note += ` — the file has ${parsed.features.length} features, only the first one is used`;
        }

        state.inputDrawnItems.clearLayers();
        try {
            const layer = L.geoJSON(parsed, { style: { color: '#6366f1' } });
            layer.eachLayer((l) => state.inputDrawnItems.addLayer(l));
            state.inputMap.fitBounds(state.inputDrawnItems.getBounds(), { padding: [30, 30] });
        } catch (error) {
            showError(el.inputError, el.inputErrorMsg,
                'The geometry could not be drawn on the map. Check that it is a Polygon in EPSG:4326.');
            return;
        }

        setInputGeometry(parsed, note);
    };
    reader.readAsText(file);
}

el.bufferM.addEventListener('input', () => {
    state.bufferM = Number(el.bufferM.value);
    el.bufferMValue.textContent = `${state.bufferM} m`;
});

el.useBaseline.addEventListener('change', () => {
    if (el.useBaseline.checked) {
        show(el.baselineGroup);
        if (!el.baselineDate.value && el.eventDate.value) {
            el.baselineDate.value = sameWeekdayFourWeeksEarlier(el.eventDate.value);
        }
        el.weightsHint.textContent =
            'Baseline mode: the defaults are 0.40 / 0.30 / 0.15 / 0.15.';
        setWeightDefaults(0.40, 0.30, 0.15, 0.15);
    } else {
        hide(el.baselineGroup);
        el.weightsHint.textContent =
            'No baseline: the weights shift to 0.30 / 0.35 / 0.20 / 0.15, because excess gets less ' +
            'reliable and the shape of the curve matters more.';
        setWeightDefaults(0.30, 0.35, 0.20, 0.15);
    }
    updateRunAvailability();
});

function setWeightDefaults(excess, similarity, peak, proximity) {
    document.getElementById('w-excess').value = excess.toFixed(2);
    document.getElementById('w-similarity').value = similarity.toFixed(2);
    document.getElementById('w-peak').value = peak.toFixed(2);
    document.getElementById('w-proximity').value = proximity.toFixed(2);
}

function sameWeekdayFourWeeksEarlier(dateStr) {
    const date = new Date(`${dateStr}T00:00:00`);
    date.setDate(date.getDate() - 28);
    return date.toISOString().slice(0, 10);
}

el.eventDate.addEventListener('change', () => {
    if (el.useBaseline.checked && el.eventDate.value) {
        el.baselineDate.value = sameWeekdayFourWeeksEarlier(el.eventDate.value);
    }
    updateRunAvailability();
});

el.hourEnd.addEventListener('change', () => {
    if (Number(el.hourEnd.value) >= 23) show(el.hour23Warning);
    else hide(el.hour23Warning);
});

function updateRunAvailability() {
    const ready = Boolean(state.inputGeojson) && Boolean(el.eventDate.value);
    el.btnPreview.disabled = !ready;
    el.btnRun.disabled = !ready;
}

function collectParams() {
    const start = Math.max(0, Math.min(23, Number(el.hourStart.value)));
    const end = Math.max(0, Math.min(23, Number(el.hourEnd.value)));
    const validHours = [];
    for (let h = Math.min(start, end); h <= Math.max(start, end); h += 1) validHours.push(h);

    return {
        valid_hours: validHours,
        w_excess: Number(document.getElementById('w-excess').value),
        w_similarity: Number(document.getElementById('w-similarity').value),
        w_peak: Number(document.getElementById('w-peak').value),
        w_proximity: Number(document.getElementById('w-proximity').value),
        proximity_length_m: Number(document.getElementById('proximity-length').value),
        fill_neighbour_threshold: Number(document.getElementById('fill-threshold').value),
        min_component_share: Number(document.getElementById('min-component-share').value),
        target_node_count: Number(document.getElementById('target-count').value),
        closing_radius_m: Number(document.getElementById('closing-radius').value),
        simplify_tolerance_m: Number(document.getElementById('simplify-tolerance').value),
    };
}

function validateDates() {
    const today = new Date().toISOString().slice(0, 10);
    if (el.eventDate.value >= today) {
        return 'The event date must be in the past. Data is only available for days that have already been processed.';
    }
    if (el.useBaseline.checked) {
        if (!el.baselineDate.value) {
            return 'Pick a baseline day, or uncheck the baseline comparison.';
        }
        if (el.baselineDate.value >= today) {
            return 'The baseline date must be in the past.';
        }
        if (el.baselineDate.value === el.eventDate.value) {
            return 'The baseline day must be different from the event day.';
        }
    }
    return null;
}

el.btnPreview.addEventListener('click', async () => {
    clearError(el.inputError);
    el.btnPreview.disabled = true;
    show(el.previewSpinner);

    try {
        const res = await fetch('/api/polygon-optimizer/preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                country_code: state.countryCode,
                geojson: state.inputGeojson,
                buffer_m: state.bufferM,
            }),
        });
        const data = await res.json();

        if (!data.success) {
            showError(el.inputError, el.inputErrorMsg, data.error);
            return;
        }

        drawPreview(data);
        renderWarnings(el.inputWarnings, data.warnings);
        el.areaSummaryMsg.textContent =
            `${formatCount(data.node_count)} nodes in the ${state.bufferM} m collection area, ` +
            `${formatCount(data.seed_count)} of them inside your polygon. ` +
            `The diagnostic project will hold ${formatCount(data.node_count)} zones.`;
        show(el.areaSummary);
    } catch (error) {
        showError(el.inputError, el.inputErrorMsg,
            `The preview failed (${error.message}). Try again in a moment.`);
    } finally {
        el.btnPreview.disabled = false;
        hide(el.previewSpinner);
    }
});

function drawPreview(data) {
    if (state.inputNodeLayer) state.inputMap.removeLayer(state.inputNodeLayer);
    if (state.inputBufferLayer) state.inputMap.removeLayer(state.inputBufferLayer);

    state.inputBufferLayer = L.geoJSON(data.buffer_geometry, {
        style: { color: '#8b5cf6', weight: 1, dashArray: '4 4', fillOpacity: 0.05 },
    }).addTo(state.inputMap);

    state.inputNodeLayer = L.layerGroup(
        data.nodes.map((node) => L.circleMarker([node.lat, node.lon], {
            radius: 3,
            color: node.in_seed ? '#10b981' : '#64748b',
            fillColor: node.in_seed ? '#10b981' : '#64748b',
            fillOpacity: 0.8,
            weight: 1,
        }))
    ).addTo(state.inputMap);

    state.inputMap.fitBounds(state.inputBufferLayer.getBounds(), { padding: [30, 30] });
}

el.btnBack2.addEventListener('click', () => goToStep(1));

el.btnRun.addEventListener('click', async () => {
    clearError(el.inputError);

    const dateProblem = validateDates();
    if (dateProblem) {
        showError(el.inputError, el.inputErrorMsg, dateProblem);
        return;
    }

    el.btnRun.disabled = true;

    try {
        const res = await fetch('/api/polygon-optimizer/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                token: state.token,
                root_url: state.rootUrl,
                country_code: state.countryCode,
                geojson: state.inputGeojson,
                event_date: el.eventDate.value,
                baseline_date: el.useBaseline.checked ? el.baselineDate.value : null,
                buffer_m: state.bufferM,
                primary_metric: el.primaryMetric.value,
                params: collectParams(),
            }),
        });
        const data = await res.json();

        if (!data.success) {
            showError(el.inputError, el.inputErrorMsg, data.error || 'The analysis could not be started.');
            el.btnRun.disabled = false;
            return;
        }

        state.jobId = data.job_id;
        startPolling();
        goToStep(3);
    } catch (error) {
        showError(el.inputError, el.inputErrorMsg,
            `The analysis could not be started (${error.message}).`);
        el.btnRun.disabled = false;
    }
});

// ==========================================
// STEP 3: PROCESSING
// ==========================================

function startPolling() {
    clearError(el.runError);
    hide(el.projectTrace);
    hide(el.btnBack3);
    show(el.runSpinner);
    el.runHeadline.textContent = 'Working…';
    initTodo();

    state.jobStartedAt = Date.now();
    state.elapsedTimer = setInterval(() => {
        el.runElapsed.textContent = `${formatElapsed((Date.now() - state.jobStartedAt) / 1000)} elapsed`;
    }, 1000);

    pollJob();
    state.pollTimer = setInterval(pollJob, 2500);
}

function stopPolling() {
    if (state.pollTimer) clearInterval(state.pollTimer);
    if (state.elapsedTimer) clearInterval(state.elapsedTimer);
    state.pollTimer = null;
    state.elapsedTimer = null;
}

async function pollJob() {
    try {
        const res = await fetch(`/api/polygon-optimizer/status/${state.jobId}`);
        const data = await res.json();

        if (!data.success) {
            stopPolling();
            hide(el.runSpinner);
            showError(el.runError, el.runErrorMsg, data.error);
            show(el.btnBack3);
            return;
        }

        state.jobSteps = data.steps;
        renderTodo();

        const running = data.steps.find((s) => s.state === 'running');
        el.runHeadline.textContent = running ? running.label : 'Working…';

        traceProjectFromSteps(data.steps);

        if (data.state === 'error') {
            stopPolling();
            hide(el.runSpinner);
            showError(el.runError, el.runErrorMsg, data.error);
            show(el.btnBack3);
            el.btnRun.disabled = false;
        } else if (data.state === 'done') {
            stopPolling();
            hide(el.runSpinner);
            el.runHeadline.textContent = 'Analysis complete';
            onResult(data.result);
        }
    } catch (error) {
        // A transient network blip should not kill the run; the next tick retries.
    }
}

function traceProjectFromSteps(steps) {
    const created = steps.find((s) => s.key === 'create_project' && s.detail);
    if (!created) return;
    el.projectTraceMsg.textContent = created.detail;
    show(el.projectTrace);
}

el.btnBack3.addEventListener('click', () => {
    stopPolling();
    el.btnRun.disabled = false;
    goToStep(2);
});

// ==========================================
// STEP 4 AND 5 (wired in the review build)
// ==========================================

function onResult(result) {
    state.result = result;
    state.projectId = result.project_id;
    state.projectName = result.project_name;
    if (typeof enterReview === 'function') enterReview(result);
}

el.btnBack4.addEventListener('click', () => goToStep(2));
el.btnBack5.addEventListener('click', () => goToStep(4));
el.btnRestart.addEventListener('click', () => window.location.reload());

// ==========================================
// INIT
// ==========================================

(function init() {
    initTodo();
    el.bufferMValue.textContent = `${el.bufferM.value} m`;
    state.bufferM = Number(el.bufferM.value);

    // Default the event date picker to yesterday, the most recent day that can
    // realistically have data.
    const yesterday = new Date();
    yesterday.setDate(yesterday.getDate() - 1);
    el.eventDate.max = yesterday.toISOString().slice(0, 10);
    el.baselineDate.max = el.eventDate.max;
})();

// ==========================================
// STEP 4: REVIEW
// ==========================================

const review = {
    nodeLayer: null,
    polygonLayer: null,
    inputLayer: null,
    markers: {},          // node_id -> circleMarker
    mode: 'view',         // view | toggle | draw
    drawnItems: null,
    drawHandler: null,
    geometryToken: 0,     // guards against out-of-order geometry responses
    pendingGeometry: null,
};

// A perceptually even ramp for the continuous layers, dark to bright.
const RAMP = ['#1e1b4b', '#3730a3', '#6366f1', '#a78bfa', '#f0abfc', '#fde68a'];

function rampColor(t) {
    if (!isFinite(t)) return RAMP[0];
    const clamped = Math.max(0, Math.min(1, t));
    const scaled = clamped * (RAMP.length - 1);
    return RAMP[Math.round(scaled)];
}

function enterReview(result) {
    state.selectedIds = new Set(result.nodes.filter((n) => n.selected).map((n) => n.node_id));
    state.currentGeometry = result.geometry;

    el.windowStart.value = result.event_window[0];
    el.windowEnd.value = result.event_window[1];
    el.windowSource.textContent = result.event_window_source === 'user'
        ? 'Set by you. Recompute applies it without querying the platform again.'
        : `Detected automatically from the arrival curve (${result.detected_window[0]}h–${result.detected_window[1]}h).`;

    el.exportName.value = `${result.project_name || 'event'}_optimized`;
    el.exportProjectTrace.textContent =
        `${result.project_name} · ${result.project_id}`;

    // The step has to be visible before the map is measured, otherwise
    // fitBounds runs against a zero-sized container and nothing is drawn.
    goToStep(4);
    initReviewMap();
    setTimeout(() => {
        state.reviewMap.invalidateSize();
        renderReview();
    }, 80);
}

function initReviewMap() {
    if (state.reviewMap) {
        state.reviewMap.invalidateSize();
        return;
    }

    state.reviewMap = L.map('review-map').setView([0, 0], 2);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors',
        maxZoom: 19,
    }).addTo(state.reviewMap);

    review.drawnItems = new L.FeatureGroup();
    state.reviewMap.addLayer(review.drawnItems);

    attachDrawHandlers();
}

function renderReview() {
    const result = state.result;

    drawInputPolygon(result);
    drawSuggestedPolygon(state.currentGeometry);
    drawNodes(result);
    renderLegend();
    renderCoverage();
    renderHourlyChart(result);
    renderReasons(result);
    renderWarnings(el.reviewWarnings, result.warnings);
}

function drawInputPolygon(result) {
    if (review.inputLayer) state.reviewMap.removeLayer(review.inputLayer);
    review.inputLayer = L.geoJSON(result.input_geometry, {
        style: { color: '#94a3b8', weight: 2, dashArray: '6 5', fill: false },
    }).addTo(state.reviewMap);
}

function drawSuggestedPolygon(geometry) {
    if (review.polygonLayer) state.reviewMap.removeLayer(review.polygonLayer);
    if (!geometry) return;

    review.polygonLayer = L.geoJSON(geometry, {
        style: { color: '#10b981', weight: 2, fillColor: '#10b981', fillOpacity: 0.18 },
    }).addTo(state.reviewMap);

    // The polygon sits under the node markers so clicks still reach them.
    review.polygonLayer.bringToBack();
    if (review.inputLayer) review.inputLayer.bringToBack();
}

function nodeColor(node, layer, extent) {
    if (layer === 'decision') {
        return REASON_COLORS[node.reason] || REASON_COLORS.excluded;
    }
    const value = layer === 'excess' ? node.excess
        : layer === 'similarity' ? node.similarity
            : node.total_event;
    const span = extent.max - extent.min;
    return rampColor(span > 0 ? (value - extent.min) / span : 0);
}

function layerExtent(nodes, layer) {
    const values = nodes.map((n) => (
        layer === 'excess' ? n.excess : layer === 'similarity' ? n.similarity : n.total_event
    ));
    return { min: Math.min(...values), max: Math.max(...values) };
}

function drawNodes(result) {
    if (review.nodeLayer) state.reviewMap.removeLayer(review.nodeLayer);
    review.markers = {};

    const layer = el.layerSelect.value;
    const extent = layerExtent(result.nodes, layer);

    const markers = result.nodes.map((node) => {
        const selected = state.selectedIds.has(node.node_id);
        const marker = L.circleMarker([node.lat, node.lon], {
            radius: selected ? 6 : 4,
            color: selected ? '#f8fafc' : 'rgba(255,255,255,0.25)',
            weight: selected ? 1.5 : 1,
            fillColor: nodeColor(node, layer, extent),
            fillOpacity: selected ? 0.95 : 0.45,
        });

        marker.bindPopup(() => nodePopup(node), { maxWidth: 260 });
        marker.on('click', () => {
            if (review.mode === 'toggle') toggleNode(node.node_id);
        });

        review.markers[node.node_id] = marker;
        return marker;
    });

    review.nodeLayer = L.layerGroup(markers).addTo(state.reviewMap);

    const bounds = review.polygonLayer
        ? review.polygonLayer.getBounds()
        : (review.nodeLayer ? L.featureGroup(markers).getBounds() : null);
    if (bounds && bounds.isValid()) {
        state.reviewMap.invalidateSize();
        state.reviewMap.fitBounds(bounds, { padding: [40, 40] });
    }
}

function nodePopup(node) {
    const selected = state.selectedIds.has(node.node_id);
    const rows = [
        ['Volume (event day)', node.total_event.toLocaleString('en-US')],
        ['Excess', node.excess.toLocaleString('en-US')],
        ['Similarity', node.similarity.toFixed(2)],
        ['Peak hour', `${node.peak_hour}:00`],
        ['Rank', `#${node.rank}`],
        ['Coverage', `${(node.coverage_ratio * 100).toFixed(0)}%`],
    ];
    if (node.total_baseline !== null && node.total_baseline !== undefined) {
        rows.splice(1, 0, ['Volume (baseline)', node.total_baseline.toLocaleString('en-US')]);
    }

    const flags = [];
    if (node.low_confidence) flags.push('<span class="tag tag-warning">low confidence</span>');
    if (node.component_flagged) flags.push('<span class="tag tag-warning">detached block</span>');

    return `
        <div class="po-popup">
            <div class="font-semibold">${escapeHtml(REASON_LABELS[node.reason] || node.reason)}</div>
            <div class="po-reason-id">buffer_${node.node_id}</div>
            <div class="mt-sm">${flags.join(' ')}</div>
            ${sparkline(node)}
            <table class="mt-sm">
                ${rows.map(([k, v]) => `<tr><td>${escapeHtml(k)}</td><td class="po-popup-val">${escapeHtml(v)}</td></tr>`).join('')}
            </table>
            <div class="mt-sm text-muted text-xs">
                ${selected ? 'In the current selection.' : 'Not in the current selection.'}
                ${review.mode === 'toggle' ? ' Click the node to flip it.' : ''}
            </div>
        </div>`;
}

function sparkline(node) {
    const width = 190;
    const height = 44;
    const curve = node.hourly_event || [];
    const reference = state.result.reference_curve || [];
    if (!curve.length) return '';

    const maxCurve = Math.max(...curve, 1);
    const maxRef = Math.max(...reference.map(Math.abs), 1);
    const step = width / 23;

    const path = (values, scale) => values.map((v, i) => (
        `${i === 0 ? 'M' : 'L'}${(i * step).toFixed(1)},${(height - (v / scale) * (height - 4) - 2).toFixed(1)}`
    )).join(' ');

    const window = state.result.event_window;
    const bandX = window[0] * step;
    const bandW = Math.max(step, (window[1] - window[0]) * step);

    return `
        <svg class="po-sparkline mt-sm" viewBox="0 0 ${width} ${height}">
            <rect x="${bandX.toFixed(1)}" y="0" width="${bandW.toFixed(1)}" height="${height}"
                  fill="rgba(99,102,241,0.18)"></rect>
            <path d="${path(reference.map((v) => Math.max(v, 0)), maxRef)}"
                  fill="none" stroke="#64748b" stroke-width="1" stroke-dasharray="2 2"></path>
            <path d="${path(curve, maxCurve)}" fill="none" stroke="#10b981" stroke-width="1.5"></path>
        </svg>
        <div class="text-muted text-xs">Green: this node. Grey: the event reference curve.</div>`;
}

function renderLegend() {
    const layer = el.layerSelect.value;

    if (layer === 'decision') {
        el.mapLegend.innerHTML = Object.keys(REASON_LABELS).map((reason) => `
            <span class="po-legend-item">
                <span class="po-legend-swatch" style="background:${REASON_COLORS[reason]}"></span>
                ${escapeHtml(REASON_LABELS[reason])}
            </span>`).join('');
        return;
    }

    const label = layer === 'excess' ? 'Event excess'
        : layer === 'similarity' ? 'Curve similarity' : 'Raw volume';
    el.mapLegend.innerHTML = `
        <span class="po-legend-item">${escapeHtml(label)}: low</span>
        ${RAMP.map((c) => `<span class="po-legend-swatch" style="background:${c}"></span>`).join('')}
        <span class="po-legend-item">high</span>`;
}

function renderCoverage() {
    const nodes = state.result.nodes;
    const positive = (n) => Math.max(n.excess, 0);
    const total = nodes.reduce((sum, n) => sum + positive(n), 0);

    const seedShare = total > 0
        ? nodes.filter((n) => n.in_seed).reduce((s, n) => s + positive(n), 0) / total : 0;
    const selectedShare = total > 0
        ? nodes.filter((n) => state.selectedIds.has(n.node_id)).reduce((s, n) => s + positive(n), 0) / total : 0;

    el.coverageBefore.textContent = `${(seedShare * 100).toFixed(0)}%`;
    el.coverageAfter.textContent = `${(selectedShare * 100).toFixed(0)}%`;

    const seedCount = nodes.filter((n) => n.in_seed).length;
    const selectedCount = state.selectedIds.size;
    const added = nodes.filter((n) => state.selectedIds.has(n.node_id) && !n.in_seed).length;
    const dropped = nodes.filter((n) => n.in_seed && !state.selectedIds.has(n.node_id)).length;

    el.coverageDetail.textContent =
        `${seedCount} nodes in your polygon, ${selectedCount} in the current selection ` +
        `(${added} added, ${dropped} removed). ${((1 - selectedShare) * 100).toFixed(0)}% of the ` +
        `event excess is still outside.`;
}

function renderHourlyChart(result) {
    const width = 380;
    const height = 150;
    const seed = result.seed_curve || [];
    const baseline = result.baseline_curve;
    if (!seed.length) return;

    const max = Math.max(...seed, ...(baseline || [0]), 1);
    const step = width / 23;
    const y = (v) => height - (v / max) * (height - 16) - 8;

    const line = (values, color, dash) => `
        <path d="${values.map((v, i) => `${i === 0 ? 'M' : 'L'}${(i * step).toFixed(1)},${y(v).toFixed(1)}`).join(' ')}"
              fill="none" stroke="${color}" stroke-width="2"
              ${dash ? `stroke-dasharray="${dash}"` : ''}></path>`;

    const window = result.event_window;
    const bandX = window[0] * step;
    const bandW = Math.max(step, (window[1] - window[0]) * step);

    el.hourlyChart.innerHTML = `
        <rect x="${bandX.toFixed(1)}" y="0" width="${bandW.toFixed(1)}" height="${height}"
              fill="rgba(99,102,241,0.18)"></rect>
        ${baseline ? line(baseline, '#64748b', '4 3') : ''}
        ${line(seed, '#10b981')}`;

    el.hourlyChartLegend.textContent = baseline
        ? `Green: event day (${result.event_date}). Grey: baseline (${result.baseline_date}), rescaled ×${result.summary.volume_scale}. Shaded: the event window.`
        : `Green: event day (${result.event_date}). No baseline day, so the reference is the background profile of the outer ring. Shaded: the event window.`;
}

function renderReasons(result) {
    const changed = result.nodes.filter((n) => {
        const selected = state.selectedIds.has(n.node_id);
        return (selected && !n.in_seed) || (!selected && n.in_seed) || n.reason === 'seed_dropped';
    });

    changed.sort((a, b) => b.excess - a.excess);

    if (!changed.length) {
        el.reasonList.innerHTML = '<p class="text-muted text-sm">The suggestion matches your polygon exactly.</p>';
        return;
    }

    el.reasonList.innerHTML = changed.map((node) => {
        const selected = state.selectedIds.has(node.node_id);
        const label = !selected && node.in_seed ? 'Removed'
            : node.reason === 'seed_dropped' ? 'Suggest removing' : REASON_LABELS[node.reason] || node.reason;
        const color = !selected ? REASON_COLORS.excluded : (REASON_COLORS[node.reason] || REASON_COLORS.added_excess);

        return `
            <div class="po-reason" data-node="${node.node_id}" style="cursor:pointer;">
                <span>
                    <span class="po-legend-swatch" style="background:${color}"></span>
                    ${escapeHtml(label)}
                    <span class="po-reason-id">buffer_${node.node_id}</span>
                </span>
                <span class="font-mono text-xs">${Math.round(node.excess).toLocaleString('en-US')}</span>
            </div>`;
    }).join('');

    el.reasonList.querySelectorAll('.po-reason').forEach((row) => {
        row.addEventListener('click', () => {
            const marker = review.markers[Number(row.dataset.node)];
            if (marker) {
                state.reviewMap.setView(marker.getLatLng(), Math.max(state.reviewMap.getZoom(), 16));
                marker.openPopup();
            }
        });
    });
}

// ==========================================
// EDITING MODES
// ==========================================

el.layerSelect.addEventListener('change', () => {
    drawNodes(state.result);
    renderLegend();
});

function setMode(mode) {
    review.mode = mode;
    el.btnModeToggle.classList.toggle('po-mode-active', mode === 'toggle');
    el.btnModeDraw.classList.toggle('po-mode-active', mode === 'draw');

    if (review.drawHandler) {
        review.drawHandler.disable();
        review.drawHandler = null;
    }

    if (mode === 'draw') {
        review.drawHandler = new L.Draw.Polygon(state.reviewMap, {
            allowIntersection: false,
            shapeOptions: { color: '#f59e0b' },
        });
        review.drawHandler.enable();
    }
}

el.btnModeToggle.addEventListener('click', () => {
    setMode(review.mode === 'toggle' ? 'view' : 'toggle');
});

el.btnModeDraw.addEventListener('click', () => {
    setMode(review.mode === 'draw' ? 'view' : 'draw');
});

function toggleNode(nodeId) {
    if (state.selectedIds.has(nodeId)) state.selectedIds.delete(nodeId);
    else state.selectedIds.add(nodeId);

    // Repaint immediately so the click feels instant, then fetch the outline.
    refreshSelectionStyles();
    renderCoverage();
    renderReasons(state.result);
    requestGeometry();
}

function refreshSelectionStyles() {
    const layer = el.layerSelect.value;
    const extent = layerExtent(state.result.nodes, layer);

    state.result.nodes.forEach((node) => {
        const marker = review.markers[node.node_id];
        if (!marker) return;
        const selected = state.selectedIds.has(node.node_id);
        marker.setStyle({
            radius: selected ? 6 : 4,
            color: selected ? '#f8fafc' : 'rgba(255,255,255,0.25)',
            weight: selected ? 1.5 : 1,
            fillColor: nodeColor(node, layer, extent),
            fillOpacity: selected ? 0.95 : 0.45,
        });
    });
}

async function requestGeometry() {
    if (!state.selectedIds.size) {
        drawSuggestedPolygon(null);
        return;
    }

    const token = ++review.geometryToken;
    try {
        const res = await fetch('/api/polygon-optimizer/geometry', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                job_id: state.jobId,
                node_ids: Array.from(state.selectedIds),
            }),
        });
        const data = await res.json();

        // A slower earlier response must not overwrite a newer selection.
        if (token !== review.geometryToken) return;

        if (data.success) {
            state.currentGeometry = data.geometry;
            drawSuggestedPolygon(data.geometry);
        }
    } catch (error) {
        // Keep the previous outline; the next toggle retries.
    }
}

// Draw manually: the drawn shape decides the node set, not the outline, so
// the edit is resolved back into a set of nodes before anything is redrawn.
function attachDrawHandlers() {
    state.reviewMap.on(L.Draw.Event.CREATED, async (event) => {
        const drawn = event.layer.toGeoJSON();
        setMode('view');

        try {
            const res = await fetch('/api/polygon-optimizer/nodes-in-polygon', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ job_id: state.jobId, geometry: drawn }),
            });
            const data = await res.json();
            if (!data.success) {
                renderWarnings(el.reviewWarnings, [{ level: 'error', code: 'draw_failed', message: data.error }]);
                return;
            }

            const before = new Set(state.selectedIds);
            state.selectedIds = new Set(data.node_ids);

            const added = data.node_ids.filter((id) => !before.has(id));
            const removed = Array.from(before).filter((id) => !state.selectedIds.has(id));

            refreshSelectionStyles();
            renderCoverage();
            renderReasons(state.result);
            await requestGeometry();

            renderWarnings(el.reviewWarnings, [{
                level: 'info',
                code: 'manual_edit',
                message: `Your drawing selected ${data.node_ids.length} nodes: ` +
                    `${added.length} came in and ${removed.length} dropped out.`,
            }]);
        } catch (error) {
            renderWarnings(el.reviewWarnings, [{
                level: 'error', code: 'draw_failed',
                message: `The drawn area could not be read (${error.message}).`,
            }]);
        }
    });
}

el.btnReset.addEventListener('click', () => {
    state.selectedIds = new Set(state.result.nodes.filter((n) => n.selected).map((n) => n.node_id));
    state.currentGeometry = state.result.geometry;
    setMode('view');
    renderReview();
});

el.btnRecompute.addEventListener('click', async () => {
    show(el.recomputeSpinner);
    el.btnRecompute.disabled = true;

    try {
        const res = await fetch('/api/polygon-optimizer/rescore', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                job_id: state.jobId,
                event_window: [Number(el.windowStart.value), Number(el.windowEnd.value)],
            }),
        });
        const data = await res.json();

        if (!data.success) {
            renderWarnings(el.reviewWarnings, [{ level: 'error', code: 'rescore_failed', message: data.error }]);
            return;
        }

        state.result = data.result;
        state.selectedIds = new Set(data.result.nodes.filter((n) => n.selected).map((n) => n.node_id));
        state.currentGeometry = data.result.geometry;
        el.windowSource.textContent = 'Set by you. The platform was not queried again.';
        renderReview();
    } catch (error) {
        renderWarnings(el.reviewWarnings, [{
            level: 'error', code: 'rescore_failed',
            message: `The rescore failed (${error.message}).`,
        }]);
    } finally {
        hide(el.recomputeSpinner);
        el.btnRecompute.disabled = false;
    }
});

el.btnAccept.addEventListener('click', () => {
    const selectedCount = state.selectedIds.size;
    el.exportSummary.textContent =
        `${selectedCount} nodes, ${el.coverageAfter.textContent} of the event excess, ` +
        `event window ${el.windowStart.value}h–${el.windowEnd.value}h on ${state.result.event_date}.`;
    goToStep(5);
});

// ==========================================
// STEP 5: EXPORT
// ==========================================

function buildExportGeojson() {
    const rawId = el.exportId.value.trim() || '1';
    const id = /^-?\d+$/.test(rawId) ? Number(rawId) : rawId;

    return {
        type: 'FeatureCollection',
        features: [{
            type: 'Feature',
            properties: {
                id,
                name: el.exportName.value.trim() || 'optimized_area',
                poly_type: 'core',
            },
            geometry: state.currentGeometry,
        }],
    };
}

el.btnDownloadGeojson.addEventListener('click', () => {
    if (!state.currentGeometry) return;
    const name = (el.exportName.value.trim() || 'optimized_area').replace(/[^\w.-]+/g, '_');
    downloadBlob(`${name}.geojson`, JSON.stringify(buildExportGeojson(), null, 2), 'application/geo+json');
});

el.btnDownloadReport.addEventListener('click', async () => {
    el.btnDownloadReport.disabled = true;
    try {
        const res = await fetch('/api/polygon-optimizer/report-csv', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                job_id: state.jobId,
                node_ids: Array.from(state.selectedIds),
            }),
        });

        const type = res.headers.get('content-type') || '';
        if (type.includes('application/json')) {
            const data = await res.json();
            renderWarnings(el.reviewWarnings, [{
                level: 'error', code: 'report_failed',
                message: data.error || 'The audit report could not be built.',
            }]);
            return;
        }

        const text = await res.text();
        const name = (state.result.project_name || 'polygon_optimizer');
        downloadBlob(`${name}_audit.csv`, text, 'text/csv');
    } finally {
        el.btnDownloadReport.disabled = false;
    }
});
