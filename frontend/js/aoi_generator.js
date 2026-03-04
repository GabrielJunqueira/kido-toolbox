/**
 * AOI Generator via API — Frontend Logic
 * 4-step wizard: Location → Generate → Review (Map + Edit) → Finish
 */

const API = '/api/aoi-generator';
const API_LOGIN = '/api/login';
const API_CREATE = '/api/create-project';

// ── State ──────────────────────────────────────────────────────
let currentStep = 1;
let selectedCountry = null;   // { name, iso }
let selectedState = null;     // { id, name }
let selectedCity = null;      // { id, name }
let projectGeoJSON = null;
let projectFilename = '';
let map = null;
let geoLayer = null;
let selectedFeatureIndex = null;
let selectedLayer = null;

// ── DOM References ─────────────────────────────────────────────
const $ = id => document.getElementById(id);

const stepEls = document.querySelectorAll('.step-content');
const stepperSteps = document.querySelectorAll('.stepper-step');
const stepperLines = document.querySelectorAll('.stepper-line');

// ── Stepper Navigation ────────────────────────────────────────

function goToStep(step) {
    stepEls.forEach(el => el.classList.remove('active'));
    $(`step-${step}`).classList.add('active');

    stepperSteps.forEach((el, i) => {
        const s = i + 1;
        el.classList.remove('active', 'completed');
        if (s < step) el.classList.add('completed');
        else if (s === step) el.classList.add('active');
    });

    stepperLines.forEach((el, i) => {
        el.style.background = i < step - 1 ? 'var(--success)' : 'var(--glass-border)';
    });

    currentStep = step;

    if (step === 3 && projectGeoJSON) {
        setTimeout(() => initMap(), 100);
    }
}

// ── Step 1: Load Countries ────────────────────────────────────

async function loadCountries() {
    try {
        const res = await fetch(`${API}/countries`);
        const countries = await res.json();
        const sel = $('sel-country');
        sel.innerHTML = '<option value="">Select a country...</option>';
        countries.forEach(c => {
            sel.innerHTML += `<option value='${JSON.stringify(c)}'>${c.name}</option>`;
        });
    } catch (e) {
        console.error('Failed to load countries', e);
    }
}

$('sel-country').addEventListener('change', async function () {
    const val = this.value;
    $('sel-state').disabled = true;
    $('sel-city').disabled = true;
    $('btn-next-1').disabled = true;
    selectedCountry = null;
    selectedState = null;
    selectedCity = null;

    if (!val) return;

    selectedCountry = JSON.parse(val);
    $('state-hint').textContent = 'Loading states...';

    try {
        const res = await fetch(`${API}/states/${selectedCountry.iso}`);
        const states = await res.json();
        const sel = $('sel-state');
        sel.innerHTML = '<option value="">Select a state...</option>';
        states.forEach(s => {
            sel.innerHTML += `<option value='${JSON.stringify(s)}'>${s.name}</option>`;
        });
        sel.disabled = false;
        $('state-hint').textContent = `${states.length} states loaded`;
    } catch (e) {
        $('state-hint').textContent = '❌ Failed to load states';
    }
});

$('sel-state').addEventListener('change', async function () {
    const val = this.value;
    $('sel-city').disabled = true;
    $('btn-next-1').disabled = true;
    selectedState = null;
    selectedCity = null;

    if (!val) return;

    selectedState = JSON.parse(val);
    $('city-hint').textContent = 'Loading cities...';

    try {
        const res = await fetch(`${API}/cities/${selectedCountry.iso}/${encodeURIComponent(selectedState.name)}`);
        const cities = await res.json();
        const sel = $('sel-city');
        sel.innerHTML = '<option value="">Select a city...</option>';
        cities.forEach(c => {
            sel.innerHTML += `<option value='${JSON.stringify(c)}'>${c.name}</option>`;
        });
        sel.disabled = false;
        $('city-hint').textContent = `${cities.length} cities available`;
    } catch (e) {
        $('city-hint').textContent = '❌ Failed to load cities';
    }
});

$('sel-city').addEventListener('change', function () {
    const val = this.value;
    selectedCity = val ? JSON.parse(val) : null;
    $('btn-next-1').disabled = !selectedCity;
});

// ── Step 1 → 2: Generate ─────────────────────────────────────

