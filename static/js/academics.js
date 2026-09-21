/**
 * NexusNode — Academics View Controller
 * Phase 4.2A Product Rebase
 * Subtabs: Overview, Timetable, Attendance (with Safe Bunks), LMS, Calendar, Results (Coming later).
 */

let activeAcademicsSubtab = 'overview';
let cachedAttendanceData = null;
let cachedTimetableSessions = [];
let cachedLmsCourses = [];

function renderProvenanceBadge(state, timestamp) {
  const s = (state || 'NOT_SYNCED').toUpperCase();
  let badgeClass = 'badge-secondary';
  let label = s;
  let icon = 'help';

  if (s === 'LIVE' || s === 'LIVE DATA') {
    badgeClass = 'badge-healthy';
    label = 'LIVE DATA';
    icon = 'check_circle';
  } else if (s === 'CACHED' || s === 'CACHED DATA') {
    badgeClass = 'badge-primary';
    label = 'CACHED DATA';
    icon = 'database';
  } else if (s === 'STALE' || s === 'STALE DATA') {
    badgeClass = 'badge-warning';
    label = 'STALE DATA';
    icon = 'update';
  } else if (s === 'NOT_SYNCED' || s === 'NOT YET SYNCED') {
    badgeClass = 'badge-secondary';
    label = 'NOT YET SYNCED';
    icon = 'cloud_off';
  } else if (s === 'AUTH_REQUIRED') {
    badgeClass = 'badge-warning';
    label = 'AUTH REQUIRED';
    icon = 'lock';
  } else if (s === 'NO_DATA' || s === 'NO DATA AVAILABLE') {
    badgeClass = 'badge-secondary';
    label = 'NO DATA';
    icon = 'block';
  } else if (s === 'ERROR') {
    badgeClass = 'badge-critical';
    label = 'ERROR';
    icon = 'error';
  }

  const timeStr = timestamp ? ` · ${formatTimeAgo(timestamp)}` : '';
  return `
    <span class="status-badge ${badgeClass}" style="display: inline-flex; align-items: center; gap: 4px; font-size: 11px; padding: 3px 8px;">
      <span class="material-symbols-outlined" style="font-size: 13px;">${icon}</span>
      ${label}${timeStr}
    </span>
  `;
}

function switchAcademicsSubtab(subtabId) {
  activeAcademicsSubtab = subtabId;
  const buttons = document.querySelectorAll('.academics-subnav .subnav-btn');
  buttons.forEach(b => {
    b.classList.toggle('active', b.getAttribute('data-subtab') === subtabId);
  });

  const panes = document.querySelectorAll('.academics-subpane');
  panes.forEach(p => {
    p.classList.toggle('active', p.id === `academics-pane-${subtabId}`);
  });

  if (subtabId === 'overview') loadAcademicsOverview();
  else if (subtabId === 'timetable') loadAcademicsTimetable();
  else if (subtabId === 'attendance') loadAcademicsAttendance();
  else if (subtabId === 'lms') loadAcademicsLMS();
  else if (subtabId === 'calendar') loadAcademicsCalendar();
  else if (subtabId === 'results') loadAcademicsResults();
}

async function loadAcademics() {
  switchAcademicsSubtab(activeAcademicsSubtab);
}

// -----------------------------------------------------------------------------
// SUBTAB 1: OVERVIEW
// -----------------------------------------------------------------------------
async function loadAcademicsOverview() {
  const container = document.getElementById('academics-pane-overview');
  if (!container) return;

  const cached = window.NexusStateCache ? window.NexusStateCache.get('academics-overview') : null;
  if (cached) {
    renderAcademicsOverview(cached);
  } else if (!container.children.length) {
    container.innerHTML = '<div style="color: var(--on-surface-muted); padding: 24px 0;">Loading academic telemetry and provenance...</div>';
  }

  try {
    const snap = await apiJson('/api/academics/snapshot');
    if (window.NexusStateCache) {
      window.NexusStateCache.set('academics-overview', snap);
    }
    renderAcademicsOverview(snap);
  } catch (err) {
    if (!cached) {
      container.innerHTML = `<div style="color: var(--status-critical); padding: 16px;">Failed to load academic overview: ${escapeHtml(err.message)}</div>`;
    }
  }
}

