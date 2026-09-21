/**
 * NexusNode — Vault File Manager Controller
 * Phase 4.2A Product Rebase
 * First-class file explorer: list, search, breadcrumbs, upload, download, mkdir, rename, delete, preview.
 */

let currentVaultPath = '';
let cachedVaultFiles = [];
let vaultSearchQuery = '';

async function loadVault(path = '') {
  currentVaultPath = path;
  const container = document.getElementById('vaultContent');
  if (!container) return;

  container.innerHTML = '<div style="color: var(--on-surface-muted); padding: 24px 0;">Loading Vault contents...</div>';

  try {
    const data = await apiJson(`/files?path=${encodeURIComponent(path)}`);
    cachedVaultFiles = (data && data.files) || [];
    renderVaultView();
  } catch (err) {
    container.innerHTML = `
      <div class="tech-card" style="border-color: var(--status-critical);">
        <div class="tech-card-header">
          <span class="tech-card-title" style="color: var(--status-critical);">Vault Access Error</span>
          <button class="btn btn-secondary" onclick="loadVault('')">Root</button>
        </div>
        <p style="color: var(--on-surface-variant); font-size: 13px;">${escapeHtml(err.message)}</p>
      </div>
    `;
  }
}

function renderVaultView() {
  const container = document.getElementById('vaultContent');
  if (!container) return;

  // Build breadcrumbs
  const parts = currentVaultPath ? currentVaultPath.split('/').filter(Boolean) : [];
  let breadcrumbHtml = `<span style="cursor: pointer; color: var(--primary);" onclick="loadVault('')">Vault Root</span>`;
  let accum = '';
  for (let i = 0; i < parts.length; i++) {
    accum += (accum ? '/' : '') + parts[i];
    const target = accum;
    breadcrumbHtml += ` <span style="color: var(--on-surface-muted);">/</span> <span style="cursor: pointer; color: ${i === parts.length - 1 ? 'var(--on-surface-bright)' : 'var(--primary)'};" onclick="loadVault('${escapeHtml(target)}')">${escapeHtml(parts[i])}</span>`;
  }

  // Filter files by search query
  let files = cachedVaultFiles;
  if (vaultSearchQuery.trim()) {
    const q = vaultSearchQuery.toLowerCase();
    files = cachedVaultFiles.filter(f => f.name.toLowerCase().includes(q));
  }

  container.innerHTML = `
    <div style="display: flex; flex-direction: column; gap: 14px;">
      
      <!-- Top Action Bar -->
      <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
        <div style="font-size: 13px; display: flex; align-items: center; gap: 4px;">
          <span class="material-symbols-outlined" style="font-size: 18px; color: var(--primary);">folder</span>
          ${breadcrumbHtml}
        </div>
        <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
          <input type="text" class="form-input" placeholder="Search Vault files..." value="${escapeHtml(vaultSearchQuery)}" oninput="handleVaultSearch(this.value)" style="width: 180px; min-height: 32px; padding: 4px 8px; font-size: 12px;">
          <button class="btn btn-secondary" style="font-size: 11px; padding: 4px 10px; min-height: 32px;" onclick="promptNewFolder()">
            <span class="material-symbols-outlined" style="font-size: 14px;">create_new_folder</span>
            New Folder
          </button>
          <label class="btn btn-primary" style="font-size: 11px; padding: 4px 12px; min-height: 32px; cursor: pointer; margin-bottom: 0;">
            <span class="material-symbols-outlined" style="font-size: 14px;">upload</span>
            Upload File
            <input type="file" id="vaultUploadInput" style="display: none;" onchange="handleVaultUpload(this)">
          </label>
        </div>
      </div>

      <!-- File Table Card -->
      <div class="tech-card">
        <div class="tech-card-header">
          <span class="tech-card-title">
            <span class="material-symbols-outlined">storage</span>
            Objects (${files.length})
          </span>
          ${parts.length > 0 ? `
            <button class="btn btn-secondary" style="padding: 2px 8px; font-size: 11px; min-height: 24px;" onclick="navigateVaultUp()">
              <span class="material-symbols-outlined" style="font-size: 13px;">arrow_upward</span> Up One Level
            </button>
          ` : ''}
        </div>
        
        ${files.length === 0 ? `
          <div style="color: var(--on-surface-muted); font-size: 13px; padding: 32px; text-align: center;">
            No files or folders in this directory.
          </div>
        ` : `
          <div style="overflow-x: auto;">
            <table class="tech-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Size</th>
                  <th>Category</th>
                  <th>Modified</th>
                  <th style="text-align: right;">Actions</th>
                </tr>
              </thead>
              <tbody>
                ${files.map(f => {
                  const isImage = !f.is_dir && ['photos'].includes(f.category);
                  const icon = f.is_dir ? 'folder' : (f.category === 'photos' ? 'image' : (f.category === 'documents' ? 'description' : (f.category === 'music' ? 'audio_file' : (f.category === 'videos' ? 'video_file' : 'draft'))));
                  return `
                    <tr>
                      <td>
                        <div style="display: flex; align-items: center; gap: 8px;">
                          <span class="material-symbols-outlined" style="font-size: 18px; color: ${f.is_dir ? 'var(--primary)' : 'var(--on-surface-muted)'};">
                            ${icon}
                          </span>
                          ${f.is_dir ? `
                            <span style="font-weight: 600; color: var(--primary); cursor: pointer;" onclick="loadVault('${escapeHtml(f.path)}')">
                              ${escapeHtml(f.name)}
                            </span>
                          ` : `
                            <span style="font-weight: 500; color: var(--on-surface-bright); ${isImage ? 'cursor: pointer;' : ''}" ${isImage ? `onclick="previewVaultImage('/download/${encodeURIComponent(f.path)}?inline=true', '${escapeHtml(f.name)}')"` : ''}>
                              ${escapeHtml(f.name)}
                            </span>
                          `}
                        </div>
                      </td>
                      <td class="font-mono">${f.is_dir ? '—' : formatBytes(f.size)}</td>
                      <td style="color: var(--on-surface-muted); text-transform: capitalize;">${escapeHtml(f.category || 'file')}</td>
                      <td class="font-mono" style="font-size: 11px;">${formatDateTime(f.modified)}</td>
                      <td style="text-align: right; white-space: nowrap;">
                        ${isImage ? `
                          <button class="icon-btn" title="Preview Image" onclick="previewVaultImage('/download/${encodeURIComponent(f.path)}?inline=true', '${escapeHtml(f.name)}')">
                            <span class="material-symbols-outlined" style="font-size: 16px;">visibility</span>
                          </button>
                        ` : ''}
                        <button class="icon-btn" title="Download" onclick="window.open('/download/${encodeURIComponent(f.path)}')">
                          <span class="material-symbols-outlined" style="font-size: 16px;">download</span>
                        </button>
                        <button class="icon-btn" title="Rename" onclick="promptRename('${escapeHtml(f.path)}', '${escapeHtml(f.name)}')">
                          <span class="material-symbols-outlined" style="font-size: 16px;">edit</span>
                        </button>
                        <button class="icon-btn" title="Delete" style="color: var(--status-critical);" onclick="confirmDelete('${escapeHtml(f.path)}', '${escapeHtml(f.name)}')">
                          <span class="material-symbols-outlined" style="font-size: 16px;">delete</span>
                        </button>
                      </td>
                    </tr>
                  `;
                }).join('')}
              </tbody>
            </table>
          </div>
        `}
      </div>

    </div>

    <!-- Image Preview Modal -->
    <div id="vaultPhotoModal" class="photo-modal-overlay" style="display: none;" onclick="closeVaultPhotoModal(event)">
      <div class="photo-modal-card" onclick="event.stopPropagation()">
        <div class="photo-modal-header">
          <span id="vaultPhotoTitle" style="font-weight: 600; color: var(--on-surface-bright);"></span>
          <button class="icon-btn" onclick="closeVaultPhotoModal()">&times;</button>
        </div>
        <div class="photo-modal-body">
          <img id="vaultPhotoImg" src="" alt="Preview" style="max-width: 100%; max-height: 70vh; object-fit: contain;">
        </div>
      </div>
    </div>
  `;
}

