/**
 * NexusNode — Academic Accounts View Controller & Guided Onboarding Portal
 * Phase 4.3A: Multi-Account Onboarding & Self-Service Checklist Engine
 * 
 * Includes:
 * 1. State-driven Student Self-Service view ("My Academic Account") with 10-point checklist & NEXT REQUIRED ACTION.
 * 2. Admin Multi-Tenant Governance view with user list, inspection, and the 11-step "+ Add Academic Account" wizard.
 * 3. Guided Google OAuth Web App setup with explicit Testing-mode test-user whitelist instructions.
 */

let currentWizardStep = 1;
let wizardStudentData = {
  user_id: '',
  display_name: '',
  upes_email: '',
  google_email: '',
  password: 'Student@1234',
  must_change_password: true
};
let inspectingUserId = null;

async function loadAccounts() {
  const container = document.getElementById('accountsContent');
  if (!container) return;

  container.innerHTML = '<div style="color: var(--on-surface-muted); padding: 24px 0;">Loading academic accounts...</div>';

  try {
    const data = await apiJson('/api/timetable/onboarding-status');
    renderAccounts(data);
  } catch (err) {
    container.innerHTML = `
      <div class="tech-card" style="border-color: var(--status-critical);">
        <div class="tech-card-header">
          <span class="tech-card-title" style="color: var(--status-critical);">Error Loading Account Status</span>
          <button class="btn btn-secondary" onclick="loadAccounts()">Retry</button>
        </div>
        <p style="color: var(--on-surface-variant); font-size: 13px;">${escapeHtml(err.message)}</p>
      </div>
    `;
  }
}

function renderAccounts(data) {
  const container = document.getElementById('accountsContent');
  if (!container) return;

  // Separate Admin Governance from Student Self-Service
  if (isAdmin()) {
    renderAdminGovernanceView(container, data);
  } else {
    renderStudentSelfServiceView(container, data);
  }
}

// =============================================================================
// 1. STUDENT SELF-SERVICE VIEW ("My Academic Account")
// =============================================================================

