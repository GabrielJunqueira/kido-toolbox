/**
 * Retail Report Generator - Frontend JavaScript
 * Handles wizard navigation, API calls, and HTML dashboard download
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
    dateMode: 'months',      // 'months' or 'range'
    selectedMonths: [],
    startDate: '',            // YYYY-MM-DD
    endDate: '',              // YYYY-MM-DD
    downloadUrl: null,
    htmlFilename: null
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
        const res = await fetch('/api/login', {
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
    $('#btn-next-2').disabled = !projectId;
}

$('#project-id')?.addEventListener('input', validateStep2);

$('#btn-next-2')?.addEventListener('click', () => {
    state.projectId = $('#project-id').value.trim();
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

    validateStep3();
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
        }
        renderMonthTags();
    });
});

// Date mode toggle
$$('.date-mode-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const mode = btn.dataset.mode;
        state.dateMode = mode;

        // Toggle button styles
        $$('.date-mode-btn').forEach(b => {
            b.classList.remove('btn-primary', 'active');
            b.classList.add('btn-secondary');
        });
        btn.classList.remove('btn-secondary');
        btn.classList.add('btn-primary', 'active');

        // Toggle panels
        if (mode === 'months') {
            show('#date-mode-months');
            hide('#date-mode-range');
        } else {
            hide('#date-mode-months');
            show('#date-mode-range');
        }
        validateStep3();
    });
});

// Date range inputs
$('#date-start')?.addEventListener('change', () => {
    state.startDate = $('#date-start').value;
    validateStep3();
});
$('#date-end')?.addEventListener('change', () => {
    state.endDate = $('#date-end').value;
    validateStep3();
});

// Date range presets
$$('.date-preset-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const days = parseInt(btn.dataset.days);
        const end = new Date();
        end.setDate(end.getDate() - 1); // yesterday
        const start = new Date(end);
        start.setDate(start.getDate() - days + 1);

        const fmt = d => d.toISOString().split('T')[0];
        $('#date-start').value = fmt(start);
        $('#date-end').value = fmt(end);
        state.startDate = fmt(start);
        state.endDate = fmt(end);
        validateStep3();
    });
});

function validateStep3() {
    if (state.dateMode === 'months') {
        $('#btn-next-3').disabled = state.selectedMonths.length === 0;
    } else {
        const valid = state.startDate && state.endDate && state.startDate <= state.endDate;
        $('#btn-next-3').disabled = !valid;
    }
}

$('#btn-next-3')?.addEventListener('click', () => goToStep(4));
$('#btn-back-2')?.addEventListener('click', () => goToStep(2));

// ══════════════════════════════════════════
// STEP 4: GENERATE REPORT
// ══════════════════════════════════════════
function prepareStep4() {
    // Set summary info
    $('#summary-project').textContent = state.projectId;
    if (state.dateMode === 'months') {
        const sorted = [...state.selectedMonths].sort();
        $('#summary-period').textContent = `${formatMonth(sorted[0])} → ${formatMonth(sorted[sorted.length - 1])}`;
        $('#summary-months-count').textContent = `${sorted.length} month(s)`;
    } else {
        $('#summary-period').textContent = `${state.startDate} → ${state.endDate}`;
        // Calculate day count
        const d1 = new Date(state.startDate);
        const d2 = new Date(state.endDate);
        const days = Math.round((d2 - d1) / (86400000)) + 1;
        $('#summary-months-count').textContent = `${days} day(s)`;
    }

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
    state.downloadUrl = null;
    state.htmlFilename = null;
    state.selectedMonths = [];
    state.projectId = '';
    $('#project-id').value = '';
    renderMonthTags();
    goToStep(2);
});

$('#btn-download-html')?.addEventListener('click', () => {
    if (state.downloadUrl) {
        const a = document.createElement('a');
        a.href = state.downloadUrl;
        a.download = state.htmlFilename || 'dashboard.html';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    }
});

$('#btn-print-pdf')?.addEventListener('click', () => {
    const iframe = document.getElementById('html-preview');
    if (iframe && iframe.contentWindow) {
        iframe.contentWindow.focus();
        iframe.contentWindow.print();
    }
});

// ══════════════════════════════════════════
// REPORT GENERATION (SSE for progress, then direct download)
// ══════════════════════════════════════════
function log(msg, type = '') {
    const logArea = $('#log-area');
    const entry = document.createElement('div');
    entry.className = `log-entry ${type}`;
    entry.textContent = msg;
    logArea.appendChild(entry);
    logArea.scrollTop = logArea.scrollHeight;
}

function setProgress(pct, label) {
    $('#progress-bar').style.width = `${pct}%`;
    $('#progress-label').textContent = label;
    $('#progress-percent').textContent = `${Math.round(pct)}%`;
}

async function fetchWithSSE(url, payload) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', url, true);
        xhr.setRequestHeader('Content-Type', 'application/json');

        let lastIndex = 0;

        xhr.onprogress = () => {
            const text = xhr.responseText;
            const newText = text.slice(lastIndex);
            lastIndex = text.length;

            // Split into SSE lines
            const lines = newText.split('\n');
            for (const line of lines) {
                const trimmed = line.trim();
                if (!trimmed.startsWith('data: ')) continue;

                try {
                    const data = JSON.parse(trimmed.substring(6));

                    if (data.status === 'processing') {
                        if (data.progress) setProgress(data.progress, data.message);
                        if (data.message) log(data.message, data.level || 'info');

                    } else if (data.status === 'success') {
                        // Server saved the file; we get a file_id to download
                        resolve({
                            filename: data.filename,
                            file_id: data.file_id,
                            summary: data.summary,
                        });

                    } else if (data.status === 'error') {
                        reject(new Error(data.message));
                    }
                } catch (_) {
                    // Ignore partial / unparseable lines
                }
            }
        };

        xhr.onerror = () => reject(new Error('Network request failed'));
        xhr.onload = () => {
            if (xhr.status >= 400) {
                try {
                    const err = JSON.parse(xhr.responseText);
                    reject(new Error(err.detail || 'Request failed: ' + xhr.status));
                } catch (_) {
                    reject(new Error('Request failed: ' + xhr.status));
                }
            }
        };

        xhr.send(JSON.stringify(payload));
    });
}

async function generateReport() {
    hide('#pre-generate');
    hide('#results');
    hide('#error-view');
    show('#generating');
    $('#log-area').innerHTML = '';

    setProgress(0, 'Starting...');

    try {
        log('🔐 Authenticating...', 'info');
        setProgress(5, 'Authenticating...');

        log(`📋 Project: ${state.projectId}`, 'info');
        if (state.dateMode === 'months') {
            log(`📅 Months: ${state.selectedMonths.join(', ')}`, 'info');
        } else {
            log(`📅 Date range: ${state.startDate} → ${state.endDate}`, 'info');
        }
        log('📡 Initiating generation process, this may take a while...', 'info');

        const payload = {
            token: state.token,
            root_url: state.rootUrl,
            project_id: state.projectId,
        };

        if (state.dateMode === 'months') {
            payload.months = state.selectedMonths;
        } else {
            payload.start_date = state.startDate;
            payload.end_date = state.endDate;
        }

        // SSE stream for progress, returns file_id on success
        const data = await fetchWithSSE('/api/retail-report/generate', payload);

        setProgress(100, 'Done!');
        log('✅ Dashboard generated successfully!', 'success');

        // Build download URL from the file_id
        state.downloadUrl = `/api/retail-report/download/${data.file_id}`;
        state.htmlFilename = data.filename;

        setTimeout(() => {
            showResults(data.filename, data.summary);
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

function showResults(filename, summary) {
    hide('#generating');
    show('#results');

    $('#result-info').innerHTML = `
        Dashboard <strong>${filename}</strong> generated successfully.<br>
        Polygons processed: ${summary ? summary.polygons : 'N/A'}<br>
        Polygons failed: ${summary ? summary.failed : 'N/A'}
    `;

    // Show preview in iframe via download URL
    const preview = $('#html-preview');
    if (state.downloadUrl) {
        preview.src = state.downloadUrl;
        show('#html-preview-container');
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