function handleVaultSearch(q) {
  vaultSearchQuery = q;
  renderVaultView();
}

function navigateVaultUp() {
  if (!currentVaultPath) return;
  const parts = currentVaultPath.split('/').filter(Boolean);
  parts.pop();
  loadVault(parts.join('/'));
}

async function promptNewFolder() {
  const folderName = prompt('Enter new folder name:');
  if (!folderName || !folderName.trim()) return;

  try {
    await apiJson('/api/vault/mkdir', {
      method: 'POST',
      body: { path: currentVaultPath, name: folderName.trim() }
    });
    showToast(`Folder '${folderName}' created.`, 'success');
    loadVault(currentVaultPath);
  } catch (err) {
    showToast(`Failed to create folder: ${err.message}`, 'error');
  }
}

async function promptRename(oldPath, oldName) {
  const newName = prompt('Enter new name for item:', oldName);
  if (!newName || !newName.trim() || newName.trim() === oldName) return;

  try {
    await apiJson('/api/vault/rename', {
      method: 'POST',
      body: { old_path: oldPath, new_name: newName.trim() }
    });
    showToast(`Renamed to '${newName}'.`, 'success');
    loadVault(currentVaultPath);
  } catch (err) {
    showToast(`Rename failed: ${err.message}`, 'error');
  }
}

async function confirmDelete(filePath, fileName) {
  if (!confirm(`Are you sure you want to delete '${fileName}'?`)) return;

  try {
    await apiJson('/delete', {
      method: 'POST',
      body: { filename: filePath }
    });
    showToast(`'${fileName}' deleted.`, 'info');
    loadVault(currentVaultPath);
  } catch (err) {
    showToast(`Delete failed: ${err.message}`, 'error');
  }
}

async function handleVaultUpload(fileInput) {
  if (!fileInput.files || !fileInput.files.length) return;
  const file = fileInput.files[0];

  const formData = new FormData();
  formData.append('file', file);
  formData.append('path', currentVaultPath);

  showToast(`Uploading '${file.name}'...`, 'info');

  try {
    const res = await apiFetch('/upload', {
      method: 'POST',
      body: formData
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.error || `HTTP ${res.status}`);
    }
    showToast(`'${file.name}' uploaded successfully!`, 'success');
    fileInput.value = '';
    loadVault(currentVaultPath);
  } catch (err) {
    showToast(`Upload failed: ${err.message}`, 'error');
  }
}

function previewVaultImage(imgUrl, fileName) {
  const modal = document.getElementById('vaultPhotoModal');
  const img = document.getElementById('vaultPhotoImg');
  const title = document.getElementById('vaultPhotoTitle');
  if (modal && img && title) {
    img.src = imgUrl;
    title.textContent = fileName;
    modal.style.display = 'flex';
  }
}

function closeVaultPhotoModal(e) {
  const modal = document.getElementById('vaultPhotoModal');
  if (modal) modal.style.display = 'none';
}
