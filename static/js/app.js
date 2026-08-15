/**
 * NexusNode — 24/7 Personal Mobile Server Appliance Controller & SSE Streamer
 * Architecture: Single-Endpoint System Polling, Reactive UI, Range Stream Player, Media & Task Queue
 */

const ALL_PRIVILEGES_LIST = [
  'can_view_logs',
  'can_delete_files',
  'can_upload_files',
  'can_manage_engine',
  'can_run_tasks',
  'can_use_rag',
  'can_manage_users',
  'can_create_shares',
  'can_manage_backups',
  'can_manage_automation',
  'can_manage_settings'
];

function getStoredAuth() {
  const token = sessionStorage.getItem('nexus_auth_token') || localStorage.getItem('nexus_auth_token') || '';
  const userStr = sessionStorage.getItem('nexus_user_profile') || localStorage.getItem('nexus_user_profile');
  const user = userStr ? JSON.parse(userStr) : null;
  return { token, user };
}

const initialAuth = getStoredAuth();
let state = {
  token: initialAuth.token,
  user: initialAuth.user,
  activeTab: 'dashboard',
  systemStatusInterval: null,
  cachedFiles: [],
  mediaLibrary: { music: [], videos: [], podcasts: [], downloads: [], other: [] },
  activeMediaCat: 'all',
  currentAudioVideo: null,
  chatMessages: [],
  allEvents: [],
  activeEventCat: 'ALL',
  logEventSource: null
};

function hasPrivilege(privName) {
  if (!state.user) return false;
  if (state.user.role === 'admin') return true;
  return !!(state.user.privileges && state.user.privileges[privName]);
}

function getAuthHeaders() {
  return {
    'Authorization': `Bearer ${state.token}`,
    'localtonet-skip-warning': 'true',
    'Content-Type': 'application/json'
  };
}

// Battery Optimization: Pause polling when screen off or backgrounded
document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    if (state.systemStatusInterval) {
      clearInterval(state.systemStatusInterval);
      state.systemStatusInterval = null;
    }
  } else {
    if (state.token) {
      fetchSystemStatus();
      initSystemPolling();
    }
  }
});

// App Bootstrap
document.addEventListener('DOMContentLoaded', async () => {
  if (state.token && state.user) {
    try {
      const res = await fetch('/api/auth/me', { headers: getAuthHeaders() });
      if (res.ok) {
        const data = await res.json();
        state.user = data.user;
        closeModal('loginModal');
        applyUserRoleUI();
        initDashboard();
      } else {
        handleLogout(false);
      }
    } catch (e) {
      closeModal('loginModal');
      applyUserRoleUI();
      initDashboard();
    }
  } else {
    openModal('loginModal');
  }
});

function applyUserRoleUI() {
  if (!state.user) return;
  document.getElementById('headerUsername').textContent = state.user.user_id;
  const roleBadge = document.getElementById('headerRoleBadge');
  roleBadge.textContent = state.user.role.toUpperCase();
  roleBadge.className = `role-badge ${state.user.role}`;

  const adminTabs = document.querySelectorAll('.admin-only');
  adminTabs.forEach(el => {
    el.style.display = (state.user.role === 'admin') ? '' : 'none';
  });
}

function initDashboard() {
  fetchSystemStatus();
  initSystemPolling();
  fetchVaultFiles();
  fetchMediaLibrary();
  fetchTasks();
  fetchEvents();
  checkModelEstimate(document.getElementById('aiModelSelect')?.value || 'qwen2.5:0.5b');
}

function initSystemPolling() {
  if (state.systemStatusInterval) clearInterval(state.systemStatusInterval);
  state.systemStatusInterval = setInterval(fetchSystemStatus, 3000);
}

// Single-Endpoint Central Telemetry Poller
async function fetchSystemStatus() {
  if (!state.token) return;
  try {
    const res = await fetch('/api/system/status', { headers: getAuthHeaders() });
    if (!res.ok) {
      if (res.status === 401) handleLogout(false);
      return;
    }
    const data = await res.json();
    renderApplianceStatus(data);
  } catch (e) {}
}

