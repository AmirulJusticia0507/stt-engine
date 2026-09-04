/* Helper auth + SweetAlert untuk semua halaman. */
const Auth = {
  get apiBase() { return localStorage.getItem('apiBase') || location.origin; },
  get token() { return localStorage.getItem('stt_token') || ''; },
  set token(v) { v ? localStorage.setItem('stt_token', v) : localStorage.removeItem('stt_token'); },
  get user() { return localStorage.getItem('stt_user') || ''; },
  set user(v) { v ? localStorage.setItem('stt_user', v) : localStorage.removeItem('stt_user'); },
  headers(extra = {}) {
    return { ...(this.token ? { Authorization: 'Bearer ' + this.token } : {}), ...extra };
  },
  requireAuth() {
    if (!this.token) { location.href = 'login.html'; return false; }
    return true;
  },
  logout() { this.token = ''; this.user = ''; location.href = 'login.html'; },
};

const UI = {
  ok(msg) { Swal.fire({ icon: 'success', title: 'Berhasil', text: msg, timer: 2000, showConfirmButton: false }); },
  err(msg) { Swal.fire({ icon: 'error', title: 'Gagal', text: msg }); },
  async confirm(msg) { const r = await Swal.fire({ icon: 'question', title: 'Yakin?', text: msg, showCancelButton: true, confirmButtonText: 'Ya', cancelButtonText: 'Batal' }); return r.isConfirmed; },
};
