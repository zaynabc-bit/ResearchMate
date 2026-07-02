/* ============================================
   ResearchMate — Frontend Application Logic
   ============================================ */

// Supabase Config
const supabaseUrl = 'https://fsuztgcsrbuvhvnnblbl.supabase.co';
const supabaseKey = 'sb_publishable_k-kL82doDKALUtUgGuuOgg_gd7DTJnj';
let supabaseClient = null;
try {
  if (window.supabase) {
    supabaseClient = window.supabase.createClient(supabaseUrl, supabaseKey);
  } else {
    console.warn("Supabase SDK not loaded from CDN.");
  }
} catch (e) {
  console.error("Failed to initialize Supabase:", e);
}
let session = null;

// Intercept fetch to support custom Backend API URL (for hosting on GitHub Pages)
const originalFetch = window.fetch;
window.fetch = function(input, init) {
  let url = typeof input === 'string' ? input : input.url;
  const backendUrl = localStorage.getItem('rm_backend_url') || '';
  
  if (url.startsWith('/api/') && backendUrl) {
    const baseUrl = backendUrl.endsWith('/') ? backendUrl.slice(0, -1) : backendUrl;
    url = baseUrl + url;
    if (typeof input === 'string') {
      input = url;
    } else {
      input = new Request(url, input);
    }
  }

  // Inject Supabase Auth Token
  if (session && session.access_token) {
    init = init || {};
    init.headers = init.headers || {};
    if (init.headers instanceof Headers) {
      init.headers.set('Authorization', `Bearer ${session.access_token}`);
    } else {
      init.headers['Authorization'] = `Bearer ${session.access_token}`;
    }
  }

  return originalFetch(input, init);
};

// ---- State ----
const state = {
  papers: [],
  folders: [],
  currentView: 'home',
  currentPaper: null,
  currentTab: 'summary',
  chatHistory: [],
  notesTimer: null,
  searchQuery: '',
  sortBy: 'created_at',
  selectedColour: '#6366f1',
  editingFolderId: null,
  zoom: 1,
  aiMode: 'phi3',          // 'phi3', 'fast', 'smart', 'vision', 'vision_pro' or 'openai', 'gemini', 'deepseek'
  phi3Model: 'phi3:latest',
  fastModel: 'llama3.2:3b',
  smartModel: 'qwen2.5:3b',
  visionModel: 'moondream:latest',
  visionProModel: 'llava:7b',
  ragAvailable: true,
  enabledCloud: {
    openai: false,
    gemini: false,
    deepseek: false
  },
  keys: {
    openai: '',
    gemini: '',
    deepseek: ''
  },
  selectedPaperIds: [],
  comparisons: [],
  activeComparison: null
};

const FOLDER_COLOURS = [
  '#6366f1', '#3b82f6', '#8b5cf6', '#ec4899',
  '#f59e0b', '#10b981', '#ef4444', '#06b6d4',
];

// UI Initialization
window.addEventListener('DOMContentLoaded', async () => {
  // Apply theme first
  const savedTheme = localStorage.getItem('theme') || 'dark';
  if (savedTheme === 'light') {
    document.documentElement.setAttribute('data-theme', 'light');
    const toggleBtn = document.getElementById('theme-toggle');
    if (toggleBtn) toggleBtn.textContent = '🌙';
  }

  // Show home immediately
  switchView('home');

  // Check if already logged in
  if (supabaseClient) {
    try {
      const { data } = await supabaseClient.auth.getSession();
      if (data && data.session) {
        session = data.session;
        updateAuthUI(data.session);
      }
    } catch (err) {
      console.warn('Auth check failed silently:', err);
    }
  }

  // Load API Keys
  state.keys.openai = localStorage.getItem('key-openai') || '';
  state.keys.gemini = localStorage.getItem('key-gemini') || '';
  state.keys.deepseek = localStorage.getItem('key-deepseek') || '';
  state.enabledCloud.openai = localStorage.getItem('enable-openai') === 'true';
  state.enabledCloud.gemini = localStorage.getItem('enable-gemini') === 'true';
  state.enabledCloud.deepseek = localStorage.getItem('enable-deepseek') === 'true';

  updateAvailableModels();
  const savedMode = localStorage.getItem('aiMode') || 'fast';
  setMode(savedMode);

  checkAIStatus();
  renderColourSwatches();
  await loadFolders();
  await loadPapers();
  updateHomeDashboard();
});

// Auth UI helpers
function getGreeting() {
  const hour = new Date().getHours();
  if (hour >= 5 && hour < 12) return { text: 'Good morning', emoji: '☀️' };
  if (hour >= 12 && hour < 17) return { text: 'Good afternoon', emoji: '🌤️' };
  if (hour >= 17 && hour < 21) return { text: 'Good evening', emoji: '🌆' };
  return { text: 'Good night', emoji: '🌙' };
}

function updateAuthUI(sess) {
  const handle = sess ? (sess.user.email || '').replace('@researchmate.app', '') : null;
  const displayName = sess ? (sess.user.user_metadata && sess.user.user_metadata.display_name) || handle : null;
  const signUpBtn = document.getElementById('btn-sidebar-signup');
  const loginBtn = document.getElementById('btn-sidebar-login');
  const logoutBtn = document.getElementById('btn-sidebar-logout');
  const userInfo = document.getElementById('auth-user-info');
  const handleDisplay = document.getElementById('auth-handle-display');
  const greetingBar = document.getElementById('greeting-bar');
  const greetingText = document.getElementById('greeting-text');
  const greetingEmoji = document.getElementById('greeting-emoji');

  if (sess) {
    if (signUpBtn) signUpBtn.style.display = 'none';
    if (loginBtn) loginBtn.style.display = 'none';
    if (logoutBtn) logoutBtn.style.display = 'flex';
    if (userInfo) { userInfo.style.display = 'flex'; }
    if (handleDisplay) handleDisplay.textContent = displayName || ('@' + handle);

    // Show greeting bar
    if (greetingBar) {
      const { text, emoji } = getGreeting();
      const name = displayName || handle;
      greetingBar.style.display = 'flex';
      if (greetingText) greetingText.textContent = text + ', ' + name + '!';
      if (greetingEmoji) greetingEmoji.textContent = emoji;
    }
  } else {
    if (signUpBtn) signUpBtn.style.display = 'flex';
    if (loginBtn) loginBtn.style.display = 'flex';
    if (logoutBtn) logoutBtn.style.display = 'none';
    if (userInfo) userInfo.style.display = 'none';

    // Hide greeting bar
    if (greetingBar) greetingBar.style.display = 'none';
  }
}

function openAuthModal(type) {
  const overlay = document.getElementById('auth-modal-overlay');
  const title = document.getElementById('auth-modal-title');
  const submitBtn = document.getElementById('auth-modal-submit');
  const toggleText = document.getElementById('auth-toggle-text');
  const errorMsg = document.getElementById('auth-error-msg');
  const nameField = document.getElementById('auth-name-field');
  if (errorMsg) { errorMsg.textContent = ''; errorMsg.style.color = '#ef4444'; }
  document.getElementById('auth-handle').value = '';
  document.getElementById('auth-passphrase').value = '';
  if (document.getElementById('auth-displayname')) document.getElementById('auth-displayname').value = '';

  if (type === 'signup') {
    title.textContent = 'Sign Up';
    submitBtn.textContent = 'Create Account';
    toggleText.textContent = 'Log In instead';
    if (nameField) nameField.style.display = 'block';
  } else {
    title.textContent = 'Log In';
    submitBtn.textContent = 'Log In';
    toggleText.textContent = 'Sign Up instead';
    if (nameField) nameField.style.display = 'none';
  }
  overlay.style.display = 'flex';
}

function closeAuthModal() {
  document.getElementById('auth-modal-overlay').style.display = 'none';
}

function toggleAuthMode() {
  const title = document.getElementById('auth-modal-title');
  const isSignup = title.textContent === 'Sign Up';
  openAuthModal(isSignup ? 'login' : 'signup');
}

async function handleAuth(type) {
  const handle = (document.getElementById('auth-handle').value || '').trim();
  let pass = (document.getElementById('auth-passphrase').value || '').trim();
  const displayName = type === 'signup' ? ((document.getElementById('auth-displayname') || {}).value || '').trim() : '';
  const errorMsg = document.getElementById('auth-error-msg');
  errorMsg.textContent = '';

  if (type === 'signup' && !displayName) {
    errorMsg.textContent = 'Please enter your name.';
    return;
  }
  if (!handle) {
    errorMsg.textContent = 'Please enter a username.';
    return;
  }
  if (!pass) {
    errorMsg.textContent = 'Please enter a passphrase.';
    return;
  }

  // Sanitise handle
  const safeHandle = handle.toLowerCase().replace(/[^a-z0-9_\-]/g, '');
  if (!safeHandle) {
    errorMsg.textContent = 'Username can only contain letters, numbers, _ and -';
    return;
  }

  // Pad password to meet Supabase 6-char minimum silently
  while (pass.length < 6) pass += '0';

  const email = safeHandle + '@researchmate.app';

  const submitBtn = document.getElementById('auth-modal-submit');
  const originalText = submitBtn.textContent;
  submitBtn.textContent = 'Working...';
  submitBtn.disabled = true;

  try {
    let result;
    if (type === 'signup') {
      result = await supabaseClient.auth.signUp({
        email,
        password: pass,
        options: {
          emailRedirectTo: null,
          data: {
            username: safeHandle,
            display_name: displayName
          }
        }
      });
    } else {
      result = await supabaseClient.auth.signInWithPassword({ email, password: pass });
    }

    submitBtn.textContent = originalText;
    submitBtn.disabled = false;

    if (result.error) {
      let msg = result.error.message;
      if (msg.includes('User already registered')) msg = 'Account exists. Try logging in instead.';
      else if (msg.includes('Invalid login credentials')) msg = 'Wrong username or passphrase.';
      else if (msg.includes('rate limit') || msg.includes('over_email_send_rate_limit') || msg.includes('email rate limit')) {
        msg = 'Rate limit hit. Please disable "Confirm email" in your Supabase Dashboard under Authentication → Providers → Email, then try again.';
      }
      errorMsg.textContent = msg;
      return;
    }

    if (type === 'signup') {
      // After sign up, take them to the login page to confirm credentials
      openAuthModal('login');
      document.getElementById('auth-handle').value = safeHandle;
      document.getElementById('auth-error-msg').textContent = '';
      // Show a success message inside the login modal
      const successEl = document.getElementById('auth-error-msg');
      if (successEl) {
        successEl.style.color = '#22c55e';
        successEl.textContent = '✅ Account created! Now log in with your passphrase.';
      }
      showToast('Account created! Now log in 🎉');
    } else {
      session = result.data.session;
      updateAuthUI(session);
      closeAuthModal();
      const greeting = displayName || safeHandle;
      showToast('Welcome back, ' + greeting + '! 🎉');
    }
  } catch (err) {
    submitBtn.textContent = originalText;
    submitBtn.disabled = false;
    errorMsg.textContent = err.message || 'Something went wrong. Try again.';
  }
}

async function logout() {
  if (supabaseClient) await supabaseClient.auth.signOut();
  session = null;
  updateAuthUI(null);
  showToast('Logged out.');
}

function saveSettings() {
  const oKey = document.getElementById('key-openai').value.trim();
  const gKey = document.getElementById('key-gemini').value.trim();
  const dKey = document.getElementById('key-deepseek').value.trim();
  const bUrl = document.getElementById('backend-url').value.trim();

  state.keys.openai = oKey;
  state.keys.gemini = gKey;
  state.keys.deepseek = dKey;
  
  state.enabledCloud.openai = document.getElementById('enable-openai').checked;
  state.enabledCloud.gemini = document.getElementById('enable-gemini').checked;
  state.enabledCloud.deepseek = document.getElementById('enable-deepseek').checked;

  localStorage.setItem('key-openai', oKey);
  localStorage.setItem('key-gemini', gKey);
  localStorage.setItem('key-deepseek', dKey);
  localStorage.setItem('rm_backend_url', bUrl);
  
  localStorage.setItem('enable-openai', state.enabledCloud.openai);
  localStorage.setItem('enable-gemini', state.enabledCloud.gemini);
  localStorage.setItem('enable-deepseek', state.enabledCloud.deepseek);
  
  updateAvailableModels();
  
  showToast('Settings saved successfully!');
}
function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('mobile-overlay');
  if (sidebar && overlay) {
    sidebar.classList.toggle('open');
    if (sidebar.classList.contains('open')) {
      overlay.style.display = 'block';
      setTimeout(() => overlay.style.opacity = '1', 10);
    } else {
      overlay.style.opacity = '0';
      setTimeout(() => overlay.style.display = 'none', 300);
    }
  }
}

function toggleTheme() {
  const root = document.documentElement;
  const btn = document.getElementById('theme-toggle');
  
  root.classList.add('theme-transitioning');
  
  if (root.getAttribute('data-theme') === 'light') {
    root.removeAttribute('data-theme');
    localStorage.setItem('theme', 'dark');
    if (btn) btn.textContent = '☀️';
  } else {
    root.setAttribute('data-theme', 'light');
    localStorage.setItem('theme', 'light');
    if (btn) btn.textContent = '🌙';
  }
  
  setTimeout(() => {
    root.classList.remove('theme-transitioning');
  }, 400);
}


