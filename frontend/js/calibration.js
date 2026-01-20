/**
 * Mall Calibration Tool - Main JavaScript
 * Handles all interactions for the calibration wizard
 */

// ==========================================
// STATE MANAGEMENT
// ==========================================

const state = {
    currentStep: 1,
    totalSteps: 6,

    // Auth
    token: null,
    rootUrl: null,
    brand: null,
    countryCode: null,

    // Location
    latitude: null,
    longitude: null,
    countryName: null,

    // Radii
    radii: [200, 300, 400],

    // Project
    projectId: null,
    projectName: null,
    geojson: null,

    // Results
    extractedData: []
};

// ==========================================
// DOM ELEMENTS
// ==========================================

const elements = {
    // Stepper
    stepper: document.getElementById('stepper'),
    stepContents: document.querySelectorAll('.step-content'),

    // Step 1: Login
    loginForm: document.getElementById('login-form'),
    username: document.getElementById('username'),
    password: document.getElementById('password'),
    countryCode: document.getElementById('country-code'),
    btnLogin: document.getElementById('btn-login'),
    loginError: document.getElementById('login-error'),
    loginErrorMessage: document.getElementById('login-error-message'),

    // Step 2: Location
    latitude: document.getElementById('latitude'),
    longitude: document.getElementById('longitude'),
    btnBack1: document.getElementById('btn-back-1'),
    btnNext2: document.getElementById('btn-next-2'),
    countryDetected: document.getElementById('country-detected'),
    countryName: document.getElementById('country-name'),

    // Step 3: Radii
    radiusContainer: document.getElementById('radius-container'),
    radiusInput: document.getElementById('radius-input'),
    presetBtns: document.querySelectorAll('.preset-btn'),
    btnBack2: document.getElementById('btn-back-2'),
    btnNext3: document.getElementById('btn-next-3'),

    // Step 4: Project
    projectName: document.getElementById('project-name'),
    projectDescription: document.getElementById('project-description'),
    summaryCoords: document.getElementById('summary-coords'),
    summaryRadii: document.getElementById('summary-radii'),
    summaryCountry: document.getElementById('summary-country'),
    btnBack3: document.getElementById('btn-back-3'),
    btnCreateProject: document.getElementById('btn-create-project'),
    projectError: document.getElementById('project-error'),
    projectErrorMessage: document.getElementById('project-error-message'),

    // Step 5: Extraction
    startMonth: document.getElementById('start-month'),
    endMonth: document.getElementById('end-month'),
    radiiCheckboxes: document.getElementById('radii-checkboxes'),
    extractionProgress: document.getElementById('extraction-progress'),
    extractionStatus: document.getElementById('extraction-status'),
    extractionError: document.getElementById('extraction-error'),
    extractionErrorMessage: document.getElementById('extraction-error-message'),
    btnBack4: document.getElementById('btn-back-4'),
    btnExtract: document.getElementById('btn-extract'),

    // Step 6: Results
    resultSummary: document.getElementById('result-summary'),
    resultsBody: document.getElementById('results-body'),
    btnNewCalibration: document.getElementById('btn-new-calibration'),
    btnExportCsv: document.getElementById('btn-export-csv')
};

// Maps
let locationMap = null;
let previewMap = null;
let locationMarker = null;
let bufferLayers = [];

// ==========================================
// INITIALIZATION
// ==========================================

document.addEventListener('DOMContentLoaded', () => {
    initEventListeners();
    setDefaultDates();
});