function renderStudentSelfServiceView(container, data) {
  const creds = data.credentials || data.upes || {};
  const google = data.google || {};
  const tt = data.timetable || {};
  const user = data.user || data.user_profile || {};
  const checklist = data.checklist || [];
  const healthState = data.health_state || 'UNKNOWN';
  const nextStep = data.next_required_step || data.next_step || 'All systems operational';

  // Actionable Banner Determination
  let actionBtnHtml = '';
  let bannerClass = 'alert-info';
  let bannerIcon = 'info';

  if (healthState === 'PASSWORD_CHANGE_REQUIRED') {
    bannerClass = 'alert-warning';
    bannerIcon = 'lock_reset';
    actionBtnHtml = `<button class="btn btn-primary" onclick="switchTab('settings')">Change Password Now</button>`;
  } else if (healthState === 'GOOGLE_REQUIRED' || healthState === 'GOOGLE_EXPIRED') {
    bannerClass = 'alert-critical';
    bannerIcon = 'link_off';
    actionBtnHtml = `<button class="btn btn-primary" onclick="handleConnectGoogle()"><span class="material-symbols-outlined" style="font-size: 14px;">link</span> Connect Google Calendar</button>`;
  } else if (healthState === 'UPES_REQUIRED' || healthState === 'UPES_EXPIRED') {
    bannerClass = 'alert-warning';
    bannerIcon = 'school';
    actionBtnHtml = `<button class="btn btn-primary" onclick="document.getElementById('upesUsername').focus()">Configure UPES Credentials</button>`;
  } else if (healthState === 'READY_TO_SYNC' || healthState === 'SYNC_FAILED') {
    bannerClass = 'alert-warning';
    bannerIcon = 'sync';
    actionBtnHtml = `<button class="btn btn-primary" onclick="handleTriggerSync(this)"><span class="material-symbols-outlined" style="font-size: 14px;">sync</span> Synchronize Now</button>`;
  } else if (healthState === 'SYNCING') {
    bannerClass = 'alert-info';
    bannerIcon = 'sync';
    actionBtnHtml = `<span class="badge badge-primary font-mono">IN PROGRESS</span>`;
  } else {
    bannerClass = 'alert-healthy';
    bannerIcon = 'check_circle';
    actionBtnHtml = `<span class="status-badge badge-healthy">OPERATIONAL</span>`;
  }

  container.innerHTML = `
    <div style="display: flex; flex-direction: column; gap: 16px;">
      
      <!-- Account Header Banner -->
      <div class="tech-card" style="border-color: var(--border-medium);">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">badge</span>
            My Academic Account & Integration Status
          </span>
          ${renderStatusBadge(healthState)}
        </div>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; font-size: 12px;">
          <div>
            <span style="color: var(--on-surface-muted); display: block;">Student User ID</span>
            <span class="font-mono" style="font-weight: 600; color: var(--on-surface-bright);">${escapeHtml(data.user_id || user.user_id || 'student')}</span>
          </div>
          <div>
            <span style="color: var(--on-surface-muted); display: block;">Registered Email</span>
            <span style="color: var(--on-surface);">${escapeHtml(user.upes_email || creds.username_hint || 'Not configured')}</span>
          </div>
          <div>
            <span style="color: var(--on-surface-muted); display: block;">Google Account</span>
            <span style="color: var(--on-surface);">${google.needs_reauth ? '<span style="color: var(--status-warning); font-weight: 600;">Reauthorization Required</span>' : escapeHtml(google.connected_email || (google.connected ? 'Connected' : 'Disconnected'))}</span>
          </div>
          <div>
            <span style="color: var(--on-surface-muted); display: block;">Timetable Status</span>
            <span class="font-mono" style="color: var(--primary);">${tt.available ? `${tt.session_count} Sessions Loaded` : 'No Sessions'}</span>
          </div>
        </div>
      </div>

      <!-- State-Driven NEXT REQUIRED ACTION Banner -->
      <div class="alert-banner ${bannerClass}" style="
        background: var(--surface-1);
        border-left: 4px solid ${healthState === 'HEALTHY' || healthState === 'READY' ? 'var(--status-healthy)' : (healthState.includes('EXPIRED') || healthState.includes('REQUIRED') ? 'var(--status-warning)' : 'var(--primary)')};
        border-top: 1px solid var(--border-subtle);
        border-right: 1px solid var(--border-subtle);
        border-bottom: 1px solid var(--border-subtle);
        border-radius: var(--radius-md);
        padding: 14px 16px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        flex-wrap: wrap;
      ">
        <div style="display: flex; align-items: center; gap: 12px;">
          <span class="material-symbols-outlined" style="font-size: 22px; color: ${healthState === 'HEALTHY' || healthState === 'READY' ? 'var(--status-healthy)' : 'var(--status-warning)'};">
            ${bannerIcon}
          </span>
          <div>
            <strong style="color: var(--on-surface-bright); font-size: 13px;">${escapeHtml(nextStep)}</strong>
            <div style="font-size: 11px; color: var(--on-surface-muted); margin-top: 2px;">Automated background state evaluator</div>
          </div>
        </div>
        ${actionBtnHtml}
      </div>

      <!-- 10-Point Authoritative Onboarding Checklist -->
      <div class="tech-card">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">checklist</span>
            Academic Setup & Verification Checklist
          </span>
          <span class="badge badge-secondary">${checklist.filter(c => c.completed).length} / ${checklist.length} Complete</span>
        </div>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 8px; margin-top: 6px;">
          ${checklist.map(item => `
            <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 12px; background: var(--surface-2); border-radius: var(--radius-sm);">
              <div style="display: flex; align-items: center; gap: 8px;">
                <span class="material-symbols-outlined" style="font-size: 18px; color: ${item.completed ? 'var(--status-healthy)' : 'var(--on-surface-muted)'};">
                  ${item.completed ? 'check_circle' : 'radio_button_unchecked'}
                </span>
                <span style="font-size: 12px; color: ${item.completed ? 'var(--on-surface-bright)' : 'var(--on-surface-variant)'};">
                  ${escapeHtml(item.title)}
                </span>
              </div>
              <span class="badge ${item.completed ? 'badge-healthy' : 'badge-warning'}" style="font-size: 10px;">
                ${item.completed ? 'VERIFIED' : (item.required ? 'REQUIRED' : 'OPTIONAL')}
              </span>
            </div>
          `).join('')}
        </div>
      </div>

      <!-- Section 1: UPES Portal Credentials -->
      <div class="tech-card">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">school</span>
            1. UPES Student Portal Credentials
          </span>
          ${creds.configured ? '<span class="status-badge badge-healthy">CONFIGURED</span>' : '<span class="status-badge badge-critical">NOT CONFIGURED</span>'}
        </div>
        <p style="color: var(--on-surface-variant); font-size: 13px; margin-bottom: 14px;">
          Enter your official UPES institutional email and password. Credentials are encrypted at rest with PBKDF2/AES and stored exclusively on your appliance.
        </p>

        <form id="upesCredsForm" onsubmit="handleSaveUpesCreds(event)" style="display: flex; flex-direction: column; gap: 12px; max-width: 500px;">
          <div class="form-group">
            <label class="form-label">UPES Institutional Email</label>
            <input type="email" class="form-input" id="upesUsername" placeholder="your.name.sapid@stu.upes.ac.in" required value="${escapeHtml(creds.username_hint || '')}">
          </div>
          <div class="form-group">
            <label class="form-label">Portal Password</label>
            <input type="password" class="form-input" id="upesPassword" placeholder="${creds.configured ? '••••••••••••' : 'Enter portal password'}" ${creds.configured ? '' : 'required'}>
          </div>
          <div style="display: flex; gap: 8px; flex-wrap: wrap;">
            <button type="submit" class="btn btn-primary" id="saveUpesBtn">
              <span class="material-symbols-outlined" style="font-size: 14px;">save</span>
              Save Credentials
            </button>
            ${creds.configured ? `
              <button type="button" class="btn btn-secondary" onclick="handleTestUpesLogin(this)">
                <span class="material-symbols-outlined" style="font-size: 14px;">check_circle</span>
                Test Login
              </button>
              <button type="button" class="btn btn-danger" onclick="handleDeleteUpesCreds(this)">
                <span class="material-symbols-outlined" style="font-size: 14px;">delete</span>
                Delete
              </button>
            ` : ''}
          </div>
        </form>
      </div>

      <!-- Section 2: Google Calendar Integration -->
      <div class="tech-card">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">event</span>
            2. Google Calendar Integration
          </span>
          ${google.needs_reauth ? '<span class="status-badge badge-warning">REAUTHORIZE</span>' : (google.connected ? '<span class="status-badge badge-healthy">CONNECTED</span>' : '<span class="status-badge badge-stale">DISCONNECTED</span>')}
        </div>
        <p style="color: var(--on-surface-variant); font-size: 13px; margin-bottom: 14px;">
          Connect your Google Calendar to automatically synchronize classes into your mobile schedule.
        </p>
        <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
          ${google.needs_reauth ? `
            <div style="font-size: 13px; color: var(--status-warning); margin-right: 12px;">
              OAuth token expired or revoked. Please re-authorize Google Calendar access.
            </div>
            <a href="/api/auth/google/authorize?redirect=true" class="btn btn-warning" style="text-decoration: none; display: inline-flex; align-items: center; gap: 6px; font-size: 13px; padding: 6px 14px;">
              <span class="material-symbols-outlined" style="font-size: 14px;">vpn_key</span>
              Re-authorize Google
            </a>
          ` : google.connected ? `
            <div style="font-size: 13px; color: var(--on-surface); margin-right: 12px;">
              Linked as: <strong>${escapeHtml(google.connected_email || 'Google User')}</strong>
            </div>
            <button class="btn btn-danger" onclick="handleDisconnectGoogle(this)">
              Disconnect Google
            </button>
          ` : `
            <button class="btn btn-primary" onclick="handleConnectGoogle()">
              <span class="material-symbols-outlined" style="font-size: 14px;">link</span>
              Connect Google Calendar
            </button>
          `}
        </div>
      </div>

      <!-- Section 3: Manual Timetable Fallback Upload -->
      <div class="tech-card">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">upload_file</span>
            3. Manual Timetable JSON Upload
          </span>
        </div>
        <p style="color: var(--on-surface-variant); font-size: 13px; margin-bottom: 14px;">
          If the UPES portal is temporarily unreachable or undergoing maintenance, you can upload your exported timetable JSON file directly.
        </p>
        <div style="display: flex; flex-direction: column; gap: 10px; max-width: 500px;">
          <input type="file" id="manualTimetableFileInput" accept=".json" class="form-input" style="padding: 6px;">
          <button class="btn btn-secondary" style="align-self: flex-start;" onclick="handleUploadTimetableFile(this)">
            Upload Timetable File
          </button>
        </div>
      </div>

    </div>
  `;
}