// ============================================
// FOLDERS
// ============================================
async function loadFolders() {
  try {
    const res = await fetch('/api/folders');
    state.folders = await res.json();
    renderFolderList();
    updateHomeDashboard();
  } catch (e) {
    console.error('Failed to load folders:', e);
  }
}

function renderFolderList() {
  const el = document.getElementById('folder-list');
  if (!state.folders.length) {
    el.innerHTML = '<p style="font-size:12px;color:var(--text-3);padding:8px 10px;">No folders yet</p>';
    return;
  }
  el.innerHTML = state.folders.map(f => `
    <button class="folder-item ${state.currentView === f.id ? 'active' : ''}" onclick="navigateTo('${f.id}')">
      <span class="folder-dot" style="background:${f.colour}"></span>
      <span class="folder-name">${escHtml(f.name)}</span>
      <div class="folder-actions">
        <span class="folder-action-btn" onclick="event.stopPropagation(); openEditFolderModal('${f.id}')" title="Rename">✎</span>
        <span class="folder-action-btn" onclick="event.stopPropagation(); deleteFolder('${f.id}')" title="Delete">✕</span>
      </div>
    </button>
  `).join('');
}

async function deleteFolder(folderId) {
  if (!confirm('Delete this folder? Papers inside will not be deleted.')) return;
  try {
    await fetch(`/api/folders/${folderId}`, { method: 'DELETE' });
    if (state.currentView === folderId) navigateTo('all');
    await loadFolders();
    showToast('Folder deleted', 'info');
  } catch (e) {
    showToast('Failed to delete folder', 'error');
  }
}

// ============================================
// FOLDER MODAL
// ============================================
function openNewFolderModal() {
  state.editingFolderId = null;
  state.selectedColour = '#6366f1';
  document.getElementById('folder-modal-title').textContent = 'New Folder';
  document.getElementById('folder-name-input').value = '';
  document.getElementById('save-folder-btn').textContent = 'Create Folder';
  updateColourSwatches();
  showModal('folder-modal');
  setTimeout(() => document.getElementById('folder-name-input').focus(), 100);
}

function openEditFolderModal(folderId) {
  const folder = state.folders.find(f => f.id === folderId);
  if (!folder) return;
  state.editingFolderId = folderId;
  state.selectedColour = folder.colour;
  document.getElementById('folder-modal-title').textContent = 'Rename Folder';
  document.getElementById('folder-name-input').value = folder.name;
  document.getElementById('save-folder-btn').textContent = 'Save Changes';
  updateColourSwatches();
  showModal('folder-modal');
  setTimeout(() => document.getElementById('folder-name-input').focus(), 100);
}