function renderApplianceStatus(data) {
  const { server, appliance, memory, disk, device, services, tasks, rag } = data;

  // Header & Sub
  if (server) {
    document.getElementById('serverApplianceSub').textContent = `${server.device || 'Android Termux'} • Uptime: ${server.uptime || '--'}`;
    const tunnelPill = document.getElementById('metaTunnelStatus');
    if (tunnelPill) {
      tunnelPill.textContent = (services.localtonet && services.localtonet.status === 'online') ? 'Active' : 'Offline';
      tunnelPill.style.color = (services.localtonet && services.localtonet.status === 'online') ? 'var(--accent-cyan)' : 'var(--accent-rose)';
    }
  }

  // Device / Thermal / Battery
  if (device) {
    const thermPill = document.getElementById('metaThermalState');
    if (thermPill) {
      thermPill.textContent = device.thermal_state || 'NORMAL';
      thermPill.style.color = device.thermal_state === 'CRITICAL' ? 'var(--accent-rose)' : (device.thermal_state === 'THROTTLED' || device.thermal_state === 'WARM' ? 'var(--accent-amber)' : 'var(--accent-emerald)');
    }
    const batPill = document.getElementById('metaBatteryPct');
    if (batPill) {
      batPill.textContent = device.battery_percent !== null ? `${device.battery_percent}%` : '--%';
    }
  }

  // Appliance State Badge
  if (appliance) {
    const badge = document.getElementById('governorStateBadge');
    if (badge) {
      badge.textContent = appliance.badge;
      badge.className = `governor-badge ${appliance.state.toLowerCase().includes('crit') ? 'critical' : (appliance.state.toLowerCase().includes('press') ? 'pressure' : 'normal')}`;
    }
  }

  // RAM Meter
  if (memory) {
    document.getElementById('ramStatText').textContent = `${memory.used_mb} MB / ${memory.total_mb} MB (${memory.ram_percent}%)`;
    document.getElementById('ramProgressBar').style.width = `${memory.ram_percent}%`;
    document.getElementById('ramAvailableDetail').textContent = `Available: ${memory.available_mb} MB`;
  }

  // Disk Meter
  if (disk) {
    document.getElementById('diskStatText').textContent = `${disk.used_gb} GB / ${disk.total_gb} GB (${disk.percent}%)`;
    document.getElementById('diskProgressBar').style.width = `${disk.percent}%`;
    document.getElementById('diskFreeDetail').textContent = `Free Space: ${disk.free_gb} GB`;
    document.getElementById('diskTotalDetail').textContent = `Capacity: ${disk.total_gb} GB`;
  }

  // Services Quad
  if (services) {
    updateServiceCard('svcCardNexus', 'svcPillNexus', 'svcPidNexus', services.nexusnode);
    updateServiceCard('svcCardTunnel', 'svcPillTunnel', 'svcPidTunnel', services.localtonet);
    updateServiceCard('svcCardSsh', 'svcPillSsh', 'svcPidSsh', services.ssh);
    updateServiceCard('svcCardOllama', 'svcPillOllama', 'svcPidOllama', services.ollama);
  }

  // Active Job Preview
  if (tasks && tasks.active_tasks && tasks.active_tasks.length > 0) {
    const active = tasks.active_tasks[0];
    document.getElementById('activeJobContainer').innerHTML = `
      <div class="active-job-card">
        <div style="display:flex; justify-content:space-between; margin-bottom:0.35rem;">
          <strong style="font-size:0.88rem;">${escapeHtml(active.title)}</strong>
          <span class="badge-pill" style="background:var(--accent-amber); color:#000;">${active.progress}%</span>
        </div>
        <div class="progress-track-bg"><div class="progress-fill-cyan" style="width:${active.progress}%;"></div></div>
        <p class="card-subtitle font-mono" style="margin-top:0.35rem;">${escapeHtml((active.logs && active.logs.slice(-1)[0]) || 'Processing...')}</p>
      </div>
    `;
  } else {
    document.getElementById('activeJobContainer').innerHTML = `<p class="empty-state-muted">No background tasks currently running.</p>`;
  }

  // RAG stats
  if (rag) {
    const docEl = document.getElementById('ragDocsStat');
    if (docEl) docEl.textContent = `Documents: ${rag.documents_count || 0}`;
    const chunkEl = document.getElementById('ragChunksStat');
    if (chunkEl) chunkEl.textContent = `Chunks: ${rag.chunks_count || 0}`;
    const updEl = document.getElementById('ragUpdatedStat');
    if (updEl) updEl.textContent = `Synced: ${rag.updated_at || 'Never'}`;
  }
}

function updateServiceCard(cardId, pillId, pidId, svcData) {
  const card = document.getElementById(cardId);
  const pill = document.getElementById(pillId);
  const pid = document.getElementById(pidId);
  if (!card || !pill || !svcData) return;

  const isOnline = (svcData.status === 'online' || svcData.status === 'running');
  pill.textContent = svcData.status.toUpperCase();
  pill.className = `svc-state-pill ${isOnline ? 'online' : 'offline'}`;
  if (isOnline) card.classList.add('online'); else card.classList.remove('online');
  if (pid) pid.textContent = svcData.pid || '--';
}

// Navigation Tabs
function switchTab(tabId) {
  state.activeTab = tabId;

  // Desktop tabs
  document.querySelectorAll('.desktop-nav-tabs .nav-tab').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === tabId);
  });

  // Mobile dock buttons
  document.querySelectorAll('.mobile-bottom-dock .dock-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === tabId);
  });

  // Panes
  document.querySelectorAll('.tab-pane').forEach(p => {
    p.classList.toggle('active', p.id === `tab-${tabId}`);
  });

  // Tab-specific fetch triggers
  if (tabId === 'storage') fetchVaultFiles();
  if (tabId === 'media') fetchMediaLibrary();
  if (tabId === 'tasks') fetchTasks();
  if (tabId === 'events') fetchEvents();
  if (tabId === 'automation') fetchAutomationJobs();
  if (tabId === 'backups') fetchBackupsList();
  if (tabId === 'storage-intel') fetchStorageIntelligence();
  if (tabId === 'admin') { fetchAdminUsers(); fetchSharesList(); }
  if (tabId === 'settings') loadSettings();
}

