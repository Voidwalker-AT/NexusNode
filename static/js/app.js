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
  isPollingSystemStatus: false,
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
// 1.1 CENTRAL DATA CACHE & STALE-WHILE-REVALIDATE REGISTRY
// ==============================================================================

const appData = {
  status: { data: null, loadedAt: 0, loading: false, error: null, ttl: 3000 },
  vault: { data: null, loadedAt: 0, loading: false, error: null, ttl: 20000, currentPath: '', destinations: null },
  media: { data: null, loadedAt: 0, loading: false, error: null, ttl: 15000 },
  mediaQueue: { data: null, loadedAt: 0, loading: false, error: null, ttl: 2500 },
  tasks: { data: null, loadedAt: 0, loading: false, error: null, ttl: 2000 },
  aiState: { data: null, loadedAt: 0, loading: false, error: null, ttl: 4000 },
  aiModels: { data: null, loadedAt: 0, loading: false, error: null, ttl: 30000 },
  services: { data: null, loadedAt: 0, loading: false, error: null, ttl: 5000 },
  events: { data: null, loadedAt: 0, loading: false, error: null, ttl: 20000 },
  backups: { data: null, loadedAt: 0, loading: false, error: null, ttl: 45000 },
  automation: { data: null, loadedAt: 0, loading: false, error: null, ttl: 45000 },
  storageIntel: { data: null, loadedAt: 0, loading: false, error: null, ttl: 30000 },
  settings: { data: null, loadedAt: 0, loading: false, error: null, ttl: 45000 },
  users: { data: null, loadedAt: 0, loading: false, error: null, ttl: 45000 },
  diagnostics: { data: null, loadedAt: 0, loading: false, error: null, ttl: 60000 }
};

const inFlightRequests = new Map();

function clearAppDataCache() {
  for (const key of Object.keys(appData)) {
    if (key === 'vault') {
      appData[key].data = null;
      appData[key].loadedAt = 0;
      appData[key].loading = false;
      appData[key].error = null;
      appData[key].currentPath = '';
      appData[key].destinations = null;
    } else {
      appData[key].data = null;
      appData[key].loadedAt = 0;
      appData[key].loading = false;
      appData[key].error = null;
    }
  }
  inFlightRequests.clear();
}

