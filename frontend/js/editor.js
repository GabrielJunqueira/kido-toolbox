// Map Viewer Logic — Enhanced with dual-range sliders
let map;
let drawnItems;

// Glify layer references (for destroy/recreate)
let nodeGlifyInstance = null;
let antennaGlifyInstance = null;

// Radius circles layer group
let radiusLayerGroup = null;

// Store raw data for re-rendering with filters
let currentData = null;

document.addEventListener('DOMContentLoaded', () => {
    initMap();
    setupEventListeners();
});

// ─── Map Initialization ────────────────────────────────────────
function initMap() {
    map = L.map('map').setView([-22.9, -43.2], 10);

    // CartoDB Positron
    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png?v=2', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
        subdomains: 'abcd',
        maxZoom: 20
    }).addTo(map);

    document.getElementById('map').style.backgroundColor = 'white';

    // FeatureGroup for editable polygon layers
    drawnItems = new L.FeatureGroup();
    map.addLayer(drawnItems);

    // Radius circles layer
    radiusLayerGroup = new L.LayerGroup();
    map.addLayer(radiusLayerGroup);

    // Draw Controls
    const drawControl = new L.Control.Draw({
        edit: { featureGroup: drawnItems },
        draw: {
            polygon: { allowIntersection: false, showArea: true },
            polyline: false,
            rectangle: false,
            circle: false,
            marker: false,
            circlemarker: false
        }
    });
    map.addControl(drawControl);

    map.on(L.Draw.Event.CREATED, (e) => {
        drawnItems.addLayer(e.layer);
    });
}

// ─── Event Listeners ───────────────────────────────────────────
function setupEventListeners() {
    const form = document.getElementById('uploadForm');
    const loadBtn = document.getElementById('loadBtn');
    const loadingOverlay = document.getElementById('loadingOverlay');
    const layerControl = document.getElementById('layerControl');
    const exportBtn = document.getElementById('exportBtn');
    const refreshBtn = document.getElementById('refreshBtn');
    const fullscreenBtn = document.getElementById('fullscreenBtn');

    // ── Upload Form ──
    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const polyFile = document.getElementById('polyFile').files[0];
        if (!polyFile) return;

        loadingOverlay.classList.remove('hidden');
        loadBtn.disabled = true;

        const formData = new FormData(form);

        try {
            const response = await fetch('/api/editor/process', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || 'Processing failed');
            }

            const data = await response.json();
            currentData = data;

            // Configure dual-range sliders from the data
            configureDualSliders(data);

            // Initial render
            applyFilters();

            // Show controls panel
            layerControl.classList.remove('hidden');

        } catch (error) {
            console.error(error);
            alert(`Error: ${error.message}`);
        } finally {
            loadingOverlay.classList.add('hidden');
            loadBtn.disabled = false;
        }
    });

    // ── Refresh Button ──
    refreshBtn.addEventListener('click', () => {
        if (!currentData) return;
        applyFilters();
    });

    // ── Dual-range slider events ──
    setupDualRange('nodeMin', 'nodeMax', 'nodeMinVal', 'nodeMaxVal', 'nodeFill');
    setupDualRange('antMin', 'antMax', 'antMinVal', 'antMaxVal', 'antFill');

    // ── Layer Toggles (immediate) ──
    document.getElementById('showPolygons').addEventListener('change', (e) => {
        if (e.target.checked) map.addLayer(drawnItems);
        else map.removeLayer(drawnItems);
    });

    document.getElementById('showNodes').addEventListener('change', (e) => {
        toggleNodeLayer(e.target.checked);
    });

    document.getElementById('showAntennas').addEventListener('change', (e) => {
        toggleAntennaLayer(e.target.checked);
    });

    document.getElementById('showRadius').addEventListener('change', (e) => {
        if (e.target.checked) map.addLayer(radiusLayerGroup);
        else map.removeLayer(radiusLayerGroup);
    });

    // ── Fullscreen ──
    fullscreenBtn.addEventListener('click', toggleFullscreen);
    document.addEventListener('fullscreenchange', onFullscreenChange);
    document.addEventListener('webkitfullscreenchange', onFullscreenChange);

    // ── Export ──
    exportBtn.addEventListener('click', exportGeoJSON);
}