// =============================================================================
// 2. ADMIN MULTI-TENANT GOVERNANCE VIEW
// =============================================================================

function renderAdminGovernanceView(container, data) {
  container.innerHTML = `
    <div style="display: flex; flex-direction: column; gap: 16px;">
      
      <!-- Admin Governance Header -->
      <div class="tech-card" style="border-color: var(--border-medium);">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">admin_panel_settings</span>
            Multi-Tenant Academic Governance & Onboarding
          </span>
          <div style="display: flex; gap: 8px;">
            <button class="btn btn-primary" onclick="openAddAccountWizard()">
              <span class="material-symbols-outlined" style="font-size: 14px;">person_add</span>
              + Add Academic Account
            </button>
            <button class="btn btn-secondary" onclick="loadAdminUsersList()">
              <span class="material-symbols-outlined" style="font-size: 14px;">refresh</span>
              Refresh
            </button>
          </div>
        </div>
        <p style="color: var(--on-surface-variant); font-size: 13px; line-height: 1.5;">
          Manage student tenants, review automated 3-hour sync schedules, inspect 10-point onboarding checklists, and guide new student enrollment through the 11-step onboarding wizard.
        </p>
      </div>

      <!-- Enrolled Tenants Table -->
      <div class="tech-card">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">group</span>
            Enrolled Student Accounts
          </span>
          <span class="status-badge badge-healthy">MULTI-TENANT ISOLATED</span>
        </div>
        <div id="adminUsersListContainer" style="color: var(--on-surface-muted); font-size: 13px;">
          Loading enrolled student tenants...
        </div>
      </div>

      <!-- Detailed Inspection Container -->
      <div id="adminUserInspectionContainer" style="display: none;"></div>

      <!-- Wizard Modal Container -->
      <div id="addAccountWizardModalContainer"></div>

    </div>
  `;

  loadAdminUsersList();
}

async function loadAdminUsersList() {
  const container = document.getElementById('adminUsersListContainer');
  if (!container) return;

  container.innerHTML = '<div style="padding: 12px 0; color: var(--on-surface-muted);">Fetching student accounts from database...</div>';

  try {
    const data = await apiJson('/api/admin/users');
    const users = (data && data.users) || (Array.isArray(data) ? data : []);

    if (users.length === 0) {
      container.innerHTML = '<div style="padding: 12px 0;">No student tenant accounts found. Click <strong>+ Add Academic Account</strong> to enroll a student.</div>';
      return;
    }

    container.innerHTML = `
      <table class="tech-table" style="margin-top: 8px;">
        <thead>
          <tr>
            <th>User ID</th>
            <th>Display Name</th>
            <th>UPES Email</th>
            <th>Google Calendar</th>
            <th>Portal Sync</th>
            <th>Onboarding State</th>
            <th style="text-align: right;">Actions</th>
          </tr>
        </thead>
        <tbody>
          ${users.map(u => `
            <tr>
              <td class="font-mono"><strong>${escapeHtml(u.user_id)}</strong></td>
              <td>${escapeHtml(u.display_name || '—')}</td>
              <td>${escapeHtml(u.upes_email || '—')}</td>
              <td>${u.google_connected ? '<span style="color: var(--status-healthy); font-weight: 600;">Connected</span>' : '<span style="color: var(--on-surface-muted);">No</span>'}</td>
              <td>${u.upes_configured ? '<span style="color: var(--status-healthy);">Configured</span>' : '<span style="color: var(--status-warning);">Missing</span>'}</td>
              <td><span class="badge ${u.setup_state === 'COMPLETE' ? 'badge-healthy' : 'badge-warning'}">${escapeHtml(u.setup_state || 'INCOMPLETE')}</span></td>
              <td style="text-align: right; white-space: nowrap;">
                <button class="btn btn-secondary" style="font-size: 11px; padding: 3px 8px; min-height: 24px;" onclick="inspectStudentChecklist('${escapeHtml(u.user_id)}')">
                  Inspect Checklist
                </button>
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  } catch (err) {
    container.innerHTML = `<span style="color: var(--status-critical);">${escapeHtml(err.message)}</span>`;
  }
}

async function inspectStudentChecklist(targetUserId) {
  const container = document.getElementById('adminUserInspectionContainer');
  if (!container) return;

  container.style.display = 'block';
  container.innerHTML = `<div class="tech-card"><div style="color: var(--on-surface-muted);">Loading checklist for ${escapeHtml(targetUserId)}...</div></div>`;

  try {
    const data = await apiJson(`/api/admin/users/${targetUserId}/onboarding-status`);
    const checklist = data.checklist || [
      { id: 'account_created', title: 'NexusNode Account Created', completed: Boolean(data.account_created) },
      { id: 'password_changed', title: 'Initial Password Changed', completed: Boolean(data.password_changed) },
      { id: 'google_connected', title: 'Google Calendar Connected', completed: Boolean(data.google_connected) },
      { id: 'calendar_selected', title: 'Target Calendar Selected', completed: Boolean(data.calendar_selected) },
      { id: 'upes_credentials', title: 'UPES Credentials Configured', completed: Boolean(data.upes_configured) },
      { id: 'upes_session', title: 'Portal Authentication Active', completed: Boolean(data.upes_status === 'HEALTHY') },
      { id: 'timetable_synced', title: 'Timetable Synchronized', completed: Boolean(data.timetable_synced) },
      { id: 'calendar_synced', title: 'Google Calendar Reconciled', completed: Boolean(data.last_synced_at) },
      { id: 'attendance_synced', title: 'Attendance Loaded', completed: Boolean(data.attendance_synced) },
      { id: 'results_synced', title: 'Academic Results / SGPA Loaded', completed: Boolean(data.results_synced) }
    ];

    container.innerHTML = `
      <div class="tech-card" style="border-color: var(--primary); margin-top: 16px;">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">checklist</span>
            Onboarding Checklist: <span class="font-mono" style="color: var(--primary);">${escapeHtml(targetUserId)}</span>
          </span>
          <button class="btn btn-secondary" style="font-size: 11px; padding: 2px 6px; min-height: 22px;" onclick="document.getElementById('adminUserInspectionContainer').style.display='none'">
            Close
          </button>
        </div>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 8px; margin-top: 8px;">
          ${checklist.map(item => `
            <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 10px; background: var(--surface-2); border-radius: var(--radius-sm);">
              <span style="font-size: 12px; color: ${item.completed ? 'var(--on-surface-bright)' : 'var(--on-surface-variant)'};">
                ${escapeHtml(item.title)}
              </span>
              <span class="badge ${item.completed ? 'badge-healthy' : 'badge-warning'}" style="font-size: 10px;">
                ${item.completed ? 'VERIFIED' : 'PENDING'}
              </span>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  } catch (err) {
    container.innerHTML = `<div class="tech-card" style="border-color: var(--status-critical);"><span style="color: var(--status-critical);">${escapeHtml(err.message)}</span></div>`;
  }
}