function initEventListeners() {
    // Step 1: Login
    elements.btnLogin.addEventListener('click', handleLogin);
    elements.loginForm.addEventListener('submit', (e) => {
        e.preventDefault();
        handleLogin();
    });

    // Step 2: Location
    elements.btnBack1.addEventListener('click', () => goToStep(1));
    elements.btnNext2.addEventListener('click', () => goToStep(3));
    elements.latitude.addEventListener('input', handleCoordinateChange);
    elements.longitude.addEventListener('input', handleCoordinateChange);

    // Step 3: Radii
    elements.btnBack2.addEventListener('click', () => goToStep(2));
    elements.btnNext3.addEventListener('click', () => goToStep(4));
    elements.radiusInput.addEventListener('keydown', handleRadiusKeydown);
    elements.presetBtns.forEach(btn => {
        btn.addEventListener('click', handlePresetClick);
    });

    // Step 4: Project
    elements.btnBack3.addEventListener('click', () => goToStep(3));
    elements.btnCreateProject.addEventListener('click', handleCreateProject);

    // Step 5: Extraction
    elements.btnBack4.addEventListener('click', () => goToStep(4));
    elements.btnExtract.addEventListener('click', handleExtractData);

    // Step 6: Results
    elements.btnNewCalibration.addEventListener('click', resetWizard);
    elements.btnExportCsv.addEventListener('click', exportToCsv);
}

function setDefaultDates() {
    const now = new Date();
    const lastMonth = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    const threeMonthsAgo = new Date(now.getFullYear(), now.getMonth() - 3, 1);

    elements.startMonth.value = formatMonth(threeMonthsAgo);
    elements.endMonth.value = formatMonth(lastMonth);
}

function formatMonth(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    return `${year}-${month}`;
}

// ==========================================
// STEP NAVIGATION
// ==========================================

function goToStep(step) {
    if (step < 1 || step > state.totalSteps) return;

    state.currentStep = step;

    // Update stepper UI
    const stepperSteps = elements.stepper.querySelectorAll('.stepper-step');
    stepperSteps.forEach((el, index) => {
        const stepNum = index + 1;
        el.classList.remove('active', 'completed');

        if (stepNum < step) {
            el.classList.add('completed');
        } else if (stepNum === step) {
            el.classList.add('active');
        }
    });

    // Update content visibility
    elements.stepContents.forEach((content, index) => {
        content.classList.remove('active');
        if (index + 1 === step) {
            content.classList.add('active');
        }
    });

    // Step-specific initialization
    if (step === 2) {
        initLocationMap();
    } else if (step === 3) {
        initPreviewMap();
        updateRadiiTags();
    } else if (step === 4) {
        updateProjectSummary();
    } else if (step === 5) {
        initExtractionStep();
    }
}

// ==========================================
// STEP 1: LOGIN
// ==========================================

async function handleLogin() {
    const username = elements.username.value.trim();
    const password = elements.password.value;
    const countryCode = elements.countryCode.value;

    if (!username || !password || !countryCode) {
        showLoginError('Please fill in all fields.');
        return;
    }

    // Show loading state
    elements.btnLogin.disabled = true;
    elements.btnLogin.innerHTML = `
        <div class="spinner"></div>
        Connecting...
    `;
    hideLoginError();

    try {
        const response = await fetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password, country_code: countryCode })
        });

        const data = await response.json();

        if (data.success) {
            state.token = data.token;
            state.rootUrl = data.root_url;
            state.brand = data.brand;
            state.countryCode = data.country_code;

            goToStep(2);
        } else {
            showLoginError(data.error || 'Login failed. Please check your credentials.');
        }
    } catch (error) {
        showLoginError('Connection error. Please try again.');
        console.error('Login error:', error);
    } finally {
        elements.btnLogin.disabled = false;
        elements.btnLogin.innerHTML = `
            Connect
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M5 12h14M12 5l7 7-7 7"/>
            </svg>
        `;
    }
}

function showLoginError(message) {
    elements.loginError.classList.remove('hidden');
    elements.loginErrorMessage.textContent = message;
}

function hideLoginError() {
    elements.loginError.classList.add('hidden');
}

// ==========================================
// STEP 2: LOCATION
// ==========================================

function initLocationMap() {
    if (locationMap) {
        locationMap.invalidateSize();
        return;
    }

    // Default to center of South America
    const defaultLat = -15.7801;
    const defaultLng = -47.9292;

    locationMap = L.map('location-map').setView([defaultLat, defaultLng], 4);

    // Add tile layer
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors'
    }).addTo(locationMap);

    // Handle map clicks
    locationMap.on('click', (e) => {
        setLocation(e.latlng.lat, e.latlng.lng);
    });

    // If we already have coordinates, show them
    if (state.latitude && state.longitude) {
        setLocation(state.latitude, state.longitude);
    }
}