async function saveFolder() {
  const name = document.getElementById('folder-name-input').value.trim();
  if (!name) { showToast('Please enter a folder name', 'error'); return; }

  try {
    if (state.editingFolderId) {
      await fetch(`/api/folders/${state.editingFolderId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, colour: state.selectedColour }),
      });
      showToast('Folder updated', 'success');
    } else {
      await fetch('/api/folders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, colour: state.selectedColour }),
      });
      showToast('Folder created', 'success');
    }
    closeModal('folder-modal');
    await loadFolders();
  } catch (e) {
    showToast('Failed to save folder', 'error');
  }
}

document.getElementById('folder-name-input')?.addEventListener('keydown', e => {
  if (e.key === 'Enter') saveFolder();
});

function renderColourSwatches() {
  const container = document.getElementById('colour-swatches');
  container.innerHTML = FOLDER_COLOURS.map(c => `
    <button type="button" class="colour-swatch ${c === state.selectedColour ? 'selected' : ''}"
      style="background-color: ${c}; --swatch-color: ${c};"
      onclick="selectColour('${c}')"
      title="${c}">
    </button>
  `).join('');
}

function updateColourSwatches() {
  document.querySelectorAll('.colour-swatch').forEach(el => {
    el.classList.toggle('selected', el.style.background === state.selectedColour ||
      el.getAttribute('onclick')?.includes(state.selectedColour));
  });
  renderColourSwatches();
}

function selectColour(colour) {
  state.selectedColour = colour;
  renderColourSwatches();
}

// ============================================
// PAPERS
// ============================================
async function loadPapers() {
  try {
    let url = `/api/papers?sort=${state.sortBy}`;
    if (state.currentView === 'favourites') url += '&favourites=true';
    else if (state.currentView !== 'all' && state.currentView !== 'home') url += `&folder_id=${state.currentView}`;
    if (state.searchQuery) url += `&q=${encodeURIComponent(state.searchQuery)}`;

    const res = await fetch(url);
    state.papers = await res.json();
    
    if (state.currentView === 'favourites') {
      const compRes = await fetch('/api/comparisons/');
      const allComps = await compRes.json();
      state.favouriteComparisons = allComps.filter(c => c.is_favourite);
    } else {
      state.favouriteComparisons = [];
    }

    renderPapers();
    updateBadges();
    updateHomeDashboard();
  } catch (e) {
    console.error('Failed to load papers:', e);
  }
}

function renderPapers() {
  const grid = document.getElementById('papers-grid');
  const empty = document.getElementById('empty-state');

  if (!state.papers.length) {
    grid.innerHTML = '';
    grid.style.display = 'none';
    empty.style.display = 'flex';
    return;
  }
  grid.style.display = 'grid';
  empty.style.display = 'none';

  let html = state.papers.map((p, i) => {
    const ext = p.file_url ? p.file_url.substring(p.file_url.lastIndexOf('.')).toLowerCase() : '';
    let docType = 'PDF';
    if (ext === '.docx') docType = 'DOCX';
    else if (ext === '.pptx') docType = 'PPTX';
    else if (ext === '.csv') docType = 'CSV';
    else if (ext === '.xlsx' || ext === '.xls') docType = 'EXCEL';
    else if (ext === '.txt') docType = 'TXT';
    else if (ext === '.md') docType = 'MD';

    return `
    <div class="paper-card" onclick="openPaper('${p.id}')" style="animation-delay:${i * 0.04}s">
      
      <div class="card-checkbox-wrapper" onclick="event.stopPropagation();" style="position: absolute; top: 12px; left: 12px; z-index: 10;">
        <input type="checkbox" class="card-checkbox" ${state.selectedPaperIds.includes(p.id) ? 'checked' : ''} onchange="togglePaperSelection('${p.id}')" style="width: 16px; height: 16px; cursor: pointer;" />
      </div>

      <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 4px;">
        <div class="card-title" style="margin: 0; flex: 1;">${escHtml(p.title)}</div>
        
        <div style="display: flex; align-items: center; gap: 8px; flex-shrink: 0;">
          <span style="font-size: 10px; font-weight: 700; padding: 3px 6px; background: rgba(99,102,241,0.1); color: var(--primary); border: 1px solid rgba(99,102,241,0.2); border-radius: 4px; letter-spacing: 0.05em;">${docType}</span>
          <button class="card-fav-btn ${p.is_favourite ? 'starred' : ''}"
            onclick="event.stopPropagation(); toggleCardFavourite('${p.id}', ${p.is_favourite})"
            title="${p.is_favourite ? 'Remove from favourites' : 'Add to favourites'}"
            style="position: static; padding: 2px;">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="${p.is_favourite ? 'currentColor' : 'none'}">
              <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" stroke="currentColor" stroke-width="2"/>
            </svg>
          </button>
        </div>
      </div>

      <div class="card-authors" style="margin-bottom: 12px;">${escHtml(p.authors || 'Unknown Author')}</div>
      ${p.custom_header ? `<div class="card-description" style="margin-bottom: 12px;" title="${escHtml(p.custom_header)}">${escHtml(p.custom_header)}</div>` : ''}

      <div class="card-meta">
        <span class="card-date">${formatDate(p.created_at)}</span>
        <div class="card-badges" style="display: flex; gap: 6px; align-items: center;">
          ${p.summary_status === 'done' ? '<span class="badge badge-summary">✓ Summarised</span>' : ''}
          ${getFolderBadge(p.folder_id)}
        </div>
      </div>

      <div class="card-footer">
        <span class="card-pages">${p.page_count ? `${p.page_count} pages` : formatFileSize(p.file_size)}</span>
        <div class="card-actions" style="display: flex; gap: 6px;">
          <button class="card-action-btn" onclick="event.stopPropagation(); openEditPaperModal('${p.id}')">
            ✎ Edit
          </button>
          <button class="card-action-btn" onclick="event.stopPropagation(); openMoveModal('${p.id}')">
            📁 Move
          </button>
          <button class="card-action-btn card-action-danger-btn" onclick="event.stopPropagation(); deletePaperById('${p.id}', '${escHtml(p.title).replace(/'/g, "\\'")}')">
            🗑 Delete
          </button>
        </div>
      </div>
    </div>
    `;
  }).join('');

  if (state.currentView === 'favourites' && state.favouriteComparisons && state.favouriteComparisons.length > 0) {
    const startIndex = state.papers.length;
    html += state.favouriteComparisons.map((c, i) => renderComparisonCardHTML(c, startIndex + i)).join('');
  }

  grid.innerHTML = html;
}

function getFolderBadge(folderId) {
  if (!folderId) return '';
  const folder = state.folders.find(f => f.id === folderId);
  if (!folder) return '';
  return `
    <span class="badge badge-folder" style="display: inline-flex; align-items: center; gap: 4px;">
      <span style="width:6px;height:6px;border-radius:50%;background:${folder.colour};display:inline-block;"></span>
      ${escHtml(folder.name)}
    </span>`;
}

async function updateBadges() {
  try {
    const res = await fetch('/api/papers?sort=created_at');
    const all = await res.json();
    document.getElementById('badge-all').textContent = all.length;
  } catch {}
}

// ============================================
// NAVIGATION
// ============================================
function navigateTo(view) {
  state.currentView = view;
  state.searchQuery = '';
  document.getElementById('search-input').value = '';
  document.getElementById('search-clear').style.display = 'none';

  // Only show greeting on home page
  const greetingBar = document.getElementById('greeting-bar');
  if (greetingBar) {
    greetingBar.style.display = (view === 'home' && session) ? 'flex' : 'none';
  }

  // Close sidebar on mobile
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('mobile-overlay');
  if (sidebar && sidebar.classList.contains('open')) {
    sidebar.classList.remove('open');
    if (overlay) {
      overlay.style.opacity = '0';
      setTimeout(() => overlay.style.display = 'none', 300);
    }
  }

  // Update nav items
  const homeNav = document.getElementById('nav-home');
  if (homeNav) homeNav.classList.toggle('active', view === 'home');
  document.getElementById('nav-all').classList.toggle('active', view === 'all');
  document.getElementById('nav-favourites').classList.toggle('active', view === 'favourites');
  
  const globalNav = document.getElementById('nav-global-chat');
  if (globalNav) {
    globalNav.classList.toggle('active', view === 'global-chat');
  }

   const settingsNav = document.getElementById('nav-settings');
  if (settingsNav) {
    settingsNav.classList.toggle('active', view === 'settings');
  }

  const compNav = document.getElementById('nav-comparisons');
  if (compNav) {
    compNav.classList.toggle('active', view === 'comparisons');
  }

  const webRefNav = document.getElementById('nav-web-references');
  if (webRefNav) {
    webRefNav.classList.toggle('active', view === 'web-references');
  }

  const rewriteNav = document.getElementById('nav-rewrite-studio');
  if (rewriteNav) {
    rewriteNav.classList.toggle('active', view === 'rewrite-studio');
  }

  const synthNav = document.getElementById('nav-synthesis-studio');
  if (synthNav) {
    synthNav.classList.toggle('active', view === 'synthesis-studio');
  }

  if (view === 'home') {
    switchView('home');
    updateHomeDashboard();
  } else if (view === 'settings') {
    switchView('settings');
    document.getElementById('page-title').textContent = '⚙️ Settings';
    document.getElementById('key-openai').value = state.keys.openai || '';
    document.getElementById('key-gemini').value = state.keys.gemini || '';
    document.getElementById('key-deepseek').value = state.keys.deepseek || '';
    document.getElementById('backend-url').value = localStorage.getItem('rm_backend_url') || '';
    const eO = document.getElementById('enable-openai'); if(eO) eO.checked = state.enabledCloud.openai;
    const eG = document.getElementById('enable-gemini'); if(eG) eG.checked = state.enabledCloud.gemini;
    const eD = document.getElementById('enable-deepseek'); if(eD) eD.checked = state.enabledCloud.deepseek;
  } else if (view === 'comparisons') {
    switchView('comparisons');
    loadComparisons();
  } else if (view === 'web-references') {
    switchView('web-references');
    loadRecentSearches();
  } else if (view === 'rewrite-studio') {
    switchView('rewrite-studio');
    loadRewriteHistory();
  } else if (view === 'synthesis-studio') {
    switchView('synthesis-studio');
    loadSynthesisLibraryPapers();
  } else if (view === 'global-chat') {
    switchView('global-chat');
    document.getElementById('page-title').textContent = '✨ AI Assistant (Library)';
    renderFolderList();

    // Reset global chat first
    document.getElementById('global-chat-messages').innerHTML = `
      <div class="chat-welcome">
        <div class="chat-welcome-icon">✨</div>
        <p>Ask anything about all the papers in your library.</p>
      </div>`;
    
    // Fetch global chat history
    fetch('/api/ai/chat/global/history')
      .then(res => res.json())
      .then(history => {
        globalChatHistory = history;
        if (history.length > 0) {
          document.getElementById('global-chat-messages').innerHTML = '';
          history.forEach(msg => addGlobalChatBubble(msg.role, msg.content));
        }
      })
      .catch(err => console.warn("Could not load global chat history", err));
  } else {
    switchView('library');
    // Update page title
    let title = 'All Papers';
    if (view === 'favourites') title = '⭐ Favourites';
    else if (view !== 'all') {
      const folder = state.folders.find(f => f.id === view);
      title = folder ? folder.name : 'Papers';
    }
    document.getElementById('page-title').textContent = title;

    renderFolderList();
    loadPapers();
  }
}

function handleSearch(query) {
  state.searchQuery = query;
  document.getElementById('search-clear').style.display = query ? 'block' : 'none';
  clearTimeout(state.searchTimer);
  state.searchTimer = setTimeout(loadPapers, 250);
}

function clearSearch() {
  state.searchQuery = '';
  document.getElementById('search-input').value = '';
  document.getElementById('search-clear').style.display = 'none';
  loadPapers();
}

function handleSort(value) {
  state.sortBy = value;
  loadPapers();
}

// ============================================
// PAPER DETAIL
// ============================================
async function openPaper(paperId) {
  try {
    const res = await fetch(`/api/papers/${paperId}`);
    const paper = await res.json();
    state.currentPaper = paper;
    state.chatHistory = [];
    state.currentTab = 'summary';

    // Update detail view
    document.getElementById('detail-title').textContent = paper.title;
    document.getElementById('detail-meta').textContent =
      [paper.authors, paper.year, paper.journal].filter(Boolean).join(' · ');

    const descEl = document.getElementById('detail-description');
    if (paper.custom_header) {
      descEl.textContent = paper.custom_header;
      descEl.style.display = 'block';
    } else {
      descEl.style.display = 'none';
    }

    // Favourite button
    const favBtn = document.getElementById('fav-btn');
    favBtn.classList.toggle('starred', paper.is_favourite);

    // Load document preview
    loadDocument(paper);

    // Load summary
    renderSummary(paper);

    // Load notes
    document.getElementById('notes-editor').value = paper.notes || '';

    // Reset chat
    document.getElementById('chat-messages').innerHTML = `
      <div class="chat-welcome">
        <div class="chat-welcome-icon">✨</div>
        <p>Ask anything about this paper. The AI will only answer using the paper's content.</p>
      </div>`;

    // Fetch chat history
    fetch(`/api/ai/chat/${paperId}/history`)
      .then(res => res.json())
      .then(history => {
        state.chatHistory = history;
        if (history.length > 0) {
          document.getElementById('chat-messages').innerHTML = '';
          history.forEach(msg => addChatBubble(msg.role, msg.content));
        }
      })
      .catch(err => console.warn("Could not load chat history", err));

    // Switch to detail view
    switchView('detail');
    switchTab('summary');

    // Update AI badge
    updateAIBadge();
  } catch (e) {
    showToast('Failed to open paper', 'error');
  }
}

function loadDocument(paper) {
  const iframe = document.getElementById('pdf-iframe');
  const textReader = document.getElementById('text-reader');
  const slideViewer = document.getElementById('slide-viewer');
  const loading = document.getElementById('pdf-loading');
  const pageInfo = document.getElementById('pdf-page-info');
  const pdfControls = document.querySelector('.pdf-controls');

  loading.style.display = 'flex';
  iframe.style.display = 'none';
  textReader.style.display = 'none';
  slideViewer.style.display = 'none';

  const ext = paper.file_url ? paper.file_url.substring(paper.file_url.lastIndexOf('.')).toLowerCase() : '';

  if (ext === '.pdf') {
    if (pdfControls) pdfControls.style.display = 'flex';
    const filename = paper.file_url.split('/').pop();
    iframe.src = `/uploads/${filename}`;
    pageInfo.textContent = paper.page_count ? `${paper.page_count} pages` : 'Loading...';
    iframe.onload = () => {
      loading.style.display = 'none';
      iframe.style.display = 'block';
    };

  } else if (ext === '.pptx') {
    if (pdfControls) pdfControls.style.display = 'none';
    pageInfo.textContent = paper.page_count ? `${paper.page_count} slides` : '';

    // Fetch slide images from API
    fetch(`/api/papers/${paper.id}/slides`)
      .then(res => res.json())
      .then(slides => {
        loading.style.display = 'none';

        // Try to parse NEW format: "--- Slide N ---\ntext"
        const slideTexts = {};
        let hasNewFormat = false;
        if (paper.extracted_text && paper.extracted_text.includes('--- Slide ')) {
          hasNewFormat = true;
          const matches = paper.extracted_text.matchAll(/--- Slide (\d+) ---\n([\s\S]*?)(?=--- Slide \d+ ---|$)/g);
          for (const m of matches) {
            slideTexts[parseInt(m[1])] = m[2].trim();
          }
        }

        const hasImages = slides.some(s => s.images && s.images.length > 0);

        // If no images and no new-format text → fall back to plain text reader
        if (!hasImages && !hasNewFormat) {
          textReader.style.display = 'block';
          textReader.textContent = paper.extracted_text || 'No content extracted from this presentation.';
          slideViewer.style.display = 'none';
          return;
        }

        // Build merged slide list
        const allSlideNums = new Set([
          ...slides.map(s => s.slide_num),
          ...Object.keys(slideTexts).map(Number),
        ]);
        const sorted = [...allSlideNums].sort((a, b) => a - b);

        const slideMap = {};
        slides.forEach(s => { slideMap[s.slide_num] = s.images; });

        slideViewer.innerHTML = sorted.map(n => {
          const images = slideMap[n] || [];
          const text = slideTexts[n] || '';

          const imgHTML = images.map(src => `
            <div class="slide-image-wrap">
              <img src="${src}" alt="Slide ${n}" class="slide-img" loading="lazy"
                onclick="openSlideImage('${src}')" title="Click to enlarge" />
            </div>
          `).join('');

          // Only render card if there's something to show
          if (!imgHTML && !text) return '';

          return `
            <div class="slide-card">
              <div class="slide-num-label">Slide ${n}</div>
              ${imgHTML}
              ${text ? `<div class="slide-text-caption">${escHtml(text)}</div>` : ''}
            </div>
          `;
        }).filter(Boolean).join('');

        if (!slideViewer.innerHTML.trim()) {
          // All cards were empty — fall back to text reader
          textReader.style.display = 'block';
          textReader.textContent = paper.extracted_text || 'No content extracted.';
          slideViewer.style.display = 'none';
        } else {
          slideViewer.style.display = 'flex';
        }
      })
      .catch(err => {
        console.error('Could not load slides:', err);
        loading.style.display = 'none';
        textReader.style.display = 'block';
        textReader.textContent = paper.extracted_text || 'No content extracted.';
      });

  } else {
    if (pdfControls) pdfControls.style.display = 'none';
    loading.style.display = 'none';
    textReader.style.display = 'block';
    textReader.textContent = paper.extracted_text || 'No text extracted.';
    pageInfo.textContent = paper.page_count ? `${paper.page_count} pages` : '';
  }
}

function openSlideImage(src) {
  // Lightbox: open image in full screen overlay
  const overlay = document.createElement('div');
  overlay.className = 'lightbox-overlay';
  overlay.innerHTML = `
    <div class="lightbox-inner" onclick="event.stopPropagation()">
      <img src="${src}" class="lightbox-img" alt="Slide" />
      <button class="lightbox-close" onclick="this.closest('.lightbox-overlay').remove()">✕</button>
    </div>
  `;
  overlay.onclick = () => overlay.remove();
  document.body.appendChild(overlay);
}



function renderSummary(paper) {
  const generateBtn = document.getElementById('generate-btn');
  const summaryContent = document.getElementById('summary-content');
  const summaryGenerating = document.getElementById('summary-generating');

  if (paper.summary_status === 'done' && paper.summary) {
    generateBtn.textContent = '✨ Regenerate Smart Summary';
    generateBtn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 4v6h6M23 20v-6h-6" /><path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15" /></svg> Regenerate Smart Summary`;
    summaryContent.style.display = 'flex';
    summaryContent.innerHTML = buildSummaryHTML(paper);
  } else {
    generateBtn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg> Generate Smart Summary`;
    summaryContent.style.display = 'none';
    summaryContent.innerHTML = '';
  }
}
 
function buildSummaryHTML(paper) {
  const sections = [
    { icon: '📋', label: 'Smart Summary', value: paper.summary },
    { icon: '🎯', label: 'Research Aim', value: paper.research_aim },
    { icon: '🔬', label: 'Methodology', value: paper.methodology },
    { icon: '💡', label: 'Key Findings', value: paper.key_findings },
    { icon: '⚠️', label: 'Limitations', value: paper.limitations },
    { icon: '✅', label: 'Strengths', value: paper.strengths },
    { icon: '🔻', label: 'Weaknesses', value: paper.weaknesses },
    { icon: '🔮', label: 'Future Work', value: paper.future_work },
  ].filter(s => s.value);

  let keywords = [];
  try { keywords = JSON.parse(paper.keywords || '[]'); } catch {}

  const sectionsHTML = sections.map(s => `
    <div class="summary-section">
      <div class="summary-section-header">
        <span>${s.icon}</span>
        <span>${s.label}</span>
      </div>
      <div class="summary-section-body">${escHtml(s.value)}</div>
    </div>
  `).join('');

  const keywordsHTML = keywords.length ? `
    <div class="summary-section">
      <div class="summary-section-header"><span>🏷️</span><span>Keywords</span></div>
      <div class="keywords-wrap">
        ${keywords.map(k => `<span class="keyword-tag">${escHtml(k)}</span>`).join('')}
      </div>
    </div>
  ` : '';

  return sectionsHTML + keywordsHTML +
    `<button class="btn-regenerate" onclick="generateSummary()">↺ Regenerate</button>`;
}

// ============================================
// AI MODE (Fast / Smart)
// ============================================
function updateAvailableModels() {
  const btnOpenai = document.getElementById('mode-openai');
  const btnGemini = document.getElementById('mode-gemini');
  const btnDeepseek = document.getElementById('mode-deepseek');
  const cloudRow = document.getElementById('cloud-row');

  if (btnOpenai) btnOpenai.style.display = state.enabledCloud.openai ? 'inline-block' : 'none';
  if (btnGemini) btnGemini.style.display = state.enabledCloud.gemini ? 'inline-block' : 'none';
  if (btnDeepseek) btnDeepseek.style.display = state.enabledCloud.deepseek ? 'inline-block' : 'none';

  // Show/hide the entire Cloud row
  const anyCloud = state.enabledCloud.openai || state.enabledCloud.gemini || state.enabledCloud.deepseek;
  if (cloudRow) cloudRow.style.display = anyCloud ? 'flex' : 'none';

  // If the current mode is disabled, fallback to phi3
  if (state.aiMode === 'openai' && !state.enabledCloud.openai) setMode('phi3');
  if (state.aiMode === 'gemini' && !state.enabledCloud.gemini) setMode('phi3');
  if (state.aiMode === 'deepseek' && !state.enabledCloud.deepseek) setMode('phi3');
}

function setMode(mode) {
  state.aiMode = mode;
  localStorage.setItem('aiMode', mode);
  
  const models = ['phi3', 'fast', 'smart', 'openai', 'gemini', 'deepseek'];
  models.forEach(m => {
    const btn = document.getElementById(`mode-${m.replace('_', '-')}`);
    if (btn) btn.classList.toggle('active', mode === m);
  });

  let modelName = '';
  if (mode === 'phi3') modelName = state.phi3Model;
  else if (mode === 'fast') modelName = state.fastModel;
  else if (mode === 'smart') modelName = state.smartModel;
  else if (mode === 'openai') modelName = 'gpt-4o-mini';
  else if (mode === 'gemini') modelName = 'gemini-2.5-flash';
  else if (mode === 'deepseek') modelName = 'deepseek-chat';

  const nameEl = document.getElementById('mode-model-name');
  if (nameEl) nameEl.textContent = modelName;
  updateAIBadge();
}

async function generateSummary() {
  if (!state.currentPaper) return;

  const btn = document.getElementById('generate-btn');
  const summaryContent = document.getElementById('summary-content');
  const summaryGenerating = document.getElementById('summary-generating');

  btn.disabled = true;
  summaryContent.style.display = 'none';
  summaryGenerating.style.display = 'flex';

  try {
    const res = await fetch(`/api/ai/summarise/${state.currentPaper.id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: state.aiMode }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Summary failed');
    }

    const paper = await res.json();
    state.currentPaper = paper;
    renderSummary(paper);

    // Refresh card in library
    const idx = state.papers.findIndex(p => p.id === paper.id);
    if (idx !== -1) state.papers[idx] = paper;

    showToast('Summary generated!', 'success');
  } catch (e) {
    summaryGenerating.style.display = 'none';
    summaryContent.style.display = 'none';
    showToast(e.message || 'AI error — is Ollama running?', 'error');
  } finally {
    btn.disabled = false;
    summaryGenerating.style.display = 'none';
  }
}