// ─── Dual Range Slider Setup ───────────────────────────────────
function setupDualRange(minId, maxId, minValId, maxValId, fillId) {
    const minInput = document.getElementById(minId);
    const maxInput = document.getElementById(maxId);
    const minValEl = document.getElementById(minValId);
    const maxValEl = document.getElementById(maxValId);
    const fillEl = document.getElementById(fillId);

    function update() {
        let minVal = parseInt(minInput.value);
        let maxVal = parseInt(maxInput.value);

        // Prevent crossover
        if (minVal > maxVal) {
            // Determine which one was moved and clamp it
            minInput.value = maxVal;
            minVal = maxVal;
        }

        // Update display badges
        minValEl.textContent = minVal;
        maxValEl.textContent = maxVal;

        // Update fill bar position
        const rangeMax = parseInt(minInput.max) || 1;
        const leftPercent = (minVal / rangeMax) * 100;
        const rightPercent = (maxVal / rangeMax) * 100;
        fillEl.style.left = leftPercent + '%';
        fillEl.style.width = (rightPercent - leftPercent) + '%';
    }

    minInput.addEventListener('input', () => {
        if (parseInt(minInput.value) > parseInt(maxInput.value)) {
            minInput.value = maxInput.value;
        }
        update();
    });

    maxInput.addEventListener('input', () => {
        if (parseInt(maxInput.value) < parseInt(minInput.value)) {
            maxInput.value = minInput.value;
        }
        update();
    });

    // Initial paint
    update();
}

// ─── Configure Dual Sliders ────────────────────────────────────
function configureDualSliders(data) {
    let maxNodes = 0;
    let maxAntennas = 0;

    if (data.polygons && data.polygons.features) {
        data.polygons.features.forEach(f => {
            const nc = f.properties.node_count || 0;
            const ac = f.properties.antenna_count || 0;
            if (nc > maxNodes) maxNodes = nc;
            if (ac > maxAntennas) maxAntennas = ac;
        });
    }

    // Nodes range
    const nodeMin = document.getElementById('nodeMin');
    const nodeMax = document.getElementById('nodeMax');
    nodeMin.min = 0; nodeMin.max = maxNodes; nodeMin.value = 0;
    nodeMax.min = 0; nodeMax.max = maxNodes; nodeMax.value = maxNodes;
    document.getElementById('nodeMinVal').textContent = '0';
    document.getElementById('nodeMaxVal').textContent = maxNodes;

    // Antennas range
    const antMin = document.getElementById('antMin');
    const antMax = document.getElementById('antMax');
    antMin.min = 0; antMin.max = maxAntennas; antMin.value = 0;
    antMax.min = 0; antMax.max = maxAntennas; antMax.value = maxAntennas;
    document.getElementById('antMinVal').textContent = '0';
    document.getElementById('antMaxVal').textContent = maxAntennas;

    // Update fills
    updateFill('nodeMin', 'nodeMax', 'nodeFill');
    updateFill('antMin', 'antMax', 'antFill');
}

function updateFill(minId, maxId, fillId) {
    const minInput = document.getElementById(minId);
    const maxInput = document.getElementById(maxId);
    const fillEl = document.getElementById(fillId);
    const rangeMax = parseInt(minInput.max) || 1;
    const leftPercent = (parseInt(minInput.value) / rangeMax) * 100;
    const rightPercent = (parseInt(maxInput.value) / rangeMax) * 100;
    fillEl.style.left = leftPercent + '%';
    fillEl.style.width = (rightPercent - leftPercent) + '%';
}