function setLocation(lat, lng) {
    state.latitude = lat;
    state.longitude = lng;

    // Update input fields
    elements.latitude.value = lat.toFixed(6);
    elements.longitude.value = lng.toFixed(6);

    // Update marker
    if (locationMarker) {
        locationMarker.setLatLng([lat, lng]);
    } else {
        locationMarker = L.marker([lat, lng]).addTo(locationMap);
    }

    // Center map
    locationMap.setView([lat, lng], 14);

    // Enable next button
    elements.btnNext2.disabled = false;

    // Check country
    checkCountry();
}

function handleCoordinateChange() {
    const lat = parseFloat(elements.latitude.value);
    const lng = parseFloat(elements.longitude.value);

    if (!isNaN(lat) && !isNaN(lng) &&
        lat >= -90 && lat <= 90 &&
        lng >= -180 && lng <= 180) {
        setLocation(lat, lng);
    }
}

async function checkCountry() {
    // This would ideally call the backend, but for preview we'll skip it
    // The country detection happens when creating buffers
    elements.countryDetected.classList.add('hidden');
}

// ==========================================
// STEP 3: RADII CONFIGURATION
// ==========================================

function initPreviewMap() {
    if (previewMap) {
        previewMap.invalidateSize();
        updateBufferPreview();
        return;
    }

    previewMap = L.map('preview-map').setView([state.latitude, state.longitude], 14);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors'
    }).addTo(previewMap);

    // Add center marker
    L.marker([state.latitude, state.longitude]).addTo(previewMap);

    updateBufferPreview();
}

function updateRadiiTags() {
    // Clear existing tags
    const existingTags = elements.radiusContainer.querySelectorAll('.tag');
    existingTags.forEach(tag => tag.remove());

    // Add tags for current radii
    state.radii.forEach(r => {
        const tag = createRadiusTag(r);
        elements.radiusContainer.insertBefore(tag, elements.radiusInput);
    });

    // Update next button state
    elements.btnNext3.disabled = state.radii.length === 0;
}

function createRadiusTag(radius) {
    const tag = document.createElement('span');
    tag.className = 'tag tag-primary tag-removable';
    tag.innerHTML = `
        ${radius}m
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M18 6L6 18M6 6l12 12"/>
        </svg>
    `;
    tag.dataset.radius = radius;
    tag.addEventListener('click', () => removeRadius(radius));
    return tag;
}

function addRadius(radius) {
    radius = parseInt(radius);
    if (isNaN(radius) || radius < 50 || radius > 5000) return;
    if (state.radii.includes(radius)) return;

    state.radii.push(radius);
    state.radii.sort((a, b) => a - b);

    updateRadiiTags();
    updateBufferPreview();
}

function removeRadius(radius) {
    state.radii = state.radii.filter(r => r !== radius);
    updateRadiiTags();
    updateBufferPreview();
}

function handleRadiusKeydown(e) {
    if (e.key === 'Enter' || e.key === ',') {
        e.preventDefault();
        const value = elements.radiusInput.value.trim();
        if (value) {
            addRadius(value);
            elements.radiusInput.value = '';
        }
    }
}

function handlePresetClick(e) {
    const radii = e.target.dataset.radii.split(',').map(r => parseInt(r));
    state.radii = radii;
    updateRadiiTags();
    updateBufferPreview();
}

async function updateBufferPreview() {
    if (!previewMap || state.radii.length === 0) return;

    // Clear existing layers
    bufferLayers.forEach(layer => previewMap.removeLayer(layer));
    bufferLayers = [];

    try {
        const response = await fetch('/api/buffer-preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                lat: state.latitude,
                lon: state.longitude,
                radii: state.radii
            })
        });

        const data = await response.json();

        if (data.success && data.geojson) {
            // Color palette for buffers
            const colors = ['#6366f1', '#8b5cf6', '#a855f7', '#d946ef', '#ec4899'];

            // Add each buffer feature
            data.geojson.features.forEach((feature, index) => {
                if (feature.properties.type === 'center') return;

                const color = colors[index % colors.length];

                const layer = L.geoJSON(feature, {
                    style: {
                        color: color,
                        fillColor: color,
                        fillOpacity: 0.1,
                        weight: 2
                    }
                }).addTo(previewMap);

                // Add popup
                layer.bindPopup(`<strong>${feature.properties.name}</strong><br>Radius: ${feature.properties.radius}m`);

                bufferLayers.push(layer);
            });

            // Fit bounds to show all buffers
            if (bufferLayers.length > 0) {
                const group = L.featureGroup(bufferLayers);
                previewMap.fitBounds(group.getBounds().pad(0.1));
            }
        }
    } catch (error) {
        console.error('Buffer preview error:', error);
    }
}

