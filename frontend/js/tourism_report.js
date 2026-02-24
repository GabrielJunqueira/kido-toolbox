/**
 * AOI Tourism Report - Frontend JavaScript
 * Handles wizard navigation, API calls, and chart display
 */

// ══════════════════════════════════════════
// STATE
// ══════════════════════════════════════════
const state = {
    currentStep: 1,
    token: null,
    rootUrl: null,
    brand: null,
    projectId: '',
    aoiId: '',
    selectedMonths: [],
    csvDataB64: null
};

// ══════════════════════════════════════════
// DOM HELPERS
// ══════════════════════════════════════════
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

function show(el) { if (typeof el === 'string') el = $(el); el?.classList.remove('hidden'); }
function hide(el) { if (typeof el === 'string') el = $(el); el?.classList.add('hidden'); }

// ══════════════════════════════════════════
// STEPPER NAVIGATION
// ══════════════════════════════════════════
function goToStep(step) {
    state.currentStep = step;

    $$('.stepper-step').forEach(s => {
        const stepNum = parseInt(s.dataset.step);
        s.classList.remove('active', 'completed');
        if (stepNum === step) s.classList.add('active');
        else if (stepNum < step) s.classList.add('completed');
    });

    $$('.step-content').forEach(c => c.classList.remove('active'));
    $(`#step-${step}`)?.classList.add('active');

    // Show wizard card, hide results when navigating back
    if (step <= 3) {
        show('#wizard-card');
        hide('#results');
    }

    if (step === 4) {
        show('#wizard-card');
        hide('#results');
        prepareStep4();
    }
}

// ══════════════════════════════════════════
// STEP 1: LOGIN
// ══════════════════════════════════════════
$('#btn-login')?.addEventListener('click', async () => {
    const username = $('#username').value.trim();
    const password = $('#password').value;
    const countryCode = $('#country-code').value;

    if (!username || !password || !countryCode) {
        showLoginError('Please fill in all fields');
        return;
    }

    const btn = $('#btn-login');
    btn.disabled = true;
    btn.innerHTML = '<div class="spinner" style="width:20px;height:20px;"></div> Connecting...';
    hide('#login-error');

    try {
        const res = await fetch('/api/tourism-report/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password, country_code: countryCode })
        });

        const data = await res.json();

        if (data.success) {
            state.token = data.token;
            state.rootUrl = data.root_url;
            state.brand = data.brand;
            goToStep(2);
        } else {
            showLoginError(data.error || 'Login failed');
        }
    } catch (e) {
        showLoginError('Connection error: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = 'Connect <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14M12 5l7 7-7 7"/></svg>';
    }
});

function showLoginError(msg) {
    show('#login-error');
    $('#login-error-message').textContent = msg;
}

// ══════════════════════════════════════════
// STEP 2: PROJECT SETUP
// ══════════════════════════════════════════
function validateStep2() {
    const projectId = $('#project-id').value.trim();
    const aoiId = $('#aoi-id').value.trim();
    $('#btn-next-2').disabled = !(projectId && aoiId);
}

$('#project-id')?.addEventListener('input', validateStep2);
$('#aoi-id')?.addEventListener('input', validateStep2);

$('#btn-next-2')?.addEventListener('click', () => {
    state.projectId = $('#project-id').value.trim();
    state.aoiId = $('#aoi-id').value.trim();
    goToStep(3);
});

$('#btn-back-1')?.addEventListener('click', () => goToStep(1));

// ══════════════════════════════════════════
// STEP 3: DATE RANGE
// ══════════════════════════════════════════
function renderMonthTags() {
    const container = $('#month-tags');
    const noMsg = $('#no-months-msg');

    container.querySelectorAll('.month-tag').forEach(t => t.remove());

    if (state.selectedMonths.length === 0) {
        show(noMsg);
    } else {
        hide(noMsg);
        const sorted = [...state.selectedMonths].sort();
        sorted.forEach(month => {
            const tag = document.createElement('span');
            tag.className = 'month-tag';
            tag.innerHTML = `${formatMonth(month)} <span class="remove-icon">×</span>`;
            tag.addEventListener('click', () => removeMonth(month));
            container.appendChild(tag);
        });
    }

    $('#btn-next-3').disabled = state.selectedMonths.length === 0;
}

