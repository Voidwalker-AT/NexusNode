/**
 * NexusNode — 24/7 Personal Mobile Server Appliance Controller & SSE Streamer
 * Canonical Design System: stitch_nexusnode_control_interface/nexusnode/DESIGN.md
 * Target Hardware: TECNO BG6, Android 13, Termux, ~4 GB RAM, unrooted
 * Architecture: Centralized authState, Strict Least-Privilege RBAC, Reactive UI, Telemetry Mapping
 */

// ==============================================================================
// 1. GLOBAL STATE & PRIVILEGES REGISTRY
// ==============================================================================

const authState = {
  token: null,
  user: null,
  role: 'user',
  privileges: {},
  isAuthenticated: false,
  isLocked: false,
  lockoutRemaining: 0,
  lockoutTimer: null
};

const appState = {
  activeTab: 'dashboard',
  systemStatusInterval: null,
  cachedFiles: [],
  activeVaultFilter: 'all',
  activeVaultQuery: '',
  mediaLibrary: [],
  activeTaskId: null,
  eventSource: null,
  selectedModel: '',
  loadedModel: '',
  isStreamingChat: false
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

  try {
    const res = await fetch(url, options);
    if (res.status === 401) {
      if (authState.isAuthenticated) {
        showToast('Session expired. Please log in again.', 'warning');
        handleLogout(false);
      }
      return res;
    }
    if (res.status === 403) {
      showToast('Access denied: insufficient operator privileges.', 'error');
    }
    return res;
  } catch (err) {
    console.error(`API Fetch failed for ${url}:`, err);
    throw err;
  }
}

function clearLockoutCountdown() {
  if (authState.lockoutTimer) {
    clearInterval(authState.lockoutTimer);
    authState.lockoutTimer = null;
  }
  authState.isLocked = false;
  authState.lockoutRemaining = 0;

  const lockoutAlert = document.getElementById('lockoutAlert');
  const submitBtn = document.getElementById('loginSubmitBtn');
  const countdown = document.getElementById('lockoutCountdown');

  if (lockoutAlert) lockoutAlert.style.display = 'none';
  if (countdown) countdown.textContent = '0';
  if (submitBtn) {
    submitBtn.disabled = false;
    const btnText = submitBtn.querySelector('span:last-child');
    if (btnText) btnText.textContent = 'AUTHENTICATE';
  }
}

function startLockoutCountdown(seconds) {
  const duration = parseInt(seconds, 10);
  if (isNaN(duration) || duration <= 0) {
    clearLockoutCountdown();
    return;
  }

  // Prevent duplicate intervals
  if (authState.lockoutTimer) {
    clearInterval(authState.lockoutTimer);
    authState.lockoutTimer = null;
  }

  authState.isLocked = true;
  authState.lockoutRemaining = duration;

  const lockoutAlert = document.getElementById('lockoutAlert');
  const countdown = document.getElementById('lockoutCountdown');
  const submitBtn = document.getElementById('loginSubmitBtn');

  if (lockoutAlert) lockoutAlert.style.display = 'flex';
  if (countdown) countdown.textContent = duration;
  if (submitBtn) {
    submitBtn.disabled = true;
    const btnText = submitBtn.querySelector('span:last-child');
    if (btnText) btnText.textContent = `LOCKED (${duration}s)`;
  }

  authState.lockoutTimer = setInterval(() => {
    authState.lockoutRemaining -= 1;

    if (authState.lockoutRemaining > 0) {
      const cdEl = document.getElementById('lockoutCountdown');
      const btnEl = document.getElementById('loginSubmitBtn');
      if (cdEl) cdEl.textContent = authState.lockoutRemaining;
      if (btnEl) {
        const textSpan = btnEl.querySelector('span:last-child');
        if (textSpan) textSpan.textContent = `LOCKED (${authState.lockoutRemaining}s)`;
      }
    } else {
      clearLockoutCountdown();
      showToast('Lockout period ended. Authentication controls restored.', 'info');
    }
  }, 1000);
}

async function checkServerLockoutState(username = null) {
  try {
    const usernameInput = document.getElementById('loginUsername');
    const targetUser = (username || (usernameInput ? usernameInput.value : '') || 'admin').trim().toLowerCase();
    const res = await fetch(`/api/auth/lockout-status?user_id=${encodeURIComponent(targetUser)}`, {
      headers: { 'localtonet-skip-warning': 'true' }
    });
    if (res.ok) {
      const data = await res.json();
      const secs = data.remaining_seconds || data.lockout_seconds || 0;
      if (data.locked && secs > 0) {
        startLockoutCountdown(secs);
      } else {
        if (authState.isLocked) {
          clearLockoutCountdown();
        }
      }
    }
  } catch (err) {
    console.warn('Failed to query server lockout status:', err);
  }
}

async function initAuth() {
  const savedToken = localStorage.getItem('nexus_token');
  if (savedToken) {
    authState.token = savedToken;
    try {
      const res = await apiFetch('/api/auth/me');
      if (res.ok) {
        const data = await res.json();
        setAuthenticatedState(data.user, savedToken);
        return;
      }
    } catch (err) {
      console.warn('Saved token validation failed:', err);
    }
  }
  handleLogout(false);
  // Authoritatively reconstruct lockout state from server upon page load / refresh
  await checkServerLockoutState();
}

function setAuthenticatedState(user, token) {
  clearLockoutCountdown();

  authState.token = token;
  authState.user = user;
  authState.role = user.role || 'user';
  authState.privileges = user.privileges || {};
  authState.isAuthenticated = true;

  localStorage.setItem('nexus_token', token);

  // Update Header UI
  const headerUsername = document.getElementById('headerUsername');
  if (headerUsername) headerUsername.textContent = user.username || user.user_id || 'admin';

  const headerAvatar = document.getElementById('headerUserAvatar');
  if (headerAvatar) headerAvatar.textContent = ((user.username || user.user_id || 'A')[0]).toUpperCase();

  const roleBadge = document.getElementById('headerRoleBadge');
  if (roleBadge) {
    roleBadge.textContent = authState.role.toUpperCase();
    if (authState.role === 'admin') {
      roleBadge.className = 'role-badge admin';
    } else {
      roleBadge.className = 'role-badge';
    }
  }

  // Hide Login Modal
  const loginScreen = document.getElementById('loginScreen');
  if (loginScreen) loginScreen.style.display = 'none';

  applyRbacVisibility();
  startPeriodicPolling();
  connectLogStream();

  // Load initial tab data
  switchTab(appState.activeTab || 'dashboard');
}

