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
    nodes: [],          // [[lat, lon], ...]
    nodeCount: 0,
    geoCountry: null,
    geoCountryName: null,

    // Establishments
    establishments: [],  // Array of GeoJSON Feature dicts
    buffers: [],         // Array of buffer GeoJSON Feature dicts
    nodesPerEst: [],     // Array of arrays of [lat, lon]

    // Map
    map: null,
    drawnItems: null,
    nodeMarkers: null,
    bufferLayers: [],
    polygonLayers: [],

    // Generation
    region: null,
    regionName: null,
    city: null,
    geojson: null,
    filename: null,
    featureCount: 0,
    projectId: null,
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
    geoCountry: document.getElementById('geo-country'),
    uploadArea: document.getElementById('upload-area'),
    nodesFile: document.getElementById('nodes-file'),
    uploadSuccess: document.getElementById('upload-success'),
    uploadSuccessMsg: document.getElementById('upload-success-message'),
    uploadError: document.getElementById('upload-error'),
    uploadErrorMsg: document.getElementById('upload-error-message'),
    btnBack1: document.getElementById('btn-back-1'),
    btnNext2: document.getElementById('btn-next-2'),

    // Step 3
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
    loadCountries();
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
    el.geoCountry.addEventListener('change', handleGeoCountryChange);

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
    if (step === 4) initMap();
    if (step === 5) initGenerateStep();
    if (step === 6) updateFinalSummary();
}

// ==========================================
// COUNTRIES
// ==========================================

async function loadCountries() {
    try {
        const res = await fetch('/api/aoi/countries');
        const countries = await res.json();
        el.geoCountry.innerHTML = '<option value="">Select a country...</option>';
        countries.forEach(c => {
            const flag = { BR: '🇧🇷', PT: '🇵🇹', ES: '🇪🇸', MX: '🇲🇽', CL: '🇨🇱' }[c.code] || '🌍';
            el.geoCountry.innerHTML += `<option value="${c.code}">${flag} ${c.name}</option>`;
        });
    } catch (e) {
        el.geoCountry.innerHTML = '<option value="">Error loading countries</option>';
    }
}

function handleGeoCountryChange() {
    state.geoCountry = el.geoCountry.value;
    state.geoCountryName = el.geoCountry.options[el.geoCountry.selectedIndex]?.text || '';
    checkStep2Ready();
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
            state.nodes = data.nodes;
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
    el.btnNext2.disabled = !(state.geoCountry && state.nodeCount > 0);
}

// ==========================================
// STEP 3: ESTABLISHMENTS
// ==========================================

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
    // Ask for custom name via prompt (simple approach)
    const customName = prompt('Name for this establishment:', result.name.split(',')[0]);
    if (customName === null) return; // cancelled

    hideEl(el.searchResults);
    await fetchAndAddPolygon(result.lat, result.lon, customName || result.name.split(',')[0]);
}

async function handleAddByCoords() {
    const name = el.estNameManual.value.trim();
    const lat = parseFloat(el.estLat.value);
    const lon = parseFloat(el.estLon.value);

    if (!name) { alert('Please enter a name for the establishment.'); return; }
    if (isNaN(lat) || isNaN(lon)) { alert('Please enter valid latitude and longitude.'); return; }

    await fetchAndAddPolygon(lat, lon, name);

    // Clear fields
    el.estNameManual.value = '';
    el.estLat.value = '';
    el.estLon.value = '';
}

async function fetchAndAddPolygon(lat, lon, name) {
    showEl(el.polygonProgress);
    el.polygonProgressText.textContent = `Fetching building polygon for "${name}"...`;

    try {
        const res = await fetch('/api/li-project/get-establishment-polygon', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lat, lon, custom_name: name, radius: 50 }),
        });
        const data = await res.json();

        let feature;
        if (data.success && data.feature) {
            feature = data.feature;
        } else {
            // Create a small buffer polygon as fallback
            console.warn('No polygon found, creating circular buffer.');
            feature = createFallbackPolygon(lat, lon, name);
        }

        // Filter nodes in buffer
        const nodesRes = await fetch('/api/li-project/filter-nodes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                nodes: state.nodes,
                center_lat: lat,
                center_lon: lon,
                radius_m: 500,
            }),
        });
        const nodesData = await nodesRes.json();

        state.establishments.push(feature);
        state.nodesPerEst.push(nodesData.success ? nodesData.filtered_nodes : []);
        state.buffers.push(nodesData.success ? nodesData.buffer_geojson : null);

        updateEstablishmentsList();

    } catch (e) {
        console.error('Error adding establishment:', e);
        alert('Error fetching polygon. Please try again.');
    } finally {
        hideEl(el.polygonProgress);
    }
}