// ─── Apply Filters & Re-render ─────────────────────────────────
function applyFilters() {
    if (!currentData) return;

    const minNodes = parseInt(document.getElementById('nodeMin').value, 10);
    const maxNodes = parseInt(document.getElementById('nodeMax').value, 10);
    const minAntennas = parseInt(document.getElementById('antMin').value, 10);
    const maxAntennas = parseInt(document.getElementById('antMax').value, 10);

    // Filter polygons by dual range
    const allFeatures = currentData.polygons.features;
    const filtered = allFeatures.filter(f => {
        const nc = f.properties.node_count || 0;
        const ac = f.properties.antenna_count || 0;
        return nc >= minNodes && nc <= maxNodes && ac >= minAntennas && ac <= maxAntennas;
    });

    const filteredGeoJSON = {
        type: 'FeatureCollection',
        features: filtered
    };

    // Determine which layers are visible
    const showPolygons = document.getElementById('showPolygons').checked;
    const showNodes = document.getElementById('showNodes').checked;
    const showAntennas = document.getElementById('showAntennas').checked;
    const showRadius = document.getElementById('showRadius').checked;

    // Render
    renderData(filteredGeoJSON, currentData.nodes, currentData.antennas, {
        showPolygons,
        showNodes,
        showAntennas,
        showRadius
    });

    // Update stats
    document.getElementById('polyCount').textContent = filtered.length.toLocaleString();
    document.getElementById('nodeCount').textContent = (currentData.nodes ? currentData.nodes.length : 0).toLocaleString();
    document.getElementById('antCount').textContent = (currentData.antennas ? currentData.antennas.length : 0).toLocaleString();

    // Show filter info
    const filteredInfo = document.getElementById('filteredInfo');
    const isFiltered = minNodes > 0 || maxNodes < parseInt(document.getElementById('nodeMax').max) ||
        minAntennas > 0 || maxAntennas < parseInt(document.getElementById('antMax').max);
    if (isFiltered) {
        filteredInfo.style.display = 'block';
        document.getElementById('filteredCount').textContent = filtered.length;
        document.getElementById('totalCount').textContent = allFeatures.length;
    } else {
        filteredInfo.style.display = 'none';
    }
}

// ─── Render Data ───────────────────────────────────────────────
function renderData(polygonsGeoJSON, nodesData, antennasData, visibility) {
    // 1. Clear existing layers
    drawnItems.clearLayers();
    destroyGlifyLayers();
    radiusLayerGroup.clearLayers();

    // 2. Polygons
    if (visibility.showPolygons && polygonsGeoJSON.features.length > 0) {
        L.geoJSON(polygonsGeoJSON, {
            style: (feature) => {
                const hasId = feature.properties.polygon_id !== undefined;
                return {
                    fillColor: '#3b82f6',
                    weight: hasId ? 2 : 1,
                    opacity: 1,
                    color: hasId ? '#1d4ed8' : '#60a5fa',
                    dashArray: hasId ? '' : '3',
                    fillOpacity: 0.2
                };
            },
            onEachFeature: (feature, layer) => {
                const p = feature.properties;
                layer.bindPopup(`
                    <b>ID:</b> ${p.polygon_id}<br>
                    <b>Nodes:</b> ${p.node_count}<br>
                    <b>Antennas:</b> ${p.antenna_count}<br>
                    <b>Total:</b> ${p.total_count}
                `);
                drawnItems.addLayer(layer);
            }
        });

        if (!map.hasLayer(drawnItems)) {
            map.addLayer(drawnItems);
        }

        if (drawnItems.getBounds().isValid()) {
            map.fitBounds(drawnItems.getBounds());
        }
    }

    // 3. Nodes (WebGL via Glify)
    if (visibility.showNodes && nodesData && nodesData.length > 0) {
        nodeGlifyInstance = L.glify.points({
            map: map,
            data: nodesData,
            size: 3,
            color: { r: 0.29, g: 0.29, b: 0.29 },
            opacity: 0.8,
            click: (e, point, xy) => {
                const latlng = L.latLng(point[0], point[1]);
                const circle = L.circle(latlng, {
                    radius: 500,
                    color: '#3b82f6',
                    fillColor: '#3b82f6',
                    fillOpacity: 0.08,
                    weight: 1,
                    dashArray: '4 4'
                }).addTo(radiusLayerGroup);
                circle.bindPopup(`<b>Node</b><br>500m radius`).openPopup();
            }
        });

        // Default 500m radius circles
        if (visibility.showRadius) {
            addDefaultRadiusCircles(nodesData);
        }
    }

    // 4. Antennas (WebGL via Glify)
    if (visibility.showAntennas && antennasData && antennasData.length > 0) {
        antennaGlifyInstance = L.glify.points({
            map: map,
            data: antennasData,
            size: 5,
            color: { r: 1, g: 0, b: 0 },
            opacity: 0.9
        });
    }
}