async function handleLoginSubmit(event) {
  event.preventDefault();
  const usernameInput = document.getElementById('loginUsername');
  const passwordInput = document.getElementById('loginPassword');
  const submitBtn = document.getElementById('loginSubmitBtn');

  if (authState.isLocked && authState.lockoutRemaining > 0) {
    showToast(`Account is locked. Please wait ${authState.lockoutRemaining}s before attempting login.`, 'warning');
    return;
  }

  if (!usernameInput || !passwordInput) return;

  const username = usernameInput.value.trim();
  const password = passwordInput.value;

  if (!username || !password) {
    showToast('Please enter both operator ID and passphrase.', 'warning');
    return;
  }

  if (submitBtn) submitBtn.disabled = true;

  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'localtonet-skip-warning': 'true'
      },
      body: JSON.stringify({ user_id: username, username, password })
    });

    const data = await res.json();
    if (res.ok && (data.token || data.success)) {
      clearLockoutCountdown();
      setAuthenticatedState(data.user, data.token);
      showToast(`Welcome back, ${data.user.username || data.user.user_id || 'Operator'}`, 'success');
      passwordInput.value = '';
    } else {
      if (res.status === 429 || data.error === 'account_locked' || data.error === 'locked_out' || data.lockout_seconds || data.remaining_seconds) {
        const secs = data.remaining_seconds || data.lockout_seconds || data.retry_after || 60;
        startLockoutCountdown(secs);
        showToast(data.message || `Account Locked. Try again in ${secs}s.`, 'error');
      } else {
        showToast(data.message || data.error || 'Authentication failed.', 'error');
        if (submitBtn && !authState.isLocked) submitBtn.disabled = false;
      }
    }
  } catch (err) {
    showToast('Failed to connect to authentication gateway.', 'error');
    if (submitBtn && !authState.isLocked) submitBtn.disabled = false;
  }
}

async function handleLogout(notifyServer = true) {
  clearLockoutCountdown();

  if (notifyServer && authState.token) {
    try {
      await apiFetch('/api/auth/logout', { method: 'POST' });
    } catch (e) {
      console.warn('Server logout notification error:', e);
    }
  }

  // Clear Session
  authState.token = null;
  authState.user = null;
  authState.role = 'user';
  authState.privileges = {};
  authState.isAuthenticated = false;
  localStorage.removeItem('nexus_token');

  // Stop background polling & SSE
  if (appState.systemStatusInterval) clearInterval(appState.systemStatusInterval);
  if (appState.eventSource) {
    appState.eventSource.close();
    appState.eventSource = null;
  }

  // Clear Admin / Sensitive DOM state
  document.querySelectorAll('.admin-only').forEach(el => el.style.display = 'none');
  const diagFindings = document.getElementById('diagFindingsContainer');
  if (diagFindings) diagFindings.innerHTML = '';
  const adminUsers = document.getElementById('adminUserTableBody');
  if (adminUsers) adminUsers.innerHTML = '';

  // Show Login Screen
  const loginScreen = document.getElementById('loginScreen');
  if (loginScreen) loginScreen.style.display = 'flex';

  // Force active tab to dashboard
  appState.activeTab = 'dashboard';
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  const dashPane = document.getElementById('tab-dashboard');
  if (dashPane) dashPane.classList.add('active');
}

function applyRbacVisibility() {
  const isAdmin = (authState.role === 'admin');

  // Admin-only elements
  document.querySelectorAll('.admin-only').forEach(el => {
    el.style.display = isAdmin ? '' : 'none';
  });

  // Privilege specific elements
  document.querySelectorAll('.perm-backups').forEach(el => {
    el.style.display = (isAdmin || hasPrivilege('can_manage_backups')) ? '' : 'none';
  });
  document.querySelectorAll('.perm-automation').forEach(el => {
    el.style.display = (isAdmin || hasPrivilege('can_manage_automation')) ? '' : 'none';
  });
  document.querySelectorAll('.perm-settings').forEach(el => {
    el.style.display = (isAdmin || hasPrivilege('can_manage_settings')) ? '' : 'none';
  });
}

// ==============================================================================
// 3. NAVIGATION & DRAWER CONTROLS
// ==============================================================================

function switchTab(tabId) {
  // Check Admin / Privilege guard
  if ((tabId === 'admin' || tabId === 'diagnostics') && authState.role !== 'admin') {
    showToast('Administrator privileges required.', 'warning');
    return;
  }

  appState.activeTab = tabId;

  // Update Desktop Tab Buttons
  document.querySelectorAll('.desktop-nav-tabs .nav-tab').forEach(tab => {
    if (tab.getAttribute('data-tab') === tabId) {
      tab.classList.add('active');
    } else {
      tab.classList.remove('active');
    }
  });

  // Update Mobile Tab Buttons
  document.querySelectorAll('.mobile-bottom-nav .mobile-nav-btn').forEach(btn => {
    if (btn.getAttribute('data-tab') === tabId) {
      btn.classList.add('active');
    } else {
      btn.classList.remove('active');
    }
  });

  // Show Active Pane
  document.querySelectorAll('.tab-pane').forEach(pane => {
    if (pane.id === `tab-${tabId}`) {
      pane.classList.add('active');
      pane.style.display = '';
    } else {
      pane.classList.remove('active');
      pane.style.display = 'none';
    }
  });

  // Trigger tab data reload
  switch (tabId) {
    case 'dashboard':
      pollSystemStatus();
      break;
    case 'storage':
      loadVaultFiles();
      break;
    case 'media':
      loadMediaLibrary();
      pollMediaQueue();
      break;
    case 'tasks':
      loadTasksList();
      break;
    case 'ai-studio':
      loadAiState();
      break;
    case 'diagnostics':
      loadDiagnosticsReport();
      break;
    case 'settings':
      loadSettings();
      break;
    case 'automation':
      loadAutomationJobs();
      break;
    case 'backups':
      loadBackupsList();
      break;
    case 'storage-intel':
      loadStorageIntel();
      break;
    case 'events':
      loadEventsArchive();
      break;
    case 'admin':
      loadAdminUsers();
      break;
  }
}

function toggleDesktopMoreMenu(event) {
  if (event) event.stopPropagation();
  const menu = document.getElementById('desktopMoreMenu');
  if (menu) menu.classList.toggle('show');
}

function closeAllMoreMenus() {
  const menu = document.getElementById('desktopMoreMenu');
  if (menu) menu.classList.remove('show');
}

document.addEventListener('click', (e) => {
  const wrapper = document.querySelector('.desktop-more-wrapper');
  if (wrapper && !wrapper.contains(e.target)) {
    closeAllMoreMenus();
  }
});

function openMobileMoreDrawer() {
  const drawer = document.getElementById('moreDrawer');
  const overlay = document.getElementById('moreDrawerOverlay');
  if (drawer) drawer.classList.remove('closed');
  if (overlay) overlay.classList.remove('closed');
}

function closeMobileMoreDrawer() {
  const drawer = document.getElementById('moreDrawer');
  const overlay = document.getElementById('moreDrawerOverlay');
  if (drawer) drawer.classList.add('closed');
  if (overlay) overlay.classList.add('closed');
}

// ==============================================================================
// 4. TELEMETRY, SYSTEM STATUS & SSE STREAM
// ==============================================================================

function startPeriodicPolling() {
  if (appState.systemStatusInterval) clearInterval(appState.systemStatusInterval);
  pollSystemStatus();
  appState.systemStatusInterval = setInterval(pollSystemStatus, 3000);
}

async function pollSystemStatus() {
  if (!authState.isAuthenticated) return;
  try {
    const res = await apiFetch('/api/system/status');
    if (res.ok) {
      const data = await res.json();
      updateTelemetryUI(data);
    }
  } catch (e) {
    console.warn('System status poll error:', e);
  }
}

