/**
 * AOI Project Generator - Main JavaScript
 * Handles all interactions for the AOI project wizard
 */

// ==========================================
// STATE MANAGEMENT
// ==========================================

const state = {
    currentStep: 1,
    totalSteps: 4,

    // Auth
    token: null,
    rootUrl: null,
    brand: null,
    apiCountry: null,

    // Location Selection
    geoCountry: null,
    geoCountryName: null,
    region: null,
    regionName: null,
    municipality: null,

    // Generated Project
    geojson: null,
    filename: null,
    featureCount: 0,

    // Project
    projectId: null
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
    apiCountry: document.getElementById('api-country'),
    btnLogin: document.getElementById('btn-login'),
    loginError: document.getElementById('login-error'),
    loginErrorMessage: document.getElementById('login-error-message'),

    // Step 2: Location
    geoCountry: document.getElementById('geo-country'),
    region: document.getElementById('region'),
    regionHint: document.getElementById('region-hint'),
    municipality: document.getElementById('municipality'),
    municipalityHint: document.getElementById('municipality-hint'),
    btnBack1: document.getElementById('btn-back-1'),
    btnNext2: document.getElementById('btn-next-2'),
    locationError: document.getElementById('location-error'),
    locationErrorMessage: document.getElementById('location-error-message'),

    // Step 3: Generate
    summaryCountry: document.getElementById('summary-country'),
    summaryRegion: document.getElementById('summary-region'),
    summaryCity: document.getElementById('summary-city'),
    generateProgress: document.getElementById('generate-progress'),
    generateResult: document.getElementById('generate-result'),
    generateSummary: document.getElementById('generate-summary'),
    generateError: document.getElementById('generate-error'),
    generateErrorMessage: document.getElementById('generate-error-message'),
    btnBack2: document.getElementById('btn-back-2'),
    btnGenerate: document.getElementById('btn-generate'),

    // Step 4: Finish
    finalSummary: document.getElementById('final-summary'),
    projectName: document.getElementById('project-name'),
    projectDescription: document.getElementById('project-description'),
    createProgress: document.getElementById('create-progress'),
    createStatus: document.getElementById('create-status'),
    createSuccess: document.getElementById('create-success'),
    createSuccessMessage: document.getElementById('create-success-message'),
    createError: document.getElementById('create-error'),
    createErrorMessage: document.getElementById('create-error-message'),
    btnDownload: document.getElementById('btn-download'),
    btnCreateCloud: document.getElementById('btn-create-cloud'),
    btnNewProject: document.getElementById('btn-new-project')
};

// ==========================================
// INITIALIZATION
// ==========================================

