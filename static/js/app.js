/**
 * NexusNode — Main Application Orchestrator & Router
 * Phase 4.2A Product Rebase
 * Targets: TECNO BG6 Mobile Appliance (OLED Dark Mode)
 */

let activeTab = 'dashboard';
let systemPollTimer = null;
let mcpPollTimer = null;

// In-Memory State Cache for Instant (0ms) Tab Switching
window.NexusStateCache = {
  data: {},
  get(key, maxAgeMs = 120000) {
    const entry = this.data[key];
    if (!entry) return null;
    if (Date.now() - entry.ts > maxAgeMs) return null;
    return entry.val;
  },
  set(key, val) {
    this.data[key] = { val, ts: Date.now() };
  },
  invalidate(key) {
    if (key) delete this.data[key];
    else this.data = {};
  }
};

const VALID_TABS = ['dashboard', 'academics', 'accounts', 'vault', 'mcp', 'diagnostics', 'settings'];

function switchTab(tabId, subtabId = null) {
  if (!VALID_TABS.includes(tabId)) {
    tabId = 'dashboard';
  }

  // Admin guard
  if (tabId === 'diagnostics' && !isAdmin()) {
    showToast('Administrator privileges required for Diagnostics', 'warning');
    tabId = 'dashboard';
  }

  // Close SSE stream if leaving diagnostics
  if (activeTab === 'diagnostics' && tabId !== 'diagnostics') {
    if (typeof stopDiagnosticsLogStream === 'function') {
      stopDiagnosticsLogStream();
    }
  }

  activeTab = tabId;

  // Update hash
  window.location.hash = `#tab-${tabId}`;

  // Update Desktop Header Navigation
  document.querySelectorAll('.desktop-nav-tabs .nav-tab').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-tab') === tabId);
  });

  // Update Mobile Bottom Navigation
  document.querySelectorAll('.mobile-bottom-nav .mobile-nav-btn').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-tab') === tabId);
  });

  // Switch Active Tab Pane
  document.querySelectorAll('.tab-pane').forEach(pane => {
    pane.classList.toggle('active', pane.id === `tab-${tabId}`);
  });

  // Trigger View Loader
  if (tabId === 'dashboard') {
    loadDashboard();
  } else if (tabId === 'academics') {
    if (subtabId) switchAcademicsSubtab(subtabId);
    else loadAcademics();
  } else if (tabId === 'accounts') {
    loadAccounts();
  } else if (tabId === 'vault') {
    loadVault();
  } else if (tabId === 'mcp') {
    loadMcp();
  } else if (tabId === 'diagnostics') {
    loadDiagnostics();
  } else if (tabId === 'settings') {
    loadSettings();
  }

  // Manage MCP Polling
  if (tabId === 'mcp') {
    startMcpPolling();
  } else {
    stopMcpPolling();
  }

  // Scroll to top
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function updateAuthUI() {
  const loginOverlay = document.getElementById('loginOverlay');
  const user = authState.user;

  if (!authState.isAuthenticated || !user) {
    if (loginOverlay) loginOverlay.style.display = 'flex';
    return;
  }

  if (loginOverlay) loginOverlay.style.display = 'none';

  // Update Header Elements
  const headerUsername = document.getElementById('headerUsername');
  if (headerUsername) headerUsername.textContent = user.username || user.user_id || 'User';

  const headerAvatar = document.getElementById('headerUserAvatar');
  if (headerAvatar) {
    const firstLetter = (user.username || user.user_id || 'U')[0].toUpperCase();
    headerAvatar.textContent = firstLetter;
  }

  const roleBadge = document.getElementById('headerRoleBadge');
  if (roleBadge) {
    roleBadge.textContent = (user.role || 'USER').toUpperCase();
    roleBadge.className = `role-badge ${user.role === 'admin' ? 'admin' : 'user'}`;
  }

  // Admin-only elements visibility
  const adminElements = document.querySelectorAll('.admin-only');
  adminElements.forEach(el => {
    el.style.display = isAdmin() ? '' : 'none';
  });
}