function updateTelemetryUI(data) {
  if (!data) return;

  // 1. Top Status Strip
  const stripUptime = document.getElementById('stripUptime');
  if (stripUptime && data.system && data.system.uptime) {
    stripUptime.textContent = data.system.uptime;
  }

  const stripBattery = document.getElementById('stripBattery');
  if (stripBattery && data.battery) {
    stripBattery.textContent = `${data.battery.level ?? '--'}%`;
  }

  const stripConnStatus = document.getElementById('stripConnStatus');
  const stripStatusDot = document.getElementById('stripStatusDot');
  if (stripConnStatus && data.network) {
    const isWan = data.network.mode === 'wan';
    stripConnStatus.textContent = isWan ? 'ONLINE (WAN)' : 'ONLINE (LAN)';
    if (stripStatusDot) stripStatusDot.className = 'status-dot';
  }

  // 2. RAM Meter (PSS + Ollama)
  const ram = data.memory || {};
  const ramPercent = ram.percent || 0;
  const ramMeterFill = document.getElementById('ramMeterFill');
  const ramMeterVal = document.getElementById('ramMeterVal');
  const ramDetail = document.getElementById('ramDetailText');
  if (ramMeterFill) {
    ramMeterFill.style.width = `${Math.min(ramPercent, 100)}%`;
    if (ramPercent >= 90) ramMeterFill.className = 'meter-fill critical';
    else if (ramPercent >= 80) ramMeterFill.className = 'meter-fill warning';
    else ramMeterFill.className = 'meter-fill';
  }
  if (ramMeterVal) ramMeterVal.textContent = `${ramPercent}%`;
  if (ramDetail && ram.used_mb && ram.total_mb) {
    ramDetail.textContent = `${ram.used_mb} / ${ram.total_mb} MB`;
  }

  // 3. Swap / ZRAM Meter
  const swap = data.swap || {};
  const swapPercent = swap.percent || 0;
  const swapMeterFill = document.getElementById('swapMeterFill');
  const swapMeterVal = document.getElementById('swapMeterVal');
  const swapDetail = document.getElementById('swapDetailText');
  if (swapMeterFill) {
    swapMeterFill.style.width = `${Math.min(swapPercent, 100)}%`;
  }
  if (swapMeterVal) swapMeterVal.textContent = `${swapPercent}%`;
  if (swapDetail && swap.used_mb !== undefined) {
    swapDetail.textContent = `${swap.used_mb} / ${swap.total_mb || 0} MB`;
  }

  // 4. Storage Meter
  const stg = data.storage || {};
  const stgPercent = stg.percent || 0;
  const stgMeterFill = document.getElementById('storageMeterFill');
  const stgMeterVal = document.getElementById('storageMeterVal');
  const stgDetail = document.getElementById('storageDetailText');
  if (stgMeterFill) stgMeterFill.style.width = `${Math.min(stgPercent, 100)}%`;
  if (stgMeterVal) stgMeterVal.textContent = `${stgPercent}%`;
  if (stgDetail && stg.used_gb) {
    stgDetail.textContent = `${stg.used_gb} / ${stg.total_gb} GB`;
  }

  // 5. CPU Meter
  const cpu = data.cpu || {};
  const cpuPercent = cpu.percent || 0;
  const cpuMeterFill = document.getElementById('cpuMeterFill');
  const cpuMeterVal = document.getElementById('cpuMeterVal');
  if (cpuMeterFill) cpuMeterFill.style.width = `${Math.min(cpuPercent, 100)}%`;
  if (cpuMeterVal) cpuMeterVal.textContent = `${cpuPercent}%`;

  // 6. Battery & Thermal Chip
  const dashBatteryLevel = document.getElementById('dashBatteryLevel');
  const dashBatteryStatus = document.getElementById('dashBatteryStatus');
  if (dashBatteryLevel && data.battery) {
    dashBatteryLevel.textContent = `${data.battery.level ?? '--'}%`;
    if (dashBatteryStatus) dashBatteryStatus.textContent = data.battery.status || 'STANDBY';
  }

  const dashThermalLevel = document.getElementById('dashThermalLevel');
  const dashThermalStatus = document.getElementById('dashThermalStatus');
  if (dashThermalLevel && data.thermal) {
    dashThermalLevel.textContent = `${data.thermal.temp_c ?? '--'}°C`;
    if (dashThermalStatus) dashThermalStatus.textContent = (data.thermal.status || 'NORMAL').toUpperCase();
  }

  // 7. Active Task Supervision
  if (data.active_task) {
    const task = data.active_task;
    appState.activeTaskId = task.id;
    const taskTitle = document.getElementById('activeTaskTitle');
    const taskStatus = document.getElementById('activeTaskStatus');
    const taskFill = document.getElementById('activeTaskMeterFill');
    const taskStep = document.getElementById('activeTaskStepText');
    const taskPct = document.getElementById('activeTaskPercent');
    const cancelBtn = document.getElementById('activeTaskCancelBtn');
    const idText = document.getElementById('activeTaskIdText');

    if (taskTitle) taskTitle.textContent = task.title || task.type;
    if (taskStatus) taskStatus.textContent = (task.status || 'RUNNING').toUpperCase();
    if (taskFill) taskFill.style.width = `${Math.min(task.progress || 0, 100)}%`;
    if (taskStep) taskStep.textContent = task.step_label || 'Executing...';
    if (taskPct) taskPct.textContent = `${task.progress || 0}%`;
    if (cancelBtn) cancelBtn.style.display = 'block';
    if (idText) idText.textContent = `TASK: #${task.id}`;
  } else {
    appState.activeTaskId = null;
    const taskTitle = document.getElementById('activeTaskTitle');
    const taskStatus = document.getElementById('activeTaskStatus');
    const taskFill = document.getElementById('activeTaskMeterFill');
    const taskStep = document.getElementById('activeTaskStepText');
    const taskPct = document.getElementById('activeTaskPercent');
    const cancelBtn = document.getElementById('activeTaskCancelBtn');
    const idText = document.getElementById('activeTaskIdText');

    if (taskTitle) taskTitle.textContent = 'No Active Operations';
    if (taskStatus) taskStatus.textContent = 'IDLE';
    if (taskFill) taskFill.style.width = '0%';
    if (taskStep) taskStep.textContent = 'System standby';
    if (taskPct) taskPct.textContent = '0%';
    if (cancelBtn) cancelBtn.style.display = 'none';
    if (idText) idText.textContent = 'TASK: NONE';
  }

  // 8. Core Services
  if (data.services) {
    updateServicesUI(data.services);
  }
}

