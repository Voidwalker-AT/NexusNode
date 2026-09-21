/**
 * NexusNode — MCP Gateway Surface Controller
 * Phase 4.2A Product Rebase
 * Dedicated MCP appliance interface: server status, public endpoint, 11-tool explorer, authorized clients, activity trace.
 */

let cachedMcpSummary = null;

async function loadMcp() {
  const container = document.getElementById('mcpContent');
  if (!container) return;

  container.innerHTML = '<div style="color: var(--on-surface-muted); padding: 24px 0;">Querying MCP gateway telemetry...</div>';

  try {
    const data = await apiJson('/api/mcp/summary');
    cachedMcpSummary = data;
    renderMcpView(data);
  } catch (err) {
    container.innerHTML = `
      <div class="tech-card" style="border-color: var(--status-critical);">
        <div class="tech-card-header">
          <span class="tech-card-title" style="color: var(--status-critical);">MCP Gateway Error</span>
          <button class="btn btn-secondary" onclick="loadMcp()">Retry</button>
        </div>
        <p style="color: var(--on-surface-variant); font-size: 13px;">${escapeHtml(err.message)}</p>
      </div>
    `;
  }
}

function renderMcpView(data) {
  const container = document.getElementById('mcpContent');
  if (!container) return;

  const tools = data.tools || [];
  const clients = data.authorized_clients || [];
  const activity = data.recent_activity || [];

  container.innerHTML = `
    <div style="display: flex; flex-direction: column; gap: 16px;">
      
      <!-- Top Gateway Banner -->
      <div class="tech-card" style="border-color: var(--border-medium);">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">hub</span>
            NexusNode Model Context Protocol (MCP) Gateway
          </span>
          ${renderStatusBadge(data.status || 'HEALTHY')}
        </div>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; font-size: 12px;">
          <div>
            <span style="color: var(--on-surface-muted); display: block;">Protocol Version</span>
            <span class="font-mono" style="color: var(--primary); font-weight: 600;">${escapeHtml(data.protocol_version || '2026-07-28')}</span>
          </div>
          <div>
            <span style="color: var(--on-surface-muted); display: block;">Active Catalog</span>
            <span class="font-mono" style="color: var(--on-surface-bright);">${escapeHtml(data.catalog_version || 'nexus-semantic-v1')}</span>
          </div>
          <div>
            <span style="color: var(--on-surface-muted); display: block;">Semantic Tool Count</span>
            <span class="font-mono" style="color: var(--on-surface);">${data.tools_count || tools.length} Tools</span>
          </div>
          <div>
            <span style="color: var(--on-surface-muted); display: block;">Authorized Clients</span>
            <span class="font-mono" style="color: var(--on-surface);">${clients.length} Registered</span>
          </div>
        </div>

        <!-- Endpoint Management Panel -->
        <div style="display: flex; flex-direction: column; gap: 10px; margin-top: 14px;">
          <!-- 1. Public MCP Endpoint -->
          <div style="background: var(--surface-2); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 12px 14px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
            <div style="display: flex; flex-direction: column; gap: 4px; min-width: 0; flex: 1;">
              <div style="display: flex; align-items: center; gap: 8px;">
                <span class="material-symbols-outlined" style="font-size: 16px; color: var(--primary);">public</span>
                <strong style="font-size: 12px; color: var(--on-surface-bright); text-transform: uppercase; letter-spacing: 0.5px;">Public Internet MCP Endpoint</strong>
                <span class="status-badge ${data.is_public_healthy ? 'badge-healthy' : 'badge-warning'}" style="font-size: 10px;">${escapeHtml(data.is_public_healthy ? 'ONLINE (HTTPS)' : (data.tunnel_status || 'OFFLINE / STOPPED'))}</span>
              </div>
              <span class="font-mono" style="font-size: 12px; color: var(--primary); font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" id="mcpPublicEndpointUrl">${escapeHtml(data.public_mcp_url || data.public_endpoint || 'https://k09oezeyib.localto.net/api/mcp')}</span>
            </div>
            <button class="btn btn-primary" style="font-size: 11px; padding: 6px 12px; min-height: 28px;" onclick="copyMcpPublicEndpoint()">
              <span class="material-symbols-outlined" style="font-size: 14px;">content_copy</span>
              Copy Public Endpoint
            </button>
          </div>

          <!-- 2. Local LAN Endpoint -->
          <div style="background: var(--surface-2); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 10px 14px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
            <div style="display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1;">
              <div style="display: flex; align-items: center; gap: 8px;">
                <span class="material-symbols-outlined" style="font-size: 16px; color: var(--on-surface-muted);">lan</span>
                <span style="font-size: 11px; color: var(--on-surface-muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">Local LAN Endpoint (Direct Socket HTTP)</span>
              </div>
              <span class="font-mono" style="font-size: 12px; color: var(--on-surface-variant); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" id="mcpLanEndpointUrl">${escapeHtml(data.lan_mcp_url || ('http://' + window.location.host + '/api/mcp'))}</span>
            </div>
            <button class="btn btn-secondary" style="font-size: 11px; padding: 4px 10px; min-height: 28px;" onclick="copyMcpLanEndpoint()">
              <span class="material-symbols-outlined" style="font-size: 14px;">content_copy</span>
              Copy LAN Endpoint
            </button>
          </div>
        </div>
      </div>

      <!-- 11 Semantic Tools Accordion -->
      <div class="tech-card">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">terminal</span>
            nexus-semantic-v1 Tool Catalog (${tools.length})
          </span>
        </div>
        <div style="display: flex; flex-direction: column; gap: 8px;">
          ${tools.map((t, idx) => `
            <div style="background: var(--surface-2); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); overflow: hidden;">
              <div style="padding: 10px 14px; display: flex; justify-content: space-between; align-items: center; cursor: pointer;" onclick="toggleToolAccordion('tool-desc-${idx}')">
                <div>
                  <span class="font-mono" style="font-weight: 600; color: var(--primary); font-size: 13px;">${escapeHtml(t.name)}</span>
                  <div style="color: var(--on-surface-variant); font-size: 11px; margin-top: 2px;">${escapeHtml(t.description)}</div>
                </div>
                <span class="material-symbols-outlined" style="font-size: 18px; color: var(--on-surface-muted);">expand_more</span>
              </div>
              <div id="tool-desc-${idx}" style="display: none; padding: 12px 14px; background: var(--surface-3); border-top: 1px solid var(--border-subtle); font-size: 12px;">
                <div style="font-weight: 600; color: var(--on-surface-muted); margin-bottom: 6px;">Input Parameters:</div>
                <pre class="font-mono" style="background: #000; padding: 8px; border-radius: 4px; overflow-x: auto; color: #a5d6a7; font-size: 11px;">${escapeHtml(JSON.stringify(t.parameters, null, 2))}</pre>
                ${t.required && t.required.length ? `
                  <div style="margin-top: 6px; color: var(--status-warning);">Required fields: ${escapeHtml(t.required.join(', '))}</div>
                ` : ''}
              </div>
            </div>
          `).join('')}
        </div>
      </div>

      <!-- Authorized Clients Table -->
      <div class="tech-card">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">security</span>
            Authorized Remote Clients & Tokens (${clients.length})
          </span>
          ${isAdmin() ? `
            <button class="btn btn-secondary" style="font-size: 11px; padding: 4px 10px; min-height: 28px;" onclick="promptCreateAgentToken()">
              + New Agent Token
            </button>
          ` : ''}
        </div>
        ${clients.length === 0 ? `
          <div style="color: var(--on-surface-muted); font-size: 13px; padding: 16px;">No external client tokens registered.</div>
        ` : `
          <div style="overflow-x: auto;">
            <table class="tech-table">
              <thead>
                <tr>
                  <th>Principal</th>
                  <th>Description</th>
                  <th>Capabilities</th>
                  <th>Created</th>
                  <th>Last Used</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                ${clients.map(c => `
                  <tr>
                    <td class="font-mono" style="font-weight: 600; color: var(--on-surface-bright);">${escapeHtml(c.principal)}</td>
                    <td>${escapeHtml(c.description || '—')}</td>
                    <td class="font-mono" style="font-size: 11px;">${escapeHtml((c.capabilities || []).join(', ') || 'ALL')}</td>
                    <td class="font-mono" style="font-size: 11px;">${formatDateTime(c.created_at)}</td>
                    <td class="font-mono" style="font-size: 11px;">${formatTimeAgo(c.last_used_at)}</td>
                    <td>
                      ${c.revoked ? '<span class="status-badge badge-critical">REVOKED</span>' : '<span class="status-badge badge-healthy">ACTIVE</span>'}
                    </td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        `}
      </div>

      <!-- Safe Activity Trace -->
      <div class="tech-card">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">history</span>
            Recent Consequential Activity Trace (${activity.length})
          </span>
        </div>
        ${activity.length === 0 ? `
          <div style="color: var(--on-surface-muted); font-size: 13px; padding: 16px;">No recent agent audit records.</div>
        ` : `
          <div style="overflow-x: auto;">
            <table class="tech-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Operation</th>
                  <th>Principal</th>
                  <th>Status</th>
                  <th>Latency</th>
                </tr>
              </thead>
              <tbody>
                ${activity.map(a => `
                  <tr>
                    <td class="font-mono" style="font-size: 11px;">${formatDateTime(a.timestamp)}</td>
                    <td class="font-mono" style="font-weight: 600; color: var(--primary);">${escapeHtml(a.operation)}</td>
                    <td class="font-mono">${escapeHtml(a.principal || '—')}</td>
                    <td>${renderStatusBadge(a.status)}</td>
                    <td class="font-mono">${a.duration_ms ? a.duration_ms.toFixed(0) + 'ms' : '—'}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        `}
      </div>

    </div>
  `;
}

function copyMcpPublicEndpoint() {
  const el = document.getElementById('mcpPublicEndpointUrl');
  if (el) {
    navigator.clipboard.writeText(el.textContent.trim()).then(() => {
      showToast('Public MCP Endpoint copied to clipboard!', 'success');
    }).catch(() => {
      showToast('Could not copy to clipboard', 'warning');
    });
  }
}

function copyMcpLanEndpoint() {
  const el = document.getElementById('mcpLanEndpointUrl');
  if (el) {
    navigator.clipboard.writeText(el.textContent.trim()).then(() => {
      showToast('Local LAN MCP Endpoint copied to clipboard!', 'success');
    }).catch(() => {
      showToast('Could not copy to clipboard', 'warning');
    });
  }
}

function copyMcpEndpoint() {
  copyMcpPublicEndpoint();
}

function toggleToolAccordion(elId) {
  const el = document.getElementById(elId);
  if (el) {
    el.style.display = el.style.display === 'none' ? 'block' : 'none';
  }
}

async function promptCreateAgentToken() {
  const principal = prompt('Enter agent principal name (e.g. spark-agent, mistral-client):', 'gemini-spark');
  if (!principal || !principal.trim()) return;

  const desc = prompt('Enter token description:', 'Remote MCP Agent Token');

  try {
    const res = await apiJson('/api/admin/agent-tokens', {
      method: 'POST',
      body: { principal: principal.trim(), description: desc || '' }
    });
    alert(`Generated Token (Save securely; won't be shown again):\n\n${res.token}`);
    loadMcp();
  } catch (err) {
    showToast(`Failed to generate token: ${err.message}`, 'error');
  }
}