function createFallbackPolygon(lat, lon, name) {
    // Create a simple circular polygon (~30m radius) as fallback
    const r = 0.0003; // ~30m in degrees
    const coords = [];
    for (let i = 0; i <= 32; i++) {
        const angle = (i / 32) * 2 * Math.PI;
        coords.push([lon + r * Math.cos(angle), lat + r * Math.sin(angle)]);
    }
    return {
        type: 'Feature',
        properties: { id: 'manual', name: name, poly_type: 'core' },
        geometry: { type: 'Polygon', coordinates: [coords] },
    };
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
        const name = est.properties?.name || `Establishment ${i + 1}`;
        const nodes = state.nodesPerEst[i]?.length || 0;
        const div = document.createElement('div');
        div.className = 'establishment-item';
        div.innerHTML = `
            <div class="est-info">
                <div class="est-name">${name}</div>
                <div class="est-coords">${nodes} nodes within 500m buffer</div>
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
    updateEstablishmentsList();
}

// ==========================================
// STEP 4: MAP EDITOR
// ==========================================

function initMap() {
    if (state.map) {
        state.map.remove();
        state.map = null;
    }

    state.map = L.map('map', {
        center: [0, 0],
        zoom: 2,
    });

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap',
        maxZoom: 19,
    }).addTo(state.map);

    // FeatureGroup for editable polygons
    state.drawnItems = new L.FeatureGroup();
    state.map.addLayer(state.drawnItems);

    // Draw control (edit only, no new shapes)
    const drawControl = new L.Control.Draw({
        draw: false,
        edit: {
            featureGroup: state.drawnItems,
            edit: { selectedPathOptions: { color: '#ec4899', fillColor: '#ec4899' } },
            remove: false,
        },
    });
    state.map.addControl(drawControl);

    // Add establishment polygons (editable)
    const bounds = L.latLngBounds();
    state.polygonLayers = [];

    state.establishments.forEach((est, i) => {
        const geojsonLayer = L.geoJSON(est, {
            style: {
                color: '#ec4899',
                fillColor: '#ec4899',
                fillOpacity: 0.25,
                weight: 2,
            },
            onEachFeature: (feature, layer) => {
                const name = feature.properties?.name || `Est. ${i + 1}`;
                layer.bindTooltip(name, { permanent: true, direction: 'center', className: 'polygon-tooltip' });
            },
        });

        geojsonLayer.eachLayer(l => {
            state.drawnItems.addLayer(l);
            state.polygonLayers.push({ index: i, layer: l });
            if (l.getBounds) bounds.extend(l.getBounds());
        });
    });

    // Add buffer circles (non-editable, dashed)
    state.bufferLayers = [];
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

    // Fit bounds
    if (bounds.isValid()) {
        state.map.fitBounds(bounds, { padding: [40, 40] });
    }

    // Update stats
    updatePolygonStats();

    // Handle polygon edits
    state.map.on(L.Draw.Event.EDITED, () => {
        // Sync edited polygons back to state
        syncPolygonsFromMap();
        updatePolygonStats();
    });
}

function syncPolygonsFromMap() {
    state.polygonLayers.forEach(({ index, layer }) => {
        const geojson = layer.toGeoJSON();
        // Preserve original properties
        geojson.properties = {
            ...state.establishments[index].properties,
        };
        state.establishments[index] = geojson;
    });
}

function updatePolygonStats() {
    const lines = state.establishments.map((est, i) => {
        const name = est.properties?.name || `Est. ${i + 1}`;
        const nodes = state.nodesPerEst[i]?.length || 0;
        return `<strong>${name}</strong>: ${nodes} nodes in buffer`;
    });
    el.polygonStatsMsg.innerHTML = lines.join('<br>');
    showEl(el.polygonStats);
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
    const estNames = state.establishments.map(e => e.properties?.name || '?').join(', ');
    el.genSummary.innerHTML = `
        <strong>Country:</strong> ${state.geoCountryName || '-'}<br>
        <strong>Region:</strong> ${state.regionName || '-'}<br>
        <strong>City:</strong> ${state.city || '-'}<br>
        <strong>Establishments (${state.establishments.length}):</strong> ${estNames || '-'}
    `;
}

async function handleGenerate() {
    if (!state.city) return;

    showEl(el.genProgress);
    hideEl(el.genError);
    el.btnGenerate.disabled = true;

    try {
        const res = await fetch('/api/li-project/generate-project', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                establishments: state.establishments,
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
    const estNames = state.establishments.map(e => e.properties?.name || '?').join(', ');
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
    state.nodes = [];
    state.nodeCount = 0;
    state.establishments = [];
    state.buffers = [];
    state.nodesPerEst = [];
    state.region = null;
    state.regionName = null;
    state.city = null;
    state.geojson = null;
    state.filename = null;
    state.featureCount = 0;
    state.projectId = null;

    if (state.map) { state.map.remove(); state.map = null; }

    el.geoCountry.value = '';
    el.btnNext2.disabled = true;
    el.btnNext3.disabled = true;
    hideEl(el.uploadSuccess);
    hideEl(el.uploadError);
    hideEl(el.createSuccess);
    hideEl(el.createError);
    updateEstablishmentsList();
    goToStep(2);
}
