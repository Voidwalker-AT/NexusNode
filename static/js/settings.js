/**
 * NexusNode — Settings View Controller
 * Phase 4.2A Product Rebase
 * User password change, appearance preferences, and admin server operations.
 */

async function loadSettings() {
  const container = document.getElementById('settingsContent');
  if (!container) return;

  container.innerHTML = `
    <div style="display: flex; flex-direction: column; gap: 20px; max-width: 600px;">
      
      <!-- Change Password Card -->
      <div class="tech-card">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">key</span>
            Change NexusNode Password
          </span>
        </div>
        <form onsubmit="handleChangePassword(event)" style="display: flex; flex-direction: column; gap: 12px;">
          <div class="form-group">
            <label class="form-label">Current Password</label>
            <input type="password" class="form-input" id="currentPasswordInput" required placeholder="Enter current password">
          </div>
          <div class="form-group">
            <label class="form-label">New Password</label>
            <input type="password" class="form-input" id="newPasswordInput" required minlength="8" placeholder="At least 8 characters">
          </div>
          <div class="form-group">
            <label class="form-label">Confirm New Password</label>
            <input type="password" class="form-input" id="confirmPasswordInput" required minlength="8" placeholder="Repeat new password">
          </div>
          <button type="submit" class="btn btn-primary" style="align-self: flex-start;" id="changePasswordBtn">
            Update Password
          </button>
        </form>
      </div>

      <!-- Appearance Card -->
      <div class="tech-card">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">palette</span>
            Appearance & Interface
          </span>
        </div>
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <div>
            <div style="font-weight: 600; color: var(--on-surface-bright); font-size: 13px;">OLED Pure Black Mode</div>
            <div style="color: var(--on-surface-muted); font-size: 11px;">Optimized for TECNO BG6 AMOLED display (#000000)</div>
          </div>
          <span class="status-badge badge-healthy">ENABLED (DEFAULT)</span>
        </div>
      </div>

      <!-- Admin Server Operations Card -->
      ${isAdmin() ? `
        <div class="tech-card" style="border-color: var(--status-warning);">
          <div class="tech-card-header">
            <span class="tech-card-title" style="color: var(--status-warning);">
              <span class="material-symbols-outlined">power_settings_new</span>
              Admin Appliance Controls
            </span>
          </div>
          <p style="color: var(--on-surface-variant); font-size: 13px; margin-bottom: 12px;">
            Manage the underlying Waitress WSGI server process running on the TECNO BG6.
          </p>
          <div style="display: flex; gap: 8px;">
            <button class="btn btn-danger" onclick="handleRestartServer(this)">
              Restart NexusNode Service
            </button>
          </div>
        </div>
      ` : ''}

    </div>
  `;
}

async function handleChangePassword(e) {
  e.preventDefault();
  const currentPassword = document.getElementById('currentPasswordInput').value;
  const newPassword = document.getElementById('newPasswordInput').value;
  const confirmPassword = document.getElementById('confirmPasswordInput').value;
  const btn = document.getElementById('changePasswordBtn');

  if (newPassword !== confirmPassword) {
    showToast('New passwords do not match', 'error');
    return;
  }

  if (btn) btn.disabled = true;
  showToast('Updating password...', 'info');

  try {
    await apiJson('/api/auth/change-password', {
      method: 'POST',
      body: { old_password: currentPassword, new_password: newPassword }
    });
    showToast('Password changed successfully!', 'success');
    document.getElementById('currentPasswordInput').value = '';
    document.getElementById('newPasswordInput').value = '';
    document.getElementById('confirmPasswordInput').value = '';
  } catch (err) {
    showToast(`Password change failed: ${err.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function handleRestartServer(btn) {
  if (!confirm('Are you sure you want to restart the NexusNode service? Temporary disconnection will occur.')) return;
  if (btn) btn.disabled = true;
  showToast('Initiating appliance service restart...', 'warning');
  try {
    await apiFetch('/api/admin/system/restart', { method: 'POST' });
    showToast('Restart signal dispatched.', 'info');
  } catch (err) {
    showToast('Server restart dispatched. Reconnecting shortly...', 'info');
  }
}