// ==========================================
// STEP 4: PROJECT CREATION
// ==========================================

function updateProjectSummary() {
    elements.summaryCoords.innerHTML = `<strong>Coordinates:</strong> ${state.latitude.toFixed(6)}, ${state.longitude.toFixed(6)}`;
    elements.summaryRadii.innerHTML = `<strong>Radii:</strong> ${state.radii.join(', ')} meters`;
    elements.summaryCountry.innerHTML = state.countryName
        ? `<strong>Country:</strong> ${state.countryName}`
        : '';
}

async function handleCreateProject() {
    const name = elements.projectName.value.trim();
    const description = elements.projectDescription.value.trim();

    if (!name) {
        showProjectError('Please enter a project name.');
        return;
    }

    // Show loading state
    elements.btnCreateProject.disabled = true;
    elements.btnCreateProject.innerHTML = `
        <div class="spinner"></div>
        Creating...
    `;
    hideProjectError();

    try {
        // First, create the buffers with country
        const bufferResponse = await fetch('/api/create-buffers', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                lat: state.latitude,
                lon: state.longitude,
                radii: state.radii
            })
        });

        const bufferData = await bufferResponse.json();

        if (!bufferData.success) {
            showProjectError(bufferData.error || 'Failed to create buffers.');
            return;
        }

        state.geojson = bufferData.geojson;
        state.countryName = bufferData.country_name;

        // Now create the project
        const projectResponse = await fetch('/api/create-project', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                token: state.token,
                root_url: state.rootUrl,
                name: name,
                description: description,
                geojson: state.geojson
            })
        });

        const projectData = await projectResponse.json();

        if (projectData.success) {
            state.projectId = projectData.project_id;
            state.projectName = name;
            goToStep(5);
        } else {
            showProjectError(projectData.error || 'Failed to create project.');
        }
    } catch (error) {
        showProjectError('Connection error. Please try again.');
        console.error('Project creation error:', error);
    } finally {
        elements.btnCreateProject.disabled = false;
        elements.btnCreateProject.innerHTML = `
            Create Project
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M5 12h14M12 5l7 7-7 7"/>
            </svg>
        `;
    }
}

function showProjectError(message) {
    elements.projectError.classList.remove('hidden');
    elements.projectErrorMessage.textContent = message;
}

function hideProjectError() {
    elements.projectError.classList.add('hidden');
}

// ==========================================
// STEP 5: DATA EXTRACTION
// ==========================================

function initExtractionStep() {
    // Populate radii checkboxes
    elements.radiiCheckboxes.innerHTML = '';

    state.radii.forEach(r => {
        const label = document.createElement('label');
        label.className = 'form-check';
        label.innerHTML = `
            <input type="checkbox" class="form-check-input" value="${r}" checked>
            <span class="form-check-label">${r}m</span>
        `;
        elements.radiiCheckboxes.appendChild(label);
    });
}

