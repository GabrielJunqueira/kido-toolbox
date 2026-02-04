/**
 * Scaling Factor Adjustment Tool
 * Handles login, polygon loading, and scaling factor adjustments
 */

document.addEventListener('DOMContentLoaded', () => {
    // =============================
    // State
    // =============================
    let currentStep = 1;
    let authToken = null;
    let rootUrl = null;
    let brand = null;
    let projectId = null;
    let polygons = [];
    let selectedPolygon = null;

    // =============================
    // DOM Elements
    // =============================
    const stepDots = document.querySelectorAll('.step-dot');
    const stepConnectors = document.querySelectorAll('.step-connector');
    const stepContents = document.querySelectorAll('.step-content');

    // Step 1: Login
    const loginForm = document.getElementById('loginForm');
    const countryGrid = document.getElementById('countryGrid');
    const countryCodeInput = document.getElementById('countryCode');
    const loginBtn = document.getElementById('loginBtn');
    const loginStatus = document.getElementById('loginStatus');

    // Step 2: Project
    const projectForm = document.getElementById('projectForm');
    const projectIdInput = document.getElementById('projectId');
    const brandBadge = document.getElementById('brandBadge');
    const loadPolygonsBtn = document.getElementById('loadPolygonsBtn');
    const projectStatus = document.getElementById('projectStatus');
    const backToStep1 = document.getElementById('backToStep1');

    // Step 3: Polygon Selection
    const polygonSearch = document.getElementById('polygonSearch');
    const polygonTableBody = document.getElementById('polygonTableBody');
    const polygonCount = document.getElementById('polygonCount');
    const emptyPolygons = document.getElementById('emptyPolygons');
    const continueToStep4 = document.getElementById('continueToStep4');
    const backToStep2 = document.getElementById('backToStep2');

    // Step 4: Adjustment
    const adjustmentForm = document.getElementById('adjustmentForm');
    const selectedPolygonInfo = document.getElementById('selectedPolygonInfo');
    const scalingFactorInput = document.getElementById('scalingFactor');
    const validFromInput = document.getElementById('validFrom');
    const validToInput = document.getElementById('validTo');
    const confirmationBox = document.getElementById('confirmationBox');
    const confirmationDetails = document.getElementById('confirmationDetails');
    const previewBtn = document.getElementById('previewBtn');
    const applyBtn = document.getElementById('applyBtn');
    const adjustmentStatus = document.getElementById('adjustmentStatus');
    const backToStep3 = document.getElementById('backToStep3');
    const viewCurrentSFBtn = document.getElementById('viewCurrentSFBtn');
    const currentAdjustmentsModal = document.getElementById('currentAdjustmentsModal');
    const currentAdjustmentsBody = document.getElementById('currentAdjustmentsBody');
    const closeModalBtn = document.getElementById('closeModalBtn');
    const successModal = document.getElementById('successModal');
    const successMessage = document.getElementById('successMessage');
    const continueAdjustingBtn = document.getElementById('continueAdjustingBtn');

    // =============================
    // Step Navigation
    // =============================
    function goToStep(step) {
        currentStep = step;

        // Update step indicators
        stepDots.forEach((dot, index) => {
            dot.classList.remove('active', 'completed');
            if (index + 1 < step) {
                dot.classList.add('completed');
                dot.innerHTML = '✓';
            } else if (index + 1 === step) {
                dot.classList.add('active');
                dot.innerHTML = step;
            } else {
                dot.innerHTML = index + 1;
            }
        });

        stepConnectors.forEach((connector, index) => {
            connector.classList.toggle('completed', index + 1 < step);
        });

        // Show/hide step content
        stepContents.forEach((content, index) => {
            content.classList.toggle('active', index + 1 === step);
        });
    }

    // =============================
    // Country Selection
    // =============================
    countryGrid.addEventListener('click', (e) => {
        const btn = e.target.closest('.country-btn');
        if (!btn) return;

        // Remove selection from all
        countryGrid.querySelectorAll('.country-btn').forEach(b => b.classList.remove('selected'));

        // Select clicked
        btn.classList.add('selected');
        countryCodeInput.value = btn.dataset.country;
    });

    // =============================
    // Step 1: Login
    // =============================
    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        if (!countryCodeInput.value) {
            showStatus(loginStatus, 'Please select a country.', 'error');
            return;
        }

        const email = document.getElementById('email').value;
        const password = document.getElementById('password').value;
        const countryCode = countryCodeInput.value;

        // Loading state
        const originalText = loginBtn.innerHTML;
        loginBtn.disabled = true;
        loginBtn.innerHTML = `
            <svg class="animate-spin" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
            </svg>
            Connecting...
        `;

        try {
            const response = await fetch('/api/scaling-factor/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    email,
                    password,
                    country_code: countryCode
                })
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || 'Login failed');
            }

            // Store auth info
            authToken = data.token;
            rootUrl = data.root_url;
            brand = data.brand;

            // Update UI
            brandBadge.textContent = `${brand.toUpperCase()}-${countryCode.toUpperCase()}`;
            showStatus(loginStatus, 'Connected successfully!', 'success');

            // Go to step 2
            setTimeout(() => goToStep(2), 500);

        } catch (error) {
            showStatus(loginStatus, error.message, 'error');
        } finally {
            loginBtn.disabled = false;
            loginBtn.innerHTML = originalText;
        }
    });

    // =============================
    // Step 2: Load Polygons
    // =============================
    projectForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        projectId = projectIdInput.value.trim();
        if (!projectId) {
            showStatus(projectStatus, 'Please enter a project UUID.', 'error');
            return;
        }

        // Loading state
        const originalText = loadPolygonsBtn.innerHTML;
        loadPolygonsBtn.disabled = true;
        loadPolygonsBtn.innerHTML = `
            <svg class="animate-spin" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
            </svg>
            Loading...
        `;

        try {
            const response = await fetch(`/api/scaling-factor/polygons/${projectId}`, {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${authToken}`,
                    'x-root-url': rootUrl
                }
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || 'Failed to load polygons');
            }

            // Filter only AOI- polygons
            polygons = (data.polygons || []).filter(p => p.polygon_id.startsWith('AOI-'));

            if (polygons.length === 0) {
                showStatus(projectStatus, 'No AOI polygons found in this project.', 'warning');
                return;
            }

            // Render polygons
            renderPolygonTable(polygons);
            polygonCount.textContent = `${polygons.length} AOI polygons`;

            // Go to step 3
            goToStep(3);

        } catch (error) {
            showStatus(projectStatus, error.message, 'error');
        } finally {
            loadPolygonsBtn.disabled = false;
            loadPolygonsBtn.innerHTML = originalText;
        }
    });

    backToStep1.addEventListener('click', () => goToStep(1));

    // =============================
    // Step 3: Polygon Selection
    // =============================
    function renderPolygonTable(polygonsToRender) {
        if (polygonsToRender.length === 0) {
            polygonTableBody.innerHTML = '';
            emptyPolygons.classList.remove('hidden');
            return;
        }

        emptyPolygons.classList.add('hidden');

        // Sort by polygon_id
        polygonsToRender.sort((a, b) => a.polygon_id.localeCompare(b.polygon_id, undefined, { numeric: true }));

        polygonTableBody.innerHTML = polygonsToRender.map(polygon => `
            <tr class="polygon-row" data-uuid="${polygon.uuid}" data-polygon-id="${polygon.polygon_id}" data-name="${polygon.name}">
                <td class="polygon-id">${polygon.polygon_id}</td>
                <td>${polygon.name || '—'}</td>
                <td class="polygon-uuid">${polygon.uuid}</td>
            </tr>
        `).join('');
    }

    // Search filter
    polygonSearch.addEventListener('input', (e) => {
        const query = e.target.value.toLowerCase();
        const filtered = polygons.filter(p =>
            p.polygon_id.toLowerCase().includes(query) ||
            (p.name && p.name.toLowerCase().includes(query))
        );
        renderPolygonTable(filtered);
    });

    // Row selection
    polygonTableBody.addEventListener('click', (e) => {
        const row = e.target.closest('.polygon-row');
        if (!row) return;

        // Remove previous selection
        polygonTableBody.querySelectorAll('.polygon-row').forEach(r => r.classList.remove('selected'));

        // Select current
        row.classList.add('selected');

        selectedPolygon = {
            uuid: row.dataset.uuid,
            polygon_id: row.dataset.polygonId,
            name: row.dataset.name
        };

        continueToStep4.disabled = false;
    });

    continueToStep4.addEventListener('click', () => {
        if (!selectedPolygon) return;

        // Update selected polygon info
        selectedPolygonInfo.innerHTML = `
            <div class="flex items-center justify-between">
                <div>
                    <span class="polygon-id">${selectedPolygon.polygon_id}</span>
                    <span class="text-secondary ml-sm">${selectedPolygon.name || ''}</span>
                </div>
                <span class="polygon-uuid">${selectedPolygon.uuid}</span>
            </div>
        `;

        goToStep(4);
    });

    backToStep2.addEventListener('click', () => goToStep(2));

    // =============================
    // Step 4: Adjustment
    // =============================
    previewBtn.addEventListener('click', () => {
        const scalingFactor = parseFloat(scalingFactorInput.value);
        const validFrom = validFromInput.value;
        const validTo = validToInput.value;

        if (!scalingFactor || !validFrom || !validTo) {
            showStatus(adjustmentStatus, 'Please fill in all fields.', 'error');
            return;
        }

        if (new Date(validFrom) > new Date(validTo)) {
            showStatus(adjustmentStatus, 'Valid From date must be before Valid To date.', 'error');
            return;
        }

        // Show confirmation
        confirmationDetails.innerHTML = `
            <div class="confirmation-item">
                <span class="confirmation-label">Polygon</span>
                <span class="confirmation-value">${selectedPolygon.polygon_id} (${selectedPolygon.name || 'No name'})</span>
            </div>
            <div class="confirmation-item">
                <span class="confirmation-label">Scaling Factor</span>
                <span class="confirmation-value">${scalingFactor}</span>
            </div>
            <div class="confirmation-item">
                <span class="confirmation-label">Valid From</span>
                <span class="confirmation-value">${validFrom}</span>
            </div>
            <div class="confirmation-item">
                <span class="confirmation-label">Valid To</span>
                <span class="confirmation-value">${validTo}</span>
            </div>
        `;

        confirmationBox.style.display = 'block';
        applyBtn.disabled = false;
        adjustmentStatus.classList.add('hidden');
    });

    adjustmentForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        const scalingFactor = parseFloat(scalingFactorInput.value);
        const validFrom = validFromInput.value;
        const validTo = validToInput.value;

        // Loading state
        const originalText = applyBtn.innerHTML;
        applyBtn.disabled = true;
        applyBtn.innerHTML = `
            <svg class="animate-spin" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
            </svg>
            Applying...
        `;

        try {
            const response = await fetch('/api/scaling-factor/adjust', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${authToken}`,
                    'x-root-url': rootUrl
                },
                body: JSON.stringify({
                    project_id: projectId,
                    polygon_uuid: selectedPolygon.uuid,
                    valid_from: validFrom,
                    valid_to: validTo,
                    scaling_factor: scalingFactor
                })
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || 'Failed to apply adjustment');
            }

            // Show success modal
            successMessage.textContent = `Scaling factor ${scalingFactor} applied to ${selectedPolygon.polygon_id} for ${validFrom} to ${validTo}.`;
            successModal.style.display = 'flex';

            // Reset form for another adjustment
            confirmationBox.style.display = 'none';
            scalingFactorInput.value = '';
            validFromInput.value = '';
            validToInput.value = '';

        } catch (error) {
            showStatus(adjustmentStatus, error.message, 'error');
        } finally {
            applyBtn.disabled = true;
            applyBtn.innerHTML = originalText;
        }
    });

    backToStep3.addEventListener('click', () => {
        confirmationBox.style.display = 'none';
        applyBtn.disabled = true;
        adjustmentStatus.classList.add('hidden');
        goToStep(3);
    });

    // =============================
    // Utilities
    // =============================
    function showStatus(element, message, type) {
        const bgColors = {
            success: 'bg-green-50 text-green-600',
            error: 'bg-red-50 text-red-600',
            warning: 'bg-yellow-50 text-yellow-600'
        };

        element.textContent = message;
        element.className = `mt-lg p-md rounded-md text-sm ${bgColors[type] || ''}`;
        element.classList.remove('hidden');
    }

    // =============================
    // View Current Adjustments
    // =============================
    if (viewCurrentSFBtn) {
        viewCurrentSFBtn.addEventListener('click', async () => {
            if (!projectId || !authToken) {
                showStatus(projectStatus, 'Please load a project first.', 'error');
                return;
            }

            const originalText = viewCurrentSFBtn.innerHTML;
            viewCurrentSFBtn.disabled = true;
            viewCurrentSFBtn.innerHTML = `
                <svg class="animate-spin" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
                </svg>
                Loading...
            `;

            try {
                const response = await fetch(`/api/scaling-factor/current-adjustments/${projectId}`, {
                    method: 'GET',
                    headers: {
                        'Authorization': `Bearer ${authToken}`,
                        'x-root-url': rootUrl
                    }
                });

                const data = await response.json();

                if (!response.ok) {
                    throw new Error(data.detail || 'Failed to load adjustments');
                }

                const adjustments = data.adjustments || [];

                if (adjustments.length === 0) {
                    currentAdjustmentsBody.innerHTML = `
                        <tr>
                            <td colspan="4" class="text-center text-secondary" style="padding: 2rem;">
                                No scaling factor adjustments found for this project.
                            </td>
                        </tr>
                    `;
                } else {
                    currentAdjustmentsBody.innerHTML = adjustments.map(adj => `
                        <tr>
                            <td class="polygon-id">${adj.polygon_user_id}</td>
                            <td>${adj.scaling_factor}</td>
                            <td>${adj.valid_from} → ${adj.valid_to}</td>
                            <td class="text-secondary text-sm">${new Date(adj.committed_at).toLocaleDateString()}</td>
                        </tr>
                    `).join('');
                }

                currentAdjustmentsModal.style.display = 'flex';

            } catch (error) {
                showStatus(projectStatus, error.message, 'error');
            } finally {
                viewCurrentSFBtn.disabled = false;
                viewCurrentSFBtn.innerHTML = originalText;
            }
        });
    }

    if (closeModalBtn) {
        closeModalBtn.addEventListener('click', () => {
            currentAdjustmentsModal.style.display = 'none';
        });
    }

    // Close modal on backdrop click
    if (currentAdjustmentsModal) {
        currentAdjustmentsModal.addEventListener('click', (e) => {
            if (e.target === currentAdjustmentsModal) {
                currentAdjustmentsModal.style.display = 'none';
            }
        });
    }

    // Success modal handlers
    if (continueAdjustingBtn) {
        continueAdjustingBtn.addEventListener('click', () => {
            successModal.style.display = 'none';
            goToStep(3);  // Go back to polygon selection
        });
    }

    if (successModal) {
        successModal.addEventListener('click', (e) => {
            if (e.target === successModal) {
                successModal.style.display = 'none';
            }
        });
    }
});
