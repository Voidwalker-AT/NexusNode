/**
 * NexusNode — 24/7 Personal Mobile Server Appliance Controller & SSE Streamer
 * Architecture: Centralized authState, Strict Least-Privilege RBAC, Reactive UI, Range Stream Player, Media & Task Queue
 */

// ==============================================================================
// 1. GLOBAL STATE & PRIVILEGES REGISTRY
// ==============================================================================

const ALL_PRIVILEGES_LIST = [
  "can_upload_files",
  "can_manage_files",
  "can_create_shares",
  "can_download_media",
  "can_use_ai",
  "can_use_rag",
  "can_control_services",
  "can_manage_models",
  "can_view_system_logs",
  "can_manage_users",
  "can_manage_backups",
  "can_manage_automation",
  "can_manage_settings"
];

const USER_DEFAULT_PRIVILEGES = {
  can_upload_files: true,
  can_manage_files: true,
  can_create_shares: false,
  can_download_media: true,
  can_use_ai: true,
  can_use_rag: true,
  can_control_services: false,
  can_manage_models: false,
  can_view_system_logs: false,
  can_manage_users: false,
  can_manage_backups: false,
  can_manage_automation: false,
  can_manage_settings: false
};

const authState = {
  token: null,
  user: null,
  role: 'user',
  privileges: {},
  isAuthenticated: false
};

let appState = {
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

// ==============================================================================
// 2. AUTHENTICATION & SESSION ISOLATION
// ==============================================================================

function hasPrivilege(privName) {
  if (!authState.isAuthenticated || !authState.user) return false;
  if (authState.role === 'admin') return true;
  return Boolean(authState.privileges && authState.privileges[privName]);
}

function getAuthHeaders() {
  const headers = {
    'localtonet-skip-warning': 'true',
    'Content-Type': 'application/json'
  };
  if (authState.token) {
    headers['Authorization'] = `Bearer ${authState.token}`;
  }
  return headers;
}

/**
 * Central API fetch wrapper.
 * Intercepts HTTP 401 to clear local auth state and force login.
 * Intercepts HTTP 403 to notify user without destroying session.
 */
async function apiFetch(url, options = {}) {
  const headers = {
    'localtonet-skip-warning': 'true',
    ...(options.headers || {})
  };
  if (authState.token) {
    headers['Authorization'] = `Bearer ${authState.token}`;
  }
  if (!headers['Content-Type'] && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }
  options.headers = headers;

  const res = await fetch(url, options);

  if (res.status === 401) {
    showToast('Session expired or invalid. Please sign in.', 'error');
    clearAuthState(true);
    throw new Error('Unauthorized (HTTP 401)');
  }

  if (res.status === 403) {
    const clone = res.clone();
    let msg = 'Permission denied (HTTP 403).';
    try {
      const errData = await clone.json();
      if (errData.message) msg = errData.message;
    } catch (_) {}
    showToast(msg, 'error');
  }

  return res;
}

function clearAuthState(showLogin = true) {
  // 1. Sever background polling & SSE
  if (appState.systemStatusInterval) {
    clearInterval(appState.systemStatusInterval);
    appState.systemStatusInterval = null;
  }
  if (appState.logEventSource) {
    appState.logEventSource.close();
    appState.logEventSource = null;
  }

  // 2. Clear client-side storage
  sessionStorage.removeItem('nexus_auth_token');
  sessionStorage.removeItem('nexus_user_profile');
  localStorage.removeItem('nexus_auth_token');
  localStorage.removeItem('nexus_user_profile');

  // 3. Reset in-memory auth state
  authState.token = null;
  authState.user = null;
  authState.role = 'user';
  authState.privileges = {};
  authState.isAuthenticated = false;

  // 4. Clear cached sensitive application data
  appState.cachedFiles = [];
  appState.mediaLibrary = { music: [], videos: [], podcasts: [], downloads: [], other: [] };
  appState.allEvents = [];
  appState.chatMessages = [];

  // 5. Clear sensitive DOM containers
  const containersToClear = [
    'adminUsersContainer',
    'adminSharesContainer',
    'dbRowsContainer',
    'eventsTerminalContainer',
    'backupsListContainer',
    'automationJobsContainer',
    'tasksListContainer',
    'vaultFilesContainer'
  ];
  containersToClear.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = '<p class="empty-state-muted">Sign in to load data.</p>';
  });

  // 6. Reset UI and Navigation
  document.getElementById('headerUsername').textContent = 'Guest';
  const roleBadge = document.getElementById('headerRoleBadge');
  roleBadge.textContent = 'GUEST';
  roleBadge.className = 'role-badge user';
  document.getElementById('headerUserAvatar').textContent = 'G';

  // Strictly hide all privileged / admin UI
  document.querySelectorAll('.admin-only').forEach(el => {
    el.style.setProperty('display', 'none', 'important');
  });
  document.querySelectorAll('.perm-backups, .perm-automation, .perm-settings, .perm-services, .perm-rag, .perm-upload, .perm-files, .perm-download-media').forEach(el => {
    el.style.setProperty('display', 'none', 'important');
  });

  // Reset tab to dashboard
  switchTabDirect('dashboard');

  // Clear login form
  const uInput = document.getElementById('loginUserId');
  const pInput = document.getElementById('loginPassword');
  if (uInput) uInput.value = '';
  if (pInput) pInput.value = '';
  const errBox = document.getElementById('loginErrorMsg');
  if (errBox) { errBox.textContent = ''; errBox.style.display = 'none'; }

  closeAllMoreMenus();
  closeModal('createUserModal');
  closeModal('editPrivilegesModal');
  closeModal('createShareModal');
  closeModal('checksumModal');

  if (showLogin) {
    openModal('loginModal');
  }
}

function updateAuthState(user, token) {
  authState.token = token;
  authState.user = user;
  authState.role = user.role || 'user';
  authState.privileges = user.privileges || {};
  authState.isAuthenticated = true;

  sessionStorage.setItem('nexus_auth_token', token);
  sessionStorage.setItem('nexus_user_profile', JSON.stringify(user));
  localStorage.setItem('nexus_auth_token', token);
  localStorage.setItem('nexus_user_profile', JSON.stringify(user));

  // Update header badges
  document.getElementById('headerUsername').textContent = user.user_id;
  const roleBadge = document.getElementById('headerRoleBadge');
  roleBadge.textContent = user.role.toUpperCase();
  roleBadge.className = `role-badge ${user.role}`;
  document.getElementById('headerUserAvatar').textContent = (user.user_id || 'U')[0].toUpperCase();

  // Apply RBAC UI Rules
  applyUserRoleUI();

  // Close Login Modal
  closeModal('loginModal');

  // If user was on a forbidden tab, route to dashboard
  if (appState.activeTab === 'admin' && user.role !== 'admin' && !hasPrivilege('can_manage_users')) {
    switchTab('dashboard');
  } else {
    switchTab(appState.activeTab || 'dashboard');
  }

  // Start system polling and initialize dashboard
  initDashboard();
}