async function handleExtractData() {
    const startMonth = elements.startMonth.value;
    const endMonth = elements.endMonth.value;

    if (!startMonth || !endMonth) {
        showExtractionError('Please select a date range.');
        return;
    }

    // Get selected radii
    const checkboxes = elements.radiiCheckboxes.querySelectorAll('input:checked');
    const selectedRadii = Array.from(checkboxes).map(cb => parseInt(cb.value));

    if (selectedRadii.length === 0) {
        showExtractionError('Please select at least one radius.');
        return;
    }

    // Show progress
    elements.extractionProgress.classList.remove('hidden');
    elements.btnExtract.disabled = true;
    hideExtractionError();

    try {
        const response = await fetch('/api/extract-data', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                token: state.token,
                root_url: state.rootUrl,
                project_id: state.projectId,
                radii: selectedRadii,
                start_month: startMonth,
                end_month: endMonth
            })
        });

        const data = await response.json();

        if (data.success) {
            state.extractedData = data.data;
            displayResults();
            goToStep(6);
        } else {
            showExtractionError(data.error || 'Failed to extract data.');
        }
    } catch (error) {
        showExtractionError('Connection error. Please try again.');
        console.error('Extraction error:', error);
    } finally {
        elements.extractionProgress.classList.add('hidden');
        elements.btnExtract.disabled = false;
    }
}

function showExtractionError(message) {
    elements.extractionError.classList.remove('hidden');
    elements.extractionErrorMessage.textContent = message;
}

function hideExtractionError() {
    elements.extractionError.classList.add('hidden');
}

// ==========================================
// STEP 6: RESULTS
// ==========================================

function displayResults() {
    // Summary
    const successCount = state.extractedData.filter(d => d.status === 'success').length;
    const totalCount = state.extractedData.length;
    elements.resultSummary.textContent = `Retrieved ${successCount} of ${totalCount} data points for project "${state.projectName}".`;

    // Table
    elements.resultsBody.innerHTML = '';

    if (state.extractedData.length === 0) {
        elements.resultsBody.innerHTML = `
            <tr>
                <td colspan="5" class="table-empty">No data available</td>
            </tr>
        `;
        return;
    }

    state.extractedData.forEach(row => {
        const tr = document.createElement('tr');

        let statusBadge = '';
        switch (row.status) {
            case 'success':
                statusBadge = '<span class="tag tag-success">Success</span>';
                break;
            case 'processing':
                statusBadge = '<span class="tag tag-warning">Processing</span>';
                break;
            case 'empty':
                statusBadge = '<span class="tag">Empty</span>';
                break;
            default:
                statusBadge = `<span class="tag tag-error">${row.status}</span>`;
        }

        tr.innerHTML = `
            <td>${row.month}</td>
            <td><code>${row.aoi_id}</code></td>
            <td>${row.radius}m</td>
            <td>${row.visits !== null ? row.visits.toLocaleString() : '-'}</td>
            <td>${statusBadge}</td>
        `;

        elements.resultsBody.appendChild(tr);
    });
}

function exportToCsv() {
    if (state.extractedData.length === 0) return;

    // Create CSV content
    const headers = ['month', 'aoi_id', 'radius', 'visits', 'status'];
    const rows = state.extractedData.map(row => [
        row.month,
        row.aoi_id,
        row.radius,
        row.visits !== null ? row.visits : '',
        row.status
    ]);

    const csvContent = [
        headers.join(','),
        ...rows.map(row => row.join(','))
    ].join('\n');

    // Create download
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);

    link.setAttribute('href', url);
    link.setAttribute('download', `visitors_${state.projectName.replace(/\s+/g, '_')}.csv`);
    link.style.visibility = 'hidden';

    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// ==========================================
// UTILITIES
// ==========================================

function resetWizard() {
    // Reset state
    state.currentStep = 1;
    state.latitude = null;
    state.longitude = null;
    state.countryName = null;
    state.radii = [200, 300, 400];
    state.projectId = null;
    state.projectName = null;
    state.geojson = null;
    state.extractedData = [];

    // Reset forms
    elements.loginForm.reset();
    elements.latitude.value = '';
    elements.longitude.value = '';
    elements.projectName.value = '';
    elements.projectDescription.value = '';

    // Reset maps
    if (locationMarker) {
        locationMap.removeLayer(locationMarker);
        locationMarker = null;
    }

    bufferLayers.forEach(layer => {
        if (previewMap) previewMap.removeLayer(layer);
    });
    bufferLayers = [];

    // Reset buttons
    elements.btnNext2.disabled = true;
    elements.btnNext3.disabled = false;

    // Go to step 1
    goToStep(1);
}
