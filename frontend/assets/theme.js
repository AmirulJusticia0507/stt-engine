/* Helper Dark Mode Theme Controller for STT Engine */
(function () {
  function setupTailwind() {
    if (window.tailwind) {
      window.tailwind.config = window.tailwind.config || {};
      window.tailwind.config.darkMode = 'class';
    }
  }
  setupTailwind();

  // Dynamically inject theme CSS rules if not already present
  if (!document.getElementById('stt-theme-style')) {
    const style = document.createElement('style');
    style.id = 'stt-theme-style';
    style.textContent = `
      html {
        transition: background-color 0.25s ease, color 0.25s ease;
      }
      .bg-white, .bg-slate-50, aside, header, card, input, select, textarea, button, table, tr, td, th {
        transition: background-color 0.2s ease, border-color 0.2s ease, color 0.2s ease;
      }
      html.dark .swal2-popup {
        background-color: #0f172a !important;
        color: #f8fafc !important;
        border: 1px solid #1e293b !important;
        box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7) !important;
      }
      html.dark .swal2-title,
      html.dark .swal2-html-container,
      html.dark .swal2-content {
        color: #f8fafc !important;
      }
      html.dark .swal2-input,
      html.dark .swal2-select,
      html.dark .swal2-textarea {
        background-color: #1e293b !important;
        color: #f8fafc !important;
        border-color: #334155 !important;
      }
      html.dark .swal2-cancel {
        background-color: #334155 !important;
        color: #f8fafc !important;
      }
      html.dark ::-webkit-scrollbar {
        width: 8px;
        height: 8px;
      }
      html.dark ::-webkit-scrollbar-track {
        background: #0f172a;
      }
      html.dark ::-webkit-scrollbar-thumb {
        background: #334155;
        border-radius: 4px;
      }
      html.dark ::-webkit-scrollbar-thumb:hover {
        background: #475569;
      }
    `;
    (document.head || document.documentElement).appendChild(style);
  }

  const Theme = {
    KEY: 'stt_theme',
    get isDark() {
      const saved = localStorage.getItem(this.KEY);
      if (saved) return saved === 'dark';
      return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    },
    apply() {
      setupTailwind();
      const dark = this.isDark;
      const root = document.documentElement;
      if (dark) {
        root.classList.add('dark');
        if (document.body) document.body.classList.add('dark');
      } else {
        root.classList.remove('dark');
        if (document.body) document.body.classList.remove('dark');
      }
      this.updateButtons();
    },
    toggle() {
      const nextDark = !this.isDark;
      localStorage.setItem(this.KEY, nextDark ? 'dark' : 'light');
      this.apply();
    },
    updateButtons() {
      const dark = this.isDark;
      document.querySelectorAll('.theme-toggle-btn').forEach((btn) => {
        const iconSpan = btn.querySelector('.theme-icon');
        const textSpan = btn.querySelector('.theme-text');
        if (iconSpan) iconSpan.textContent = dark ? '☀️' : '🌙';
        if (textSpan) textSpan.textContent = dark ? 'Terang' : 'Gelap';
        btn.setAttribute('title', dark ? 'Ganti ke Mode Terang' : 'Ganti ke Mode Gelap');
      });
    },
    init() {
      this.apply();
      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => this.apply());
      } else {
        this.apply();
      }
    }
  };

  Theme.init();
  window.Theme = Theme;
})();