function renderAcademicsOverview(snap) {
  const container = document.getElementById('academics-pane-overview');
  if (!container) return;

  const tt = snap.timetable || {};
  const att = snap.attendance || {};
  const res = snap.results || {};
  const lms = snap.lms || {};

  const attOverall = att.overall || {};
  const nextClass = tt.next_class;
  const sessionsCount = tt.count || 0;
  const lmsOk = Boolean(lms.ok);
  const lmsCount = lms.courses_count || 0;

  // Attendance meters HTML
  let attHtml = '';
  const attPct = attOverall.attendance_percentage !== undefined ? attOverall.attendance_percentage : attOverall.overall_percentage;
  if (attPct !== null && attPct !== undefined) {
    const attended = attOverall.attended_classes || attOverall.total_attended || 0;
    const conducted = attOverall.conducted_classes || attOverall.total_conducted || 0;
    const criticalCount = attOverall.critical_subjects !== undefined ? attOverall.critical_subjects : (attOverall.critical_count || 0);
    const safeBunks = attOverall.total_safe_bunks !== undefined ? attOverall.total_safe_bunks : (attOverall.overall_safe_bunks || 0);

    attHtml = `
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-top: 10px;">
        <div class="meter-box">
          <span class="meter-label">Overall Attendance</span>
          <span class="meter-val font-mono" style="color: ${attPct >= 75 ? 'var(--status-healthy)' : 'var(--status-critical)'};">
            ${parseFloat(attPct).toFixed(1)}%
          </span>
        </div>
        <div class="meter-box">
          <span class="meter-label">Classes Attended</span>
          <span class="meter-val font-mono">${attended} / ${conducted}</span>
        </div>
        <div class="meter-box">
          <span class="meter-label">Subjects Below 75%</span>
          <span class="meter-val font-mono" style="color: ${criticalCount > 0 ? 'var(--status-critical)' : 'var(--status-healthy)'};">
            ${criticalCount}
          </span>
        </div>
        <div class="meter-box">
          <span class="meter-label">Total Safe Bunks</span>
          <span class="meter-val font-mono" style="color: var(--primary);">${safeBunks}</span>
        </div>
      </div>
    `;
  } else {
    attHtml = `
      <div style="color: var(--on-surface-muted); font-size: 13px; padding: 14px 0;">
        No attendance records synchronized yet. Click <strong>Sync UPES Attendance</strong> in the Attendance tab.
      </div>
    `;
  }

  // Results snapshot HTML
  let resultsHtml = '';
  const cgpaVal = res ? res.cgpa : null;
  if (cgpaVal !== null && cgpaVal !== undefined) {
    const earnedCr = res.total_credits_earned || 0;
    const semCount = res.semesters_count || 0;
    resultsHtml = `
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-top: 10px;">
        <div class="meter-box">
          <span class="meter-label">Cumulative CGPA</span>
          <span class="meter-val font-mono" style="color: var(--primary); font-weight: 700;">
            ${parseFloat(cgpaVal).toFixed(2)}
          </span>
        </div>
        <div class="meter-box">
          <span class="meter-label">Earned Credits</span>
          <span class="meter-val font-mono" style="color: var(--status-healthy);">${parseFloat(earnedCr).toFixed(1)}</span>
        </div>
        <div class="meter-box">
          <span class="meter-label">Semesters Recorded</span>
          <span class="meter-val font-mono">${semCount}</span>
        </div>
      </div>
    `;
  } else {
    resultsHtml = `
      <div style="color: var(--on-surface-muted); font-size: 13px; padding: 14px 0;">
        No official grade records synchronized yet. Click <strong>Sync Results</strong> in the Results tab.
      </div>
    `;
  }

  container.innerHTML = `
    <div style="display: flex; flex-direction: column; gap: 16px;">
      
      <!-- Top Provenance & Fast Action Header -->
      <div class="tech-card" style="border-color: var(--border-medium);">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">dataset</span>
            Academic Subsystem Provenance Matrix
          </span>
          <button class="btn btn-primary" style="font-size: 11px; padding: 5px 12px; min-height: 28px;" onclick="refreshAllAcademics(this)">
            <span class="material-symbols-outlined" style="font-size: 14px;">sync</span>
            Refresh All Academics
          </button>
        </div>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; font-size: 12px;">
          <div style="background: var(--surface-2); padding: 10px; border-radius: var(--radius-sm);">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
              <strong>Timetable</strong>
              ${renderProvenanceBadge(sessionsCount > 0 ? (tt.is_stale ? 'STALE' : 'CACHED') : 'NOT_SYNCED', tt.last_synced_at)}
            </div>
            <span style="color: var(--on-surface-variant);">${sessionsCount} sessions loaded</span>
          </div>
          <div style="background: var(--surface-2); padding: 10px; border-radius: var(--radius-sm);">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
              <strong>Attendance</strong>
              ${renderProvenanceBadge(att.subjects_count > 0 ? 'CACHED' : 'NOT_SYNCED', att.as_of_date)}
            </div>
            <span style="color: var(--on-surface-variant);">${att.subjects_count || 0} subjects tracked</span>
          </div>
          <div style="background: var(--surface-2); padding: 10px; border-radius: var(--radius-sm);">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
              <strong>Results</strong>
              ${renderProvenanceBadge((res.semesters_count || 0) > 0 ? 'CACHED' : 'NOT_SYNCED', res.last_synced_at)}
            </div>
            <span style="color: var(--on-surface-variant);">${res.semesters_count || 0} semester records</span>
          </div>
          <div style="background: var(--surface-2); padding: 10px; border-radius: var(--radius-sm);">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
              <strong>LMS & Materials</strong>
              ${renderProvenanceBadge(lmsOk ? 'LIVE' : 'AUTH_REQUIRED', lms.fetched_at)}
            </div>
            <span style="color: var(--on-surface-variant);">${lmsOk ? `${lmsCount} courses enrolled` : 'Auth Required'}</span>
          </div>
        </div>
      </div>

      <!-- Next Scheduled Class Card -->
      <div class="tech-card">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">schedule</span>
            Next Class Schedule
          </span>
          <button class="btn btn-secondary" style="font-size: 11px; padding: 3px 8px; min-height: 26px;" onclick="switchAcademicsSubtab('timetable')">
            Full Timetable &rarr;
          </button>
        </div>
        ${nextClass ? `
          <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; padding: 4px 0;">
            <div>
              <div style="font-size: 15px; font-weight: 600; color: var(--on-surface-bright);">
                ${escapeHtml(nextClass.course_name || nextClass.course || nextClass.subject || 'Class')}
              </div>
              <div style="color: var(--on-surface-variant); font-size: 12px; margin-top: 4px;">
                ${escapeHtml(nextClass.course_code ? nextClass.course_code + ' · ' : '')}
                Room: <strong>${escapeHtml(nextClass.room || 'TBD')}</strong>
                ${escapeHtml(nextClass.faculty ? ' · ' + nextClass.faculty : '')}
              </div>
            </div>
            <div style="text-align: right;">
              <div class="font-mono" style="font-size: 15px; color: var(--primary); font-weight: 700;">
                ${escapeHtml(nextClass.start_time || nextClass.start || '')} - ${escapeHtml(nextClass.end_time || nextClass.end || '')}
              </div>
              <div style="color: var(--on-surface-muted); font-size: 11px; margin-top: 2px;">
                ${escapeHtml(nextClass.date || nextClass.day_of_week || nextClass.weekday || '')}
              </div>
              ${nextClass.meeting_link ? `
                <a href="${escapeHtml(nextClass.meeting_link)}" target="_blank" rel="noopener" class="btn btn-primary" style="font-size: 11px; padding: 3px 8px; min-height: 24px; margin-top: 6px; display: inline-flex; align-items: center; gap: 4px;">
                  <span class="material-symbols-outlined" style="font-size: 12px;">video_call</span>
                  Join MS Teams
                </a>
              ` : ''}
            </div>
          </div>
        ` : `
          <div style="color: var(--on-surface-muted); font-size: 13px; padding: 10px 0;">
            No scheduled classes found. Sync your timetable in the Timetable tab.
          </div>
        `}
      </div>

      <!-- Attendance & Safe Bunks Snapshot -->
      <div class="tech-card">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">analytics</span>
            Attendance &amp; Safe Bunks Overview
          </span>
          <button class="btn btn-secondary" style="font-size: 11px; padding: 3px 8px; min-height: 26px;" onclick="switchAcademicsSubtab('attendance')">
            Details &amp; Planner &rarr;
          </button>
        </div>
        ${attHtml}
      </div>

      <!-- Results Snapshot -->
      <div class="tech-card">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">grade</span>
            Academic Performance &amp; CGPA
          </span>
          <button class="btn btn-secondary" style="font-size: 11px; padding: 3px 8px; min-height: 26px;" onclick="switchAcademicsSubtab('results')">
            Results &amp; What-If &rarr;
          </button>
        </div>
        ${resultsHtml}
      </div>

      <!-- Subtab Navigation Grid -->
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px;">
        <div class="tech-card" style="cursor: pointer;" onclick="switchAcademicsSubtab('timetable')">
          <div class="tech-card-header">
            <span class="tech-card-title"><span class="material-symbols-outlined">calendar_month</span> Timetable</span>
            <span class="material-symbols-outlined" style="color: var(--primary);">arrow_forward</span>
          </div>
          <p style="color: var(--on-surface-variant); font-size: 12px;">Browse weekly schedule (${sessionsCount} sessions), filter by weekday, and view room numbers.</p>
        </div>

        <div class="tech-card" style="cursor: pointer;" onclick="switchAcademicsSubtab('attendance')">
          <div class="tech-card-header">
            <span class="tech-card-title"><span class="material-symbols-outlined">fact_check</span> Safe Bunks & Attendance</span>
            <span class="material-symbols-outlined" style="color: var(--primary);">arrow_forward</span>
          </div>
          <p style="color: var(--on-surface-variant); font-size: 12px;">Inspect 75% attendance threshold, module safe bunk limits, and simulate absences.</p>
        </div>

        <div class="tech-card" style="cursor: pointer;" onclick="switchAcademicsSubtab('lms')">
          <div class="tech-card-header">
            <span class="tech-card-title"><span class="material-symbols-outlined">school</span> LMS & Materials</span>
            <span class="material-symbols-outlined" style="color: var(--primary);">arrow_forward</span>
          </div>
          <p style="color: var(--on-surface-variant); font-size: 12px;">Access UPES Moodle directly via HTTP and download syllabus & notes into Vault.</p>
        </div>

        <div class="tech-card" style="cursor: pointer;" onclick="switchAcademicsSubtab('results')">
          <div class="tech-card-header">
            <span class="tech-card-title"><span class="material-symbols-outlined">calculate</span> Results & What-If</span>
            <span class="material-symbols-outlined" style="color: var(--primary);">arrow_forward</span>
          </div>
          <p style="color: var(--on-surface-variant); font-size: 12px;">View official UPES grade reports and run prospective What-If SGPA/CGPA simulations.</p>
        </div>
      </div>

    </div>
  `;
}

// -----------------------------------------------------------------------------
// SUBTAB 2: TIMETABLE
// -----------------------------------------------------------------------------
let selectedTimetableDay = 'ALL';

async function loadAcademicsTimetable() {
  const container = document.getElementById('academics-pane-timetable');
  if (!container) return;

  const cached = window.NexusStateCache ? window.NexusStateCache.get('academics-timetable') : null;
  if (cached) {
    cachedTimetableSessions = (cached && cached.sessions) || [];
    renderTimetableGrid();
  } else if (!container.children.length) {
    container.innerHTML = '<div style="color: var(--on-surface-muted); padding: 24px 0;">Loading timetable schedule...</div>';
  }

  try {
    const data = await apiJson('/api/timetable/sessions');
    cachedTimetableSessions = (data && data.sessions) || [];
    if (window.NexusStateCache) {
      window.NexusStateCache.set('academics-timetable', data);
    }
    renderTimetableGrid();
  } catch (err) {
    if (!cached) {
      container.innerHTML = `<div style="color: var(--status-critical);">Failed to load timetable: ${escapeHtml(err.message)}</div>`;
    }
  }
}

function filterTimetableDay(day) {
  selectedTimetableDay = day;
  renderTimetableGrid();
}

