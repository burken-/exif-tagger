// EXIF Tagger Dashboard — Client-side JavaScript

const API_BASE = '';
let pollInterval = null;
let currentSessionId = null;
let autoScroll = true;
let lastProcessedLogId = 0;

document.getElementById('auto-scroll-toggle').addEventListener('change', (e) => {
    autoScroll = e.target.checked;
});

document.getElementById('btn-clear-log').addEventListener('click', () => {
    document.getElementById('log-output').innerHTML = '';
    lastProcessedLogId = 0;
});

// ---------------------------------------------------------------------------
// Toast notifications
// ---------------------------------------------------------------------------
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(50px)';
        toast.style.transition = 'opacity 0.3s, transform 0.3s';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

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
        isRunning = true;
        indicator.textContent = 'Running';
        indicator.className = 'status-badge running';
        btnStart.disabled = true;
        btnStop.disabled = false;
    } else if (data.stopRequested) {
        isRunning = false;
        indicator.textContent = 'Stopping...';
        indicator.className = 'status-badge stopped';
    } else {
        const hasFailures = data.summary && (data.summary.failed > 0 || (data.summary.errors && data.summary.errors.length > 0));
        indicator.textContent = data.summary ? (hasFailures ? 'Completed with errors' : 'Completed') : 'Idle';
        if (hasFailures) {
            indicator.className = 'status-badge warning';
        } else {
            indicator.className = 'status-badge idle';
        }
        isRunning = false;
        btnStart.disabled = false;
        btnStop.disabled = true;
    }

    // Update progress
    if (data.total > 0) {
        const pct = data.progressPct || 0;
        progressBar.style.width = `${pct}%`;
        progressText.textContent = `${data.processed} / ${data.total} images processed (${pct}%)`;
    }

    // Update log output continuously without duplicate repetition
    if (data.logs && Array.isArray(data.logs)) {
        data.logs.forEach(log => {
            if (log.id > lastProcessedLogId) {
                appendLog(log.text, log.level || 'info');
                lastProcessedLogId = log.id;
            }
        });
    }

    setupPolling();
}

function appendLog(text, severity = 'info') {
    const el = document.getElementById('log-output');
    const line = document.createElement('div');
    line.className = `log-line ${severity}`;
    line.textContent = text;
    el.appendChild(line);
    if (autoScroll) {
        el.scrollTop = el.scrollHeight;
    }
}

let isRunning = false;

function setupPolling() {
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(fetchStatus, isRunning ? 1000 : 5000);
}

// Start polling when page loads
fetchStatus().then(() => setupPolling());

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
            document.getElementById('log-output').innerHTML = '';
            lastProcessedLogId = 0;
            document.getElementById('progress-bar').style.width = '0%';
            document.getElementById('progress-text').textContent = '0 / 0 images processed (0%)';
            appendLog('Session started.', 'info');
        } else {
            const err = await resp.json();
            showToast(err.detail || 'Failed to start session', 'error');
        }
    } catch (e) { showToast('Network error: ' + e.message, 'error'); }
});

document.getElementById('btn-stop').addEventListener('click', async () => {
    try {
        const resp = await fetch(`${API_BASE}/api/stop`, { method: 'POST' });
        if (resp.ok) appendLog('Stop requested.', 'info');
    } catch (e) { showToast('Network error: ' + e.message, 'error'); }
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
        const folderPathEl = document.getElementById('folder-path');
        if (folderPathEl) {
            folderPathEl.placeholder = config.root_directory ? `Default: ${config.root_directory}` : '/data/images/this-month';
        }
        document.getElementById('model-base-url').value = config.model?.base_url || '';
        document.getElementById('model-name').value = config.model?.model_name || '';
        document.getElementById('model-max-tokens').value = config.model?.max_tokens || 500;
        const tempSlider = document.getElementById('model-temperature');
        const tempVal = config.model?.temperature ?? 0.1;
        tempSlider.value = tempVal;
        document.getElementById('temp-value').textContent = tempVal;

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
    updateTagMoveButtons();
}

function updateTagMoveButtons() {
    const cards = document.querySelectorAll('#tags-container .tag-card');
    cards.forEach((card, index) => {
        const btnUp = card.querySelector('.tag-move-btn[data-dir="up"]');
        const btnDown = card.querySelector('.tag-move-btn[data-dir="down"]');
        if (btnUp) btnUp.disabled = (index === 0);
        if (btnDown) btnDown.disabled = (index === cards.length - 1);
    });
}

function addTagCard(name = '', desc = '', threshold = 0.7) {
    const container = document.getElementById('tags-container');
    const card = document.createElement('div');
    card.className = 'tag-card';
    card.innerHTML = `
        <input type="text" class="tag-name-input" placeholder="e.g. landscape" value="${name}">
        <input type="text" class="tag-desc-input" placeholder="What should this tag detect?" value="${desc}">
        <input type="number" class="tag-threshold-input" min="0" max="1" step="0.05" value="${threshold}" title="Threshold">
        <button class="btn btn-secondary tag-move-btn" data-dir="up" style="padding:2px 6px; font-size:0.8rem;">↑</button>
        <button class="btn btn-secondary tag-move-btn" data-dir="down" style="padding:2px 6px; font-size:0.8rem;">↓</button>
        <button class="btn btn-danger tag-remove-btn" style="padding:4px 8px;">×</button>
    `;
    card.querySelector('.tag-remove-btn').addEventListener('click', () => {
        card.remove();
        updateTagMoveButtons();
    });
    card.querySelectorAll('.tag-move-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const dir = btn.dataset.dir;
            if (dir === 'up') {
                const prev = card.previousElementSibling;
                if (prev) container.insertBefore(card, prev);
            } else {
                const next = card.nextElementSibling;
                if (next) container.insertBefore(next, card);
            }
            updateTagMoveButtons();
        });
    });
    container.appendChild(card);
    updateTagMoveButtons();
}