// ============================================
// FAVOURITE
// ============================================
async function toggleFavourite() {
  if (!state.currentPaper) return;
  const newVal = !state.currentPaper.is_favourite;
  try {
    const res = await fetch(`/api/papers/${state.currentPaper.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_favourite: newVal }),
    });
    state.currentPaper = await res.json();
    document.getElementById('fav-btn').classList.toggle('starred', newVal);
    showToast(newVal ? 'Added to favourites' : 'Removed from favourites', 'success');
  } catch { showToast('Failed to update', 'error'); }
}

async function toggleCardFavourite(paperId, current) {
  try {
    const res = await fetch(`/api/papers/${paperId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_favourite: !current }),
    });
    const updated = await res.json();
    const idx = state.papers.findIndex(p => p.id === paperId);
    if (idx !== -1) state.papers[idx] = updated;
    renderPapers();
    showToast(updated.is_favourite ? '⭐ Added to favourites' : 'Removed from favourites', 'info');
  } catch { showToast('Failed to update', 'error'); }
}

// ============================================
// DELETE PAPER
// ============================================
async function deletePaper() {
  if (!state.currentPaper) return;
  await deletePaperById(state.currentPaper.id, state.currentPaper.title);
}

async function deletePaperById(paperId, title) {
  if (!confirm(`Delete "${title}"? This cannot be undone.`)) return;
  try {
    const res = await fetch(`/api/papers/${paperId}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Delete failed');
    showToast('Paper deleted', 'info');

    // If the paper currently open is the one we deleted, go back to library
    if (state.currentPaper && state.currentPaper.id === paperId) {
      backToLibrary();
    }

    await loadPapers();
  } catch (e) {
    showToast('Failed to delete paper', 'error');
  }
}

// ============================================
// MOVE TO FOLDER MODAL
// ============================================
function openMoveModal(paperId) {
  const paper = state.papers.find(p => p.id === paperId);
  if (!paper) return;
  state.movingPaperId = paperId;

  const list = document.getElementById('move-folder-list');
  list.innerHTML = [
    `<div class="move-folder-item" onclick="movePaper(null)">
      <span>📂</span> No Folder (remove from folder)
    </div>`,
    ...state.folders.map(f => `
      <div class="move-folder-item" onclick="movePaper('${f.id}')">
        <span style="width:10px;height:10px;border-radius:50%;background:${f.colour};display:inline-block;"></span>
        ${escHtml(f.name)}
      </div>
    `)
  ].join('');

  showModal('move-modal');
}

async function movePaper(folderId) {
  try {
    const res = await fetch(`/api/papers/${state.movingPaperId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder_id: folderId }),
    });
    const updated = await res.json();
    const idx = state.papers.findIndex(p => p.id === state.movingPaperId);
    if (idx !== -1) state.papers[idx] = updated;
    closeModal('move-modal');
    renderPapers();
    showToast(folderId ? 'Paper moved to folder' : 'Paper removed from folder', 'success');
  } catch { showToast('Failed to move paper', 'error'); }
}

// ============================================
// AI CHAT
// ============================================
async function sendChat() {
  const input = document.getElementById('chat-input');
  const message = input.value.trim();
  if (!message || !state.currentPaper) return;

  input.value = '';
  input.style.height = 'auto';
  document.getElementById('send-btn').disabled = true;

  // Add user bubble
  addChatBubble('user', message);
  state.chatHistory.push({ role: 'user', content: message });

  // Add assistant bubble (streaming)
  const assistantId = 'bubble-' + Date.now();
  addChatBubble('assistant', '', assistantId);
  let fullResponse = '';

  try {
    const res = await fetch(`/api/ai/chat/${state.currentPaper.id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message,
        history: state.chatHistory.slice(-10),
        mode: state.aiMode,
        api_keys: state.keys
      }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Chat failed');
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const text = decoder.decode(value);
      const lines = text.split('\n');

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6).trim();
          if (data === '[DONE]') break;
          try {
            const parsed = JSON.parse(data);
            if (parsed.content) {
              fullResponse += parsed.content;
              updateBubble(assistantId, fullResponse);
            }
            if (parsed.error) throw new Error(parsed.error);
          } catch {}
        }
      }
    }

    state.chatHistory.push({ role: 'assistant', content: fullResponse });
  } catch (e) {
    updateBubble(assistantId, `⚠️ ${e.message || 'AI error — is Ollama running?'}`);
  } finally {
    document.getElementById('send-btn').disabled = false;
  }
}

function addChatBubble(role, content, id = '') {
  const messages = document.getElementById('chat-messages');

  // Remove welcome message on first message
  const welcome = messages.querySelector('.chat-welcome');
  if (welcome) welcome.remove();

  const bubble = document.createElement('div');
  bubble.className = `chat-bubble ${role}`;
  if (id) bubble.id = id;

  bubble.innerHTML = `
    ${role === 'assistant' ? `<div class="bubble-header"><span>✨</span><span>ResearchMate AI</span></div>` : ''}
    <div class="bubble-content">${role === 'assistant' && !content ? `<div class="thinking-indicator"><span></span><span></span><span></span></div>` : escHtml(content)}</div>
  `;

  messages.appendChild(bubble);
  messages.scrollTop = messages.scrollHeight;
}

function updateBubble(id, content) {
  const el = document.getElementById(id);
  if (!el) return;
  const contentEl = el.querySelector('.bubble-content');
  if (contentEl) contentEl.textContent = content;
  const messages = document.getElementById('chat-messages');
  messages.scrollTop = messages.scrollHeight;
}

function sendQuickPrompt(prompt) {
  document.getElementById('chat-input').value = prompt;
  sendChat();
}

function handleChatKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendChat();
  }
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}

// ============================================
// NOTES
// ============================================
function handleNotesChange() {
  clearTimeout(state.notesTimer);
  const saved = document.getElementById('notes-saved');
  saved.classList.remove('visible');
  state.notesTimer = setTimeout(saveNotes, 1200);
}

async function saveNotes() {
  if (!state.currentPaper) return;
  const notes = document.getElementById('notes-editor').value;
  try {
    await fetch(`/api/papers/${state.currentPaper.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ notes }),
    });
    state.currentPaper.notes = notes;
    const saved = document.getElementById('notes-saved');
    saved.classList.add('visible');
    setTimeout(() => saved.classList.remove('visible'), 2000);
  } catch {}
}

// ============================================
// IMPORT / UPLOAD
// ============================================
function openImportModal() { showModal('import-modal'); }

function handleDragOver(e) {
  e.preventDefault();
  document.getElementById('drop-zone').classList.add('drag-over');
}

function handleDragLeave(e) {
  document.getElementById('drop-zone').classList.remove('drag-over');
}

function handleDrop(e) {
  e.preventDefault();
  document.getElementById('drop-zone').classList.remove('drag-over');
  const file = e.dataTransfer.files[0];
  if (file) uploadFile(file);
}

function handleFileSelect(e) {
  const file = e.target.files[0];
  if (file) uploadFile(file);
}

async function uploadFile(file) {
  const allowedExts = ['.pdf', '.docx', '.pptx', '.txt', '.md', '.csv', '.xlsx', '.xls'];
  const ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
  if (!allowedExts.includes(ext)) {
    showToast('Supported formats: PDF, DOCX, PPTX, CSV, Excel, TXT, MD', 'error');
    return;
  }

  const dropZone = document.getElementById('drop-zone');
  const progress = document.getElementById('upload-progress');
  const progressBar = document.getElementById('progress-bar');
  const uploadStatus = document.getElementById('upload-status');

  dropZone.style.display = 'none';
  progress.style.display = 'flex';
  uploadStatus.textContent = `Uploading "${file.name}"...`;

  // Animate progress bar
  let pct = 0;
  const interval = setInterval(() => {
    pct = Math.min(pct + 8, 85);
    progressBar.style.width = pct + '%';
  }, 200);

  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await fetch('/api/papers', { method: 'POST', body: formData });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Upload failed');
    }

    clearInterval(interval);
    progressBar.style.width = '100%';
    uploadStatus.textContent = '✓ Paper imported successfully!';

    const paper = await res.json();
    await loadPapers();

    setTimeout(() => {
      closeModal('import-modal');
      // Reset modal
      dropZone.style.display = 'flex';
      progress.style.display = 'none';
      progressBar.style.width = '0%';
      document.getElementById('file-input').value = '';

      showToast(`"${paper.title}" imported!`, 'success');
      openPaper(paper.id);
    }, 800);

  } catch (e) {
    clearInterval(interval);
    progress.style.display = 'none';
    dropZone.style.display = 'flex';
    showToast(e.message || 'Upload failed', 'error');
  }
}

// ============================================
// PDF ZOOM (visual only via CSS transform)
// ============================================
function zoomIn() {
  state.zoom = Math.min(state.zoom + 0.2, 2.5);
  applyZoom();
}

function zoomOut() {
  state.zoom = Math.max(state.zoom - 0.2, 0.5);
  applyZoom();
}

function applyZoom() {
  const iframe = document.getElementById('pdf-iframe');
  iframe.style.transform = `scale(${state.zoom})`;
  iframe.style.transformOrigin = 'top center';
}

// ============================================
// AI STATUS
// ============================================
async function checkAIStatus() {
  try {
    const res = await fetch('/api/ai/status');
    const data = await res.json();
    const dot = document.getElementById('status-dot');
    const text = document.getElementById('status-text');

    // Auto-enable cloud models if configured on backend
    if (data.openai_configured) state.enabledCloud.openai = true;
    if (data.gemini_configured) state.enabledCloud.gemini = true;
    if (data.deepseek_configured) state.enabledCloud.deepseek = true;

    // Update settings placeholders if keys are configured on backend
    const oInput = document.getElementById('key-openai');
    if (oInput && !state.keys.openai && data.openai_configured) {
      oInput.placeholder = '[Configured in .env]';
    }
    const gInput = document.getElementById('key-gemini');
    if (gInput && !state.keys.gemini && data.gemini_configured) {
      gInput.placeholder = '[Configured in .env]';
    }
    const dInput = document.getElementById('key-deepseek');
    if (dInput && !state.keys.deepseek && data.deepseek_configured) {
      dInput.placeholder = '[Configured in .env]';
    }

    // Synchronize toggles checked status in UI
    const eO = document.getElementById('enable-openai'); if(eO) eO.checked = state.enabledCloud.openai;
    const eG = document.getElementById('enable-gemini'); if(eG) eG.checked = state.enabledCloud.gemini;
    const eD = document.getElementById('enable-deepseek'); if(eD) eD.checked = state.enabledCloud.deepseek;

    updateAvailableModels();

    // Update model names in state
    if (data.fast_model) state.fastModel = data.fast_model;
    if (data.smart_model) state.smartModel = data.smart_model;

    // Update mode model name display
    document.getElementById('mode-model-name').textContent =
      state.aiMode === 'fast' ? state.fastModel : state.smartModel;

    // Dim Smart button if model not pulled
    if (!data.smart_available) {
      document.getElementById('mode-smart').title = `${state.smartModel} not found in Ollama`;
      document.getElementById('mode-smart').style.opacity = '0.5';
    }

    if (data.active_provider === 'openai') {
      dot.className = 'status-dot online';
      text.textContent = 'OpenAI connected';
    } else if (data.active_provider === 'ollama') {
      dot.className = 'status-dot online';
      const embedTip = data.embed_available ? ' + RAG' : '';
      text.textContent = `Ollama${embedTip}`;
    } else {
      dot.className = 'status-dot offline';
      text.textContent = 'No AI — start Ollama';
    }
  } catch {
    document.getElementById('status-dot').className = 'status-dot offline';
    document.getElementById('status-text').textContent = 'AI unavailable';
  }
}

function updateAIBadge() {
  const badge = document.getElementById('ai-badge');
  if (!badge) return;
  const dot = document.getElementById('status-dot');
  const modelName = state.aiMode === 'fast' ? state.fastModel : state.smartModel;
  const modeLabel = state.aiMode === 'fast' ? '⚡ Fast' : '🧠 Smart';
  if (dot && dot.classList.contains('online')) {
    badge.textContent = `${modeLabel} · ${modelName} · RAG enabled`;
  } else {
    badge.textContent = '⚠️ No AI — run: ollama serve';
  }
}