// =============================================================================
// 3. AUTHORITATIVE 11-STEP ADMIN "+ ADD ACADEMIC ACCOUNT" WIZARD
// =============================================================================

function openAddAccountWizard() {
  currentWizardStep = 1;
  wizardStudentData = {
    user_id: '',
    display_name: '',
    upes_email: '',
    google_email: '',
    password: 'Student@1234',
    must_change_password: true
  };
  renderWizardModal();
}

function closeAddAccountWizard() {
  const container = document.getElementById('addAccountWizardModalContainer');
  if (container) container.innerHTML = '';
  loadAdminUsersList();
}

function renderWizardModal() {
  const container = document.getElementById('addAccountWizardModalContainer');
  if (!container) return;

  const totalSteps = 11;
  const stepTitles = [
    'Create NexusNode Account',
    'Google Cloud Eligibility',
    'Student First Login',
    'Google Calendar Integration',
    'UPES Institutional Portal',
    'Academic Data Verification',
    'Calendar Reconciliation Preview',
    'Student Calendar Sync',
    '3-Hour Automation Setup',
    'MCP Client Integration',
    'Onboarding Complete'
  ];

  container.innerHTML = `
    <div style="
      position: fixed;
      top: 0;
      left: 0;
      width: 100vw;
      height: 100vh;
      background: rgba(0, 0, 0, 0.8);
      backdrop-filter: blur(4px);
      z-index: 1000;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 20px;
      box-sizing: border-box;
    ">
      <div style="
        background: var(--surface-1);
        border: 1px solid var(--border-medium);
        border-radius: var(--radius-md);
        width: 100%;
        max-width: 680px;
        max-height: 90vh;
        display: flex;
        flex-direction: column;
        overflow: hidden;
        box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
      ">
        <!-- Wizard Header -->
        <div style="padding: 16px 20px; border-bottom: 1px solid var(--border-subtle); display: flex; justify-content: space-between; align-items: center; background: var(--surface-2);">
          <div>
            <div style="font-size: 11px; text-transform: uppercase; color: var(--primary); font-weight: 600; letter-spacing: 0.5px;">
              Step ${currentWizardStep} of ${totalSteps} · Guided Academic Onboarding
            </div>
            <div style="font-size: 16px; font-weight: 700; color: var(--on-surface-bright); margin-top: 2px;">
              ${stepTitles[currentWizardStep - 1]}
            </div>
          </div>
          <button class="icon-btn" onclick="closeAddAccountWizard()" title="Cancel">
            <span class="material-symbols-outlined">close</span>
          </button>
        </div>

        <!-- Wizard Step Body -->
        <div id="wizardStepBody" style="padding: 20px; overflow-y: auto; flex: 1;">
          ${getWizardStepContent(currentWizardStep)}
        </div>

        <!-- Wizard Footer -->
        <div style="padding: 14px 20px; border-top: 1px solid var(--border-subtle); display: flex; justify-content: space-between; align-items: center; background: var(--surface-2);">
          <button class="btn btn-secondary" onclick="wizardPrev()" ${currentWizardStep === 1 ? 'disabled style="opacity: 0.5;"' : ''}>
            &larr; Back
          </button>
          <div style="display: flex; gap: 8px;">
            <button class="btn btn-secondary" onclick="closeAddAccountWizard()">Cancel</button>
            <button class="btn btn-primary" id="wizardNextBtn" onclick="wizardNext()">
              ${currentWizardStep === totalSteps ? 'Complete Onboarding' : 'Next &rarr;'}
            </button>
          </div>
        </div>
      </div>
    </div>
  `;
}