function applyUserRoleUI() {
  const isAdmin = (authState.role === 'admin');

  // Admin-Only Elements
  document.querySelectorAll('.admin-only').forEach(el => {
    if (isAdmin || hasPrivilege('can_manage_users')) {
      el.style.removeProperty('display');
    } else {
      el.style.setProperty('display', 'none', 'important');
    }
  });

  // Granular Permission Elements
  document.querySelectorAll('.perm-backups').forEach(el => {
    el.style.display = (isAdmin || hasPrivilege('can_manage_backups')) ? '' : 'none';
  });

  document.querySelectorAll('.perm-automation').forEach(el => {
    el.style.display = (isAdmin || hasPrivilege('can_manage_automation')) ? '' : 'none';
  });

  document.querySelectorAll('.perm-settings').forEach(el => {
    el.style.display = (isAdmin || hasPrivilege('can_manage_settings')) ? '' : 'none';
  });

  document.querySelectorAll('.perm-services').forEach(el => {
    el.style.display = (isAdmin || hasPrivilege('can_control_services')) ? '' : 'none';
  });

  document.querySelectorAll('.perm-rag').forEach(el => {
    el.style.display = (isAdmin || hasPrivilege('can_use_rag')) ? '' : 'none';
  });

  document.querySelectorAll('.perm-upload').forEach(el => {
    el.style.display = (isAdmin || hasPrivilege('can_upload_files')) ? '' : 'none';
  });

  document.querySelectorAll('.perm-files').forEach(el => {
    el.style.display = (isAdmin || hasPrivilege('can_manage_files')) ? '' : 'none';
  });

  document.querySelectorAll('.perm-download-media').forEach(el => {
    el.style.display = (isAdmin || hasPrivilege('can_download_media')) ? '' : 'none';
  });
}

// Battery Optimization: Pause polling when tab is backgrounded
document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    if (appState.systemStatusInterval) {
      clearInterval(appState.systemStatusInterval);
      appState.systemStatusInterval = null;
    }
  } else {
    if (authState.token) {
      fetchSystemStatus();
      initSystemPolling();
    }
  }
});

// App Bootstrap
document.addEventListener('DOMContentLoaded', async () => {
  renderPrivilegesCheckboxes('newPrivilegesGrid', USER_DEFAULT_PRIVILEGES);

  // Global click listener to close dropdowns when clicking outside
  document.addEventListener('click', (e) => {
    const moreWrapper = document.querySelector('.desktop-more-wrapper');
    if (moreWrapper && !moreWrapper.contains(e.target)) {
      const menu = document.getElementById('desktopMoreMenu');
      if (menu) menu.classList.remove('open');
    }
  });

  // Global keydown for Escape key to close menus/modals
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeAllMoreMenus();
      closeModal('createUserModal');
      closeModal('editPrivilegesModal');
      closeModal('createShareModal');
      closeModal('checksumModal');
    }
  });

  const storedToken = sessionStorage.getItem('nexus_auth_token') || localStorage.getItem('nexus_auth_token');
  if (storedToken) {
    try {
      const res = await fetch('/api/auth/me', {
        headers: {
          'Authorization': `Bearer ${storedToken}`,
          'localtonet-skip-warning': 'true'
        }
      });
      if (res.ok) {
        const data = await res.json();
        updateAuthState(data.user, storedToken);
        return;
      }
    } catch (_) {}
  }

  // Not authenticated
  clearAuthState(true);
});

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
    if (res.ok && data.token) {
      updateAuthState(data.user, data.token);
      showToast(`Welcome back, ${data.user.user_id}!`, 'success');
    } else {
      errBox.textContent = data.message || data.error || 'Authentication failed.';
      errBox.style.display = 'block';
    }
  } catch (err) {
    errBox.textContent = `Login connection error: ${err.message}`;
    errBox.style.display = 'block';
  }
}

async function handleLogout() {
  if (authState.token) {
    try {
      await fetch('/api/auth/logout', {
        method: 'POST',
        headers: getAuthHeaders()
      });
    } catch (_) {}
  }
  clearAuthState(true);
  showToast('You have been signed out.', 'info');
}

// ==============================================================================
// 3. NAVIGATION & VIEW SWITCHING
// ==============================================================================

function switchTab(tabId) {
  // Permission checks before tab switch
  if (tabId === 'admin' && authState.role !== 'admin' && !hasPrivilege('can_manage_users')) {
    showToast('Permission denied: Admin role required.', 'error');
    return;
  }
  if (tabId === 'backups' && authState.role !== 'admin' && !hasPrivilege('can_manage_backups')) {
    showToast('Permission denied: Backups management required.', 'error');
    return;
  }
  if (tabId === 'automation' && authState.role !== 'admin' && !hasPrivilege('can_manage_automation')) {
    showToast('Permission denied: Automation management required.', 'error');
    return;
  }
  if (tabId === 'settings' && authState.role !== 'admin' && !hasPrivilege('can_manage_settings')) {
    showToast('Permission denied: Settings management required.', 'error');
    return;
  }

  switchTabDirect(tabId);
}

function switchTabDirect(tabId) {
  appState.activeTab = tabId;

  // Toggle Tab Panes
  document.querySelectorAll('.tab-pane').forEach(pane => {
    pane.classList.remove('active');
  });
  const activePane = document.getElementById(`tab-${tabId}`);
  if (activePane) {
    activePane.classList.add('active');
  }

  // Update Desktop Navigation Tabs
  document.querySelectorAll('.desktop-nav-tabs .nav-tab').forEach(btn => {
    if (btn.getAttribute('data-tab') === tabId) {
      btn.classList.add('active');
    } else {
      btn.classList.remove('active');
    }
  });

  // Update Mobile Bottom Dock
  document.querySelectorAll('.mobile-bottom-dock .dock-btn').forEach(btn => {
    if (btn.getAttribute('data-tab') === tabId) {
      btn.classList.add('active');
    } else {
      btn.classList.remove('active');
    }
  });

  // Trigger Data Loads for Active Tab
  if (authState.isAuthenticated) {
    if (tabId === 'storage') fetchVaultFiles();
    else if (tabId === 'media') fetchMediaLibrary();
    else if (tabId === 'tasks') fetchTasks();
    else if (tabId === 'events') fetchEvents();
    else if (tabId === 'storage-intel') fetchStorageIntelligence();
    else if (tabId === 'backups') fetchBackupsList();
    else if (tabId === 'automation') fetchAutomationJobs();
    else if (tabId === 'settings') loadSettings();
    else if (tabId === 'admin') { fetchAdminUsers(); fetchSharesList(); }
    else if (tabId === 'network') runAllNetworkTests();
  }

  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function toggleDesktopMoreMenu(e) {
  if (e) e.stopPropagation();
  const menu = document.getElementById('desktopMoreMenu');
  if (menu) menu.classList.toggle('open');
}

function toggleMobileMoreSheet(open = null) {
  const overlay = document.getElementById('moreSheetOverlay');
  if (!overlay) return;
  if (open === null) {
    overlay.classList.toggle('open');
  } else if (open) {
    overlay.classList.add('open');
  } else {
    overlay.classList.remove('open');
  }
}

function closeAllMoreMenus() {
  const dMenu = document.getElementById('desktopMoreMenu');
  if (dMenu) dMenu.classList.remove('open');
  toggleMobileMoreSheet(false);
}

// ==============================================================================
// 4. DASHBOARD & CENTRAL TELEMETRY POLLING
// ==============================================================================

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
  if (appState.systemStatusInterval) clearInterval(appState.systemStatusInterval);
  appState.systemStatusInterval = setInterval(fetchSystemStatus, 3000);
}

