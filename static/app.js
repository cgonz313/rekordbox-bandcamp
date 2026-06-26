/* bandcamp → rekordbox  |  client-side logic */

let ws;

// ── DOM refs ──────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);

const indexBtn          = $('index-btn');
const indexStatus       = $('index-status');
const indexProgress     = $('index-progress');
const indexFill         = $('index-fill');
const indexLabel        = $('index-label');
const musicDirsList     = $('music-dirs-list');
const addDirBtn         = $('add-dir-btn');
const exportDirInput    = $('export-dir-input');
const exportDirBrowse   = $('export-dir-browse-btn');
const exportDirSave     = $('export-dir-save-btn');

// ── Folder browser ────────────────────────────────────────────────────────────
const browseModal    = $('browse-modal');
const browsePath     = $('browse-path');
const browseList     = $('browse-list');
const browseSelect   = $('browse-select');
const browseCancel   = $('browse-cancel');
const browseClose    = $('browse-close');

let currentBrowsePath = '';
let browseTarget = null; // { input, action }

async function browseDir(path) {
  const params = path ? `?path=${encodeURIComponent(path)}` : '';
  const res = await fetch(`/browse${params}`);
  const data = await res.json();
  if (data.error) { setStatus(data.error, true); return; }

  currentBrowsePath = data.path || '';
  browsePath.textContent = currentBrowsePath || 'Drives';
  browseSelect.disabled = !currentBrowsePath;
  browseList.innerHTML = '';

  if (data.parent !== undefined && data.parent !== null) {
    const up = document.createElement('div');
    up.className = 'dir-entry dir-up';
    up.innerHTML = `<span class="dir-icon">↑</span><span>Parent folder</span>`;
    up.addEventListener('click', () => browseDir(data.parent));
    browseList.appendChild(up);
  }

  for (const entry of data.entries) {
    const row = document.createElement('div');
    row.className = 'dir-entry';
    row.innerHTML = `<span class="dir-icon">▶</span><span>${escHtml(entry.name)}</span>`;
    row.addEventListener('click', () => browseDir(entry.path));
    browseList.appendChild(row);
  }

  if (data.entries.length === 0 && !data.parent) {
    browseList.innerHTML = `<div style="padding:16px 20px;color:var(--muted);font-size:13px">No subfolders found</div>`;
  }
}

function openBrowser(wsAction, startPath = '') {
  browseTarget = { action: wsAction };
  browseModal.classList.remove('hidden');
  browseDir(startPath || '');
}

function closeBrowser() {
  browseModal.classList.add('hidden');
  browseTarget = null;
}

addDirBtn.addEventListener('click',          () => openBrowser('add_music_dir'));
exportDirBrowse.addEventListener('click',    () => openBrowser('set_export_dir', exportDirInput.value.trim()));
browseClose.addEventListener('click',  closeBrowser);
browseCancel.addEventListener('click', closeBrowser);
browseModal.addEventListener('click', e => {
  if (e.target === browseModal) closeBrowser();
});

browseSelect.addEventListener('click', () => {
  if (currentBrowsePath && browseTarget) {
    if (browseTarget.action === 'set_export_dir') {
      exportDirInput.value = currentBrowsePath;
    }
    send({ action: browseTarget.action, path: currentBrowsePath });
    closeBrowser();
  }
});

const loginBtn       = $('login-btn');
const loginStatus    = $('login-status');

const playlistsCard  = $('playlists-card');
const playlistList   = $('playlist-list');
const selectAllRow   = $('select-all-row');
const selectAllChk   = $('select-all-chk');
const exportBtn      = $('export-btn');

const matchProgress  = $('match-progress');
const matchFill      = $('match-fill');
const matchLabel     = $('match-label');

const results        = $('results');
const statMatched    = $('stat-matched');
const statTotal      = $('stat-total');
const statUnmatched  = $('stat-unmatched');
const downloadLink   = $('download-link');
const unmatchedToggle = $('unmatched-toggle');
const unmatchedList  = $('unmatched-list');

const statusbar      = $('statusbar');