// ============================================
// VIEW SWITCHING
// ============================================
function switchView(view) {
  // All possible view IDs
  const allViews = ['view-home', 'view-library', 'view-detail', 'view-global-chat', 'view-settings', 'view-comparisons', 'view-comparison-active', 'view-web-references', 'view-rewrite-studio'];
  allViews.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });

  const target = document.getElementById('view-' + view);
  if (target) {
    if (view === 'home' || view === 'settings' || view === 'comparisons' || view === 'web-references') {
      target.style.display = 'block';
    } else {
      target.style.display = 'flex';
    }
  }
}

function backToLibrary() {
  if (state.currentView === 'home') {
    navigateTo('home');
  } else {
    navigateTo(state.currentView || 'all');
  }
}

// ============================================
// TAB SWITCHING
// ============================================
function switchTab(tab) {
  state.currentTab = tab;
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
  document.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');
  document.getElementById(`tab-${tab}`).style.display = 'flex';
  document.getElementById(`tab-${tab}`).style.flexDirection = 'column';
}

// ============================================
// MODALS
// ============================================
function showModal(id) { document.getElementById(id).style.display = 'flex'; }
function closeModal(id) { document.getElementById(id).style.display = 'none'; }
function closeModalOnOverlay(e, id) { if (e.target === e.currentTarget) closeModal(id); }

// ============================================
// TOAST NOTIFICATIONS
// ============================================
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;

  const icons = { success: '✓', error: '✕', info: 'ℹ' };
  toast.innerHTML = `<span>${icons[type] || 'ℹ'}</span><span>${escHtml(message)}</span>`;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(20px)';
    toast.style.transition = 'all 0.3s';
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

// ============================================
// UTILITIES
// ============================================
function escHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatDate(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}

function formatFileSize(bytes) {
  if (!bytes) return '';
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

// Keyboard shortcuts
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    ['import-modal', 'folder-modal', 'move-modal', 'edit-paper-modal'].forEach(closeModal);
  }
});

// ============================================
// EDIT PAPER DETAILS
// ============================================
let editingPaperId = null;

function openEditPaperModal(paperId) {
  if (!paperId) return;
  const paper = state.papers.find(p => p.id === paperId) || state.currentPaper;
  if (!paper) return;

  editingPaperId = paperId;
  document.getElementById('edit-paper-title').value = paper.title || '';
  document.getElementById('edit-paper-authors').value = paper.authors || '';
  document.getElementById('edit-paper-journal').value = paper.journal || '';
  document.getElementById('edit-paper-year').value = paper.year || '';
  document.getElementById('edit-paper-header').value = paper.custom_header || '';

  showModal('edit-paper-modal');
}

async function savePaperDetails() {
  if (!editingPaperId) return;

  const title = document.getElementById('edit-paper-title').value.trim();
  const authors = document.getElementById('edit-paper-authors').value.trim();
  const journal = document.getElementById('edit-paper-journal').value.trim();
  const yearVal = document.getElementById('edit-paper-year').value.trim();
  const customHeader = document.getElementById('edit-paper-header').value.trim();

  if (!title) {
    showToast('Title is required', 'error');
    return;
  }

  const year = yearVal ? parseInt(yearVal) : null;

  const saveBtn = document.getElementById('save-paper-btn');
  saveBtn.disabled = true;
  saveBtn.textContent = 'Saving...';

  try {
    const res = await fetch(`/api/papers/${editingPaperId}`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        title: title,
        authors: authors,
        journal: journal,
        year: year,
        custom_header: customHeader,
      }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Failed to save changes');
    }

    const updatedPaper = await res.json();

    // Update local state list
    const idx = state.papers.findIndex(p => p.id === editingPaperId);
    if (idx !== -1) {
      state.papers[idx] = updatedPaper;
    }
    if (state.currentPaper && state.currentPaper.id === editingPaperId) {
      state.currentPaper = updatedPaper;
      // Update detail view if open
      document.getElementById('detail-title').textContent = updatedPaper.title;
      document.getElementById('detail-meta').textContent =
        [updatedPaper.authors, updatedPaper.year, updatedPaper.journal].filter(Boolean).join(' · ');

      const descEl = document.getElementById('detail-description');
      if (updatedPaper.custom_header) {
        descEl.textContent = updatedPaper.custom_header;
        descEl.style.display = 'block';
      } else {
        descEl.style.display = 'none';
      }
    }

    renderPapers();
    closeModal('edit-paper-modal');
    showToast('Changes saved successfully');

  } catch (e) {
    showToast(e.message, 'error');
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = 'Save Changes';
  }
}

// ============================================
// GLOBAL LIBRARY AI CHAT
// ============================================
let globalChatHistory = [];

function addGlobalChatBubble(role, content, id = '') {
  const messages = document.getElementById('global-chat-messages');
  const welcome = messages.querySelector('.chat-welcome');
  if (welcome) welcome.remove();

  const bubble = document.createElement('div');
  bubble.className = `chat-bubble ${role}`;
  if (id) bubble.id = id;

  bubble.innerHTML = `
    ${role === 'assistant' ? `<div class="bubble-header"><span>✨</span><span>ResearchMate Library AI</span></div>` : ''}
    <div class="bubble-content">${role === 'assistant' && !content ? `<div class="thinking-indicator"><span></span><span></span><span></span></div>` : escHtml(content)}</div>
  `;

  messages.appendChild(bubble);
  messages.scrollTop = messages.scrollHeight;
}

function updateGlobalBubble(id, content, sources = null) {
  const el = document.getElementById(id);
  if (!el) return;
  const contentEl = el.querySelector('.bubble-content');
  if (contentEl) contentEl.textContent = content;

  if (sources && sources.length > 0) {
    let sourcesEl = el.querySelector('.source-papers');
    if (!sourcesEl) {
      sourcesEl = document.createElement('div');
      sourcesEl.className = 'source-papers';
      el.appendChild(sourcesEl);
    }
    sourcesEl.innerHTML = `
      <div class="source-title">Sources:</div>
      <div class="source-list">
        ${sources.map(s => `
          <span class="source-badge" onclick="openPaper('${s.id}')" title="Open Paper">
            📄 ${escHtml(s.title || 'Untitled Paper')}
          </span>
        `).join('')}
      </div>
    `;
  }

  const messages = document.getElementById('global-chat-messages');
  messages.scrollTop = messages.scrollHeight;
}

async function sendGlobalChatMessage() {
  const input = document.getElementById('global-chat-input');
  const message = input.value.trim();
  if (!message) return;

  input.value = '';
  addGlobalChatBubble('user', message);
  globalChatHistory.push({ role: 'user', content: message });

  const sendBtn = document.getElementById('global-send-btn');
  sendBtn.disabled = true;

  const assistantId = 'bubble-' + Date.now();
  addGlobalChatBubble('assistant', '', assistantId);
  let fullResponse = '';
  let sources = null;

  try {
    const res = await fetch('/api/ai/chat/global', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message,
        history: globalChatHistory.slice(-10),
        mode: state.aiMode,
        api_keys: state.keys
      }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Chat failed');
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const text = decoder.decode(value);
      const lines = text.split('\n');

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6).trim();
          if (data === '[DONE]') break;
          try {
            const parsed = JSON.parse(data);
            if (parsed.sources) {
              sources = parsed.sources;
              updateGlobalBubble(assistantId, fullResponse, sources);
            }
            if (parsed.content) {
              fullResponse += parsed.content;
              updateGlobalBubble(assistantId, fullResponse, sources);
            }
            if (parsed.error) throw new Error(parsed.error);
          } catch {}
        }
      }
    }

    globalChatHistory.push({ role: 'assistant', content: fullResponse });
  } catch (e) {
    updateGlobalBubble(assistantId, `⚠️ ${e.message || 'AI error — is Ollama running?'}`);
  } finally {
    sendBtn.disabled = false;
  }
}

function handleGlobalChatKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendGlobalChatMessage();
  }
}

// ============================================
// CLEAR & RENAME — GLOBAL CHAT
// ============================================
async function clearGlobalChatHistory() {
  if (!confirm('Clear all global chat history? This cannot be undone.')) return;
  try {
    await fetch('/api/ai/chat/global/history', { method: 'DELETE' });
    globalChatHistory = [];
    document.getElementById('global-chat-messages').innerHTML = `
      <div class="chat-welcome">
        <div class="chat-welcome-icon">📚</div>
        <p style="font-weight:500;font-size:15px;color:var(--text);">Chat history cleared.</p>
        <p style="font-size:13.5px;color:var(--text-2);max-width:500px;margin-top:4px;">Ask a new question to get started.</p>
      </div>`;
    showToast('Global chat history cleared', 'success');
  } catch {
    showToast('Failed to clear chat history', 'error');
  }
}

function startRenamingGlobalChat() {
  const display = document.getElementById('global-chat-title-display');
  const input = document.getElementById('global-chat-title-input');
  input.value = display.textContent;
  display.style.display = 'none';
  input.style.display = 'inline-block';
  input.focus();
  input.select();
}

function saveGlobalChatTitle() {
  const display = document.getElementById('global-chat-title-display');
  const input = document.getElementById('global-chat-title-input');
  const val = input.value.trim();
  if (val) display.textContent = val;
  input.style.display = 'none';
  display.style.display = 'inline';
}

// ============================================
// CLEAR — PAPER CHAT
// ============================================
async function clearPaperChatHistory() {
  if (!state.currentPaper) return;
  if (!confirm('Clear chat history for this paper? This cannot be undone.')) return;
  try {
    await fetch(`/api/ai/chat/${state.currentPaper.id}/history`, { method: 'DELETE' });
    state.chatHistory = [];
    document.getElementById('chat-messages').innerHTML = `
      <div class="chat-welcome">
        <div class="chat-welcome-icon">✨</div>
        <p>Chat history cleared. Ask anything about this paper.</p>
      </div>`;
    showToast('Chat history cleared', 'success');
  } catch {
    showToast('Failed to clear chat history', 'error');
  }
}

// ============================================
// CITATIONS & BIBLIOGRAPHY EXPORT
// ============================================
let activeCitations = {};
let activeBibliography = "";
let activeBibliographyFormat = "apa";