function toggleMoreSheet(forceState) {
  const overlay = document.getElementById('moreSheetOverlay');
  if (!overlay) return;
  if (typeof forceState === 'boolean') {
    overlay.classList.toggle('open', forceState);
  } else {
    overlay.classList.toggle('open');
  }
}

// ==============================================================================
// VAULT STORAGE & TEMPORARY SHARES
// ==============================================================================

async function fetchVaultFiles() {
  try {
    const res = await fetch('/files', { headers: getAuthHeaders() });
    if (!res.ok) return;
    const files = await res.json();
    state.cachedFiles = files;
    renderVaultFiles(files);
  } catch (e) {}
}

function renderVaultFiles(files) {
  const container = document.getElementById('vaultFilesContainer');
  if (!container) return;

  if (!files || files.length === 0) {
    container.innerHTML = `<p class="empty-state-muted">No files in storage vault.</p>`;
    return;
  }

  container.innerHTML = files.map(f => {
    const isDir = f.is_dir;
    const name = f.name;
    return `
      <div class="vault-file-row">
        <div class="file-info-group">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="${isDir ? 'var(--accent-amber)' : 'var(--accent-cyan)'}" stroke-width="2">
            ${isDir ? '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>' : '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>'}
          </svg>
          <span class="file-name-text font-mono">${escapeHtml(name)}</span>
        </div>
        <div class="file-actions-group">
          ${!isDir ? `<button class="ghost-btn" onclick="openCreateShareModal('${escapeHtml(name)}')">Share</button>` : ''}
          ${!isDir ? `<button class="ghost-btn" onclick="viewChecksum('${escapeHtml(name)}')">Integrity</button>` : ''}
          ${!isDir ? `<a class="ghost-btn" href="/download/${encodeURIComponent(name)}?auth=${encodeURIComponent(state.token)}" download>Download</a>` : ''}
          <button class="ghost-btn danger" onclick="deleteVaultFile('${escapeHtml(name)}')">Delete</button>
        </div>
      </div>
    `;
  }).join('');
}

function filterVaultFiles() {
  const q = document.getElementById('vaultSearchInput')?.value.toLowerCase() || '';
  const typeFilter = document.getElementById('vaultTypeFilter')?.value || 'all';

  const filtered = state.cachedFiles.filter(f => {
    const name = f.name.toLowerCase();
    if (q && !name.includes(q)) return false;
    if (typeFilter === 'audio') return name.match(/\.(mp3|m4a|opus|wav|flac)$/);
    if (typeFilter === 'video') return name.match(/\.(mp4|mkv|webm|mov)$/);
    if (typeFilter === 'documents') return name.match(/\.(pdf|txt|md|docx|json|py|sh)$/);
    if (typeFilter === 'archives') return name.match(/\.(zip|tar|gz|7z|rar)$/);
    if (typeFilter === 'models') return name.match(/\.(gguf|bin)$/);
    return true;
  });
  renderVaultFiles(filtered);
}

