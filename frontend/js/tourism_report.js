/**
 * AOI Tourism Report - Frontend JavaScript
 * Handles wizard navigation, per-month API fetching with live feedback, and chart display
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
        state.selectedMonths = [];
        const now = new Date();

        if (btn.dataset.months) {
            // Last N months
            const numMonths = parseInt(btn.dataset.months);
            for (let i = numMonths; i >= 1; i--) {
                const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
                const m = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
                state.selectedMonths.push(m);
            }
        } else if (btn.dataset.year) {
            // Full year (Jan–Dec)
            const year = parseInt(btn.dataset.year);
            for (let m = 1; m <= 12; m++) {
                state.selectedMonths.push(`${year}-${String(m).padStart(2, '0')}`);
            }
        } else if (btn.dataset.range) {
            // Custom range "YYYY-MM,YYYY-MM"
            const [startStr, endStr] = btn.dataset.range.split(',');
            const [sy, sm] = startStr.split('-').map(Number);
            const [ey, em] = endStr.split('-').map(Number);
            let cur = new Date(sy, sm - 1, 1);
            const end = new Date(ey, em - 1, 1);
            while (cur <= end) {
                state.selectedMonths.push(`${cur.getFullYear()}-${String(cur.getMonth() + 1).padStart(2, '0')}`);
                cur.setMonth(cur.getMonth() + 1);
            }
        } else if (btn.dataset.ytd) {
            // Year-to-date: Jan of that year up to last completed month
            const year = parseInt(btn.dataset.ytd);
            const lastMonth = (year === now.getFullYear()) ? now.getMonth() : 12;
            for (let m = 1; m <= lastMonth; m++) {
                state.selectedMonths.push(`${year}-${String(m).padStart(2, '0')}`);
            }
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
// REPORT GENERATION (per-month fetching)
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
        log('🔐 Authenticated. Starting data download...', 'info');
        log(`📋 Project: ${state.projectId}`, 'info');
        log(`📍 AOI: ${state.aoiId}`, 'info');

        const sortedMonths = [...state.selectedMonths].sort();
        const totalMonths = sortedMonths.length;
        const csvDataList = [];
        const failedMonths = [];
        const slowMonths = [];

        // ── Phase 1: Fetch each month individually with live feedback ──
        for (let i = 0; i < totalMonths; i++) {
            const month = sortedMonths[i];
            const pctBase = (i / totalMonths) * 80;  // 0-80% for fetching
            const pctNext = ((i + 1) / totalMonths) * 80;

            setProgress(pctBase, `Downloading ${formatMonth(month)} (${i + 1}/${totalMonths})...`);
            log(`📆 Fetching ${formatMonth(month)} (${i + 1}/${totalMonths})...`, 'info');

            try {
                const res = await fetch('/api/tourism-report/fetch-month', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        token: state.token,
                        root_url: state.rootUrl,
                        project_id: state.projectId,
                        aoi_id: state.aoiId,
                        month: month
                    })
                });

                const result = await res.json();

                if (result.success) {
                    csvDataList.push(result.data);
                    if (result.was_slow) {
                        slowMonths.push(month);
                        log(`⏳ ${result.message}`, 'info');
                    } else {
                        log(`${result.message}`, 'success');
                    }
                } else {
                    failedMonths.push(month);
                    log(`${result.message}`, 'error');
                }
            } catch (e) {
                failedMonths.push(month);
                log(`❌ ${formatMonth(month)} — connection error: ${e.message}`, 'error');
            }

            setProgress(pctNext, `Downloaded ${i + 1}/${totalMonths} months`);
        }

        // Check if we have any data
        if (csvDataList.length === 0) {
            throw new Error('No data was returned for any of the selected months. Please check the project/AOI settings or try different months.');
        }

        // Show warnings for failed months
        if (failedMonths.length > 0) {
            log(`⚠️ ${failedMonths.length} month(s) had no data: ${failedMonths.map(formatMonth).join(', ')}`, 'error');
            log(`   Continuing with ${csvDataList.length} month(s) of available data...`, 'info');
        }

        // ── Phase 2: Generate charts from fetched data ──
        setProgress(85, 'Generating 15 charts...');
        log('📊 Generating charts from downloaded data...', 'info');

        const chartRes = await fetch('/api/tourism-report/generate-charts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                project_id: state.projectId,
                aoi_id: state.aoiId,
                csv_data: csvDataList,
                months_count: csvDataList.length
            })
        });

        const chartData = await chartRes.json();

        if (!chartRes.ok || !chartData.success) {
            throw new Error(chartData.detail || chartData.error || `Chart generation failed (${chartRes.status})`);
        }

        state.csvDataB64 = chartData.summary.csv_data || null;

        setProgress(100, 'Done!');
        log('✅ Tourism report generated successfully!', 'success');

        if (failedMonths.length > 0) {
            chartData.summary.failed_months = failedMonths.map(formatMonth);
        }

        setTimeout(() => {
            showResults(chartData.summary);
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

    window.scrollTo({ top: 0, behavior: 'smooth' });

    let infoHtml = `Tourism report for <strong>${state.aoiId}</strong> generated with <strong>${summary.months_processed}</strong> month(s) of data.`;
    if (summary.failed_months && summary.failed_months.length > 0) {
        infoHtml += `<br><br><span style="color: var(--warning);">⚠️ Months with no data: <strong>${summary.failed_months.join(', ')}</strong>. These were skipped.</span>`;
    }
    $('#result-info').innerHTML = infoHtml;

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

    // Load all 15 chart images
    const chartKeys = [
        'visitors_total', 'visitors_local', 'visitors_regional', 'visitors_national', 'visitors_international',
        'tourist_total', 'tourist_local', 'tourist_regional', 'tourist_national', 'tourist_international',
        'hiker_total', 'hiker_local', 'hiker_regional', 'hiker_national', 'hiker_international'
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