async function openCitationModal(paperId) {
  if (!paperId) return;
  try {
    const res = await fetch(`/api/papers/${paperId}/citation`);
    if (!res.ok) throw new Error("Failed to fetch citation");
    
    activeCitations = await res.json();
    
    document.getElementById('cite-text-apa').textContent = activeCitations.apa;
    document.getElementById('cite-text-harvard').textContent = activeCitations.harvard;
    document.getElementById('cite-text-bibtex').textContent = activeCitations.bibtex;
    
    switchCitationTab(null, 'apa');
    showModal('citation-modal');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

function switchCitationTab(event, format) {
  document.getElementById('cite-content-apa').style.display = 'none';
  document.getElementById('cite-content-harvard').style.display = 'none';
  document.getElementById('cite-content-bibtex').style.display = 'none';
  
  document.getElementById('cite-tab-apa').classList.remove('active');
  document.getElementById('cite-tab-harvard').classList.remove('active');
  document.getElementById('cite-tab-bibtex').classList.remove('active');
  
  if (format === 'apa') {
    document.getElementById('cite-content-apa').style.display = 'block';
    document.getElementById('cite-tab-apa').classList.add('active');
  } else if (format === 'harvard') {
    document.getElementById('cite-content-harvard').style.display = 'block';
    document.getElementById('cite-tab-harvard').classList.add('active');
  } else if (format === 'bibtex') {
    document.getElementById('cite-content-bibtex').style.display = 'block';
    document.getElementById('cite-tab-bibtex').classList.add('active');
  }
}

async function copyCitationText(format) {
  const text = activeCitations[format];
  if (!text) return;
  
  try {
    const cleanText = text.replace(/\*/g, '');
    await navigator.clipboard.writeText(cleanText);
    showToast('Citation copied to clipboard!', 'success');
  } catch {
    showToast('Failed to copy citation', 'error');
  }
}

async function exportActiveCitations() {
  const folderId = state.currentFolderId || "all";
  const folderName = state.currentFolderId ? 
    (state.folders.find(f => f.id === state.currentFolderId)?.name || "Folder") : "All Library";
  
  document.getElementById('bibliography-modal-title').textContent = `Export References: ${folderName}`;
  
  activeBibliographyFormat = "apa";
  await loadBibliographyContent(folderId, activeBibliographyFormat);
  
  document.getElementById('bib-tab-apa').classList.add('active');
  document.getElementById('bib-tab-harvard').classList.remove('active');
  document.getElementById('bib-tab-bibtex').classList.remove('active');
  
  showModal('bibliography-modal');
}

async function loadBibliographyContent(folderId, format) {
  const textEl = document.getElementById('bibliography-text');
  textEl.textContent = "Loading references list...";
  
  try {
    const res = await fetch(`/api/papers/export-citations?folder_id=${folderId}&format=${format}`);
    if (!res.ok) throw new Error("Failed to load bibliography");
    
    const data = await res.json();
    activeBibliography = data.citations || "No papers found in this view to generate citations.";
    textEl.textContent = activeBibliography.replace(/\*/g, ''); 
  } catch (err) {
    textEl.textContent = `Error: ${err.message}`;
    activeBibliography = "";
  }
}

async function switchBibliographyTab(event, format) {
  const folderId = state.currentFolderId || "all";
  activeBibliographyFormat = format;
  
  document.getElementById('bib-tab-apa').classList.remove('active');
  document.getElementById('bib-tab-harvard').classList.remove('active');
  document.getElementById('bib-tab-bibtex').classList.remove('active');
  
  if (event) {
    event.currentTarget.classList.add('active');
  } else {
    document.getElementById(`bib-tab-${format}`).classList.add('active');
  }
  
  await loadBibliographyContent(folderId, format);
}

async function copyBibliography() {
  if (!activeBibliography) return;
  try {
    const cleanText = activeBibliography.replace(/\*/g, '');
    await navigator.clipboard.writeText(cleanText);
    showToast('Bibliography copied to clipboard!', 'success');
  } catch {
    showToast('Failed to copy bibliography', 'error');
  }
}

function downloadBibliography() {
  if (!activeBibliography) return;
  
  const cleanText = activeBibliography.replace(/\*/g, '');
  const folderName = state.currentFolderId ? 
    (state.folders.find(f => f.id === state.currentFolderId)?.name || "Folder") : "All_Library";
  
  const blob = new Blob([cleanText], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${folderName.replace(/\s+/g, '_')}_references_${activeBibliographyFormat}.txt`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
  showToast('Bibliography downloaded!', 'success');
}

function updateHomeDashboard() {
  const totalEl = document.getElementById('home-stat-total');
  const foldersEl = document.getElementById('home-stat-folders');
  const favsEl = document.getElementById('home-stat-favourites');
  
  if (totalEl) totalEl.textContent = state.papers.length;
  if (foldersEl) foldersEl.textContent = state.folders.length;
  
  const favCount = state.papers.filter(p => p.is_favourite).length;
  if (favsEl) favsEl.textContent = favCount;
  
  const recentListEl = document.getElementById('home-recent-papers-list');
  if (recentListEl) {
    if (state.papers.length === 0) {
      recentListEl.innerHTML = '<div class="no-recent-papers">No papers available. Click "Import Paper" to get started.</div>';
      return;
    }
    
    const recent = [...state.papers]
      .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
      .slice(0, 4);
      
    recentListEl.innerHTML = recent.map(p => {
      const meta = [p.authors, p.year, p.journal].filter(Boolean).join(' · ');
      return `
        <div class="recent-paper-item" onclick="openPaper('${p.id}')">
          <div class="recent-paper-info">
            <div class="recent-paper-title">${escHtml(p.title)}</div>
            <div class="recent-paper-meta">${escHtml(meta || 'No metadata available')}</div>
          </div>
          <div class="recent-paper-arrow">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
          </div>
        </div>
      `;
    }).join('');
  }
}


// ============================================
// COMPARE PAPERS FLAGSHIP FEATURE
// ============================================

function togglePaperSelection(paperId) {
  const idx = state.selectedPaperIds.indexOf(paperId);
  if (idx === -1) {
    state.selectedPaperIds.push(paperId);
  } else {
    state.selectedPaperIds.splice(idx, 1);
  }
  updateCompareButtonState();
}

function updateCompareButtonState() {
  const count = state.selectedPaperIds.length;
  const btn = document.getElementById('compare-init-btn');
  const countEl = document.getElementById('selected-papers-count');
  if (btn && countEl) {
    countEl.textContent = count;
    if (count >= 2) {
      btn.style.display = 'inline-flex';
      btn.disabled = false;
      btn.style.opacity = '1';
      btn.style.cursor = 'pointer';
    } else if (count > 0) {
      btn.style.display = 'inline-flex';
      btn.disabled = true;
      btn.style.opacity = '0.5';
      btn.style.cursor = 'not-allowed';
    } else {
      btn.style.display = 'none';
    }
  }
}

function startComparisonSelection() {
  if (state.selectedPaperIds.length < 2) {
    showToast('Please select at least 2 papers to compare.', 'error');
    return;
  }
  const idA = state.selectedPaperIds[0];
  const idB = state.selectedPaperIds[1];
  
  switchView('comparison-active');
  document.getElementById('comparison-loading').style.display = 'flex';
  document.getElementById('comparison-result-area').style.display = 'none';
  document.getElementById('comparison-save-btn').style.display = 'inline-block';
  document.getElementById('comparison-save-btn').disabled = true;

  const paperA = state.papers.find(p => p.id === idA);
  const paperB = state.papers.find(p => p.id === idB);
  
  document.getElementById('comparison-display-title').textContent = 'AI Comparison Result';
  document.getElementById('comparison-display-meta').textContent = `Comparing "${paperA ? paperA.title : 'Paper A'}" vs "${paperB ? paperB.title : 'Paper B'}"`;

  const requestBody = {
    paper_a_id: idA,
    paper_b_id: idB,
    mode: state.aiMode,
    api_keys: state.keys
  };

  fetch('/api/comparisons/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(requestBody)
  })
  .then(res => {
    if (!res.ok) {
      return res.json().then(err => { throw new Error(err.detail || 'Failed to generate comparison') });
    }
    return res.json();
  })
  .then(comparison => {
    state.activeComparison = {
      paper_a_id: idA,
      paper_b_id: idB,
      paper_a_title: paperA ? paperA.title : 'Paper A',
      paper_b_title: paperB ? paperB.title : 'Paper B',
      comparison_data: comparison,
      title: comparison.title || `Comparison of ${paperA ? paperA.title : 'Paper A'} and ${paperB ? paperB.title : 'Paper B'}`
    };

    renderActiveComparison(state.activeComparison);
    
    // Automatically save the comparison to the database
    saveActiveComparison(true);
  })
  .catch(err => {
    showToast(err.message, 'error');
    goBackFromComparison();
  });
}

function renderActiveComparison(comp) {
  document.getElementById('comparison-loading').style.display = 'none';
  document.getElementById('comparison-result-area').style.display = 'block';

  document.getElementById('comparison-display-title').textContent = comp.title;
  document.getElementById('comp-th-paper-a').textContent = comp.paper_a_title;
  document.getElementById('comp-th-paper-b').textContent = comp.paper_b_title;

  const data = comp.comparison_data;

  // Table
  const tbody = document.getElementById('comparison-table-body');
  tbody.innerHTML = '';
  if (data.table) {
    Object.keys(data.table).forEach(category => {
      const row = data.table[category];
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td style="font-weight: 600; color: var(--text); background: var(--glass);">${escHtml(category)}</td>
        <td style="color: var(--text-2);">${escHtml(row.paper_a || 'N/A')}</td>
        <td style="color: var(--text-2);">${escHtml(row.paper_b || 'N/A')}</td>
      `;
      tbody.appendChild(tr);
    });
  }

  // Narrative
  document.getElementById('comparison-narrative-text').textContent = data.narrative || 'No narrative synthesis available.';

  // Evidence
  let confText = data.confidence;
  if (typeof confText === 'object' && confText !== null) {
    confText = Object.values(confText).filter(v => typeof v === 'string').join('\n\n').trim() || null;
  }
  document.getElementById('comparison-evidence-body').textContent = confText || 'No evidence critique available for this comparison.';

  // Agreement
  const listEl = document.getElementById('comparison-agreement-list');
  listEl.innerHTML = '';
  if (data.agreement && Array.isArray(data.agreement)) {
    data.agreement.forEach(item => {
      let icon = '✓';
      let badgeClass = 'agreement-tag-success';
      if (item.status === 'partial') {
        icon = '≈';
        badgeClass = 'agreement-tag-warning';
      } else if (item.status === 'contradiction') {
        icon = '✕';
        badgeClass = 'agreement-tag-danger';
      }

      const div = document.createElement('div');
      div.className = 'agreement-item';
      div.style.cssText = 'display: flex; flex-direction: column; gap: 4px; padding: 12px; border-radius: var(--radius); border: 1px solid var(--border); background: var(--glass);';
      div.innerHTML = `
        <div style="display: flex; align-items: center; gap: 8px;">
          <span class="agreement-tag ${badgeClass}" style="display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 20px; border-radius: 50%; font-size: 11px; font-weight: bold; color: white;">${icon}</span>
          <strong style="font-size: 13.5px; color: var(--text);">${escHtml(item.topic || 'Category')}</strong>
          <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600; opacity: 0.8;" class="${item.status === 'contradiction' ? 'text-danger' : item.status === 'partial' ? 'text-warning' : 'text-success'}">${item.status}</span>
        </div>
        <p style="margin: 4px 0 0 28px; font-size: 13px; color: var(--text-2); line-height: 1.45;">${escHtml(item.explanation || '')}</p>
      `;
      listEl.appendChild(div);
    });
  }

  const saveBtn = document.getElementById('comparison-save-btn');
  if (comp.id) {
    saveBtn.style.display = 'none';
  } else {
    saveBtn.style.display = 'inline-block';
    saveBtn.disabled = false;
  }
}