async function fetchSystemStatus() {
  if (!authState.token) return;
  try {
    const res = await apiFetch('/api/system/status');
    if (!res.ok) return;
    const data = await res.json();
    renderApplianceStatus(data);
  } catch (_) {}
}

function renderApplianceStatus(data) {
  const { server, appliance, memory, disk, device, services, tasks } = data;

  // Header Subtitle & WAN Status
  if (server) {
    document.getElementById('serverApplianceSub').textContent = `${server.device || 'Android Termux'} • Uptime: ${server.uptime || '--'}`;
    const tunnelPill = document.getElementById('metaTunnelStatus');
    if (tunnelPill && services && services.localtonet) {
      const isOnline = (services.localtonet.status === 'online');
      tunnelPill.textContent = isOnline ? 'Active' : 'Offline';
      tunnelPill.style.color = isOnline ? 'var(--accent-cyan)' : 'var(--accent-rose)';
    }
  }

  // Thermal & Battery Telemetry
  if (device) {
    const thermPill = document.getElementById('metaThermalState');
    if (thermPill) {
      thermPill.textContent = device.thermal_state || 'NORMAL';
      thermPill.style.color = (device.thermal_state === 'CRITICAL') ? 'var(--accent-rose)' :
        ((device.thermal_state === 'THROTTLED' || device.thermal_state === 'WARM') ? 'var(--accent-amber)' : 'var(--accent-emerald)');
    }
    const batPill = document.getElementById('metaBatteryPct');
    if (batPill) {
      batPill.textContent = (device.battery_percent !== null) ? `${device.battery_percent}%` : '--%';
    }
  }

  // Governor State Badge
  if (appliance) {
    const badge = document.getElementById('governorStateBadge');
    if (badge) {
      badge.textContent = appliance.badge || '● HEALTHY';
      badge.className = `governor-badge ${appliance.state.toLowerCase().includes('crit') ? 'critical' : (appliance.state.toLowerCase().includes('press') ? 'pressure' : 'normal')}`;
    }
  }

  // RAM Usage
  if (memory) {
    document.getElementById('ramStatText').textContent = `${memory.used_mb} MB / ${memory.total_mb} MB (${memory.ram_percent}%)`;
    document.getElementById('ramProgressBar').style.width = `${memory.ram_percent}%`;
    document.getElementById('ramAvailableDetail').textContent = `Available: ${memory.available_mb} MB`;
  }

  // Disk Storage
  if (disk) {
    document.getElementById('diskStatText').textContent = `${disk.used_gb} GB / ${disk.total_gb} GB (${disk.percent}%)`;
    document.getElementById('diskProgressBar').style.width = `${disk.percent}%`;
    document.getElementById('diskFreeDetail').textContent = `Free: ${disk.free_gb} GB`;
    document.getElementById('diskTotalDetail').textContent = `Capacity: ${disk.total_gb} GB`;
  }

  // Services Quad
  if (services) {
    updateServiceCard('svcCardNexus', 'svcPillNexus', 'svcPidNexus', services.nexusnode);
    updateServiceCard('svcCardTunnel', 'svcPillTunnel', 'svcPidTunnel', services.localtonet);
    updateServiceCard('svcCardSsh', 'svcPillSsh', 'svcPidSsh', services.ssh);
    updateServiceCard('svcCardOllama', 'svcPillOllama', 'svcPidOllama', services.ollama);
  }

  // Active Task Preview
  const taskContainer = document.getElementById('activeJobContainer');
  if (taskContainer) {
    if (tasks && tasks.active_tasks && tasks.active_tasks.length > 0) {
      const active = tasks.active_tasks[0];
      taskContainer.innerHTML = `
        <div class="active-job-card">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <strong>${escapeHtml(active.title)}</strong>
            <span class="badge-pill available">${active.progress}%</span>
          </div>
          <div class="progress-track-bg" style="margin: 0.5rem 0;">
            <div class="progress-fill-cyan" style="width: ${active.progress}%;"></div>
          </div>
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <span class="font-mono" style="font-size:0.75rem; color:var(--text-muted);">${escapeHtml(active.type)}</span>
            <button class="ghost-btn danger" style="padding:0.25rem 0.5rem; font-size:0.75rem;" onclick="cancelTask('${active.id}')">Cancel</button>
          </div>
        </div>
      `;
    } else {
      taskContainer.innerHTML = `<p class="empty-state-muted">No background tasks currently executing.</p>`;
    }
  }

  // RAG Stats
  if (data.rag) {
    const dStat = document.getElementById('ragDocsStat');
    const cStat = document.getElementById('ragChunksStat');
    const uStat = document.getElementById('ragUpdatedStat');
    if (dStat) dStat.textContent = `Docs: ${data.rag.documents_count || 0}`;
    if (cStat) cStat.textContent = `Chunks: ${data.rag.chunks_count || 0}`;
    if (uStat) uStat.textContent = `Synced: ${data.rag.updated_at ? new Date(data.rag.updated_at * 1000).toLocaleTimeString() : 'Never'}`;
  }
}

function updateServiceCard(cardId, pillId, pidId, serviceData) {
  const card = document.getElementById(cardId);
  const pill = document.getElementById(pillId);
  const pidSpan = document.getElementById(pidId);

  if (!card || !pill || !serviceData) return;

  const isOnline = (serviceData.status === 'online' || serviceData.status === 'running');
  if (isOnline) {
    card.classList.add('online');
    pill.textContent = 'ONLINE';
    pill.className = 'svc-state-pill online';
  } else {
    card.classList.remove('online');
    pill.textContent = (serviceData.status || 'OFFLINE').toUpperCase();
    pill.className = 'svc-state-pill';
  }

  if (pidSpan) {
    pidSpan.textContent = serviceData.pid || '--';
  }
}

// ==============================================================================
// 5. STORAGE VAULT OPERATIONS
// ==============================================================================

async function fetchVaultFiles() {
  const container = document.getElementById('vaultFilesContainer');
  if (!container) return;

  try {
    const res = await apiFetch('/files');
    if (!res.ok) return;
    const files = await res.json();
    appState.cachedFiles = files;
    renderVaultFiles(files);
  } catch (_) {}
}

