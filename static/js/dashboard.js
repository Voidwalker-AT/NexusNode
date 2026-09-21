/**
 * NexusNode — Dashboard View Controller
 * Phase 4.2A Product Rebase
 * Fast, read-only summary aggregation (0 browser, 0 live UPES requests on load).
 */

async function loadDashboard() {
  const container = document.getElementById('dashboardContent');
  if (!container) return;

  // 1. Instant render from in-memory cache if available (0ms)
  const cached = window.NexusStateCache ? window.NexusStateCache.get('dashboard') : null;
  if (cached) {
    renderDashboard(cached);
  } else if (!container.children.length) {
    container.innerHTML = '<div style="color: var(--on-surface-muted); padding: 24px 0;">Loading dashboard summary...</div>';
  }

  try {
    const data = await apiJson('/api/dashboard/summary');
    if (window.NexusStateCache) {
      window.NexusStateCache.set('dashboard', data);
    }
    renderDashboard(data);
  } catch (err) {
    if (!cached) {
      console.error('[Dashboard] Error loading dashboard summary:', err);
      container.innerHTML = `
        <div class="tech-card" style="border-color: var(--status-critical);">
          <div class="tech-card-header">
            <span class="tech-card-title" style="color: var(--status-critical);">
              <span class="material-symbols-outlined">error</span>
              Dashboard Load Error
            </span>
            <button class="btn btn-secondary" onclick="loadDashboard()">Retry</button>
          </div>
          <p style="color: var(--on-surface-variant); font-size: 13px;">${escapeHtml(err.message)}</p>
        </div>
      `;
    }
  }
}

