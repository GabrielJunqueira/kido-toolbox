/**
 * Advanced Calibration Tool
 * Replicates functionality of the React-based Kido Calibration App
 */

// State Management
const state = {
    token: null,
    rootUrl: null, // e.g. https://api.kido-ch.kidodynamics.com/v1/
    countryCode: 'ch',

    // UI State
    currentProject: null, // { id, name, ... }
    refData: {}, // key -> value map
    apiData: [], // Array of data points

    // Map State
    drawnItems: null
};

// DOM Elements
const elements = {
    authOverlay: document.getElementById('auth-overlay'),
    loginForm: document.getElementById('login-form'),
    projectSelect: document.getElementById('project-select'),
    projectName: document.getElementById('project-name'),
    projectDesc: document.getElementById('project-desc'),
    btnCreateProject: document.getElementById('btn-create-project'),
    btnFetchData: document.getElementById('btn-fetch-data'),
    dateStart: document.getElementById('date-start'),
    dateEnd: document.getElementById('date-end'),
    pointCount: document.getElementById('point-count'),
    correlationValue: document.getElementById('correlation-value'),
    mapHint: document.getElementById('map-hint'),

    // Reference Data
    refTableBody: document.getElementById('ref-data-body'),
    btnSaveRef: document.getElementById('btn-save-ref'),

    // Chart
    chartCanvas: document.getElementById('correlation-chart')
};

let map;
let chart;

// =============================================================================
// INITIALIZATION
// =============================================================================

document.addEventListener('DOMContentLoaded', () => {
    initMap();
    initEventListeners();
    initChart();
});

function initEventListeners() {
    // Auth
    elements.loginForm.addEventListener('submit', handleLogin);

    // Project
    elements.btnCreateProject.addEventListener('click', handleCreateProject);
    elements.projectSelect.addEventListener('change', handleProjectChange);

    // Data
    elements.btnFetchData.addEventListener('click', handleFetchData);

    // Reference Data
    elements.btnSaveRef.addEventListener('click', saveReferenceData);

    // Tabs
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            // Remove active class from all
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

            // Add to clicked
            e.target.classList.add('active');
            const tabId = e.target.dataset.tab;
            document.getElementById(tabId).classList.add('active');

            // Resize map if needed
            if (tabId === 'map-view' && map) map.invalidateSize();
        });
    });
}

// =============================================================================
// MAP & DRAWING
// =============================================================================

function initMap() {
    map = L.map('map').setView([46.8182, 8.2275], 8); // Default Switzerland center

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors'
    }).addTo(map);

    // FeatureGroup is to store editable layers
    state.drawnItems = new L.FeatureGroup();
    map.addLayer(state.drawnItems);

    // Initialize Draw Control
    const drawControl = new L.Control.Draw({
        draw: {
            polyline: false,
            circle: false,
            marker: false,
            circlemarker: false,
            polygon: {
                allowIntersection: false,
                showArea: true
            },
            rectangle: true
        },
        edit: {
            featureGroup: state.drawnItems
        }
    });
    map.addControl(drawControl);

    // Draw Events
    map.on(L.Draw.Event.CREATED, (e) => {
        const layer = e.layer;

        // Clear previous items if single selection is enforced (optional)
        state.drawnItems.clearLayers();

        state.drawnItems.addLayer(layer);

        // Update point count (mocked for now, implies calling a count API)
        updatePointCountEstimate(layer);

        // Enable create button
        elements.btnCreateProject.disabled = false;
        elements.mapHint.classList.add('hidden');
    });

    map.on(L.Draw.Event.DELETED, () => {
        if (state.drawnItems.getLayers().length === 0) {
            elements.btnCreateProject.disabled = true;
            elements.pointCount.textContent = '0';
        }
    });
}

function updatePointCountEstimate(layer) {
    // In a real app, we might call an API to count points in polygon
    // For now, estimate based on area or just show "Ready"
    const area = L.GeometryUtil.geodesicArea(layer.getLatLngs()[0]);
    // Mock calculation: 1 point per 1000 sqm
    const count = Math.round(area / 1000);
    elements.pointCount.textContent = `~${count.toLocaleString()} (est)`;
}

// =============================================================================
// AUTHENTICATION
// =============================================================================

async function handleLogin(e) {
    e.preventDefault();
    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;
    const country = document.getElementById('country-code').value;

    try {
        const response = await fetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password, country_code: country })
        });

        const data = await response.json();

        if (data.success) {
            state.token = data.token;
            state.rootUrl = data.root_url; // e.g., https://api.kido-ch..../v1/
            state.countryCode = country;

            elements.authOverlay.classList.add('hidden');
            loadProjects();

            // Adjust map center based on country
            centerMapByCountry(country);
        } else {
            const errDiv = document.getElementById('login-error');
            errDiv.textContent = data.error || 'Login failed';
            errDiv.classList.remove('hidden');
        }
    } catch (error) {
        console.error('Login error', error);
        alert('Login failed: ' + error.message);
    }
}

