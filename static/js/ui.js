/**
 * NexusNode — UI Helpers, Badges, Modals & Toast System
 * Phase 4.2A Product Rebase
 */

// Escape HTML for XSS prevention
function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

/**
 * Toast Notification System
 */
function showToast(message, type = 'info', duration = 3500) {
  let container = document.getElementById('toastContainer');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toastContainer';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;

  const iconName = type === 'success' ? 'check_circle' :
                   type === 'error' ? 'error' :
                   type === 'warning' ? 'warning' : 'info';

  toast.innerHTML = `
    <span class="material-symbols-outlined toast-icon">${iconName}</span>
    <span class="toast-message">${escapeHtml(message)}</span>
    <button class="toast-close" onclick="this.parentElement.remove()">&times;</button>
  `;

  container.appendChild(toast);

  // Trigger reflow for slide-in animation
  setTimeout(() => toast.classList.add('visible'), 10);

  setTimeout(() => {
    toast.classList.remove('visible');
    setTimeout(() => toast.remove(), 250);
  }, duration);
}

/**
 * Modal Management
 */
function openModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) {
    modal.classList.add('active');
    document.body.style.overflow = 'hidden';
  }
}

function closeModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) {
    modal.classList.remove('active');
    document.body.style.overflow = '';
  }
}

/**
 * Formats byte counts into human-readable strings
 */
function formatBytes(bytes, decimals = 1) {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

/**
 * Relative time formatter (e.g., '2m ago', 'Just now')
 */
function formatTimeAgo(timestamp) {
  if (!timestamp) return 'Never';
  const ts = typeof timestamp === 'number' ? timestamp : new Date(timestamp).getTime() / 1000;
  const now = Date.now() / 1000;
  const diff = Math.max(0, Math.floor(now - ts));

  if (diff < 30) return 'Just now';
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

/**
 * Formats ISO or Unix timestamp to local time string
 */
function formatDateTime(timestamp) {
  if (!timestamp) return '—';
  const d = typeof timestamp === 'number' ? new Date(timestamp * 1000) : new Date(timestamp);
  if (isNaN(d.getTime())) return String(timestamp);
  return d.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  });
}

/**
 * Provenance Badge Renderer (Live · <time>, Cached · <time>, Stale)
 */
function renderProvenanceBadge(source, fetchedAt) {
  const s = String(source || 'local').toLowerCase();
  const timeStr = fetchedAt ? formatTimeAgo(fetchedAt) : '';

  if (s === 'live') {
    return `<span class="badge-provenance badge-live" title="Fetched directly from upstream">Live ${timeStr ? '· ' + timeStr : ''}</span>`;
  } else if (s === 'cached' || s === 'local') {
    return `<span class="badge-provenance badge-cached" title="Served from local SQLite cache">Cached ${timeStr ? '· ' + timeStr : ''}</span>`;
  } else if (s === 'stale' || s === 'lkg') {
    return `<span class="badge-provenance badge-stale" title="Last Known Good data (stale)">Stale ${timeStr ? '· ' + timeStr : ''}</span>`;
  }
  return `<span class="badge-provenance badge-local">${escapeHtml(s)}</span>`;
}

/**
 * Status Badge Renderer (HEALTHY, DEGRADED, ACTION REQUIRED, OFFLINE, SYNCING, STALE)
 */
function renderStatusBadge(status) {
  const norm = String(status || 'UNKNOWN').toUpperCase();
  let badgeClass = 'badge-secondary';

  if (norm === 'HEALTHY' || norm === 'COMPLETE' || norm === 'SAFE' || norm === 'ONLINE') {
    badgeClass = 'badge-healthy';
  } else if (norm === 'DEGRADED' || norm === 'WARNING' || norm === 'PRESSURE') {
    badgeClass = 'badge-warning';
  } else if (norm === 'ACTION REQUIRED' || norm === 'CRITICAL' || norm === 'ERROR' || norm === 'FAILED') {
    badgeClass = 'badge-critical';
  } else if (norm === 'SYNCING') {
    badgeClass = 'badge-syncing';
  } else if (norm === 'STALE' || norm === 'OFFLINE') {
    badgeClass = 'badge-stale';
  }

  return `<span class="status-badge ${badgeClass}">${escapeHtml(norm)}</span>`;
}
