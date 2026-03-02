/**
 * AOI Report Generator - Frontend JavaScript
 * Handles wizard navigation, API calls, and PDF download
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
    pdfBlobUrl: null,
    pdfFilename: null,
    csvDailyB64: null,
    csvMonthlyB64: null
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

    // Update stepper UI
    $$('.stepper-step').forEach(s => {
        const stepNum = parseInt(s.dataset.step);
        s.classList.remove('active', 'completed');
        if (stepNum === step) s.classList.add('active');
        else if (stepNum < step) s.classList.add('completed');
    });

    // Update content
    $$('.step-content').forEach(c => c.classList.remove('active'));
    $(`#step-${step}`)?.classList.add('active');

    // Prepare step-specific content
    if (step === 4) {
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
        const res = await fetch('/api/report/login', {
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

    // Remove existing tags (keep the message)
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

// Allow Enter to add month
$('#month-input')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        e.preventDefault();
        $('#btn-add-month').click();
    }
});

// Quick presets
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
    // Set summary info
    $('#summary-project').textContent = state.projectId;
    $('#summary-aoi').textContent = state.aoiId;
    const sorted = [...state.selectedMonths].sort();
    $('#summary-period').textContent = `${formatMonth(sorted[0])} → ${formatMonth(sorted[sorted.length - 1])}`;
    $('#summary-months-count').textContent = `${sorted.length} month(s)`;

    // Reset views
    show('#pre-generate');
    hide('#generating');
    hide('#results');
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
    // Clean up
    if (state.pdfBlobUrl) URL.revokeObjectURL(state.pdfBlobUrl);
    state.pdfBlobUrl = null;
    state.csvDailyB64 = null;
    state.csvMonthlyB64 = null;
    state.selectedMonths = [];
    state.projectId = '';
    state.aoiId = '';
    $('#project-id').value = '';
    $('#aoi-id').value = '';
    renderMonthTags();
    goToStep(2);
});

$('#btn-download-pdf')?.addEventListener('click', () => {
    if (state.pdfBlobUrl) {
        const a = document.createElement('a');
        a.href = state.pdfBlobUrl;
        a.download = state.pdfFilename || 'report.pdf';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    }
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

$('#btn-download-daily-csv')?.addEventListener('click', () => {
    if (state.csvDailyB64) {
        const tag = `${state.aoiId}_daily`;
        downloadBase64CSV(state.csvDailyB64, `${tag}.csv`);
    }
});

$('#btn-download-monthly-csv')?.addEventListener('click', () => {
    if (state.csvMonthlyB64) {
        const tag = `${state.aoiId}_monthly`;
        downloadBase64CSV(state.csvMonthlyB64, `${tag}.csv`);
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
        log('📡 Sending report generation request...', 'info');

        // Simulate progress while waiting
        let progressValue = 10;
        const progressInterval = setInterval(() => {
            if (progressValue < 85) {
                progressValue += Math.random() * 3;
                setProgress(progressValue, 'Fetching data & generating charts...');
            }
        }, 1000);

        const res = await fetch('/api/report/generate', {
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

        setProgress(90, 'Processing PDF...');
        log('📄 Receiving PDF...', 'info');

        // Decode base64 PDF
        const binaryString = window.atob(data.pdf_base64);
        const bytes = new Uint8Array(binaryString.length);
        for (let i = 0; i < binaryString.length; i++) {
            bytes[i] = binaryString.charCodeAt(i);
        }
        const blob = new Blob([bytes], { type: 'application/pdf' });

        setProgress(95, 'Preparing preview...');
        log('✅ Report generated successfully!', 'success');

        // Create blob URL
        if (state.pdfBlobUrl) URL.revokeObjectURL(state.pdfBlobUrl);
        state.pdfBlobUrl = URL.createObjectURL(blob);
        state.pdfFilename = data.filename;

        // Store CSV data
        state.csvDailyB64 = data.summary.csv_daily || null;
        state.csvMonthlyB64 = data.summary.csv_monthly || null;

        setProgress(100, 'Done!');

        // Show results
        setTimeout(() => {
            showResults(data.summary, blob.size, data.filename);
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

function showResults(summary, fileSize, filename) {
    hide('#generating');
    show('#results');

    // Result info
    const sizeKB = (fileSize / 1024).toFixed(1);
    $('#result-info').innerHTML = `Report <strong>${filename}</strong> (${sizeKB} KB) generated successfully.`;

    // Summary stats
    const statsContainer = $('#summary-stats');
    statsContainer.innerHTML = '';

    if (summary) {
        const stats = [
            { value: summary.total_days || '—', label: 'Total Days' },
            { value: summary.months_processed || '—', label: 'Months' },
            { value: summary.daily_mean ? Number(summary.daily_mean).toLocaleString('en', { maximumFractionDigits: 0 }) : '—', label: 'Daily Avg' },
            { value: summary.daily_max ? Number(summary.daily_max).toLocaleString('en', { maximumFractionDigits: 0 }) : '—', label: 'Daily Max' },
            { value: summary.daily_min ? Number(summary.daily_min).toLocaleString('en', { maximumFractionDigits: 0 }) : '—', label: 'Daily Min' },
            { value: `${sizeKB} KB`, label: 'PDF Size' },
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

    // PDF preview
    const preview = $('#pdf-preview');
    if (state.pdfBlobUrl) {
        preview.src = state.pdfBlobUrl;
        show('#pdf-preview-container');
    }

    // Chart Images
    if (summary.charts) {
        if (summary.charts.daily_chart) {
            $('#daily-chart-img').src = `data:image/png;base64,${summary.charts.daily_chart}`;
        }
        if (summary.charts.monthly_chart) {
            $('#monthly-chart-img').src = `data:image/png;base64,${summary.charts.monthly_chart}`;
        }
    }

    // Monthly Stats Table
    const tableBody = $('#monthly-stats-table tbody');
    tableBody.innerHTML = '';
    if (summary.monthly_stats && summary.monthly_stats.length > 0) {
        summary.monthly_stats.forEach(m => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td style="font-weight: 500;">${m.month}</td>
                <td>${m.days}</td>
                <td>${Number(m.mean).toLocaleString()}</td>
                <td>${Number(m.median).toLocaleString()}</td>
                <td>${Number(m.max).toLocaleString()}<br><small class="text-muted">${m.max_date}</small></td>
                <td>${Number(m.min).toLocaleString()}<br><small class="text-muted">${m.min_date}</small></td>
                <td>${m.weekday_mean ? Number(m.weekday_mean).toLocaleString() : '-'}</td>
                <td>${m.weekend_mean ? Number(m.weekend_mean).toLocaleString() : '-'}</td>
            `;
            tableBody.appendChild(row);
        });
    }

    // Unique Visitors & Visits Table
    const uniqueBody = $('#unique-data-table tbody');
    uniqueBody.innerHTML = '';
    if (summary.monthly_data && summary.monthly_data.length > 0) {
        summary.monthly_data.forEach(d => {
            const row = document.createElement('tr');
            const uv = d.unique_visitors != null ? Number(d.unique_visitors).toLocaleString() : 'N/A';
            const uvs = d.unique_visits != null ? Number(d.unique_visits).toLocaleString() : 'N/A';
            row.innerHTML = `
                <td style="font-weight: 500;">${formatMonth(d.month)}</td>
                <td>${uv}</td>
                <td>${uvs}</td>
            `;
            uniqueBody.appendChild(row);
        });
    }
}

// ══════════════════════════════════════════
// INIT
// ══════════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => {
    renderMonthTags();

    // Set default month to current minus 1
    const now = new Date();
    const lastMonth = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    const monthInput = $('#month-input');
    if (monthInput) {
        monthInput.value = `${lastMonth.getFullYear()}-${String(lastMonth.getMonth() + 1).padStart(2, '0')}`;
    }
});