async function fetchJsonCached(url, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  if (method === 'GET') {
    if (inFlightRequests.has(url)) {
      return inFlightRequests.get(url);
    }
    const promise = (async () => {
      try {
        const res = await apiFetch(url, options);
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        return await res.json();
      } finally {
        inFlightRequests.delete(url);
      }
    })();
    inFlightRequests.set(url, promise);
    return promise;
  }
  const res = await apiFetch(url, options);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return await res.json();
}

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
    headers['X-Session-Token'] = authState.token;
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
    headers['X-Session-Token'] = authState.token;
  }
  if (!headers['Content-Type'] && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }
  options.headers = headers;

  // Timeout handling using AbortController (default 8000ms, bypassable via options.timeoutMs = 0)
  const timeoutMs = options.timeoutMs !== undefined ? options.timeoutMs : 8000;
  let timerId = null;
  let controller = null;

  if (timeoutMs > 0 && !options.signal) {
    controller = new AbortController();
    options.signal = controller.signal;
    timerId = setTimeout(() => {
      controller.abort();
    }, timeoutMs);
  }

  try {
    const res = await fetch(url, options);
    if (timerId) clearTimeout(timerId);

    if (res.status === 401) {
      clearAppDataCache();
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
    if (timerId) clearTimeout(timerId);
    if (err.name === 'AbortError') {
      console.warn(`Request timed out after ${timeoutMs}ms: ${url}`);
      throw new Error(`Request timed out after ${timeoutMs / 1000}s`);
    }
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

  // Load initial tab data (shows dashboard immediately)
  switchTab(appState.activeTab || 'dashboard');

  // Start background preload of lightweight tab datasets in parallel
  preloadAppData();
}

// ==============================================================================
// 2.1 BACKGROUND PRELOAD ROUTINE (STALE-WHILE-REVALIDATE)
// ==============================================================================

let isPreloadingData = false;

async function preloadAppData() {
  if (!authState.isAuthenticated || isPreloadingData) return;
  isPreloadingData = true;

  const isAdmin = (authState.role === 'admin');

  // Lightweight tab datasets to fetch concurrently without blocking the main dashboard
  const preloadTasks = [
    // 1. Vault Root files & dynamic destinations
    loadVaultFiles('', { isPreload: true }).catch(() => {}),
    loadVaultDestinations({ isPreload: true }).catch(() => {}),

    // 2. Media Library & Media Queue
    loadMediaLibrary({ isPreload: true }).catch(() => {}),
    pollMediaQueue({ isPreload: true }).catch(() => {}),

    // 3. Background Tasks List
    loadTasksList({ isPreload: true }).catch(() => {}),

    // 4. AI Studio State & Installed Models
    loadAiState({ isPreload: true }).catch(() => {}),

    // 5. Network / Services status
    loadNetworkInterfaces({ isPreload: true }).catch(() => {}),

    // 6. Storage Partition Intelligence
    loadStorageIntel({ isPreload: true }).catch(() => {}),

    // 7. Server Settings
    loadSettings({ isPreload: true }).catch(() => {})
  ];

  if (isAdmin || hasPrivilege('can_view_system_logs')) {
    preloadTasks.push(loadEventsArchive({ isPreload: true }).catch(() => {}));
  }

  if (isAdmin || hasPrivilege('can_manage_backups')) {
    preloadTasks.push(loadBackupsList({ isPreload: true }).catch(() => {}));
  }

  if (isAdmin || hasPrivilege('can_manage_automation')) {
    preloadTasks.push(loadAutomationJobs({ isPreload: true }).catch(() => {}));
  }

  if (isAdmin) {
    preloadTasks.push(loadAdminUsers({ isPreload: true }).catch(() => {}));
  }

  // Execute all preload tasks concurrently using Promise.allSettled
  Promise.allSettled(preloadTasks).then(() => {
    isPreloadingData = false;
  });
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

  // Clear Session & Cache
  clearAppDataCache();
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
      loadVaultDestinations();
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
      loadTimetableSyncStatus();
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
    case 'network':
      loadNetworkInterfaces();
      break;
    case 'admin':
      loadAdminUsers();
      break;
    case 'attendance':
      loadAttendanceData();
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

async function pollSystemStatus(opts = {}) {
  if (!authState.isAuthenticated) return;
  if (appState.isPollingSystemStatus && !opts.force) return;

  // Render cached status immediately if present
  if (appData.status.data && !opts.isPreload) {
    updateTelemetryUI(appData.status.data);
  }

  appState.isPollingSystemStatus = true;

  try {
    const data = await fetchJsonCached('/api/system/status', { timeoutMs: 6000 });
    appData.status.data = data;
    appData.status.loadedAt = Date.now();
    appData.status.error = null;

    if (!opts.isPreload) {
      updateTelemetryUI(data);
    }
    return data;
  } catch (e) {
    appData.status.error = e;
    console.warn('System status poll error:', e);
  } finally {
    appState.isPollingSystemStatus = false;
  }
}

function updateTelemetryUI(data) {
  if (!data) return;

  // 1. Top Status Strip
  const stripUptime = document.getElementById('stripUptime');
  const uptimeVal = data.system?.uptime || data.server?.uptime;
  if (stripUptime && uptimeVal) {
    stripUptime.textContent = uptimeVal;
  }

  const stripBattery = document.getElementById('stripBattery');
  const battLvl = data.battery?.level ?? data.device?.battery_percent;
  if (stripBattery && battLvl !== undefined && battLvl !== null) {
    stripBattery.textContent = `${battLvl}%`;
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
  const ramPercent = ram.percent ?? ram.ram_percent ?? 0;
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
  const swap = data.swap || data.memory || {};
  const swapPercent = swap.percent ?? swap.swap_percent ?? 0;
  const swapMeterFill = document.getElementById('swapMeterFill');
  const swapMeterVal = document.getElementById('swapMeterVal');
  const swapDetail = document.getElementById('swapDetailText');
  if (swapMeterFill) {
    swapMeterFill.style.width = `${Math.min(swapPercent, 100)}%`;
  }
  if (swapMeterVal) swapMeterVal.textContent = `${swapPercent}%`;
  const swapUsed = swap.used_mb ?? swap.swap_used_mb;
  const swapTotal = swap.total_mb ?? swap.swap_total_mb;
  if (swapDetail && swapUsed !== undefined) {
    swapDetail.textContent = `${swapUsed} / ${swapTotal || 0} MB`;
  }

  // 4. Storage Meter
  const stg = data.storage || data.disk || {};
  const stgPercent = stg.percent || 0;
  const stgMeterFill = document.getElementById('storageMeterFill');
  const stgMeterVal = document.getElementById('storageMeterVal');
  const stgDetail = document.getElementById('storageDetailText');
  if (stgMeterFill) stgMeterFill.style.width = `${Math.min(stgPercent, 100)}%`;
  if (stgMeterVal) stgMeterVal.textContent = `${stgPercent}%`;
  if (stgDetail && stg.used_gb) {
    stgDetail.textContent = `${stg.used_gb} / ${stg.total_gb || '--'} GB`;
  }

  // 5. CPU Meter
  const cpu = data.cpu || data.device || {};
  const cpuPercent = cpu.percent ?? cpu.cpu_usage_percent ?? 0;
  const cpuMeterFill = document.getElementById('cpuMeterFill');
  const cpuMeterVal = document.getElementById('cpuMeterVal');
  if (cpuMeterFill) cpuMeterFill.style.width = `${Math.min(cpuPercent, 100)}%`;
  if (cpuMeterVal) cpuMeterVal.textContent = `${cpuPercent}%`;

  // 6. Battery & Thermal Chip
  const dashBatteryLevel = document.getElementById('dashBatteryLevel');
  const dashBatteryStatus = document.getElementById('dashBatteryStatus');
  if (dashBatteryLevel) {
    dashBatteryLevel.textContent = `${battLvl ?? '--'}%`;
    if (dashBatteryStatus) dashBatteryStatus.textContent = (data.battery?.status || data.device?.battery_status || 'STANDBY').toUpperCase();
  }

  const dashThermalLevel = document.getElementById('dashThermalLevel');
  const dashThermalStatus = document.getElementById('dashThermalStatus');
  const thermTemp = data.thermal?.temp_c ?? data.device?.cpu_temperature_c;
  if (dashThermalLevel) {
    dashThermalLevel.textContent = thermTemp !== undefined && thermTemp !== null ? `${thermTemp}°C` : '--°C';
    if (dashThermalStatus) dashThermalStatus.textContent = (data.thermal?.status || data.appliance?.state || 'NORMAL').toUpperCase();
  }

  // 7. Active Task Supervision
  const activeTask = data.active_task || (data.tasks?.active_tasks && data.tasks.active_tasks[0]);
  if (activeTask) {
    const rawTaskId = activeTask.task_id || activeTask.id;
    appState.activeTaskId = rawTaskId;
    const taskTitle = document.getElementById('activeTaskTitle');
    const taskStatus = document.getElementById('activeTaskStatus');
    const taskFill = document.getElementById('activeTaskMeterFill');
    const taskStep = document.getElementById('activeTaskStepText');
    const taskPct = document.getElementById('activeTaskPercent');
    const cancelBtn = document.getElementById('activeTaskCancelBtn');
    const idText = document.getElementById('activeTaskIdText');

    const statusUpper = (activeTask.status || 'RUNNING').toUpperCase();
    const stageUpper = (activeTask.stage || statusUpper).toUpperCase();
    let stepLabel = activeTask.step_label || 'Executing operation...';
    if (stageUpper === 'POST_PROCESSING') stepLabel = 'Post-processing media (merging/transcoding)...';
    else if (stageUpper === 'VERIFYING') stepLabel = 'Verifying output media file...';
    else if (stageUpper === 'DOWNLOADING') {
      const spd = activeTask.speed_bps ? `${(activeTask.speed_bps / (1024*1024)).toFixed(1)} MB/s` : '';
      const eta = activeTask.eta_seconds ? `ETA ${activeTask.eta_seconds}s` : '';
      if (spd || eta) stepLabel = `Downloading... ${[spd, eta].filter(Boolean).join(' • ')}`;
    }

    if (taskTitle) taskTitle.textContent = activeTask.title || activeTask.type;
    if (taskStatus) taskStatus.textContent = stageUpper !== statusUpper ? `${statusUpper} (${stageUpper})` : statusUpper;
    if (taskFill) taskFill.style.width = `${Math.min(activeTask.progress || 0, 100)}%`;
    if (taskStep) taskStep.textContent = stepLabel;
    if (taskPct) taskPct.textContent = `${activeTask.progress || 0}%`;
    if (cancelBtn) cancelBtn.style.display = 'block';
    if (idText) idText.textContent = `TASK: #${rawTaskId}`;
  } else {
    appState.activeTaskId = null;
    const taskTitle = document.getElementById('activeTaskTitle');
    const taskStatus = document.getElementById('activeTaskStatus');
    const taskFill = document.getElementById('activeTaskMeterFill');
    const taskStep = document.getElementById('activeTaskStepText');
    const taskPct = document.getElementById('activeTaskPercent');
    const cancelBtn = document.getElementById('activeTaskCancelBtn');
    const idText = document.getElementById('activeTaskIdText');

    if (taskTitle) taskTitle.textContent = 'Bounded Worker Pool (Concurrency = 1)';
    if (taskStatus) taskStatus.textContent = 'IDLE';
    if (taskFill) taskFill.style.width = '0%';
    if (taskStep) taskStep.textContent = 'Bounded runner standing by...';
    if (taskPct) taskPct.textContent = '0%';
    if (cancelBtn) cancelBtn.style.display = 'none';
    if (idText) idText.textContent = 'TASK: IDLE';
  }

  // 8. Core Services
  if (data.services) {
    updateServicesUI(data.services);
  }
}

function updateServicesUI(services) {
  if (!services) return;

  // 1. NexusNode
  const nexus = services.nexusnode || {};
  const isNexusUp = Boolean(nexus.running || nexus.status === 'online' || nexus.status === 'running' || nexus.pid);
  const svcBadgeNexus = document.getElementById('svcBadgeNexus');
  const svcDotNexus = document.getElementById('svcDotNexus');
  const svcDetailNexus = document.getElementById('svcDetailNexus');
  if (svcBadgeNexus) svcBadgeNexus.textContent = isNexusUp ? 'RUNNING' : 'STOPPED';
  if (svcDotNexus) svcDotNexus.className = isNexusUp ? 'service-dot online' : 'service-dot offline';
  if (svcDetailNexus) svcDetailNexus.textContent = `PID ${nexus.pid || '--'} • Port ${nexus.port || 5000}`;

  // 2. SSHD
  const ssh = services.ssh || services.sshd || {};
  const isSshUp = Boolean(ssh.running || ssh.status === 'online' || ssh.status === 'running');
  const svcBadgeSsh = document.getElementById('svcBadgeSsh');
  const svcDotSsh = document.getElementById('svcDotSsh');
  const svcDetailSsh = document.getElementById('svcDetailSsh');
  if (svcBadgeSsh) svcBadgeSsh.textContent = isSshUp ? 'RUNNING' : 'STOPPED';
  if (svcDotSsh) svcDotSsh.className = isSshUp ? 'service-dot online' : 'service-dot offline';
  if (svcDetailSsh) svcDetailSsh.textContent = `PID ${ssh.pid || '--'} • Port ${ssh.port || 8022}`;

  // 3. LocalToNet
  const l2n = services.localtonet || {};
  const isL2nConnected = Boolean(l2n.connected || l2n.status === 'tunnel_connected' || l2n.state === 'TUNNEL_CONNECTED' || l2n.public_endpoint === 'reachable');
  const isL2nRunning = Boolean(l2n.running || l2n.process === 'running' || l2n.state === 'PROCESS_ONLY' || l2n.pid);
  const svcBadgeL2n = document.getElementById('svcBadgeL2n');
  const svcDotL2n = document.getElementById('svcDotL2n');
  const svcDetailL2n = document.getElementById('svcDetailL2n');
  if (svcBadgeL2n) svcBadgeL2n.textContent = isL2nConnected ? 'CONNECTED' : (isL2nRunning ? 'CONNECTING' : 'OFFLINE');
  if (svcDotL2n) svcDotL2n.className = isL2nConnected ? 'service-dot online' : (isL2nRunning ? 'service-dot warning' : 'service-dot offline');
  if (svcDetailL2n) svcDetailL2n.textContent = l2n.url || (isL2nRunning ? 'Tunnel initializing...' : 'No active tunnel URL');

  // 4. Ollama
  const ollama = services.ollama || {};
  const isOllamaUp = Boolean(ollama.running || ollama.online || ollama.status === 'running' || ollama.status === 'online' || ollama.loaded_model);
  const svcBadgeOllama = document.getElementById('svcBadgeOllama');
  const svcDotOllama = document.getElementById('svcDotOllama');
  const svcDetailOllama = document.getElementById('svcDetailOllama');
  if (svcBadgeOllama) svcBadgeOllama.textContent = isOllamaUp ? 'RUNNING' : 'STANDBY';
  if (svcDotOllama) svcDotOllama.className = isOllamaUp ? 'service-dot online' : 'service-dot warning';
  if (svcDetailOllama) {
    if (ollama.loaded_model) {
      svcDetailOllama.textContent = `Active: ${ollama.loaded_model}`;
    } else {
      svcDetailOllama.textContent = isOllamaUp ? 'Ready • No model resident' : 'Supervisor standby';
    }
  }
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

async function loadVaultDestinations(opts = {}) {
  const select = document.getElementById('vaultUploadDestination');
  if (appData.vault.destinations && select) {
    renderVaultDestinations(appData.vault.destinations);
  }

  const now = Date.now();
  if (appData.vault.destinations && (now - appData.vault.loadedAt < 30000) && !opts.force && !opts.isPreload) {
    return appData.vault.destinations;
  }

  try {
    const data = await fetchJsonCached('/api/vault/destinations', { timeoutMs: 6000 });
    const destinations = data.destinations || [];
    appData.vault.destinations = destinations;
    if (select) {
      renderVaultDestinations(destinations);
    }
    return destinations;
  } catch (e) {
    console.warn('Failed to load dynamic vault destinations:', e);
  }
}

function renderVaultDestinations(destinations) {
  const select = document.getElementById('vaultUploadDestination');
  if (!select || !destinations) return;
  const currentVal = select.value;
  select.innerHTML = destinations.map(d => `
    <option value="${escapeHtml(d.path)}" ${d.path === currentVal ? 'selected' : ''}>${escapeHtml(d.label)}</option>
  `).join('');
}

async function loadVaultFiles(folderPath, opts = {}) {
  const tbody = document.getElementById('vaultTableBody');
  const countLabel = document.getElementById('vaultFileCount');
  const isRoot = !folderPath;

  appState.currentVaultPath = folderPath || '';

  // 1. If viewing Root and cached data exists, render IMMEDIATELY
  if (isRoot && appData.vault.data) {
    appState.cachedFiles = appData.vault.data;
    if (!opts.isPreload) {
      renderVaultTable(appData.vault.data);
    }
  } else if (!opts.isPreload) {
    // Only show loading indicator if we don't already have rendered items
    if (tbody && (!tbody.children.length || tbody.innerHTML.includes('Unable to load') || tbody.innerHTML.includes('Vault load error'))) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--on-surface-muted); padding: 24px;">Loading Vault objects...</td></tr>';
    }
  }

  const url = folderPath ? `/files?path=${encodeURIComponent(folderPath)}` : '/files';

  // Check TTL for root
  const now = Date.now();
  if (isRoot && appData.vault.data && (now - appData.vault.loadedAt < appData.vault.ttl) && !opts.force && !opts.isPreload) {
    return appData.vault.data;
  }

  try {
    const data = await fetchJsonCached(url, { timeoutMs: 8000 });
    const files = data.files || (Array.isArray(data) ? data : []);

    if (isRoot) {
      appData.vault.data = files;
      appData.vault.loadedAt = Date.now();
      appData.vault.error = null;
    }
    appState.cachedFiles = files;

    if (!opts.isPreload) {
      renderVaultTable(files);

      // Sync destination dropdown with current folder if available
      const destSelect = document.getElementById('vaultUploadDestination');
      if (destSelect && folderPath !== undefined) {
        let optExists = Array.from(destSelect.options).some(o => o.value === (folderPath || ''));
        if (!optExists && folderPath) {
          const newOpt = document.createElement('option');
          newOpt.value = folderPath;
          newOpt.textContent = `${folderPath.split('/').pop()} (/${folderPath})`;
          destSelect.appendChild(newOpt);
        }
        destSelect.value = folderPath || '';
      }
    }
    return files;
  } catch (e) {
    console.error('Failed to load vault files:', e);
    if (isRoot && appData.vault.data) {
      // Keep existing cached data rendered!
      showToast('Vault background refresh failed.', 'warning');
    } else if (!opts.isPreload) {
      if (countLabel) countLabel.textContent = 'ERROR';
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--status-critical); padding: 24px;">Vault load error: ${escapeHtml(e.message || 'Request failed')}</td></tr>`;
      }
    }
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

  const authQuery = authState.token ? `?auth=${encodeURIComponent(authState.token)}` : '';

  rowsHtml += filtered.map(file => {
    const isDir = Boolean(file.is_dir);
    const ext = isDir ? 'FOLDER' : (file.name.split('.').pop() || 'FILE').toUpperCase();
    const size = isDir ? '--' : formatBytes(file.size || 0);
    const date = file.modified ? file.modified.substring(0, 16).replace('T', ' ') : '--';
    const isMedia = !isDir && ['MP3', 'MP4', 'MKV', 'WEBM', 'M4A', 'FLAC', 'WAV', 'AAC', 'OGG', 'MOV', 'AVI'].includes(ext);
    const isPhoto = !isDir && ['JPG', 'JPEG', 'PNG', 'WEBP', 'GIF', 'SVG', 'BMP', 'ICO', 'TIFF'].includes(ext);

    let iconName = 'draft';
    if (isDir) iconName = 'folder';
    else if (isPhoto) iconName = 'image';
    else if (isMedia) iconName = 'movie';

    return `
      <tr>
        <td style="font-weight: 500; color: var(--on-surface-bright);">
          <div style="display: flex; align-items: center; gap: 8px;">
            <span class="material-symbols-outlined" style="color: ${isDir ? 'var(--primary)' : isPhoto ? 'var(--secondary)' : 'var(--on-surface-muted)'};">${iconName}</span>
            ${isDir ? `<a href="#" onclick="loadVaultFiles('${encodeURIComponent(file.path || file.name)}'); return false;" style="color: var(--primary); text-decoration: underline;">${escapeHtml(file.name)}</a>` : isPhoto ? `<span style="cursor: pointer; color: var(--on-surface-bright);" onclick="openPhotoPreview('${encodeURIComponent(file.path || file.name)}', '${escapeHtml(file.name)}')">${escapeHtml(file.name)}</span>` : `<span>${escapeHtml(file.name)}</span>`}
          </div>
        </td>
        <td><span class="node-badge" style="${isDir ? 'color: var(--primary); border-color: rgba(0, 218, 243, 0.4);' : isPhoto ? 'color: var(--secondary);' : ''}">${ext}</span></td>
        <td class="font-data-sm">${size}</td>
        <td class="font-data-sm" style="color: var(--on-surface-variant);">${date}</td>
        <td style="text-align: right;">
          <div style="display: inline-flex; gap: 4px;">
            ${isPhoto ? `<button class="icon-btn" title="View Photo" onclick="openPhotoPreview('${encodeURIComponent(file.path || file.name)}', '${escapeHtml(file.name)}')"><span class="material-symbols-outlined" style="font-size: 16px;">visibility</span></button>` : ''}
            ${isMedia ? `<button class="icon-btn" title="Stream" onclick="playMediaFile('${encodeURIComponent(file.path || file.name)}', '${ext.toLowerCase()}', '${escapeHtml(file.name)}')"><span class="material-symbols-outlined" style="font-size: 16px;">play_arrow</span></button>` : ''}
            <a class="icon-btn" title="${isDir ? 'Download Zip' : 'Download'}" href="/download/${encodeURIComponent(file.path || file.name)}${authQuery}" download><span class="material-symbols-outlined" style="font-size: 16px;">${isDir ? 'folder_zip' : 'download'}</span></a>
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
  } else if (location === 'photos') {
    // Show all files filtered by photos category
    if (appState.currentVaultPath) {
      loadVaultFiles(appState.currentVaultPath);
    } else {
      loadVaultFiles('');
    }
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

  const destSelect = document.getElementById('vaultUploadDestination');
  const selectedDest = (destSelect ? destSelect.value : '') || appState.currentVaultPath || '';

  const formData = new FormData();
  formData.append('file', file);
  if (selectedDest) {
    formData.append('path', selectedDest);
  }

  try {
    const destDisplay = selectedDest ? `/${selectedDest}` : 'Vault Root';
    showToast(`Uploading ${file.name} to ${destDisplay}...`, 'info');
    const res = await apiFetch('/upload', {
      method: 'POST',
      body: formData,
      timeoutMs: 0 // File uploads must not time out
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      showToast(data.message || 'File uploaded successfully.', 'success');
      loadVaultFiles(selectedDest);
      loadVaultDestinations();
    } else {
      showToast(data.message || data.error || `Upload failed (HTTP ${res.status}).`, 'error');
    }
  } catch (e) {
    showToast(`Failed to upload file: ${e.message || 'Network error'}`, 'error');
  } finally {
    event.target.value = '';
  }
}

async function handleVaultDelete(filename) {
  const decoded = decodeURIComponent(filename);
  if (!confirm(`Are you sure you want to delete ${decoded}?`)) return;

  try {
    const res = await apiFetch('/delete', {
      method: 'POST',
      body: JSON.stringify({ filename: decoded })
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      showToast(data.message || 'Object deleted successfully.', 'success');
      loadVaultFiles(appState.currentVaultPath);
    } else {
      showToast(data.message || data.error || 'Delete failed.', 'error');
    }
  } catch (e) {
    showToast(`Failed to delete object: ${e.message || 'Network error'}`, 'error');
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

let lastKnownActiveMediaCount = 0;

async function pollMediaQueue(opts = {}) {
  // If cached queue exists, render immediately
  if (appData.mediaQueue.data && !opts.isPreload) {
    renderMediaQueue(appData.mediaQueue.data);
  }

  try {
    const data = await fetchJsonCached('/api/tasks?type=media_download', { timeoutMs: 6000 });
    const tasks = Array.isArray(data) ? data : (data.tasks || []);
    appData.mediaQueue.data = tasks;
    appData.mediaQueue.loadedAt = Date.now();
    appData.mediaQueue.error = null;

    if (!opts.isPreload) {
      renderMediaQueue(tasks);
    }
    return tasks;
  } catch (e) {
    appData.mediaQueue.error = e;
  }
}

function renderMediaQueue(tasks) {
  const container = document.getElementById('mediaQueueContainer');
  const countLabel = document.getElementById('mediaQueueCount');
  if (!container) return;

  const activeTasks = tasks.filter(t => ['STARTING', 'RUNNING', 'POST_PROCESSING', 'VERIFYING', 'CANCELLING'].includes((t.status || '').toUpperCase()));
  const queuedTasks = tasks.filter(t => (t.status || '').toUpperCase() === 'QUEUED');
  const currentTotal = activeTasks.length + queuedTasks.length;

  if (countLabel) {
    if (queuedTasks.length > 0) {
      countLabel.textContent = `${activeTasks.length} ACTIVE • ${queuedTasks.length} QUEUED`;
    } else {
      countLabel.textContent = `${activeTasks.length} ACTIVE`;
    }
  }

  if (lastKnownActiveMediaCount > 0 && currentTotal === 0) {
    loadMediaLibrary();
  }
  lastKnownActiveMediaCount = currentTotal;

  const displayTasks = [...activeTasks, ...queuedTasks];
  if (displayTasks.length === 0) {
    container.innerHTML = '<div class="font-data-sm" style="color: var(--on-surface-muted); text-align: center; padding: 16px;">Queue is currently empty.</div>';
    return;
  }

  container.innerHTML = displayTasks.map(t => {
    const rawId = t.task_id || t.id;
    const statusUpper = (t.status || 'QUEUED').toUpperCase();
    const stageUpper = (t.stage || statusUpper).toUpperCase();
    const stageDisplay = stageUpper !== statusUpper ? `${statusUpper} (${stageUpper})` : statusUpper;
    return `
      <div style="background-color: var(--surface-2); border: 1px solid var(--border-subtle); border-radius: var(--radius-xs); padding: 10px 12px; display: flex; justify-content: space-between; align-items: center;">
        <div style="display: flex; flex-direction: column; gap: 4px;">
          <span class="font-headline-md" style="font-size: 13px; color: var(--on-surface-bright);">${escapeHtml(t.title || 'YT-DLP Operation')}</span>
          <span class="font-data-sm" style="color: var(--on-surface-variant);">${stageDisplay} • ${t.progress || 0}%</span>
        </div>
        <button class="btn btn-danger" style="padding: 2px 8px; font-size: 10px; min-height: 24px;" onclick="cancelTask('${escapeHtml(String(rawId))}')">Cancel</button>
      </div>
    `;
  }).join('');
}

async function loadMediaLibrary(opts = {}) {
  const grid = document.getElementById('mediaLibraryGrid');

  // 1. If cached data exists, render IMMEDIATELY
  if (appData.media.data) {
    appState.mediaLibrary = appData.media.data;
    if (!opts.isPreload) {
      renderMediaLibrary(appData.media.data);
    }
  } else if (!opts.isPreload) {
    if (grid && (!grid.children.length || grid.innerHTML.includes('Unable to load') || grid.innerHTML.includes('Media library error'))) {
      grid.innerHTML = '<div class="font-data-sm" style="color: var(--on-surface-muted); padding: 16px;">Scanning media files...</div>';
    }
  }

  const now = Date.now();
  if (appData.media.data && (now - appData.media.loadedAt < appData.media.ttl) && !opts.force && !opts.isPreload) {
    return appData.media.data;
  }

  try {
    const data = await fetchJsonCached('/api/media/library', { timeoutMs: 8000 });
    let items = [];
    if (data.items) {
      items = data.items;
    } else if (Array.isArray(data)) {
      items = data;
    } else if (typeof data === 'object') {
      items = Object.values(data).filter(Array.isArray).flat();
    }
    appData.media.data = items;
    appData.media.loadedAt = Date.now();
    appData.media.error = null;
    appState.mediaLibrary = items;

    if (!opts.isPreload) {
      renderMediaLibrary(items);
    }
    return items;
  } catch (e) {
    console.error('Failed to load media library:', e);
    if (appData.media.data) {
      showToast('Media library background refresh failed.', 'warning');
    } else if (!opts.isPreload && grid) {
      grid.innerHTML = `<div class="font-data-sm" style="color: var(--status-critical); padding: 16px;">Media library error: ${escapeHtml(e.message || 'Request failed')}</div>`;
    }
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

async function playMediaFile(encodedPath, type, title) {
  const path = decodeURIComponent(encodedPath);
  const playerBox = document.getElementById('mediaPlayerBox');
  const nowPlayingTitle = document.getElementById('nowPlayingTitle');
  const audio = document.getElementById('globalAudioPlayer');
  const video = document.getElementById('globalVideoPlayer');

  if (!playerBox) return;
  playerBox.style.display = 'block';
  if (nowPlayingTitle) nowPlayingTitle.textContent = `Preparing stream: ${title || path}...`;

  let streamUrl = `/stream/${encodeURIComponent(path)}`;
  try {
    const res = await fetch('/api/media/playback-token', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${authState.token || ''}`
      },
      body: JSON.stringify({ path: path })
    });
    if (res.ok) {
      const data = await res.json();
      if (data && data.playback_token) {
        streamUrl = `/stream/${encodeURIComponent(path)}?playback_token=${encodeURIComponent(data.playback_token)}`;
      }
    }
  } catch (e) {
    console.warn('Playback token request fallback:', e);
  }

  if (nowPlayingTitle) nowPlayingTitle.textContent = `Streaming: ${title || path}`;

  const isVid = (type && (type.toLowerCase() === 'video' || type.toLowerCase() === 'videos' || ['mp4', 'mkv', 'webm', 'mov', 'm4v', 'avi'].includes(type.toLowerCase()))) ||
                ['.mp4', '.mkv', '.webm', '.mov', '.m4v', '.avi'].some(ext => path.toLowerCase().endsWith(ext));

  if (isVid) {
    if (audio) { audio.pause(); audio.style.display = 'none'; }
    if (video) {
      video.src = streamUrl;
      video.style.display = 'block';
      video.onerror = () => showToast(`Unable to decode or stream video: ${title || path}`, 'error');
      video.play().catch(e => console.warn('Autoplay prevented or video play error:', e));
    }
  } else {
    if (video) { video.pause(); video.style.display = 'none'; }
    if (audio) {
      audio.src = streamUrl;
      audio.style.display = 'block';
      audio.onerror = () => showToast(`Unable to decode or stream audio: ${title || path}`, 'error');
      audio.play().catch(e => console.warn('Autoplay prevented or audio play error:', e));
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

async function loadTasksList(opts = {}) {
  const tbody = document.getElementById('tasksTableBody');

  // If cached data exists, render IMMEDIATELY
  if (appData.tasks.data) {
    if (!opts.isPreload) {
      renderTasksTable(appData.tasks.data);
    }
  } else if (!opts.isPreload) {
    if (tbody && (!tbody.children.length || tbody.innerHTML.includes('Unable to load') || tbody.innerHTML.includes('Task load error'))) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--on-surface-muted); padding: 24px;">Loading tasks...</td></tr>';
    }
  }

  const now = Date.now();
  if (appData.tasks.data && (now - appData.tasks.loadedAt < appData.tasks.ttl) && !opts.force && !opts.isPreload) {
    return appData.tasks.data;
  }

  try {
    const data = await fetchJsonCached('/api/tasks', { timeoutMs: 6000 });
    const tasks = Array.isArray(data) ? data : (data.tasks || []);
    appData.tasks.data = tasks;
    appData.tasks.loadedAt = Date.now();
    appData.tasks.error = null;

    if (!opts.isPreload) {
      renderTasksTable(tasks);
    }
    return tasks;
  } catch (e) {
    console.error('Failed to load tasks:', e);
    if (appData.tasks.data) {
      showToast('Tasks background refresh failed.', 'warning');
    } else if (!opts.isPreload && tbody) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--status-critical); padding: 24px;">Task load error: ${escapeHtml(e.message || 'Request failed')}</td></tr>`;
    }
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
    const rawId = t.task_id || t.id;
    const statusUpper = (t.status || 'QUEUED').toUpperCase();
    const stageUpper = (t.stage || statusUpper).toUpperCase();
    const canCancel = ['QUEUED', 'STARTING', 'RUNNING', 'POST_PROCESSING', 'VERIFYING'].includes(statusUpper);
    const created = formatTimestamp(t.created_at);

    let statusClass = 'var(--on-surface-variant)';
    if (['STARTING', 'RUNNING', 'POST_PROCESSING', 'VERIFYING'].includes(statusUpper)) statusClass = 'var(--primary)';
    if (statusUpper === 'COMPLETED') statusClass = 'var(--status-healthy)';
    if (statusUpper === 'FAILED') statusClass = 'var(--status-critical)';
    if (statusUpper === 'CANCELLED') statusClass = 'var(--on-surface-dim)';

    const displayStatus = stageUpper !== statusUpper ? `${statusUpper} (${stageUpper})` : statusUpper;

    return `
      <tr>
        <td><span class="font-label-caps" style="color: ${statusClass};">${displayStatus}</span></td>
        <td><span class="node-badge">${escapeHtml(t.type || t.task_type || 'TASK')}</span></td>
        <td style="color: var(--on-surface-bright); font-weight: 500;">
          ${escapeHtml(t.title || 'Task #' + rawId)}
          ${t.error ? `<div class="font-data-sm" style="color: var(--status-critical); font-size: 11px; margin-top: 3px; font-weight: normal;">${escapeHtml(t.error)}</div>` : ''}
        </td>
        <td class="font-data-sm">${t.progress || 0}%</td>
        <td class="font-data-sm">${escapeHtml(t.owner || t.owner_user_id || 'system')}</td>
        <td class="font-data-sm" style="color: var(--on-surface-variant);">${created}</td>
        <td style="text-align: right;">
          ${canCancel ? `<button class="btn btn-danger" style="padding: 2px 8px; font-size: 10px; min-height: 24px;" onclick="cancelTask('${escapeHtml(String(rawId))}')">Abort</button>` : '<span style="color: var(--on-surface-dim); font-size: 11px;">--</span>'}
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
    const res = await apiFetch(`/api/tasks/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' });
    if (res.ok) {
      showToast(`Task #${taskId} cancelled.`, 'warning');
      loadTasksList({ force: true });
      pollMediaQueue({ force: true });
      pollSystemStatus({ force: true });
    } else {
      const data = await res.json().catch(() => ({}));
      showToast(data.message || 'Failed to cancel task.', 'error');
    }
  } catch (e) {
    showToast('Failed to cancel task.', 'error');
  }
}