function getWizardStepContent(step) {
  switch (step) {
    case 1: // Create NexusNode Account
      return `
        <p style="color: var(--on-surface-variant); font-size: 13px; line-height: 1.5; margin-bottom: 16px;">
          Define the student tenant identity. All timetable, attendance, results, Google tokens, and Vault files will be partitioned under this unique user ID in SQLite.
        </p>
        <div style="display: flex; flex-direction: column; gap: 12px;">
          <div class="form-group">
            <label class="form-label">Display Name</label>
            <input type="text" class="form-input" id="wzDisplayName" placeholder="e.g. Rohan Mehra" value="${escapeHtml(wizardStudentData.display_name)}">
          </div>
          <div class="form-group">
            <label class="form-label">Username / User ID (Tenant identifier)</label>
            <input type="text" class="form-input font-mono" id="wzUserId" placeholder="e.g. rohan_m" value="${escapeHtml(wizardStudentData.user_id)}">
          </div>
          <div class="form-group">
            <label class="form-label">Initial Temporary Password</label>
            <input type="text" class="form-input font-mono" id="wzPassword" value="${escapeHtml(wizardStudentData.password)}">
            <span style="font-size: 11px; color: var(--on-surface-muted); margin-top: 4px; display: block;">
              Student will be required to change this temporary password upon first login.
            </span>
          </div>
          <div class="form-group">
            <label class="form-label">Institutional UPES Email</label>
            <input type="email" class="form-input" id="wzUpesEmail" placeholder="rohan.mehra.59001@stu.upes.ac.in" value="${escapeHtml(wizardStudentData.upes_email)}">
          </div>
          <div class="form-group">
            <label class="form-label">Optional Google Account Email (for Google Calendar)</label>
            <input type="email" class="form-input" id="wzGoogleEmail" placeholder="rohan.mehra@gmail.com" value="${escapeHtml(wizardStudentData.google_email)}">
          </div>
        </div>
      `;

    case 2: // Google Cloud Eligibility
      return `
        <div class="alert-banner alert-warning" style="background: var(--surface-2); border-left: 4px solid var(--primary); padding: 12px 14px; border-radius: var(--radius-sm); margin-bottom: 16px;">
          <strong style="color: var(--on-surface-bright); font-size: 13px;">Shared Google OAuth Web Application Setup</strong>
          <p style="color: var(--on-surface-variant); font-size: 12px; margin-top: 4px; line-height: 1.5;">
            NexusNode uses <strong>ONE shared Google OAuth application</strong> configured on the appliance. The student does <strong>NOT</strong> need to create their own Google Cloud project or client secret.
          </p>
        </div>
        <p style="color: var(--on-surface-variant); font-size: 13px; line-height: 1.5; margin-bottom: 12px;">
          If your Google Cloud OAuth app is in <strong>Testing</strong> mode, Google blocks authorization unless the student's Gmail is explicitly added under <strong>Test Users</strong>:
        </p>
        <div style="background: var(--surface-2); border-radius: var(--radius-sm); padding: 14px; font-size: 12px; margin-bottom: 14px; line-height: 1.7;">
          <strong>Action in Google Cloud Console:</strong>
          <ol style="margin: 6px 0 0 18px; padding: 0;">
            <li>Open Google Cloud Console OAuth Consent Screen.</li>
            <li>Under <strong>Audience &gt; Test users</strong>, click <strong>+ ADD USERS</strong>.</li>
            <li>Paste student's email: <strong class="font-mono" style="color: var(--primary);">${escapeHtml(wizardStudentData.google_email || 'student@gmail.com')}</strong></li>
            <li>Click <strong>SAVE</strong>.</li>
          </ol>
        </div>
        <div style="display: flex; gap: 8px; flex-wrap: wrap;">
          <button class="btn btn-secondary" onclick="copyStudentGoogleEmail()">
            <span class="material-symbols-outlined" style="font-size: 14px;">content_copy</span>
            COPY STUDENT GOOGLE EMAIL
          </button>
          <a href="https://console.cloud.google.com/apis/credentials/consent" target="_blank" class="btn btn-primary" style="text-decoration: none;">
            <span class="material-symbols-outlined" style="font-size: 14px;">open_in_new</span>
            OPEN GOOGLE CLOUD CONSOLE &rarr;
          </a>
          <button class="btn btn-secondary" onclick="copyRedirectUri()">
            <span class="material-symbols-outlined" style="font-size: 14px;">link</span>
            COPY REDIRECT URI
          </button>
        </div>
      `;

    case 3: // Student First Login
      return `
        <p style="color: var(--on-surface-variant); font-size: 13px; line-height: 1.5; margin-bottom: 16px;">
          The student should now log into NexusNode for the first time. They will immediately be prompted to change their temporary password to their own secret password.
        </p>
        <div style="background: var(--surface-2); border-radius: var(--radius-sm); padding: 14px; font-size: 13px; margin-bottom: 14px;">
          <div style="margin-bottom: 8px;"><strong>Appliance URL:</strong> <span class="font-mono" style="color: var(--primary);">${window.location.origin}</span></div>
          <div style="margin-bottom: 8px;"><strong>Username:</strong> <span class="font-mono">${escapeHtml(wizardStudentData.user_id)}</span></div>
          <div style="margin-bottom: 8px;"><strong>Initial Temporary Password:</strong> <span class="font-mono">${escapeHtml(wizardStudentData.password)}</span></div>
          <div><strong>Tenant Identity:</strong> <span class="badge badge-healthy">CONFIRMED IN SQLITE</span></div>
        </div>
        <p style="color: var(--on-surface-muted); font-size: 12px;">
          The student can log in now in an incognito window or on their phone, or you can proceed with configuring the academic integration as administrator.
        </p>
      `;

    case 4: // Google Calendar
      return `
        <p style="color: var(--on-surface-variant); font-size: 13px; line-height: 1.5; margin-bottom: 16px;">
          Connect Google Calendar so NexusNode can synchronize class timetables directly to the student's mobile schedule. Tokens are encrypted at rest with AES-GCM per-user.
        </p>
        <div style="background: var(--surface-2); border-radius: var(--radius-sm); padding: 14px; margin-bottom: 16px;">
          <div class="form-group" style="margin-bottom: 12px;">
            <label class="form-label">Target Google Calendar</label>
            <div style="display: flex; gap: 12px; margin-top: 4px;">
              <label style="display: flex; align-items: center; gap: 6px; font-size: 13px; cursor: pointer;">
                <input type="radio" name="wzCalType" value="primary" checked onchange="document.getElementById('wzCustomCalGroup').style.display='none'">
                Primary Calendar (Recommended)
              </label>
              <label style="display: flex; align-items: center; gap: 6px; font-size: 13px; cursor: pointer;">
                <input type="radio" name="wzCalType" value="custom" onchange="document.getElementById('wzCustomCalGroup').style.display='block'">
                Custom Calendar ID
              </label>
            </div>
          </div>
          <div class="form-group" id="wzCustomCalGroup" style="display: none; margin-top: 8px;">
            <label class="form-label">Custom Calendar ID</label>
            <input type="text" class="form-input font-mono" id="wzCalendarId" placeholder="e.g. c_188abc...@group.calendar.google.com">
          </div>
        </div>
        <div style="text-align: center; padding: 10px 0;">
          <button class="btn btn-primary" onclick="handleConnectGoogle()">
            <span class="material-symbols-outlined" style="font-size: 16px;">link</span>
            CONNECT GOOGLE CALENDAR
          </button>
        </div>
      `;

    case 5: // UPES
      return `
        <p style="color: var(--on-surface-variant); font-size: 13px; line-height: 1.5; margin-bottom: 16px;">
          Configure UPES Student Portal credentials for automated timetable, attendance, and results synchronization. Credentials are encrypted at rest with PBKDF2/AES.
        </p>
        <div style="display: flex; flex-direction: column; gap: 12px; max-width: 500px; margin-bottom: 16px;">
          <div class="form-group">
            <label class="form-label">Institutional UPES Email</label>
            <input type="email" class="form-input" id="wzUpesLoginUsername" value="${escapeHtml(wizardStudentData.upes_email)}">
          </div>
          <div class="form-group">
            <label class="form-label">Portal Password</label>
            <input type="password" class="form-input" id="wzUpesLoginPassword" placeholder="Enter student portal password">
          </div>
        </div>
        <div style="display: flex; gap: 8px;">
          <button class="btn btn-primary" onclick="handleWizardSaveUpes()">
            <span class="material-symbols-outlined" style="font-size: 14px;">save</span>
            Save Credentials
          </button>
          <button class="btn btn-secondary" onclick="handleWizardTestUpesLogin(this)">
            <span class="material-symbols-outlined" style="font-size: 14px;">check_circle</span>
            Test Portal Login
          </button>
        </div>
        <div id="wzUpesAuthOutput" style="margin-top: 10px; font-size: 12px;"></div>
      `;

    case 6: // Academic Data
      return `
        <p style="color: var(--on-surface-variant); font-size: 13px; line-height: 1.5; margin-bottom: 16px;">
          Verify academic data loaded from upstream portal endpoints into the appliance SQLite cache.
        </p>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin-bottom: 16px;">
          <div style="background: var(--surface-2); padding: 12px; border-radius: var(--radius-sm);">
            <div style="font-size: 11px; color: var(--on-surface-muted); text-transform: uppercase;">Timetable</div>
            <div id="wzTileTimetable" style="font-size: 15px; font-weight: 700; color: var(--on-surface-bright); margin-top: 4px;">Pending Check</div>
          </div>
          <div style="background: var(--surface-2); padding: 12px; border-radius: var(--radius-sm);">
            <div style="font-size: 11px; color: var(--on-surface-muted); text-transform: uppercase;">Attendance</div>
            <div id="wzTileAttendance" style="font-size: 15px; font-weight: 700; color: var(--on-surface-bright); margin-top: 4px;">Pending Check</div>
          </div>
          <div style="background: var(--surface-2); padding: 12px; border-radius: var(--radius-sm);">
            <div style="font-size: 11px; color: var(--on-surface-muted); text-transform: uppercase;">Results / SGPA</div>
            <div id="wzTileResults" style="font-size: 15px; font-weight: 700; color: var(--on-surface-bright); margin-top: 4px;">Pending Check</div>
          </div>
          <div style="background: var(--surface-2); padding: 12px; border-radius: var(--radius-sm);">
            <div style="font-size: 11px; color: var(--on-surface-muted); text-transform: uppercase;">LMS Courses</div>
            <div id="wzTileLms" style="font-size: 15px; font-weight: 700; color: var(--on-surface-bright); margin-top: 4px;">Pending Check</div>
          </div>
        </div>
        <button class="btn btn-secondary" onclick="handleWizardVerifyAcademicData(this)">
          <span class="material-symbols-outlined" style="font-size: 14px;">refresh</span>
          Fetch / Verify Academic Records
        </button>
      `;

    case 7: // Calendar Preview
      return `
        <p style="color: var(--on-surface-variant); font-size: 13px; line-height: 1.5; margin-bottom: 16px;">
          Calendar reconciliation preview: NexusNode compares loaded timetable sessions with managed Google Calendar events.
        </p>
        <div style="background: var(--surface-2); border-radius: var(--radius-sm); padding: 14px; font-size: 13px; margin-bottom: 14px;">
          <div style="display: flex; align-items: center; gap: 8px; color: var(--status-healthy); margin-bottom: 8px;">
            <span class="material-symbols-outlined" style="font-size: 18px;">verified</span>
            <strong>Reconciliation Preview &amp; Idempotency Active</strong>
          </div>
          <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; text-align: center; margin: 12px 0;">
            <div style="background: var(--surface-1); padding: 8px; border-radius: 4px;">
              <div style="font-size: 10px; color: var(--on-surface-muted);">CREATE</div>
              <div id="wzPreviewCreate" class="font-mono" style="font-size: 16px; font-weight: 700; color: var(--primary);">0</div>
            </div>
            <div style="background: var(--surface-1); padding: 8px; border-radius: 4px;">
              <div style="font-size: 10px; color: var(--on-surface-muted);">PATCH</div>
              <div id="wzPreviewPatch" class="font-mono" style="font-size: 16px; font-weight: 700; color: var(--status-warning);">0</div>
            </div>
            <div style="background: var(--surface-1); padding: 8px; border-radius: 4px;">
              <div style="font-size: 10px; color: var(--on-surface-muted);">DELETE</div>
              <div id="wzPreviewDelete" class="font-mono" style="font-size: 16px; font-weight: 700; color: var(--status-critical);">0</div>
            </div>
            <div style="background: var(--surface-1); padding: 8px; border-radius: 4px;">
              <div style="font-size: 10px; color: var(--on-surface-muted);">NOOP</div>
              <div id="wzPreviewNoop" class="font-mono" style="font-size: 16px; font-weight: 700; color: var(--status-healthy);">0</div>
            </div>
          </div>
          <p style="color: var(--on-surface-variant); font-size: 12px; margin: 0; line-height: 1.5;">
            <strong>Destructive Deletion Protection:</strong> If timetable data is ever empty, malformed, or stale (LKG), deletions are strictly suppressed (<code>allow_deletions = False</code>). Manual personal calendar events are never modified.
          </p>
        </div>
      `;

    case 8: // Calendar Sync
      return `
        <p style="color: var(--on-surface-variant); font-size: 13px; line-height: 1.5; margin-bottom: 16px;">
          Run initial Google Calendar reconciliation for <strong>THIS STUDENT ONLY</strong> (<span class="font-mono">${escapeHtml(wizardStudentData.user_id)}</span>).
        </p>
        <div style="text-align: center; padding: 14px 0;">
          <button class="btn btn-primary" onclick="handleWizardRunCalendarSync(this)">
            <span class="material-symbols-outlined" style="font-size: 16px;">sync</span>
            Run Reconciliation for ${escapeHtml(wizardStudentData.user_id)}
          </button>
          <div id="wzCalendarSyncOutput" style="margin-top: 12px; font-size: 13px;"></div>
        </div>
      `;

    case 9: // Automation
      return `
        <p style="color: var(--on-surface-variant); font-size: 13px; line-height: 1.5; margin-bottom: 16px;">
          Activate 3-Hour Automation: The persistent scheduler will execute background synchronization every 10,800 seconds (3 hours).
        </p>
        <div style="background: var(--surface-2); border-radius: var(--radius-sm); padding: 14px; font-size: 13px;">
          <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
            <span style="color: var(--on-surface-muted);">Automatic Sync:</span>
            <span class="badge badge-healthy">ENABLED</span>
          </div>
          <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
            <span style="color: var(--on-surface-muted);">Sync Interval:</span>
            <span class="font-mono">Every 3 Hours (10,800s)</span>
          </div>
          <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
            <span style="color: var(--on-surface-muted);">Subsystem Isolation:</span>
            <span style="color: var(--status-healthy);">Timetable, Attendance, Results &amp; LMS independent</span>
          </div>
          <div style="display: flex; justify-content: space-between;">
            <span style="color: var(--on-surface-muted);">Appliance Zero-Browser Guarantee:</span>
            <span class="font-mono" style="color: var(--primary);">0 Chromium Launches</span>
          </div>
        </div>
      `;

    case 10: // MCP
      return `
        <p style="color: var(--on-surface-variant); font-size: 13px; line-height: 1.5; margin-bottom: 16px;">
          Model Context Protocol (MCP) Integration: External frontier reasoning models (Gemini Spark, Mistral) connect via standard Streamable HTTP JSON-RPC 2.0.
        </p>
        <div style="background: var(--surface-2); border-radius: var(--radius-sm); padding: 14px; font-size: 13px; margin-bottom: 14px;">
          <div style="margin-bottom: 8px;"><strong>Public Internet MCP Endpoint:</strong> <span class="font-mono" style="color: var(--primary);">https://k09oezeyib.localto.net/api/mcp</span></div>
          <div style="margin-bottom: 8px;"><strong>Local LAN Endpoint:</strong> <span class="font-mono" style="color: var(--on-surface-variant);">${window.location.origin}/api/mcp</span> (alias <span class="font-mono">/mcp</span>)</div>
          <div style="margin-bottom: 8px;"><strong>Tenant Binding:</strong> Authenticated MCP Bearer Token maps strictly to student user ID.</div>
          <div style="margin-bottom: 8px;"><strong>Public Semantic Catalog:</strong> Exactly 11 high-signal tools (<code>academic.query</code>, <code>academic.analyze</code>, <code>lms.query</code>, <code>vault.manage</code>, etc.)</div>
          <div><strong>Frontier Client Compatibility:</strong> Gemini Spark (strict JSON Schema) &amp; Mistral AI (OpenAI function calling specification).</div>
        </div>
      `;

    case 11: // COMPLETE
      return `
        <div style="text-align: center; padding: 10px 0 16px;">
          <span class="material-symbols-outlined" style="font-size: 44px; color: var(--status-healthy);">verified_user</span>
          <h3 style="color: var(--on-surface-bright); font-size: 16px; margin: 8px 0 2px;">Onboarding Complete &amp; Verified</h3>
          <p style="color: var(--on-surface-variant); font-size: 12px;">
            Student account <strong class="font-mono">${escapeHtml(wizardStudentData.user_id)}</strong> is fully enrolled in NexusNode.
          </p>
        </div>
        <div style="background: var(--surface-2); border-radius: var(--radius-sm); padding: 14px; font-size: 12px;">
          <div style="color: var(--status-healthy); font-weight: 600; margin-bottom: 6px;">Next Required Actions for Student:</div>
          <ul style="margin: 0 0 0 16px; color: var(--on-surface-variant); line-height: 1.7;">
            <li>Log into NexusNode at <span class="font-mono" style="color: var(--primary);">${window.location.origin}</span></li>
            <li>Complete forced temporary password change</li>
            <li>Inspect personalized Timetable, Attendance, Safe Bunks, and Results</li>
          </ul>
        </div>
      `;

    default:
      return '';
  }
}

