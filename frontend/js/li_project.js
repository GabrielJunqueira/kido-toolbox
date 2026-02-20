/**
 * LI Project Creator - Main JavaScript
 * 6-step wizard: Login → Nodes → Establishments → Map → Generate → Finish
 */

// ==========================================
// STATE
// ==========================================

const state = {
    currentStep: 1,
    totalSteps: 6,

    // Auth
    token: null,
    rootUrl: null,
    brand: null,
    apiCountry: null,

    // Nodes
    nodeKey: null,      // Server-side node storage key
    nodeCount: 0,
    geoCountry: null,
    geoCountryName: null,
    nodeRadius: 1000,   // Default node search radius in meters

    // Establishments (name + coords, polygon drawn later on map)
    establishments: [],  // Array of {name, lat, lon, polygon: GeoJSON Feature | null}
    buffers: [],         // Array of buffer GeoJSON Feature dicts
    nodesPerEst: [],     // Array of arrays of [lat, lon]

    // Buffer polygons created from drawn polygons
    bufferPolygons: [],  // Array of {estIndex, distance, polygon: GeoJSON Feature, name, id}

    // Map
    map: null,
    drawnItems: null,
    nodeMarkers: null,
    bufferLayers: [],
    markerLayers: [],     // Establishment center markers
    pendingDrawQueue: [], // Indices of establishments that still need polygons drawn

    // Generation
    region: null,
    regionName: null,
    city: null,
    geojson: null,
    filename: null,
    featureCount: 0,
    projectId: null,
};

// Country code to name/flag mapping
const COUNTRY_MAP = {
    'br': { name: 'Brazil', flag: '🇧🇷', geoCode: 'BR' },
    'pt': { name: 'Portugal', flag: '🇵🇹', geoCode: 'PT' },
    'es': { name: 'Spain', flag: '🇪🇸', geoCode: 'ES' },
    'mx': { name: 'Mexico', flag: '🇲🇽', geoCode: 'MX' },
    'ch': { name: 'Switzerland', flag: '🇨🇭', geoCode: 'CH' },
    'cl': { name: 'Chile', flag: '🇨🇱', geoCode: 'CL' },
};

// ==========================================
// DOM ELEMENTS
// ==========================================

const el = {
    stepper: document.getElementById('stepper'),
    stepContents: document.querySelectorAll('.step-content'),

    // Step 1
    loginForm: document.getElementById('login-form'),
    username: document.getElementById('username'),
    password: document.getElementById('password'),
    apiCountry: document.getElementById('api-country'),
    btnLogin: document.getElementById('btn-login'),
    loginError: document.getElementById('login-error'),
    loginErrorMsg: document.getElementById('login-error-message'),

    // Step 2
    uploadArea: document.getElementById('upload-area'),
    nodesFile: document.getElementById('nodes-file'),
    uploadSuccess: document.getElementById('upload-success'),
    uploadSuccessMsg: document.getElementById('upload-success-message'),
    uploadError: document.getElementById('upload-error'),
    uploadErrorMsg: document.getElementById('upload-error-message'),
    btnBack1: document.getElementById('btn-back-1'),
    btnNext2: document.getElementById('btn-next-2'),

    // Step 3
    nodeRadius: document.getElementById('node-radius'),
    searchQuery: document.getElementById('search-query'),
    btnSearch: document.getElementById('btn-search'),
    searchProgress: document.getElementById('search-progress'),
    searchResults: document.getElementById('search-results'),
    searchError: document.getElementById('search-error'),
    searchErrorMsg: document.getElementById('search-error-message'),
    estNameManual: document.getElementById('est-name-manual'),
    estLat: document.getElementById('est-lat'),
    estLon: document.getElementById('est-lon'),
    btnAddCoords: document.getElementById('btn-add-coords'),
    polygonProgress: document.getElementById('polygon-progress'),
    polygonProgressText: document.getElementById('polygon-progress-text'),
    estCountBadge: document.getElementById('est-count-badge'),
    noEstablishments: document.getElementById('no-establishments'),
    establishmentsList: document.getElementById('establishments-list'),
    btnBack2: document.getElementById('btn-back-2'),
    btnNext3: document.getElementById('btn-next-3'),

    // Step 4
    mapContainer: document.getElementById('map-container'),
    polygonStats: document.getElementById('polygon-stats'),
    polygonStatsMsg: document.getElementById('polygon-stats-message'),
    legendBufferText: document.getElementById('legend-buffer-text'),
    btnBack3: document.getElementById('btn-back-3'),
    btnNext4: document.getElementById('btn-next-4'),

    // Step 5
    genRegion: document.getElementById('gen-region'),
    genCity: document.getElementById('gen-city'),
    genSummary: document.getElementById('gen-summary'),
    genProgress: document.getElementById('gen-progress'),
    genError: document.getElementById('gen-error'),
    genErrorMsg: document.getElementById('gen-error-message'),
    btnBack4: document.getElementById('btn-back-4'),
    btnGenerate: document.getElementById('btn-generate'),

    // Step 6
    finalSummary: document.getElementById('final-summary'),
    projectName: document.getElementById('project-name'),
    projectDescription: document.getElementById('project-description'),
    createProgress: document.getElementById('create-progress'),
    createStatus: document.getElementById('create-status'),
    createSuccess: document.getElementById('create-success'),
    createSuccessMsg: document.getElementById('create-success-message'),
    createError: document.getElementById('create-error'),
    createErrorMsg: document.getElementById('create-error-message'),
    btnDownload: document.getElementById('btn-download'),
    btnCreateCloud: document.getElementById('btn-create-cloud'),
    btnNewProject: document.getElementById('btn-new-project'),
};