function formatMonth(monthStr) {
    const [y, m] = monthStr.split('-');
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return `${months[parseInt(m) - 1]}/${y}`;
}

function addMonth(month) {
    if (month && !state.selectedMonths.includes(month)) {
        state.selectedMonths.push(month);
        state.selectedMonths.sort();
        renderMonthTags();
    }
}

function removeMonth(month) {
    state.selectedMonths = state.selectedMonths.filter(m => m !== month);
    renderMonthTags();
}

$('#btn-add-month')?.addEventListener('click', () => {
    const input = $('#month-input');
    if (input.value) {
        addMonth(input.value);
        input.value = '';
    }
});

$('#month-input')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        e.preventDefault();
        $('#btn-add-month').click();
    }
});

$$('.preset-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const numMonths = parseInt(btn.dataset.months);
        state.selectedMonths = [];
        const now = new Date();
        for (let i = numMonths; i >= 1; i--) {
            const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
            const m = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
            state.selectedMonths.push(m);
        }
        renderMonthTags();
    });
});

$('#btn-next-3')?.addEventListener('click', () => goToStep(4));
$('#btn-back-2')?.addEventListener('click', () => goToStep(2));

// ══════════════════════════════════════════
// STEP 4: GENERATE REPORT
// ══════════════════════════════════════════
function prepareStep4() {
    $('#summary-project').textContent = state.projectId;
    $('#summary-aoi').textContent = state.aoiId;
    const sorted = [...state.selectedMonths].sort();
    $('#summary-period').textContent = `${formatMonth(sorted[0])} → ${formatMonth(sorted[sorted.length - 1])}`;
    $('#summary-months-count').textContent = `${sorted.length} month(s)`;

    show('#pre-generate');
    hide('#generating');
    hide('#error-view');
}

$('#btn-back-3')?.addEventListener('click', () => goToStep(3));

$('#btn-generate')?.addEventListener('click', generateReport);
$('#btn-retry')?.addEventListener('click', generateReport);

$('#btn-back-error')?.addEventListener('click', () => {
    show('#pre-generate');
    hide('#error-view');
});

$('#btn-new-report')?.addEventListener('click', () => {
    state.csvDataB64 = null;
    state.selectedMonths = [];
    state.projectId = '';
    state.aoiId = '';
    $('#project-id').value = '';
    $('#aoi-id').value = '';
    renderMonthTags();
    goToStep(2);
});

function downloadBase64CSV(b64, filename) {
    const bin = window.atob(b64);
    const blob = new Blob([bin], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

$('#btn-download-csv')?.addEventListener('click', () => {
    if (state.csvDataB64) {
        downloadBase64CSV(state.csvDataB64, `tourism_${state.aoiId}_data.csv`);
    }
});

// ══════════════════════════════════════════
// REPORT GENERATION
// ══════════════════════════════════════════
async function generateReport() {
    hide('#pre-generate');
    hide('#results');
    hide('#error-view');
    show('#generating');

    const logArea = $('#log-area');
    logArea.innerHTML = '';

    const progressBar = $('#progress-bar');
    const progressLabel = $('#progress-label');
    const progressPercent = $('#progress-percent');

    function log(msg, type = '') {
        const entry = document.createElement('div');
        entry.className = `log-entry ${type}`;
        entry.textContent = msg;
        logArea.appendChild(entry);
        logArea.scrollTop = logArea.scrollHeight;
    }

    function setProgress(pct, label) {
        progressBar.style.width = `${pct}%`;
        progressLabel.textContent = label;
        progressPercent.textContent = `${Math.round(pct)}%`;
    }

    try {
        log('🔐 Authenticating...', 'info');
        setProgress(5, 'Authenticating...');

        log(`📋 Project: ${state.projectId}`, 'info');
        log(`📍 AOI: ${state.aoiId}`, 'info');
        log(`📅 Months: ${state.selectedMonths.join(', ')}`, 'info');

        setProgress(10, 'Sending request to server...');
        log('📡 Sending tourism report request...', 'info');

        let progressValue = 10;
        const progressInterval = setInterval(() => {
            if (progressValue < 85) {
                progressValue += Math.random() * 3;
                setProgress(progressValue, 'Fetching tourism data & generating charts...');
            }
        }, 1000);

        const res = await fetch('/api/tourism-report/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                token: state.token,
                root_url: state.rootUrl,
                project_id: state.projectId,
                aoi_id: state.aoiId,
                months: state.selectedMonths
            })
        });

        clearInterval(progressInterval);

        const data = await res.json();

        if (!res.ok || !data.success) {
            throw new Error(data.detail || data.error || `Server error (${res.status})`);
        }

        setProgress(90, 'Processing charts...');
        log('📊 Receiving chart data...', 'info');

        state.csvDataB64 = data.summary.csv_data || null;

        setProgress(100, 'Done!');
        log('✅ Tourism report generated successfully!', 'success');

        setTimeout(() => {
            showResults(data.summary);
        }, 500);

    } catch (e) {
        log(`❌ Error: ${e.message}`, 'error');
        setTimeout(() => {
            hide('#generating');
            show('#error-view');
            $('#error-message').textContent = e.message;
        }, 500);
    }
}