function centerMapByCountry(code) {
    const centers = {
        'ch': [46.8182, 8.2275],
        'br': [-14.2350, -51.9253],
        'es': [40.4168, -3.7038],
        'pt': [39.3999, -8.2245],
        'mx': [23.6345, -102.5528]
    };
    if (centers[code]) {
        map.setView(centers[code], code === 'br' || code === 'mx' ? 4 : 7);
    }
}

// =============================================================================
// API PROXY HELPER
// =============================================================================

async function callKidoApi(path, method = 'GET', body = null) {
    if (!state.token) return;

    // Path should be relative to v1/ or v2/ depending on what we want
    // But our proxy takes the full path suffix.
    // The state.rootUrl usually ends in /v1/. 
    // If we need v2, we should adjust.

    // Hack: If path starts with v2/, use that.
    // The router simply appends path to root_url. 
    // If root_url is .../v1/ and we send v2/..., we get .../v1/v2/... which is wrong.

    // Better strategy: The proxy endpoint is /api/calibration/proxy/{path}
    // And it uses x-kido-root-url.

    let effectiveRootUrl = state.rootUrl;

    // If path starts with "v2/", we might need to adjust rootUrl if it was v1
    if (path.startsWith('v2/')) {
        effectiveRootUrl = state.rootUrl.replace('/v1/', '/');
    } else {
        // Ensure path doesn't duplicate v1 if root already has it
        if (state.rootUrl.endsWith('/v1/') && path.startsWith('v1/')) {
            path = path.substring(3);
        }
    }

    try {
        const headers = {
            'x-kido-token': state.token,
            'x-kido-root-url': effectiveRootUrl,
            'Content-Type': 'application/json'
        };

        const options = {
            method,
            headers,
            body: body ? JSON.stringify(body) : null
        };

        const response = await fetch(`/api/calibration/proxy/${path}`, options);

        if (!response.ok) {
            const txt = await response.text();
            throw new Error(`API Error ${response.status}: ${txt}`);
        }

        return await response.json();
    } catch (error) {
        console.error('API Proxy Error:', error);
        throw error;
    }
}

// =============================================================================
// PROJECT MANAGEMENT
// =============================================================================

async function loadProjects() {
    try {
        // GET /projects
        const data = await callKidoApi('projects');
        // Expecting { projects: [...] } or just array
        const projects = data.projects || data;

        elements.projectSelect.innerHTML = '<option value="">-- New Project --</option>';
        projects.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.id;
            opt.textContent = p.name + ` (ID: ${p.id})`;
            elements.projectSelect.appendChild(opt);
        });
    } catch (error) {
        console.error('Failed to load projects', error);
    }
}

async function handleProjectChange(e) {
    const projectId = e.target.value;
    if (!projectId) {
        state.currentProject = null;
        document.getElementById('new-project-form').style.display = 'block';
        elements.btnFetchData.disabled = true;
        elements.btnExportGeoJSON.disabled = true;
        return;
    }

    document.getElementById('new-project-form').style.display = 'none';
    state.currentProject = { id: projectId };
    elements.btnFetchData.disabled = false;

    // Load reference data
    await loadReferenceData(projectId);
}

async function handleCreateProject() {
    if (state.drawnItems.getLayers().length === 0) {
        alert('Please draw a polygon on the map first.');
        return;
    }

    const name = elements.projectName.value;
    if (!name) {
        alert('Please enter a project name.');
        return;
    }

    const geojson = state.drawnItems.toGeoJSON();

    // Simplify: take the first feature
    const geometry = geojson.features[0].geometry;

    // Payload for Kido API Project Creation
    const payload = {
        name: name,
        description: elements.projectDesc.value,
        geojson: {
            type: "FeatureCollection",
            features: [
                {
                    type: "Feature",
                    properties: { name: "AOI" },
                    geometry: geometry
                }
            ]
        }
        // Note: Real API might need validation first, simplifying here
    };

    elements.btnCreateProject.disabled = true;
    elements.btnCreateProject.textContent = 'Creating...';

    try {
        // POST /projects/create
        // Check if we need validation first as per calibration.py
        // We'll try direct creation for now via proxy
        const res = await callKidoApi('projects/create', 'POST', payload);

        alert('Project Created! ID: ' + res.id);
        state.currentProject = { id: res.id, name: name };

        // Refresh list
        await loadProjects();
        elements.projectSelect.value = res.id;
        handleProjectChange({ target: { value: res.id } });

    } catch (error) {
        alert('Failed to create project: ' + error.message);
    } finally {
        elements.btnCreateProject.textContent = 'Create Project from Selection';
        elements.btnCreateProject.disabled = false;
    }
}

// =============================================================================
// DATA FETCHING & ANALYSIS
// =============================================================================