function updateServicesUI(services) {
  // NexusNode
  const nexus = services.nexusnode || {};
  const svcBadgeNexus = document.getElementById('svcBadgeNexus');
  const svcDotNexus = document.getElementById('svcDotNexus');
  const svcDetailNexus = document.getElementById('svcDetailNexus');
  if (svcBadgeNexus) svcBadgeNexus.textContent = nexus.running ? 'RUNNING' : 'STOPPED';
  if (svcDotNexus) svcDotNexus.className = nexus.running ? 'service-dot online' : 'service-dot offline';
  if (svcDetailNexus) svcDetailNexus.textContent = `PID ${nexus.pid || '--'} • Port 5000`;

  // SSHD
  const ssh = services.sshd || {};
  const svcBadgeSsh = document.getElementById('svcBadgeSsh');
  const svcDotSsh = document.getElementById('svcDotSsh');
  const svcDetailSsh = document.getElementById('svcDetailSsh');
  if (svcBadgeSsh) svcBadgeSsh.textContent = ssh.running ? 'RUNNING' : 'STOPPED';
  if (svcDotSsh) svcDotSsh.className = ssh.running ? 'service-dot online' : 'service-dot offline';
  if (svcDetailSsh) svcDetailSsh.textContent = `PID ${ssh.pid || '--'} • Port 8022`;

  // LocalToNet
  const l2n = services.localtonet || {};
  const svcBadgeL2n = document.getElementById('svcBadgeL2n');
  const svcDotL2n = document.getElementById('svcDotL2n');
  const svcDetailL2n = document.getElementById('svcDetailL2n');
  if (svcBadgeL2n) svcBadgeL2n.textContent = l2n.connected ? 'CONNECTED' : (l2n.running ? 'CONNECTING' : 'OFFLINE');
  if (svcDotL2n) svcDotL2n.className = l2n.connected ? 'service-dot online' : (l2n.running ? 'service-dot warning' : 'service-dot offline');
  if (svcDetailL2n && l2n.url) svcDetailL2n.textContent = l2n.url;

  // Ollama
  const ollama = services.ollama || {};
  const svcBadgeOllama = document.getElementById('svcBadgeOllama');
  const svcDotOllama = document.getElementById('svcDotOllama');
  const svcDetailOllama = document.getElementById('svcDetailOllama');
  if (svcBadgeOllama) svcBadgeOllama.textContent = ollama.running ? 'RUNNING' : 'STANDBY';
  if (svcDotOllama) svcDotOllama.className = ollama.running ? 'service-dot online' : 'service-dot warning';
  if (svcDetailOllama) svcDetailOllama.textContent = `PID ${ollama.pid || '--'} • Port 11434`;
}

function connectLogStream() {
  if (appState.eventSource) appState.eventSource.close();
  const token = authState.token;
  const url = token ? `/api/logs/stream?token=${encodeURIComponent(token)}` : '/api/logs/stream';

  appState.eventSource = new EventSource(url);
  appState.eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      appendEventLog(data);
    } catch (e) {}
  };
  appState.eventSource.onerror = () => {
    // Reconnect silently handled by browser
  };
}

function appendEventLog(log) {
  const container = document.getElementById('eventLogFeed');
  if (!container) return;

  const entry = document.createElement('div');
  entry.className = 'log-entry';

  const time = log.timestamp ? log.timestamp.split('T')[1]?.substring(0, 8) : '--:--:--';
  const level = log.level || 'INFO';

  entry.innerHTML = `
    <span class="log-time">[${time}]</span>
    <span class="log-level ${level}">${level}</span>
    <span class="log-msg">${escapeHtml(log.message || log.event || '')}</span>
  `;

  container.prepend(entry);
  if (container.children.length > 50) {
    container.removeChild(container.lastChild);
  }
}

function clearEventFeed() {
  const container = document.getElementById('eventLogFeed');
  if (container) {
    container.innerHTML = '<div class="log-entry"><span class="log-time">[SYSTEM]</span><span class="log-level INFO">INFO</span><span class="log-msg">Feed cleared.</span></div>';
  }
}

// ==============================================================================
// 5. VAULT FILE MANAGER
// ==============================================================================

async function loadVaultFiles(folderPath = '') {
  try {
    appState.currentVaultPath = folderPath || '';
    const url = folderPath ? `/files?path=${encodeURIComponent(folderPath)}` : '/files';
    const res = await apiFetch(url);
    if (res.ok) {
      const data = await res.json();
      appState.cachedFiles = data.files || [];
      renderVaultTable(appState.cachedFiles);
    }
  } catch (e) {
    console.error('Failed to load vault files:', e);
  }
}

function renderVaultTable(files) {
  const tbody = document.getElementById('vaultTableBody');
  const countLabel = document.getElementById('vaultFileCount');
  if (!tbody) return;

  let filtered = files;
  if (appState.activeVaultFilter !== 'all') {
    filtered = filtered.filter(f => (f.category || '').toLowerCase() === appState.activeVaultFilter);
  }
  if (appState.activeVaultQuery) {
    const q = appState.activeVaultQuery.toLowerCase();
    filtered = filtered.filter(f => (f.name || '').toLowerCase().includes(q));
  }

  if (countLabel) countLabel.textContent = `${filtered.length} OBJECTS`;

  let rowsHtml = '';

  // If in a subfolder, add a back row
  if (appState.currentVaultPath) {
    const parentPath = appState.currentVaultPath.includes('/') ? appState.currentVaultPath.substring(0, appState.currentVaultPath.lastIndexOf('/')) : '';
    rowsHtml += `
      <tr style="cursor: pointer; background: rgba(0, 218, 243, 0.04);" onclick="loadVaultFiles('${encodeURIComponent(parentPath)}')">
        <td colspan="5" style="color: var(--primary); font-weight: 600;">
          <div style="display: flex; align-items: center; gap: 8px;">
            <span class="material-symbols-outlined">arrow_back</span>
            <span>.. (Up to ${parentPath || 'Root Vault'})</span>
          </div>
        </td>
      </tr>
    `;
  }

  if (filtered.length === 0 && !appState.currentVaultPath) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--on-surface-muted); padding: 24px;">No objects found in this location.</td></tr>';
    return;
  }

  rowsHtml += filtered.map(file => {
    const isDir = Boolean(file.is_dir);
    const ext = isDir ? 'FOLDER' : (file.name.split('.').pop() || 'FILE').toUpperCase();
    const size = isDir ? '--' : formatBytes(file.size || 0);
    const date = file.modified ? file.modified.substring(0, 16).replace('T', ' ') : '--';
    const isMedia = !isDir && ['MP3', 'MP4', 'MKV', 'WEBM', 'M4A', 'FLAC', 'WAV'].includes(ext);

    return `
      <tr>
        <td style="font-weight: 500; color: var(--on-surface-bright);">
          <div style="display: flex; align-items: center; gap: 8px;">
            <span class="material-symbols-outlined" style="color: ${isDir ? 'var(--primary)' : 'var(--on-surface-muted)'};">${isDir ? 'folder' : 'draft'}</span>
            ${isDir ? `<a href="#" onclick="loadVaultFiles('${encodeURIComponent(file.path || file.name)}'); return false;" style="color: var(--primary); text-decoration: underline;">${escapeHtml(file.name)}</a>` : `<span>${escapeHtml(file.name)}</span>`}
          </div>
        </td>
        <td><span class="node-badge" style="${isDir ? 'color: var(--primary); border-color: rgba(0, 218, 243, 0.4);' : ''}">${ext}</span></td>
        <td class="font-data-sm">${size}</td>
        <td class="font-data-sm" style="color: var(--on-surface-variant);">${date}</td>
        <td style="text-align: right;">
          <div style="display: inline-flex; gap: 4px;">
            ${isMedia ? `<button class="icon-btn" title="Stream" onclick="playMediaFile('${encodeURIComponent(file.path || file.name)}', '${ext.toLowerCase()}', '${escapeHtml(file.name)}')"><span class="material-symbols-outlined" style="font-size: 16px;">play_arrow</span></button>` : ''}
            <a class="icon-btn" title="${isDir ? 'Download Zip' : 'Download'}" href="/download/${encodeURIComponent(file.path || file.name)}" download><span class="material-symbols-outlined" style="font-size: 16px;">${isDir ? 'folder_zip' : 'download'}</span></a>
            <button class="icon-btn" title="Delete" onclick="handleVaultDelete('${encodeURIComponent(file.path || file.name)}')"><span class="material-symbols-outlined" style="font-size: 16px;">delete</span></button>
          </div>
        </td>
      </tr>
    `;
  }).join('');

  tbody.innerHTML = rowsHtml;
}