// ==============================================================================
// 8. AI STUDIO (MODEL SELECTION, RESIDENCY & CHAT)
// ==============================================================================

async function loadAiState(opts = {}) {
  // If cached data exists, render immediately
  if (appData.aiState.data || appData.aiModels.data) {
    if (!opts.isPreload) {
      renderAiStateUI(appData.aiState.data, appData.aiModels.data);
    }
  }

  const now = Date.now();
  const isFresh = appData.aiState.data && appData.aiModels.data && (now - appData.aiState.loadedAt < appData.aiState.ttl);
  if (isFresh && !opts.force && !opts.isPreload) {
    return { state: appData.aiState.data, models: appData.aiModels.data };
  }

  try {
    const [modelsResult, stateResult] = await Promise.allSettled([
      fetchJsonCached('/api/ai/models', { timeoutMs: 6000 }),
      fetchJsonCached('/api/ai/state', { timeoutMs: 6000 })
    ]);

    let modelsData = null;
    let stateData = null;

    if (modelsResult.status === 'fulfilled') {
      modelsData = modelsResult.value;
      appData.aiModels.data = modelsData;
      appData.aiModels.loadedAt = Date.now();
      appData.aiModels.error = null;
    }
    if (stateResult.status === 'fulfilled') {
      stateData = stateResult.value;
      appData.aiState.data = stateData;
      appData.aiState.loadedAt = Date.now();
      appData.aiState.error = null;
    }

    if (!opts.isPreload) {
      renderAiStateUI(stateData || appData.aiState.data, modelsData || appData.aiModels.data);
    }
    return { state: appData.aiState.data, models: appData.aiModels.data };
  } catch (e) {
    console.error('Failed to load AI state:', e);
  }
}