// ==========================================
// INIT
// ==========================================

document.addEventListener('DOMContentLoaded', () => {
    initEventListeners();
});

function initEventListeners() {
    // Step 1
    el.btnLogin.addEventListener('click', handleLogin);
    el.loginForm.addEventListener('submit', (e) => { e.preventDefault(); handleLogin(); });

    // Step 2
    el.btnBack1.addEventListener('click', () => goToStep(1));
    el.btnNext2.addEventListener('click', () => goToStep(3));
    el.uploadArea.addEventListener('click', () => el.nodesFile.click());
    el.nodesFile.addEventListener('change', handleFileUpload);
    el.uploadArea.addEventListener('dragover', (e) => { e.preventDefault(); el.uploadArea.classList.add('dragover'); });
    el.uploadArea.addEventListener('dragleave', () => el.uploadArea.classList.remove('dragover'));
    el.uploadArea.addEventListener('drop', handleFileDrop);

    // Step 3
    el.nodeRadius.addEventListener('change', handleRadiusChange);

    // Step 3 tabs
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
        });
    });
    el.btnSearch.addEventListener('click', handleSearch);
    el.searchQuery.addEventListener('keypress', (e) => { if (e.key === 'Enter') handleSearch(); });
    el.btnAddCoords.addEventListener('click', handleAddByCoords);
    el.btnBack2.addEventListener('click', () => goToStep(2));
    el.btnNext3.addEventListener('click', () => goToStep(4));

    // Step 4
    el.btnBack3.addEventListener('click', () => goToStep(3));
    el.btnNext4.addEventListener('click', () => goToStep(5));

    // Step 5
    el.genRegion.addEventListener('change', handleRegionChange);
    el.genCity.addEventListener('change', handleCityChange);
    el.btnBack4.addEventListener('click', () => goToStep(4));
    el.btnGenerate.addEventListener('click', handleGenerate);

    // Step 6
    el.btnDownload.addEventListener('click', handleDownload);
    el.btnCreateCloud.addEventListener('click', handleCreateCloud);
    el.btnNewProject.addEventListener('click', resetWizard);
}

// ==========================================
// NAVIGATION
// ==========================================

function goToStep(step) {
    if (step < 1 || step > state.totalSteps) return;
    state.currentStep = step;

    // Update stepper
    const steps = el.stepper.querySelectorAll('.stepper-step');
    steps.forEach((s, i) => {
        s.classList.remove('active', 'completed');
        if (i + 1 < step) s.classList.add('completed');
        else if (i + 1 === step) s.classList.add('active');
    });

    // Update content
    el.stepContents.forEach((c, i) => {
        c.classList.remove('active');
        if (i + 1 === step) c.classList.add('active');
    });

    // Step-specific init
    if (step === 2) checkStep2Ready();
    if (step === 4) initMap();
    if (step === 5) initGenerateStep();
    if (step === 6) updateFinalSummary();
}

// ==========================================
// STEP 1: LOGIN
// ==========================================

async function handleLogin() {
    const username = el.username.value.trim();
    const password = el.password.value;
    const apiCountry = el.apiCountry.value;
    if (!username || !password || !apiCountry) { showError(el.loginError, el.loginErrorMsg, 'Please fill in all fields.'); return; }

    el.btnLogin.disabled = true;
    el.btnLogin.innerHTML = '<div class="spinner"></div> Connecting...';
    hideEl(el.loginError);

    try {
        const res = await fetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password, country_code: apiCountry }),
        });
        const data = await res.json();
        if (data.success) {
            state.token = data.token;
            state.rootUrl = data.root_url;
            state.brand = data.brand;
            state.apiCountry = apiCountry;

            // Auto-set geo country from the API country
            const countryInfo = COUNTRY_MAP[apiCountry.toLowerCase()];
            if (countryInfo) {
                state.geoCountry = countryInfo.geoCode;
                state.geoCountryName = `${countryInfo.flag} ${countryInfo.name}`;
            } else {
                state.geoCountry = apiCountry.toUpperCase();
                state.geoCountryName = apiCountry.toUpperCase();
            }

            goToStep(2);
        } else {
            showError(el.loginError, el.loginErrorMsg, data.error || 'Login failed.');
        }
    } catch (e) {
        showError(el.loginError, el.loginErrorMsg, 'Connection error. Please try again.');
    } finally {
        el.btnLogin.disabled = false;
        el.btnLogin.innerHTML = 'Connect <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14M12 5l7 7-7 7"/></svg>';
    }
}

// ==========================================
// STEP 2: NODES UPLOAD
// ==========================================

function handleFileDrop(e) {
    e.preventDefault();
    el.uploadArea.classList.remove('dragover');
    const files = e.dataTransfer.files;
    if (files.length > 0) uploadFile(files[0]);
}

function handleFileUpload() {
    if (el.nodesFile.files.length > 0) uploadFile(el.nodesFile.files[0]);
}