function filterVaultLocation(location, elem) {
  appState.activeVaultFilter = location;
  document.querySelectorAll('.vault-nav-item').forEach(el => el.classList.remove('active'));
  if (elem) elem.classList.add('active');
  if (location === 'all') {
    loadVaultFiles('');
  } else if (['documents', 'media', 'downloads', 'backups', 'rag'].includes(location)) {
    loadVaultFiles(location);
  } else {
    renderVaultTable(appState.cachedFiles);
  }
}

function handleVaultSearch(query) {
  appState.activeVaultQuery = query;
  renderVaultTable(appState.cachedFiles);
}

async function handleVaultUpload(event) {
  const file = event.target.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append('file', file);

  try {
    showToast(`Uploading ${file.name}...`, 'info');
    const res = await apiFetch('/upload', {
      method: 'POST',
      body: formData
    });
    if (res.ok) {
      showToast('File uploaded successfully.', 'success');
      loadVaultFiles();
    } else {
      const err = await res.json();
      showToast(err.error || 'Upload failed.', 'error');
    }
  } catch (e) {
    showToast('Failed to upload file.', 'error');
  } finally {
    event.target.value = '';
  }
}

async function handleVaultDelete(filename) {
  if (!confirm(`Are you sure you want to delete ${decodeURIComponent(filename)}?`)) return;

  try {
    const res = await apiFetch('/delete', {
      method: 'POST',
      body: JSON.stringify({ filename: decodeURIComponent(filename) })
    });
    if (res.ok) {
      showToast('Object deleted.', 'success');
      loadVaultFiles();
    } else {
      const err = await res.json();
      showToast(err.error || 'Delete failed.', 'error');
    }
  } catch (e) {
    showToast('Failed to delete object.', 'error');
  }
}

async function handleCleanTempFiles() {
  try {
    showToast('Cleaning temporary files...', 'info');
    const res = await apiFetch('/api/vault/cleanup-temp', { method: 'POST' });
    if (res.ok) {
      showToast('Temporary storage cleaned.', 'success');
      loadVaultFiles();
    }
  } catch (e) {
    showToast('Cleanup failed.', 'error');
  }
}

// ==============================================================================
// 6. MEDIA CENTER (ACQUISITION ENGINE & LIBRARY)
// ==============================================================================