function renderVaultFiles(files) {
  const container = document.getElementById('vaultFilesContainer');
  if (!container) return;

  if (!files || files.length === 0) {
    container.innerHTML = `<p class="empty-state-muted">Vault is empty. Upload or download media to get started.</p>`;
    return;
  }

  const canManage = hasPrivilege('can_manage_files');
  const canShare = hasPrivilege('can_create_shares');

  container.innerHTML = files.map(f => `
    <div class="vault-file-row">
      <div class="file-info-group">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: ${f.is_dir ? 'var(--accent-amber)' : 'var(--accent-cyan)'}; flex-shrink:0;">
          ${f.is_dir ? '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>' : '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>'}
        </svg>
        <span class="file-name-text font-mono">${escapeHtml(f.name)}</span>
      </div>
      <div class="file-actions-row">
        ${!f.is_dir ? `<a class="ghost-btn" href="/download/${encodeURIComponent(f.name)}?auth=${encodeURIComponent(authState.token)}" download title="Download">↓</a>` : ''}
        ${!f.is_dir && canShare ? `<button class="ghost-btn" title="Create Temporary Share Link" onclick="openCreateShareModal('${escapeHtml(f.name)}')">Share</button>` : ''}
        ${!f.is_dir && canManage ? `<button class="ghost-btn" title="Checksums" onclick="showFileChecksum('${escapeHtml(f.name)}')">#</button>` : ''}
        ${canManage ? `<button class="ghost-btn danger" title="Delete File" onclick="deleteVaultFile('${escapeHtml(f.name)}')">&times;</button>` : ''}
      </div>
    </div>
  `).join('');
}

function filterVaultFiles() {
  const query = (document.getElementById('vaultSearchInput')?.value || '').toLowerCase();
  const typeFilter = document.getElementById('vaultTypeFilter')?.value || 'all';

  const filtered = appState.cachedFiles.filter(f => {
    const matchesSearch = f.name.toLowerCase().includes(query);
    if (!matchesSearch) return false;
    if (typeFilter === 'all') return true;

    const ext = f.name.split('.').pop().toLowerCase();
    if (typeFilter === 'audio') return ['mp3', 'm4a', 'opus', 'wav', 'flac'].includes(ext);
    if (typeFilter === 'video') return ['mp4', 'mkv', 'webm', 'mov'].includes(ext);
    if (typeFilter === 'documents') return ['pdf', 'txt', 'md', 'docx', 'py', 'json'].includes(ext);
    if (typeFilter === 'archives') return ['zip', 'tar', 'gz', '7z', 'bz2'].includes(ext);
    if (typeFilter === 'models') return ['gguf', 'bin'].includes(ext);
    return true;
  });

  renderVaultFiles(filtered);
}

async function handleFileUpload(file) {
  if (!file) return;
  if (!hasPrivilege('can_upload_files')) {
    showToast('Permission denied: File upload forbidden.', 'error');
    return;
  }

  const formData = new FormData();
  formData.append('file', file);

  showToast(`Uploading '${file.name}'...`, 'info');
  try {
    const res = await apiFetch('/upload', {
      method: 'POST',
      body: formData
    });
    if (res.ok) {
      showToast(`'${file.name}' uploaded successfully.`, 'success');
      fetchVaultFiles();
      fetchStorageIntelligence();
    }
  } catch (err) {
    showToast(`Upload failed: ${err.message}`, 'error');
  }
}

async function deleteVaultFile(filename) {
  if (!hasPrivilege('can_manage_files')) {
    showToast('Permission denied: File deletion forbidden.', 'error');
    return;
  }

  if (!confirm(`Are you sure you want to delete '${filename}'?`)) return;

  try {
    const res = await apiFetch(`/files/${encodeURIComponent(filename)}`, { method: 'DELETE' });
    if (res.ok) {
      showToast(`'${filename}' deleted.`, 'info');
      fetchVaultFiles();
      fetchStorageIntelligence();
    }
  } catch (err) {
    showToast(`Delete failed: ${err.message}`, 'error');
  }
}

async function showFileChecksum(filename) {
  openModal('checksumModal');
  const box = document.getElementById('checksumContent');
  box.textContent = `Calculating SHA-256 and MD5 for '${filename}'...`;

  try {
    const res = await apiFetch(`/api/vault/checksum/${encodeURIComponent(filename)}`);
    if (res.ok) {
      const data = await res.json();
      box.innerHTML = `
        <div style="display:flex; flex-direction:column; gap:0.5rem;">
          <div><strong>Target:</strong> ${escapeHtml(data.filename)}</div>
          <div><strong>Size:</strong> ${(data.size_bytes / 1024).toFixed(1)} KB (${data.size_bytes} bytes)</div>
          <div><strong>SHA-256:</strong><br><span style="color:var(--accent-cyan);">${data.sha256}</span></div>
          <div><strong>MD5:</strong><br><span style="color:var(--accent-emerald);">${data.md5}</span></div>
        </div>
      `;
    } else {
      box.textContent = 'Failed to calculate checksum.';
    }
  } catch (err) {
    box.textContent = `Error: ${err.message}`;
  }
}

async function triggerCleanTemp() {
  if (!hasPrivilege('can_manage_files')) {
    showToast('Permission denied: File cleanup forbidden.', 'error');
    return;
  }
  try {
    const res = await apiFetch('/api/vault/clean-temp', { method: 'POST' });
    if (res.ok) {
      showToast('Temporary download artifacts swept.', 'success');
      fetchVaultFiles();
      fetchStorageIntelligence();
    }
  } catch (_) {}
}

// ==============================================================================
// 6. MEDIA CENTER & STREAMING
// ==============================================================================

async function handleMediaDownloadSubmit(e) {
  e.preventDefault();
  if (!hasPrivilege('can_download_media')) {
    showToast('Permission denied: Media downloading forbidden.', 'error');
    return;
  }

  const url = document.getElementById('mediaUrlInput').value.trim();
  const format = document.getElementById('mediaFormatSelect').value;
  const quality = document.getElementById('mediaQualitySelect').value;
  const destination = document.getElementById('mediaDestSelect').value;
  const subtitlesMode = document.getElementById('mediaSubtitlesSelect').value;
  const filename = document.getElementById('mediaCustomFilename').value.trim();

  try {
    const res = await apiFetch('/api/media/download', {
      method: 'POST',
      body: JSON.stringify({
        url,
        format,
        quality,
        destination,
        subtitles: { mode: subtitlesMode },
        filename
      })
    });
    if (res.ok) {
      const data = await res.json();
      showToast(`Enqueued ${data.count || 1} media download task(s).`, 'success');
      document.getElementById('mediaUrlInput').value = '';
      document.getElementById('mediaCustomFilename').value = '';
      switchTab('tasks');
    }
  } catch (err) {
    showToast(`Enqueue failed: ${err.message}`, 'error');
  }
}

async function fetchMediaLibrary() {
  const container = document.getElementById('mediaLibraryContainer');
  if (!container) return;

  try {
    const res = await apiFetch('/api/media/library');
    if (!res.ok) return;
    const library = await res.json();
    appState.mediaLibrary = library;
    renderMediaLibrary();
  } catch (_) {}
}

function switchMediaCat(category, btn) {
  appState.activeMediaCat = category;
  document.querySelectorAll('.tab-pill-group .tab-pill').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  renderMediaLibrary();
}

function renderMediaLibrary() {
  const container = document.getElementById('mediaLibraryContainer');
  if (!container) return;

  let items = [];
  const cat = appState.activeMediaCat;

  if (cat === 'all') {
    items = [
      ...appState.mediaLibrary.music,
      ...appState.mediaLibrary.videos,
      ...appState.mediaLibrary.podcasts,
      ...appState.mediaLibrary.downloads,
      ...appState.mediaLibrary.other
    ];
  } else {
    items = appState.mediaLibrary[cat] || [];
  }

  if (items.length === 0) {
    container.innerHTML = `<p class="empty-state-muted">No media found in '${cat}'.</p>`;
    return;
  }

  container.innerHTML = items.map(item => `
    <div class="media-card">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <span class="badge-pill available font-mono">${item.format}</span>
        <span class="font-mono" style="font-size:0.72rem; color:var(--text-dim);">${item.size_display}</span>
      </div>
      <strong class="file-name-text font-mono" style="font-size:0.82rem; margin:0.25rem 0;">${escapeHtml(item.filename)}</strong>
      <div style="display:flex; gap:0.4rem; margin-top:auto;">
        <button class="primary-action-btn full-width" style="padding:0.35rem 0.5rem; font-size:0.76rem;" onclick="playMediaStream('${escapeHtml(item.path)}', '${escapeHtml(item.filename)}', '${item.format}')">▶ Play</button>
        <a class="ghost-btn" href="${item.stream_url}?auth=${encodeURIComponent(authState.token)}" download title="Direct Download">↓</a>
      </div>
    </div>
  `).join('');
}

function playMediaStream(relPath, filename, format) {
  const playerCard = document.getElementById('mediaPlayerCard');
  const mount = document.getElementById('playerMountContainer');
  const title = document.getElementById('playerMediaTitle');
  const sub = document.getElementById('playerMediaSub');

  if (!playerCard || !mount) return;

  playerCard.style.display = 'flex';
  title.textContent = filename;
  sub.textContent = `Streaming: ${relPath}`;

  const streamUrl = `/stream/${encodeURIComponent(relPath)}?auth=${encodeURIComponent(authState.token)}`;
  const isVideo = ['MP4', 'MKV', 'WEBM', 'MOV'].includes(format.toUpperCase());

  if (isVideo) {
    mount.innerHTML = `<video controls autoplay style="width:100%; max-height:420px;" src="${streamUrl}"></video>`;
  } else {
    mount.innerHTML = `<audio controls autoplay style="width:100%; padding:1rem;" src="${streamUrl}"></audio>`;
  }
}

function closeMediaPlayer() {
  const playerCard = document.getElementById('mediaPlayerCard');
  const mount = document.getElementById('playerMountContainer');
  if (mount) mount.innerHTML = '';
  if (playerCard) playerCard.style.display = 'none';
}

// ==============================================================================
// 7. TASK QUEUE & WORKER
// ==============================================================================

async function fetchTasks() {
  const container = document.getElementById('tasksListContainer');
  if (!container) return;

  try {
    const res = await apiFetch('/api/tasks');
    if (!res.ok) return;
    const tasks = await res.json();
    renderTasks(tasks);
  } catch (_) {}
}

function renderTasks(tasks) {
  const container = document.getElementById('tasksListContainer');
  if (!container) return;

  if (!tasks || tasks.length === 0) {
    container.innerHTML = `<p class="empty-state-muted">No background tasks found.</p>`;
    return;
  }

  container.innerHTML = tasks.map(t => `
    <div class="task-item-card ${t.status === 'running' ? 'running' : ''}">
      <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.4rem;">
        <div>
          <span class="badge-pill ${t.status === 'running' ? 'available' : ''}">${t.status.toUpperCase()}</span>
          <strong style="margin-left:0.4rem;">${escapeHtml(t.title)}</strong>
        </div>
        <div style="display:flex; align-items:center; gap:0.5rem;">
          <span class="font-mono" style="font-size:0.75rem; color:var(--text-muted);">${t.progress}%</span>
          ${t.status === 'running' || t.status === 'queued' ? `<button class="ghost-btn danger" style="padding:0.2rem 0.5rem; font-size:0.72rem;" onclick="cancelTask('${t.id}')">Cancel</button>` : ''}
        </div>
      </div>
      <div class="progress-track-bg">
        <div class="progress-fill-cyan" style="width: ${t.progress}%;"></div>
      </div>
      ${t.logs && t.logs.length > 0 ? `
        <div class="font-mono" style="font-size:0.72rem; color:var(--text-dim); background:#03060c; padding:0.4rem; border-radius:var(--radius-xs); max-height:80px; overflow-y:auto;">
          ${escapeHtml(t.logs.slice(-3).join('\n'))}
        </div>
      ` : ''}
    </div>
  `).join('');
}

async function cancelTask(taskId) {
  try {
    const res = await apiFetch(`/api/tasks/${taskId}/cancel`, { method: 'POST' });
    if (res.ok) {
      showToast('Task cancellation requested.', 'info');
      fetchTasks();
    }
  } catch (err) {
    showToast(`Cancel failed: ${err.message}`, 'error');
  }
}

// ==============================================================================
// 8. AI STUDIO, RAG & OLLAMA
// ==============================================================================

async function checkModelEstimate(modelName) {
  const badge = document.getElementById('modelResourceBadge');
  if (!badge) return;

  try {
    const res = await apiFetch('/api/models/estimate', {
      method: 'POST',
      body: JSON.stringify({ model: modelName })
    });
    if (res.ok) {
      const data = await res.json();
      badge.textContent = `RAM: ~${data.estimated_mb} MB | Available: ${data.available_mb} MB | ${data.decision}`;
      badge.className = `model-resource-badge ${data.decision === 'SAFE' ? 'safe' : 'blocked'}`;
    }
  } catch (_) {}
}

async function toggleEngine(action) {
  if (!hasPrivilege('can_control_services')) {
    showToast('Permission denied: Service control forbidden.', 'error');
    return;
  }
  showToast(`Issuing AI engine '${action}' command...`, 'info');
  try {
    const res = await apiFetch(`/${action}`, { method: 'POST' });
    const data = await res.json();
    showToast(data.message || data.error || 'Command sent', res.ok ? 'success' : 'error');
    fetchSystemStatus();
  } catch (err) {
    showToast(`Engine toggle failed: ${err.message}`, 'error');
  }
}

async function triggerRagRebuild() {
  if (!hasPrivilege('can_use_rag')) {
    showToast('Permission denied: RAG indexing forbidden.', 'error');
    return;
  }
  try {
    const res = await apiFetch('/api/rag/index', { method: 'POST' });
    if (res.ok) {
      showToast('RAG indexing initiated in background.', 'success');
      fetchSystemStatus();
    }
  } catch (err) {
    showToast(`RAG error: ${err.message}`, 'error');
  }
}

async function handleChatSubmit(e) {
  e.preventDefault();
  if (!hasPrivilege('can_use_ai')) {
    showToast('Permission denied: AI usage forbidden.', 'error');
    return;
  }

  const promptInput = document.getElementById('chatPromptInput');
  const prompt = promptInput.value.trim();
  if (!prompt) return;

  const model = document.getElementById('aiModelSelect')?.value || 'qwen2.5:0.5b';
  promptInput.value = '';

  appendChatMessage('user', prompt);

  const assistantBubble = appendChatMessage('assistant', '...');
  let fullResponse = '';

  try {
    const res = await fetch('/chat/stream', {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ prompt, model, rag_enabled: true })
    });

    if (res.status === 401) {
      clearAuthState(true);
      return;
    }
    if (res.status === 403) {
      assistantBubble.textContent = 'Permission denied: You do not have access to AI Studio.';
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder('utf-8');

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunkText = decoder.decode(value);
      const lines = chunkText.split('\n');

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));
            if (data.token) {
              fullResponse += data.token;
              assistantBubble.textContent = fullResponse;
            }
            if (data.citations && data.citations.length > 0) {
              const citBox = document.createElement('div');
              citBox.className = 'citations-box';
              citBox.innerHTML = `<strong>Vault Citations:</strong><br>` + data.citations.map(c => `• ${escapeHtml(c.doc)}`).join('<br>');
              assistantBubble.parentNode.insertBefore(citBox, assistantBubble);
            }
            if (data.error) {
              assistantBubble.textContent = `Error: ${data.error}`;
            }
          } catch (_) {}
        }
      }
    }
  } catch (err) {
    assistantBubble.textContent = `Streaming failed: ${err.message}`;
  }
}

function appendChatMessage(role, text) {
  const container = document.getElementById('chatMessagesContainer');
  if (!container) return null;

  const msgDiv = document.createElement('div');
  msgDiv.className = `chat-message ${role}`;
  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble';
  bubble.textContent = text;
  msgDiv.appendChild(bubble);
  container.appendChild(msgDiv);
  container.scrollTop = container.scrollHeight;
  return bubble;
}

function clearChat() {
  const container = document.getElementById('chatMessagesContainer');
  if (container) {
    container.innerHTML = `
      <div class="chat-message assistant">
        <div class="chat-bubble">NexusNode AI Studio ready. How can I assist you with your vault documents today?</div>
      </div>
    `;
  }
}

// ==============================================================================
// 9. NETWORK CENTER DIAGNOSTICS
// ==============================================================================

async function runAllNetworkTests() {
  testNetworkTarget('internet');
  testNetworkTarget('nexusnode');
  testNetworkTarget('tunnel');
  testNetworkTarget('ollama');
}

async function testNetworkTarget(target) {
  const badgeId = `diagBadge${target.charAt(0).toUpperCase() + target.slice(1)}`;
  const latId = `diagLat${target.charAt(0).toUpperCase() + target.slice(1)}`;
  const badge = document.getElementById(badgeId);
  const latSpan = document.getElementById(latId);

  if (badge) badge.textContent = 'PROBING';

  try {
    const res = await apiFetch('/api/network/test', {
      method: 'POST',
      body: JSON.stringify({ target })
    });
    if (res.ok) {
      const data = await res.json();
      if (badge) {
        badge.textContent = data.status.toUpperCase();
        badge.className = `badge-pill ${data.status === 'available' ? 'available' : 'unavailable'}`;
      }
      if (latSpan && data.latency_ms !== null) {
        latSpan.textContent = `${data.latency_ms} ms`;
      }
    }
  } catch (_) {
    if (badge) {
      badge.textContent = 'ERROR';
      badge.className = 'badge-pill unavailable';
    }
  }
}

// ==============================================================================
// 10. EVENTS & AUDIT LOGS
// ==============================================================================

async function fetchEvents() {
  const container = document.getElementById('eventsTerminalContainer');
  const recentTicker = document.getElementById('recentEventsFeed');

  try {
    const res = await apiFetch(`/api/events?category=${appState.activeEventCat}&limit=60`);
    if (!res.ok) return;
    const events = await res.json();
    appState.allEvents = events;

    // Render in main terminal
    if (container) {
      if (events.length === 0) {
        container.innerHTML = `<p class="empty-state-muted">No audit events found.</p>`;
      } else {
        container.innerHTML = events.map(e => `
          <div class="log-entry">
            <span class="log-time">[${new Date(e.created_at * 1000).toLocaleTimeString()}]</span>
            <span class="log-cat">${escapeHtml(e.category)}</span>
            <span class="log-msg">${escapeHtml(e.message)}</span>
          </div>
        `).join('');
      }
    }

    // Render in Dashboard Recent Events Ticker
    if (recentTicker) {
      if (events.length === 0) {
        recentTicker.innerHTML = `<p class="empty-state-muted">No recent events.</p>`;
      } else {
        recentTicker.innerHTML = events.slice(0, 5).map(e => `
          <div style="display:flex; justify-content:space-between; font-size:0.75rem; padding:0.25rem 0; border-bottom:1px solid var(--border-subtle);">
            <span class="font-mono" style="color:var(--text-muted);">${new Date(e.created_at * 1000).toLocaleTimeString()}</span>
            <span class="font-mono" style="color:var(--accent-cyan); font-weight:700;">${escapeHtml(e.category)}</span>
            <span class="file-name-text" style="max-width:60%;">${escapeHtml(e.message)}</span>
          </div>
        `).join('');
      }
    }
  } catch (_) {}
}

function filterEventsCategory(cat, btn) {
  appState.activeEventCat = cat;
  document.querySelectorAll('#eventFilterChips .chip').forEach(c => c.classList.remove('active'));
  if (btn) btn.classList.add('active');
  fetchEvents();
}

// ==============================================================================
// 11. SCHEDULED AUTOMATION
// ==============================================================================

async function fetchAutomationJobs() {
  const container = document.getElementById('automationJobsContainer');
  if (!container) return;

  try {
    const res = await apiFetch('/api/automation/jobs');
    if (!res.ok) return;
    const jobs = await res.json();

    if (jobs.length === 0) {
      container.innerHTML = `<p class="empty-state-muted">No scheduled jobs configured.</p>`;
      return;
    }

    container.innerHTML = jobs.map(j => `
      <div class="glass-card" style="padding:0.85rem;">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem;">
          <div>
            <strong>${escapeHtml(j.name)}</strong>
            <p class="card-subtitle font-mono">Interval: ${j.interval_seconds}s | Status: ${j.enabled ? 'Enabled' : 'Disabled'}</p>
          </div>
          <div style="display:flex; gap:0.4rem;">
            <button class="ghost-btn" onclick="toggleJobState('${j.id}')">${j.enabled ? 'Disable' : 'Enable'}</button>
            <button class="primary-action-btn" style="padding:0.25rem 0.6rem; font-size:0.75rem;" onclick="runJobNow('${j.id}')">Run Now</button>
          </div>
        </div>
      </div>
    `).join('');
  } catch (_) {}
}

async function toggleJobState(jobId) {
  try {
    const res = await apiFetch(`/api/automation/jobs/${jobId}/toggle`, { method: 'POST' });
    if (res.ok) {
      showToast('Job status updated.', 'info');
      fetchAutomationJobs();
    }
  } catch (_) {}
}

async function runJobNow(jobId) {
  try {
    const res = await apiFetch(`/api/automation/jobs/${jobId}/run`, { method: 'POST' });
    if (res.ok) {
      showToast('Scheduled task triggered.', 'success');
      switchTab('tasks');
    }
  } catch (_) {}
}

// ==============================================================================
// 12. ATOMIC BACKUPS
// ==============================================================================

async function fetchBackupsList() {
  const container = document.getElementById('backupsListContainer');
  if (!container) return;

  try {
    const res = await apiFetch('/api/backups');
    if (!res.ok) return;
    const backups = await res.json();

    if (backups.length === 0) {
      container.innerHTML = `<p class="empty-state-muted">No system backups created yet.</p>`;
      return;
    }

    const isAdmin = (authState.role === 'admin');

    container.innerHTML = backups.map(b => `
      <div class="glass-card" style="padding:0.85rem;">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem;">
          <div>
            <strong>${escapeHtml(b.filename)}</strong>
            <p class="card-subtitle font-mono">Size: ${Math.round(b.size_bytes / 1024)} KB | SHA-256: ${b.checksum.slice(0, 16)}...</p>
          </div>
          <div style="display:flex; gap:0.4rem;">
            <a class="ghost-btn" href="/api/backups/download/${b.id}?auth=${encodeURIComponent(authState.token)}" download>Download</a>
            ${isAdmin ? `<button class="ghost-btn danger" onclick="restoreBackup('${b.id}')">Restore</button>` : ''}
          </div>
        </div>
      </div>
    `).join('');
  } catch (_) {}
}

async function triggerQuickBackup() {
  if (!hasPrivilege('can_manage_backups')) {
    showToast('Permission denied: Backups creation forbidden.', 'error');
    return;
  }
  showToast('Generating atomic backup snapshot...', 'info');
  try {
    const res = await apiFetch('/api/backups/create', { method: 'POST' });
    if (res.ok) {
      showToast('Atomic backup created successfully.', 'success');
      fetchBackupsList();
    }
  } catch (err) {
    showToast(`Backup failed: ${err.message}`, 'error');
  }
}

async function restoreBackup(backupId) {
  if (authState.role !== 'admin') {
    showToast('Permission denied: Only system administrators can restore backups.', 'error');
    return;
  }
  if (!confirm(`Restore configuration and RAG index from backup '${backupId}'?`)) return;
  try {
    const res = await apiFetch('/api/backups/restore', {
      method: 'POST',
      body: JSON.stringify({ backup_id: backupId, confirm: true })
    });
    const data = await res.json();
    showToast(data.message || 'Restored successfully', 'success');
  } catch (err) {
    showToast(`Restore failed: ${err.message}`, 'error');
  }
}

// ==============================================================================
// 13. STORAGE INTELLIGENCE
// ==============================================================================

async function fetchStorageIntelligence() {
  try {
    const res = await apiFetch('/api/storage/intelligence');
    if (!res.ok) return;
    const data = await res.json();
    renderStorageIntelligence(data);
  } catch (_) {}
}

function renderStorageIntelligence(data) {
  const { breakdown, large_files } = data;
  if (!breakdown) return;

  const total = (breakdown.videos_bytes + breakdown.music_bytes + breakdown.models_bytes + breakdown.vault_bytes + breakdown.temp_bytes) || 1;

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
          <span class="font-mono" style="color:var(--accent-amber); font-size:0.8rem;">${f.size_mb} MB</span>
        </div>
      `).join('');
    }
  }
}

