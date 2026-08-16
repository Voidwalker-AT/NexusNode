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
    case 'network':
      loadNetworkInterfaces();
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
  if (appState.isPollingSystemStatus) return;
  appState.isPollingSystemStatus = true;

  try {
    const res = await apiFetch('/api/system/status');
    if (res.ok) {
      const data = await res.json();
      updateTelemetryUI(data);
    }
  } catch (e) {
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
    appState.activeTaskId = activeTask.id;
    const taskTitle = document.getElementById('activeTaskTitle');
    const taskStatus = document.getElementById('activeTaskStatus');
    const taskFill = document.getElementById('activeTaskMeterFill');
    const taskStep = document.getElementById('activeTaskStepText');
    const taskPct = document.getElementById('activeTaskPercent');
    const cancelBtn = document.getElementById('activeTaskCancelBtn');
    const idText = document.getElementById('activeTaskIdText');

    if (taskTitle) taskTitle.textContent = activeTask.title || activeTask.type;
    if (taskStatus) taskStatus.textContent = (activeTask.status || 'RUNNING').toUpperCase();
    if (taskFill) taskFill.style.width = `${Math.min(activeTask.progress || 0, 100)}%`;
    if (taskStep) taskStep.textContent = activeTask.step_label || 'Executing operation...';
    if (taskPct) taskPct.textContent = `${activeTask.progress || 0}%`;
    if (cancelBtn) cancelBtn.style.display = 'block';
    if (idText) idText.textContent = `TASK: #${activeTask.id}`;
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

async function loadVaultFiles(folderPath = '') {
  const tbody = document.getElementById('vaultTableBody');
  const countLabel = document.getElementById('vaultFileCount');

  try {
    appState.currentVaultPath = folderPath || '';
    if (tbody) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--on-surface-muted); padding: 24px;">Loading Vault objects...</td></tr>';
    }
    const url = folderPath ? `/files?path=${encodeURIComponent(folderPath)}` : '/files';
    const res = await apiFetch(url);
    if (res.ok) {
      const data = await res.json();
      appState.cachedFiles = data.files || (Array.isArray(data) ? data : []);
      renderVaultTable(appState.cachedFiles);
    } else {
      if (countLabel) countLabel.textContent = 'UNAVAILABLE';
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--status-critical); padding: 24px;">Unable to load Vault — HTTP ${res.status}</td></tr>`;
      }
    }
  } catch (e) {
    console.error('Failed to load vault files:', e);
    if (countLabel) countLabel.textContent = 'ERROR';
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--status-critical); padding: 24px;">Vault load error: ${escapeHtml(e.message || 'Request failed')}</td></tr>`;
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
      const data = await res.json();
      const tasks = Array.isArray(data) ? data : (data.tasks || []);
      renderMediaQueue(tasks);
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
  const grid = document.getElementById('mediaLibraryGrid');
  try {
    if (grid) grid.innerHTML = '<div class="font-data-sm" style="color: var(--on-surface-muted); padding: 16px;">Scanning media files...</div>';
    const res = await apiFetch('/api/media/library');
    if (res.ok) {
      const data = await res.json();
      let items = [];
      if (data.items) {
        items = data.items;
      } else if (Array.isArray(data)) {
        items = data;
      } else if (typeof data === 'object') {
        items = Object.values(data).filter(Array.isArray).flat();
      }
      appState.mediaLibrary = items;
      renderMediaLibrary(items);
    } else if (grid) {
      grid.innerHTML = `<div class="font-data-sm" style="color: var(--status-critical); padding: 16px;">Unable to load media library — HTTP ${res.status}</div>`;
    }
  } catch (e) {
    console.error('Failed to load media library:', e);
    if (grid) {
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
  const tbody = document.getElementById('tasksTableBody');
  try {
    const res = await apiFetch('/api/tasks');
    if (res.ok) {
      const data = await res.json();
      const tasks = Array.isArray(data) ? data : (data.tasks || []);
      renderTasksTable(tasks);
    } else if (tbody) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--status-critical); padding: 24px;">Unable to load tasks — HTTP ${res.status}</td></tr>`;
    }
  } catch (e) {
    console.error('Failed to load tasks:', e);
    if (tbody) {
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
  const select = document.getElementById('aiModelSelect');
  const loadedName = document.getElementById('aiLoadedModelName');
  const loadedMem = document.getElementById('aiLoadedModelMemory');
  const unloadBtn = document.getElementById('aiUnloadModelBtn');

  try {
    const [modelsResult, stateResult] = await Promise.allSettled([
      apiFetch('/api/ai/models'),
      apiFetch('/api/ai/state')
    ]);

    // 1. Process Models List
    if (modelsResult.status === 'fulfilled' && modelsResult.value.ok) {
      const modelsData = await modelsResult.value.json();
      const modelsList = Array.isArray(modelsData) ? modelsData : (modelsData.models || []);
      const selectedModel = modelsData.selected_model || appState.selectedModel || (modelsList[0] ? modelsList[0].name : '');

      if (select) {
        if (modelsList.length === 0) {
          select.innerHTML = '<option value="">No models installed</option>';
        } else {
          select.innerHTML = modelsList.map(m => `
            <option value="${m.name}" ${m.name === selectedModel ? 'selected' : ''}>${m.name} (${m.size_display || formatBytes(m.size_bytes || m.size || 0)})</option>
          `).join('');
          appState.selectedModel = selectedModel;
        }
      }
    } else if (select) {
      select.innerHTML = '<option value="">Unable to load models</option>';
    }

    // 2. Process Runtime Residency State
    if (stateResult.status === 'fulfilled' && stateResult.value.ok) {
      const stateData = await stateResult.value.json();
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
  } catch (e) {
    console.error('Failed to load AI state:', e);
    if (select) select.innerHTML = '<option value="">Unable to load models (Error)</option>';
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

  const container = document.getElementById('diagFindingsContainer');
  const countLabel = document.getElementById('diagFindingsCount');

  try {
    const [fullRes, sysRes] = await Promise.allSettled([
      apiFetch('/api/admin/diagnostics/full-report'),
      apiFetch('/api/admin/diagnostics/system')
    ]);

    let findings = [];
    let processes = [];
    let rag = null;

    if (fullRes.status === 'fulfilled' && fullRes.value.ok) {
      const fullData = await fullRes.value.json();
      findings = fullData.findings || [];
      processes = fullData.processes || [];
      rag = fullData.rag || fullData.diagnostics?.rag;
    }

    if (sysRes.status === 'fulfilled' && sysRes.value.ok) {
      const sysData = await sysRes.value.json();
      if (!processes.length && sysData.top_processes) {
        processes = sysData.top_processes;
      }
      if (!rag && sysData.rag) {
        rag = sysData.rag;
      }
    }

    renderDiagnosticFindings(findings);
    renderDiagnosticsProcesses(processes);

    // Update RAG stats
    const docCount = document.getElementById('ragDocCount');
    const idxSize = document.getElementById('ragIndexSize');
    const walSize = document.getElementById('ragWalSize');
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
  } catch (e) {
    console.error('Failed to load diagnostics report:', e);
    if (countLabel) countLabel.textContent = 'ERROR';
    if (container) {
      container.innerHTML = `<div class="font-data-sm" style="color: var(--status-critical); padding: 16px;">Diagnostics unavailable: ${escapeHtml(e.message || 'Request failed')}</div>`;
    }
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
  const container = document.getElementById('automationJobsList');
  try {
    const res = await apiFetch('/api/automation/jobs');
    if (res.ok) {
      const data = await res.json();
      const jobs = Array.isArray(data) ? data : (data.jobs || []);
      if (container) {
        if (jobs.length === 0) {
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
    } else if (container) {
      container.innerHTML = `<div class="font-data-sm" style="color: var(--status-critical); padding: 16px;">Unable to load automation jobs — HTTP ${res.status}</div>`;
    }
  } catch (e) {
    console.error('Failed to load automation jobs:', e);
    if (container) {
      container.innerHTML = `<div class="font-data-sm" style="color: var(--status-critical); padding: 16px;">Automation load error: ${escapeHtml(e.message || 'Request failed')}</div>`;
    }
  }
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
  const tbody = document.getElementById('backupsTableBody');
  try {
    const res = await apiFetch('/api/backups');
    if (res.ok) {
      const data = await res.json();
      const backups = Array.isArray(data) ? data : (data.backups || []);
      if (tbody) {
        if (backups.length === 0) {
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
    } else if (tbody) {
      tbody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--status-critical); padding: 16px;">Unable to load backups — HTTP ${res.status}</td></tr>`;
    }
  } catch (e) {
    console.error('Failed to load backups list:', e);
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--status-critical); padding: 16px;">Backup load error: ${escapeHtml(e.message || 'Request failed')}</td></tr>`;
    }
  }
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
  const container = document.getElementById('storageIntelBreakdown');
  try {
    const res = await apiFetch('/api/system/storage-intel');
    if (res.ok) {
      const data = await res.json();
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
      if (container) {
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
    } else if (container) {
      container.innerHTML = `<div class="font-data-sm" style="color: var(--status-critical); padding: 16px;">Unable to load storage breakdown — HTTP ${res.status}</div>`;
    }
  } catch (e) {
    console.error('Failed to load storage intel:', e);
    if (container) {
      container.innerHTML = `<div class="font-data-sm" style="color: var(--status-critical); padding: 16px;">Storage intel error: ${escapeHtml(e.message || 'Request failed')}</div>`;
    }
  }
}

async function loadEventsArchive() {
  const container = document.getElementById('fullEventLogContainer');
  try {
    const res = await apiFetch('/api/events');
    if (res.ok) {
      const data = await res.json();
      const events = Array.isArray(data) ? data : (data.events || []);
      if (container) {
        if (events.length === 0) {
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
    } else if (container) {
      container.innerHTML = `<div class="log-entry" style="color: var(--status-critical);">Unable to load audit logs — HTTP ${res.status}</div>`;
    }
  } catch (e) {
    console.error('Failed to load events archive:', e);
    if (container) {
      container.innerHTML = `<div class="log-entry" style="color: var(--status-critical);">Event load error: ${escapeHtml(e.message || 'Request failed')}</div>`;
    }
  }
}

async function loadAdminUsers() {
  if (authState.role !== 'admin') return;
  const tbody = document.getElementById('adminUserTableBody');
  try {
    const res = await apiFetch('/api/admin/users');
    if (res.ok) {
      const data = await res.json();
      const users = Array.isArray(data) ? data : (data.users || []);
      if (tbody) {
        if (users.length === 0) {
          tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--on-surface-muted); padding: 16px;">No registered user accounts found.</td></tr>';
          return;
        }
        tbody.innerHTML = users.map(u => {
          const uname = u.username || u.user_id || 'user';
          const urole = (u.role || 'USER').toUpperCase();
          const created = u.created_at ? (typeof u.created_at === 'string' ? u.created_at.substring(0, 10) : new Date(u.created_at * 1000).toISOString().substring(0, 10)) : '--';
          return `
            <tr>
              <td style="color: var(--on-surface-bright); font-weight: 500;">${escapeHtml(uname)}</td>
              <td><span class="node-badge" style="color: ${urole === 'ADMIN' ? 'var(--primary)' : 'var(--on-surface-variant)'};">${urole}</span></td>
              <td class="font-data-sm">${created}</td>
              <td style="text-align: right;">
                <button class="btn btn-secondary" style="padding: 2px 8px; font-size: 10px; min-height: 24px;" onclick="showToast('User account active.', 'info')">Details</button>
              </td>
            </tr>
          `;
        }).join('');
      }
    } else if (tbody) {
      tbody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--status-critical); padding: 16px;">Unable to load users — HTTP ${res.status}</td></tr>`;
    }
  } catch (e) {
    console.error('Failed to load admin users:', e);
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--status-critical); padding: 16px;">User load error: ${escapeHtml(e.message || 'Request failed')}</td></tr>`;
    }
  }
}

async function loadNetworkInterfaces() {
  const container = document.getElementById('networkInterfacesList');
  if (!container) return;

  try {
    container.innerHTML = '<div class="font-data-sm" style="color: var(--on-surface-muted); padding: 16px;">Probing network interfaces...</div>';
    const res = await apiFetch('/api/services/status');
    if (res.ok) {
      const data = await res.json();
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
    } else {
      container.innerHTML = `<div class="font-data-sm" style="color: var(--status-critical); padding: 16px;">Unable to probe network interfaces — HTTP ${res.status}</div>`;
    }
  } catch (e) {
    console.error('Failed to load network interfaces:', e);
    container.innerHTML = `<div class="font-data-sm" style="color: var(--status-critical); padding: 16px;">Network probe error: ${escapeHtml(e.message || 'Request failed')}</div>`;
  }
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