async function handleMediaDownloadSubmit(event) {
  event.preventDefault();
  const urlInput = document.getElementById('mediaUrlInput');
  const formatSelect = document.getElementById('mediaFormatSelect');
  const qualitySelect = document.getElementById('mediaQualitySelect');
  const destSelect = document.getElementById('mediaDestSelect');
  const embedMeta = document.getElementById('mediaEmbedMeta');
  const subs = document.getElementById('mediaSubs');

  if (!urlInput || !urlInput.value.trim()) return;

  const payload = {
    url: urlInput.value.trim(),
    format: formatSelect ? formatSelect.value : 'mp4',
    quality: qualitySelect ? qualitySelect.value : 'best',
    destination: destSelect ? destSelect.value : 'media/videos',
    embed_metadata: embedMeta ? embedMeta.checked : true,
    subtitles: subs ? subs.checked : false
  };

  try {
    showToast('Queuing download task...', 'info');
    const res = await apiFetch('/api/media/download', {
      method: 'POST',
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (res.ok && data.success) {
      showToast('Download queued successfully.', 'success');
      urlInput.value = '';
      pollMediaQueue();
      pollSystemStatus();
    } else {
      showToast(data.error || 'Failed to queue download.', 'error');
    }
  } catch (e) {
    showToast('Network error queuing download.', 'error');
  }
}

async function pollMediaQueue() {
  try {
    const res = await apiFetch('/api/tasks?type=media_download');
    if (res.ok) {
      const tasks = await res.json();
      renderMediaQueue(tasks.tasks || []);
    }
  } catch (e) {}
}

function renderMediaQueue(tasks) {
  const container = document.getElementById('mediaQueueContainer');
  const countLabel = document.getElementById('mediaQueueCount');
  if (!container) return;

  const active = tasks.filter(t => t.status === 'RUNNING' || t.status === 'QUEUED');
  if (countLabel) countLabel.textContent = `${active.length} ACTIVE`;

  if (active.length === 0) {
    container.innerHTML = '<div class="font-data-sm" style="color: var(--on-surface-muted); text-align: center; padding: 16px;">Queue is currently empty.</div>';
    return;
  }

  container.innerHTML = active.map(t => `
    <div style="background-color: var(--surface-2); border: 1px solid var(--border-subtle); border-radius: var(--radius-xs); padding: 10px 12px; display: flex; justify-content: space-between; align-items: center;">
      <div style="display: flex; flex-direction: column; gap: 4px;">
        <span class="font-headline-md" style="font-size: 13px; color: var(--on-surface-bright);">${escapeHtml(t.title || 'YT-DLP Operation')}</span>
        <span class="font-data-sm" style="color: var(--on-surface-variant);">${t.status} • ${t.progress || 0}%</span>
      </div>
      <button class="btn btn-danger" style="padding: 2px 8px; font-size: 10px; min-height: 24px;" onclick="cancelTask(${t.id})">Cancel</button>
    </div>
  `).join('');
}

async function loadMediaLibrary() {
  try {
    const res = await apiFetch('/api/media/library');
    if (res.ok) {
      const data = await res.json();
      appState.mediaLibrary = data.items || [];
      renderMediaLibrary(appState.mediaLibrary);
    }
  } catch (e) {
    console.error('Failed to load media library:', e);
  }
}

function renderMediaLibrary(items) {
  const grid = document.getElementById('mediaLibraryGrid');
  if (!grid) return;

  if (items.length === 0) {
    grid.innerHTML = '<div class="font-data-sm" style="color: var(--on-surface-muted); padding: 16px;">No media files found in Vault.</div>';
    return;
  }

  grid.innerHTML = items.map(m => {
    const isVideo = (m.type === 'video');
    return `
      <div class="media-card">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span class="material-symbols-outlined" style="color: var(--primary);">${isVideo ? 'movie' : 'music_note'}</span>
          <span class="font-headline-md" style="font-size: 13px; color: var(--on-surface-bright); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(m.name)}</span>
        </div>
        <span class="font-data-sm" style="color: var(--on-surface-variant);">${formatBytes(m.size || 0)}</span>
        <div style="display: flex; gap: 6px; margin-top: 4px;">
          <button class="btn btn-primary" style="flex: 1; padding: 4px 8px; font-size: 11px; min-height: 28px;" onclick="playMediaFile('${encodeURIComponent(m.path)}', '${m.type}', '${escapeHtml(m.name)}')">
            <span class="material-symbols-outlined" style="font-size: 14px;">play_arrow</span>
            <span>Play</span>
          </button>
        </div>
      </div>
    `;
  }).join('');
}

function playMediaFile(encodedPath, type, title) {
  const path = decodeURIComponent(encodedPath);
  const streamUrl = `/stream/${encodeURIComponent(path)}`;
  const playerBox = document.getElementById('mediaPlayerBox');
  const nowPlayingTitle = document.getElementById('nowPlayingTitle');
  const audio = document.getElementById('globalAudioPlayer');
  const video = document.getElementById('globalVideoPlayer');

  if (!playerBox) return;
  playerBox.style.display = 'block';
  if (nowPlayingTitle) nowPlayingTitle.textContent = `Streaming: ${title}`;

  if (type === 'video' || path.endsWith('.mp4') || path.endsWith('.mkv') || path.endsWith('.webm')) {
    if (audio) { audio.pause(); audio.style.display = 'none'; }
    if (video) {
      video.src = streamUrl;
      video.style.display = 'block';
      video.play();
    }
  } else {
    if (video) { video.pause(); video.style.display = 'none'; }
    if (audio) {
      audio.src = streamUrl;
      audio.style.display = 'block';
      audio.play();
    }
  }
}

function closeMediaPlayer() {
  const playerBox = document.getElementById('mediaPlayerBox');
  const audio = document.getElementById('globalAudioPlayer');
  const video = document.getElementById('globalVideoPlayer');
  if (audio) { audio.pause(); audio.src = ''; }
  if (video) { video.pause(); video.src = ''; }
  if (playerBox) playerBox.style.display = 'none';
}

// ==============================================================================
// 7. TASK SUPERVISION
// ==============================================================================

async function loadTasksList() {
  try {
    const res = await apiFetch('/api/tasks');
    if (res.ok) {
      const data = await res.json();
      renderTasksTable(data.tasks || []);
    }
  } catch (e) {
    console.error('Failed to load tasks:', e);
  }
}

function renderTasksTable(tasks) {
  const tbody = document.getElementById('tasksTableBody');
  if (!tbody) return;

  if (tasks.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--on-surface-muted); padding: 24px;">No background tasks found.</td></tr>';
    return;
  }

  tbody.innerHTML = tasks.map(t => {
    const canCancel = (t.status === 'RUNNING' || t.status === 'QUEUED');
    const created = t.created_at ? t.created_at.substring(0, 16).replace('T', ' ') : '--';
    let statusClass = 'var(--on-surface-variant)';
    if (t.status === 'RUNNING') statusClass = 'var(--primary)';
    if (t.status === 'COMPLETED') statusClass = 'var(--status-healthy)';
    if (t.status === 'FAILED') statusClass = 'var(--status-critical)';

    return `
      <tr>
        <td><span class="font-label-caps" style="color: ${statusClass};">${t.status}</span></td>
        <td><span class="node-badge">${escapeHtml(t.type || 'TASK')}</span></td>
        <td style="color: var(--on-surface-bright); font-weight: 500;">${escapeHtml(t.title || 'Task #' + t.id)}</td>
        <td class="font-data-sm">${t.progress || 0}%</td>
        <td class="font-data-sm">${escapeHtml(t.owner || 'system')}</td>
        <td class="font-data-sm" style="color: var(--on-surface-variant);">${created}</td>
        <td style="text-align: right;">
          ${canCancel ? `<button class="btn btn-danger" style="padding: 2px 8px; font-size: 10px; min-height: 24px;" onclick="cancelTask(${t.id})">Abort</button>` : '<span style="color: var(--on-surface-dim); font-size: 11px;">--</span>'}
        </td>
      </tr>
    `;
  }).join('');
}

async function cancelCurrentActiveTask() {
  if (appState.activeTaskId) {
    cancelTask(appState.activeTaskId);
  }
}

async function cancelTask(taskId) {
  try {
    const res = await apiFetch(`/api/tasks/${taskId}/cancel`, { method: 'POST' });
    if (res.ok) {
      showToast(`Task #${taskId} cancelled.`, 'warning');
      loadTasksList();
      pollSystemStatus();
    }
  } catch (e) {
    showToast('Failed to cancel task.', 'error');
  }
}

// ==============================================================================
// 8. AI STUDIO (MODEL SELECTION, RESIDENCY & CHAT)
// ==============================================================================

async function loadAiState() {
  try {
    // 1. Get Models List
    const modelsRes = await apiFetch('/api/ai/models');
    if (modelsRes.ok) {
      const modelsData = await modelsRes.json();
      const select = document.getElementById('aiModelSelect');
      if (select && modelsData.models) {
        select.innerHTML = modelsData.models.map(m => `
          <option value="${m.name}" ${m.name === modelsData.selected_model ? 'selected' : ''}>${m.name} (${formatBytes(m.size || 0)})</option>
        `).join('');
        appState.selectedModel = modelsData.selected_model || (modelsData.models[0] ? modelsData.models[0].name : '');
      }
    }

    // 2. Get Runtime Residency State
    const stateRes = await apiFetch('/api/ai/state');
    if (stateRes.ok) {
      const stateData = await stateRes.json();
      const loadedName = document.getElementById('aiLoadedModelName');
      const loadedMem = document.getElementById('aiLoadedModelMemory');
      const unloadBtn = document.getElementById('aiUnloadModelBtn');

      if (stateData.loaded_model) {
        appState.loadedModel = stateData.loaded_model;
        if (loadedName) loadedName.textContent = stateData.loaded_model;
        if (loadedMem) loadedMem.textContent = `Resident RAM: ${stateData.memory_mb || 0} MB`;
        if (unloadBtn) unloadBtn.style.display = 'block';
      } else {
        appState.loadedModel = '';
        if (loadedName) loadedName.textContent = 'None (Unloaded)';
        if (loadedMem) loadedMem.textContent = 'Resident RAM: 0 MB';
        if (unloadBtn) unloadBtn.style.display = 'none';
      }
    }
  } catch (e) {
    console.error('Failed to load AI state:', e);
  }
}

async function handleSelectAiModel() {
  const select = document.getElementById('aiModelSelect');
  if (!select || !select.value) return;

  try {
    showToast(`Setting ${select.value} as active inference model...`, 'info');
    const res = await apiFetch('/api/ai/models/select', {
      method: 'POST',
      body: JSON.stringify({ model: select.value })
    });
    if (res.ok) {
      showToast('Model selected successfully.', 'success');
      loadAiState();
    }
  } catch (e) {
    showToast('Failed to select model.', 'error');
  }
}

async function handleUnloadAiModel() {
  try {
    showToast('Unloading resident model...', 'info');
    const res = await apiFetch('/api/ai/models/unload', { method: 'POST' });
    if (res.ok) {
      showToast('Model unloaded from memory.', 'success');
      loadAiState();
    }
  } catch (e) {
    showToast('Failed to unload model.', 'error');
  }
}

async function handleSendAiChat(event) {
  event.preventDefault();
  const input = document.getElementById('aiChatInput');
  const chatBox = document.getElementById('aiChatBox');
  const sysPrompt = document.getElementById('aiSystemPrompt');
  const ragEnabled = document.getElementById('aiRagEnabled');
  const keepAlive = document.getElementById('aiKeepAliveSelect');

  if (!input || !input.value.trim() || appState.isStreamingChat) return;

  const userMessage = input.value.trim();
  input.value = '';

  // Append User Bubble
  const userBubble = document.createElement('div');
  userBubble.className = 'chat-bubble user';
  userBubble.textContent = userMessage;
  chatBox.appendChild(userBubble);

  // Append Assistant Bubble Placeholder
  const assistantBubble = document.createElement('div');
  assistantBubble.className = 'chat-bubble assistant';
  assistantBubble.innerHTML = '<em>Inferring response on TECNO BG6...</em>';
  chatBox.appendChild(assistantBubble);
  chatBox.scrollTop = chatBox.scrollHeight;

  appState.isStreamingChat = true;

  try {
    const res = await fetch('/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'localtonet-skip-warning': 'true',
        'Authorization': `Bearer ${authState.token || ''}`
      },
      body: JSON.stringify({
        message: userMessage,
        model: appState.selectedModel,
        system_prompt: sysPrompt ? sysPrompt.value : '',
        use_rag: ragEnabled ? ragEnabled.checked : true,
        keep_alive: keepAlive ? keepAlive.value : '5m'
      })
    });

    if (!res.ok) {
      assistantBubble.textContent = 'Neural inference failed. Check Ollama service.';
      appState.isStreamingChat = false;
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let accumulated = '';
    assistantBubble.textContent = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value, { stream: true });
      accumulated += chunk;
      assistantBubble.textContent = accumulated;
      chatBox.scrollTop = chatBox.scrollHeight;
    }
  } catch (e) {
    assistantBubble.textContent = 'Connection error during token streaming.';
  } finally {
    appState.isStreamingChat = false;
    loadAiState();
  }
}