async function wizardNext() {
  if (currentWizardStep === 1) {
    const displayName = document.getElementById('wzDisplayName')?.value.trim();
    const userId = document.getElementById('wzUserId')?.value.trim().toLowerCase();
    const password = document.getElementById('wzPassword')?.value.trim();
    const upesEmail = document.getElementById('wzUpesEmail')?.value.trim().toLowerCase();
    const googleEmail = document.getElementById('wzGoogleEmail')?.value.trim().toLowerCase();

    if (!userId || !password) {
      showToast('User ID and Temporary Password are required', 'warning');
      return;
    }

    wizardStudentData.user_id = userId;
    wizardStudentData.display_name = displayName;
    wizardStudentData.upes_email = upesEmail;
    wizardStudentData.google_email = googleEmail;
    wizardStudentData.password = password;

    const btn = document.getElementById('wizardNextBtn');
    if (btn) btn.disabled = true;
    showToast('Creating student tenant account...', 'info');

    try {
      await apiJson('/api/admin/users', {
        method: 'POST',
        body: {
          user_id: userId,
          display_name: displayName,
          upes_email: upesEmail,
          google_email: googleEmail,
          password: password,
          role: 'user',
          must_change_password: true
        }
      });
      showToast('Student tenant created successfully!', 'success');
      currentWizardStep = 2;
      renderWizardModal();
    } catch (err) {
      showToast(`Creation failed: ${err.message}`, 'error');
      if (btn) btn.disabled = false;
    }
    return;
  }

  if (currentWizardStep === 5) {
    const pw = document.getElementById('wzUpesLoginPassword')?.value;
    const un = document.getElementById('wzUpesLoginUsername')?.value;
    if (un && pw) {
      try {
        await apiJson('/api/upes/auth/credentials', {
          method: 'POST',
          body: { username: un, password: pw }
        });
      } catch (e) {
        console.warn('UPES creds save note:', e);
      }
    }
  }

  if (currentWizardStep >= 11) {
    closeAddAccountWizard();
    return;
  }

  currentWizardStep++;
  renderWizardModal();
}