function renderTimetableGrid() {
  const container = document.getElementById('academics-pane-timetable');
  if (!container) return;

  const days = ['ALL', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

  let filtered = cachedTimetableSessions;
  if (selectedTimetableDay !== 'ALL') {
    filtered = cachedTimetableSessions.filter(s => {
      const dName = s.day_of_week || s.weekday;
      if (dName) return dName.toLowerCase() === selectedTimetableDay.toLowerCase();
      if (s.date) {
        const d = new Date(s.date);
        const dayName = d.toLocaleDateString('en-US', { weekday: 'long' });
        return dayName.toLowerCase() === selectedTimetableDay.toLowerCase();
      }
      return false;
    });
  }

  // Sort by date/start_time
  filtered.sort((a, b) => (a.date || '').localeCompare(b.date || '') || (a.start_time || a.start || '').localeCompare(b.start_time || b.start || ''));

  container.innerHTML = `
    <div style="display: flex; flex-direction: column; gap: 14px;">
      <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
        <div class="day-filter-bar" style="display: flex; gap: 4px; overflow-x: auto; padding-bottom: 4px;">
          ${days.map(d => `
            <button class="btn btn-secondary ${selectedTimetableDay === d ? 'active' : ''}" style="padding: 4px 10px; font-size: 11px; min-height: 28px; ${selectedTimetableDay === d ? 'background: var(--primary); color: #000; font-weight: 600;' : ''}" onclick="filterTimetableDay('${d}')">
              ${d}
            </button>
          `).join('')}
        </div>
        <div style="display: flex; align-items: center; gap: 8px;">
          ${renderProvenanceBadge(cachedTimetableSessions.length > 0 ? 'CACHED' : 'NOT_SYNCED')}
          <button class="btn btn-primary" style="font-size: 11px; padding: 4px 12px; min-height: 28px;" onclick="triggerLiveTimetableSync(this)">
            <span class="material-symbols-outlined" style="font-size: 14px;">sync</span>
            Resync from UPES
          </button>
        </div>
      </div>

      <div class="tech-card">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">calendar_month</span>
            Timetable Sessions (${filtered.length})
          </span>
        </div>
        ${filtered.length === 0 ? `
          <div style="color: var(--on-surface-muted); font-size: 13px; padding: 20px; text-align: center;">
            No scheduled classes found for ${escapeHtml(selectedTimetableDay)}.
          </div>
        ` : `
          <div style="display: flex; flex-direction: column; gap: 8px;">
            ${filtered.map(s => `
              <div style="background: var(--surface-2); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 12px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
                <div>
                  <div style="font-weight: 600; color: var(--on-surface-bright); font-size: 13px;">
                    ${escapeHtml(s.course_name || s.course || s.subject || 'Class')}
                  </div>
                  <div style="color: var(--on-surface-variant); font-size: 11px; margin-top: 2px;">
                    ${escapeHtml(s.course_code ? s.course_code + ' · ' : '')}Room: <strong>${escapeHtml(s.room || 'TBD')}</strong>${escapeHtml(s.faculty ? ' · ' + s.faculty : '')}
                  </div>
                </div>
                <div style="text-align: right;">
                  <div class="font-mono" style="font-size: 12px; color: var(--primary); font-weight: 600;">
                    ${escapeHtml(s.start_time || s.start || '')} - ${escapeHtml(s.end_time || s.end || '')}
                  </div>
                  <div style="color: var(--on-surface-muted); font-size: 10px;">${escapeHtml(s.date || s.day_of_week || s.weekday || '')}</div>
                </div>
              </div>
            `).join('')}
          </div>
        `}
      </div>
    </div>
  `;
}

async function triggerLiveTimetableSync(btn) {
  if (btn) btn.disabled = true;
  showToast('Starting UPES timetable synchronization...', 'info');
  try {
    const res = await apiJson('/api/timetable/sync', { method: 'POST' });
    const upesStatus = res.upes_refresh_status || 'UNKNOWN';
    const ttStatus = res.timetable_status || 'UNKNOWN';
    const calStatus = res.calendar_status || 'UNKNOWN';
    const stageMsg = `UPES: ${upesStatus} · Timetable: ${ttStatus} · Calendar: ${calStatus}`;

    if (res.status === 'success') {
      showToast(`Resynced successfully! (${stageMsg})`, 'success');
    } else {
      showToast(`Resync: ${res.message || stageMsg}`, res.status === 'partial' ? 'warning' : 'error');
    }
    loadAcademicsTimetable();
  } catch (err) {
    showToast(`Sync failed: ${err.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

// -----------------------------------------------------------------------------
// SUBTAB 3: ATTENDANCE & SAFE BUNKS PLANNER
// -----------------------------------------------------------------------------
async function loadAcademicsAttendance() {
  const container = document.getElementById('academics-pane-attendance');
  if (!container) return;

  const cached = window.NexusStateCache ? window.NexusStateCache.get('academics-attendance') : null;
  if (cached) {
    cachedAttendanceData = cached;
    renderAttendanceView();
  } else if (!container.children.length) {
    container.innerHTML = '<div style="color: var(--on-surface-muted); padding: 24px 0;">Loading attendance analytics...</div>';
  }

  try {
    const data = await apiJson('/api/attendance/summary');
    cachedAttendanceData = data;
    if (window.NexusStateCache) {
      window.NexusStateCache.set('academics-attendance', data);
    }
    renderAttendanceView();
  } catch (err) {
    if (!cached) {
      container.innerHTML = `<div style="color: var(--status-critical);">Failed to load attendance: ${escapeHtml(err.message)}</div>`;
    }
  }
}

function renderAttendanceView() {
  const container = document.getElementById('academics-pane-attendance');
  if (!container || !cachedAttendanceData) return;

  const summary = cachedAttendanceData.overall || cachedAttendanceData.summary || {};
  const reports = cachedAttendanceData.subjects || cachedAttendanceData.subject_reports || [];
  const conducted = summary.conducted_classes || summary.total_conducted || 0;
  const attended = summary.attended_classes || summary.total_attended || 0;
  const overallPct = (summary.attendance_percentage !== undefined && summary.attendance_percentage !== null)
    ? Number(summary.attendance_percentage).toFixed(1) + '%'
    : (conducted > 0 ? ((attended / conducted) * 100).toFixed(1) + '%' : '—');
  const safeBunks = summary.safe_bunks !== undefined ? summary.safe_bunks : 0;
  const critCount = summary.critical_subjects !== undefined ? summary.critical_subjects : reports.filter(r => (r.attendance_percentage !== null && r.attendance_percentage < 75)).length;
  const provTimestamp = cachedAttendanceData.as_of_date || cachedAttendanceData.last_synced_at || cachedAttendanceData.timestamp;

  container.innerHTML = `
    <div style="display: flex; flex-direction: column; gap: 16px;">
      
      <!-- Top Action Bar & Provenance -->
      <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
        <div style="display: flex; align-items: center; gap: 8px;">
          ${renderProvenanceBadge(reports.length > 0 ? 'CACHED' : 'NOT_SYNCED', provTimestamp)}
          <span style="font-size: 12px; color: var(--on-surface-muted);">Threshold: 75% Attendance Requirement</span>
        </div>
        <button class="btn btn-primary" style="font-size: 11px; padding: 4px 12px; min-height: 28px;" onclick="triggerLiveAttendanceSync(this)">
          <span class="material-symbols-outlined" style="font-size: 14px;">sync</span>
          Sync UPES Attendance
        </button>
      </div>

      <!-- Attendance Overall Metric Cards -->
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px;">
        <div class="tech-card" style="padding: 12px;">
          <div style="font-size: 11px; color: var(--on-surface-variant); text-transform: uppercase;">Overall Attendance</div>
          <div class="font-mono" style="font-size: 22px; font-weight: 700; color: ${critCount > 0 ? 'var(--status-critical)' : 'var(--status-healthy)'}; margin-top: 4px;">
            ${overallPct}
          </div>
          <div style="font-size: 11px; color: var(--on-surface-muted); margin-top: 2px;">${attended} / ${conducted} classes attended</div>
        </div>

        <div class="tech-card" style="padding: 12px;">
          <div style="font-size: 11px; color: var(--on-surface-variant); text-transform: uppercase;">Total Safe Bunks</div>
          <div class="font-mono" style="font-size: 22px; font-weight: 700; color: var(--primary); margin-top: 4px;">
            ${safeBunks}
          </div>
          <div style="font-size: 11px; color: var(--on-surface-muted); margin-top: 2px;">Classes you can miss &gt;= 75%</div>
        </div>

        <div class="tech-card" style="padding: 12px;">
          <div style="font-size: 11px; color: var(--on-surface-variant); text-transform: uppercase;">Subjects Tracked</div>
          <div class="font-mono" style="font-size: 22px; font-weight: 700; color: var(--on-surface-bright); margin-top: 4px;">
            ${reports.length}
          </div>
          <div style="font-size: 11px; color: var(--on-surface-muted); margin-top: 2px;">${critCount > 0 ? `<span style="color: var(--status-critical); font-weight: 600;">${critCount} critical</span>` : 'All subjects safe'}</div>
        </div>
      </div>

      <!-- Attendance Table -->
      <div class="tech-card">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">fact_check</span>
            Module Attendance & Safe Bunk Analytics (${reports.length})
          </span>
        </div>
        ${reports.length === 0 ? `
          <div style="color: var(--on-surface-muted); font-size: 13px; padding: 20px; text-align: center;">
            No attendance records available. Click 'Sync UPES Attendance' to fetch records.
          </div>
        ` : `
          <div style="overflow-x: auto;">
            <table class="tech-table">
              <thead>
                <tr>
                  <th>Subject Name</th>
                  <th>Conducted</th>
                  <th>Attended</th>
                  <th>Percentage</th>
                  <th>Safe Bunks</th>
                  <th>Recovery Needed</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                ${reports.map(r => {
                  const rName = r.course_name || r.course || r.subject || 'Subject';
                  const rCode = r.course_code || r.code || '';
                  const rCond = r.conducted_classes !== undefined ? r.conducted_classes : (r.conducted || 0);
                  const rAtt = r.attended_classes !== undefined ? r.attended_classes : (r.attended || 0);
                  const rPct = (r.attendance_percentage !== null && r.attendance_percentage !== undefined)
                    ? Number(r.attendance_percentage).toFixed(1) + '%'
                    : (rCond > 0 ? ((rAtt / rCond) * 100).toFixed(1) + '%' : '—');
                  const rPctNum = (r.attendance_percentage !== null && r.attendance_percentage !== undefined)
                    ? Number(r.attendance_percentage)
                    : (rCond > 0 ? (rAtt / rCond) * 100 : 100);
                  const rBunks = r.safe_bunks !== undefined ? r.safe_bunks : 0;
                  const rRec = r.recovery_classes_needed !== undefined ? r.recovery_classes_needed : (r.recovery_needed || 0);
                  const status = rPctNum < 75 ? 'CRITICAL' : (rPctNum < 80 ? 'WARNING' : 'SAFE');
                  return `
                    <tr>
                      <td>
                        <div style="font-weight: 600; color: var(--on-surface-bright);">${escapeHtml(rName)}</div>
                        <div style="color: var(--on-surface-muted); font-size: 10px;">${escapeHtml(rCode)}</div>
                      </td>
                      <td class="font-mono">${rCond}</td>
                      <td class="font-mono">${rAtt}</td>
                      <td class="font-mono" style="font-weight: 600; color: ${status === 'SAFE' ? 'var(--status-healthy)' : 'var(--status-critical)'};">
                        ${rPct}
                      </td>
                      <td class="font-mono" style="color: var(--primary); font-weight: 600;">
                        ${rBunks}
                      </td>
                      <td class="font-mono" style="color: ${rRec > 0 ? 'var(--status-critical)' : 'var(--on-surface-muted)'};">
                        ${rRec}
                      </td>
                      <td>${renderStatusBadge(status)}</td>
                    </tr>
                  `;
                }).join('')}
              </tbody>
            </table>
          </div>
        `}
      </div>

      <!-- Safe Bunk "What-If" Calculator Card -->
      ${reports.length > 0 ? `
        <div class="tech-card">
          <div class="tech-card-header">
            <span class="tech-card-title">
              <span class="material-symbols-outlined">calculate</span>
              Safe Bunk "What-If" Projection Calculator
            </span>
          </div>
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; align-items: flex-end;">
            <div class="form-group" style="margin-bottom: 0;">
              <label class="form-label">Select Subject</label>
              <select class="form-select" id="whatIfSubjectSelect">
                ${reports.map(r => `<option value="${escapeHtml(String(r.module_id || r.course_code || r.course_name || ''))}">${escapeHtml(r.course_name || r.course || 'Subject')}</option>`).join('')}
              </select>
            </div>
            <div class="form-group" style="margin-bottom: 0;">
              <label class="form-label">Missed Classes to Simulate</label>
              <input type="number" class="form-input" id="whatIfBunksInput" value="1" min="1" max="20">
            </div>
            <div>
              <button class="btn btn-primary" onclick="calculateWhatIfProjection()">Calculate Projection</button>
            </div>
          </div>
          <div id="whatIfResult" style="margin-top: 14px; display: none;"></div>
        </div>
      ` : ''}

    </div>
  `;
}

function calculateWhatIfProjection() {
  const sel = document.getElementById('whatIfSubjectSelect');
  const input = document.getElementById('whatIfBunksInput');
  const resultDiv = document.getElementById('whatIfResult');
  if (!sel || !input || !resultDiv || !cachedAttendanceData) return;

  const moduleId = String(sel.value).trim();
  const bunksToMiss = parseInt(input.value, 10) || 0;

  const reports = cachedAttendanceData.subjects || cachedAttendanceData.subject_reports || [];
  const subject = reports.find(r => String(r.module_id || r.course_code || r.course_name || '').trim() === moduleId);
  if (!subject) return;

  const cond = subject.conducted_classes !== undefined ? subject.conducted_classes : (subject.conducted || 0);
  const att = subject.attended_classes !== undefined ? subject.attended_classes : (subject.attended || 0);
  const conducted = cond + bunksToMiss;
  const attended = att;
  const newPct = conducted > 0 ? (attended / conducted) * 100 : 100;
  const curPct = (subject.attendance_percentage !== null && subject.attendance_percentage !== undefined)
    ? Number(subject.attendance_percentage)
    : (cond > 0 ? (att / cond) * 100 : 100);

  resultDiv.style.display = 'block';
  resultDiv.innerHTML = `
    <div style="background: var(--surface-2); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 12px;">
      <div style="font-size: 13px; color: var(--on-surface);">
        If you miss <strong>${bunksToMiss}</strong> more class${bunksToMiss === 1 ? '' : 'es'} in <em>${escapeHtml(subject.course_name || subject.course || 'Subject')}</em>:
      </div>
      <div style="display: flex; gap: 16px; margin-top: 8px; align-items: baseline;">
        <span class="font-mono" style="font-size: 24px; font-weight: 700; color: ${newPct >= 75 ? 'var(--status-healthy)' : 'var(--status-critical)'};">
          ${newPct.toFixed(1)}%
        </span>
        <span style="font-size: 12px; color: var(--on-surface-muted);">
          Current: ${curPct.toFixed(1)}% · ${newPct >= 75 ? 'Safe from debarment' : 'DEBARMENT RISK (Below 75%)'}
        </span>
      </div>
    </div>
  `;
}

async function triggerLiveAttendanceSync(btn) {
  if (btn) btn.disabled = true;
  showToast('Starting UPES attendance synchronization...', 'info');
  try {
    const res = await apiJson('/api/attendance/sync', { method: 'POST' });
    showToast('Attendance synced successfully!', 'success');
    loadAcademicsAttendance();
  } catch (err) {
    showToast(`Sync failed: ${err.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

// -----------------------------------------------------------------------------
// SUBTAB 4: LMS (COURSES, ASSIGNMENTS, RESOURCES)
// -----------------------------------------------------------------------------
async function loadAcademicsLMS() {
  const container = document.getElementById('academics-pane-lms');
  if (!container) return;

  container.innerHTML = '<div style="color: var(--on-surface-muted); padding: 24px 0;">Loading UPES Moodle LMS courses...</div>';

  try {
    const data = await apiJson('/api/lms/courses');
    if (!data || !data.ok) {
      container.innerHTML = `
        <div style="display: flex; flex-direction: column; gap: 16px;">
          <div class="tech-card">
            <div class="tech-card-header">
              <span class="tech-card-title">
                <span class="material-symbols-outlined">menu_book</span>
                UPES Moodle LMS
              </span>
              <div style="display: flex; align-items: center; gap: 8px;">
                ${renderProvenanceBadge('AUTH_REQUIRED')}
                <button class="btn btn-secondary" style="font-size: 11px; padding: 4px 10px; min-height: 28px;" onclick="loadAcademicsLMS()">
                  <span class="material-symbols-outlined" style="font-size: 14px;">sync</span>
                  Check LMS
                </button>
              </div>
            </div>
            <div style="color: var(--on-surface-muted); font-size: 13px; padding: 28px 20px; text-align: center; background: var(--surface-2); border-radius: var(--radius-sm);">
              <span class="material-symbols-outlined" style="font-size: 36px; color: var(--status-warning); margin-bottom: 8px;">lock</span>
              <div style="font-weight: 600; font-size: 15px; margin-bottom: 6px; color: var(--on-surface-bright);">Moodle LMS Authentication Required</div>
              <div style="font-size: 12px; max-width: 480px; margin: 0 auto; line-height: 1.5; color: var(--on-surface-variant);">
                ${escapeHtml(data?.error || 'Direct HTTP session requires active UPES Moodle authentication. No valid Moodle session cookies detected.')}
              </div>
            </div>
          </div>
        </div>
      `;
      return;
    }

    const courses = (data && (data.courses || (data.data && data.data.courses))) || [];
    cachedLmsCourses = courses;

    container.innerHTML = `
      <div style="display: flex; flex-direction: column; gap: 16px;">
        <div class="tech-card">
          <div class="tech-card-header">
            <span class="tech-card-title">
              <span class="material-symbols-outlined">menu_book</span>
              Enrolled LMS Courses (${courses.length})
            </span>
            <div style="display: flex; align-items: center; gap: 8px;">
              ${renderProvenanceBadge(courses.length > 0 ? 'LIVE' : 'EMPTY', data?.provenance?.fetched_at)}
              <button class="btn btn-secondary" style="font-size: 11px; padding: 4px 10px; min-height: 28px;" onclick="loadAcademicsLMS()">
                <span class="material-symbols-outlined" style="font-size: 14px;">sync</span>
                Sync LMS
              </button>
            </div>
          </div>
          ${courses.length === 0 ? `
            <div style="color: var(--on-surface-muted); font-size: 13px; padding: 24px; text-align: center; background: var(--surface-2); border-radius: var(--radius-sm);">
              <span class="material-symbols-outlined" style="font-size: 32px; color: var(--on-surface-muted); margin-bottom: 8px;">folder_off</span>
              <div style="font-weight: 600; margin-bottom: 4px; color: var(--on-surface);">No Enrolled LMS Courses Found</div>
              <div style="font-size: 11px; max-width: 480px; margin: 0 auto; line-height: 1.5; color: var(--on-surface-variant);">
                Authenticated to UPES Moodle, but your account currently has 0 active course shells registered.
              </div>
            </div>
          ` : `
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px;">
              ${courses.map(c => `
                <div style="background: var(--surface-2); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 12px; display: flex; flex-direction: column; justify-content: space-between; gap: 10px;">
                  <div>
                    <div style="font-weight: 600; color: var(--on-surface-bright); font-size: 13px;">${escapeHtml(c.name || c.fullname || 'Course')}</div>
                    <div style="color: var(--on-surface-variant); font-size: 11px; margin-top: 2px;">${escapeHtml(c.short_name || c.shortname || '')}</div>
                  </div>
                  <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid var(--border-subtle); padding-top: 8px;">
                    <span class="font-mono" style="font-size: 10px; color: var(--on-surface-muted);">${escapeHtml(c.course_id || c.id || '')}</span>
                    <button class="btn btn-secondary" style="font-size: 11px; padding: 3px 8px; min-height: 24px;" onclick="loadCourseResources('${escapeHtml(c.course_id || c.id)}', '${escapeHtml(c.name || c.fullname || 'Course')}')">
                      Materials &rarr;
                    </button>
                  </div>
                </div>
              `).join('')}
            </div>
          `}
        </div>

        <div id="lmsResourcesSection"></div>
      </div>
    `;
  } catch (err) {
    container.innerHTML = `<div style="color: var(--status-critical);">Failed to load LMS courses: ${escapeHtml(err.message)}</div>`;
  }
}

async function loadCourseResources(courseId, courseName) {
  const container = document.getElementById('lmsResourcesSection');
  if (!container) return;

  container.innerHTML = `<div style="color: var(--on-surface-muted); padding: 12px 0;">Loading materials for ${escapeHtml(courseName)}...</div>`;

  try {
    const data = await apiJson(`/api/lms/resources?course_id=${encodeURIComponent(courseId)}`);
    const resources = (data && data.resources) || [];

    container.innerHTML = `
      <div class="tech-card">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">folder_open</span>
            Materials for: ${escapeHtml(courseName)} (${resources.length})
          </span>
        </div>
        ${resources.length === 0 ? `
          <div style="color: var(--on-surface-muted); font-size: 13px; padding: 16px;">No downloadable resources found in this course.</div>
        ` : `
          <div style="display: flex; flex-direction: column; gap: 8px;">
            ${resources.map(r => `
              <div style="background: var(--surface-2); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 10px 14px; display: flex; justify-content: space-between; align-items: center; gap: 8px;">
                <div>
                  <div style="font-weight: 500; color: var(--on-surface-bright); font-size: 13px;">${escapeHtml(r.title || r.name)}</div>
                  <div style="color: var(--on-surface-muted); font-size: 11px;">${escapeHtml(r.type || 'Document')}</div>
                </div>
                <button class="btn btn-secondary" style="font-size: 11px; padding: 4px 10px; min-height: 28px;" onclick="downloadLmsResourceToVault('${escapeHtml(r.resource_id || r.id)}', '${escapeHtml(courseName)}/${escapeHtml(r.title || 'material')}')">
                  <span class="material-symbols-outlined" style="font-size: 14px;">download</span>
                  Save to Vault
                </button>
              </div>
            `).join('')}
          </div>
        `}
      </div>
    `;
  } catch (err) {
    container.innerHTML = `<div style="color: var(--status-critical);">Failed to load course materials: ${escapeHtml(err.message)}</div>`;
  }
}

async function downloadLmsResourceToVault(resourceId, destPath) {
  showToast('Downloading resource to Vault...', 'info');
  try {
    const res = await apiJson('/api/lms/download', {
      method: 'POST',
      body: { resource_id: resourceId, destination_path: destPath }
    });
    showToast(`Saved to Vault: ${res.data?.vault_path || destPath}`, 'success');
  } catch (err) {
    showToast(`Download failed: ${err.message}`, 'error');
  }
}

// -----------------------------------------------------------------------------
// SUBTAB 5: CALENDAR
// -----------------------------------------------------------------------------
async function loadAcademicsCalendar() {
  const container = document.getElementById('academics-pane-calendar');
  if (!container) return;

  container.innerHTML = '<div style="color: var(--on-surface-muted); padding: 24px 0;">Loading calendar status...</div>';

  try {
    const data = await apiJson('/api/timetable/onboarding-status');
    const google = (data && data.google) || {};
    const sync = (data && data.calendar_sync) || {};
    const timetable = (data && data.timetable) || {};
    const checklist = (data && data.checklist) || [];

    const isConnected = !!google.connected;
    const isSynced = checklist.some(c => c.id === 'calendar_synced' && c.completed);

    let stateLabel = 'DISCONNECTED';
    let stateBadge = 'badge-critical';
    if (isConnected) {
      if (isSynced) {
        stateLabel = 'SYNCHRONIZED';
        stateBadge = 'badge-healthy';
      } else {
        stateLabel = 'CONFIGURED (PENDING SYNC)';
        stateBadge = 'badge-warning';
      }
    }

    const accountEmail = google.connected_email || google.email || data.user?.google_email || (isConnected ? 'Connected Google Account' : 'None');
    const targetCalendar = sync.target_calendar_id || google.calendar_id || 'primary';
    const lastSyncTime = sync.last_sync ? formatTimeAgo(sync.last_sync) : 'Never';
    const lastResult = sync.last_status || sync.last_sync_status || 'None';
    const nextSyncTime = sync.next_sync ? (new Date(sync.next_sync * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' (' + formatTimeAgo(sync.next_sync) + ')') : 'Every 3 hours';
    const mappedCount = timetable.reconciled_events ?? 0;
    const totalCount = timetable.total_sessions ?? timetable.session_count ?? 0;

    container.innerHTML = `
      <div class="tech-card">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">event_available</span>
            Google Calendar Synchronization
          </span>
          <span class="status-badge ${stateBadge}">${stateLabel}</span>
        </div>
        <div style="display: flex; flex-direction: column; gap: 12px;">
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; font-size: 13px;">
            <div>
              <span style="color: var(--on-surface-muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; display: block;">Connection Status</span>
              <strong style="color: ${isConnected ? 'var(--status-healthy)' : 'var(--status-critical)'};">
                ${isConnected ? 'Connected' : 'Disconnected'}
              </strong>
            </div>
            <div>
              <span style="color: var(--on-surface-muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; display: block;">Google Account</span>
              <span class="font-mono" style="color: var(--on-surface-bright);">${escapeHtml(accountEmail)}</span>
            </div>
            <div>
              <span style="color: var(--on-surface-muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; display: block;">Target Calendar</span>
              <span class="font-mono">${escapeHtml(targetCalendar)}</span>
            </div>
            <div>
              <span style="color: var(--on-surface-muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; display: block;">Event Mappings</span>
              <span class="font-mono" style="font-weight: 600; color: var(--primary);">${mappedCount} / ${totalCount} sessions</span>
            </div>
            <div>
              <span style="color: var(--on-surface-muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; display: block;">Last Sync</span>
              <span class="font-mono">${escapeHtml(lastSyncTime)}</span>
            </div>
            <div>
              <span style="color: var(--on-surface-muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; display: block;">Last Result</span>
              <span class="font-mono" style="text-transform: uppercase;">${escapeHtml(lastResult)}</span>
            </div>
            <div>
              <span style="color: var(--on-surface-muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; display: block;">Next Scheduled Sync</span>
              <span class="font-mono">${escapeHtml(nextSyncTime)}</span>
            </div>
            <div>
              <span style="color: var(--on-surface-muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; display: block;">Reconciliation Mode</span>
              <span class="font-mono">FULL_SEMESTER (10,800s)</span>
            </div>
          </div>

          <div style="font-size: 11px; color: var(--on-surface-muted); margin-top: 10px; line-height: 1.4;">
            Fetch the latest timetable from UPES, update NexusNode, then reconcile your Google Calendar.
          </div>

          <div style="display: flex; justify-content: flex-end; gap: 8px; border-top: 1px solid var(--border-subtle); padding-top: 12px; margin-top: 10px; flex-wrap: wrap;">
            <button class="btn btn-secondary" style="font-size: 11px; padding: 4px 10px;" onclick="triggerCacheOnlyReconcile(this)" title="Reconcile existing local timetable to Google Calendar without fetching from UPES">
              <span class="material-symbols-outlined" style="font-size: 14px;">cached</span>
              Reconcile from Cache
            </button>
            <a href="/api/auth/google/authorize?redirect=true" class="btn btn-secondary" style="font-size: 11px; padding: 4px 10px; text-decoration: none; display: inline-flex; align-items: center; gap: 4px;">
              <span class="material-symbols-outlined" style="font-size: 14px;">vpn_key</span>
              Re-authorize Google
            </a>
            <button class="btn btn-primary" style="font-size: 12px;" onclick="triggerCalendarReconcile(this)">
              <span class="material-symbols-outlined" style="font-size: 14px;">sync</span>
              Resync from UPES
            </button>
          </div>
        </div>
      </div>
    `;
  } catch (err) {
    container.innerHTML = `<div style="color: var(--status-critical);">Failed to load calendar status: ${escapeHtml(err.message)}</div>`;
  }
}

async function triggerCalendarReconcile(btn) {
  if (btn) btn.disabled = true;
  showToast('Starting live UPES timetable refresh & Google Calendar reconciliation...', 'info');
  try {
    const res = await apiJson('/api/timetable/sync', { method: 'POST' });
    const upesStatus = res.upes_refresh_status || (res.stages && res.stages.upes_refresh && res.stages.upes_refresh.status) || 'UNKNOWN';
    const ttStatus = res.timetable_status || (res.stages && res.stages.timetable && res.stages.timetable.status) || 'UNKNOWN';
    const calStatus = res.calendar_status || (res.stages && res.stages.calendar && res.stages.calendar.status) || 'UNKNOWN';

    const stageMsg = `[1] UPES: ${upesStatus} | [2] Timetable: ${ttStatus} | [3] Calendar: ${calStatus} (C:${res.created || 0} U:${res.updated || 0} D:${res.deleted || 0})`;

    if (res.status === 'success') {
      showToast(`Resync Succeeded! ${stageMsg}`, 'success');
    } else if (res.status === 'partial') {
      showToast(`Partial Resync: ${stageMsg}`, 'warning');
    } else {
      showToast(`Resync: ${res.message || res.errors?.join(', ') || stageMsg}`, 'error');
    }
    loadAcademicsCalendar();
  } catch (err) {
    showToast(`Resync failed: ${err.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function triggerCacheOnlyReconcile(btn) {
  if (btn) btn.disabled = true;
  showToast('Reconciling Google Calendar from local cache...', 'info');
  try {
    const res = await apiJson('/api/timetable/reconcile_cached', { method: 'POST' });
    showToast(`Cache Reconciliation: Calendar ${res.calendar_status || res.status} (C:${res.created || 0} U:${res.updated || 0} D:${res.deleted || 0})`, res.status === 'success' ? 'success' : 'warning');
    loadAcademicsCalendar();
  } catch (err) {
    showToast(`Reconciliation failed: ${err.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

// -----------------------------------------------------------------------------
// SUBTAB 6: RESULTS & SGPA/CGPA (PHASE 4.3A)
// -----------------------------------------------------------------------------
let cachedResultsRecord = null;
let whatIfCoursesList = [];

async function loadAcademicsResults() {
  const container = document.getElementById('academics-pane-results');
  if (!container) return;

  container.innerHTML = '<div style="color: var(--on-surface-muted); padding: 24px 0;">Loading academic results and grade history...</div>';

  try {
    const data = await apiJson('/api/academics/results');
    cachedResultsRecord = data;
    renderAcademicsResults(data);
  } catch (err) {
    container.innerHTML = `
      <div class="tech-card" style="border-color: var(--status-critical);">
        <div class="tech-card-header">
          <span class="tech-card-title" style="color: var(--status-critical);">
            <span class="material-symbols-outlined">error</span>
            Error Loading Academic Results
          </span>
          <button class="btn btn-secondary" onclick="loadAcademicsResults()">Retry</button>
        </div>
        <p style="color: var(--on-surface-variant); font-size: 13px;">${escapeHtml(err.message)}</p>
      </div>
    `;
  }
}

function getGradeBadgeClass(grade) {
  const g = (grade || '').toUpperCase().trim();
  if (g === 'O' || g === 'A+') return 'badge-healthy';
  if (g === 'A' || g === 'B+') return 'badge-primary';
  if (g === 'B' || g === 'C+') return 'badge-warning';
  if (g === 'C') return 'badge-secondary';
  if (g === 'F') return 'badge-critical';
  return 'badge-secondary';
}

function getCgpaClassification(cgpa) {
  if (cgpa === null || cgpa === undefined) return '—';
  const val = parseFloat(cgpa);
  if (val >= 9.0) return 'Outstanding / First Class with Distinction';
  if (val >= 8.0) return 'First Class with Distinction';
  if (val >= 6.5) return 'First Class';
  if (val >= 5.0) return 'Second Class';
  return 'Academic Warning';
}

function renderAcademicsResults(record) {
  const container = document.getElementById('academics-pane-results');
  if (!container) return;

  const semesters = (record && record.semesters) || [];
  const hasSemesters = semesters.length > 0;
  const officialCgpa = record?.official_cgpa !== null && record?.official_cgpa !== undefined ? parseFloat(record.official_cgpa).toFixed(2) : null;
  const calcCgpa = record?.calculated_cgpa !== null && record?.calculated_cgpa !== undefined ? parseFloat(record.calculated_cgpa).toFixed(2) : '0.00';
  const displayCgpa = officialCgpa || calcCgpa;
  const earnedCredits = record?.total_credits_earned || 0;
  const regCredits = record?.total_credits_registered || 0;
  const discrepancies = record?.discrepancies || [];
  const hasDiscrepancy = Boolean(record?.has_discrepancy || discrepancies.length > 0);
  const latestSem = hasSemesters ? semesters[semesters.length - 1] : null;
  const latestSgpa = latestSem ? (latestSem.official_sgpa !== null ? parseFloat(latestSem.official_sgpa).toFixed(2) : parseFloat(latestSem.calculated_sgpa).toFixed(2)) : '—';

  if (!hasSemesters) {
    container.innerHTML = `
      <div class="tech-card">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">grade</span>
            Official Academic Results & SGPA/CGPA
          </span>
          <span class="status-badge badge-stale">NO DATA LOADED</span>
        </div>
        <p style="color: var(--on-surface-variant); font-size: 13px; line-height: 1.6; margin-bottom: 16px;">
          No academic examination results or course grades have been synchronized yet. Click below to fetch your official semester grade sheets from UPES ConnectPortal and Exam-Pro.
        </p>
        <button class="btn btn-primary" onclick="syncAcademicResults(this)">
          <span class="material-symbols-outlined" style="font-size: 14px;">sync</span>
          Fetch Academic Results Now
        </button>
      </div>
    `;
    return;
  }

  // Discrepancy warning banner
  let discrepancyHtml = '';
  if (hasDiscrepancy) {
    discrepancyHtml = `
      <div class="alert-banner" style="
        background: var(--surface-1);
        border-left: 4px solid var(--status-warning);
        border-top: 1px solid var(--border-subtle);
        border-right: 1px solid var(--border-subtle);
        border-bottom: 1px solid var(--border-subtle);
        border-radius: var(--radius-md);
        padding: 14px 16px;
        margin-bottom: 16px;
      ">
        <div style="display: flex; align-items: flex-start; gap: 10px;">
          <span class="material-symbols-outlined" style="color: var(--status-warning); font-size: 20px;">warning</span>
          <div style="flex: 1;">
            <strong style="color: var(--on-surface-bright); font-size: 13px;">Official vs Computed Grade Discrepancies Detected</strong>
            <p style="color: var(--on-surface-variant); font-size: 12px; margin-top: 4px;">
              Differences were identified between reported portal GPA figures and the canonical 10-point mathematical calculation:
            </p>
            <ul style="margin: 8px 0 0 16px; font-size: 12px; color: var(--on-surface);">
              ${discrepancies.map(d => `
                <li><strong>${escapeHtml(d.term_id || d.type)}:</strong> ${escapeHtml(d.details || JSON.stringify(d))}</li>
              `).join('')}
            </ul>
          </div>
        </div>
      </div>
    `;
  }

  container.innerHTML = `
    <div style="display: flex; flex-direction: column; gap: 16px;">
      
      <!-- Provenance & Sync Status Header -->
      <div class="tech-card" style="border-color: var(--border-medium);">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">verified</span>
            Authoritative UPES Academic Grade Ledger
          </span>
          <div style="display: flex; align-items: center; gap: 8px;">
            ${renderStatusBadge(record.provenance ? record.provenance.toUpperCase() : 'LIVE')}
            <button class="btn btn-secondary" style="font-size: 11px; padding: 4px 8px; min-height: 28px;" onclick="syncAcademicResults(this)">
              <span class="material-symbols-outlined" style="font-size: 12px;">refresh</span>
              Sync Results
            </button>
          </div>
        </div>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; font-size: 12px;">
          <div>
            <span style="color: var(--on-surface-muted); display: block;">Student Tenant</span>
            <span class="font-mono" style="font-weight: 600; color: var(--on-surface-bright);">${escapeHtml(record.user_id || 'student')}</span>
          </div>
          <div>
            <span style="color: var(--on-surface-muted); display: block;">Storage Invariant</span>
            <span style="color: var(--status-healthy);">Privacy-Preserving (SHA-256 Fingerprint)</span>
          </div>
          <div>
            <span style="color: var(--on-surface-muted); display: block;">Academic Standing</span>
            <span style="color: var(--primary); font-weight: 600;">${getCgpaClassification(displayCgpa)}</span>
          </div>
          <div>
            <span style="color: var(--on-surface-muted); display: block;">Last Synced</span>
            <span class="font-mono" style="color: var(--on-surface);">${formatTimeAgo(record.last_synced_at)}</span>
          </div>
        </div>
      </div>

      ${discrepancyHtml}

      <!-- Performance Metrics Summary Cards -->
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px;">
        <div class="meter-box" style="padding: 16px;">
          <span class="meter-label">Cumulative CGPA</span>
          <span class="meter-val font-mono" style="font-size: 30px; color: var(--primary); font-weight: 700;">
            ${displayCgpa} <span style="font-size: 14px; color: var(--on-surface-muted); font-weight: 400;">/ 10.0</span>
          </span>
          <span style="font-size: 11px; color: var(--on-surface-variant); margin-top: 4px; display: block;">
            ${officialCgpa ? 'Official Portal Transcript' : 'Computed 10-pt Scale'}
          </span>
        </div>
        <div class="meter-box" style="padding: 16px;">
          <span class="meter-label">Earned Credits</span>
          <span class="meter-val font-mono" style="font-size: 30px; color: var(--status-healthy); font-weight: 700;">
            ${earnedCredits} <span style="font-size: 14px; color: var(--on-surface-muted); font-weight: 400;">/ ${regCredits}</span>
          </span>
          <span style="font-size: 11px; color: var(--on-surface-variant); margin-top: 4px; display: block;">
            ${((earnedCredits / (regCredits || 1)) * 100).toFixed(0)}% Degree Completion
          </span>
        </div>
        <div class="meter-box" style="padding: 16px;">
          <span class="meter-label">Latest Semester SGPA</span>
          <span class="meter-val font-mono" style="font-size: 30px; color: var(--on-surface-bright); font-weight: 700;">
            ${latestSgpa}
          </span>
          <span style="font-size: 11px; color: var(--on-surface-variant); margin-top: 4px; display: block;">
            ${latestSem ? escapeHtml(latestSem.semester_name || latestSem.term_id) : '—'}
          </span>
        </div>
        <div class="meter-box" style="padding: 16px;">
          <span class="meter-label">Enrolled Semesters</span>
          <span class="meter-val font-mono" style="font-size: 30px; color: var(--on-surface-bright); font-weight: 700;">
            ${semesters.length}
          </span>
          <span style="font-size: 11px; color: var(--on-surface-variant); margin-top: 4px; display: block;">
            Across All Academic Years
          </span>
        </div>
      </div>

      <!-- Semester Grade Sheets Accordion -->
      <div style="display: flex; flex-direction: column; gap: 12px;">
        <h3 style="font-size: 14px; font-weight: 600; color: var(--on-surface-bright); margin-top: 8px;">
          Semester Grade Reports (${semesters.length})
        </h3>
        
        ${semesters.map((sem, idx) => {
          const semSgpa = sem.official_sgpa !== null && sem.official_sgpa !== undefined ? parseFloat(sem.official_sgpa).toFixed(2) : parseFloat(sem.calculated_sgpa).toFixed(2);
          const semCredits = sem.credits_earned || 0;
          const courses = sem.courses || [];
          const isOpen = idx === semesters.length - 1; // Open latest semester by default

          return `
            <div class="tech-card" style="padding: 0; overflow: hidden;">
              <div 
                style="padding: 14px 16px; display: flex; justify-content: space-between; align-items: center; cursor: pointer; background: var(--surface-1);"
                onclick="toggleSemesterCard('sem-card-${idx}')"
              >
                <div style="display: flex; align-items: center; gap: 10px;">
                  <span class="material-symbols-outlined" style="color: var(--primary);">school</span>
                  <div>
                    <strong style="color: var(--on-surface-bright); font-size: 14px;">${escapeHtml(sem.semester_name || sem.term_id)}</strong>
                    <span style="color: var(--on-surface-muted); font-size: 11px; margin-left: 8px;">(${escapeHtml(sem.academic_year || 'Academic Year')})</span>
                  </div>
                </div>
                <div style="display: flex; align-items: center; gap: 12px;">
                  <span class="badge badge-primary font-mono" style="font-size: 12px;">SGPA: ${semSgpa}</span>
                  <span class="font-mono" style="font-size: 12px; color: var(--on-surface-variant);">${semCredits} Credits</span>
                  <span class="status-badge ${sem.status === 'Passed' ? 'badge-healthy' : 'badge-warning'}">${escapeHtml(sem.status || 'Passed')}</span>
                  <span class="material-symbols-outlined" id="sem-icon-${idx}" style="font-size: 18px; color: var(--on-surface-muted); transition: transform 0.2s ease;">
                    ${isOpen ? 'expand_less' : 'expand_more'}
                  </span>
                </div>
              </div>

              <div id="sem-card-${idx}" style="display: ${isOpen ? 'block' : 'none'}; padding: 16px; border-top: 1px solid var(--border-subtle);">
                <table class="tech-table">
                  <thead>
                    <tr>
                      <th>Course Code</th>
                      <th>Course Title</th>
                      <th style="text-align: center;">Credits</th>
                      <th style="text-align: center;">Grade</th>
                      <th style="text-align: center;">Grade Point</th>
                      <th style="text-align: right;">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${courses.map(c => `
                      <tr>
                        <td class="font-mono" style="font-weight: 600;">${escapeHtml(c.course_code)}</td>
                        <td>${escapeHtml(c.course_name)}</td>
                        <td class="font-mono" style="text-align: center;">${parseFloat(c.credits).toFixed(1)}</td>
                        <td style="text-align: center;">
                          <span class="badge ${getGradeBadgeClass(c.letter_grade)} font-mono" style="font-weight: 700;">
                            ${escapeHtml(c.letter_grade)}
                          </span>
                        </td>
                        <td class="font-mono" style="text-align: center; color: var(--on-surface-bright);">${parseFloat(c.grade_point).toFixed(1)}</td>
                        <td style="text-align: right;">
                          <span class="status-badge ${c.status === 'Passed' ? 'badge-healthy' : (c.status === 'Audit' ? 'badge-secondary' : 'badge-critical')}" style="font-size: 10px;">
                            ${escapeHtml(c.status || 'Passed')}
                          </span>
                        </td>
                      </tr>
                    `).join('')}
                  </tbody>
                </table>
              </div>
            </div>
          `;
        }).join('')}
      </div>

      <!-- What-If CGPA & SGPA Simulator -->
      <div class="tech-card" style="border-color: var(--primary);">
        <div class="tech-card-header">
          <span class="tech-card-title" style="color: var(--primary);">
            <span class="material-symbols-outlined">calculate</span>
            What-If CGPA & Academic Projection Simulator
          </span>
          <span class="badge badge-primary">EPHEMERAL SIMULATION</span>
        </div>
        <p style="color: var(--on-surface-variant); font-size: 13px; line-height: 1.5; margin-bottom: 16px;">
          Model future academic scenarios without affecting your official records. Calculate required future SGPAs or project your resulting CGPA based on prospective grades.
        </p>

        <!-- Mode A: Target CGPA Calculator -->
        <div style="background: var(--surface-2); border-radius: var(--radius-sm); padding: 14px; margin-bottom: 16px;">
          <strong style="color: var(--on-surface-bright); font-size: 13px; display: block; margin-bottom: 8px;">
            Target CGPA Calculator
          </strong>
          <div style="display: flex; gap: 12px; align-items: flex-end; flex-wrap: wrap;">
            <div class="form-group" style="margin-bottom: 0; min-width: 140px;">
              <label class="form-label" style="font-size: 11px;">Target Cumulative CGPA</label>
              <input type="number" step="0.01" min="0" max="10" class="form-input" id="whatIfTargetCgpa" value="8.50">
            </div>
            <div class="form-group" style="margin-bottom: 0; min-width: 140px;">
              <label class="form-label" style="font-size: 11px;">Upcoming Credits</label>
              <input type="number" step="0.5" min="1" max="60" class="form-input" id="whatIfFutureCredits" value="20.0">
            </div>
            <button class="btn btn-primary" onclick="runWhatIfTargetCgpa(this)" style="height: 38px;">
              Calculate Required SGPA
            </button>
          </div>
          <div id="whatIfTargetResult" style="margin-top: 10px; font-size: 13px;"></div>
        </div>

        <!-- Mode B: Scenario Grade Projection -->
        <div style="background: var(--surface-2); border-radius: var(--radius-sm); padding: 14px;">
          <strong style="color: var(--on-surface-bright); font-size: 13px; display: block; margin-bottom: 8px;">
            Upcoming Courses Scenario Projection
          </strong>
          <div id="whatIfCoursesContainer" style="display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px;">
            ${whatIfCoursesList.length === 0 ? `
              <div style="color: var(--on-surface-muted); font-size: 12px; font-style: italic; padding: 12px 8px; text-align: center; background: var(--surface-1); border-radius: var(--radius-sm);">
                No scenario courses added. Click "+ Add Course" to model hypothetical grades.
              </div>
            ` : whatIfCoursesList.map((c, i) => `
              <div style="display: flex; gap: 8px; align-items: center;" id="whatIfRow-${i}">
                <input type="text" class="form-input" style="flex: 2; padding: 6px;" value="${escapeHtml(c.course_code)}" onchange="whatIfCoursesList[${i}].course_code = this.value">
                <input type="number" step="0.5" min="1" max="10" class="form-input" style="flex: 1; padding: 6px;" value="${c.credits}" onchange="whatIfCoursesList[${i}].credits = parseFloat(this.value)">
                <select class="form-input" style="flex: 1; padding: 6px;" onchange="whatIfCoursesList[${i}].letter_grade = this.value">
                  ${['O', 'A+', 'A', 'B+', 'B', 'C+', 'C', 'F'].map(g => `
                    <option value="${g}" ${c.letter_grade === g ? 'selected' : ''}>${g}</option>
                  `).join('')}
                </select>
                <button class="btn btn-secondary" style="padding: 6px 10px; min-height: 32px;" onclick="removeWhatIfCourseRow(${i})">
                  <span class="material-symbols-outlined" style="font-size: 14px;">close</span>
                </button>
              </div>
            `).join('')}
          </div>
          <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
            <button class="btn btn-secondary" onclick="addWhatIfCourseRow()" style="font-size: 12px;">
              <span class="material-symbols-outlined" style="font-size: 14px;">add</span>
              Add Course
            </button>
            <button class="btn btn-primary" onclick="runWhatIfScenario(this)">
              Simulate Projected CGPA
            </button>
          </div>
          <div id="whatIfScenarioResult" style="margin-top: 12px; font-size: 13px;"></div>
        </div>

      </div>

    </div>
  `;
}

function toggleSemesterCard(cardId) {
  const card = document.getElementById(cardId);
  if (!card) return;
  const isHidden = card.style.display === 'none';
  card.style.display = isHidden ? 'block' : 'none';
  const idx = cardId.replace('sem-card-', '');
  const icon = document.getElementById(`sem-icon-${idx}`);
  if (icon) {
    icon.textContent = isHidden ? 'expand_less' : 'expand_more';
  }
}

async function syncAcademicResults(btn) {
  if (btn) btn.disabled = true;
  showToast('Fetching authoritative academic results from UPES portals...', 'info');
  try {
    const res = await apiJson('/api/academics/results/sync', { method: 'POST' });
    showToast('Academic results synchronized successfully!', 'success');
    loadAcademicsResults();
  } catch (err) {
    showToast(`Sync failed: ${err.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function runWhatIfTargetCgpa(btn) {
  const targetVal = parseFloat(document.getElementById('whatIfTargetCgpa').value);
  const futureCredits = parseFloat(document.getElementById('whatIfFutureCredits').value);
  const resultDiv = document.getElementById('whatIfTargetResult');

  if (isNaN(targetVal) || isNaN(futureCredits) || futureCredits <= 0) {
    showToast('Please enter valid target CGPA and credits', 'warning');
    return;
  }

  if (btn) btn.disabled = true;
  try {
    const res = await apiJson('/api/academics/what-if', {
      method: 'POST',
      body: { target_cgpa: targetVal, future_credits: futureCredits }
    });
    const reqSgpa = res.required_sgpa !== null ? parseFloat(res.required_sgpa).toFixed(2) : '—';
    const achievable = res.is_achievable;

    resultDiv.innerHTML = `
      <div style="padding: 10px; background: var(--surface-1); border-radius: var(--radius-sm); border-left: 3px solid ${achievable ? 'var(--status-healthy)' : 'var(--status-critical)'};">
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span>Required Upcoming SGPA: <strong class="font-mono" style="font-size: 16px; color: ${achievable ? 'var(--status-healthy)' : 'var(--status-critical)'};">${reqSgpa}</strong></span>
          <span class="status-badge ${achievable ? 'badge-healthy' : 'badge-critical'}">${achievable ? 'ACHIEVABLE' : 'IMPOSSIBLE (> 10.0)'}</span>
        </div>
        <div style="color: var(--on-surface-variant); font-size: 11px; margin-top: 4px;">
          ${escapeHtml(res.analysis || res.message || '')}
        </div>
      </div>
    `;
  } catch (err) {
    resultDiv.innerHTML = `<span style="color: var(--status-critical);">Calculation error: ${escapeHtml(err.message)}</span>`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

function addWhatIfCourseRow() {
  whatIfCoursesList.push({
    course_code: `COURSE${whatIfCoursesList.length + 1}`,
    credits: 3.0,
    letter_grade: 'A'
  });
  renderAcademicsResults(cachedResultsRecord);
}

function removeWhatIfCourseRow(idx) {
  whatIfCoursesList.splice(idx, 1);
  renderAcademicsResults(cachedResultsRecord);
}

async function runWhatIfScenario(btn) {
  if (!whatIfCoursesList || whatIfCoursesList.length === 0) {
    showToast('Please add at least one course to run scenario projection', 'warning');
    return;
  }
  const resultDiv = document.getElementById('whatIfScenarioResult');
  if (btn) btn.disabled = true;
  try {
    const res = await apiJson('/api/academics/what-if', {
      method: 'POST',
      body: { hypothetical_courses: whatIfCoursesList }
    });
    const projCgpa = res.projected_cgpa !== null ? parseFloat(res.projected_cgpa).toFixed(2) : '—';
    const curCgpa = res.current_cgpa !== null ? parseFloat(res.current_cgpa).toFixed(2) : '—';
    const delta = (parseFloat(projCgpa) - parseFloat(curCgpa)).toFixed(2);
    const deltaStr = delta > 0 ? `+${delta}` : delta;

    resultDiv.innerHTML = `
      <div style="padding: 10px; background: var(--surface-1); border-radius: var(--radius-sm); border-left: 3px solid var(--primary);">
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span>Projected CGPA: <strong class="font-mono" style="font-size: 16px; color: var(--primary);">${projCgpa}</strong> (${deltaStr})</span>
          <span class="badge badge-primary">Scenario SGPA: ${parseFloat(res.scenario_sgpa || 0).toFixed(2)}</span>
        </div>
        <div style="color: var(--on-surface-variant); font-size: 11px; margin-top: 4px;">
          Current CGPA: ${curCgpa} &rarr; Projected CGPA: ${projCgpa} across ${res.projected_credits || 0} additional credits.
        </div>
      </div>
    `;
  } catch (err) {
    resultDiv.innerHTML = `<span style="color: var(--status-critical);">Simulation error: ${escapeHtml(err.message)}</span>`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function refreshAllAcademics(btn) {
  if (btn) btn.disabled = true;
  showToast('Refreshing all academic subsystems...', 'info');
  try {
    const res = await apiJson('/api/academics/refresh-all', { method: 'POST' });
    showToast('Academic data refreshed successfully!', 'success');
    await loadAcademicsOverview();
  } catch (err) {
    showToast(`Academic refresh failed: ${err.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

