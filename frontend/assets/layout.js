/**
 * layout.js — Inject sidebar & header partials, then wire up:
 *   - Active nav highlighting
 *   - Sidebar collapse
 *   - Mobile toggle
 *   - Page title
 *   - Health check
 *   - initSidebarPlan()
 *
 * Usage in every app page (after auth.js & theme.js):
 *   <script src="assets/layout.js"></script>
 *   <script>
 *     Layout.init({ page: 'dashboard', title: 'Dashboard', subtitle: 'Selamat datang' });
 *   </script>
 *
 * The host page must have:
 *   <div id="sidebar-container"></div>
 *   <div id="header-container"></div>
 */

const Layout = (() => {

  /* ── Helpers ─────────────────────────────────────────────────────────── */

  async function fetchPartial(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error('Cannot load partial: ' + url);
    return await r.text();
  }

  function setCollapsed(c) {
    const sb = document.getElementById('sidebar');
    if (!sb) return;
    sb.classList.toggle('w-64', !c);
    sb.classList.toggle('w-20', c);
    document.querySelectorAll('#sidebar .lbl').forEach(el => el.classList.toggle('hidden', c));
    // Status badge: hide model text when collapsed, keep dot
    const statusModel = document.getElementById('statusModel');
    if (statusModel) statusModel.classList.toggle('hidden', c);
    const statusLabel = document.getElementById('statusLabel');
    if (statusLabel) statusLabel.classList.toggle('hidden', c);
    // Sub-menu dokumen: tutup saat collapsed
    if (c) {
      const sub = document.getElementById('docSubMenu');
      if (sub) sub.style.maxHeight = '0';
      const chev = document.getElementById('docMenuChevron');
      if (chev) chev.style.transform = '';
    }
    localStorage.setItem('sb_collapsed', c ? '1' : '0');
  }

  function applyActiveNav(page) {
    document.querySelectorAll('#sidebar .nav-item').forEach(link => {
      const linkPage = link.dataset.page;
      const isActive = linkPage === page;
      if (isActive) {
        link.classList.add('bg-gradient-to-r', 'from-indigo-600/90', 'to-purple-600/80', 'text-white', 'shadow-md', 'shadow-indigo-900/40');
        link.classList.remove('text-slate-400', 'hover:text-white', 'hover:bg-slate-800/70');
      } else {
        link.classList.remove('bg-gradient-to-r', 'from-indigo-600/90', 'to-purple-600/80', 'text-white', 'shadow-md', 'shadow-indigo-900/40');
        link.classList.add('text-slate-400', 'hover:text-white', 'hover:bg-slate-800/70');
      }
    });
  }

  async function doHealthCheck() {
    try {
      const r = await fetch(Auth.apiBase + '/health');
      if (!r.ok) throw new Error();
      const j = await r.json();
      const model  = j.model  || '—';
      const device = j.device || '—';

      // Subtitle in header
      const sub = document.getElementById('pageSubtitle');
      if (sub && !sub.dataset.overridden) sub.textContent = model + ' · ' + device;

      // Status badge in sidebar
      const badge = document.getElementById('statusBadge');
      if (badge) {
        badge.classList.remove('hidden');
        badge.classList.add('flex');
      }
      const labelEl = document.getElementById('statusLabel');
      if (labelEl) labelEl.textContent = 'Online';
      const modelEl = document.getElementById('statusModel');
      if (modelEl) modelEl.textContent = model + ' · ' + device;

      // sysStatus row (model.html / dashboard.html)
      const statusEl = document.getElementById('sysStatus');
      if (statusEl) {
        statusEl.textContent = '● Online';
        statusEl.className   = 'text-xs font-semibold px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-500';
      }

      document.dispatchEvent(new CustomEvent('health', { detail: j }));
      return j;
    } catch {
      const sub = document.getElementById('pageSubtitle');
      if (sub && !sub.dataset.overridden) sub.textContent = 'Backend unreachable';

      const badge = document.getElementById('statusBadge');
      if (badge) {
        badge.classList.remove('hidden');
        badge.classList.add('flex');
        badge.className = badge.className
          .replace('bg-slate-800/60', 'bg-rose-500/10')
          .replace('border-slate-700/50', 'border-rose-500/20');
      }
      const labelEl = document.getElementById('statusLabel');
      if (labelEl) { labelEl.textContent = 'Offline'; labelEl.className = labelEl.className.replace('text-emerald-400', 'text-rose-400'); }
      const modelEl = document.getElementById('statusModel');
      if (modelEl) modelEl.textContent = 'Backend unreachable';

      const statusEl = document.getElementById('sysStatus');
      if (statusEl) {
        statusEl.textContent = '● Offline';
        statusEl.className   = 'text-xs font-semibold px-2 py-0.5 rounded-full bg-rose-500/10 text-rose-500';
      }
      return null;
    }
  }

  /* ── Public API ──────────────────────────────────────────────────────── */

  /**
   * @param {object} opts
   * @param {string}  opts.page       - matches data-page on nav links (e.g. 'dashboard')
   * @param {string}  opts.title      - page title shown in header
   * @param {string}  [opts.subtitle] - optional subtitle (if omitted, health info fills it)
   * @param {boolean} [opts.health]   - run health check (default: true)
   */
  async function init({ page = '', title = '', subtitle = '', health = true } = {}) {
    // Determine base path for partials (handles pages in subdirs)
    const base = document.currentScript?.src?.replace(/assets\/layout\.js.*/, '') ?? './';

    // Inject sidebar
    const sidebarContainer = document.getElementById('sidebar-container');
    if (sidebarContainer) {
      sidebarContainer.outerHTML = await fetchPartial(base + 'partials/sidebar.html');
    }

    // Inject header
    const headerContainer = document.getElementById('header-container');
    if (headerContainer) {
      headerContainer.outerHTML = await fetchPartial(base + 'partials/header.html');
    }

    // Set page title
    if (title) {
      const el = document.getElementById('pageTitle');
      if (el) el.textContent = title;
      document.title = title + ' — STT Engine';
    }

    // Set subtitle if provided
    if (subtitle) {
      const el = document.getElementById('pageSubtitle');
      if (el) { el.textContent = subtitle; el.dataset.overridden = '1'; }
    }

    // Active nav
    applyActiveNav(page);

    // Sidebar collapse state
    if (localStorage.getItem('sb_collapsed') === '1') setCollapsed(true);

    // Wire collapse button
    document.getElementById('collapseBtn')?.addEventListener('click', () => {
      const sb = document.getElementById('sidebar');
      setCollapsed(!sb?.classList.contains('w-20'));
    });

    // Wire mobile button
    document.getElementById('mobileBtn')?.addEventListener('click', () => {
      document.getElementById('sidebar')?.classList.toggle('hidden');
    });

    // Health check
    if (health) doHealthCheck();

    // Init sidebar plan (auth.js)
    if (typeof initSidebarPlan === 'function') {
      initSidebarPlan();
    }
  }

  return { init, setCollapsed, applyActiveNav };
})();