async function uploadFile(file) {
    if (!file.name.toLowerCase().endsWith('.csv') && !file.name.toLowerCase().endsWith('.txt')) {
        showError(el.uploadError, el.uploadErrorMsg, 'Please upload a .csv file.');
        return;
    }

    hideEl(el.uploadError);
    hideEl(el.uploadSuccess);

    // Show loading
    el.uploadArea.innerHTML = '<div class="spinner" style="margin: 0 auto;"></div><p class="text-secondary" style="margin-top: 0.5rem;">Processing...</p>';

    const formData = new FormData();
    formData.append('file', file);

    try {
        const res = await fetch('/api/li-project/upload-nodes', { method: 'POST', body: formData });
        const data = await res.json();
        if (data.success) {
            state.nodeKey = data.node_key;
            state.nodeCount = data.count;
            showEl(el.uploadSuccess);
            el.uploadSuccessMsg.textContent = `${data.count.toLocaleString()} nodes loaded from ${file.name}`;
            checkStep2Ready();
        } else {
            showError(el.uploadError, el.uploadErrorMsg, data.error || 'Failed to process CSV.');
        }
    } catch (e) {
        showError(el.uploadError, el.uploadErrorMsg, 'Upload error. Please try again.');
    } finally {
        // Restore upload area
        el.uploadArea.innerHTML = `
            <svg class="upload-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
            <p style="color: var(--text-primary); font-weight: 500; margin-bottom: 0.25rem;">
                ${state.nodeCount > 0 ? '✅ ' + state.nodeCount.toLocaleString() + ' nodes loaded — click to replace' : 'Click or drag a CSV file here'}
            </p>
            <p class="text-muted text-sm">CSV with columns: latitude, longitude (or lat, lon)</p>
            <input type="file" id="nodes-file" accept=".csv,.txt">
        `;
        // Re-attach event
        document.getElementById('nodes-file').addEventListener('change', handleFileUpload);
        el.nodesFile = document.getElementById('nodes-file');
    }
}

function checkStep2Ready() {
    // Nodes are optional — always allow continuing
    el.btnNext2.disabled = false;
}

// ==========================================
// STEP 3: ESTABLISHMENTS
// ==========================================

function handleRadiusChange() {
    const val = parseInt(el.nodeRadius.value);
    if (val && val >= 100 && val <= 5000) {
        state.nodeRadius = val;
        if (el.legendBufferText) {
            el.legendBufferText.textContent = `${val}m buffer`;
        }
    }
}

async function handleSearch() {
    const q = el.searchQuery.value.trim();
    if (!q) return;

    showEl(el.searchProgress);
    hideEl(el.searchResults);
    hideEl(el.searchError);

    try {
        const res = await fetch('/api/li-project/search-establishment', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: q, country_code: state.geoCountry || '', limit: 10 }),
        });
        const data = await res.json();
        if (data.success && data.results.length > 0) {
            renderSearchResults(data.results);
        } else if (data.success) {
            showError(el.searchError, el.searchErrorMsg, 'No results found. Try a different name.');
        } else {
            showError(el.searchError, el.searchErrorMsg, data.error || 'Search failed.');
        }
    } catch (e) {
        showError(el.searchError, el.searchErrorMsg, 'Connection error.');
    } finally {
        hideEl(el.searchProgress);
    }
}

function renderSearchResults(results) {
    el.searchResults.innerHTML = '';
    results.forEach(r => {
        const div = document.createElement('div');
        div.className = 'search-result-item';
        div.innerHTML = `
            <div class="result-name">${r.name}</div>
            <div class="result-meta">Type: ${r.type} | Lat: ${r.lat.toFixed(6)}, Lon: ${r.lon.toFixed(6)}</div>
        `;
        div.addEventListener('click', () => addEstablishmentFromSearch(r));
        el.searchResults.appendChild(div);
    });
    showEl(el.searchResults);
}

async function addEstablishmentFromSearch(result) {
    const customName = prompt('Name for this establishment:', result.name.split(',')[0]);
    if (customName === null) return;

    hideEl(el.searchResults);
    await addEstablishment(result.lat, result.lon, customName || result.name.split(',')[0]);
}

async function handleAddByCoords() {
    const name = el.estNameManual.value.trim();
    const lat = parseFloat(el.estLat.value);
    const lon = parseFloat(el.estLon.value);

    if (!name) { alert('Please enter a name for the establishment.'); return; }
    if (isNaN(lat) || isNaN(lon)) { alert('Please enter valid latitude and longitude.'); return; }

    await addEstablishment(lat, lon, name);

    el.estNameManual.value = '';
    el.estLat.value = '';
    el.estLon.value = '';
}

async function addEstablishment(lat, lon, name) {
    showEl(el.polygonProgress);
    el.polygonProgressText.textContent = state.nodeKey
        ? `Filtering nodes near "${name}"...`
        : `Adding "${name}"...`;

    try {
        let filteredNodes = [];
        let bufferGeojson = null;

        // Only filter nodes if they were uploaded
        if (state.nodeKey) {
            const nodesRes = await fetch('/api/li-project/filter-nodes', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    node_key: state.nodeKey,
                    center_lat: lat,
                    center_lon: lon,
                    radius_m: state.nodeRadius,
                }),
            });
            const nodesData = await nodesRes.json();
            if (nodesData.success) {
                filteredNodes = nodesData.filtered_nodes;
                bufferGeojson = nodesData.buffer_geojson;
            }
        }

        state.establishments.push({ name, lat, lon, polygon: null });
        state.nodesPerEst.push(filteredNodes);
        state.buffers.push(bufferGeojson);

        updateEstablishmentsList();
    } catch (e) {
        console.error('Error adding establishment:', e);
        alert('Error processing establishment. Please try again.');
    } finally {
        hideEl(el.polygonProgress);
    }
}