// ==============================================================================
// 14. ADMIN HUB & RBAC (STRICTLY ISOLATED)
// ==============================================================================

async function fetchAdminUsers() {
  const container = document.getElementById('adminUsersContainer');
  if (!container) return;

  if (authState.role !== 'admin' && !hasPrivilege('can_manage_users')) {
    container.innerHTML = `<p class="empty-state-muted">Permission denied.</p>`;
    return;
  }

  try {
    const res = await apiFetch('/api/admin/users');
    if (!res.ok) return;
    const users = await res.json();
    container.innerHTML = users.map(u => `
      <div class="vault-file-row">
        <div>
          <strong>${escapeHtml(u.user_id)}</strong>
          <span class="role-badge ${u.role}">${u.role.toUpperCase()}</span>
        </div>
        <div style="display:flex; gap:0.4rem;">
          <button class="ghost-btn" onclick="openEditPrivilegesModal('${escapeHtml(u.user_id)}', ${escapeHtml(JSON.stringify(u.privileges || {}))})">Privileges</button>
          ${u.user_id !== 'admin' ? `<button class="ghost-btn danger" onclick="deleteUserAccount('${escapeHtml(u.user_id)}')">Delete</button>` : ''}
        </div>
      </div>
    `).join('');
  } catch (_) {}
}