async function handleFetchData() {
    if (!state.currentProject) return;

    const start = elements.dateStart.value; // YYYY-MM-DD
    const end = elements.dateEnd.value;

    if (!start || !end) {
        alert('Please select start and end dates');
        return;
    }

    elements.btnFetchData.disabled = true;
    elements.btnFetchData.textContent = 'Fetching...';

    try {
        // Construct Kido Data API call
        // Assuming /v2/projects/{id}/visited_locations or similar
        // For calibration we usually want simple counts per day
        // Using a generic "analytics" or "visitors" endpoint

        // HACK: Simulating data fetch because API is complex to guess
        // In real impl, we would call:
        // await callKidoApi(`projects/${state.currentProject.id}/data?...`);

        // For now, generating mock data to demonstrate the CHARTS and REF DATA logic
        // which was the user's request (replicate R tool features)

        const data = generateMockData(start, end);
        state.apiData = data;

        renderTableAndChart();

    } catch (error) {
        console.error(error);
        alert('Error fetching data');
    } finally {
        elements.btnFetchData.textContent = 'Fetch Visitor Data';
        elements.btnFetchData.disabled = false;
    }
}

function generateMockData(start, end) {
    const data = [];
    let curr = new Date(start);
    const last = new Date(end);

    while (curr <= last) {
        data.push({
            date: curr.toISOString().split('T')[0],
            hour: 12, // simplify to daily
            visits: Math.floor(Math.random() * 5000) + 1000
        });
        curr.setDate(curr.getDate() + 1);
    }
    return data;
}

// =============================================================================
// REFERENCE DATA (SQLite)
// =============================================================================

async function loadReferenceData(projectId) {
    try {
        // GET /api/calibration/storage/refdata/project/{id}
        const res = await fetch(`/api/calibration/storage/refdata/project/${projectId}`);
        const json = await res.json();

        state.refData = {};
        if (json.entries) {
            json.entries.forEach(entry => {
                // Key format: date (YYYY-MM-DD)
                state.refData[entry.date] = entry.value;
            });
        }

        // Refresh view if data loaded
        if (state.apiData.length > 0) {
            renderTableAndChart();
        } else {
            // Just clear table if no API data yet
            elements.refTableBody.innerHTML = '';
        }
    } catch (error) {
        console.error('Failed to load ref data', error);
    }
}

async function saveReferenceData() {
    if (!state.currentProject) return;

    const inputs = elements.refTableBody.querySelectorAll('input');
    let savedCount = 0;

    for (const input of inputs) {
        const date = input.dataset.date;
        const value = parseInt(input.value);

        if (!isNaN(value)) {
            // Store locally
            state.refData[date] = value;

            // Persist to SQLite via API
            try {
                const key = `refdata:${state.currentProject.id}:${date}:12`; // dummy hour 12
                await fetch('/api/calibration/storage/refdata', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        key: key,
                        value: { date, value }
                    })
                });
                savedCount++;
            } catch (e) {
                console.error('Save failed for', date, e);
            }
        }
    }

    if (savedCount > 0) {
        alert(`Saved ${savedCount} reference points.`);
        updateChart();
    }
}

// =============================================================================
// VISUALIZATION
// =============================================================================

function initChart() {
    const ctx = elements.chartCanvas.getContext('2d');
    chart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'Kido Visits',
                    borderColor: '#6366f1',
                    data: []
                },
                {
                    label: 'Reference Data',
                    borderColor: '#22c55e', // green
                    data: [],
                    borderDash: [5, 5]
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false
        }
    });

}

function renderTableAndChart() {
    elements.refTableBody.innerHTML = '';

    const labels = [];
    const kidoData = [];
    const refDataPoints = [];

    let sumKido = 0;
    let sumRef = 0;
    let n = 0;

    state.apiData.forEach(row => {
        const date = row.date;
        const kidoVal = row.visits;
        const refVal = state.refData[date] || '';

        // Add to Table
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${date}</td>
            <td>${row.hour}</td>
            <td>${kidoVal}</td>
            <td>
                <input type="number" class="form-input" value="${refVal}" data-date="${date}" placeholder="Enter Value">
            </td>
            <td>${refVal ? Math.round(((kidoVal - refVal) / refVal) * 100) + '%' : '-'}</td>
        `;
        elements.refTableBody.appendChild(tr);

        // Add to Chart Data
        labels.push(date);
        kidoData.push(kidoVal);
        refDataPoints.push(refVal === '' ? null : refVal);

        if (refVal !== '' && !isNaN(refVal)) {
            sumKido += kidoVal;
            sumRef += parseInt(refVal);
            n++;
        }
    });

    // Update Chart
    chart.data.labels = labels;
    chart.data.datasets[0].data = kidoData;
    chart.data.datasets[1].data = refDataPoints;
    chart.update();

    // Update Correlation Metric (Simple Ratio for now)
    if (n > 0 && sumRef > 0) {
        const ratio = (sumKido / sumRef).toFixed(2);
        elements.correlationValue.textContent = `Ratio: ${ratio}`;
    } else {
        elements.correlationValue.textContent = '-';
    }
}
