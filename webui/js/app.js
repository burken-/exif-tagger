// EXIF Tagger Dashboard — Client-side JavaScript

const API_BASE = '';
let pollInterval = null;
let currentSessionId = null;
let autoScroll = true;

document.getElementById('auto-scroll-toggle').addEventListener('change', (e) => {
    autoScroll = e.target.checked;
});

// ---------------------------------------------------------------------------
// Tab management
// ---------------------------------------------------------------------------
document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        btn.classList.add('active');
        const tabId = `tab-${btn.dataset.tab}`;
        document.getElementById(tabId).classList.add('active');

        if (btn.dataset.tab === 'config') loadConfig();
        if (btn.dataset.tab === 'schedule') loadSchedules();
    });
});

// ---------------------------------------------------------------------------
// Status polling
// ---------------------------------------------------------------------------
async function fetchStatus() {
    try {
        const resp = await fetch(`${API_BASE}/api/status`);
        const data = await resp.json();
        updateStatusUI(data);
        return data;
    } catch (e) { /* silent fail during startup */ }
}

function updateStatusUI(data) {
    const indicator = document.getElementById('status-indicator');
    const btnStart = document.getElementById('btn-start');
    const btnStop = document.getElementById('btn-stop');
    const progressBar = document.getElementById('progress-bar');
    const progressText = document.getElementById('progress-text');

    if (data.running) {
        indicator.textContent = 'Running';
        indicator.className = 'status-badge running';
        btnStart.disabled = true;
        btnStop.disabled = false;
    } else if (data.stopRequested) {
        indicator.textContent = 'Stopping...';
        indicator.className = 'status-badge stopped';
    } else {
        indicator.textContent = data.summary ? 'Completed' : 'Idle';
        indicator.className = 'status-badge idle';
        btnStart.disabled = false;
        btnStop.disabled = true;
    }

    if (data.total > 0) {
        const pct = data.progressPct || 0;
        progressBar.style.width = `${pct}%`;
        progressText.textContent = `${data.processed} / ${data.total} images processed (${pct}%)`;
    } else {
        progressBar.style.width = '0%';
        progressText.textContent = '0 / 0 images processed (0%)';
    }

    // Update log output if available
    const logOutput = document.getElementById('log-output');
    if (data.summary && data.summary.errors) {
        data.summary.errors.forEach(err => appendLog(`Error: ${err}`));
    }
}

function appendLog(text) {
    const el = document.getElementById('log-output');
    el.textContent += text + '\n';
    if (autoScroll) {
        el.scrollTop = el.scrollHeight;
    }
}

// Start polling when page loads
pollInterval = setInterval(fetchStatus, 2000);
fetchStatus();