// ==============================================================================
// 9. ADMIN DIAGNOSTICS & SYSTEM AUDIT
// ==============================================================================

async function loadDiagnosticsReport() {
  if (authState.role !== 'admin') return;

  try {
    const res = await apiFetch('/api/admin/diagnostics/full-report');
    if (res.ok) {
      const data = await res.json();
      renderDiagnosticFindings(data.findings || []);
      renderDiagnosticsProcesses(data.processes || []);
      if (data.rag) {
        const docCount = document.getElementById('ragDocCount');
        const idxSize = document.getElementById('ragIndexSize');
        const walSize = document.getElementById('ragWalSize');
        if (docCount) docCount.textContent = data.rag.doc_count || 0;
        if (idxSize) idxSize.textContent = `${Math.round((data.rag.index_bytes || 0) / 1024)} KB`;
        if (walSize) walSize.textContent = `${Math.round((data.rag.wal_bytes || 0) / 1024)} KB`;
      }
    }
  } catch (e) {
    console.error('Failed to load diagnostics report:', e);
  }
}

function renderDiagnosticFindings(findings) {
  const container = document.getElementById('diagFindingsContainer');
  const countLabel = document.getElementById('diagFindingsCount');
  if (!container) return;

  if (countLabel) countLabel.textContent = `${findings.length} FINDINGS`;

  if (findings.length === 0) {
    container.innerHTML = '<div class="font-data-sm" style="color: var(--status-healthy); padding: 16px;">All subsystems operating within optimal thermal and memory budgets.</div>';
    return;
  }

  container.innerHTML = findings.map(f => `
    <div class="finding-card ${f.severity || 'WARNING'}">
      <div class="finding-header">
        <span class="finding-problem">${escapeHtml(f.problem || 'Anomalous Metric')}</span>
        <span class="node-badge" style="color: ${f.severity === 'CRITICAL' ? 'var(--status-critical)' : 'var(--status-warning)'};">${f.severity || 'WARN'}</span>
      </div>
      <div class="finding-grid">
        <div class="finding-cell">
          <span>EVIDENCE</span>
          <div>${escapeHtml(f.evidence || '--')}</div>
        </div>
        <div class="finding-cell">
          <span>LIKELY CAUSE</span>
          <div>${escapeHtml(f.cause || '--')}</div>
        </div>
      </div>
      <div class="finding-cell" style="margin-top: 4px;">
        <span>RECOMMENDED ACTION</span>
        <div style="color: var(--primary);">${escapeHtml(f.recommendation || '--')}</div>
      </div>
    </div>
  `).join('');
}

function renderDiagnosticsProcesses(procs) {
  const tbody = document.getElementById('diagProcessTableBody');
  if (!tbody) return;

  if (procs.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--on-surface-muted); padding: 16px;">No process telemetry available.</td></tr>';
    return;
  }

  tbody.innerHTML = procs.map(p => `
    <tr>
      <td style="color: var(--on-surface-bright); font-weight: 500;">${escapeHtml(p.name)}</td>
      <td class="font-data-sm">${p.pid || '--'}</td>
      <td class="font-data-sm">${p.rss_mb || 0} MB</td>
      <td class="font-data-sm">${p.pss_mb || 0} MB</td>
      <td class="font-data-sm">${p.threads || '--'}</td>
      <td class="font-data-sm">${p.open_handles || p.open_fds || '--'}</td>
    </tr>
  `).join('');
}

async function handleCaptureProfileSnapshot() {
  try {
    showToast('Capturing runtime diagnostic profile...', 'info');
    const res = await apiFetch('/api/admin/diagnostics/profile-snapshot', { method: 'POST' });
    if (res.ok) {
      showToast('Profile snapshot saved to diagnostics repository.', 'success');
      loadDiagnosticsReport();
    }
  } catch (e) {
    showToast('Failed to capture profile snapshot.', 'error');
  }
}

async function handleCompactRagIndex() {
  try {
    showToast('Compacting SQLite FTS5 RAG Index...', 'info');
    const res = await apiFetch('/api/rag/compact', { method: 'POST' });
    if (res.ok) {
      showToast('RAG Inverted Index compacted.', 'success');
      loadDiagnosticsReport();
    }
  } catch (e) {
    showToast('Compaction failed.', 'error');
  }
}

// ==============================================================================
// 10. SETTINGS, AUTOMATION & BACKUPS
// ==============================================================================