function updateEstablishmentsList() {
    const count = state.establishments.length;
    el.estCountBadge.textContent = count;
    el.btnNext3.disabled = count === 0;

    if (count === 0) {
        showEl(el.noEstablishments);
        el.establishmentsList.innerHTML = '';
        return;
    }

    hideEl(el.noEstablishments);
    el.establishmentsList.innerHTML = '';

    state.establishments.forEach((est, i) => {
        const name = est.name || `Establishment ${i + 1}`;
        const nodes = state.nodesPerEst[i]?.length || 0;
        const hasPoly = est.polygon ? '✅' : '⬜';
        const div = document.createElement('div');
        div.className = 'establishment-item';
        const hasNodes = state.nodeCount > 0;
        const nodeInfo = hasNodes
            ? ` · ${nodes} nodes in ${state.nodeRadius}m radius`
            : '';
        div.innerHTML = `
            <div class="est-info">
                <div class="est-name">${hasPoly} ${name}</div>
                <div class="est-coords">Lat ${est.lat.toFixed(5)}, Lon ${est.lon.toFixed(5)}${nodeInfo}</div>
            </div>
            <button class="btn-remove" data-index="${i}">✕ Remove</button>
        `;
        div.querySelector('.btn-remove').addEventListener('click', () => removeEstablishment(i));
        el.establishmentsList.appendChild(div);
    });
}

function removeEstablishment(index) {
    state.establishments.splice(index, 1);
    state.nodesPerEst.splice(index, 1);
    state.buffers.splice(index, 1);
    // Remove any buffer polygons for this establishment
    state.bufferPolygons = state.bufferPolygons.filter(bp => bp.estIndex !== index);
    // Adjust estIndex for buffer polygons with higher indices
    state.bufferPolygons.forEach(bp => {
        if (bp.estIndex > index) bp.estIndex--;
    });
    updateEstablishmentsList();
}

// ==========================================
// STEP 4: MAP EDITOR (manual polygon drawing)
// ==========================================