function renderAiStateUI(stateData, modelsData) {
  const select = document.getElementById('aiModelSelect');
  const loadedName = document.getElementById('aiLoadedModelName');
  const loadedMem = document.getElementById('aiLoadedModelMemory');
  const unloadBtn = document.getElementById('aiUnloadModelBtn');
  const powerBadge = document.getElementById('aiEngineStatusBadge');
  const powerDetail = document.getElementById('aiEngineDetailText');
  const toggleBtn = document.getElementById('aiEngineToggleBtn');
  const toggleLabel = document.getElementById('aiEngineToggleLabel');
  const toggleIcon = document.getElementById('aiEngineToggleIcon');

  if (stateData) {
    const engineState = (stateData.engine || 'stopped').toLowerCase();
    const isRunning = (engineState === 'running');

    if (powerBadge) {
      powerBadge.textContent = engineState.toUpperCase();
      powerBadge.className = isRunning ? 'status-indicator status-healthy' : 'status-indicator status-offline';
    }
    if (powerDetail) {
      powerDetail.textContent = isRunning ? `Engine: Active (v${stateData.version || '0.x'})` : 'Engine: Offline / Suspended';
    }
    if (toggleBtn && toggleLabel) {
      if (isRunning) {
        toggleBtn.className = 'btn btn-danger';
        toggleLabel.textContent = 'TURN OFF';
        if (toggleIcon) toggleIcon.textContent = 'power_settings_new';
      } else {
        toggleBtn.className = 'btn btn-primary';
        toggleLabel.textContent = 'TURN ON';
        if (toggleIcon) toggleIcon.textContent = 'power_settings_new';
      }
    }

    if (stateData.loaded_model) {
      appState.loadedModel = stateData.loaded_model;
      if (loadedName) loadedName.textContent = stateData.loaded_model;
      const ramMb = stateData.loaded_model_details ? stateData.loaded_model_details.runtime_size_mb : (stateData.memory_mb || 0);
      if (loadedMem) loadedMem.textContent = `Resident RAM: ${ramMb} MB`;
      if (unloadBtn) unloadBtn.style.display = 'block';
    } else {
      appState.loadedModel = '';
      if (loadedName) loadedName.textContent = 'None (Unloaded)';
      if (loadedMem) loadedMem.textContent = 'Resident RAM: 0 MB';
      if (unloadBtn) unloadBtn.style.display = 'none';
    }
    if (stateData.selected_model && select && !select.value) {
      select.value = stateData.selected_model;
    }
  }

  if (modelsData && select) {
    const modelsList = Array.isArray(modelsData) ? modelsData : (modelsData.models || []);
    const selectedModel = (stateData && stateData.selected_model) || appState.selectedModel || (modelsList[0] ? modelsList[0].name : '');
    if (modelsList.length === 0) {
      select.innerHTML = '<option value="">No models installed</option>';
    } else {
      select.innerHTML = modelsList.map(m => `
        <option value="${m.name}" ${m.name === selectedModel ? 'selected' : ''}>${m.name} (${m.size_display || formatBytes(m.size_bytes || m.size || 0)})</option>
      `).join('');
      appState.selectedModel = selectedModel;
    }
  }
}

async function handleToggleAiEngine() {
  const badge = document.getElementById('aiEngineStatusBadge');
  const btn = document.getElementById('aiEngineToggleBtn');
  const label = document.getElementById('aiEngineToggleLabel');
  const detail = document.getElementById('aiEngineDetailText');

  const isRunning = badge && badge.textContent === 'RUNNING';
  const targetAction = isRunning ? 'stop' : 'start';
  const targetUrl = isRunning ? '/api/ai/stop' : '/api/ai/start';

  try {
    if (btn) btn.disabled = true;
    if (label) label.textContent = isRunning ? 'STOPPING...' : 'STARTING...';
    if (detail) detail.textContent = isRunning ? 'Stopping AI Engine service...' : 'Starting AI Engine daemon...';
    showToast(isRunning ? 'Stopping AI Engine...' : 'Starting AI Engine...', 'info');

    const res = await apiFetch(targetUrl, { method: 'POST' });
    const data = await res.json().catch(() => ({}));

    if (res.ok) {
      showToast(data.message || (isRunning ? 'AI Engine stopped.' : 'AI Engine started.'), 'success');
    } else {
      showToast(data.message || data.error || `Failed to ${targetAction} AI Engine.`, 'error');
    }
  } catch (e) {
    showToast(`Network error attempting to ${targetAction} AI Engine.`, 'error');
  } finally {
    if (btn) btn.disabled = false;
    await loadAiState();
    pollSystemStatus();
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

// ==============================================================================
// PHOTO LIGHTBOX MODAL
// ==============================================================================

function openPhotoPreview(encodedPath, title) {
  const path = decodeURIComponent(encodedPath);
  const modal = document.getElementById('photoPreviewModal');
  const img = document.getElementById('photoPreviewImg');
  const titleEl = document.getElementById('photoPreviewTitle');
  const metaEl = document.getElementById('photoPreviewMeta');
  const dimEl = document.getElementById('photoPreviewDimensions');
  const dlBtn = document.getElementById('photoDownloadBtn');

  if (!modal || !img) return;

  const authQuery = authState.token ? `?auth=${encodeURIComponent(authState.token)}` : '';
  const inlineQuery = authState.token ? `?auth=${encodeURIComponent(authState.token)}&inline=true` : '?inline=true';
  const photoUrl = `/download/${encodeURIComponent(path)}${inlineQuery}`;
  const downloadUrl = `/download/${encodeURIComponent(path)}${authQuery}`;

  if (titleEl) titleEl.textContent = title || path.split('/').pop() || 'Photo Preview';
  if (metaEl) metaEl.textContent = `Location: /${path}`;
  if (dimEl) dimEl.textContent = 'Loading image...';
  if (dlBtn) dlBtn.href = downloadUrl;

  img.src = '';
  img.onload = () => {
    if (dimEl) dimEl.textContent = `${img.naturalWidth} × ${img.naturalHeight} px`;
  };
  img.onerror = () => {
    if (dimEl) dimEl.textContent = 'Failed to load image preview';
    showToast('Failed to load image preview.', 'error');
  };
  img.src = photoUrl;

  modal.style.display = 'flex';
  document.body.style.overflow = 'hidden';
}

function closePhotoPreview() {
  const modal = document.getElementById('photoPreviewModal');
  const img = document.getElementById('photoPreviewImg');
  if (modal) modal.style.display = 'none';
  if (img) img.src = '';
  document.body.style.overflow = '';
}

function handlePhotoModalOverlayClick(event) {
  if (event.target.id === 'photoPreviewModal' || event.target.classList.contains('photo-modal-overlay')) {
    closePhotoPreview();
  }
}

// Global escape key listener for modals
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    closePhotoPreview();
    closeMediaPlayer();
  }
});

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

async function loadDiagnosticsReport(opts = {}) {
  if (authState.role !== 'admin') return;

  const container = document.getElementById('diagFindingsContainer');
  const countLabel = document.getElementById('diagFindingsCount');

  // Render cached report immediately if present
  if (appData.diagnostics.data && !opts.isPreload) {
    renderDiagnosticsReportUI(appData.diagnostics.data);
  } else if (!opts.isPreload && container && !container.children.length) {
    container.innerHTML = '<div class="font-data-sm" style="color: var(--on-surface-muted); padding: 16px;">Running diagnostic probes...</div>';
  }

  const now = Date.now();
  if (appData.diagnostics.data && (now - appData.diagnostics.loadedAt < appData.diagnostics.ttl) && !opts.force && !opts.isPreload) {
    return appData.diagnostics.data;
  }

  try {
    const [fullRes, sysRes] = await Promise.allSettled([
      fetchJsonCached('/api/admin/diagnostics/full-report', { timeoutMs: 10000 }),
      fetchJsonCached('/api/admin/diagnostics/system', { timeoutMs: 10000 })
    ]);

    let findings = [];
    let processes = [];
    let rag = null;

    if (fullRes.status === 'fulfilled') {
      const fullData = fullRes.value;
      findings = fullData.findings || [];
      processes = fullData.processes || [];
      rag = fullData.rag || fullData.diagnostics?.rag;
    }

    if (sysRes.status === 'fulfilled') {
      const sysData = sysRes.value;
      if (!processes.length && sysData.top_processes) {
        processes = sysData.top_processes;
      }
      if (!rag && sysData.rag) {
        rag = sysData.rag;
      }
    }

    const diagData = { findings, processes, rag };
    appData.diagnostics.data = diagData;
    appData.diagnostics.loadedAt = Date.now();
    appData.diagnostics.error = null;

    if (!opts.isPreload) {
      renderDiagnosticsReportUI(diagData);
    }
    return diagData;
  } catch (e) {
    console.error('Failed to load diagnostics report:', e);
    if (appData.diagnostics.data) {
      showToast('Diagnostics background refresh failed.', 'warning');
    } else if (!opts.isPreload) {
      if (countLabel) countLabel.textContent = 'ERROR';
      if (container) {
        container.innerHTML = `<div class="font-data-sm" style="color: var(--status-critical); padding: 16px;">Diagnostics unavailable: ${escapeHtml(e.message || 'Request failed')}</div>`;
      }
    }
  }
}

function renderDiagnosticsReportUI(diagData) {
  if (!diagData) return;
  renderDiagnosticFindings(diagData.findings || []);
  renderDiagnosticsProcesses(diagData.processes || []);

  // Update RAG stats
  const docCount = document.getElementById('ragDocCount');
  const idxSize = document.getElementById('ragIndexSize');
  const walSize = document.getElementById('ragWalSize');
  const rag = diagData.rag;
  if (rag) {
    const docs = rag.document_count ?? rag.doc_count ?? 0;
    const idxKb = rag.database_size_kb ?? Math.round((rag.index_bytes || 0) / 1024);
    const walKb = rag.wal_size_kb ?? Math.round((rag.wal_bytes || 0) / 1024);
    if (docCount) docCount.textContent = docs;
    if (idxSize) idxSize.textContent = `${idxKb} KB`;
    if (walSize) walSize.textContent = `${walKb} KB`;
  } else {
    if (docCount) docCount.textContent = '0';
    if (idxSize) idxSize.textContent = '0 KB';
    if (walSize) walSize.textContent = '0 KB';
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

async function loadSettings(opts = {}) {
  if (appData.settings.data && !opts.isPreload) {
    populateSettingsForm(appData.settings.data);
  }

  const now = Date.now();
  if (appData.settings.data && (now - appData.settings.loadedAt < appData.settings.ttl) && !opts.force && !opts.isPreload) {
    return appData.settings.data;
  }

  try {
    const data = await fetchJsonCached('/api/settings', { timeoutMs: 6000 });
    appData.settings.data = data;
    appData.settings.loadedAt = Date.now();
    appData.settings.error = null;

    if (!opts.isPreload) {
      populateSettingsForm(data);
    }
    return data;
  } catch (e) {
    appData.settings.error = e;
  }
}

function populateSettingsForm(data) {
  if (!data) return;
  const host = document.getElementById('settingHostname');
  const port = document.getElementById('settingPort');
  const ramP = document.getElementById('settingRamPressure');
  const ramC = document.getElementById('settingRamCritical');
  if (host && data.hostname) host.value = data.hostname;
  if (port && data.port) port.value = data.port;
  if (ramP && data.ram_pressure_threshold) ramP.value = data.ram_pressure_threshold;
  if (ramC && data.ram_critical_threshold) ramC.value = data.ram_critical_threshold;
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
      loadSettings({ force: true });
    }
  } catch (e) {
    showToast('Failed to save settings.', 'error');
  }
}

async function loadAutomationJobs(opts = {}) {
  const container = document.getElementById('automationJobsList');

  if (appData.automation.data && !opts.isPreload) {
    renderAutomationJobsUI(appData.automation.data);
  } else if (!opts.isPreload && container && !container.children.length) {
    container.innerHTML = '<div class="font-data-sm" style="color: var(--on-surface-muted); padding: 16px;">Loading scheduled jobs...</div>';
  }

  const now = Date.now();
  if (appData.automation.data && (now - appData.automation.loadedAt < appData.automation.ttl) && !opts.force && !opts.isPreload) {
    return appData.automation.data;
  }

  try {
    const data = await fetchJsonCached('/api/automation/jobs', { timeoutMs: 6000 });
    const jobs = Array.isArray(data) ? data : (data.jobs || []);
    appData.automation.data = jobs;
    appData.automation.loadedAt = Date.now();
    appData.automation.error = null;

    if (!opts.isPreload) {
      renderAutomationJobsUI(jobs);
      loadTimetableSyncStatus();
    }
    return jobs;

  } catch (e) {
    console.error('Failed to load automation jobs:', e);
    if (appData.automation.data) {
      showToast('Automation jobs refresh failed.', 'warning');
    } else if (!opts.isPreload && container) {
      container.innerHTML = `<div class="font-data-sm" style="color: var(--status-critical); padding: 16px;">Automation load error: ${escapeHtml(e.message || 'Request failed')}</div>`;
    }
  }
}