$('btn-next-1').addEventListener('click', async () => {
    if (!selectedCountry || !selectedState || !selectedCity) return;

    goToStep(2);
    $('gen-summary-country').textContent = `Country: ${selectedCountry.name}`;
    $('gen-summary-state').textContent = `State: ${selectedState.name}`;
    $('gen-summary-city').textContent = `City: ${selectedCity.name}`;
    $('gen-progress').style.display = 'flex';
    $('gen-error').classList.add('hidden');
    $('gen-status').textContent = 'Querying Overpass API...';

    try {
        const res = await fetch(`${API}/generate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                country_name: selectedCountry.name,
                state_id: selectedState.id,
                state_name: selectedState.name,
                city_id: selectedCity.id,
                city_name: selectedCity.name,
            }),
        });
        const data = await res.json();

        if (data.success) {
            projectGeoJSON = data.geojson;
            projectFilename = data.filename;
            $('gen-progress').style.display = 'none';

            // Update stats for step 3
            $('stat-prov').textContent = data.provinces;
            $('stat-mun').textContent = data.municipalities;
            $('stat-core').textContent = data.core;

            goToStep(3);
        } else {
            throw new Error(data.error || 'Generation failed');
        }
    } catch (e) {
        $('gen-progress').style.display = 'none';
        $('gen-error').classList.remove('hidden');
        $('gen-error-msg').textContent = e.message;
    }
});

$('btn-back-1').addEventListener('click', () => goToStep(1));

// ── Step 3: Map ───────────────────────────────────────────────

const STYLE = {
    provinces: { color: '#94a3b8', weight: 1.5, fillColor: '#94a3b8', fillOpacity: 0.08 },
    municipalities: { color: '#3b82f6', weight: 2, fillColor: '#3b82f6', fillOpacity: 0.12 },
    core: { color: '#10b981', weight: 3, fillColor: '#10b981', fillOpacity: 0.25 },
    selected: { color: '#f59e0b', weight: 3, fillColor: '#f59e0b', fillOpacity: 0.2 },
};

function getFeatureStyle(feature) {
    const id = feature.properties.id || '';
    if (id.startsWith('AOI-') || feature.properties.poly_type === 'core') return STYLE.core;
    if (id.startsWith('MUN-')) return STYLE.municipalities;
    return STYLE.provinces;
}

function getFeatureCategory(feature) {
    const id = feature.properties.id || '';
    if (id.startsWith('AOI-') || feature.properties.poly_type === 'core') return 'Core City';
    if (id.startsWith('MUN-')) return 'City (Periphery)';
    return 'Province (Periphery)';
}

function initMap() {
    if (map) {
        map.remove();
        map = null;
    }

    map = L.map('map', { zoomControl: true }).setView([0, 0], 2);

    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; <a href="https://carto.com">CARTO</a>',
        maxZoom: 19,
    }).addTo(map);

    renderGeoJSON();
}

function renderGeoJSON() {
    if (geoLayer) {
        map.removeLayer(geoLayer);
    }

    selectedFeatureIndex = null;
    selectedLayer = null;
    $('prop-panel').style.display = 'none';
    $('click-hint').style.display = 'block';

    geoLayer = L.geoJSON(projectGeoJSON, {
        style: feature => getFeatureStyle(feature),
        onEachFeature: (feature, layer) => {
            const cat = getFeatureCategory(feature);
            const name = feature.properties.name || '(unnamed)';
            layer.bindTooltip(`<b>${name}</b><br>${cat}`, { sticky: true });

            layer.on('click', () => {
                const idx = projectGeoJSON.features.indexOf(feature);
                selectFeature(idx, layer);
            });
        },
    }).addTo(map);

    map.fitBounds(geoLayer.getBounds(), { padding: [20, 20] });
    updateStats();
}

function selectFeature(idx, layer) {
    // Reset previous selection
    if (selectedLayer) {
        selectedLayer.setStyle(getFeatureStyle(projectGeoJSON.features[selectedFeatureIndex]));
    }

    selectedFeatureIndex = idx;
    selectedLayer = layer;
    layer.setStyle(STYLE.selected);

    const feat = projectGeoJSON.features[idx];
    $('prop-name').value = feat.properties.name || '';
    $('prop-id').value = feat.properties.id || '';
    $('prop-type').value = feat.properties.poly_type || 'periphery';
    $('prop-panel').style.display = 'block';
    $('click-hint').style.display = 'none';
}

$('btn-apply-prop').addEventListener('click', () => {
    if (selectedFeatureIndex === null) return;

    const feat = projectGeoJSON.features[selectedFeatureIndex];
    feat.properties.name = $('prop-name').value;
    feat.properties.id = $('prop-id').value;
    feat.properties.poly_type = $('prop-type').value;

    // Re-render
    renderGeoJSON();
});

function updateStats() {
    let prov = 0, mun = 0, core = 0;
    projectGeoJSON.features.forEach(f => {
        const id = f.properties.id || '';
        if (id.startsWith('AOI-') || f.properties.poly_type === 'core') core++;
        else if (id.startsWith('MUN-')) mun++;
        else prov++;
    });
    $('stat-prov').textContent = prov;
    $('stat-mun').textContent = mun;
    $('stat-core').textContent = core;
}

// Fullscreen
$('fullscreenBtn').addEventListener('click', () => {
    const wrapper = $('mapWrapper');
    wrapper.classList.toggle('is-fullscreen');
    setTimeout(() => map && map.invalidateSize(), 300);
});

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        $('mapWrapper').classList.remove('is-fullscreen');
        setTimeout(() => map && map.invalidateSize(), 300);
    }
});

$('btn-back-2').addEventListener('click', () => goToStep(1));
$('btn-next-3').addEventListener('click', () => {
    // Prepare final summary
    const prov = $('stat-prov').textContent;
    const mun = $('stat-mun').textContent;
    const core = $('stat-core').textContent;
    $('final-summary').innerHTML = `
        <strong>${selectedCity.name}</strong> — ${selectedCountry.name}<br>
        ${projectGeoJSON.features.length} polygons: ${prov} provinces, ${mun} cities, ${core} core<br>
        File: <code>${projectFilename}</code>
    `;
    $('project-name').value = `${selectedCity.name} - ${selectedCountry.name}`;
    goToStep(4);
});

// ── Step 4: Download ──────────────────────────────────────────

$('btn-download').addEventListener('click', () => {
    const blob = new Blob(
        [JSON.stringify(projectGeoJSON, null, 2)],
        { type: 'application/geo+json' }
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = projectFilename;
    a.click();
    URL.revokeObjectURL(url);
});

// ── Step 4: Create in Platform ────────────────────────────────

$('btn-create-cloud').addEventListener('click', async () => {
    const username = $('username').value.trim();
    const password = $('password').value.trim();
    const apiCountry = $('api-country').value;
    const projectName = $('project-name').value.trim();

    if (!username || !password || !apiCountry) {
        showError('create', 'Please fill in all login fields.');
        return;
    }
    if (!projectName) {
        showError('create', 'Please enter a project name.');
        return;
    }

    hideAlerts('create');
    $('create-progress').classList.remove('hidden');
    $('create-status').textContent = 'Logging in...';

    try {
        // 1. Login
        const loginRes = await fetch(API_LOGIN, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                username, password,
                country_code: apiCountry,
            }),
        });
        const loginData = await loginRes.json();

        if (!loginData.success) {
            throw new Error(loginData.error || 'Login failed');
        }

        // 2. Create project
        $('create-status').textContent = 'Validating and creating project...';
        const createRes = await fetch(API_CREATE, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                token: loginData.token,
                root_url: loginData.root_url,
                name: projectName,
                description: $('project-desc').value.trim() || '',
                geojson: projectGeoJSON,
            }),
        });
        const createData = await createRes.json();

        $('create-progress').classList.add('hidden');

        if (createData.success) {
            $('create-success').classList.remove('hidden');
            $('create-success-msg').textContent =
                `Project "${projectName}" created successfully! ID: ${createData.project_id}`;
        } else {
            throw new Error(createData.error || 'Creation failed');
        }
    } catch (e) {
        $('create-progress').classList.add('hidden');
        showError('create', e.message);
    }
});

$('btn-back-3').addEventListener('click', () => goToStep(3));

$('btn-new-project').addEventListener('click', () => {
    projectGeoJSON = null;
    projectFilename = '';
    selectedCountry = null;
    selectedState = null;
    selectedCity = null;
    $('sel-country').value = '';
    $('sel-state').innerHTML = '<option value="">Select a country first...</option>';
    $('sel-state').disabled = true;
    $('sel-city').innerHTML = '<option value="">Select a state first...</option>';
    $('sel-city').disabled = true;
    $('btn-next-1').disabled = true;
    hideAlerts('create');
    goToStep(1);
});

// ── Helpers ───────────────────────────────────────────────────

function showError(prefix, msg) {
    $(`${prefix}-error`).classList.remove('hidden');
    $(`${prefix}-error-msg`).textContent = msg;
}

function hideAlerts(prefix) {
    $(`${prefix}-error`).classList.add('hidden');
    $(`${prefix}-success`).classList.add('hidden');
}

// ── Init ──────────────────────────────────────────────────────
loadCountries();