function initMap() {
    if (state.map) {
        state.map.remove();
        state.map = null;
    }

    // Update legend
    if (el.legendBufferText) {
        el.legendBufferText.textContent = `${state.nodeRadius}m buffer`;
    }

    // Determine which establishments still need polygons drawn
    state.pendingDrawQueue = [];
    state.establishments.forEach((est, i) => {
        if (!est.polygon) state.pendingDrawQueue.push(i);
    });

    state.map = L.map('map', {
        center: [0, 0],
        zoom: 2,
    });

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap',
        maxZoom: 19,
    }).addTo(state.map);

    // FeatureGroup for drawn/editable polygons
    state.drawnItems = new L.FeatureGroup();
    state.map.addLayer(state.drawnItems);

    // Draw control — allow polygon drawing + editing
    const drawControl = new L.Control.Draw({
        draw: {
            polygon: {
                allowIntersection: false,
                shapeOptions: {
                    color: '#ec4899',
                    fillColor: '#ec4899',
                    fillOpacity: 0.25,
                    weight: 2,
                },
            },
            polyline: false,
            circle: false,
            rectangle: false,
            circlemarker: false,
            marker: false,
        },
        edit: {
            featureGroup: state.drawnItems,
            edit: { selectedPathOptions: { color: '#ec4899', fillColor: '#ec4899' } },
            remove: true,
        },
    });
    state.map.addControl(drawControl);

    const bounds = L.latLngBounds();

    // Add already-drawn polygons back (if returning to this step)
    state.establishments.forEach((est, i) => {
        if (est.polygon) {
            const geojsonLayer = L.geoJSON(est.polygon, {
                style: { color: '#ec4899', fillColor: '#ec4899', fillOpacity: 0.25, weight: 2 },
            });
            geojsonLayer.eachLayer(l => {
                l._estIndex = i;
                l._isOriginal = true;
                state.drawnItems.addLayer(l);
                if (l.getBounds) bounds.extend(l.getBounds());
            });
        }
    });

    // Add buffer polygons back
    state.bufferPolygons.forEach((bp, bpIdx) => {
        const bufLayer = L.geoJSON(bp.polygon, {
            style: { color: '#a855f7', fillColor: '#a855f7', fillOpacity: 0.15, weight: 2, dashArray: '4 3' },
        });
        bufLayer.eachLayer(l => {
            l._bufferIndex = bpIdx;
            l._isBuffer = true;
            state.drawnItems.addLayer(l);
            l.bindTooltip(bp.name, { permanent: true, direction: 'center', className: 'buffer-tooltip' });
            if (l.getBounds) bounds.extend(l.getBounds());
        });
    });

    // Add establishment center markers (red pins)
    state.markerLayers = [];
    state.establishments.forEach((est, i) => {
        const marker = L.marker([est.lat, est.lon], {
            icon: L.divIcon({
                className: 'est-marker',
                html: `<div style="background:#ec4899;color:white;border-radius:50%;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;box-shadow:0 2px 6px rgba(0,0,0,0.4);">${i + 1}</div>`,
                iconSize: [24, 24],
                iconAnchor: [12, 12],
            }),
        });
        marker.bindTooltip(est.name, { direction: 'top', offset: [0, -14] });
        marker.addTo(state.map);
        state.markerLayers.push(marker);
        bounds.extend([est.lat, est.lon]);
    });

    // Add buffer circles and node markers only if nodes were uploaded
    state.bufferLayers = [];
    if (state.nodeCount > 0) {
        state.buffers.forEach((buf, i) => {
            if (!buf) return;
            const bufLayer = L.geoJSON(buf, {
                style: {
                    color: '#f59e0b',
                    fillColor: 'transparent',
                    fillOpacity: 0,
                    weight: 1.5,
                    dashArray: '6 4',
                },
            });
            bufLayer.addTo(state.map);
            state.bufferLayers.push(bufLayer);
            bufLayer.eachLayer(l => {
                if (l.getBounds) bounds.extend(l.getBounds());
            });
        });

        // Add nodes as small circle markers
        state.nodeMarkers = L.layerGroup();
        const allNodesInBuffers = new Set();
        state.nodesPerEst.forEach(nodeList => {
            nodeList.forEach(n => allNodesInBuffers.add(`${n[0]},${n[1]}`));
        });

        allNodesInBuffers.forEach(key => {
            const [lat, lon] = key.split(',').map(Number);
            L.circleMarker([lat, lon], {
                radius: 3,
                color: '#6366f1',
                fillColor: '#6366f1',
                fillOpacity: 0.7,
                weight: 1,
            }).addTo(state.nodeMarkers);
        });
        state.nodeMarkers.addTo(state.map);
    }

    // Fit bounds
    if (bounds.isValid()) {
        state.map.fitBounds(bounds, { padding: [40, 40] });
    }

    // Update stats & instructions
    updatePolygonStats();

    // Handle newly drawn polygons → assign to next pending establishment
    state.map.on(L.Draw.Event.CREATED, (e) => {
        const layer = e.layer;
        state.drawnItems.addLayer(layer);

        if (state.pendingDrawQueue.length > 0) {
            const estIdx = state.pendingDrawQueue.shift();
            layer._estIndex = estIdx;
            layer._isOriginal = true;
            const geojson = layer.toGeoJSON();
            geojson.properties = { name: state.establishments[estIdx].name, poly_type: 'core' };
            state.establishments[estIdx].polygon = geojson;
            layer.bindTooltip(state.establishments[estIdx].name, { permanent: true, direction: 'center' });

            // Show buffer creation option
            showBufferCreationButton(estIdx, layer);
        }

        updatePolygonStats();
    });

    // Handle polygon edits → sync back
    state.map.on(L.Draw.Event.EDITED, (e) => {
        e.layers.eachLayer(layer => {
            if (layer._estIndex !== undefined && layer._isOriginal) {
                const geojson = layer.toGeoJSON();
                geojson.properties = { name: state.establishments[layer._estIndex].name, poly_type: 'core' };
                state.establishments[layer._estIndex].polygon = geojson;
            }
        });
        updatePolygonStats();
    });

    // Handle polygon deletion
    state.map.on(L.Draw.Event.DELETED, (e) => {
        e.layers.eachLayer(layer => {
            if (layer._estIndex !== undefined && layer._isOriginal) {
                state.establishments[layer._estIndex].polygon = null;
                state.pendingDrawQueue.push(layer._estIndex);
                state.pendingDrawQueue.sort((a, b) => a - b);
                // Remove associated buffer polygons
                state.bufferPolygons = state.bufferPolygons.filter(bp => bp.estIndex !== layer._estIndex);
            }
            if (layer._isBuffer && layer._bufferIndex !== undefined) {
                state.bufferPolygons.splice(layer._bufferIndex, 1);
            }
        });
        updatePolygonStats();
    });
}

// ==========================================
// BUFFER POLYGON CREATION
// ==========================================

function showBufferCreationButton(estIdx, layer) {
    const est = state.establishments[estIdx];
    const popupContent = document.createElement('div');
    popupContent.innerHTML = `
        <div style="text-align:center; padding: 4px;">
            <strong>${est.name}</strong><br>
            <button class="btn-create-buffers" style="
                margin-top: 8px;
                padding: 6px 14px;
                background: linear-gradient(135deg, #a855f7, #6366f1);
                color: white;
                border: none;
                border-radius: 6px;
                cursor: pointer;
                font-size: 0.8rem;
                font-weight: 600;
            ">🔲 Create Buffers</button>
        </div>
    `;
    popupContent.querySelector('.btn-create-buffers').addEventListener('click', () => {
        state.map.closePopup();
        openBufferModal(estIdx);
    });
    layer.bindPopup(popupContent).openPopup();
}