function renderPrivilegesCheckboxes(containerId, initialPrivs = {}) {
  const container = document.getElementById(containerId);
  if (!container) return;

  container.innerHTML = ALL_PRIVILEGES_LIST.map(p => {
    const isChecked = Boolean(initialPrivs[p]);
    const label = p.replace(/^can_/, '').replace(/_/g, ' ');
    return `
      <label class="priv-checkbox-label">
        <input type="checkbox" name="priv_${p}" value="${p}" ${isChecked ? 'checked' : ''}>
        <span>${label}</span>
      </label>
    `;
  }).join('');
}

function openCreateUserModal() {
  renderPrivilegesCheckboxes('newPrivilegesGrid', USER_DEFAULT_PRIVILEGES);
  openModal('createUserModal');
}

async function handleCreateUserSubmit(e) {
  e.preventDefault();
  const user_id = document.getElementById('newUserId').value.trim();
  const password = document.getElementById('newUserPassword').value.trim();

  const privileges = {};
  document.querySelectorAll('#newPrivilegesGrid input[type="checkbox"]').forEach(cb => {
    privileges[cb.value] = cb.checked;
  });

  try {
    const res = await apiFetch('/api/admin/users', {
      method: 'POST',
      body: JSON.stringify({ user_id, password, privileges })
    });
    if (res.ok) {
      showToast(`User '${user_id}' created successfully.`, 'success');
      closeModal('createUserModal');
      document.getElementById('newUserId').value = '';
      document.getElementById('newUserPassword').value = '';
      fetchAdminUsers();
    }
  } catch (err) {
    showToast(`User creation error: ${err.message}`, 'error');
  }
}