function showResults(summary) {
    hide('#generating');
    hide('#wizard-card');
    show('#results');

    // Scroll to top
    window.scrollTo({ top: 0, behavior: 'smooth' });

    // Result info
    $('#result-info').innerHTML = `Tourism report for <strong>${state.aoiId}</strong> generated with <strong>${summary.months_processed}</strong> month(s) of data.`;

    // Summary stats
    const statsContainer = $('#summary-stats');
    statsContainer.innerHTML = '';

    if (summary) {
        const stats = [
            { value: summary.total_days || '—', label: 'Total Days' },
            { value: summary.months_processed || '—', label: 'Months' },
            { value: summary.visitors_daily_mean ? Number(summary.visitors_daily_mean).toLocaleString('en', { maximumFractionDigits: 0 }) : '—', label: 'Visitors Daily Avg' },
            { value: summary.visitors_daily_max ? Number(summary.visitors_daily_max).toLocaleString('en', { maximumFractionDigits: 0 }) : '—', label: 'Visitors Daily Max' },
            { value: summary.tourists_daily_mean ? Number(summary.tourists_daily_mean).toLocaleString('en', { maximumFractionDigits: 0 }) : '—', label: 'Tourists Daily Avg' },
            { value: summary.hikers_daily_mean ? Number(summary.hikers_daily_mean).toLocaleString('en', { maximumFractionDigits: 0 }) : '—', label: 'Hikers Daily Avg' },
        ];

        stats.forEach(s => {
            const div = document.createElement('div');
            div.className = 'summary-stat';
            div.innerHTML = `
                <div class="summary-stat-value">${s.value}</div>
                <div class="summary-stat-label">${s.label}</div>
            `;
            statsContainer.appendChild(div);
        });
    }

    // Load all 12 chart images
    const chartKeys = [
        'visitors_total', 'visitors_national', 'visitors_local', 'visitors_international',
        'tourist_total', 'tourist_national', 'tourist_local', 'tourist_international',
        'hiker_total', 'hiker_national', 'hiker_local', 'hiker_international'
    ];

    if (summary.charts) {
        chartKeys.forEach(key => {
            const img = $(`#chart-${key}`);
            if (img && summary.charts[key]) {
                img.src = `data:image/png;base64,${summary.charts[key]}`;
            }
        });
    }
}

// ══════════════════════════════════════════
// INIT
// ══════════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => {
    renderMonthTags();

    const now = new Date();
    const lastMonth = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    const monthInput = $('#month-input');
    if (monthInput) {
        monthInput.value = `${lastMonth.getFullYear()}-${String(lastMonth.getMonth() + 1).padStart(2, '0')}`;
    }
});