function openBufferModal(estIdx) {
    const est = state.establishments[estIdx];

    // Create modal overlay
    const overlay = document.createElement('div');
    overlay.className = 'buffer-modal-overlay';
    overlay.innerHTML = `
        <div class="buffer-modal">
            <h3>🔲 Create Buffer Polygons</h3>
            <p class="text-secondary" style="margin-bottom: 1rem; font-size: 0.9rem;">
                Create buffer polygons around <strong>${est.name}</strong>. Each buffer will expand the polygon outline by the specified distance.
            </p>
            <div id="buffer-rows">
                <div class="buffer-row">
                    <span class="text-secondary" style="min-width: 60px;">Buffer 1:</span>
                    <input type="number" class="form-input buffer-distance" value="50" min="10" max="5000" step="10" placeholder="meters">
                    <span class="text-muted">m</span>
                </div>
            </div>
            <div style="margin: 1rem 0; display: flex; gap: 0.5rem;">
                <button class="btn btn-ghost" id="btn-add-buffer-row" style="font-size: 0.85rem;">+ Add Buffer</button>
            </div>
            <div style="display: flex; gap: 0.75rem; justify-content: flex-end; margin-top: 1.5rem;">
                <button class="btn btn-secondary" id="btn-cancel-buffer">Cancel</button>
                <button class="btn btn-primary" id="btn-confirm-buffer">Create Buffers</button>
            </div>
        </div>
    `;

    document.body.appendChild(overlay);

    // Add buffer row button
    overlay.querySelector('#btn-add-buffer-row').addEventListener('click', () => {
        const rows = overlay.querySelector('#buffer-rows');
        const count = rows.children.length + 1;
        const row = document.createElement('div');
        row.className = 'buffer-row';
        row.innerHTML = `
            <span class="text-secondary" style="min-width: 60px;">Buffer ${count}:</span>
            <input type="number" class="form-input buffer-distance" value="${count * 50}" min="10" max="5000" step="10" placeholder="meters">
            <span class="text-muted">m</span>
            <button class="btn-remove-buffer">✕</button>
        `;
        row.querySelector('.btn-remove-buffer').addEventListener('click', () => row.remove());
        rows.appendChild(row);
    });

    // Cancel
    overlay.querySelector('#btn-cancel-buffer').addEventListener('click', () => {
        overlay.remove();
    });

    // Confirm
    overlay.querySelector('#btn-confirm-buffer').addEventListener('click', async () => {
        const distances = [];
        overlay.querySelectorAll('.buffer-distance').forEach(input => {
            const val = parseInt(input.value);
            if (val && val > 0) distances.push(val);
        });

        if (distances.length === 0) {
            alert('Please enter at least one buffer distance.');
            return;
        }

        // Disable button
        const confirmBtn = overlay.querySelector('#btn-confirm-buffer');
        confirmBtn.disabled = true;
        confirmBtn.innerHTML = '<div class="spinner" style="width:16px;height:16px;"></div> Creating...';

        try {
            await createBufferPolygons(estIdx, distances);
            overlay.remove();
        } catch (e) {
            console.error('Error creating buffers:', e);
            alert('Error creating buffer polygons. Please try again.');
            confirmBtn.disabled = false;
            confirmBtn.textContent = 'Create Buffers';
        }
    });

    // Close on overlay click (not modal)
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) overlay.remove();
    });
}

async function createBufferPolygons(estIdx, distances) {
    const est = state.establishments[estIdx];
    if (!est.polygon) return;

    const res = await fetch('/api/li-project/buffer-polygon', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            geometry: est.polygon.geometry,
            distances: distances,
        }),
    });
    const data = await res.json();
    if (!data.success) {
        throw new Error(data.error || 'Failed to create buffer polygons');
    }

    // Remove existing buffer polygons for this establishment first
    state.bufferPolygons = state.bufferPolygons.filter(bp => bp.estIndex !== estIdx);

    // Add buffer polygons to state and map
    data.buffers.forEach((bufGeo, i) => {
        const distance = distances[i];
        const bufferFeature = {
            type: 'Feature',
            properties: {
                id: `AOI-${estIdx + 1}-${distance}`,
                name: `${est.name} - ${distance}m`,
                poly_type: 'core',
            },
            geometry: bufGeo,
        };

        const bpEntry = {
            estIndex: estIdx,
            distance: distance,
            polygon: bufferFeature,
            name: `${est.name} - ${distance}m`,
            id: `AOI-${estIdx + 1}-${distance}`,
        };
        state.bufferPolygons.push(bpEntry);

        // Add to map
        const bufLayer = L.geoJSON(bufferFeature, {
            style: { color: '#a855f7', fillColor: '#a855f7', fillOpacity: 0.15, weight: 2, dashArray: '4 3' },
        });
        bufLayer.eachLayer(l => {
            l._bufferIndex = state.bufferPolygons.length - 1;
            l._isBuffer = true;
            state.drawnItems.addLayer(l);
            l.bindTooltip(bpEntry.name, { permanent: true, direction: 'center', className: 'buffer-tooltip' });
        });
    });

    updatePolygonStats();
}

function syncPolygonsFromMap() {
    // Sync all drawn items back to state
    state.drawnItems.eachLayer(layer => {
        if (layer._estIndex !== undefined && layer._isOriginal) {
            const geojson = layer.toGeoJSON();
            geojson.properties = { name: state.establishments[layer._estIndex].name, poly_type: 'core' };
            state.establishments[layer._estIndex].polygon = geojson;
        }
    });
}

// ==========================================
// POLYGON STATS - Node counts per polygon
// ==========================================