document.getElementById('btn-add-tag').addEventListener('click', () => addTagCard());

function renderExcludes(patterns) {
    const container = document.getElementById('exclude-container');
    container.innerHTML = '';
    patterns.forEach(p => addExcludeItem(p));
    updateExcludeMoveButtons();
}

function updateExcludeMoveButtons() {
    const items = document.querySelectorAll('#exclude-container .exclude-item');
    items.forEach((item, index) => {
        const btnUp = item.querySelector('.exclude-move-btn[data-dir="up"]');
        const btnDown = item.querySelector('.exclude-move-btn[data-dir="down"]');
        if (btnUp) btnUp.disabled = (index === 0);
        if (btnDown) btnDown.disabled = (index === items.length - 1);
    });
}

function addExcludeItem(pattern = '') {
    const container = document.getElementById('exclude-container');
    const item = document.createElement('div');
    item.className = 'exclude-item';
    item.innerHTML = `
        <input type="text" class="exclude-input" placeholder="e.g. thumbs?_?(db|cache)?/i?" value="${pattern}">
        <button class="btn btn-secondary exclude-move-btn" data-dir="up" style="padding:2px 6px; font-size:0.8rem;">↑</button>
        <button class="btn btn-secondary exclude-move-btn" data-dir="down" style="padding:2px 6px; font-size:0.8rem;">↓</button>
        <button class="btn btn-danger exclude-remove-btn" style="padding:4px 8px;">×</button>
    `;
    item.querySelector('.exclude-remove-btn').addEventListener('click', () => {
        item.remove();
        updateExcludeMoveButtons();
    });
    item.querySelectorAll('.exclude-move-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const dir = btn.dataset.dir;
            if (dir === 'up') {
                const prev = item.previousElementSibling;
                if (prev) container.insertBefore(item, prev);
            } else {
                const next = item.nextElementSibling;
                if (next) container.insertBefore(next, item);
            }
            updateExcludeMoveButtons();
        });
    });
    container.appendChild(item);
    updateExcludeMoveButtons();
}

document.getElementById('btn-add-exclude').addEventListener('click', () => addExcludeItem());

// API key toggle visibility
document.getElementById('btn-toggle-api-key').addEventListener('click', () => {
    const apiKeyInput = document.getElementById('model-api-key');
    const toggleBtn = document.getElementById('btn-toggle-api-key');
    if (apiKeyInput.type === 'password') {
        apiKeyInput.type = 'text';
        toggleBtn.textContent = '🔒';
    } else {
        apiKeyInput.type = 'password';
        toggleBtn.textContent = '👁️';
    }
});

// Temperature slider display sync
document.getElementById('model-temperature').addEventListener('input', (e) => {
    document.getElementById('temp-value').textContent = e.target.value;
});

document.getElementById('btn-save-config').addEventListener('click', async () => {
    const btn = document.getElementById('btn-save-config');
    btn.disabled = true;
    const originalText = btn.textContent;
    btn.textContent = 'Saving...';

    try {
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
                showToast('Invalid JSON in Extra Params field', 'error');
                return;
            }
        }

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
            showToast('Configuration saved successfully.', 'success');
        } else {
            const err = await resp.json();
            showToast('Failed to save config: ' + (err.detail || 'Unknown error'), 'error');
        }
    } catch (e) { showToast('Network error: ' + e.message, 'error'); }
    finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
});