async function handleFileUpload(file) {
  if (!file) return;
  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await fetch('/upload', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${state.token}`, 'localtonet-skip-warning': 'true' },
      body: formData
    });
    if (res.ok) {
      fetchVaultFiles();
    } else {
      const err = await res.json();
      alert(`Upload error: ${err.message || err.error}`);
    }
  } catch (e) {
    alert(`Upload failed: ${e.message}`);
  }
}

async function deleteVaultFile(filename) {
  if (!confirm(`Delete '${filename}' from storage vault?`)) return;
  try {
    const res = await fetch(`/files/${encodeURIComponent(filename)}`, {
      method: 'DELETE',
      headers: getAuthHeaders()
    });
    if (res.ok) {
      fetchVaultFiles();
      fetchMediaLibrary();
    }
  } catch (e) {}
}

async function triggerCleanTemp() {
  try {
    const res = await fetch('/api/vault/clean-temp', {
      method: 'POST',
      headers: getAuthHeaders()
    });
    if (res.ok) {
      alert('Temporary files swept successfully.');
      fetchVaultFiles();
      fetchStorageIntelligence();
    }
  } catch (e) {}
}

// Temporary Shares Modal
function openCreateShareModal(filename) {
  document.getElementById('shareFilenameInput').value = filename;
  document.getElementById('shareFilenameDisplay').textContent = `Target: ${filename}`;
  document.getElementById('shareResultBox').style.display = 'none';
  document.getElementById('createShareBtn').style.display = '';
  openModal('createShareModal');
}

async function handleCreateShareSubmit(e) {
  e.preventDefault();
  const filename = document.getElementById('shareFilenameInput').value;
  const duration = document.getElementById('shareDurationSelect').value;
  const max_downloads = parseInt(document.getElementById('shareMaxDownloads').value || '0');

  try {
    const res = await fetch('/api/shares', {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ filename, duration, max_downloads })
    });
    if (res.ok) {
      const data = await res.json();
      const fullUrl = `${window.location.origin}${data.share_url}`;
      document.getElementById('shareResultUrl').value = fullUrl;
      document.getElementById('shareResultBox').style.display = '';
      document.getElementById('createShareBtn').style.display = 'none';
    } else {
      const err = await res.json();
      alert(`Share error: ${err.message || err.error}`);
    }
  } catch (e) {
    alert(`Failed to create share: ${e.message}`);
  }
}

function copyShareUrl() {
  const el = document.getElementById('shareResultUrl');
  el.select();
  navigator.clipboard.writeText(el.value);
  alert('Share URL copied to clipboard!');
}

async function fetchSharesList() {
  const container = document.getElementById('adminSharesContainer');
  if (!container) return;
  try {
    const res = await fetch('/api/shares', { headers: getAuthHeaders() });
    if (!res.ok) return;
    const shares = await res.json();
    if (shares.length === 0) {
      container.innerHTML = `<p class="empty-state-muted">No active share links.</p>`;
      return;
    }
    container.innerHTML = shares.map(s => `
      <div class="vault-file-row">
        <div>
          <strong>${escapeHtml(s.filename)}</strong>
          <p class="card-subtitle font-mono">Downloads: ${s.downloads_count} | Exp: ${new Date(s.expires_at * 1000).toLocaleString()} ${s.revoked ? '(REVOKED)' : ''}</p>
        </div>
        ${!s.revoked ? `<button class="ghost-btn danger" onclick="revokeShareLink('${s.id}')">Revoke</button>` : ''}
      </div>
    `).join('');
  } catch (e) {}
}

async function revokeShareLink(shareId) {
  try {
    const res = await fetch(`/api/shares/${shareId}`, { method: 'DELETE', headers: getAuthHeaders() });
    if (res.ok) fetchSharesList();
  } catch (e) {}
}

async function viewChecksum(filename) {
  openModal('checksumModal');
  const box = document.getElementById('checksumContent');
  box.textContent = 'Computing SHA-256 and MD5 hashes...';
  try {
    const res = await fetch(`/api/vault/checksum/${encodeURIComponent(filename)}`, { headers: getAuthHeaders() });
    if (res.ok) {
      const data = await res.json();
      box.innerHTML = `
        <strong>File:</strong> ${escapeHtml(data.filename)}<br><br>
        <strong>SHA-256:</strong><br><span style="color:var(--accent-cyan);">${data.sha256}</span><br><br>
        <strong>MD5:</strong><br><span style="color:var(--accent-emerald);">${data.md5}</span>
      `;
    }
  } catch (e) {
    box.textContent = `Error computing checksum: ${e.message}`;
  }
}

// ==============================================================================
// MEDIA CENTER & RANGE STREAM PLAYER
// ==============================================================================

async function handleMediaDownloadSubmit(e) {
  e.preventDefault();
  const url = document.getElementById('mediaUrlInput').value.trim();
  const format = document.getElementById('mediaFormatSelect').value;
  const quality = document.getElementById('mediaQualitySelect').value;
  const destination = document.getElementById('mediaDestSelect').value;
  const subMode = document.getElementById('mediaSubtitlesSelect').value;
  const customName = document.getElementById('mediaCustomFilename').value.trim();

  try {
    const res = await fetch('/api/media/download', {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        url,
        format,
        quality,
        destination,
        subtitles: { mode: subMode },
        filename: customName,
        metadata: { embed_metadata: true, embed_thumbnail: true, embed_chapters: true }
      })
    });
    if (res.ok) {
      document.getElementById('mediaUrlInput').value = '';
      switchTab('tasks');
    } else {
      const err = await res.json();
      alert(`Download error: ${err.message || err.error}`);
    }
  } catch (e) {
    alert(`Failed to submit download: ${e.message}`);
  }
}

async function fetchMediaLibrary() {
  try {
    const res = await fetch('/api/media/library', { headers: getAuthHeaders() });
    if (!res.ok) return;
    state.mediaLibrary = await res.json();
    renderMediaLibrary();
  } catch (e) {}
}

function switchMediaCat(cat, btn) {
  state.activeMediaCat = cat;
  document.querySelectorAll('.tab-pill-group .tab-pill').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  renderMediaLibrary();
}

function renderMediaLibrary() {
  const container = document.getElementById('mediaLibraryContainer');
  if (!container) return;

  let items = [];
  if (state.activeMediaCat === 'all') {
    items = [...state.mediaLibrary.music, ...state.mediaLibrary.videos, ...state.mediaLibrary.podcasts, ...state.mediaLibrary.downloads];
  } else {
    items = state.mediaLibrary[state.activeMediaCat] || [];
  }

  if (items.length === 0) {
    container.innerHTML = `<p class="empty-state-muted">No media files found in this category.</p>`;
    return;
  }

  container.innerHTML = items.map(m => `
    <div class="media-card">
      <div class="media-card-title">${escapeHtml(m.filename)}</div>
      <div class="media-card-meta font-mono">
        <span>${m.format} • ${m.size_display}</span>
        <span>${m.created_at}</span>
      </div>
      <div class="media-card-actions">
        <button class="primary-action-btn" style="flex:1; padding:0.4rem 0.75rem; font-size:0.8rem;" onclick="playMediaStream('${m.stream_url}', '${escapeHtml(m.filename)}', '${m.format}')">
          Play Stream
        </button>
        <button class="ghost-btn" onclick="openCreateShareModal('${escapeHtml(m.path)}')">Share</button>
      </div>
    </div>
  `).join('');
}

function playMediaStream(streamUrl, title, format) {
  const card = document.getElementById('mediaPlayerCard');
  const mount = document.getElementById('playerMountContainer');
  const titleEl = document.getElementById('playerMediaTitle');
  if (!card || !mount) return;

  titleEl.textContent = title;
  card.style.display = '';

  const isVideo = ['MP4', 'MKV', 'WEBM', 'MOV'].includes(format.toUpperCase());
  const tokenQuery = `?auth=${encodeURIComponent(state.token)}`;

  if (isVideo) {
    mount.innerHTML = `<video controls autoplay preload="metadata" src="${streamUrl}${tokenQuery}"></video>`;
  } else {
    mount.innerHTML = `<audio controls autoplay preload="metadata" src="${streamUrl}${tokenQuery}"></audio>`;
  }
}

function closeMediaPlayer() {
  const card = document.getElementById('mediaPlayerCard');
  const mount = document.getElementById('playerMountContainer');
  if (mount) mount.innerHTML = '';
  if (card) card.style.display = 'none';
}

// ==============================================================================
// TASK QUEUE EXECUTION
// ==============================================================================

async function fetchTasks() {
  try {
    const res = await fetch('/api/tasks', { headers: getAuthHeaders() });
    if (!res.ok) return;
    const tasks = await res.json();
    renderTasksList(tasks);
  } catch (e) {}
}

function renderTasksList(tasks) {
  const container = document.getElementById('tasksListContainer');
  if (!container) return;

  if (tasks.length === 0) {
    container.innerHTML = `<p class="empty-state-muted">No background tasks found.</p>`;
    return;
  }

  container.innerHTML = tasks.map(t => {
    const isRunning = t.status === 'running';
    const isQueued = t.status === 'queued';
    return `
      <div class="glass-card" style="padding:0.85rem; border-left:3px solid ${isRunning ? 'var(--accent-cyan)' : (t.status === 'completed' ? 'var(--accent-emerald)' : 'var(--accent-rose)')};">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <div>
            <strong style="font-size:0.9rem;">${escapeHtml(t.title)}</strong>
            <p class="card-subtitle font-mono">Status: ${t.status.toUpperCase()} | Progress: ${t.progress}%</p>
          </div>
          ${(isRunning || isQueued) ? `<button class="ghost-btn danger" onclick="cancelTask('${t.id}')">Cancel</button>` : ''}
        </div>
        ${isRunning ? `<div class="progress-track-bg" style="margin-top:0.4rem;"><div class="progress-fill-cyan" style="width:${t.progress}%;"></div></div>` : ''}
        <div class="events-log-terminal" style="max-height:100px; margin-top:0.4rem;">
          ${(t.logs || []).slice(-3).map(l => `<div class="event-log-entry">${escapeHtml(l)}</div>`).join('')}
        </div>
      </div>
    `;
  }).join('');
}

async function cancelTask(taskId) {
  try {
    await fetch(`/api/tasks/${taskId}/cancel`, { method: 'POST', headers: getAuthHeaders() });
    fetchTasks();
  } catch (e) {}
}

// ==============================================================================
// AI STUDIO & RAG INDEXING
// ==============================================================================

async function checkModelEstimate(modelName) {
  const badge = document.getElementById('modelResourceBadge');
  if (!badge) return;
  try {
    const res = await fetch('/api/models/estimate', {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ model: modelName })
    });
    if (res.ok) {
      const data = await res.json();
      badge.textContent = `Estimated: ~${data.estimated_mb} MB | Available: ${data.available_mb} MB | Status: ${data.decision}`;
      badge.className = `model-resource-badge ${data.decision.toLowerCase()}`;
    }
  } catch (e) {}
}

async function toggleEngine(action) {
  try {
    const res = await fetch(`/${action}`, { method: 'POST', headers: getAuthHeaders() });
    const data = await res.json();
    alert(data.message || data.error);
    fetchSystemStatus();
  } catch (e) {
    alert(`Engine command failed: ${e.message}`);
  }
}

async function triggerRagRebuild() {
  try {
    const res = await fetch('/api/rag/index', { method: 'POST', headers: getAuthHeaders() });
    const data = await res.json();
    alert(data.message || data.reason || 'RAG rebuild scheduled.');
    fetchSystemStatus();
  } catch (e) {}
}

async function handleChatSubmit(e) {
  e.preventDefault();
  const input = document.getElementById('chatPromptInput');
  const prompt = input.value.trim();
  const model = document.getElementById('aiModelSelect').value;
  if (!prompt) return;

  input.value = '';
  appendChatMessage('user', prompt);

  const assistantBubble = appendChatMessage('assistant', '...');

  try {
    const res = await fetch('/chat/stream', {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ prompt, model, rag_enabled: true })
    });

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let assistantText = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunkStr = decoder.decode(value);
      const lines = chunkStr.split('\n');

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));
            if (data.token) {
              assistantText += data.token;
              assistantBubble.textContent = assistantText;
            }
          } catch (err) {}
        }
      }
    }
  } catch (e) {
    assistantBubble.textContent = `Error: ${e.message}`;
  }
}

function appendChatMessage(role, text) {
  const container = document.getElementById('chatMessagesContainer');
  if (!container) return null;
  const msgEl = document.createElement('div');
  msgEl.className = `chat-message ${role}`;
  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble';
  bubble.textContent = text;
  msgEl.appendChild(bubble);
  container.appendChild(msgEl);
  container.scrollTop = container.scrollHeight;
  return bubble;
}

function clearChat() {
  document.getElementById('chatMessagesContainer').innerHTML = '';
}

// ==============================================================================
// NETWORK DIAGNOSTICS
// ==============================================================================

async function testNetworkTarget(target) {
  const badgeMap = {
    'internet': ['diagBadgeInternet', 'diagLatInternet'],
    'nexusnode': ['diagBadgeNexus', 'diagLatNexus'],
    'tunnel': ['diagBadgeTunnel', 'diagLatTunnel'],
    'ollama': ['diagBadgeOllama', 'diagLatOllama']
  };

  const [bId, lId] = badgeMap[target] || [];
  if (bId) document.getElementById(bId).textContent = 'TESTING';

  try {
    const res = await fetch('/api/network/test', {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ target })
    });
    if (res.ok) {
      const data = await res.json();
      if (bId) {
        const badge = document.getElementById(bId);
        badge.textContent = data.status.toUpperCase();
        badge.className = `badge-pill ${data.status}`;
      }
      if (lId) {
        document.getElementById(lId).textContent = data.latency_ms !== null ? `${data.latency_ms} ms` : '-- ms';
      }
    }
  } catch (e) {}
}

function runAllNetworkTests() {
  testNetworkTarget('internet');
  testNetworkTarget('nexusnode');
  testNetworkTarget('tunnel');
  testNetworkTarget('ollama');
}

// ==============================================================================
// EVENTS & INCIDENT CORRELATION
// ==============================================================================

async function fetchEvents(category = state.activeEventCat) {
  state.activeEventCat = category;
  try {
    const res = await fetch(`/api/events?category=${category}&limit=80`, { headers: getAuthHeaders() });
    if (!res.ok) return;
    const events = await res.json();
    renderEventsTerminal(events);
  } catch (e) {}
}

function filterEventsCategory(cat, btn) {
  document.querySelectorAll('#eventFilterChips .chip').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  fetchEvents(cat);
}

function renderEventsTerminal(events) {
  const container = document.getElementById('eventsTerminalContainer');
  const feed = document.getElementById('recentEventsFeed');

  if (container) {
    if (events.length === 0) {
      container.innerHTML = `<p class="empty-state-muted">No events recorded for category '${state.activeEventCat}'.</p>`;
    } else {
      container.innerHTML = events.map(e => `
        <div class="event-log-entry">
          <span style="color:var(--text-dim);">[${e.timestamp}]</span>
          <span style="color:${e.level === 'CRITICAL' || e.level === 'ERROR' ? 'var(--accent-rose)' : (e.level === 'WARN' ? 'var(--accent-amber)' : 'var(--accent-cyan)')};">[${e.category}]</span>
          <span>${escapeHtml(e.message)}</span>
        </div>
      `).join('');
    }
  }

  if (feed) {
    feed.innerHTML = events.slice(0, 5).map(e => `
      <div style="font-size:0.78rem; display:flex; gap:0.4rem; padding:0.25rem 0; border-bottom:1px solid var(--border-subtle);">
        <span class="font-mono" style="color:var(--text-dim);">${e.timestamp}</span>
        <strong style="color:var(--accent-cyan);">${e.category}:</strong>
        <span style="white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${escapeHtml(e.message)}</span>
      </div>
    `).join('');
  }
}

// ==============================================================================
// SCHEDULED AUTOMATION
// ==============================================================================

async function fetchAutomationJobs() {
  const container = document.getElementById('automationJobsContainer');
  if (!container) return;
  try {
    const res = await fetch('/api/automation/jobs', { headers: getAuthHeaders() });
    if (!res.ok) return;
    const jobs = await res.json();
    container.innerHTML = jobs.map(j => `
      <div class="glass-card" style="padding:0.85rem;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <div>
            <strong>${escapeHtml(j.name)}</strong>
            <p class="card-subtitle font-mono">Interval: ${j.interval_seconds / 3600}h | Next: ${new Date((j.next_run || 0) * 1000).toLocaleTimeString()} | Status: ${j.last_status}</p>
          </div>
          <div style="display:flex; gap:0.4rem;">
            <button class="primary-action-btn" style="padding:0.35rem 0.75rem; font-size:0.78rem;" onclick="triggerAutomationJob('${j.id}')">Run Now</button>
            <button class="ghost-btn" onclick="toggleAutomationJob('${j.id}')">${j.enabled ? 'Disable' : 'Enable'}</button>
          </div>
        </div>
      </div>
    `).join('');
  } catch (e) {}
}

async function triggerAutomationJob(jobId) {
  try {
    const res = await fetch(`/api/automation/jobs/${jobId}/run`, { method: 'POST', headers: getAuthHeaders() });
    if (res.ok) {
      alert('Scheduled maintenance job enqueued.');
      fetchAutomationJobs();
      fetchTasks();
    }
  } catch (e) {}
}

async function toggleAutomationJob(jobId) {
  try {
    await fetch(`/api/automation/jobs/${jobId}/toggle`, { method: 'POST', headers: getAuthHeaders() });
    fetchAutomationJobs();
  } catch (e) {}
}

// ==============================================================================
// BACKUP & RESTORE
// ==============================================================================

async function fetchBackupsList() {
  const container = document.getElementById('backupsListContainer');
  if (!container) return;
  try {
    const res = await fetch('/api/backups', { headers: getAuthHeaders() });
    if (!res.ok) return;
    const backups = await res.json();
    if (backups.length === 0) {
      container.innerHTML = `<p class="empty-state-muted">No system backups created yet.</p>`;
      return;
    }
    container.innerHTML = backups.map(b => `
      <div class="glass-card" style="padding:0.85rem;">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem;">
          <div>
            <strong>${escapeHtml(b.filename)}</strong>
            <p class="card-subtitle font-mono">Size: ${Math.round(b.size_bytes / 1024)} KB | SHA-256: ${b.checksum.slice(0, 16)}...</p>
          </div>
          <div style="display:flex; gap:0.4rem;">
            <a class="ghost-btn" href="/api/backups/download/${b.id}?auth=${encodeURIComponent(state.token)}" download>Download</a>
            <button class="ghost-btn danger" onclick="restoreBackup('${b.id}')">Restore</button>
          </div>
        </div>
      </div>
    `).join('');
  } catch (e) {}
}

async function triggerQuickBackup() {
  try {
    const res = await fetch('/api/backups/create', { method: 'POST', headers: getAuthHeaders() });
    if (res.ok) {
      alert('Atomic backup created successfully.');
      fetchBackupsList();
    }
  } catch (e) {
    alert(`Backup failed: ${e.message}`);
  }
}

async function restoreBackup(backupId) {
  if (!confirm(`Restore configuration and RAG index from backup '${backupId}'?`)) return;
  try {
    const res = await fetch('/api/backups/restore', {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ backup_id: backupId, confirm: true })
    });
    const data = await res.json();
    alert(data.message || data.error);
  } catch (e) {
    alert(`Restore failed: ${e.message}`);
  }
}

// ==============================================================================
// STORAGE INTELLIGENCE
// ==============================================================================

async function fetchStorageIntelligence() {
  try {
    const res = await fetch('/api/storage/intelligence', { headers: getAuthHeaders() });
    if (!res.ok) return;
    const data = await res.json();
    renderStorageIntelligence(data);
  } catch (e) {}
}

function renderStorageIntelligence(data) {
  const { breakdown, large_files } = data;
  if (!breakdown) return;

  const total = (breakdown.videos_bytes + breakdown.music_bytes + breakdown.models_bytes + breakdown.vault_bytes + breakdown.temp_bytes + breakdown.rag_bytes) || 1;

  const vPct = Math.max(1, Math.round((breakdown.videos_bytes / total) * 100));
  const mPct = Math.max(1, Math.round((breakdown.music_bytes / total) * 100));
  const oPct = Math.max(1, Math.round((breakdown.models_bytes / total) * 100));
  const docPct = Math.max(1, Math.round((breakdown.vault_bytes / total) * 100));
  const tPct = Math.max(1, Math.round((breakdown.temp_bytes / total) * 100));

  const multiBar = document.getElementById('storageMultiBar');
  if (multiBar) {
    multiBar.innerHTML = `
      <div class="bar-segment video" style="width:${vPct}%;"></div>
      <div class="bar-segment music" style="width:${mPct}%;"></div>
      <div class="bar-segment models" style="width:${oPct}%;"></div>
      <div class="bar-segment vault" style="width:${docPct}%;"></div>
      <div class="bar-segment temp" style="width:${tPct}%;"></div>
    `;
  }

  const legend = document.getElementById('storageBreakdownLegend');
  if (legend) {
    legend.innerHTML = `
      <div class="legend-item"><div class="legend-dot" style="background:#3b82f6;"></div> Videos (${Math.round(breakdown.videos_bytes/(1024*1024))} MB)</div>
      <div class="legend-item"><div class="legend-dot" style="background:#10b981;"></div> Music (${Math.round(breakdown.music_bytes/(1024*1024))} MB)</div>
      <div class="legend-item"><div class="legend-dot" style="background:#a855f7;"></div> AI Models (${Math.round(breakdown.models_bytes/(1024*1024))} MB)</div>
      <div class="legend-item"><div class="legend-dot" style="background:#06b6d4;"></div> Vault Docs (${Math.round(breakdown.vault_bytes/(1024*1024))} MB)</div>
      <div class="legend-item"><div class="legend-dot" style="background:#f43f5e;"></div> Temp Files (${Math.round(breakdown.temp_bytes/(1024*1024))} MB)</div>
    `;
  }

  const lContainer = document.getElementById('largeFilesContainer');
  if (lContainer) {
    if (!large_files || large_files.length === 0) {
      lContainer.innerHTML = `<p class="empty-state-muted">No files exceeding 50 MB found.</p>`;
    } else {
      lContainer.innerHTML = large_files.map(f => `
        <div class="vault-file-row">
          <span class="file-name-text font-mono">${escapeHtml(f.name)}</span>
          <span class="font-mono" style="color:var(--accent-amber);">${f.size_mb} MB</span>
        </div>
      `).join('');
    }
  }
}

// ==============================================================================
// ADMIN HUB & RBAC
// ==============================================================================

async function fetchAdminUsers() {
  const container = document.getElementById('adminUsersContainer');
  if (!container) return;
  try {
    const res = await fetch('/api/admin/users', { headers: getAuthHeaders() });
    if (!res.ok) return;
    const users = await res.json();
    container.innerHTML = users.map(u => `
      <div class="vault-file-row">
        <div>
          <strong>${escapeHtml(u.user_id)}</strong>
          <span class="role-badge ${u.role}">${u.role.toUpperCase()}</span>
        </div>
        ${u.user_id !== 'admin' ? `<button class="ghost-btn danger" onclick="deleteUserAccount('${u.user_id}')">Delete</button>` : ''}
      </div>
    `).join('');
  } catch (e) {}
}

function openCreateUserModal() { openModal('createUserModal'); }

async function handleCreateUserSubmit(e) {
  e.preventDefault();
  const user_id = document.getElementById('newUserId').value.trim();
  const password = document.getElementById('newUserPassword').value.trim();

  try {
    const res = await fetch('/api/admin/users', {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ user_id, password })
    });
    if (res.ok) {
      closeModal('createUserModal');
      fetchAdminUsers();
    } else {
      const err = await res.json();
      alert(`User error: ${err.message || err.error}`);
    }
  } catch (e) {
    alert(`Failed to create user: ${e.message}`);
  }
}

async function deleteUserAccount(userId) {
  if (!confirm(`Delete user '${userId}'?`)) return;
  try {
    const res = await fetch(`/api/admin/users/${userId}`, { method: 'DELETE', headers: getAuthHeaders() });
    if (res.ok) fetchAdminUsers();
  } catch (e) {}
}

async function inspectDbTable(tableName) {
  const container = document.getElementById('dbRowsContainer');
  if (!container) return;
  try {
    const res = await fetch(`/api/admin/db/query?table=${tableName}&limit=25`, { headers: getAuthHeaders() });
    if (!res.ok) return;
    const data = await res.json();
    if (data.rows.length === 0) {
      container.innerHTML = `<p class="empty-state-muted">Table '${tableName}' is empty.</p>`;
      return;
    }
    container.innerHTML = `
      <div style="font-size:0.75rem; color:var(--text-dim); margin-bottom:0.4rem;">Showing ${data.count} rows</div>
      ${data.rows.map(r => `
        <div style="background:var(--bg-surface-2); padding:0.5rem; border-radius:var(--radius-sm); margin-bottom:0.35rem; font-family:monospace; font-size:0.78rem;">
          ${Object.entries(r).map(([k, v]) => `<div><span style="color:var(--accent-cyan);">${k}:</span> ${escapeHtml(String(v))}</div>`).join('')}
        </div>
      `).join('')}
    `;
  } catch (e) {}
}

// ==============================================================================
// SETTINGS
// ==============================================================================

async function loadSettings() {
  try {
    const res = await fetch('/api/settings', { headers: getAuthHeaders() });
    if (!res.ok) return;
    const s = await res.json();
    document.getElementById('settingRamNorm').value = s.ram_normal_mb;
    document.getElementById('settingRamPressure').value = s.ram_pressure_mb;
  } catch (e) {}
}

async function handleSettingsSave(e) {
  e.preventDefault();
  const ram_normal_mb = parseInt(document.getElementById('settingRamNorm').value);
  const ram_pressure_mb = parseInt(document.getElementById('settingRamPressure').value);

  try {
    const res = await fetch('/api/settings', {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ ram_normal_mb, ram_pressure_mb })
    });
    if (res.ok) {
      alert('Settings saved successfully.');
    }
  } catch (e) {}
}

// ==============================================================================
// AUTH & MODALS
// ==============================================================================

async function handleLoginSubmit(e) {
  e.preventDefault();
  const user_id = document.getElementById('loginUserId').value.trim();
  const password = document.getElementById('loginPassword').value.trim();
  const errBox = document.getElementById('loginErrorMsg');

  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'localtonet-skip-warning': 'true' },
      body: JSON.stringify({ user_id, password })
    });
    const data = await res.json();
    if (res.ok) {
      state.token = data.token;
      state.user = data.user;
      sessionStorage.setItem('nexus_auth_token', data.token);
      sessionStorage.setItem('nexus_user_profile', JSON.stringify(data.user));
      closeModal('loginModal');
      applyUserRoleUI();
      initDashboard();
    } else {
      errBox.textContent = data.message || data.error;
      errBox.style.display = 'block';
    }
  } catch (err) {
    errBox.textContent = `Login failed: ${err.message}`;
    errBox.style.display = 'block';
  }
}

function handleLogout(sendServer = true) {
  if (sendServer && state.token) {
    fetch('/api/auth/logout', { method: 'POST', headers: getAuthHeaders() }).catch(() => {});
  }
  state.token = '';
  state.user = null;
  sessionStorage.clear();
  localStorage.clear();
  openModal('loginModal');
}

function openModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add('open');
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove('open');
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