function openEditPrivilegesModal(userId, privs) {
  document.getElementById('editPrivUserId').value = userId;
  document.getElementById('editPrivilegesTitle').textContent = `Privileges: ${userId}`;
  renderPrivilegesCheckboxes('editPrivilegesGrid', privs);
  openModal('editPrivilegesModal');
}

async function handleSavePrivilegesSubmit(e) {
  e.preventDefault();
  const user_id = document.getElementById('editPrivUserId').value;
  const privileges = {};
  document.querySelectorAll('#editPrivilegesGrid input[type="checkbox"]').forEach(cb => {
    privileges[cb.value] = cb.checked;
  });

  try {
    const res = await apiFetch('/api/admin/users/update-privileges', {
      method: 'POST',
      body: JSON.stringify({ user_id, privileges })
    });
    if (res.ok) {
      showToast(`Privileges updated for '${user_id}'.`, 'success');
      closeModal('editPrivilegesModal');
      fetchAdminUsers();
    }
  } catch (err) {
    showToast(`Update error: ${err.message}`, 'error');
  }
}

async function deleteUserAccount(userId) {
  if (!confirm(`Delete user '${userId}'?`)) return;
  try {
    const res = await apiFetch(`/api/admin/users/${encodeURIComponent(userId)}`, { method: 'DELETE' });
    if (res.ok) {
      showToast(`User '${userId}' deleted.`, 'info');
      fetchAdminUsers();
    }
  } catch (err) {
    showToast(`Delete error: ${err.message}`, 'error');
  }
}