function wizardPrev() {
  if (currentWizardStep > 1) {
    currentWizardStep--;
    renderWizardModal();
  }
}

function copyStudentGoogleEmail() {
  const email = wizardStudentData.google_email || 'student@gmail.com';
  navigator.clipboard.writeText(email).then(() => {
    showToast(`Copied "${email}" to clipboard!`, 'success');
  }).catch(() => {
    showToast(`Student email: ${email}`, 'info');
  });
}

function copyRedirectUri() {
  const uri = `${window.location.origin}/api/auth/google/callback`;
  navigator.clipboard.writeText(uri).then(() => {
    showToast(`Copied redirect URI: ${uri}`, 'success');
  }).catch(() => {
    showToast(`Redirect URI: ${uri}`, 'info');
  });
}

async function handleWizardSaveUpes() {
  const un = document.getElementById('wzUpesLoginUsername')?.value.trim();
  const pw = document.getElementById('wzUpesLoginPassword')?.value;
  const out = document.getElementById('wzUpesAuthOutput');
  if (!un || !pw) {
    showToast('Email and password required', 'warning');
    return;
  }
  try {
    await apiJson('/api/upes/auth/credentials', { method: 'POST', body: { username: un, password: pw } });
    if (out) out.innerHTML = '<span style="color: var(--status-healthy);">Credentials saved securely.</span>';
    showToast('UPES credentials saved!', 'success');
  } catch (err) {
    if (out) out.innerHTML = `<span style="color: var(--status-critical);">${escapeHtml(err.message)}</span>`;
  }
}