// ─── Default 500m Radius Circles ───────────────────────────────
function addDefaultRadiusCircles(nodesData) {
    const maxCircles = Math.min(50, nodesData.length);
    const step = Math.max(1, Math.floor(nodesData.length / maxCircles));

    for (let i = 0; i < nodesData.length && radiusLayerGroup.getLayers().length < maxCircles; i += step) {
        const point = nodesData[i];
        L.circle([point[0], point[1]], {
            radius: 500,
            color: '#3b82f6',
            fillColor: '#3b82f6',
            fillOpacity: 0.05,
            weight: 1,
            dashArray: '4 4',
            interactive: false
        }).addTo(radiusLayerGroup);
    }
}

// ─── Glify Layer Management ────────────────────────────────────
function destroyGlifyLayers() {
    if (nodeGlifyInstance) {
        try { nodeGlifyInstance.remove(); } catch (e) { }
        nodeGlifyInstance = null;
    }
    if (antennaGlifyInstance) {
        try { antennaGlifyInstance.remove(); } catch (e) { }
        antennaGlifyInstance = null;
    }
}

function toggleNodeLayer(show) {
    if (show && currentData && currentData.nodes && currentData.nodes.length > 0) {
        if (!nodeGlifyInstance) {
            nodeGlifyInstance = L.glify.points({
                map: map,
                data: currentData.nodes,
                size: 3,
                color: { r: 0.29, g: 0.29, b: 0.29 },
                opacity: 0.8,
                click: (e, point, xy) => {
                    const latlng = L.latLng(point[0], point[1]);
                    L.circle(latlng, {
                        radius: 500,
                        color: '#3b82f6',
                        fillColor: '#3b82f6',
                        fillOpacity: 0.08,
                        weight: 1,
                        dashArray: '4 4'
                    }).addTo(radiusLayerGroup).bindPopup(`<b>Node</b><br>500m radius`).openPopup();
                }
            });
        }
    } else {
        if (nodeGlifyInstance) {
            try { nodeGlifyInstance.remove(); } catch (e) { }
            nodeGlifyInstance = null;
        }
    }
}

function toggleAntennaLayer(show) {
    if (show && currentData && currentData.antennas && currentData.antennas.length > 0) {
        if (!antennaGlifyInstance) {
            antennaGlifyInstance = L.glify.points({
                map: map,
                data: currentData.antennas,
                size: 5,
                color: { r: 1, g: 0, b: 0 },
                opacity: 0.9
            });
        }
    } else {
        if (antennaGlifyInstance) {
            try { antennaGlifyInstance.remove(); } catch (e) { }
            antennaGlifyInstance = null;
        }
    }
}

// ─── Fullscreen ────────────────────────────────────────────────
function toggleFullscreen() {
    const wrapper = document.getElementById('mapWrapper');

    if (!document.fullscreenElement && !document.webkitFullscreenElement) {
        if (wrapper.requestFullscreen) {
            wrapper.requestFullscreen();
        } else if (wrapper.webkitRequestFullscreen) {
            wrapper.webkitRequestFullscreen();
        }
    } else {
        if (document.exitFullscreen) {
            document.exitFullscreen();
        } else if (document.webkitExitFullscreen) {
            document.webkitExitFullscreen();
        }
    }
}

function onFullscreenChange() {
    const wrapper = document.getElementById('mapWrapper');
    const icon = document.getElementById('fullscreenIcon');
    const isFullscreen = !!document.fullscreenElement || !!document.webkitFullscreenElement;

    if (isFullscreen) {
        wrapper.classList.add('is-fullscreen');
        icon.innerHTML = '<path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3"/>';
    } else {
        wrapper.classList.remove('is-fullscreen');
        icon.innerHTML = '<path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/>';
    }

    setTimeout(() => {
        map.invalidateSize();
    }, 200);
}

// ─── Export GeoJSON ────────────────────────────────────────────
function exportGeoJSON() {
    const data = drawnItems.toGeoJSON();
    const convertedData = 'text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(data));

    const a = document.createElement('a');
    a.href = 'data:' + convertedData;
    a.download = 'edited_polygons.geojson';
    a.innerHTML = 'download';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}