function countNodesInPolygon(polygonFeature, nodesForEst) {
    if (!polygonFeature || !nodesForEst || nodesForEst.length === 0) return 0;

    // Use Turf.js for point-in-polygon if available
    if (typeof turf !== 'undefined') {
        let count = 0;
        const poly = turf.feature(polygonFeature.geometry);
        for (const node of nodesForEst) {
            const pt = turf.point([node[1], node[0]]); // [lon, lat]
            if (turf.booleanPointInPolygon(pt, poly)) {
                count++;
            }
        }
        return count;
    }

    // Fallback: simple ray-casting point-in-polygon
    const coords = polygonFeature.geometry.coordinates[0]; // outer ring
    let count = 0;
    for (const node of nodesForEst) {
        if (pointInPolygon([node[1], node[0]], coords)) {
            count++;
        }
    }
    return count;
}

function pointInPolygon(point, polygon) {
    const [x, y] = point;
    let inside = false;
    for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
        const xi = polygon[i][0], yi = polygon[i][1];
        const xj = polygon[j][0], yj = polygon[j][1];
        const intersect = ((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi) + xi);
        if (intersect) inside = !inside;
    }
    return inside;
}

function updatePolygonStats() {
    const pending = state.establishments.filter(e => !e.polygon).length;
    const drawn = state.establishments.filter(e => e.polygon).length;
    const total = state.establishments.length;
    const hasNodes = state.nodeCount > 0;

    // Collect unique nodes for per-polygon counting (only if nodes were uploaded)
    let uniqueNodes = [];
    if (hasNodes) {
        const nodeSet = new Map();
        state.nodesPerEst.forEach(nodeList => {
            nodeList.forEach(n => nodeSet.set(`${n[0]},${n[1]}`, n));
        });
        uniqueNodes = Array.from(nodeSet.values());
    }

    let html = '';
    if (pending > 0) {
        const nextIdx = state.pendingDrawQueue[0];
        const nextName = nextIdx !== undefined ? state.establishments[nextIdx].name : '?';
        html += `<strong style="color:var(--warning)">⏳ ${pending} polygon(s) to draw.</strong> `;
        html += `Next: draw polygon for <strong>${nextName}</strong>. Use the polygon tool in the toolbar above the map.<br>`;
    }
    if (drawn > 0) {
        html += `✅ ${drawn}/${total} establishment polygons drawn.<br>`;
    }

    // Show per-polygon info
    state.establishments.forEach((est, i) => {
        const status = est.polygon ? '✅' : '⬜';
        if (est.polygon) {
            if (hasNodes) {
                const nodesInPoly = countNodesInPolygon(est.polygon, uniqueNodes);
                html += `${status} <strong>${est.name}</strong>: ${nodesInPoly} nodes<br>`;
            } else {
                html += `${status} <strong>${est.name}</strong><br>`;
            }
        } else {
            html += `${status} <strong>${est.name}</strong>: polygon not drawn yet<br>`;
        }

        // Show buffer polygon info
        const estBuffers = state.bufferPolygons.filter(bp => bp.estIndex === i);
        estBuffers.sort((a, b) => a.distance - b.distance);
        estBuffers.forEach(bp => {
            if (hasNodes) {
                const nodesInBuf = countNodesInPolygon(bp.polygon, uniqueNodes);
                html += `&nbsp;&nbsp;&nbsp;&nbsp;↳ <strong>${bp.name}</strong>: ${nodesInBuf} nodes<br>`;
            } else {
                html += `&nbsp;&nbsp;&nbsp;&nbsp;↳ <strong>${bp.name}</strong><br>`;
            }
        });
    });

    el.polygonStatsMsg.innerHTML = html;
    showEl(el.polygonStats);

    // Disable continue if not all polygons drawn
    el.btnNext4.disabled = pending > 0;
}

// ==========================================
// STEP 5: GENERATE
// ==========================================

async function initGenerateStep() {
    // Sync polygons from map one last time
    if (state.map) syncPolygonsFromMap();

    // Load regions for selected country
    el.genRegion.innerHTML = '<option value="">Loading regions...</option>';
    el.genRegion.disabled = true;
    el.genCity.innerHTML = '<option value="">Select a region first...</option>';
    el.genCity.disabled = true;
    el.btnGenerate.disabled = true;

    hideEl(el.genError);

    try {
        const res = await fetch(`/api/aoi/regions/${state.geoCountry}`);
        const regions = await res.json();
        el.genRegion.innerHTML = '<option value="">Select a region...</option>';
        regions.forEach(r => {
            el.genRegion.innerHTML += `<option value="${r.code}">${r.name}</option>`;
        });
        el.genRegion.disabled = false;
    } catch (e) {
        el.genRegion.innerHTML = '<option value="">Error loading regions</option>';
    }

    updateGenSummary();
}

async function handleRegionChange() {
    const regionCode = el.genRegion.value;
    el.genCity.innerHTML = '<option value="">Loading municipalities...</option>';
    el.genCity.disabled = true;
    el.btnGenerate.disabled = true;

    if (!regionCode) {
        el.genCity.innerHTML = '<option value="">Select a region first...</option>';
        return;
    }

    state.region = regionCode;
    state.regionName = el.genRegion.options[el.genRegion.selectedIndex]?.text || '';

    try {
        const res = await fetch(`/api/aoi/municipalities/${state.geoCountry}/${regionCode}`);
        const data = await res.json();
        el.genCity.innerHTML = '<option value="">Select a municipality...</option>';
        data.municipalities.forEach(name => {
            el.genCity.innerHTML += `<option value="${name}">${name}</option>`;
        });
        el.genCity.disabled = false;
    } catch (e) {
        el.genCity.innerHTML = '<option value="">Error loading municipalities</option>';
    }

    updateGenSummary();
}