function toggleMobileMoreDrawer(forceState) {
  const overlay = document.getElementById('drawerOverlay');
  const drawer = document.getElementById('drawerContent');
  if (!overlay || !drawer) return;

  const shouldOpen = forceState !== undefined ? forceState : overlay.classList.contains('closed');
  if (shouldOpen) {
    overlay.classList.remove('closed');
    drawer.classList.remove('closed');
    document.body.style.overflow = 'hidden';
  } else {
    overlay.classList.add('closed');
    drawer.classList.add('closed');
    document.body.style.overflow = '';
  }
}

function closeAllMoreMenus() {
  toggleMobileMoreDrawer(false);
}

// Bounded Polling Helpers
function startSystemPolling() {
  if (systemPollTimer) clearInterval(systemPollTimer);
  // Poll system status every 60 seconds
  systemPollTimer = setInterval(() => {
    if (authState.isAuthenticated) {
      apiJson('/api/system/status').then(data => {
        const dot = document.getElementById('headerConnDot');
        if (dot) dot.style.background = 'var(--status-healthy)';
      }).catch(err => {
        const dot = document.getElementById('headerConnDot');
        if (dot) dot.style.background = 'var(--status-critical)';
      });
    }
  }, 60000);
}

function startMcpPolling() {
  if (mcpPollTimer) clearInterval(mcpPollTimer);
  // Poll MCP activity every 30s only while on MCP tab
  mcpPollTimer = setInterval(() => {
    if (activeTab === 'mcp' && authState.isAuthenticated) {
      loadMcp();
    }
  }, 30000);
}

function stopMcpPolling() {
  if (mcpPollTimer) {
    clearInterval(mcpPollTimer);
    mcpPollTimer = null;
  }
}

// Handle Login Submission
async function handleLoginSubmit(e) {
  e.preventDefault();
  const userField = document.getElementById('loginUsername');
  const passField = document.getElementById('loginPassword');
  const errDiv = document.getElementById('loginErrorMessage');
  const submitBtn = document.getElementById('loginSubmitBtn');

  if (!userField || !passField) return;

  const username = userField.value.trim();
  const password = passField.value;

  if (errDiv) errDiv.style.display = 'none';
  if (submitBtn) submitBtn.disabled = true;

  try {
    await apiLogin(username, password);
    userField.value = '';
    passField.value = '';
    updateAuthUI();
    showToast('Signed in successfully', 'success');
    switchTab(activeTab);
    startSystemPolling();
  } catch (err) {
    if (errDiv) {
      errDiv.textContent = err.message || 'Login failed';
      errDiv.style.display = 'block';
    }
    showToast(`Authentication failed: ${err.message}`, 'error');
  } finally {
    if (submitBtn) submitBtn.disabled = false;
  }
}

// Handle Sign Out
async function handleLogout() {
  if (!confirm('Are you sure you want to sign out of NexusNode?')) return;
  await apiLogout();
}

// Initialize on DOM Ready
document.addEventListener('DOMContentLoaded', async () => {
  // Listen for auth required events
  window.addEventListener('nexus:auth-required', () => {
    updateAuthUI();
  });

  // Bind Login Form
  const loginForm = document.getElementById('loginForm');
  if (loginForm) {
    loginForm.addEventListener('submit', handleLoginSubmit);
  }

  // Check stored auth session
  const valid = await apiCheckAuth();
  updateAuthUI();

  if (valid) {
    // Read URL Hash for initial tab
    const hash = window.location.hash.replace('#tab-', '').toLowerCase();
    const initialTab = VALID_TABS.includes(hash) ? hash : 'dashboard';
    switchTab(initialTab);
    startSystemPolling();
  } else {
    // Show login overlay
    const overlay = document.getElementById('loginOverlay');
    if (overlay) overlay.style.display = 'flex';
  }
});
