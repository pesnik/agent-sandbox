/**
 * clipboard-sync.js — Bidirectional clipboard bridge for noVNC.
 *
 * VNC → Host: when the VNC session puts something on the clipboard,
 *   write it to the browser (OS) clipboard via navigator.clipboard.writeText().
 *
 * Host → VNC: when the noVNC canvas gains focus, read the browser clipboard
 *   and send it to the VNC session. Also intercept Ctrl+V on the page level
 *   as a fallback.
 *
 * Loaded after ui.js so window.UI and the RFB instance are available.
 */

(function () {
  'use strict';

  function waitForRfb(cb) {
    if (window.UI && window.UI.rfb) {
      cb(window.UI.rfb);
    } else {
      setTimeout(() => waitForRfb(cb), 300);
    }
  }

  async function writeHostClipboard(text) {
    try {
      await navigator.clipboard.writeText(text);
    } catch (_) {
      // Clipboard permission denied — silently ignore, textarea still updated
    }
  }

  async function readHostClipboard() {
    try {
      return await navigator.clipboard.readText();
    } catch (_) {
      return null;
    }
  }

  waitForRfb((rfb) => {
    // ── VNC → Host ──────────────────────────────────────────────────────────
    // noVNC fires a "clipboard" event on the rfb object with e.detail.text
    rfb.addEventListener('clipboard', (e) => {
      const text = e.detail.text;
      if (text) writeHostClipboard(text);
    });

    // ── Host → VNC ──────────────────────────────────────────────────────────
    const canvas = document.getElementById('noVNC_canvas');

    // When the canvas gains focus, push the current host clipboard into VNC
    if (canvas) {
      canvas.addEventListener('focus', async () => {
        const text = await readHostClipboard();
        if (text !== null) rfb.clipboardPasteFrom(text);
      });
    }

    // Intercept Ctrl+V at the document level — fires before noVNC keyboard handler
    document.addEventListener('paste', async (e) => {
      // If the event target is the noVNC clipboard textarea, leave it alone
      if (e.target && e.target.id === 'noVNC_clipboard_text') return;
      const text = (e.clipboardData || window.clipboardData)?.getData('text');
      if (text) rfb.clipboardPasteFrom(text);
    });

    // Also handle Ctrl+V keydown for browsers that don't fire paste on canvas
    document.addEventListener('keydown', async (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'v') {
        if (e.target && e.target.id === 'noVNC_clipboard_text') return;
        const text = await readHostClipboard();
        if (text !== null) rfb.clipboardPasteFrom(text);
      }
    });
  });
})();
