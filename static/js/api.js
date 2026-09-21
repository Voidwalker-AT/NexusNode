/**
 * NexusNode — Core API & Authentication Layer
 * Phase 4.2A Product Rebase
 */

const API_STORAGE_KEYS = {
  TOKEN: 'nexus_session_token',
  USER: 'nexus_user_info'
};

const authState = {
  token: localStorage.getItem(API_STORAGE_KEYS.TOKEN) || null,
  user: null,
  role: 'user',
  privileges: {},
  isAuthenticated: false
};

// Try restoring user info from localStorage
try {
  const cachedUser = localStorage.getItem(API_STORAGE_KEYS.USER);
  if (cachedUser) {
    const parsed = JSON.parse(cachedUser);
    authState.user = parsed;
    authState.role = parsed.role || 'user';
    authState.privileges = parsed.privileges || {};
    if (authState.token) {
      authState.isAuthenticated = true;
    }
  }
} catch (e) {
  console.warn('[API] Could not restore cached user session:', e);
}

function getToken() {
  return authState.token;
}

function setSession(token, user) {
  authState.token = token;
  authState.user = user;
  authState.role = user.role || 'user';
  authState.privileges = user.privileges || {};
  authState.isAuthenticated = true;

  if (token) {
    localStorage.setItem(API_STORAGE_KEYS.TOKEN, token);
  }
  if (user) {
    localStorage.setItem(API_STORAGE_KEYS.USER, JSON.stringify(user));
  }
}

function clearSession() {
  authState.token = null;
  authState.user = null;
  authState.role = 'user';
  authState.privileges = {};
  authState.isAuthenticated = false;

  localStorage.removeItem(API_STORAGE_KEYS.TOKEN);
  localStorage.removeItem(API_STORAGE_KEYS.USER);
}

function isAdmin() {
  return authState.role === 'admin';
}

function hasPrivilege(priv) {
  if (isAdmin()) return true;
  return Boolean(authState.privileges && authState.privileges[priv]);
}

/**
 * Universal API fetch wrapper with automatic JWT Bearer injection and error normalization.
 */
async function apiFetch(endpoint, options = {}) {
  const headers = { ...(options.headers || {}) };

  if (authState.token && !headers['Authorization']) {
    headers['Authorization'] = `Bearer ${authState.token}`;
  }
  if (!headers['localtonet-skip-warning']) {
    headers['localtonet-skip-warning'] = 'true';
  }

  // Handle JSON payload stringification if not FormData
  if (options.body && typeof options.body === 'object' && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(options.body);
  }

  const finalOptions = {
    ...options,
    headers
  };

  try {
    const res = await fetch(endpoint, finalOptions);

    if (res.status === 401) {
      // Session expired or invalid
      console.warn(`[API] 401 Unauthorized on ${endpoint}`);
      if (authState.isAuthenticated) {
        clearSession();
        window.dispatchEvent(new CustomEvent('nexus:auth-required', { detail: { endpoint } }));
      }
    }

    return res;
  } catch (err) {
    console.error(`[API] Network error fetching ${endpoint}:`, err);
    throw err;
  }
}

/**
 * Convenience helper that parses JSON response and throws formatted errors on failures.
 */
async function apiJson(endpoint, options = {}) {
  const res = await apiFetch(endpoint, options);
  let data = null;
  const contentType = res.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    try {
      data = await res.json();
    } catch (e) {
      data = null;
    }
  }

  if (!res.ok) {
    const errorMsg = (data && (data.error || data.message)) || `HTTP ${res.status} ${res.statusText}`;
    const err = new Error(errorMsg);
    err.status = res.status;
    err.data = data;
    throw err;
  }

  return data;
}

/**
 * Perform login request
 */
async function apiLogin(username, password) {
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: username, password })
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.message || data.error || 'Authentication failed');
    err.status = res.status;
    err.data = data;
    throw err;
  }

  setSession(data.token, data.user);
  return data;
}

/**
 * Perform logout request
 */
async function apiLogout() {
  try {
    if (authState.token) {
      await apiFetch('/api/auth/logout', { method: 'POST' });
    }
  } catch (e) {
    console.warn('[API] Logout request error (continuing cleanup):', e);
  } finally {
    clearSession();
    window.dispatchEvent(new CustomEvent('nexus:auth-required', { detail: { logout: true } }));
  }
}

/**
 * Verify current session with `/api/auth/me`
 */
async function apiCheckAuth() {
  if (!authState.token) {
    return false;
  }
  try {
    const res = await apiFetch('/api/auth/me');
    if (!res.ok) {
      clearSession();
      return false;
    }
    const data = await res.json();
    if (data && data.user) {
      setSession(authState.token, data.user);
      return true;
    }
    return false;
  } catch (e) {
    // If network fails, allow cached state to stand
    return authState.isAuthenticated;
  }
}