// Shares Inspector
async function fetchSharesList() {
  const container = document.getElementById('adminSharesContainer');
  if (!container) return;

  try {
    const res = await apiFetch('/api/shares');
    if (!res.ok) return;
    const shares = await res.json();

    if (shares.length === 0) {
      container.innerHTML = `<p class="empty-state-muted">No temporary share links active.</p>`;
      return;
    }

    container.innerHTML = shares.map(s => `
      <div class="vault-file-row">
        <div>
          <strong>${escapeHtml(s.filename)}</strong>
          <p class="card-subtitle font-mono">Downloads: ${s.downloads_count} / ${s.max_downloads || '∞'} | Token: ${s.token.slice(0, 10)}...</p>
        </div>
        <div>
          ${!s.revoked ? `<button class="ghost-btn danger" onclick="revokeShareLink('${s.id}')">Revoke</button>` : `<span class="badge-pill unavailable">REVOKED</span>`}
        </div>
      </div>
    `).join('');
  } catch (_) {}
}

function openCreateShareModal(filename) {
  document.getElementById('shareFilenameInput').value = filename;
  document.getElementById('shareFilenameDisplay').textContent = `Target: ${filename}`;
  document.getElementById('shareResultBox').style.display = 'none';
  openModal('createShareModal');
}

async function handleCreateShareSubmit(e) {
  e.preventDefault();
  const filename = document.getElementById('shareFilenameInput').value;
  const duration = document.getElementById('shareDurationSelect').value;
  const max_downloads = parseInt(document.getElementById('shareMaxDownloads').value) || 0;

  try {
    const res = await apiFetch('/api/shares', {
      method: 'POST',
      body: JSON.stringify({ filename, duration, max_downloads })
    });
    if (res.ok) {
      const data = await res.json();
      const fullUrl = `${window.location.origin}${data.share_url}`;
      document.getElementById('shareResultUrl').value = fullUrl;
      document.getElementById('shareResultBox').style.display = 'block';
      showToast('Share link generated.', 'success');
      fetchSharesList();
    }
  } catch (err) {
    showToast(`Share error: ${err.message}`, 'error');
  }
}

function copyShareUrl() {
  const urlInput = document.getElementById('shareResultUrl');
  urlInput.select();
  navigator.clipboard.writeText(urlInput.value);
  showToast('Share URL copied to clipboard.', 'success');
}

async function revokeShareLink(shareId) {
  try {
    const res = await apiFetch(`/api/shares/${shareId}`, { method: 'DELETE' });
    if (res.ok) {
      showToast('Share revoked.', 'info');
      fetchSharesList();
    }
  } catch (_) {}
}

// Database Inspector
async function inspectDbTable(tableName) {
  const container = document.getElementById('dbRowsContainer');
  if (!container) return;

  try {
    const res = await apiFetch(`/api/admin/db/query?table=${tableName}&limit=25`);
    if (!res.ok) return;
    const data = await res.json();

    if (data.rows.length === 0) {
      container.innerHTML = `<p class="empty-state-muted">Table '${tableName}' is empty.</p>`;
      return;
    }

    container.innerHTML = `
      <div style="font-size:0.75rem; color:var(--text-dim); margin-bottom:0.4rem;">Showing ${data.count} records</div>
      ${data.rows.map(r => `
        <div style="background:var(--bg-surface-2); padding:0.5rem; border-radius:var(--radius-sm); margin-bottom:0.35rem; font-family:monospace; font-size:0.76rem;">
          ${Object.entries(r).map(([k, v]) => `<div><span style="color:var(--accent-cyan);">${k}:</span> ${escapeHtml(String(v))}</div>`).join('')}
        </div>
      `).join('')}
    `;
  } catch (_) {}
}

// ==============================================================================
// 15. SYSTEM SETTINGS
// ==============================================================================

async function loadSettings() {
  try {
    const res = await apiFetch('/api/settings');
    if (!res.ok) return;
    const s = await res.json();
    const rNorm = document.getElementById('settingRamNorm');
    const rPress = document.getElementById('settingRamPressure');
    if (rNorm) rNorm.value = s.ram_normal_mb;
    if (rPress) rPress.value = s.ram_pressure_mb;
  } catch (_) {}
}

async function handleSettingsSave(e) {
  e.preventDefault();
  if (!hasPrivilege('can_manage_settings')) {
    showToast('Permission denied: Settings modification forbidden.', 'error');
    return;
  }

  const ram_normal_mb = parseInt(document.getElementById('settingRamNorm').value);
  const ram_pressure_mb = parseInt(document.getElementById('settingRamPressure').value);

  try {
    const res = await apiFetch('/api/settings', {
      method: 'POST',
      body: JSON.stringify({ ram_normal_mb, ram_pressure_mb })
    });
    if (res.ok) {
      showToast('Settings saved successfully.', 'success');
      fetchSystemStatus();
    }
  } catch (err) {
    showToast(`Settings save error: ${err.message}`, 'error');
  }
}

// ==============================================================================
// 16. UI HELPERS & MODALS
// ==============================================================================

function openModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add('open');
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove('open');
}

function showToast(message, type = 'info', durationMs = 3500) {
  const container = document.getElementById('toastContainer');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 250);
  }, durationMs);
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