async function loadSettings() {
  try {
    const res = await apiFetch('/api/settings');
    if (res.ok) {
      const data = await res.json();
      const host = document.getElementById('settingHostname');
      const port = document.getElementById('settingPort');
      const ramP = document.getElementById('settingRamPressure');
      const ramC = document.getElementById('settingRamCritical');
      if (host && data.hostname) host.value = data.hostname;
      if (port && data.port) port.value = data.port;
      if (ramP && data.ram_pressure_threshold) ramP.value = data.ram_pressure_threshold;
      if (ramC && data.ram_critical_threshold) ramC.value = data.ram_critical_threshold;
    }
  } catch (e) {}
}

async function handleSaveSettings() {
  const host = document.getElementById('settingHostname');
  const port = document.getElementById('settingPort');
  const ramP = document.getElementById('settingRamPressure');
  const ramC = document.getElementById('settingRamCritical');

  const payload = {
    hostname: host ? host.value : 'TECNO BG6',
    port: port ? parseInt(port.value, 10) : 5000,
    ram_pressure_threshold: ramP ? parseInt(ramP.value, 10) : 82,
    ram_critical_threshold: ramC ? parseInt(ramC.value, 10) : 92
  };

  try {
    const res = await apiFetch('/api/settings', {
      method: 'POST',
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      showToast('Settings saved successfully.', 'success');
    }
  } catch (e) {
    showToast('Failed to save settings.', 'error');
  }
}

async function loadAutomationJobs() {
  try {
    const res = await apiFetch('/api/automation/jobs');
    if (res.ok) {
      const data = await res.json();
      const container = document.getElementById('automationJobsList');
      if (container && data.jobs) {
        container.innerHTML = data.jobs.map(j => `
          <div class="service-row">
            <div>
              <div class="service-name">${escapeHtml(j.name)}</div>
              <div class="service-detail">${escapeHtml(j.schedule || 'Scheduled')} • Last run: ${j.last_run || 'Never'}</div>
            </div>
            <button class="btn btn-primary" style="padding: 2px 8px; font-size: 11px; min-height: 28px;" onclick="runAutomationJob('${j.id}')">Run Now</button>
          </div>
        `).join('');
      }
    }
  } catch (e) {}
}

async function runAutomationJob(jobId) {
  try {
    showToast(`Triggering job ${jobId}...`, 'info');
    const res = await apiFetch(`/api/automation/jobs/${jobId}/run`, { method: 'POST' });
    if (res.ok) {
      showToast('Job executed.', 'success');
      loadAutomationJobs();
    }
  } catch (e) {
    showToast('Job execution failed.', 'error');
  }
}

async function loadBackupsList() {
  try {
    const res = await apiFetch('/api/backups');
    if (res.ok) {
      const data = await res.json();
      const tbody = document.getElementById('backupsTableBody');
      if (tbody && data.backups) {
        if (data.backups.length === 0) {
          tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--on-surface-muted); padding: 16px;">No backup archives generated yet.</td></tr>';
          return;
        }
        tbody.innerHTML = data.backups.map(b => `
          <tr>
            <td style="color: var(--on-surface-bright); font-weight: 500;">${escapeHtml(b.filename)}</td>
            <td class="font-data-sm">${formatBytes(b.size || 0)}</td>
            <td class="font-data-sm">${b.created || '--'}</td>
            <td style="text-align: right;">
              <a class="btn btn-primary" style="padding: 2px 8px; font-size: 10px; min-height: 24px;" href="/download/${encodeURIComponent(b.filename)}" download>Download</a>
            </td>
          </tr>
        `).join('');
      }
    }
  } catch (e) {}
}

async function handleCreateBackup() {
  try {
    showToast('Generating system backup...', 'info');
    const res = await apiFetch('/api/backups/create', { method: 'POST' });
    if (res.ok) {
      showToast('Backup archive created.', 'success');
      loadBackupsList();
    }
  } catch (e) {
    showToast('Backup creation failed.', 'error');
  }
}

async function loadStorageIntel() {
  try {
    const res = await apiFetch('/api/system/storage-intel');
    if (res.ok) {
      const data = await res.json();
      const container = document.getElementById('storageIntelBreakdown');
      if (container && data.breakdown) {
        container.innerHTML = data.breakdown.map(b => `
          <div class="service-row">
            <div>
              <div class="service-name">${escapeHtml(b.directory)}</div>
              <div class="service-detail">${b.file_count || 0} objects</div>
            </div>
            <span class="font-data-md" style="color: var(--primary);">${formatBytes(b.size_bytes || 0)}</span>
          </div>
        `).join('');
      }
    }
  } catch (e) {}
}

async function loadEventsArchive() {
  try {
    const res = await apiFetch('/api/events');
    if (res.ok) {
      const data = await res.json();
      const container = document.getElementById('fullEventLogContainer');
      if (container && data.events) {
        container.innerHTML = data.events.map(ev => `
          <div class="log-entry">
            <span class="log-time">[${ev.timestamp ? ev.timestamp.substring(11, 19) : '--'}]</span>
            <span class="log-level ${ev.level || 'INFO'}">${ev.level || 'INFO'}</span>
            <span class="log-msg">${escapeHtml(ev.message || '')}</span>
          </div>
        `).join('');
      }
    }
  } catch (e) {}
}

async function loadAdminUsers() {
  if (authState.role !== 'admin') return;
  try {
    const res = await apiFetch('/api/admin/users');
    if (res.ok) {
      const data = await res.json();
      const tbody = document.getElementById('adminUserTableBody');
      if (tbody && data.users) {
        tbody.innerHTML = data.users.map(u => `
          <tr>
            <td style="color: var(--on-surface-bright); font-weight: 500;">${escapeHtml(u.username)}</td>
            <td><span class="node-badge" style="color: ${u.role === 'admin' ? 'var(--primary)' : 'var(--on-surface-variant)'};">${(u.role || 'USER').toUpperCase()}</span></td>
            <td class="font-data-sm">${u.created_at ? u.created_at.substring(0, 10) : '--'}</td>
            <td style="text-align: right;">
              <button class="btn btn-secondary" style="padding: 2px 8px; font-size: 10px; min-height: 24px;" onclick="showToast('User edit modal ready.', 'info')">Edit</button>
            </td>
          </tr>
        `).join('');
      }
    }
  } catch (e) {}
}

function openAddUserModal() {
  showToast('Add user dialog opening...', 'info');
}

// ==============================================================================
// 11. UTILITY FUNCTIONS
// ==============================================================================

function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `
    <span class="material-symbols-outlined" style="font-size: 16px;">
      ${type === 'success' ? 'check_circle' : (type === 'error' ? 'error' : (type === 'warning' ? 'warning' : 'info'))}
    </span>
    <span>${escapeHtml(message)}</span>
  `;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

function formatBytes(bytes, decimals = 2) {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
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

// ==============================================================================
// 12. INITIALIZATION ON DOM READY
// ==============================================================================

document.addEventListener('DOMContentLoaded', () => {
  initAuth();

  const usernameInput = document.getElementById('loginUsername');
  if (usernameInput) {
    let debounceTimer = null;
    usernameInput.addEventListener('input', (e) => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        checkServerLockoutState(e.target.value);
      }, 350);
    });
  }
});