document.addEventListener('DOMContentLoaded', () => {
    initEventListeners();
    loadCountries();
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
    elements.geoCountry.addEventListener('change', handleCountryChange);
    elements.region.addEventListener('change', handleRegionChange);
    elements.municipality.addEventListener('change', handleMunicipalityChange);

    // Step 3: Generate
    elements.btnBack2.addEventListener('click', () => goToStep(2));
    elements.btnGenerate.addEventListener('click', handleGenerate);

    // Step 4: Finish
    elements.btnDownload.addEventListener('click', handleDownload);
    elements.btnCreateCloud.addEventListener('click', handleCreateCloud);
    elements.btnNewProject.addEventListener('click', resetWizard);
}

// ==========================================
// LOAD COUNTRIES (For Geographic Selection)
// ==========================================

async function loadCountries() {
    try {
        const response = await fetch('/api/aoi/countries');
        const countries = await response.json();

        elements.geoCountry.innerHTML = '<option value="">Select a country...</option>';
        countries.forEach(country => {
            const flag = getCountryFlag(country.code);
            elements.geoCountry.innerHTML += `<option value="${country.code}">${flag} ${country.name}</option>`;
        });
    } catch (error) {
        console.error('Error loading countries:', error);
        elements.geoCountry.innerHTML = '<option value="">Error loading countries</option>';
    }
}

function getCountryFlag(code) {
    const flags = {
        'BR': '🇧🇷',
        'PT': '🇵🇹',
        'ES': '🇪🇸',
        'MX': '🇲🇽',
        'CL': '🇨🇱'
    };
    return flags[code] || '🌍';
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
    if (step === 3) {
        updateGenerateSummary();
    } else if (step === 4) {
        updateFinalSummary();
    }
}

// ==========================================
// STEP 1: LOGIN
// ==========================================

async function handleLogin() {
    const username = elements.username.value.trim();
    const password = elements.password.value;
    const apiCountry = elements.apiCountry.value;

    if (!username || !password || !apiCountry) {
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
            body: JSON.stringify({
                username,
                password,
                country_code: apiCountry
            })
        });

        const data = await response.json();

        if (data.success) {
            state.token = data.token;
            state.rootUrl = data.root_url;
            state.brand = data.brand;
            state.apiCountry = apiCountry;

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
// STEP 2: LOCATION SELECTION
// ==========================================

async function handleCountryChange() {
    const countryCode = elements.geoCountry.value;

    // Reset dependent fields
    elements.region.innerHTML = '<option value="">Loading regions...</option>';
    elements.region.disabled = true;
    elements.municipality.innerHTML = '<option value="">Select a region first...</option>';
    elements.municipality.disabled = true;
    elements.btnNext2.disabled = true;

    if (!countryCode) {
        elements.region.innerHTML = '<option value="">Select a country first...</option>';
        return;
    }

    state.geoCountry = countryCode;
    state.geoCountryName = elements.geoCountry.options[elements.geoCountry.selectedIndex].text;

    try {
        const response = await fetch(`/api/aoi/regions/${countryCode}`);
        const regions = await response.json();

        elements.region.innerHTML = '<option value="">Select a region...</option>';
        regions.forEach(region => {
            elements.region.innerHTML += `<option value="${region.code}">${region.name}</option>`;
        });
        elements.region.disabled = false;

        // Update hint based on country
        const hints = {
            'BR': 'Brazilian state (UF)',
            'PT': 'Portuguese district',
            'ES': 'Spanish province',
            'MX': 'Mexican state',
            'CL': 'Chilean region'
        };
        elements.regionHint.textContent = hints[countryCode] || 'Select the region';

    } catch (error) {
        console.error('Error loading regions:', error);
        elements.region.innerHTML = '<option value="">Error loading regions</option>';
        showLocationError('Failed to load regions. Please try again.');
    }
}

async function handleRegionChange() {
    const regionCode = elements.region.value;

    // Reset municipality
    elements.municipality.innerHTML = '<option value="">Loading municipalities...</option>';
    elements.municipality.disabled = true;
    elements.btnNext2.disabled = true;

    if (!regionCode) {
        elements.municipality.innerHTML = '<option value="">Select a region first...</option>';
        return;
    }

    state.region = regionCode;
    state.regionName = elements.region.options[elements.region.selectedIndex].text;

    try {
        const response = await fetch(`/api/aoi/municipalities/${state.geoCountry}/${regionCode}`);
        const data = await response.json();

        elements.municipality.innerHTML = '<option value="">Select a municipality...</option>';
        data.municipalities.forEach(name => {
            elements.municipality.innerHTML += `<option value="${name}">${name}</option>`;
        });
        elements.municipality.disabled = false;

        // Update hint
        elements.municipalityHint.textContent = `${data.municipalities.length} municipalities available`;

    } catch (error) {
        console.error('Error loading municipalities:', error);
        elements.municipality.innerHTML = '<option value="">Error loading municipalities</option>';
        showLocationError('Failed to load municipalities. Please try again.');
    }
}

function handleMunicipalityChange() {
    const municipality = elements.municipality.value;

    if (municipality) {
        state.municipality = municipality;
        elements.btnNext2.disabled = false;
    } else {
        elements.btnNext2.disabled = true;
    }
}

function showLocationError(message) {
    elements.locationError.classList.remove('hidden');
    elements.locationErrorMessage.textContent = message;
}

function hideLocationError() {
    elements.locationError.classList.add('hidden');
}

// ==========================================
// STEP 3: GENERATE
// ==========================================

function updateGenerateSummary() {
    elements.summaryCountry.innerHTML = `<strong>Country:</strong> ${state.geoCountryName}`;
    elements.summaryRegion.innerHTML = `<strong>Region:</strong> ${state.regionName}`;
    elements.summaryCity.innerHTML = `<strong>Municipality:</strong> ${state.municipality}`;

    // Reset generate state
    elements.generateResult.classList.add('hidden');
    elements.generateError.classList.add('hidden');
    elements.btnGenerate.disabled = false;
}

async function handleGenerate() {
    elements.generateProgress.classList.remove('hidden');
    elements.generateResult.classList.add('hidden');
    elements.generateError.classList.add('hidden');
    elements.btnGenerate.disabled = true;

    try {
        const response = await fetch('/api/aoi/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                country_code: state.geoCountry,
                region_code: state.region,
                city_name: state.municipality
            })
        });

        const data = await response.json();

        if (data.success) {
            state.geojson = data.geojson;
            state.filename = data.filename;
            state.featureCount = data.feature_count;

            elements.generateResult.classList.remove('hidden');
            elements.generateSummary.textContent =
                `Generated ${data.feature_count} features. Filename: ${data.filename}`;

            // Auto-advance to step 4
            setTimeout(() => goToStep(4), 1000);

        } else {
            showGenerateError(data.error || 'Failed to generate project.');
        }
    } catch (error) {
        showGenerateError('Connection error. Please try again.');
        console.error('Generate error:', error);
    } finally {
        elements.generateProgress.classList.add('hidden');
        elements.btnGenerate.disabled = false;
    }
}