function renderAutomationJobsUI(jobs) {
  const container = document.getElementById('automationJobsList');
  if (!container) return;
  if (!jobs || jobs.length === 0) {
    container.innerHTML = '<div class="font-data-sm" style="color: var(--on-surface-muted); padding: 16px;">No automation tasks scheduled.</div>';
    return;
  }
  container.innerHTML = jobs.map(j => `
    <div class="service-row">
      <div>
        <div class="service-name">${escapeHtml(j.name || j.id)}</div>
        <div class="service-detail">${escapeHtml(j.schedule || `Interval: ${j.interval_seconds}s`)} • Last run: ${j.last_run || 'Never'}</div>
      </div>
      <button class="btn btn-primary" style="padding: 2px 8px; font-size: 11px; min-height: 28px;" onclick="runAutomationJob('${j.id}')">Run Now</button>
    </div>
  `).join('');
}

async function runAutomationJob(jobId) {
  try {
    showToast(`Triggering job ${jobId}...`, 'info');
    const res = await apiFetch(`/api/automation/jobs/${jobId}/run`, { method: 'POST' });
    if (res.ok) {
      showToast('Job executed.', 'success');
      loadAutomationJobs({ force: true });
    }
  } catch (e) {
    showToast('Job execution failed.', 'error');
  }
}

// --- Timetable & Google Calendar Synchronization ---

async function loadTimetableSyncStatus() {
  try {
    const res = await apiFetch('/api/maintenance/timetable/status');
    if (!res.ok) return;
    const data = await res.json();
    renderTimetableSyncStatus(data);
  } catch (e) {
    console.error('Failed to load timetable sync status:', e);
  }
}

function renderTimetableSyncStatus(status) {
  const statusEl = document.getElementById('timetableGoogleStatus');
  const emailEl = document.getElementById('timetableConnectedEmail');
  const calEl = document.getElementById('timetableCalendarName');
  const nextEl = document.getElementById('timetableNextSync');
  const resultEl = document.getElementById('timetableLastSyncResult');
  const timeEl = document.getElementById('timetableLastSyncTime');
  const btnConnect = document.getElementById('btnGoogleConnect');
  const btnDisconnect = document.getElementById('btnGoogleDisconnect');

  if (!statusEl) return;

  if (status.google_connected) {
    statusEl.innerHTML = '<span style="color: var(--status-healthy, #00daf3);">● Connected</span>';
    emailEl.textContent = status.connected_email || 'Google Account Linked';
    if (btnConnect) btnConnect.style.display = 'none';
    if (btnDisconnect) btnDisconnect.style.display = '';
  } else {
    statusEl.innerHTML = '<span style="color: var(--on-surface-muted, #888);">○ Not Connected</span>';
    emailEl.textContent = 'Authorize to enable sync';
    if (btnConnect) btnConnect.style.display = '';
    if (btnDisconnect) btnDisconnect.style.display = 'none';
  }

  if (calEl) {
    calEl.textContent = status.calendar_id || 'primary';
  }

  if (nextEl) {
    if (status.next_scheduled_run) {
      const nextDate = new Date(status.next_scheduled_run * 1000);
      nextEl.textContent = `Next sync: ${nextDate.toLocaleTimeString()}`;
    } else {
      nextEl.textContent = 'Scheduled: Every 3 hours';
    }
  }

  if (status.last_sync) {
    const ls = status.last_sync;
    const lsDate = new Date(ls.timestamp * 1000);
    if (resultEl) {
      resultEl.textContent = `${(ls.status || '').toUpperCase()} (${ls.created} created, ${ls.updated} updated, ${ls.unchanged} unchanged)`;
    }
    if (timeEl) {
      timeEl.textContent = lsDate.toLocaleString();
    }
  } else {
    if (resultEl) resultEl.textContent = 'No sync history recorded';
    if (timeEl) timeEl.textContent = 'Never';
  }
}

async function connectGoogleCalendar() {
  try {
    const res = await apiFetch('/api/auth/google/authorize');
    if (!res.ok) {
      const err = await res.json();
      showToast(err.message || err.error || 'Failed to initiate Google OAuth.', 'error');
      return;
    }
    const data = await res.json();
    if (data.authorization_url) {
      window.location.href = data.authorization_url;
    }
  } catch (e) {
    showToast('Failed to connect Google Calendar: ' + e.message, 'error');
  }
}

async function disconnectGoogleCalendar() {
  if (!confirm('Disconnect Google Calendar? Scheduled synchronization will be paused.')) return;
  try {
    const res = await apiFetch('/api/auth/google/disconnect', { method: 'POST' });
    if (res.ok) {
      showToast('Google Calendar disconnected.', 'success');
      loadTimetableSyncStatus();
    } else {
      showToast('Failed to disconnect Google Calendar.', 'error');
    }
  } catch (e) {
    showToast('Failed to disconnect: ' + e.message, 'error');
  }
}

async function triggerManualTimetableSync() {
  const btn = document.getElementById('btnTimetableSyncNow');
  if (btn) btn.disabled = true;
  showToast('Starting timetable synchronization...', 'info');

  try {
    const res = await apiFetch('/api/maintenance/timetable/sync', { method: 'POST' });
    const data = await res.json();
    if (res.ok) {
      if (data.status === 'locked') {
        showToast('Sync in progress by another task. Please wait.', 'warning');
      } else if (data.status === 'empty') {
        showToast(data.message || 'No timetable sessions found. Upload timetable first.', 'warning');
      } else {
        showToast(`Sync complete! Created: ${data.created}, Updated: ${data.updated}, Unchanged: ${data.unchanged}`, 'success');
      }
      loadTimetableSyncStatus();
    } else {
      showToast(data.error || 'Timetable sync failed.', 'error');
    }
  } catch (e) {
    showToast('Timetable sync error: ' + e.message, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function handleTimetableFileUpload(event) {
  const file = event.target.files && event.target.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append('timetable_file', file);

  showToast('Uploading UPES timetable JSON...', 'info');
  try {
    const res = await fetch('/api/maintenance/timetable/upload', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${sessionToken || ''}`
      },
      body: formData
    });
    const data = await res.json();
    if (res.ok) {
      showToast(`Timetable uploaded: ${data.sessions_count} sessions parsed!`, 'success');
      loadTimetableSyncStatus();
    } else {
      showToast(data.error || 'Upload failed.', 'error');
    }
  } catch (e) {
    showToast('Upload error: ' + e.message, 'error');
  } finally {
    event.target.value = '';
  }
}

async function loadBackupsList(opts = {}) {

  const tbody = document.getElementById('backupsTableBody');

  if (appData.backups.data && !opts.isPreload) {
    renderBackupsListUI(appData.backups.data);
  } else if (!opts.isPreload && tbody && !tbody.children.length) {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--on-surface-muted); padding: 16px;">Loading backups...</td></tr>';
  }

  const now = Date.now();
  if (appData.backups.data && (now - appData.backups.loadedAt < appData.backups.ttl) && !opts.force && !opts.isPreload) {
    return appData.backups.data;
  }

  try {
    const data = await fetchJsonCached('/api/backups', { timeoutMs: 6000 });
    const backups = Array.isArray(data) ? data : (data.backups || []);
    appData.backups.data = backups;
    appData.backups.loadedAt = Date.now();
    appData.backups.error = null;

    if (!opts.isPreload) {
      renderBackupsListUI(backups);
    }
    return backups;
  } catch (e) {
    console.error('Failed to load backups list:', e);
    if (appData.backups.data) {
      showToast('Backups refresh failed.', 'warning');
    } else if (!opts.isPreload && tbody) {
      tbody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--status-critical); padding: 16px;">Backup load error: ${escapeHtml(e.message || 'Request failed')}</td></tr>`;
    }
  }
}

function renderBackupsListUI(backups) {
  const tbody = document.getElementById('backupsTableBody');
  if (!tbody) return;
  if (!backups || backups.length === 0) {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--on-surface-muted); padding: 16px;">No backup archives generated yet.</td></tr>';
    return;
  }
  tbody.innerHTML = backups.map(b => `
    <tr>
      <td style="color: var(--on-surface-bright); font-weight: 500;">${escapeHtml(b.filename || b.name || 'backup.tar.gz')}</td>
      <td class="font-data-sm">${formatBytes(b.size || b.size_bytes || 0)}</td>
      <td class="font-data-sm">${b.created || b.created_at || '--'}</td>
      <td style="text-align: right;">
        <a class="btn btn-primary" style="padding: 2px 8px; font-size: 10px; min-height: 24px;" href="/download/${encodeURIComponent(b.filename || b.name)}" download>Download</a>
      </td>
    </tr>
  `).join('');
}

async function handleCreateBackup() {
  try {
    showToast('Generating system backup...', 'info');
    const res = await apiFetch('/api/backups/create', { method: 'POST' });
    if (res.ok) {
      showToast('Backup archive created.', 'success');
      loadBackupsList({ force: true });
    }
  } catch (e) {
    showToast('Backup creation failed.', 'error');
  }
}

async function loadStorageIntel(opts = {}) {
  const container = document.getElementById('storageIntelBreakdown');

  if (appData.storageIntel.data && !opts.isPreload) {
    renderStorageIntelUI(appData.storageIntel.data);
  } else if (!opts.isPreload && container && !container.children.length) {
    container.innerHTML = '<div class="font-data-sm" style="color: var(--on-surface-muted); padding: 16px;">Analyzing storage...</div>';
  }

  const now = Date.now();
  if (appData.storageIntel.data && (now - appData.storageIntel.loadedAt < appData.storageIntel.ttl) && !opts.force && !opts.isPreload) {
    return appData.storageIntel.data;
  }

  try {
    const data = await fetchJsonCached('/api/system/storage-intel', { timeoutMs: 6000 });
    let breakdown = [];
    if (Array.isArray(data.breakdown)) {
      breakdown = data.breakdown;
    } else if (typeof data.breakdown === 'object') {
      const d = data.breakdown;
      breakdown = [
        { directory: 'Videos Vault', size_bytes: d.videos_bytes || 0, file_count: d.videos_count },
        { directory: 'Music & Audio', size_bytes: d.music_bytes || 0, file_count: d.music_count },
        { directory: 'AI Models Store', size_bytes: d.models_bytes || 0, file_count: d.models_count },
        { directory: 'Temporary Staging', size_bytes: d.temp_bytes || 0, file_count: d.temp_count },
        { directory: 'Documents & Vault', size_bytes: d.vault_bytes || 0, file_count: d.vault_count }
      ];
    }
    appData.storageIntel.data = breakdown;
    appData.storageIntel.loadedAt = Date.now();
    appData.storageIntel.error = null;

    if (!opts.isPreload) {
      renderStorageIntelUI(breakdown);
    }
    return breakdown;
  } catch (e) {
    console.error('Failed to load storage intel:', e);
    if (appData.storageIntel.data) {
      showToast('Storage breakdown refresh failed.', 'warning');
    } else if (!opts.isPreload && container) {
      container.innerHTML = `<div class="font-data-sm" style="color: var(--status-critical); padding: 16px;">Storage intel error: ${escapeHtml(e.message || 'Request failed')}</div>`;
    }
  }
}

function renderStorageIntelUI(breakdown) {
  const container = document.getElementById('storageIntelBreakdown');
  if (!container || !breakdown) return;
  container.innerHTML = breakdown.map(b => `
    <div class="service-row">
      <div>
        <div class="service-name">${escapeHtml(b.directory || 'Vault')}</div>
        <div class="service-detail">${b.file_count ? `${b.file_count} objects` : 'Managed storage partition'}</div>
      </div>
      <span class="font-data-md" style="color: var(--primary);">${formatBytes(b.size_bytes || 0)}</span>
    </div>
  `).join('');
}

async function loadEventsArchive(opts = {}) {
  const container = document.getElementById('fullEventLogContainer');

  if (appData.events.data && !opts.isPreload) {
    renderEventsArchiveUI(appData.events.data);
  } else if (!opts.isPreload && container && !container.children.length) {
    container.innerHTML = '<div class="log-entry" style="color: var(--on-surface-muted);">Loading audit events...</div>';
  }

  const now = Date.now();
  if (appData.events.data && (now - appData.events.loadedAt < appData.events.ttl) && !opts.force && !opts.isPreload) {
    return appData.events.data;
  }

  try {
    const data = await fetchJsonCached('/api/events', { timeoutMs: 6000 });
    const events = Array.isArray(data) ? data : (data.events || []);
    appData.events.data = events;
    appData.events.loadedAt = Date.now();
    appData.events.error = null;

    if (!opts.isPreload) {
      renderEventsArchiveUI(events);
    }
    return events;
  } catch (e) {
    console.error('Failed to load events archive:', e);
    if (appData.events.data) {
      showToast('Events archive refresh failed.', 'warning');
    } else if (!opts.isPreload && container) {
      container.innerHTML = `<div class="log-entry" style="color: var(--status-critical);">Event load error: ${escapeHtml(e.message || 'Request failed')}</div>`;
    }
  }
}

function renderEventsArchiveUI(events) {
  const container = document.getElementById('fullEventLogContainer');
  if (!container) return;
  if (!events || events.length === 0) {
    container.innerHTML = '<div class="log-entry" style="color: var(--on-surface-muted);">No audit log events recorded yet.</div>';
    return;
  }
  container.innerHTML = events.map(ev => {
    const ts = ev.timestamp ? ev.timestamp.substring(11, 19) : (ev.date ? ev.date : '--');
    const lvl = (ev.level || 'INFO').toUpperCase();
    return `
        <div class="log-entry">
        <span class="log-time">[${ts}]</span>
        <span class="log-level ${lvl}">${lvl}</span>
        <span class="log-msg">${escapeHtml(ev.message || '')}</span>
      </div>
    `;
  }).join('');
}

let privilegesRegistryCache = null;

async function loadPrivilegesRegistry() {
  if (privilegesRegistryCache) return privilegesRegistryCache;
  try {
    const res = await apiFetch('/api/admin/privileges');
    if (!res.ok) return null;
    const data = await res.json();
    privilegesRegistryCache = data;
    return data;
  } catch (e) {
    console.error('Failed to fetch privileges registry:', e);
    return null;
  }
}

async function loadAdminUsers(opts = {}) {
  if (authState.role !== 'admin') return;
  const tbody = document.getElementById('adminUserTableBody');

  if (appData.users.data && !opts.isPreload) {
    renderAdminUsersUI(appData.users.data);
  } else if (!opts.isPreload && tbody && !tbody.children.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--on-surface-muted); padding: 16px;">Loading users...</td></tr>';
  }

  const now = Date.now();
  if (appData.users.data && (now - appData.users.loadedAt < appData.users.ttl) && !opts.force && !opts.isPreload) {
    return appData.users.data;
  }

  try {
    const data = await fetchJsonCached('/api/admin/users', { timeoutMs: 6000 });
    const users = Array.isArray(data) ? data : (data.users || []);
    appData.users.data = users;
    appData.users.loadedAt = Date.now();
    appData.users.error = null;

    if (!opts.isPreload) {
      renderAdminUsersUI(users);
    }
    return users;
  } catch (e) {
    console.error('Failed to load admin users:', e);
    if (appData.users.data) {
      showToast('Users list refresh failed.', 'warning');
    } else if (!opts.isPreload && tbody) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--status-critical); padding: 16px;">User load error: ${escapeHtml(e.message || 'Request failed')}</td></tr>`;
    }
  }
}

