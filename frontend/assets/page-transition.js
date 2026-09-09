/**
 * page-transition.js
 * Overlay spinner saat navigasi antar halaman.
 *
 * - Page load   : overlay muncul seketika, lalu fade-out setelah DOM siap
 * - Navigasi    : overlay fade-in → tunggu selesai → redirect
 * - Logout      : PageTransition.go('login.html') dari confirmLogout
 */

const PageTransition = (() => {

  const DURATION_OUT = 280; // ms fade-out saat halaman selesai load
  const DURATION_IN  = 220; // ms fade-in sebelum navigasi

  /* ── Inject overlay HTML + style (sekali saja) ─────────────────────── */
  function inject() {
    if (document.getElementById('pt-overlay')) return;

    const style = document.createElement('style');
    style.textContent = `
      #pt-overlay {
        position: fixed; inset: 0; z-index: 9999;
        background: #080c14;
        display: flex; flex-direction: column;
        align-items: center; justify-content: center; gap: 20px;
        transition: opacity ${DURATION_OUT}ms ease;
        pointer-events: none;
      }
      #pt-overlay.visible   { opacity: 1;  pointer-events: all; }
      #pt-overlay.hidden-out { opacity: 0; pointer-events: none; }

      /* Spinner ring */
      .pt-ring {
        width: 44px; height: 44px;
        border-radius: 50%;
        border: 3px solid rgba(99,102,241,0.15);
        border-top-color: #6366f1;
        animation: pt-spin 0.75s linear infinite;
      }
      @keyframes pt-spin { to { transform: rotate(360deg); } }

      /* Brand text under spinner */
      .pt-brand {
        font-family: 'Inter', sans-serif;
        font-size: 11pt; font-weight: 700;
        background: linear-gradient(90deg, #818cf8, #c084fc, #f472b6);
        -webkit-background-clip: text; background-clip: text;
        -webkit-text-fill-color: transparent;
        opacity: 0.75;
        animation: pt-pulse 1.4s ease-in-out infinite;
      }
      @keyframes pt-pulse { 0%,100%{opacity:.5} 50%{opacity:1} }

      /* Dots */
      .pt-dots { display: flex; gap: 6px; }
      .pt-dots span {
        width: 6px; height: 6px; border-radius: 50%;
        background: #6366f1; opacity: 0.3;
        animation: pt-bounce 1.2s ease-in-out infinite;
      }
      .pt-dots span:nth-child(2) { animation-delay: .2s; background: #a855f7; }
      .pt-dots span:nth-child(3) { animation-delay: .4s; background: #ec4899; }
      @keyframes pt-bounce { 0%,80%,100%{transform:scale(.7);opacity:.3} 40%{transform:scale(1);opacity:1} }
    `;

    const overlay = document.createElement('div');
    overlay.id = 'pt-overlay';
    overlay.className = 'visible';
    overlay.innerHTML = `
      <div class="pt-ring"></div>
      <span class="pt-brand">STT Engine</span>
      <div class="pt-dots"><span></span><span></span><span></span></div>
    `;

    document.head.appendChild(style);
    document.body.insertBefore(overlay, document.body.firstChild);
  }

  /* ── Fade OUT (halaman selesai load, sembunyikan overlay) ───────────── */
  function fadeOut() {
    const el = document.getElementById('pt-overlay');
    if (!el) return;
    el.style.transitionDuration = DURATION_OUT + 'ms';
    el.classList.remove('visible');
    el.classList.add('hidden-out');
    setTimeout(() => el.remove(), DURATION_OUT + 50);
  }

  /* ── Fade IN + navigate (sebelum pindah halaman) ────────────────────── */
  function go(href) {
    // Kalau overlay sudah ada (belum selesai fade-out), langsung navigate
    const existing = document.getElementById('pt-overlay');
    if (existing) {
      existing.style.opacity = '1';
      existing.style.pointerEvents = 'all';
      setTimeout(() => { location.href = href; }, 50);
      return;
    }

    // Buat overlay baru
    inject();
    const el = document.getElementById('pt-overlay');
    // Mulai dari transparan → tampak
    el.style.transition = 'none';
    el.style.opacity = '0';
    el.classList.add('visible');
    // Force reflow
    el.offsetHeight; // eslint-disable-line no-unused-expressions
    el.style.transition = `opacity ${DURATION_IN}ms ease`;
    el.style.opacity = '1';
    setTimeout(() => { location.href = href; }, DURATION_IN + 20);
  }

  /* ── Intercept semua link <a> internal ──────────────────────────────── */
  function interceptLinks() {
    document.addEventListener('click', e => {
      const link = e.target.closest('a[href]');
      if (!link) return;

      const href = link.getAttribute('href');
      // Skip: eksternal, anchor, javascript:, target=_blank, download
      if (
        !href ||
        href.startsWith('http') ||
        href.startsWith('//') ||
        href.startsWith('#') ||
        href.startsWith('javascript') ||
        link.target === '_blank' ||
        link.hasAttribute('download') ||
        e.ctrlKey || e.metaKey || e.shiftKey
      ) return;

      e.preventDefault();
      go(href);
    }, true);
  }

  /* ── Public init ────────────────────────────────────────────────────── */
  function init() {
    inject();

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => setTimeout(fadeOut, 80));
    } else {
      setTimeout(fadeOut, 80);
    }

    interceptLinks();
  }

  return { init, go, fadeOut };
})();

// Auto-init
PageTransition.init();