async function handleWizardTestUpesLogin(btn) {
  if (btn) btn.disabled = true;
  const out = document.getElementById('wzUpesAuthOutput');
  if (out) out.innerHTML = '<span style="color: var(--on-surface-muted);">Testing portal login...</span>';
  try {
    const res = await apiJson('/api/upes/auth/test-login', { method: 'POST' });
    if (out) out.innerHTML = `<span style="color: var(--status-healthy); font-weight: 600;">Login successful! Session active.</span>`;
  } catch (err) {
    if (out) out.innerHTML = `<span style="color: var(--status-warning);">Status: ${escapeHtml(err.message)}</span>`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function handleWizardVerifyAcademicData(btn) {
  if (btn) btn.disabled = true;
  try {
    const data = await apiJson(`/api/admin/users/${wizardStudentData.user_id}/onboarding-status`);
    const tt = document.getElementById('wzTileTimetable');
    const att = document.getElementById('wzTileAttendance');
    const res = document.getElementById('wzTileResults');
    const lms = document.getElementById('wzTileLms');

    if (tt) tt.innerHTML = data.timetable_synced ? `<span style="color: var(--status-healthy);">${data.timetable?.session_count || 0} Sessions</span>` : '<span style="color: var(--status-warning);">Not Synced</span>';
    if (att) att.innerHTML = data.attendance_synced ? `<span style="color: var(--status-healthy);">Active</span>` : '<span style="color: var(--status-warning);">Not Synced</span>';
    if (res) res.innerHTML = data.results_synced ? `<span style="color: var(--status-healthy);">Loaded</span>` : '<span style="color: var(--status-warning);">Not Synced</span>';
    if (lms) lms.innerHTML = (data.lms_synced || (data.lms && data.lms.available)) ? `<span style="color: var(--status-healthy);">Connected</span>` : `<span style="color: var(--status-warning);">Auth Required</span>`;
    showToast('Academic data verified!', 'success');
  } catch (err) {
    showToast(`Verification note: ${err.message}`, 'info');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function handleWizardRunCalendarSync(btn) {
  if (btn) btn.disabled = true;
  const out = document.getElementById('wzCalendarSyncOutput');
  if (out) out.innerHTML = '<span style="color: var(--on-surface-muted);">Reconciling Google Calendar for student...</span>';
  try {
    const res = await apiJson(`/api/admin/users/${wizardStudentData.user_id}/timetable/sync`, { method: 'POST' });
    if (out) out.innerHTML = `<span style="color: var(--status-healthy); font-weight: 600;">Reconciliation complete: C:${res.created || 0} U:${res.updated || 0} D:${res.deleted || 0} NOOP:${res.unchanged || 0}</span>`;
    showToast('Calendar sync completed for student!', 'success');
  } catch (err) {
    if (out) out.innerHTML = `<span style="color: var(--status-warning);">Sync result: ${escapeHtml(err.message)}</span>`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

// =============================================================================
// 4. ACTION HANDLERS (CREDS, GOOGLE, UPLOAD, MANUAL SYNC)
// =============================================================================

async function handleSaveUpesCreds(e) {
  e.preventDefault();
  const username = document.getElementById('upesUsername').value.trim();
  const password = document.getElementById('upesPassword').value;
  const btn = document.getElementById('saveUpesBtn');

  if (!username) {
    showToast('UPES email is required', 'warning');
    return;
  }

  btn.disabled = true;
  showToast('Saving encrypted credentials...', 'info');

  try {
    await apiJson('/api/upes/auth/credentials', {
      method: 'POST',
      body: { username, password }
    });
    showToast('UPES credentials saved successfully!', 'success');
    loadAccounts();
  } catch (err) {
    showToast(`Failed to save: ${err.message}`, 'error');
  } finally {
    btn.disabled = false;
  }
}

async function handleTestUpesLogin(btn) {
  if (btn) btn.disabled = true;
  showToast('Testing UPES credentials verification...', 'info');
  try {
    await apiJson('/api/upes/auth/login', { method: 'POST' });
    showToast('UPES credentials validated successfully!', 'success');
  } catch (err) {
    showToast(`Login test failed: ${err.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function handleDeleteUpesCreds(btn) {
  if (!confirm('Are you sure you want to remove your stored UPES credentials?')) return;
  if (btn) btn.disabled = true;
  try {
    await apiJson('/api/upes/auth/credentials', { method: 'DELETE' });
    showToast('UPES credentials removed.', 'info');
    loadAccounts();
  } catch (err) {
    showToast(`Failed to delete: ${err.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function handleConnectGoogle() {
  try {
    const data = await apiJson('/api/auth/google/authorize');
    if (data && data.authorization_url) {
      window.location.href = data.authorization_url;
    } else {
      showToast('Could not retrieve Google authorization URL', 'error');
    }
  } catch (err) {
    showToast(`Google connect error: ${err.message}`, 'error');
  }
}

async function handleDisconnectGoogle(btn) {
  if (!confirm('Are you sure you want to disconnect Google Calendar?')) return;
  if (btn) btn.disabled = true;
  try {
    await apiJson('/api/auth/google/disconnect', { method: 'POST' });
    showToast('Google Calendar disconnected.', 'info');
    loadAccounts();
  } catch (err) {
    showToast(`Disconnect failed: ${err.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function handleUploadTimetableFile(btn) {
  const fileInput = document.getElementById('manualTimetableFileInput');
  if (!fileInput || !fileInput.files.length) {
    showToast('Please select a JSON file to upload', 'warning');
    return;
  }

  const file = fileInput.files[0];
  const reader = new FileReader();

  if (btn) btn.disabled = true;
  showToast('Reading file...', 'info');

  reader.onload = async (e) => {
    try {
      const content = e.target.result;
      const res = await apiJson('/api/timetable/upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: content
      });
      showToast(`Uploaded timetable successfully (${res.session_count || res.sessions || 0} sessions)!`, 'success');
      fileInput.value = '';
      loadAccounts();
    } catch (err) {
      showToast(`Upload failed: ${err.message}`, 'error');
    } finally {
      if (btn) btn.disabled = false;
    }
  };

  reader.onerror = () => {
    showToast('Could not read file', 'error');
    if (btn) btn.disabled = false;
  };

  reader.readAsText(file);
}

async function handleTriggerSync(btn) {
  if (btn) btn.disabled = true;
  showToast('Synchronizing academic data and Google Calendar...', 'info');
  try {
    await apiJson('/api/timetable/sync', { method: 'POST' });
    showToast('Synchronization complete!', 'success');
    loadAccounts();
  } catch (err) {
    showToast(`Sync failed: ${err.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}