function handleCityChange() {
    state.city = el.genCity.value;
    el.btnGenerate.disabled = !state.city;
    updateGenSummary();
}

function updateGenSummary() {
    const estNames = state.establishments.map(e => e.name || '?').join(', ');
    const bufCount = state.bufferPolygons.length;
    el.genSummary.innerHTML = `
        <strong>Country:</strong> ${state.geoCountryName || '-'}<br>
        <strong>Region:</strong> ${state.regionName || '-'}<br>
        <strong>City:</strong> ${state.city || '-'}<br>
        <strong>Establishments (${state.establishments.length}):</strong> ${estNames || '-'}
        ${bufCount > 0 ? `<br><strong>Buffer polygons:</strong> ${bufCount}` : ''}
    `;
}

async function handleGenerate() {
    if (!state.city) return;

    showEl(el.genProgress);
    hideEl(el.genError);
    el.btnGenerate.disabled = true;

    try {
        // Extract polygon GeoJSON Features from state (original + buffers)
        const estFeatures = state.establishments
            .filter(e => e.polygon)
            .map(e => e.polygon);

        // Add buffer polygon features
        const bufferFeatures = state.bufferPolygons.map(bp => bp.polygon);
        const allFeatures = [...estFeatures, ...bufferFeatures];

        const res = await fetch('/api/li-project/generate-project', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                establishments: allFeatures,
                country_code: state.geoCountry,
                region_code: state.region,
                city_name: state.city,
            }),
        });
        const data = await res.json();

        if (data.success) {
            state.geojson = data.geojson;
            state.filename = data.filename;
            state.featureCount = data.feature_count;
            goToStep(6);
        } else {
            showError(el.genError, el.genErrorMsg, data.error || 'Failed to generate project.');
            el.btnGenerate.disabled = false;
        }
    } catch (e) {
        showError(el.genError, el.genErrorMsg, 'Connection error.');
        el.btnGenerate.disabled = false;
    } finally {
        hideEl(el.genProgress);
    }
}

// ==========================================
// STEP 6: FINISH
// ==========================================

function updateFinalSummary() {
    const estNames = state.establishments.map(e => e.name || '?').join(', ');
    el.finalSummary.innerHTML =
        `<strong>${state.city}</strong> (${state.regionName}, ${state.geoCountryName})<br>` +
        `${state.featureCount} features generated. Establishments: ${estNames}<br>` +
        `Ready to download or create in platform.`;
    el.projectName.value = `LI - ${estNames.substring(0, 50)} / ${state.city}`;
    hideEl(el.createSuccess);
    hideEl(el.createError);
}

function handleDownload() {
    if (!state.geojson) return;
    const str = JSON.stringify(state.geojson, null, 2);
    const blob = new Blob([str], { type: 'application/geo+json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = state.filename || 'project.geojson';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

async function handleCreateCloud() {
    const name = el.projectName.value.trim();
    const desc = el.projectDescription.value.trim();
    if (!name) { showError(el.createError, el.createErrorMsg, 'Please enter a project name.'); return; }

    showEl(el.createProgress);
    hideEl(el.createSuccess);
    hideEl(el.createError);
    el.btnCreateCloud.disabled = true;
    el.createStatus.textContent = 'Validating GeoJSON...';

    try {
        const res = await fetch('/api/create-project', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                token: state.token,
                root_url: state.rootUrl,
                name: name,
                description: desc,
                geojson: state.geojson,
            }),
        });
        const data = await res.json();
        if (data.success) {
            state.projectId = data.project_id;
            showEl(el.createSuccess);
            el.createSuccessMsg.textContent = `Project created successfully! ID: ${data.project_id}`;
            el.btnCreateCloud.disabled = true;
        } else {
            showError(el.createError, el.createErrorMsg, data.error || 'Failed to create project.');
            el.btnCreateCloud.disabled = false;
        }
    } catch (e) {
        showError(el.createError, el.createErrorMsg, 'Connection error.');
        el.btnCreateCloud.disabled = false;
    } finally {
        hideEl(el.createProgress);
    }
}

// ==========================================
// UTILITIES
// ==========================================

function showEl(el) { el.classList.remove('hidden'); }
function hideEl(el) { el.classList.add('hidden'); }
function showError(container, msgEl, msg) { container.classList.remove('hidden'); msgEl.textContent = msg; }

function resetWizard() {
    state.nodeKey = null;
    state.nodeCount = 0;
    state.establishments = [];
    state.buffers = [];
    state.nodesPerEst = [];
    state.bufferPolygons = [];
    state.region = null;
    state.regionName = null;
    state.city = null;
    state.geojson = null;
    state.filename = null;
    state.featureCount = 0;
    state.projectId = null;
    state.nodeRadius = 1000;

    if (state.map) { state.map.remove(); state.map = null; }

    el.btnNext2.disabled = true;
    el.btnNext3.disabled = true;
    hideEl(el.uploadSuccess);
    hideEl(el.uploadError);
    hideEl(el.createSuccess);
    hideEl(el.createError);
    el.nodeRadius.value = '1000';
    updateEstablishmentsList();
    goToStep(2);
}