function filterAdminUsersTable() {
  const q = (document.getElementById('adminUserSearchInput')?.value || '').toLowerCase().trim();
  if (!appData.users.data) return;
  if (!q) {
    renderAdminUsersUI(appData.users.data);
    return;
  }
  const filtered = appData.users.data.filter(u => {
    const name = (u.user_id || u.username || '').toLowerCase();
    const role = (u.role || '').toLowerCase();
    return name.includes(q) || role.includes(q);
  });
  renderAdminUsersUI(filtered);
}

function renderAdminUsersUI(users) {
  const tbody = document.getElementById('adminUserTableBody');
  if (!tbody) return;

  if (!users || !users.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--on-surface-muted); padding: 16px;">No users registered.</td></tr>';
    return;
  }

  tbody.innerHTML = users.map(u => {
    const uname = u.user_id || u.username || 'unknown';
    const role = (u.role || 'user').toUpperCase();
    const isDisabled = Boolean(u.is_disabled);
    const isPrimaryAdmin = (uname === 'admin');
    const privCount = u.privileges ? Object.values(u.privileges).filter(Boolean).length : 0;
    const createdStr = formatTimestamp(u.created_at || Date.now());

    return `
      <tr>
        <td style="font-weight: 500; font-family: 'JetBrains Mono', monospace;">${escapeHtml(uname)}</td>
        <td>
          <span class="badge ${role === 'ADMIN' ? 'badge-primary' : 'badge-neutral'}">${escapeHtml(role)}</span>
        </td>
        <td>
          <span class="badge ${isDisabled ? 'badge-critical' : 'badge-healthy'}">
            ${isDisabled ? 'DISABLED' : 'ACTIVE'}
          </span>
        </td>
        <td style="font-size: 11px; color: var(--on-surface-muted);">
          ${privCount} granted
        </td>
        <td style="font-size: 11px; color: var(--on-surface-muted);">${createdStr}</td>
        <td style="text-align: right;">
          <div style="display: inline-flex; gap: 4px; flex-wrap: nowrap;">
            <button class="btn btn-secondary" style="padding: 2px 6px; font-size: 10px; min-height: 24px;" onclick="openEditUserModal('${escapeHtml(uname)}')">Edit</button>
            <button class="btn btn-secondary" style="padding: 2px 6px; font-size: 10px; min-height: 24px;" onclick="openAdminResetPasswordModal('${escapeHtml(uname)}')">Reset Pwd</button>
            <button class="btn btn-secondary" style="padding: 2px 6px; font-size: 10px; min-height: 24px; color: ${isDisabled ? 'var(--status-healthy)' : 'var(--status-warning)'};" onclick="handleToggleUserDisabled('${escapeHtml(uname)}', ${isDisabled})">
              ${isDisabled ? 'Enable' : 'Disable'}
            </button>
            <button class="btn btn-secondary" style="padding: 2px 6px; font-size: 10px; min-height: 24px;" title="Revoke all active sessions" onclick="handleAdminRevokeUserSessions('${escapeHtml(uname)}')">Revoke</button>
            ${!isPrimaryAdmin ? `<button class="btn btn-secondary" style="padding: 2px 6px; font-size: 10px; min-height: 24px; color: var(--status-critical);" onclick="handleDeleteUser('${escapeHtml(uname)}')">Delete</button>` : ''}
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

async function populatePrivilegeCheckboxes(selectedPrivs = {}) {
  const container = document.getElementById('adminUserPrivilegesContainer');
  if (!container) return;
  const reg = await loadPrivilegesRegistry();
  if (!reg || !reg.privileges) {
    container.innerHTML = '<span class="font-data-sm" style="color: var(--on-surface-muted);">No privileges metadata loaded.</span>';
    return;
  }

  container.innerHTML = reg.privileges.map(p => {
    const isChecked = Boolean(selectedPrivs[p.key]);
    return `
      <label style="display: flex; align-items: flex-start; gap: 8px; font-size: 12px; color: var(--on-surface); cursor: pointer; padding: 4px; border-radius: var(--radius-xs); background: var(--surface-1);">
        <input type="checkbox" name="privilege_item" value="${escapeHtml(p.key)}" ${isChecked ? 'checked' : ''} style="margin-top: 2px;">
        <div>
          <div style="font-weight: 500; font-family: 'JetBrains Mono', monospace; font-size: 11px;">${escapeHtml(p.key)}</div>
          <div style="font-size: 10px; color: var(--on-surface-muted); line-height: 1.2;">${escapeHtml(p.description || '')}</div>
        </div>
      </label>
    `;
  }).join('');
}

async function openAddUserModal() {
  const modal = document.getElementById('adminUserModal');
  const title = document.getElementById('adminUserModalTitle');
  const mode = document.getElementById('adminUserMode');
  const userIdInput = document.getElementById('adminUserIdInput');
  const pwdSection = document.getElementById('adminUserPasswordSection');
  const pwdInput = document.getElementById('adminUserPasswordInput');
  const confPwdInput = document.getElementById('adminUserConfirmPasswordInput');
  const roleSelect = document.getElementById('adminUserRoleSelect');
  const disabledInput = document.getElementById('adminUserDisabledInput');

  if (!modal) return;
  if (title) title.textContent = 'Create User Account';
  if (mode) mode.value = 'create';
  if (userIdInput) { userIdInput.value = ''; userIdInput.disabled = false; }
  if (pwdSection) pwdSection.style.display = 'grid';
  if (pwdInput) { pwdInput.value = ''; pwdInput.required = true; }
  if (confPwdInput) { confPwdInput.value = ''; confPwdInput.required = true; }
  if (roleSelect) roleSelect.value = 'user';
  if (disabledInput) disabledInput.checked = false;

  const reg = await loadPrivilegesRegistry();
  const defaultPrivs = (reg && reg.defaults && reg.defaults.user) || {};
  await populatePrivilegeCheckboxes(defaultPrivs);

  modal.style.display = 'flex';
}

async function openEditUserModal(userId) {
  const modal = document.getElementById('adminUserModal');
  const title = document.getElementById('adminUserModalTitle');
  const mode = document.getElementById('adminUserMode');
  const userIdInput = document.getElementById('adminUserIdInput');
  const pwdSection = document.getElementById('adminUserPasswordSection');
  const pwdInput = document.getElementById('adminUserPasswordInput');
  const confPwdInput = document.getElementById('adminUserConfirmPasswordInput');
  const roleSelect = document.getElementById('adminUserRoleSelect');
  const disabledInput = document.getElementById('adminUserDisabledInput');

  if (!modal) return;

  let userData = (appData.users.data || []).find(u => (u.user_id || u.username) === userId);
  if (!userData) {
    try {
      const res = await apiFetch(`/api/admin/users/${encodeURIComponent(userId)}`);
      if (!res.ok) throw new Error('User fetch failed');
      const data = await res.json();
      userData = data.user || data;
    } catch (e) {
      showToast(`Failed to load user info: ${e.message}`, 'error');
      return;
    }
  }

  if (title) title.textContent = `Edit User: ${userId}`;
  if (mode) mode.value = 'edit';
  if (userIdInput) { userIdInput.value = userId; userIdInput.disabled = true; }
  if (pwdSection) pwdSection.style.display = 'none';
  if (pwdInput) { pwdInput.value = ''; pwdInput.required = false; }
  if (confPwdInput) { confPwdInput.value = ''; confPwdInput.required = false; }
  if (roleSelect) roleSelect.value = userData.role || 'user';
  if (disabledInput) disabledInput.checked = Boolean(userData.is_disabled);

  await populatePrivilegeCheckboxes(userData.privileges || {});
  modal.style.display = 'flex';
}

function closeAdminUserModal() {
  const modal = document.getElementById('adminUserModal');
  if (modal) modal.style.display = 'none';
}

function handleUserModalOverlayClick(event) {
  if (event.target && event.target.id === 'adminUserModal') {
    closeAdminUserModal();
  }
}

async function handleRoleChangeInUserModal() {
  const mode = document.getElementById('adminUserMode')?.value;
  if (mode === 'create') {
    resetModalPrivilegesToRoleDefault();
  }
}

async function resetModalPrivilegesToRoleDefault() {
  const role = document.getElementById('adminUserRoleSelect')?.value || 'user';
  const reg = await loadPrivilegesRegistry();
  const defs = (reg && reg.defaults && reg.defaults[role]) || {};
  await populatePrivilegeCheckboxes(defs);
}

async function handleSaveAdminUser(event) {
  event.preventDefault();
  const mode = document.getElementById('adminUserMode')?.value || 'create';
  const userId = (document.getElementById('adminUserIdInput')?.value || '').trim();
  const role = document.getElementById('adminUserRoleSelect')?.value || 'user';
  const isDisabled = Boolean(document.getElementById('adminUserDisabledInput')?.checked);
  const submitBtn = document.getElementById('adminUserSubmitBtn');

  if (!userId) {
    showToast('User ID is required.', 'warning');
    return;
  }

  // Collect checked privileges
  const privileges = {};
  const checkboxes = document.querySelectorAll('#adminUserPrivilegesContainer input[name="privilege_item"]');
  checkboxes.forEach(cb => {
    privileges[cb.value] = cb.checked;
  });

  if (submitBtn) submitBtn.disabled = true;

  try {
    if (mode === 'create') {
      const password = document.getElementById('adminUserPasswordInput')?.value || '';
      const confirmPassword = document.getElementById('adminUserConfirmPasswordInput')?.value || '';
      if (!password || password.length < 6) {
        showToast('Password must be at least 6 characters.', 'warning');
        if (submitBtn) submitBtn.disabled = false;
        return;
      }
      if (password !== confirmPassword) {
        showToast('Passwords do not match.', 'warning');
        if (submitBtn) submitBtn.disabled = false;
        return;
      }
      const res = await apiFetch('/api/admin/users', {
        method: 'POST',
        body: JSON.stringify({
          user_id: userId,
          password: password,
          confirm_password: confirmPassword,
          role: role,
          is_disabled: isDisabled,
          privileges: privileges
        })
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.error || errData.message || 'Failed to create user');
      }
      showToast(`User '${userId}' created successfully.`, 'success');
    } else {
      const res = await apiFetch(`/api/admin/users/${encodeURIComponent(userId)}`, {
        method: 'PATCH',
        body: JSON.stringify({
          role: role,
          is_disabled: isDisabled,
          privileges: privileges
        })
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.error || errData.message || 'Failed to update user');
      }
      showToast(`User '${userId}' updated successfully.`, 'success');
    }
    closeAdminUserModal();
    invalidateCache('/api/admin/users');
    await loadAdminUsers({ force: true });
  } catch (e) {
    showToast(`Error saving user: ${e.message}`, 'error');
  } finally {
    if (submitBtn) submitBtn.disabled = false;
  }
}

function openAdminResetPasswordModal(userId) {
  const modal = document.getElementById('adminResetPasswordModal');
  const targetId = document.getElementById('adminResetPasswordUserId');
  const targetDisplay = document.getElementById('adminResetPasswordUserDisplay');
  const newPwd = document.getElementById('adminResetNewPassword');
  const confPwd = document.getElementById('adminResetConfirmPassword');

  if (!modal) return;
  if (targetId) targetId.value = userId;
  if (targetDisplay) targetDisplay.textContent = userId;
  if (newPwd) newPwd.value = '';
  if (confPwd) confPwd.value = '';

  modal.style.display = 'flex';
}

function closeAdminResetPasswordModal() {
  const modal = document.getElementById('adminResetPasswordModal');
  if (modal) modal.style.display = 'none';
}

function handleResetPasswordModalOverlayClick(event) {
  if (event.target && event.target.id === 'adminResetPasswordModal') {
    closeAdminResetPasswordModal();
  }
}

async function handleAdminResetPasswordSubmit(event) {
  event.preventDefault();
  const userId = document.getElementById('adminResetPasswordUserId')?.value;
  const newPwd = document.getElementById('adminResetNewPassword')?.value;
  const confPwd = document.getElementById('adminResetConfirmPassword')?.value;
  const btn = document.getElementById('adminResetPasswordSubmitBtn');

  if (!userId || !newPwd) return;
  if (newPwd !== confPwd) {
    showToast('Passwords do not match.', 'warning');
    return;
  }
  if (newPwd.length < 6) {
    showToast('Password must be at least 6 characters.', 'warning');
    return;
  }

  if (btn) btn.disabled = true;
  try {
    const res = await apiFetch(`/api/admin/users/${encodeURIComponent(userId)}/password`, {
      method: 'POST',
      body: JSON.stringify({ password: newPwd })
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.error || errData.message || 'Failed to reset password');
    }
    showToast(`Password for '${userId}' reset successfully. Active sessions revoked.`, 'success');
    closeAdminResetPasswordModal();
  } catch (e) {
    showToast(`Failed to reset password: ${e.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function handleToggleUserDisabled(userId, isCurrentlyDisabled) {
  const targetState = !isCurrentlyDisabled;
  const actionLabel = targetState ? 'disable' : 'enable';
  if (!confirm(`Are you sure you want to ${actionLabel} user '${userId}'?`)) return;

  try {
    const res = await apiFetch(`/api/admin/users/${encodeURIComponent(userId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ is_disabled: targetState })
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.error || errData.message || `Failed to ${actionLabel} user`);
    }
    showToast(`User '${userId}' has been ${targetState ? 'disabled' : 'enabled'}.`, 'success');
    invalidateCache('/api/admin/users');
    await loadAdminUsers({ force: true });
  } catch (e) {
    showToast(`Failed to ${actionLabel} user: ${e.message}`, 'error');
  }
}

async function handleAdminRevokeUserSessions(userId) {
  if (!confirm(`Revoke all active sessions for user '${userId}'?`)) return;
  try {
    const res = await apiFetch(`/api/admin/users/${encodeURIComponent(userId)}/sessions/revoke`, {
      method: 'POST',
      body: JSON.stringify({})
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.error || errData.message || 'Failed to revoke sessions');
    }
    const data = await res.json().catch(() => ({}));
    showToast(`Revoked ${data.revoked_count || 0} session(s) for '${userId}'.`, 'success');
  } catch (e) {
    showToast(`Failed to revoke sessions: ${e.message}`, 'error');
  }
}

async function handleDeleteUser(userId) {
  if (!confirm(`Are you sure you want to permanently delete user '${userId}'? This cannot be undone.`)) return;
  try {
    const res = await apiFetch(`/api/admin/users/${encodeURIComponent(userId)}`, {
      method: 'DELETE'
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.error || errData.message || 'Failed to delete user');
    }
    showToast(`User '${userId}' deleted successfully.`, 'success');
    invalidateCache('/api/admin/users');
    await loadAdminUsers({ force: true });
  } catch (e) {
    showToast(`Failed to delete user: ${e.message}`, 'error');
  }
}

async function handleChangeOwnPassword(event) {
  event.preventDefault();
  const curPwd = document.getElementById('accountCurrentPassword')?.value;
  const newPwd = document.getElementById('accountNewPassword')?.value;
  const confPwd = document.getElementById('accountConfirmPassword')?.value;
  const btn = document.getElementById('savePasswordBtn');

  if (!curPwd || !newPwd) return;
  if (newPwd !== confPwd) {
    showToast('New passwords do not match.', 'warning');
    return;
  }
  if (newPwd.length < 6) {
    showToast('Password must be at least 6 characters.', 'warning');
    return;
  }

  if (btn) btn.disabled = true;
  try {
    const res = await apiFetch('/api/account/password', {
      method: 'POST',
      body: JSON.stringify({
        current_password: curPwd,
        new_password: newPwd
      })
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.error || errData.message || 'Failed to update password');
    }
    showToast('Password updated successfully. Other sessions revoked.', 'success');
    document.getElementById('accountPasswordForm')?.reset();
  } catch (e) {
    showToast(`Password update failed: ${e.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function handleRevokeOtherSessions() {
  if (!confirm('Revoke all other active sessions for your account?')) return;
  try {
    const res = await apiFetch('/api/account/sessions/revoke', {
      method: 'POST',
      body: JSON.stringify({})
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.error || errData.message || 'Failed to revoke sessions');
    }
    const data = await res.json().catch(() => ({}));
    showToast(`Revoked ${data.revoked_count || 0} other active session(s).`, 'success');
  } catch (e) {
    showToast(`Failed to revoke sessions: ${e.message}`, 'error');
  }
}

async function loadNetworkInterfaces(opts = {}) {
  const container = document.getElementById('networkInterfacesList');

  if (appData.services.data && !opts.isPreload) {
    renderNetworkInterfacesUI(appData.services.data);
  } else if (!opts.isPreload && container && !container.children.length) {
    container.innerHTML = '<div class="font-data-sm" style="color: var(--on-surface-muted); padding: 16px;">Probing network interfaces...</div>';
  }

  const now = Date.now();
  if (appData.services.data && (now - appData.services.loadedAt < appData.services.ttl) && !opts.force && !opts.isPreload) {
    return appData.services.data;
  }

  try {
    const data = await fetchJsonCached('/api/services/status', { timeoutMs: 6000 });
    appData.services.data = data;
    appData.services.loadedAt = Date.now();
    appData.services.error = null;

    if (!opts.isPreload) {
      renderNetworkInterfacesUI(data);
    }
    return data;
  } catch (e) {
    console.error('Failed to load network interfaces:', e);
    if (appData.services.data) {
      showToast('Network services refresh failed.', 'warning');
    } else if (!opts.isPreload && container) {
      container.innerHTML = `<div class="font-data-sm" style="color: var(--status-critical); padding: 16px;">Network probe error: ${escapeHtml(e.message || 'Request failed')}</div>`;
    }
  }
}

function renderNetworkInterfacesUI(data) {
  const container = document.getElementById('networkInterfacesList');
  if (!container || !data) return;

  const l2n = data.localtonet || {};
  const ssh = data.ssh || data.sshd || {};
  const nexus = data.nexusnode || {};

  const isL2nConnected = Boolean(l2n.connected || l2n.status === 'tunnel_connected' || l2n.state === 'TUNNEL_CONNECTED');
  const isSshOnline = Boolean(ssh.running || ssh.status === 'online');

  container.innerHTML = `
    <div class="service-row">
      <div>
        <div class="service-name">LocalToNet Public WAN Ingress</div>
        <div class="service-detail">${escapeHtml(l2n.url || 'No tunnel endpoint active')} • TLS Ingress Proxy</div>
      </div>
      <span class="node-badge" style="color: ${isL2nConnected ? 'var(--status-healthy)' : 'var(--status-critical)'};">${isL2nConnected ? 'CONNECTED' : 'OFFLINE'}</span>
    </div>
    <div class="service-row">
      <div>
        <div class="service-name">OpenSSH Operator Transport</div>
        <div class="service-detail">Port ${ssh.port || 8022} • Local TCP Listener</div>
      </div>
      <span class="node-badge" style="color: ${isSshOnline ? 'var(--status-healthy)' : 'var(--status-critical)'};">${isSshOnline ? 'RUNNING' : 'STOPPED'}</span>
    </div>
    <div class="service-row">
      <div>
        <div class="service-name">NexusNode Core HTTPS Listener</div>
        <div class="service-detail">Port ${nexus.port || 5000} • Dual-Frontend REST/WS Core</div>
      </div>
      <span class="node-badge" style="color: var(--status-healthy);">ACTIVE (PID ${nexus.pid || '--'})</span>
    </div>
  `;
}

// (Legacy duplicate openAddUserModal removed - authoritative implementation is at line 2511)

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

function formatTimestamp(val) {
  if (!val) return '--';
  try {
    if (typeof val === 'number') {
      const ms = val < 10000000000 ? val * 1000 : val;
      const d = new Date(ms);
      if (!isNaN(d.getTime())) return d.toISOString().substring(0, 16).replace('T', ' ');
    } else if (typeof val === 'string') {
      const trimmed = val.trim();
      if (/^\d+(\.\d+)?$/.test(trimmed)) {
        const num = parseFloat(trimmed);
        const ms = num < 10000000000 ? num * 1000 : num;
        const d = new Date(ms);
        if (!isNaN(d.getTime())) return d.toISOString().substring(0, 16).replace('T', ' ');
      }
      const d = new Date(trimmed);
      if (!isNaN(d.getTime())) return d.toISOString().substring(0, 16).replace('T', ' ');
      return trimmed.substring(0, 16).replace('T', ' ');
    }
  } catch (e) {}
  return '--';
}

// ==============================================================================
// 12. INITIALIZATION ON DOM READY
// ==============================================================================
// 13. ATTENDANCE TRACKING & 75% BUNK PLANNER DATA SHEET (AUTHORITATIVE ENGINE)
// ==============================================================================

let attendanceState = {
  data: null,
  loading: false
};

async function loadAttendanceData() {
  if (attendanceState.loading) return;
  attendanceState.loading = true;
  
  try {
    const res = await apiRequest('/api/attendance/summary');
    if (res && res.overall) {
      attendanceState.data = res;
      renderAttendanceMetrics(res);
      renderTodayClasses(res.today_classes || []);
      renderAttendanceSubjectsTable(res.subjects || []);
      renderAttendancePunchesTable(res.recent_sessions || res.recent_punches || []);
    } else {
      showToast('No attendance data available. Click Sync with UPES.', 'warning');
    }
  } catch (err) {
    console.error('Failed to load attendance analytics:', err);
    showToast('Failed to load attendance data.', 'error');
  } finally {
    attendanceState.loading = false;
  }
}

async function triggerAttendanceSync() {
  const btn = document.getElementById('btnSyncAttendance');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span class="material-symbols-outlined spin" style="font-size: 16px;">sync</span><span>Syncing...</span>`;
  }
  showToast('Connecting to UPES Attendance microservices...', 'info');
  try {
    const res = await apiRequest('/api/attendance/sync', 'POST');
    if (res && (res.status === 'ACTIVE' || res.status === 'PARTIAL')) {
      showToast(res.message || 'Official attendance synchronized successfully!', 'success');
      loadAttendanceData();
    } else if (res && res.status === 'AUTH_REQUIRED') {
      showToast('UPES login required in browser. Please open portal tab.', 'warning');
    } else {
      showToast(res.message || res.error || 'Attendance sync failed.', 'error');
    }
  } catch (err) {
    console.error('Attendance sync error:', err);
    showToast('Failed to trigger attendance sync.', 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<span class="material-symbols-outlined" style="font-size: 16px;">cloud_sync</span><span>Sync with UPES</span>`;
    }
  }
}

function renderAttendanceMetrics(data) {
  const overall = data.overall || {};
  const pct = overall.attendance_percentage !== undefined ? overall.attendance_percentage : 0;
  
  const pctEl = document.getElementById('attOverallPct');
  if (pctEl) {
    pctEl.textContent = `${pct}%`;
    pctEl.style.color = pct >= 80 ? 'var(--primary)' : (pct >= 75 ? '#f59e0b' : '#ef4444');
  }
  
  const badgeEl = document.getElementById('attOverallBadge');
  if (badgeEl) {
    if (pct >= 80) {
      badgeEl.className = 'status-pill status-healthy';
      badgeEl.textContent = 'Safe (≥80%)';
    } else if (pct >= 75) {
      badgeEl.className = 'status-pill status-warning';
      badgeEl.textContent = 'Warning (75-80%)';
    } else {
      badgeEl.className = 'status-pill status-critical';
      badgeEl.textContent = 'Critical (<75%)';
    }
  }
  
  const countEl = document.getElementById('attOverallCount');
  if (countEl) {
    countEl.textContent = `${overall.attended_classes || 0} / ${overall.conducted_classes || 0} classes attended (${overall.missed_classes || 0} missed)`;
  }
  
  const bunksEl = document.getElementById('attSafeBunksTotal');
  if (bunksEl) {
    bunksEl.textContent = overall.total_safe_bunks !== undefined ? overall.total_safe_bunks : '--';
  }
  
  const slotsEl = document.getElementById('attSemesterTotalSlots');
  if (slotsEl) {
    slotsEl.textContent = overall.conducted_classes || 0;
  }
  
  const condEl = document.getElementById('attConductedVsRemaining');
  if (condEl) {
    condEl.textContent = `${overall.attended_classes || 0} attended · ${overall.missed_classes || 0} missed`;
  }
  
  const todayClasses = data.today_classes || [];
  const todayPunched = todayClasses.filter(c => c.is_punched || (c.punched && c.punch_status === 'present')).length;
  const todayCountEl = document.getElementById('attTodayCount');
  if (todayCountEl) {
    todayCountEl.textContent = `${todayPunched} / ${todayClasses.length}`;
  }
  
  const todayLabelEl = document.getElementById('attTodayDateLabel');
  if (todayLabelEl) {
    todayLabelEl.textContent = `Today: ${data.as_of_date || ''} (${todayClasses.length} sessions)`;
  }
}

function renderTodayClasses(classes) {
  const container = document.getElementById('todayClassesContainer');
  if (!container) return;
  
  if (!classes || classes.length === 0) {
    container.innerHTML = `<div style="color: var(--text-muted); font-size: 13px; padding: 12px; grid-column: 1 / -1; text-align: center;">No sessions scheduled for today (${new Date().toLocaleDateString()}). Enjoy your day! 🎉</div>`;
    return;
  }
  
  container.innerHTML = classes.map(c => {
    const isPresent = c.attendance_status === 'PRESENT' || c.punch_status === 'present';
    const isAbsent = c.attendance_status === 'ABSENT';
    const isPunched = bool(c.is_punched || c.punch_in_time);
    const punchTime = c.punch_in_time || c.punch_time || '';
    const roomText = c.room || 'Classroom';
    
    let statusPill = `<span class="status-pill status-healthy" style="font-size: 10px;">✓ PRESENT (Punched ${escapeHtml(punchTime || 'on-time')})</span>`;
    if (isAbsent) {
      statusPill = `<span class="status-pill status-critical" style="font-size: 10px;">✗ ABSENT</span>`;
    } else if (!isPresent) {
      statusPill = `<span style="font-size: 11px; color: var(--text-muted);">SCHEDULED</span>`;
    }

    return `
      <div style="background: var(--bg-surface-secondary); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; display: flex; flex-direction: column; justify-content: space-between;">
        <div>
          <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 6px;">
            <span style="font-size: 11px; font-weight: 700; color: var(--primary); background: rgba(59,130,246,0.1); padding: 2px 6px; border-radius: 4px;">
              ${escapeHtml(c.course_code || 'MODULE')}
            </span>
            <span style="font-size: 11px; color: var(--text-muted);">
              ${escapeHtml((c.start_time || '').substring(0, 5))} - ${escapeHtml((c.end_time || '').substring(0, 5))}
            </span>
          </div>
          <div style="font-weight: 600; font-size: 13px; color: var(--text-primary); margin-bottom: 4px;">
            ${escapeHtml(c.course_name)}
          </div>
          <div style="font-size: 11px; color: var(--text-secondary);">
            📍 ${escapeHtml(roomText)} · 👤 ${escapeHtml(c.faculty || 'Faculty')}
          </div>
        </div>
        
        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 12px; padding-top: 8px; border-top: 1px solid var(--border-subtle);">
          <div>
            ${statusPill}
          </div>
          <div>
            <span style="font-size: 10px; color: var(--text-muted); font-family: var(--font-mono);">
              ${c.attendance_subtype ? escapeHtml(c.attendance_subtype) : 'CRA'}
            </span>
          </div>
        </div>
      </div>
    `;
  }).join('');
}

function renderAttendanceSubjectsTable(subjects) {
  const tbody = document.getElementById('attendanceSubjectsTbody');
  if (!tbody) return;
  
  if (!subjects || subjects.length === 0) {
    tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--text-muted);">No subjects found in official UPES attendance. Click "Sync with UPES" to refresh.</td></tr>`;
    return;
  }
  
  tbody.innerHTML = subjects.map(s => {
    const pct = s.attendance_percentage !== undefined ? s.attendance_percentage : 100;
    let badgeClass = 'status-healthy';
    let adviceHtml = '';
    
    if (pct < 75) {
      badgeClass = 'status-critical';
      adviceHtml = `<span style="color: #ef4444; font-weight: 600; font-size: 11px;">⚠️ Attend next ${s.recovery_classes_required || 1} classes</span>`;
    } else if (pct < 80) {
      badgeClass = 'status-warning';
      adviceHtml = `<span style="color: #f59e0b; font-size: 11px;">⚠️ Borderline (Can skip ${s.safe_bunks_remaining})</span>`;
    } else {
      badgeClass = 'status-healthy';
      adviceHtml = `<span style="color: #10b981; font-size: 11px;">✓ Safe (Can skip ${s.safe_bunks_remaining})</span>`;
    }

    let projHtml = '<span style="color: var(--text-muted); font-size: 11px;">No upcoming slots</span>';
    if (s.next_session) {
      const n = s.next_session;
      projHtml = `
        <div style="font-size: 11px; color: var(--text-primary);">
          📅 ${escapeHtml(n.date)} (${escapeHtml((n.start_time || '').substring(0, 5))})
        </div>
        <div style="font-size: 10px; color: var(--text-muted); margin-top: 2px;">
          Attend: <strong style="color: #10b981;">${n.projected_pct_if_attended}%</strong> · Skip: <strong style="color: #ef4444;">${n.projected_pct_if_skipped}%</strong>
        </div>
      `;
    }
    
    return `
      <tr>
        <td>
          <div style="font-weight: 600; color: var(--text-primary); font-size: 13px;">${escapeHtml(s.course_name)}</div>
          <div style="font-size: 11px; color: var(--text-muted); font-family: var(--font-mono);">ID: ${s.module_id || '--'}</div>
        </td>
        <td>
          <span style="color: var(--text-primary); font-weight: 600;">${s.conducted_classes}</span>
          <span style="color: var(--text-muted); font-size: 11px;"> conducted</span>
        </td>
        <td>
          <span style="color: #10b981; font-weight: 600;">${s.attended_classes}</span>
          <span style="color: #ef4444; font-size: 11px;"> / ${s.absent_classes || 0} absent</span>
        </td>
        <td>
          <div style="display: flex; align-items: center; gap: 8px;">
            <span class="status-pill ${badgeClass}" style="font-weight: 700; font-size: 12px;">${pct}%</span>
          </div>
          <div style="background: rgba(255,255,255,0.08); height: 4px; border-radius: 2px; margin-top: 4px; overflow: hidden; width: 60px;">
            <div style="background: ${pct >= 75 ? '#10b981' : '#ef4444'}; width: ${Math.min(100, pct)}%; height: 100%;"></div>
          </div>
        </td>
        <td>
          <div style="font-weight: 700; font-size: 14px; color: ${s.safe_bunks_remaining > 0 ? '#10b981' : '#ef4444'};">
            ${s.safe_bunks_remaining} <span style="font-size: 11px; font-weight: 400; color: var(--text-muted);">classes</span>
          </div>
          <div style="font-size: 10px; color: var(--text-muted);">${adviceHtml}</div>
        </td>
        <td>
          ${projHtml}
        </td>
      </tr>
    `;
  }).join('');
}

function renderAttendancePunchesTable(sessions) {
  const tbody = document.getElementById('attendancePunchesTbody');
  if (!tbody) return;
  
  if (!sessions || sessions.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted);">No official session records logged yet. Click "Sync with UPES" to load ledger.</td></tr>`;
    return;
  }
  
  tbody.innerHTML = sessions.map(s => {
    const isPresent = (s.attendance_status === 'PRESENT' || s.status === 'present');
    const isAbsent = (s.attendance_status === 'ABSENT' || s.status === 'absent');
    const isCondoned = (s.attendance_status === 'CONDONED');

    let statusBadge = `<span class="status-pill status-healthy" style="font-size: 11px;">PRESENT</span>`;
    if (isAbsent) {
      statusBadge = `<span class="status-pill status-critical" style="font-size: 11px;">ABSENT</span>`;
    } else if (isCondoned) {
      statusBadge = `<span class="status-pill status-warning" style="font-size: 11px;">CONDONED</span>`;
    }

    const punchIn = s.punch_in_time || s.punch_time || '—';
    const subType = s.attendance_subtype || s.sub_type_code || (s.status ? 'MANUAL' : 'CRA');
    const subDesc = s.subtype_desc || (subType === 'CRA' ? 'Classroom RFID' : (subType === 'OA' ? 'Online' : subType));

    return `
      <tr>
        <td>
          <div style="font-weight: 600;">${escapeHtml(s.session_date || s.punch_date || '')}</div>
          <div style="font-size: 11px; color: var(--text-muted);">${escapeHtml(s.start_time ? `${s.start_time} - ${s.end_time}` : '')}</div>
        </td>
        <td style="font-family: var(--font-mono); font-size: 12px; color: var(--primary); font-weight: 600;">
          ${escapeHtml(punchIn)}
        </td>
        <td>
          <div style="font-weight: 600;">${escapeHtml(s.course_name)}</div>
          <div style="font-size: 10px; color: var(--text-muted); font-family: var(--font-mono);">${s.session_id ? `Session #${s.session_id}` : ''}</div>
        </td>
        <td>
          <div style="font-size: 12px;">📍 ${escapeHtml(s.room || 'Classroom')}</div>
          <div style="font-size: 11px; color: var(--text-muted);">👤 ${escapeHtml(s.faculty || '--')}</div>
        </td>
        <td>
          ${statusBadge}
        </td>
        <td>
          <span style="font-size: 11px; font-weight: 600; color: var(--text-secondary);">${escapeHtml(subType)}</span>
          <div style="font-size: 10px; color: var(--text-muted);">${escapeHtml(subDesc)}</div>
        </td>
      </tr>
    `;
  }).join('');
}

async function handlePunchClass(sessionId, courseName, courseCode, room, status = 'present') {
  try {
    const payload = {
      session_id: sessionId,
      course_name: courseName,
      course_code: courseCode,
      room: room,
      status: status
    };
    const res = await apiRequest('/api/attendance/punch', 'POST', payload);
    if (res && res.status === 'success') {
      showToast(`Punched attendance for ${courseName}!`, 'success');
      loadAttendanceData();
    } else {
      showToast(res.error || 'Failed to punch attendance.', 'error');
    }
  } catch (err) {
    console.error('Error punching attendance:', err);
    showToast('Failed to record punch.', 'error');
  }
}

async function handleBulkPunchToday() {
  if (!confirm("Mark all of today's scheduled classes as Present?")) return;
  try {
    const res = await apiRequest('/api/attendance/bulk-punch', 'POST', { status: 'present' });
    if (res && res.status === 'success') {
      showToast(`Recorded ${res.count} punches for today!`, 'success');
      loadAttendanceData();
    } else {
      showToast('Failed to bulk punch.', 'error');
    }
  } catch (err) {
    showToast('Error during bulk punch.', 'error');
  }
}

async function handleDeletePunch(punchId) {
  if (!confirm('Are you sure you want to delete this punch record?')) return;
  try {
    const res = await apiRequest(`/api/attendance/punch/${punchId}`, 'DELETE');
    if (res && res.status === 'success') {
      showToast('Punch record deleted.', 'success');
      loadAttendanceData();
    } else {
      showToast('Failed to delete punch.', 'error');
    }
  } catch (err) {
    showToast('Error deleting punch.', 'error');
  }
}

function openCustomPunchModal() {
  const courseName = prompt('Enter Course Name (e.g. Deep Learning):');
  if (!courseName) return;
  const courseCode = prompt('Enter Course Code (e.g. CSAI3027P_5):', '') || '';
  const date = prompt('Enter Date (YYYY-MM-DD) or leave empty for Today:', '') || '';
  const time = prompt('Enter Time (HH:MM:SS) or leave empty for Current Time:', '') || '';
  
  handleCustomPunch(courseName, courseCode, date, time);
}

async function handleCustomPunch(courseName, courseCode, date, time) {
  try {
    const payload = {
      course_name: courseName,
      course_code: courseCode,
      punch_date: date,
      punch_time: time,
      status: 'present'
    };
    const res = await apiRequest('/api/attendance/punch', 'POST', payload);
    if (res && res.status === 'success') {
      showToast(`Logged manual punch for ${courseName}!`, 'success');
      loadAttendanceData();
    } else {
      showToast(res.error || 'Failed to log punch.', 'error');
    }
  } catch (err) {
    showToast('Error logging manual punch.', 'error');
  }
}

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