// ── WebSocket ─────────────────────────────────────────────────────────────────
function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);

  ws.onopen = () => setStatus('Connected');

  ws.onmessage = e => {
    const msg = JSON.parse(e.data);
    handle(msg);
  };

  ws.onclose = () => {
    setStatus('Disconnected — retrying…', true);
    setTimeout(connect, 2000);
  };
}

function send(obj) {
  if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

// ── Message handler ───────────────────────────────────────────────────────────
function handle(msg) {
  switch (msg.type) {

    case 'init':
      if (msg.music_dirs)  renderMusicDirs(msg.music_dirs);
      if (msg.export_dir)  exportDirInput.value = msg.export_dir;
      if (msg.indexed > 0) setIndexDone(msg.indexed);
      if (msg.username)    setLoggedIn(msg.username);
      if (msg.playlists?.length) renderPlaylists(msg.playlists);
      if (msg.last_export) showDownload(msg.last_export);
      break;

    case 'music_dirs_updated':
      renderMusicDirs(msg.dirs);
      indexStatus.textContent = '';
      setStatus('Music folders updated — click Index Library to scan');
      break;

    case 'export_dir_set':
      exportDirInput.value = msg.path;
      setStatus(`Export directory set to ${msg.path}`);
      break;

    case 'index_start':
      indexBtn.disabled = true;
      indexProgress.classList.remove('hidden');
      setStatus(`Indexing ${msg.total.toLocaleString()} files…`);
      break;

    case 'index_progress':
      const pct = Math.round((msg.current / msg.total) * 100);
      indexFill.style.width = pct + '%';
      indexLabel.textContent = `${msg.current.toLocaleString()} / ${msg.total.toLocaleString()} files`;
      break;

    case 'index_done':
      setIndexDone(msg.count);
      break;

    case 'login_opened':
      loginBtn.disabled = true;
      loginStatus.textContent = 'Log into Bandcamp in the browser window…';
      setStatus('Waiting for Bandcamp login…');
      break;

    case 'logged_in':
      setLoggedIn(msg.username);
      send({ action: 'get_playlists' });
      break;

    case 'playlists':
      renderPlaylists(msg.items);
      setStatus(`Found ${msg.items.length} playlists`);
      break;

    case 'status':
      setStatus(msg.message);
      break;

    case 'match_progress':
      matchProgress.classList.remove('hidden');
      const mpct = Math.round((msg.current / msg.total) * 100);
      matchFill.style.width = mpct + '%';
      matchLabel.textContent =
        `${msg.playlist} — ${msg.matched}/${msg.current} matched (${msg.current}/${msg.total})`;
      break;

    case 'export_done':
      matchProgress.classList.add('hidden');
      showExportResults(msg);
      break;

    case 'need_username':
      const u = prompt("Could not detect your Bandcamp username automatically.\nEnter your Bandcamp username (e.g. cgonz313):");
      if (u) send({ action: 'set_username', username: u.trim() });
      break;

    case 'error':
      setStatus(msg.message, true);
      break;
  }
}

// ── UI helpers ────────────────────────────────────────────────────────────────
function renderMusicDirs(dirs) {
  musicDirsList.innerHTML = '';
  for (const dir of dirs) {
    const row = document.createElement('div');
    row.className = 'music-dir-item';
    row.innerHTML = `<span class="dir-icon">▶</span><span class="music-dir-path">${escHtml(dir)}</span><button class="btn-remove" title="Remove">×</button>`;
    row.querySelector('.btn-remove').addEventListener('click', () => {
      send({ action: 'remove_music_dir', path: dir });
    });
    musicDirsList.appendChild(row);
  }
}

function setStatus(text, isError = false) {
  statusbar.textContent = text;
  statusbar.className = isError ? 'error' : '';
}

function setIndexDone(count) {
  indexBtn.disabled = false;
  indexBtn.textContent = 'Re-index';
  indexProgress.classList.remove('hidden');
  indexFill.style.width = '100%';
  indexLabel.textContent = `${count.toLocaleString()} files indexed`;
  indexStatus.textContent = `${count.toLocaleString()} files`;
  loginBtn.disabled = false;
  setStatus('Library indexed — connect to Bandcamp');
}

function setLoggedIn(username) {
  loginBtn.disabled = false;
  loginBtn.textContent = 'Reconnect';
  loginStatus.textContent = username;
}

function renderPlaylists(items) {
  playlistsCard.classList.remove('hidden');
  playlistList.innerHTML = '';

  items.forEach(pl => {
    const row = document.createElement('label');
    row.className = 'playlist-row';
    row.innerHTML = `
      <input type="checkbox" value="${pl.url}" data-name="${escHtml(pl.name)}">
      <span class="playlist-name">${escHtml(pl.name)}</span>
      <span class="playlist-count">${pl.track_count} tracks</span>
    `;
    playlistList.appendChild(row);
  });

  updateSelectAll();
  playlistList.querySelectorAll('input').forEach(cb =>
    cb.addEventListener('change', updateExportBtn)
  );
  updateExportBtn();
}

function updateSelectAll() {
  selectAllRow.classList.remove('hidden');
  selectAllChk.addEventListener('change', () => {
    playlistList.querySelectorAll('input[type="checkbox"]').forEach(cb => {
      cb.checked = selectAllChk.checked;
    });
    updateExportBtn();
  });
}

function updateExportBtn() {
  const checked = playlistList.querySelectorAll('input:checked').length;
  exportBtn.disabled = checked === 0;
  exportBtn.textContent = checked > 0
    ? `Export ${checked} playlist${checked > 1 ? 's' : ''}`
    : 'Export';
}

function showExportResults(msg) {
  results.style.display = 'block';
  statMatched.textContent  = msg.matched;
  statTotal.textContent    = msg.total;
  statUnmatched.textContent = msg.unmatched.length;
  showDownload(msg.filename);

  if (msg.unmatched.length > 0) {
    unmatchedToggle.classList.remove('hidden');
    unmatchedList.innerHTML = msg.unmatched.map(escHtml).join('<br>');
  }
  setStatus(`Exported → ${msg.filename}`);
}

function showDownload(filename) {
  const name = filename.split('/').pop();
  downloadLink.href = `/download/${encodeURIComponent(filename)}`;
  downloadLink.download = name;
  downloadLink.textContent = `Download ${name}`;
  results.style.display = 'block';
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Button handlers ───────────────────────────────────────────────────────────
exportDirSave.addEventListener('click', () => {
  const path = exportDirInput.value.trim();
  if (path) send({ action: 'set_export_dir', path });
});

exportDirInput.addEventListener('keydown', e => {
  if (e.key === 'Enter') exportDirSave.click();
});

indexBtn.addEventListener('click', () => send({ action: 'index' }));

loginBtn.addEventListener('click', () => send({ action: 'login' }));

exportBtn.addEventListener('click', () => {
  const selected = [...playlistList.querySelectorAll('input:checked')].map(cb => ({
    name: cb.dataset.name,
    url:  cb.value,
  }));
  matchProgress.classList.remove('hidden');
  matchFill.style.width = '0%';
  results.style.display = 'none';
  exportBtn.disabled = true;
  send({ action: 'export', playlists: selected });
});

unmatchedToggle.addEventListener('click', () => {
  const visible = unmatchedList.style.display === 'block';
  unmatchedList.style.display = visible ? 'none' : 'block';
  unmatchedToggle.textContent = visible
    ? `Show ${unmatchedList.children.length} unmatched tracks`
    : 'Hide unmatched';
});

// ── Theme ─────────────────────────────────────────────────────────────────────
const themeToggle = $('theme-toggle');
const themeIcon   = $('theme-icon');
const rbLogo      = document.querySelector('.logo-rb');

const ICONS = {
  light: '<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>',
  dark:  '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>',
};

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  rbLogo.src = theme === 'light'
    ? '/static/images/rb-logo-blk.png'
    : '/static/images/rb-logo.png';
  themeIcon.innerHTML = theme === 'light' ? ICONS.dark : ICONS.light;
  localStorage.setItem('theme', theme);
}

themeToggle.addEventListener('click', () => {
  setTheme(document.documentElement.dataset.theme === 'light' ? 'dark' : 'light');
});

setTheme(localStorage.getItem('theme') || 'dark');

// ── Init ──────────────────────────────────────────────────────────────────────
connect();