// ---------------------------------------------------------------------------
// Processing controls
// ---------------------------------------------------------------------------
document.getElementById('btn-start').addEventListener('click', async () => {
    const folderPath = document.getElementById('folder-path').value.trim() || null;
    const maxImages = document.getElementById('max-images').value ? parseInt(document.getElementById('max-images').value) : null;

    try {
        const resp = await fetch(`${API_BASE}/api/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rootDirectory: folderPath, maxImages }),
        });
        if (resp.ok) {
            appendLog('Session started.');
            document.getElementById('log-output').textContent = '';
        } else {
            const err = await resp.json();
            alert(err.detail || 'Failed to start session');
        }
    } catch (e) { alert('Network error: ' + e.message); }
});

document.getElementById('btn-stop').addEventListener('click', async () => {
    try {
        const resp = await fetch(`${API_BASE}/api/stop`, { method: 'POST' });
        if (resp.ok) appendLog('Stop requested.');
    } catch (e) { alert('Network error: ' + e.message); }
});

// ---------------------------------------------------------------------------
// Config management
// ---------------------------------------------------------------------------
async function loadConfig() {
    try {
        const resp = await fetch(`${API_BASE}/api/config`);
        if (!resp.ok) return;
        const config = await resp.json();

        document.getElementById('config-root').value = config.root_directory || '';
        document.getElementById('model-base-url').value = config.model?.base_url || '';
        document.getElementById('model-name').value = config.model?.model_name || '';
        document.getElementById('model-max-tokens').value = config.model?.max_tokens || 500;
        const tempSlider = document.getElementById('model-temperature');
        tempSlider.value = config.model?.temperature ?? 0.1;
        document.getElementById('temp-value').textContent = config.model?.temperature ?? 0.1;

        // Populate API key field (only if server returned one)
        document.getElementById('model-api-key').value = config.model?.api_key || '';

        // Populate structured outputs and max dimension
        document.getElementById('model-use-structured').checked = config.model?.use_structured_outputs || false;
        document.getElementById('model-max-dimension').value = config.model?.max_image_dimension || 720;

        // Populate extra params textarea
        const modelParams = config.model?.params || {};
        document.getElementById('model-params').value = JSON.stringify(modelParams, null, 2);

        // Render tags
        renderTags(config.tags || {});

        // Render exclude patterns
        renderExcludes(config.exclude_patterns || []);
    } catch (e) { console.error('Failed to load config:', e); }
}

function renderTags(tags) {
    const container = document.getElementById('tags-container');
    container.innerHTML = '';
    for (const [name, data] of Object.entries(tags)) {
        addTagCard(name, data.description || '', data.threshold || 0.7);
    }
}

function addTagCard(name = '', desc = '', threshold = 0.7) {
    const container = document.getElementById('tags-container');
    const card = document.createElement('div');
    card.className = 'tag-card';
    card.innerHTML = `
        <input type="text" class="tag-name-input" placeholder="Tag name" value="${name}">
        <input type="text" class="tag-desc-input" placeholder="Description" value="${desc}">
        <input type="number" class="tag-threshold-input" min="0" max="1" step="0.05" value="${threshold}" title="Threshold">
        <button class="btn btn-danger tag-remove-btn" style="padding:4px 8px;">×</button>
    `;
    card.querySelector('.tag-remove-btn').addEventListener('click', () => card.remove());
    container.appendChild(card);
}

document.getElementById('btn-add-tag').addEventListener('click', () => addTagCard());

function renderExcludes(patterns) {
    const container = document.getElementById('exclude-container');
    container.innerHTML = '';
    patterns.forEach(p => addExcludeItem(p));
}

function addExcludeItem(pattern = '') {
    const container = document.getElementById('exclude-container');
    const item = document.createElement('div');
    item.className = 'exclude-item';
    item.innerHTML = `
        <input type="text" class="exclude-input" placeholder="Regex pattern (e.g. .*receipt.*|/blurry/)" value="${pattern}">
        <button class="btn btn-danger exclude-remove-btn" style="padding:4px 8px;">×</button>
    `;
    item.querySelector('.exclude-remove-btn').addEventListener('click', () => item.remove());
    container.appendChild(item);
}

document.getElementById('btn-add-exclude').addEventListener('click', () => addExcludeItem());

// Temperature slider live update
document.getElementById('model-temperature').addEventListener('input', (e) => {
    document.getElementById('temp-value').textContent = e.target.value;
});

document.getElementById('btn-save-config').addEventListener('click', async () => {
    const tags = {};
    document.querySelectorAll('.tag-card').forEach(card => {
        const name = card.querySelector('.tag-name-input').value.trim();
        if (!name) return;
        tags[name] = {
            description: card.querySelector('.tag-desc-input').value,
            threshold: parseFloat(card.querySelector('.tag-threshold-input').value) || 0.7,
        };
    });

    const excludes = [];
    document.querySelectorAll('.exclude-input').forEach(input => {
        const v = input.value.trim();
        if (v) excludes.push(v);
    });

    // Parse extra params JSON
    const paramsText = document.getElementById('model-params').value.trim();
    let modelParams = {};
    if (paramsText) {
        try {
            modelParams = JSON.parse(paramsText);
        } catch (e) {
            alert('Invalid JSON in Extra Params field');
            return;
        }
    }

    try {
        const resp = await fetch(`${API_BASE}/api/config`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                root_directory: document.getElementById('config-root').value.trim(),
                model: {
                    base_url: document.getElementById('model-base-url').value.trim(),
                    model_name: document.getElementById('model-name').value.trim(),
                    max_tokens: parseInt(document.getElementById('model-max-tokens').value) || 500,
                    temperature: parseFloat(document.getElementById('model-temperature').value) || 0.1,
                    api_key: document.getElementById('model-api-key').value.trim() || null,
                    use_structured_outputs: document.getElementById('model-use-structured').checked,
                    max_image_dimension: parseInt(document.getElementById('model-max-dimension').value) || 720,
                    params: modelParams,
                },
                tags,
                exclude_patterns: excludes,
            }),
        });
        if (resp.ok) {
            alert('Configuration saved successfully.');
        } else {
            const err = await resp.json();
            alert('Failed to save config: ' + (err.detail || 'Unknown error'));
        }
    } catch (e) { alert('Network error: ' + e.message); }
});

// ---------------------------------------------------------------------------
// Schedule management
// ---------------------------------------------------------------------------
async function loadSchedules() {
    try {
        const resp = await fetch(`${API_BASE}/api/schedule`);
        if (!resp.ok) return;
        const schedules = await resp.json();
        renderSchedules(schedules);
    } catch (e) { console.error('Failed to load schedules:', e); }
}

function renderSchedules(schedules) {
    const tbody = document.getElementById('schedules-tbody');
    tbody.innerHTML = '';
    if (schedules.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#888;">No schedules configured</td></tr>';
        return;
    }
    for (const s of schedules) {
        const tr = document.createElement('tr');
        const freqType = s.cron_expression ? 'Cron' : `Every ${s.interval_hours}h`;
        const statusColor = s.last_status === 'success' ? '#2ecc71' : s.last_status === 'failed' ? '#e74c3c' : '#888';
        tr.innerHTML = `
            <td>${s.name}</td>
            <td>${s.folder}</td>
            <td>${freqType}</td>
            <td>${s.next_run_at || '-'}</td>
            <td style="color:${statusColor}">${s.last_status || 'Never'}</td>
            <td><button class="btn btn-danger schedule-delete-btn" data-id="${s.id}" style="padding:4px 8px;">Delete</button></td>
        `;
        tbody.appendChild(tr);
    }

    // Attach delete handlers
    document.querySelectorAll('.schedule-delete-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            if (!confirm('Delete this schedule?')) return;
            try {
                const resp = await fetch(`${API_BASE}/api/schedule/${btn.dataset.id}`, { method: 'DELETE' });
                if (resp.ok) loadSchedules();
            } catch (e) { alert('Network error'); }
        });
    });
}

// Schedule type toggle
document.getElementById('schedule-type').addEventListener('change', (e) => {
    const isCron = e.target.value === 'cron';
    document.getElementById('interval-input-group').style.display = isCron ? 'none' : '';
    document.getElementById('cron-input-group').style.display = isCron ? '' : 'none';
});

// Preset buttons
document.querySelectorAll('.preset-buttons button').forEach(btn => {
    btn.addEventListener('click', () => {
        const type = btn.dataset.type;
        document.getElementById('schedule-type').value = type;
        if (type === 'interval') {
            document.getElementById('schedule-interval').value = btn.dataset.hours;
        } else {
            document.getElementById('schedule-cron').value = btn.dataset.cron;
        }
    });
});

document.getElementById('btn-add-schedule').addEventListener('click', async () => {
    const name = document.getElementById('schedule-name').value.trim();
    const folder = document.getElementById('schedule-folder').value.trim();
    const type = document.getElementById('schedule-type').value;

    if (!name || !folder) { alert('Name and folder are required'); return; }

    const body = { name, folder };
    if (type === 'interval') {
        body.interval_hours = parseFloat(document.getElementById('schedule-interval').value);
    } else {
        body.cron_expression = document.getElementById('schedule-cron').value.trim();
    }

    try {
        const resp = await fetch(`${API_BASE}/api/schedule`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (resp.ok) {
            alert('Schedule added.');
            loadSchedules();
        } else {
            const err = await resp.json();
            alert('Failed to add schedule: ' + (err.detail || 'Unknown error'));
        }
    } catch (e) { alert('Network error: ' + e.message); }
});

// Load config on first tab activation
loadConfig();