/* ── Logout confirmation (dipanggil dari header.html) ───────────────────── */
function confirmLogout() {
  const isDark = document.documentElement.classList.contains('dark');
  Swal.fire({
    icon: 'question',
    title: 'Yakin ingin keluar?',
    html: `<p class="text-sm text-slate-400">Sesi Anda akan diakhiri dan token akan dihapus.<br/>Anda perlu login kembali untuk mengakses dashboard.</p>`,
    showCancelButton: true,
    confirmButtonText: 'Ya, Keluar',
    cancelButtonText: 'Tidak, Tetap di Sini',
    confirmButtonColor: '#e11d48',
    cancelButtonColor: '#334155',
    reverseButtons: true,
    background: isDark ? '#0d1117' : '#fff',
    color: isDark ? '#f8fafc' : '#0f172a',
  }).then(result => {
    if (result.isConfirmed) {
      // Pakai PageTransition jika tersedia, fallback ke Auth.logout langsung
      if (typeof PageTransition !== 'undefined') {
        Auth.token = '';
        Auth.user  = '';
        localStorage.removeItem('stt_me');
        localStorage.removeItem('stt_me_ts');
        PageTransition.go('login.html');
      } else {
        Auth.logout();
      }
    }
  });
}
function toggleDocMenu() {
  const sub  = document.getElementById('docSubMenu');
  const chev = document.getElementById('docMenuChevron');
  const sb   = document.getElementById('sidebar');
  if (!sub) return;
  // Jangan buka saat sidebar collapsed
  if (sb && sb.classList.contains('w-20')) {
    Layout.setCollapsed(false);
    setTimeout(() => _openDocMenu(sub, chev), 260);
    return;
  }
  const isOpen = sub.style.maxHeight && sub.style.maxHeight !== '0px' && sub.style.maxHeight !== '0';
  if (isOpen) {
    sub.style.maxHeight = '0';
    if (chev) chev.style.transform = '';
    localStorage.setItem('docMenuOpen', '0');
  } else {
    _openDocMenu(sub, chev);
  }
}

function _openDocMenu(sub, chev) {
  if (!sub) return;
  sub.style.maxHeight = sub.scrollHeight + 'px';
  if (chev) chev.style.transform = 'rotate(180deg)';
  localStorage.setItem('docMenuOpen', '1');
}

/* Restore state setelah inject */
document.addEventListener('DOMContentLoaded', () => {
  if (localStorage.getItem('docMenuOpen') === '1') {
    const sub  = document.getElementById('docSubMenu');
    const chev = document.getElementById('docMenuChevron');
    _openDocMenu(sub, chev);
  }
});