// Export config as JSON download
document.getElementById('btn-export-config').addEventListener('click', async () => {
    try {
        const resp = await fetch(`${API_BASE}/api/config`);
        if (!resp.ok) { showToast('Failed to export config', 'error'); return; }
        const config = await resp.json();
        const blob = new Blob([JSON.stringify(config, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'exif-tagger-config.json';
        a.click();
        URL.revokeObjectURL(url);
    } catch (e) { showToast('Export failed: ' + e.message, 'error'); }
});

// Import config from JSON file
document.getElementById('import-config-input').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
        const text = await file.text();
        const config = JSON.parse(text);
        document.getElementById('config-root').value = config.root_directory || '';
        document.getElementById('model-base-url').value = config.model?.base_url || '';
        document.getElementById('model-name').value = config.model?.model_name || '';
        document.getElementById('model-max-tokens').value = config.model?.max_tokens || 500;
        const tempSlider = document.getElementById('model-temperature');
        const tempVal = config.model?.temperature ?? 0.1;
        tempSlider.value = tempVal;
        document.getElementById('temp-value').textContent = tempVal;
        document.getElementById('model-use-structured').checked = config.model?.use_structured_outputs || false;
        document.getElementById('model-max-dimension').value = config.model?.max_image_dimension || 720;
        const modelParams = config.model?.params || {};
        document.getElementById('model-params').value = JSON.stringify(modelParams, null, 2);
        renderTags(config.tags || {});
        renderExcludes(config.exclude_patterns || []);
        showToast('Config imported — click Save to apply', 'success');
    } catch (err) { showToast('Failed to import config: ' + err.message, 'error'); }
    // Reset input so the same file can be re-imported
    e.target.value = '';
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
            <td>
                <button class="btn btn-primary schedule-run-btn" data-id="${s.id}" style="padding:4px 8px; margin-right:4px;">Run Now</button>
                <button class="btn btn-danger schedule-delete-btn" data-id="${s.id}" style="padding:4px 8px;">Delete</button>
            </td>
        `;
        tbody.appendChild(tr);
    }

    // Attach run now handlers
    document.querySelectorAll('.schedule-run-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            try {
                const resp = await fetch(`${API_BASE}/api/schedule/${btn.dataset.id}/run`, { method: 'POST' });
                if (resp.ok) {
                    showToast('Schedule execution started.', 'success');
                } else {
                    const err = await resp.json();
                    showToast('Failed to run schedule: ' + (err.detail || 'Unknown error'), 'error');
                }
            } catch (e) { showToast('Network error: ' + e.message, 'error'); }
        });
    });

    // Attach delete handlers
    document.querySelectorAll('.schedule-delete-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            if (!confirm('Delete this schedule?')) return;
            try {
                const resp = await fetch(`${API_BASE}/api/schedule/${btn.dataset.id}`, { method: 'DELETE' });
                if (resp.ok) loadSchedules();
            } catch (e) { showToast('Network error', 'error'); }
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

    if (!name || !folder) { showToast('Name and folder are required', 'error'); return; }

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
            showToast('Schedule added.', 'success');
            document.getElementById('schedule-name').value = '';
            document.getElementById('schedule-folder').value = '';
            document.getElementById('schedule-type').value = 'interval';
            document.getElementById('schedule-interval').value = '6';
            document.getElementById('schedule-cron').value = '';
            document.getElementById('interval-input-group').style.display = '';
            document.getElementById('cron-input-group').style.display = 'none';
            loadSchedules();
        } else {
            const err = await resp.json();
            showToast('Failed to add schedule: ' + (err.detail || 'Unknown error'), 'error');
        }
    } catch (e) { showToast('Network error: ' + e.message, 'error'); }
});

// Keyboard shortcuts
document.addEventListener('keydown', (e) => {
    const isInput = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName);
    if (isInput) return;

    // Ctrl+Enter to start processing
    if (e.ctrlKey && e.key === 'Enter') {
        e.preventDefault();
        const btnStart = document.getElementById('btn-start');
        if (!btnStart.disabled) btnStart.click();
    }
    // Escape to stop
    if (e.key === 'Escape') {
        e.preventDefault();
        const btnStop = document.getElementById('btn-stop');
        if (!btnStop.disabled) btnStop.click();
    }
    // Number keys for tabs
    if (!e.ctrlKey && !e.altKey && !e.metaKey) {
        const tabBtns = document.querySelectorAll('.tab-btn');
        const num = parseInt(e.key);
        if (num >= 1 && num <= 3 && tabBtns[num - 1]) {
            tabBtns[num - 1].click();
        }
    }
});

// Load config on first tab activation
loadConfig();