function renderDashboard(data) {
  const container = document.getElementById('dashboardContent');
  if (!container) return;

  const app = data.appliance || {};
  const acc = data.account || {};
  const sched = data.schedule || {};
  const att = data.attendance || {};
  const res = data.results || {};
  const mcp = data.mcp || {};
  const alerts = data.alerts || [];

  // Update header appliance badge & status dot
  const statusLabel = document.getElementById('headerConnLabel');
  if (statusLabel) {
    statusLabel.textContent = app.status || 'ONLINE';
  }

  // Generate Actionable Alerts Banner if alerts exist
  let alertsHtml = '';
  if (alerts.length > 0) {
    alertsHtml = `
      <div class="dashboard-alerts-container" style="display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px;">
        ${alerts.map(a => `
          <div class="alert-banner alert-${escapeHtml(a.severity || 'warning')}" style="
            background: var(--surface-1);
            border-left: 4px solid ${a.severity === 'critical' ? 'var(--status-critical)' : 'var(--status-warning)'};
            border-top: 1px solid var(--border-subtle);
            border-right: 1px solid var(--border-subtle);
            border-bottom: 1px solid var(--border-subtle);
            border-radius: var(--radius-md);
            padding: 12px 16px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
          ">
            <div style="display: flex; align-items: center; gap: 10px;">
              <span class="material-symbols-outlined" style="color: ${a.severity === 'critical' ? 'var(--status-critical)' : 'var(--status-warning)'};">
                ${a.severity === 'critical' ? 'error' : 'warning'}
              </span>
              <div>
                <strong style="color: var(--on-surface-bright); font-size: 13px;">${escapeHtml(a.title)}</strong>
                <p style="color: var(--on-surface-variant); font-size: 12px; margin-top: 2px;">${escapeHtml(a.message)}</p>
              </div>
            </div>
            ${a.action_view ? `
              <button class="btn btn-secondary" style="white-space: nowrap;" onclick="switchTab('${escapeHtml(a.action_view)}')">
                Resolve
              </button>
            ` : ''}
          </div>
        `).join('')}
      </div>
    `;
  }

  // Next class details
  let nextClassHtml = `
    <div style="color: var(--on-surface-muted); font-size: 13px; padding: 12px 0;">
      No more classes scheduled for today.
    </div>
  `;
  if (sched.next_class) {
    const nc = sched.next_class;
    nextClassHtml = `
      <div style="background: var(--surface-2); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 12px; margin-top: 8px;">
        <div style="display: flex; justify-content: space-between; align-items: flex-start;">
          <div>
            <div style="font-weight: 600; color: var(--on-surface-bright); font-size: 14px;">${escapeHtml(nc.course_name || 'Upcoming Class')}</div>
            <div style="color: var(--on-surface-variant); font-size: 12px; margin-top: 2px;">
              ${escapeHtml(nc.room ? 'Room: ' + nc.room : '')} ${escapeHtml(nc.faculty ? ' · ' + nc.faculty : '')}
            </div>
          </div>
          <span class="badge badge-primary font-mono" style="font-size: 11px;">
            ${escapeHtml(nc.start_time || '')} - ${escapeHtml(nc.end_time || '')}
          </span>
        </div>
      </div>
    `;
  }

  // Attendance details
  let attPercentageDisplay = '—';
  let attBadge = '<span class="status-badge badge-stale">NO DATA</span>';
  if (att.overall_percentage !== null && att.overall_percentage !== undefined) {
    const pct = parseFloat(att.overall_percentage).toFixed(1);
    attPercentageDisplay = `${pct}%`;
    if (pct >= 80) {
      attBadge = renderStatusBadge('SAFE');
    } else if (pct >= 75) {
      attBadge = renderStatusBadge('WARNING');
    } else {
      attBadge = renderStatusBadge('CRITICAL');
    }
  }

  // RAM meter
  const ramUsed = app.memory?.used_mb || 0;
  const ramTotal = app.memory?.total_mb || 3800;
  const ramPct = app.memory?.percent || Math.round((ramUsed / ramTotal) * 100);

  container.innerHTML = `
    ${alertsHtml}

    <div class="dashboard-grid" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px;">
      
      <!-- Card 1: Appliance Status -->
      <div class="tech-card">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">dns</span>
            Appliance Health
          </span>
          ${renderStatusBadge(app.status || 'HEALTHY')}
        </div>
        <div style="display: flex; flex-direction: column; gap: 10px;">
          <div>
            <div style="display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 4px;">
              <span style="color: var(--on-surface-variant);">Available RAM</span>
              <span class="font-mono" style="color: var(--primary);">${app.memory?.available_mb || 0} MB / ${ramTotal} MB</span>
            </div>
            <div style="height: 6px; background: var(--surface-3); border-radius: var(--radius-full); overflow: hidden;">
              <div style="width: ${ramPct}%; height: 100%; background: ${ramPct > 85 ? 'var(--status-critical)' : (ramPct > 70 ? 'var(--status-warning)' : 'var(--primary)')}; transition: width 0.3s ease;"></div>
            </div>
          </div>
          <div style="display: flex; justify-content: space-between; font-size: 12px; border-top: 1px solid var(--border-subtle); padding-top: 8px;">
            <span style="color: var(--on-surface-muted);">Hardware Device</span>
            <span style="color: var(--on-surface);">${escapeHtml(app.device || 'TECNO BG6')}</span>
          </div>
          <div style="display: flex; justify-content: space-between; font-size: 12px;">
            <span style="color: var(--on-surface-muted);">System Uptime</span>
            <span class="font-mono" style="color: var(--on-surface);">${escapeHtml(app.uptime || '—')}</span>
          </div>
          <div style="display: flex; justify-content: space-between; font-size: 12px;">
            <span style="color: var(--on-surface-muted);">Software Version</span>
            <span class="font-mono" style="color: var(--on-surface);">v${escapeHtml(app.version || '4.2.0')}</span>
          </div>
        </div>
      </div>

      <!-- Card 2: Academic Account Health -->
      <div class="tech-card">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">account_circle</span>
            Academic Accounts
          </span>
          <button class="btn btn-secondary" style="padding: 4px 8px; font-size: 11px; min-height: 28px;" onclick="switchTab('accounts')">
            Manage
          </button>
        </div>
        <div style="display: flex; flex-direction: column; gap: 10px;">
          <div style="display: flex; justify-content: space-between; align-items: center; font-size: 13px;">
            <span style="display: flex; align-items: center; gap: 6px;">
              <span class="material-symbols-outlined" style="font-size: 16px; color: ${acc.upes_configured ? 'var(--status-healthy)' : 'var(--status-warning)'};">
                ${acc.upes_configured ? 'check_circle' : 'pending'}
              </span>
              UPES Portal Sync
            </span>
            <span class="font-mono" style="font-size: 11px; color: ${acc.upes_configured ? 'var(--status-healthy)' : 'var(--on-surface-muted)'};">
              ${acc.upes_configured ? 'CONFIGURED' : 'NOT LINKED'}
            </span>
          </div>
          <div style="display: flex; justify-content: space-between; align-items: center; font-size: 13px;">
            <span style="display: flex; align-items: center; gap: 6px;">
              <span class="material-symbols-outlined" style="font-size: 16px; color: ${acc.google_needs_reauth ? 'var(--status-warning)' : (acc.google_connected ? 'var(--status-healthy)' : 'var(--on-surface-muted)')};">
                ${acc.google_needs_reauth ? 'warning' : (acc.google_connected ? 'check_circle' : 'link_off')}
              </span>
              Google Calendar
            </span>
            <span class="font-mono" style="font-size: 11px; color: ${acc.google_needs_reauth ? 'var(--status-warning)' : (acc.google_connected ? 'var(--status-healthy)' : 'var(--on-surface-muted)')};">
              ${acc.google_needs_reauth ? 'REAUTHORIZE' : (acc.google_connected ? 'CONNECTED' : 'DISCONNECTED')}
            </span>
          </div>
          <div style="display: flex; justify-content: space-between; font-size: 12px; border-top: 1px solid var(--border-subtle); padding-top: 8px;">
            <span style="color: var(--on-surface-muted);">Active Timetable Source</span>
            <span style="color: var(--on-surface); text-transform: uppercase;">${escapeHtml(acc.timetable_source || 'None')}</span>
          </div>
          <div style="display: flex; justify-content: space-between; font-size: 12px;">
            <span style="color: var(--on-surface-muted);">Last Sync</span>
            <span class="font-mono" style="color: var(--on-surface);">${formatTimeAgo(acc.last_synced_at)}</span>
          </div>
        </div>
      </div>

      <!-- Card 3: Today's Schedule & Next Class -->
      <div class="tech-card">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">schedule</span>
            Schedule Overview
          </span>
          <span class="font-mono" style="font-size: 11px; color: var(--primary);">
            ${sched.today_classes_count || 0} class${sched.today_classes_count === 1 ? '' : 'es'} today
          </span>
        </div>
        ${nextClassHtml}
        <div style="display: flex; justify-content: flex-end; margin-top: 10px;">
          <button class="btn btn-secondary" style="font-size: 11px; padding: 4px 10px; min-height: 28px;" onclick="switchTab('academics', 'timetable')">
            View Full Timetable &rarr;
          </button>
        </div>
      </div>

      <!-- Card 4: Attendance Pulse -->
      <div class="tech-card">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">co_present</span>
            Attendance Pulse
          </span>
          ${attBadge}
        </div>
        <div style="display: flex; align-items: center; justify-content: space-between; padding: 6px 0;">
          <div>
            <div class="font-mono" style="font-size: 32px; font-weight: 700; color: var(--on-surface-bright); line-height: 1.1;">
              ${attPercentageDisplay}
            </div>
            <div style="color: var(--on-surface-muted); font-size: 11px; margin-top: 2px;">
              Semester Aggregate Across ${att.total_subjects || 0} Modules
            </div>
          </div>
          <div style="text-align: right;">
            <div class="font-mono" style="font-size: 18px; font-weight: 600; color: ${att.at_risk_subjects > 0 ? 'var(--status-critical)' : 'var(--status-healthy)'};">
              ${att.at_risk_subjects || 0}
            </div>
            <div style="color: var(--on-surface-muted); font-size: 11px;">
              Modules &lt; 75%
            </div>
          </div>
        </div>
        <div style="display: flex; justify-content: flex-end; border-top: 1px solid var(--border-subtle); padding-top: 10px; margin-top: 6px;">
          <button class="btn btn-secondary" style="font-size: 11px; padding: 4px 10px; min-height: 28px;" onclick="switchTab('academics', 'attendance')">
            Safe Bunk Planner &rarr;
          </button>
        </div>
      </div>

      <!-- Card 5: MCP Appliance Surface -->
      <div class="tech-card">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">hub</span>
            MCP Gateway Surface
          </span>
          ${renderStatusBadge(mcp.status || 'HEALTHY')}
        </div>
        <div style="display: flex; flex-direction: column; gap: 8px;">
          <div style="display: flex; justify-content: space-between; font-size: 12px;">
            <span style="color: var(--on-surface-muted);">Catalog Version</span>
            <span class="font-mono" style="color: var(--primary); font-weight: 600;">${escapeHtml(mcp.catalog || 'nexus-semantic-v1')}</span>
          </div>
          <div style="display: flex; justify-content: space-between; font-size: 12px;">
            <span style="color: var(--on-surface-muted);">Semantic Tools</span>
            <span class="font-mono" style="color: var(--on-surface);">${mcp.tools_count || 11} Registered</span>
          </div>
          <div style="display: flex; justify-content: space-between; font-size: 12px;">
            <span style="color: var(--on-surface-muted);">Protocol Transport</span>
            <span class="font-mono" style="color: var(--on-surface);">Streamable HTTP / SSE</span>
          </div>
          <div style="display: flex; justify-content: flex-end; border-top: 1px solid var(--border-subtle); padding-top: 10px; margin-top: 4px;">
            <button class="btn btn-secondary" style="font-size: 11px; padding: 4px 10px; min-height: 28px;" onclick="switchTab('mcp')">
              Open MCP Console &rarr;
            </button>
          </div>
        </div>
      </div>

      <!-- Card 6: Academic Performance & CGPA -->
      <div class="tech-card">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">grade</span>
            Academic Performance
          </span>
          ${renderStatusBadge(res.available ? 'HEALTHY' : 'NO DATA')}
        </div>
        <div style="display: flex; align-items: center; justify-content: space-between; padding: 6px 0;">
          <div>
            <div class="font-mono" style="font-size: 32px; font-weight: 700; color: var(--on-surface-bright); line-height: 1.1;">
              ${res.cgpa !== null && res.cgpa !== undefined ? parseFloat(res.cgpa).toFixed(2) : '—'} <span style="font-size: 14px; color: var(--on-surface-muted); font-weight: 400;">/ 10.0</span>
            </div>
            <div style="color: var(--on-surface-muted); font-size: 11px; margin-top: 2px;">
              Cumulative CGPA Across ${res.semesters_count || 0} Semesters
            </div>
          </div>
          <div style="text-align: right;">
            <div class="font-mono" style="font-size: 18px; font-weight: 600; color: var(--primary);">
              ${res.latest_sgpa !== null && res.latest_sgpa !== undefined ? parseFloat(res.latest_sgpa).toFixed(2) : '—'}
            </div>
            <div style="color: var(--on-surface-muted); font-size: 11px;">
              Latest SGPA (${res.earned_credits || 0} Cr)
            </div>
          </div>
        </div>
        <div style="display: flex; justify-content: flex-end; border-top: 1px solid var(--border-subtle); padding-top: 10px; margin-top: 6px;">
          <button class="btn btn-secondary" style="font-size: 11px; padding: 4px 10px; min-height: 28px;" onclick="switchTab('academics', 'results')">
            View Results & SGPA &rarr;
          </button>
        </div>
      </div>

    </div>
  `;
}