function showGenerateError(message) {
    elements.generateError.classList.remove('hidden');
    elements.generateErrorMessage.textContent = message;
}

// ==========================================
// STEP 4: FINISH
// ==========================================

function updateFinalSummary() {
    elements.finalSummary.innerHTML =
        `<strong>${state.municipality}</strong> (${state.regionName}, ${state.geoCountryName})<br>` +
        `${state.featureCount} features generated. Ready to download or create in platform.`;

    // Set default project name
    elements.projectName.value = `AOI - ${state.municipality}`;

    // Reset states
    elements.createSuccess.classList.add('hidden');
    elements.createError.classList.add('hidden');
}

function handleDownload() {
    if (!state.geojson) return;

    const geojsonStr = JSON.stringify(state.geojson, null, 2);
    const blob = new Blob([geojsonStr], { type: 'application/geo+json' });
    const url = URL.createObjectURL(blob);

    const link = document.createElement('a');
    link.href = url;
    link.download = state.filename || 'project.geojson';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}

async function handleCreateCloud() {
    const projectName = elements.projectName.value.trim();
    const description = elements.projectDescription.value.trim();

    if (!projectName) {
        showCreateError('Please enter a project name.');
        return;
    }

    elements.createProgress.classList.remove('hidden');
    elements.createSuccess.classList.add('hidden');
    elements.createError.classList.add('hidden');
    elements.btnCreateCloud.disabled = true;
    elements.createStatus.textContent = 'Validating GeoJSON...';

    try {
        const response = await fetch('/api/aoi/create-project', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                token: state.token,
                root_url: state.rootUrl,
                name: projectName,
                description: description,
                geojson: state.geojson
            })
        });

        const data = await response.json();

        if (data.success) {
            state.projectId = data.project_id;
            elements.createSuccess.classList.remove('hidden');
            elements.createSuccessMessage.textContent =
                `Project created successfully! ID: ${data.project_id}`;
            elements.btnCreateCloud.disabled = true;
        } else {
            showCreateError(data.error || 'Failed to create project.');
            elements.btnCreateCloud.disabled = false;
        }
    } catch (error) {
        showCreateError('Connection error. Please try again.');
        elements.btnCreateCloud.disabled = false;
        console.error('Create error:', error);
    } finally {
        elements.createProgress.classList.add('hidden');
    }
}

function showCreateError(message) {
    elements.createError.classList.remove('hidden');
    elements.createErrorMessage.textContent = message;
}

// ==========================================
// UTILITIES
// ==========================================

function resetWizard() {
    // Reset state
    state.currentStep = 1;
    state.geoCountry = null;
    state.geoCountryName = null;
    state.region = null;
    state.regionName = null;
    state.municipality = null;
    state.geojson = null;
    state.filename = null;
    state.featureCount = 0;
    state.projectId = null;

    // Reset form fields
    elements.geoCountry.value = '';
    elements.region.innerHTML = '<option value="">Select a country first...</option>';
    elements.region.disabled = true;
    elements.municipality.innerHTML = '<option value="">Select a region first...</option>';
    elements.municipality.disabled = true;
    elements.projectName.value = '';
    elements.projectDescription.value = '';

    // Reset buttons
    elements.btnNext2.disabled = true;
    elements.btnCreateCloud.disabled = false;

    // Reset alerts
    elements.generateResult.classList.add('hidden');
    elements.generateError.classList.add('hidden');
    elements.createSuccess.classList.add('hidden');
    elements.createError.classList.add('hidden');

    // Go to step 2 (already logged in)
    goToStep(2);
}