function saveActiveComparison(isAutoSave = false) {
  if (!state.activeComparison) return;
  
  // If it already has an ID, it means it's already saved
  if (state.activeComparison.id) return;

  const payload = {
    title: state.activeComparison.title,
    paper_a_id: state.activeComparison.paper_a_id,
    paper_b_id: state.activeComparison.paper_b_id,
    comparison_data: state.activeComparison.comparison_data
  };

  fetch('/api/comparisons/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
  .then(res => {
    if (!res.ok) throw new Error('Failed to save comparison');
    return res.json();
  })
  .then(saved => {
    state.activeComparison.id = saved.id;
    document.getElementById('comparison-save-btn').style.display = 'none';
    
    if (!isAutoSave) {
      showToast('Comparison saved successfully!', 'success');
    }
    
    state.selectedPaperIds = [];
    updateCompareButtonState();
    loadPapers();
  })
  .catch(err => {
    if (!isAutoSave) {
      showToast(err.message, 'error');
    }
  });
}

function goBackFromComparison() {
  state.activeComparison = null;
  if (state.currentView === 'comparisons') {
    navigateTo('comparisons');
  } else {
    navigateTo('all');
  }
}

function exportComparisonText() {
  if (!state.activeComparison) return;
  const comp = state.activeComparison;
  const data = comp.comparison_data;

  let text = `=========================================\n`;
  text += `RESEARCHMATE COMPARISON: ${comp.title.toUpperCase()}\n`;
  text += `=========================================\n`;
  text += `Compared Paper A: ${comp.paper_a_title}\n`;
  text += `Compared Paper B: ${comp.paper_b_title}\n\n`;

  text += `--- SIDE-BY-SIDE SUMMARY ---\n`;
  if (data.table) {
    Object.keys(data.table).forEach(category => {
      const row = data.table[category];
      text += `\n[${category.toUpperCase()}]\n`;
      text += `* ${comp.paper_a_title}: ${row.paper_a || 'N/A'}\n`;
      text += `* ${comp.paper_b_title}: ${row.paper_b || 'N/A'}\n`;
    });
  }

  text += `\n\n--- AI NARRATIVE SYNTHESIS ---\n`;
  text += `${data.narrative || 'N/A'}\n\n`;

  let exportConfText = data.confidence;
  if (typeof exportConfText === 'object' && exportConfText !== null) {
    exportConfText = Object.values(exportConfText).filter(v => typeof v === 'string').join('\n\n').trim() || null;
  }

  text += `--- EVIDENCE CONFIDENCE & CRITIQUE ---\n`;
  text += `${exportConfText || 'No evidence critique available for this comparison.'}\n\n`;

  text += `--- AGREEMENT & CONTRADICTION INDICATORS ---\n`;
  if (data.agreement && Array.isArray(data.agreement)) {
    data.agreement.forEach(item => {
      text += `* Topic: ${item.topic} | Status: ${item.status.toUpperCase()}\n`;
      text += `  Explanation: ${item.explanation}\n`;
    });
  }

  navigator.clipboard.writeText(text)
    .then(() => showToast('Comparison text copied to clipboard!', 'success'))
    .catch(() => {
      const blob = new Blob([text], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${comp.title.replace(/\s+/g, '_')}_comparison.txt`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      showToast('Comparison text downloaded as file.', 'success');
    });
}

async function openComparePicker(sort = 'created_at') {
  const overlay = document.getElementById('compare-picker-overlay');
  const list = document.getElementById('compare-picker-list');
  
  // Save currently selected papers if the modal is already open
  const selectedIds = Array.from(list.querySelectorAll('input[type="checkbox"]:checked')).map(cb => cb.value);
  
  overlay.style.display = 'flex';
  list.innerHTML = '<p style="color:var(--text-secondary);text-align:center;padding:24px;">Loading papers...</p>';

  // Reset button temporarily
  const btn = document.getElementById('compare-picker-btn');
  btn.disabled = true;
  btn.style.opacity = '0.5';

  try {
    // Fetch papers sorted by the requested parameter
    const res = await fetch(`/api/papers?sort=${sort}`);
    const allPapers = await res.json();

    if (!allPapers.length) {
      list.innerHTML = '<p style="color:var(--text-secondary);text-align:center;padding:24px;">No papers in your library yet. Upload some first!</p>';
      return;
    }

    list.innerHTML = allPapers.map(p => {
      const isChecked = selectedIds.includes(p.id) ? 'checked' : '';
      return `
      <label style="display:flex;align-items:center;gap:12px;padding:10px 14px;border:1.5px solid var(--border);border-radius:12px;cursor:pointer;transition:border-color 0.15s;">
        <input type="checkbox" value="${p.id}" data-title="${escHtml(p.title || 'Untitled')}" ${isChecked} onchange="updateComparePickerBtn()" style="accent-color:var(--primary);width:16px;height:16px;flex-shrink:0;" />
        <div style="min-width:0;">
          <div style="font-weight:600;font-size:13px;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${escHtml(p.title || 'Untitled')}</div>
          <div style="font-size:12px;color:var(--text-secondary);margin-top:2px;">${escHtml(p.authors || 'Unknown author')}</div>
        </div>
      </label>
    `}).join('');
    
    // Re-evaluate button state
    updateComparePickerBtn();
  } catch (e) {
    list.innerHTML = '<p style="color:#ef4444;text-align:center;padding:24px;">Failed to load papers. Try again.</p>';
  }
}

function closeComparePicker() {
  document.getElementById('compare-picker-overlay').style.display = 'none';
}

function updateComparePickerBtn() {
  const checked = document.querySelectorAll('#compare-picker-list input[type=checkbox]:checked');
  const btn = document.getElementById('compare-picker-btn');
  const enough = checked.length >= 2;
  btn.disabled = !enough;
  btn.style.opacity = enough ? '1' : '0.5';
}

async function runCompareFromPicker() {
  const checked = [...document.querySelectorAll('#compare-picker-list input[type=checkbox]:checked')];
  if (checked.length < 2) { showToast('Select at least 2 papers.', 'error'); return; }
  const ids = checked.map(c => c.value);
  closeComparePicker();

  // Fetch fresh paper objects for the selected IDs
  try {
    const res = await fetch('/api/papers?sort=created_at');
    const allPapers = await res.json();
    
    // Populate state.papers so startComparisonSelection can read titles
    state.papers = allPapers;
    state.selectedPaperIds = ids;
    
    // Start the comparison
    startComparisonSelection();
  } catch (e) {
    showToast('Failed to start comparison. Try again.', 'error');
  }
}

function loadComparisons() {
  const grid = document.getElementById('comparisons-grid');
  const empty = document.getElementById('comparisons-empty-state');

  grid.innerHTML = '';
  empty.style.display = 'none';

  fetch('/api/comparisons/')
    .then(res => res.json())
    .then(comparisons => {
      state.comparisons = comparisons;
      renderComparisonsList();
    })
    .catch(err => {
      showToast('Failed to load saved comparisons.', 'error');
    });
}

function renderComparisonCardHTML(c, i = 0) {
  return `
    <div class="paper-card" onclick="openSavedComparison('${c.id}')" style="animation-delay:${i * 0.04}s">
      <div class="card-icon" style="color: var(--primary);">VS</div>
      <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 4px;">
        <div class="card-title" style="margin: 0; flex: 1;">${escHtml(c.title)}</div>
        <div style="display: flex; align-items: center; gap: 8px; flex-shrink: 0;">
          <button class="card-fav-btn ${c.is_favourite ? 'starred' : ''}"
            onclick="event.stopPropagation(); toggleComparisonFavourite('${c.id}')"
            title="${c.is_favourite ? 'Remove from favourites' : 'Add to favourites'}"
            style="position: static; padding: 2px;">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="${c.is_favourite ? 'currentColor' : 'none'}">
              <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" stroke="currentColor" stroke-width="2"/>
            </svg>
          </button>
        </div>
      </div>
      <div class="card-authors" style="font-size:12px; margin-top:4px; white-space: normal; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical;">
        Comparing: <span style="font-weight: 500; color:var(--text-2);">${escHtml(c.paper_a_title)}</span> vs <span style="font-weight: 500; color:var(--text-2);">${escHtml(c.paper_b_title)}</span>
      </div>
      <div class="card-meta" style="margin-top:12px;">
        <span class="card-date">${formatDate(c.created_at)}</span>
      </div>
      <div class="card-footer" style="margin-top: 12px; justify-content: flex-end;">
        <div style="display:flex; gap:8px;">
          <button class="card-action-btn" onclick="event.stopPropagation(); renameComparison('${c.id}', '${escHtml(c.title).replace(/'/g, "\\'")}')">
            ✏️ Edit
          </button>
          <button class="card-action-btn card-action-danger-btn" onclick="event.stopPropagation(); deleteComparisonById('${c.id}', '${escHtml(c.title).replace(/'/g, "\\'")}')">
            🗑 Delete
          </button>
        </div>
      </div>
    </div>
  `;
}

function renderComparisonsList() {
  const grid = document.getElementById('comparisons-grid');
  const empty = document.getElementById('comparisons-empty-state');
  
  const query = (state.comparisonSearchQuery || '').toLowerCase().trim();
  const filtered = state.comparisons.filter(c => {
    return c.title.toLowerCase().includes(query) ||
           c.paper_a_title.toLowerCase().includes(query) ||
           c.paper_b_title.toLowerCase().includes(query);
  });

  if (filtered.length === 0) {
    grid.innerHTML = '';
    grid.style.display = 'none';
    empty.style.display = 'flex';
    return;
  }
  grid.style.display = 'grid';
  empty.style.display = 'none';

  grid.innerHTML = filtered.map((c, i) => renderComparisonCardHTML(c, i)).join('');
}

function openSavedComparison(id) {
  switchView('comparison-active');
  document.getElementById('comparison-loading').style.display = 'flex';
  document.getElementById('comparison-result-area').style.display = 'none';
  document.getElementById('comparison-save-btn').style.display = 'none';

  fetch(`/api/comparisons/${id}`)
    .then(res => {
      if (!res.ok) throw new Error('Comparison not found');
      return res.json();
    })
    .then(comp => {
      state.activeComparison = comp;
      renderActiveComparison(comp);
    })
    .catch(err => {
      showToast(err.message, 'error');
      navigateTo('comparisons');
    });
}

function deleteComparisonById(id, title) {
  if (!confirm(`Are you sure you want to delete the comparison "${title}"?`)) return;

  fetch(`/api/comparisons/${id}`, { method: 'DELETE' })
    .then(res => {
      if (!res.ok) throw new Error('Failed to delete comparison');
      state.comparisons = state.comparisons.filter(c => c.id !== id);
      if (state.activeComparison && state.activeComparison.id === id) {
        state.activeComparison = null;
        switchView('comparisons');
      }
      renderComparisonsList();
      showToast('Comparison deleted', 'success');
    })
    .catch(err => {
      showToast(err.message, 'error');
    });
}

function renameComparison(id, oldTitle) {
  const newTitle = prompt('Enter new comparison title:', oldTitle);
  if (!newTitle || newTitle.trim() === '' || newTitle === oldTitle) return;

  fetch(`/api/comparisons/${id}/rename`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: newTitle.trim() })
  })
  .then(res => res.json())
  .then(data => {
    if (data.status === 'success') {
      const idx = state.comparisons.findIndex(c => c.id === id);
      if (idx !== -1) {
        state.comparisons[idx].title = data.title;
        renderComparisonsList();
      }
      if (state.activeComparison && state.activeComparison.id === id) {
        state.activeComparison.title = data.title;
        document.getElementById('comparison-title').innerText = data.title;
      }
      showToast('Comparison renamed successfully', 'success');
    } else {
      showToast('Failed to rename comparison', 'error');
    }
  })
  .catch(err => {
    showToast('Failed to rename comparison', 'error');
  });
}

function toggleComparisonFavourite(id) {
  let comp = state.comparisons ? state.comparisons.find(c => c.id === id) : null;
  let favComp = state.favouriteComparisons ? state.favouriteComparisons.find(c => c.id === id) : null;
  
  if (!comp && !favComp) return;

  const targetComp = comp || favComp;
  const newState = !targetComp.is_favourite;
  
  if (comp) comp.is_favourite = newState;
  if (favComp) favComp.is_favourite = newState;

  if (state.currentView === 'favourites') {
    if (!newState && state.favouriteComparisons) {
      state.favouriteComparisons = state.favouriteComparisons.filter(c => c.id !== id);
    }
    renderPapers();
  }
  
  if (state.comparisons) {
    renderComparisonsList();
  }

  fetch(`/api/comparisons/${id}/favourite`, { method: 'PUT' })
    .then(res => res.json())
    .then(data => {
      if (data.status === 'success') {
        if (comp) comp.is_favourite = data.is_favourite;
        if (favComp) favComp.is_favourite = data.is_favourite;
        showToast(data.is_favourite ? '⭐ Added to favourites' : 'Removed from favourites', 'info');
      } else {
        if (comp) comp.is_favourite = !newState;
        if (favComp) favComp.is_favourite = !newState;
        if (state.currentView === 'favourites') loadPapers();
        else if (state.comparisons) renderComparisonsList();
        showToast('Failed to update favourite status', 'error');
      }
    })
    .catch(err => {
      if (comp) comp.is_favourite = !newState;
      if (favComp) favComp.is_favourite = !newState;
      if (state.currentView === 'favourites') loadPapers();
      else if (state.comparisons) renderComparisonsList();
      showToast('Failed to update favourite status', 'error');
    });
}

let renamingComparisonId = null;

function startRenamingComparison() {
  if (!state.activeComparison) return;
  renamingComparisonId = state.activeComparison.id;
  const titleDisplay = document.getElementById('comparison-display-title');
  const titleInput = document.getElementById('comparison-title-input');
  if (titleDisplay && titleInput) {
    titleInput.value = state.activeComparison.title;
    titleDisplay.style.display = 'none';
    titleInput.style.display = 'block';
    titleInput.focus();
    titleInput.select();
  }
}

function saveComparisonTitleChange() {
  if (!state.activeComparison) return;
  const titleInput = document.getElementById('comparison-title-input');
  const titleDisplay = document.getElementById('comparison-display-title');
  if (!titleInput || !titleDisplay) return;

  const newTitle = titleInput.value.trim();
  if (!newTitle) {
    titleDisplay.style.display = 'block';
    titleInput.style.display = 'none';
    return;
  }

  titleDisplay.style.display = 'block';
  titleInput.style.display = 'none';

  if (newTitle === state.activeComparison.title) return;

  state.activeComparison.title = newTitle;
  titleDisplay.textContent = newTitle;

  if (state.activeComparison.id) {
    fetch(`/api/comparisons/${state.activeComparison.id}/rename`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: newTitle })
    })
    .then(res => {
      if (!res.ok) throw new Error('Rename failed');
      showToast('Comparison renamed.', 'success');
    })
    .catch(err => {
      showToast(err.message, 'error');
    });
  }
}

function handleComparisonSearch(val) {
  state.comparisonSearchQuery = val;
  const clearBtn = document.getElementById('comparison-search-clear');
  if (clearBtn) {
    clearBtn.style.display = val ? 'block' : 'none';
  }
  renderComparisonsList();
}

function clearComparisonSearch() {
  document.getElementById('comparison-search-input').value = '';
  handleComparisonSearch('');
}

async function fetchWebReferences() {
  if (!state.currentPaper) return;
  
  const loading = document.getElementById('references-loading');
  const content = document.getElementById('references-content');
  const btn = document.getElementById('fetch-references-btn');
  
  loading.style.display = 'flex';
  content.style.display = 'none';
  if (btn) btn.disabled = true;

  try {
    const res = await fetch(`/api/papers/${state.currentPaper.id}/references`);
    if (!res.ok) throw new Error('Failed to fetch web references');
    
    const references = await res.json();
    loading.style.display = 'none';
    content.style.display = 'block';
    if (btn) btn.disabled = false;

    if (!references || references.length === 0) {
      content.innerHTML = `<div class="empty-state" style="padding: 40px; text-align: center; color: var(--text-2);">
        <div style="font-size: 32px; margin-bottom: 16px;">🔍</div>
        <p>No suitable external references found for this topic.</p>
      </div>`;
      return;
    }

    content.innerHTML = references.map((ref, i) => `
      <div class="reference-card" style="background: var(--bg-1); border: 1px solid var(--border); border-radius: 12px; padding: 20px; margin-bottom: 16px; animation: slideUp 0.3s ease-out ${i * 0.1}s both;">
        <h3 style="font-size: 16px; margin-bottom: 8px; color: var(--primary);">
          <a href="${ref.url}" target="_blank" style="color: inherit; text-decoration: none;">${escHtml(ref.title)}</a>
        </h3>
        <div style="font-size: 13px; color: var(--text-2); margin-bottom: 12px;">
          <span style="font-weight: 500;">${escHtml(ref.authors)}</span>
          ${ref.year ? ` • <span>${escHtml(ref.year)}</span>` : ''}
        </div>
        ${ref.abstract ? `<p style="font-size: 14px; color: var(--text); line-height: 1.5;">${escHtml(ref.abstract.substring(0, 300))}${ref.abstract.length > 300 ? '...' : ''}</p>` : ''}
        <div style="margin-top: 16px;">
          <a href="${ref.url}" target="_blank" class="btn-outline" style="font-size: 12px; padding: 6px 12px; text-decoration: none; display: inline-flex; align-items: center; gap: 6px;">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
            View Full Paper
          </a>
        </div>
      </div>
    `).join('');

  } catch (err) {
    loading.style.display = 'none';
    if (btn) btn.disabled = false;
    showToast(err.message, 'error');
  }
}

async function searchGlobalWebReferences() {
  const inputEl = document.getElementById('global-references-input');
  const query = inputEl.value.trim();
  if (!query) return;

  const loading = document.getElementById('global-references-loading');
  const content = document.getElementById('global-references-content');
  
  loading.style.display = 'flex';
  content.style.display = 'none';

  try {
    const res = await fetch(`/api/papers/references/search?q=${encodeURIComponent(query)}`);
    if (!res.ok) throw new Error('Failed to fetch web references');
    
    const references = await res.json();
    loading.style.display = 'none';
    content.style.display = 'block';
    
    loadRecentSearches();

    if (!references || references.length === 0) {
      content.innerHTML = `<div class="empty-state" style="padding: 40px; text-align: center; color: var(--text-2);">
        <div style="font-size: 32px; margin-bottom: 16px;">🔍</div>
        <p>No results found for "${escHtml(query)}".</p>
      </div>`;
      return;
    }

    content.innerHTML = references.map((ref, i) => `
      <div class="reference-card" style="background: var(--bg-1); border: 1px solid var(--border); border-radius: 12px; padding: 20px; margin-bottom: 16px; animation: slideUp 0.3s ease-out ${i * 0.1}s both;">
        <h3 style="font-size: 16px; margin-bottom: 8px; color: var(--primary);">
          <a href="${ref.url}" target="_blank" style="color: inherit; text-decoration: none;">${escHtml(ref.title)}</a>
        </h3>
        <div style="font-size: 13px; color: var(--text-2); margin-bottom: 12px;">
          <span style="font-weight: 500;">${escHtml(ref.authors)}</span>
          ${ref.year ? ` • <span>${escHtml(ref.year)}</span>` : ''}
        </div>
        ${ref.abstract ? `<p style="font-size: 14px; color: var(--text); line-height: 1.5;">${escHtml(ref.abstract.substring(0, 300))}${ref.abstract.length > 300 ? '...' : ''}</p>` : ''}
        <div style="margin-top: 16px;">
          <a href="${ref.url}" target="_blank" class="btn-outline" style="font-size: 12px; padding: 6px 12px; text-decoration: none; display: inline-flex; align-items: center; gap: 6px;">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
            View Full Paper
          </a>
        </div>
      </div>
    `).join('');

  } catch (err) {
    loading.style.display = 'none';
    showToast(err.message, 'error');
  }
}

async function loadRecentSearches() {
  if (!session) return;
  try {
    const res = await fetch('/api/papers/references/search/history');
    if (!res.ok) return;
    const history = await res.json();
    const container = document.getElementById('discover-recent-searches');
    if (!container) return;
    
    if (!history || history.length === 0) {
      container.innerHTML = '';
      return;
    }
    
    container.innerHTML = history.map(q => `
      <div onclick="searchFromHistory('${escHtml(q).replace(/'/g, "\\'")}')" style="cursor: pointer; padding: 6px 14px; background: var(--bg-1); border: 1px solid var(--border); border-radius: 16px; font-size: 13px; color: var(--text-2); display: flex; align-items: center; gap: 6px; transition: all 0.2s;" onmouseover="this.style.background='var(--surface)'; this.style.color='var(--text)';" onmouseout="this.style.background='var(--bg-1)'; this.style.color='var(--text-2)';">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
        ${escHtml(q)}
      </div>
    `).join('');
  } catch (err) {
    console.error('Failed to load recent searches', err);
  }
}

function searchFromHistory(query) {
  const inputEl = document.getElementById('global-references-input');
  if(inputEl) inputEl.value = query;
  searchGlobalWebReferences();
}

// ============================================
// REWRITE STUDIO
// ============================================
function setRewriteMode(mode) {
  state.rewriteMode = mode;
  document.querySelectorAll('.rewrite-mode-card').forEach(card => {
    let text = card.textContent.toLowerCase();
    let isActive = false;
    if (mode === 'simple') isActive = text.includes('simple');
    else if (mode === 'grammar') isActive = text.includes('grammar');
    else if (mode === 'british') isActive = text.includes('british');
    else if (mode === 'american') isActive = text.includes('american');
    else if (mode === 'tone') isActive = text.includes('tone');
    else isActive = text === mode;
    
    card.classList.toggle('active', isActive);
  });
  const toneContainer = document.getElementById('rewrite-tone-match-container');
  if (toneContainer) toneContainer.style.display = mode === 'tone' ? 'block' : 'none';
}

function updateRewriteStats() {
  const orig = document.getElementById('rewrite-original').value;
  const origWords = orig.trim() ? orig.trim().split(/\s+/).length : 0;
  document.getElementById('rewrite-orig-words').textContent = origWords + ' words';
  document.getElementById('rewrite-orig-chars').textContent = orig.length + ' characters';

  const res = document.getElementById('rewrite-result').value;
  const resWords = res.trim() ? res.trim().split(/\s+/).length : 0;
  document.getElementById('rewrite-res-words').textContent = resWords + ' words';
  document.getElementById('rewrite-res-chars').textContent = res.length + ' characters';
}

function clearRewriteOriginal() {
  document.getElementById('rewrite-original').value = '';
  document.getElementById('rewrite-result').value = '';
  updateRewriteStats();
}

async function copyRewriteResult() {
  const text = document.getElementById('rewrite-result').value;
  if (text) {
    await navigator.clipboard.writeText(text);
    showToast('Rewritten text copied!');
  }
}

async function generateRewrite() {
  const originalText = document.getElementById('rewrite-original').value.trim();
  if (!originalText) {
    showToast('Please enter some text to rewrite');
    return;
  }

  const mode = state.rewriteMode || 'natural';
  const toneExample = document.getElementById('rewrite-tone-input').value.trim();
  
  if (mode === 'tone' && !toneExample) {
    showToast('Please provide a tone example');
    return;
  }

  document.getElementById('rewrite-result').style.display = 'none';
  document.getElementById('rewrite-loading').style.display = 'flex';
  document.getElementById('btn-generate-rewrite').disabled = true;

  try {
    const res = await fetch('/api/ai/rewrite', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        original_text: originalText,
        mode: mode,
        tone_example: mode === 'tone' ? toneExample : null,
        user_id: 'default'
      })
    });

    if (!res.ok) throw new Error('Rewrite failed');
    const data = await res.json();
    
    document.getElementById('rewrite-result').value = data.rewritten_text;
  } catch (err) {
    console.error(err);
    showToast('Error generating rewrite.');
  } finally {
    document.getElementById('rewrite-loading').style.display = 'none';
    document.getElementById('rewrite-result').style.display = 'block';
    document.getElementById('btn-generate-rewrite').disabled = false;
    updateRewriteStats();
    loadRewriteHistory();
  }
}

let rewriteHistoryData = [];

async function loadRewriteHistory() {
  try {
    const res = await fetch('/api/ai/rewrite/history');
    if (!res.ok) throw new Error('Failed to load history');
    rewriteHistoryData = await res.json();
    
    const grid = document.getElementById('rewrite-history-grid');
    if (rewriteHistoryData.length === 0) {
      grid.innerHTML = '<p style="color: var(--text-3); font-size: 14px;">No saved rewrites yet. They will appear here automatically.</p>';
      return;
    }
    
    grid.innerHTML = rewriteHistoryData.map(item => `
      <div class="card" style="cursor: pointer;" onclick="loadSavedRewrite('${item.id}')">
        <div class="card-meta">
          <span class="card-date">${formatDate(item.created_at)}</span>
          <div class="card-badges">
            <span class="badge" style="background: var(--bg-2); color: var(--text-1);">${escHtml(item.mode)}</span>
          </div>
        </div>
        <p style="font-size: 13px; color: var(--text-2); margin-top: 8px; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;">
          ${escHtml(item.rewritten_text)}
        </p>
        <div style="display: flex; justify-content: flex-end; margin-top: 12px;">
          <button class="btn-icon btn-danger" onclick="event.stopPropagation(); deleteSavedRewrite('${item.id}')" title="Delete">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none"><polyline points="3 6 5 6 21 6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M19 6l-1 14H6L5 6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M10 11v6M14 11v6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M9 6V4h6v2" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
          </button>
        </div>
      </div>
    `).join('');
  } catch (err) {
    console.error(err);
  }
}

function loadSavedRewrite(id) {
  const item = rewriteHistoryData.find(r => r.id === id);
  if (!item) return;
  
  document.getElementById('rewrite-original').value = item.original_text;
  document.getElementById('rewrite-result').value = item.rewritten_text;
  setRewriteMode(item.mode);
  updateRewriteStats();
  
  // Scroll up to the editors
  document.getElementById('view-rewrite-studio').scrollTo({ top: 0, behavior: 'smooth' });
}

async function deleteSavedRewrite(id) {
  if (!confirm('Are you sure you want to delete this saved rewrite?')) return;
  try {
    const res = await fetch(`/api/ai/rewrite/${id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Failed to delete');
    loadRewriteHistory();
  } catch (err) {
    console.error(err);
    showToast('Failed to delete saved rewrite');
  }
}

// ============================================
// SYNTHESIS STUDIO
// ============================================

async function loadSynthesisLibraryPapers() {
  if (!session) return;
  try {
    const res = await fetch('/api/papers');
    if (!res.ok) throw new Error('Failed to fetch library');
    const papers = await res.json();
    
    const container = document.getElementById('synthesis-library-papers');
    if (!papers || papers.length === 0) {
      container.innerHTML = '<p style="color: var(--text-3); font-size: 13px;">No papers in your library yet.</p>';
      return;
    }
    
    container.innerHTML = papers.map(p => `
      <label style="display: flex; align-items: flex-start; gap: 8px; cursor: pointer; padding: 6px; border-radius: 6px; transition: background 0.2s;" onmouseover="this.style.background='var(--bg-1)'" onmouseout="this.style.background='transparent'">
        <input type="checkbox" class="synthesis-paper-checkbox" value="${p.id}" style="margin-top: 4px;" />
        <div style="flex: 1;">
          <div style="font-size: 13px; font-weight: 500; color: var(--text);">${escHtml(p.title)}</div>
          ${p.authors ? `<div style="font-size: 12px; color: var(--text-2);">${escHtml(p.authors)}</div>` : ''}
        </div>
      </label>
    `).join('');
  } catch (err) {
    console.error(err);
    document.getElementById('synthesis-library-papers').innerHTML = '<p style="color: #ef4444; font-size: 13px;">Failed to load library.</p>';
  }
}

async function generateSynthesis() {
  if (!session) return openAuthModal('login');
  
  // Collect selected papers (both from Synthesis view and global library selection)
  const checkboxes = document.querySelectorAll('.synthesis-paper-checkbox:checked');
  const checkedIds = Array.from(checkboxes).map(cb => cb.value);
  const paper_ids = [...new Set([...checkedIds, ...state.selectedPaperIds])];
  
  const manual_text = document.getElementById('synthesis-manual-text').value.trim();
  const style = document.getElementById('synthesis-format-style').value;
  const custom_prompt = document.getElementById('synthesis-custom-prompt').value.trim();
  
  if (paper_ids.length === 0 && !manual_text) {
    return showToast("Please select at least one paper or provide manual input.", "warning");
  }
  
  const btn = document.getElementById('btn-generate-synthesis');
  const loading = document.getElementById('synthesis-loading');
  const outputContainer = document.getElementById('synthesis-output-container');
  const resultDiv = document.getElementById('synthesis-result');
  
  btn.disabled = true;
  loading.style.display = 'flex';
  outputContainer.style.display = 'none';
  resultDiv.innerHTML = '';
  
  try {
    const res = await fetch('/api/synthesis/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: "Synthesized Document",
        paper_ids: paper_ids,
        manual_text: manual_text,
        style: style,
        custom_prompt: custom_prompt
      })
    });
    
    if (!res.ok) {
      const errData = await res.json();
      throw new Error(errData.detail || 'Failed to generate document');
    }
    
    const data = await res.json();
    resultDiv.innerHTML = marked.parse(data.content);
    
    // Update the title if available
    const titleEl = document.getElementById('synthesis-generated-title');
    if (titleEl && data.title) {
      titleEl.textContent = data.title;
    }
    
    outputContainer.style.display = 'block';
    
    // Scroll to result
    outputContainer.scrollIntoView({ behavior: 'smooth' });
    
  } catch (err) {
    console.error(err);
    showToast(err.message, "error");
  } finally {
    btn.disabled = false;
    loading.style.display = 'none';
  }
}

function copySynthesis() {
  const resultDiv = document.getElementById('synthesis-result');
  if (!resultDiv) return;
  const text = resultDiv.innerText;
  navigator.clipboard.writeText(text).then(() => {
    showToast("Copied to clipboard!", "success");
  }).catch(() => {
    showToast("Failed to copy", "error");
  });
}
