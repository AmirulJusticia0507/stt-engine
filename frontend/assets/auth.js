/* Helper auth + SweetAlert untuk semua halaman. */
const Auth = {
  get apiBase() { return localStorage.getItem('apiBase') || location.origin; },
  get token()   { return localStorage.getItem('stt_token') || ''; },
  set token(v)  { v ? localStorage.setItem('stt_token', v) : localStorage.removeItem('stt_token'); },
  get user()    { return localStorage.getItem('stt_user') || ''; },
  set user(v)   { v ? localStorage.setItem('stt_user', v) : localStorage.removeItem('stt_user'); },

  headers(extra = {}) {
    return { ...(this.token ? { Authorization: 'Bearer ' + this.token } : {}), ...extra };
  },
  requireAuth() {
    if (!this.token) { location.href = 'login.html'; return false; }
    return true;
  },
  logout() {
    this.token = '';
    this.user  = '';
    localStorage.removeItem('stt_me');
    localStorage.removeItem('stt_me_ts');
    location.href = 'login.html';
  },

  /**
   * Ambil data lengkap user dari /api/v1/me.
   * Di-cache ke localStorage selama `ttlMs` milidetik (default 60 detik).
   * Paksa refresh dengan force=true.
   */
  async fetchMe(force = false, ttlMs = 60_000) {
    const cached = localStorage.getItem('stt_me');
    const ts     = parseInt(localStorage.getItem('stt_me_ts') || '0', 10);
    if (!force && cached && (Date.now() - ts) < ttlMs) {
      try { return JSON.parse(cached); } catch {}
    }
    if (!this.token) return null;
    try {
      const r = await fetch(this.apiBase + '/api/v1/me', { headers: this.headers() });
      if (!r.ok) return null;
      const j = await r.json();
      localStorage.setItem('stt_me', JSON.stringify(j));
      localStorage.setItem('stt_me_ts', String(Date.now()));
      return j;
    } catch { return null; }
  },

  /** Invalidate cache /me (panggil setelah checkout sukses) */
  invalidateMe() {
    localStorage.removeItem('stt_me');
    localStorage.removeItem('stt_me_ts');
  },
};

const UI = {
  ok(msg)  { Swal.fire({ icon: 'success', title: 'Berhasil', text: msg, timer: 2000, showConfirmButton: false }); },
  err(msg) { Swal.fire({ icon: 'error',   title: 'Gagal',    text: msg }); },
  async confirm(msg) {
    const r = await Swal.fire({ icon: 'question', title: 'Yakin?', text: msg, showCancelButton: true, confirmButtonText: 'Ya', cancelButtonText: 'Batal' });
    return r.isConfirmed;
  },
};

/* ── Sidebar plan badge helper ──────────────────────────────────────────────
 * Dipanggil dari setiap halaman yang punya sidebar.
 * Isi #sidebarPlanBadge dan #sidebarQuotaBar jika ada.
 */
async function initSidebarPlan() {
  const me = await Auth.fetchMe();
  if (!me) return;

  // Admin indicator di nav
  if (me.is_admin) {
    document.querySelectorAll('.admin-only').forEach(el => el.classList.remove('hidden'));
  }

  // Avatar initial
  const initial = (me.username || 'U').charAt(0).toUpperCase();
  document.querySelectorAll('#avatarInitial').forEach(el => el.textContent = initial);
  document.querySelectorAll('#who').forEach(el => el.textContent = me.username);

  // Plan badge
  const badge = document.getElementById('sidebarPlanBadge');
  if (badge) {
    const PLAN_STYLE = {
      community: { label: 'Community', cls: 'bg-teal-600/20 text-teal-300' },
      free:      { label: 'Free',      cls: 'bg-slate-700 text-slate-300' },
      basic:     { label: 'Basic',     cls: 'bg-indigo-600/80 text-indigo-100' },
      pro:       { label: 'Pro',       cls: 'bg-gradient-to-r from-violet-600 to-purple-600 text-white' },
      payg:      { label: 'Pay-as-you-go', cls: 'bg-amber-500/20 text-amber-300' },
      enterprise:{ label: 'Enterprise',cls: 'bg-gradient-to-r from-rose-600 to-pink-600 text-white' },
    };
    if (me.is_admin) {
      badge.innerHTML = `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-500/20 text-amber-300">
        <svg class="w-3 h-3" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/></svg>
        Admin
      </span>`;
    } else {
      const s = PLAN_STYLE[me.plan] || PLAN_STYLE.free;
      badge.innerHTML = `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold ${s.cls}">${s.label}</span>`;
    }
    badge.classList.remove('hidden');
  }

  // Quota bar — admin: tampilkan ikon unlimited, user biasa: progress bar
  const bar = document.getElementById('sidebarQuotaBar');
  if (bar) {
    if (me.is_admin) {
      bar.innerHTML = `
        <div class="px-3 pb-3">
          <div class="flex items-center gap-1.5">
            <svg class="w-3.5 h-3.5 text-amber-400 shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z"/></svg>
            <span class="text-[10px] text-amber-400 font-semibold">Unlimited access</span>
          </div>
        </div>`;
      bar.classList.remove('hidden');
    } else if (me.quota_limit) {
      const used  = me.quota_used || 0;
      const pct   = Math.min(100, Math.round(used / me.quota_limit * 100));
      const color = pct >= 90 ? 'bg-rose-500' : pct >= 70 ? 'bg-amber-500' : 'bg-indigo-500';
      bar.innerHTML = `
        <div class="px-3 pb-3">
          <div class="flex items-center justify-between mb-1">
            <span class="text-[10px] text-slate-500">Kuota</span>
            <span class="text-[10px] text-slate-400 font-mono">${used}/${me.quota_limit}</span>
          </div>
          <div class="h-1 rounded-full bg-slate-800 overflow-hidden">
            <div class="${color} h-full rounded-full transition-all" style="width:${pct}%"></div>
          </div>
        </div>`;
      bar.classList.remove('hidden');
    }
  }

  return me;
}
