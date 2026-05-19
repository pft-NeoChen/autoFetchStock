/**
 * Floating tooltip for Volume Spike rows.
 *
 * The CSS-only `:hover` tooltip was unreliable when the spike list
 * scrolled inside an `overflow: hidden` ancestor — some browsers and
 * stacking contexts hid the absolutely/fixed positioned child. This
 * script renders a single overlay element attached to <body> so it
 * always escapes the panel.
 *
 * Each `.volume-spike-row` still ships a hidden `.vs-tooltip` child
 * containing the multi-line text built by `_build_spike_tooltip()`.
 * On mouseenter we copy that text into the singleton overlay and
 * position it near the cursor (clamped to the viewport).
 */
(function () {
    'use strict';

    var overlay = null;

    function ensureOverlay() {
        if (overlay && document.body.contains(overlay)) return overlay;
        overlay = document.createElement('div');
        overlay.id = 'vs-floating-tooltip';
        overlay.setAttribute('role', 'tooltip');
        document.body.appendChild(overlay);
        return overlay;
    }

    function findRow(target) {
        while (target && target !== document) {
            if (target.classList && target.classList.contains('volume-spike-row')) {
                return target;
            }
            target = target.parentNode;
        }
        return null;
    }

    function show(row, x, y) {
        var src = row.querySelector('.vs-tooltip');
        if (!src) return;
        var text = src.textContent || '';
        if (!text.trim()) return;

        var el = ensureOverlay();
        el.textContent = text;
        el.style.display = 'block';
        position(el, x, y);
    }

    function position(el, x, y) {
        // Render first to measure, then clamp to viewport.
        el.style.left = '0px';
        el.style.top = '0px';
        var rect = el.getBoundingClientRect();
        var w = rect.width;
        var h = rect.height;
        var pad = 12;
        var vw = window.innerWidth;
        var vh = window.innerHeight;

        // Prefer left of cursor; fall back to right if no room.
        var left = x - w - pad;
        if (left < pad) left = x + pad;
        if (left + w > vw - pad) left = vw - w - pad;
        if (left < pad) left = pad;

        var top = y - h / 2;
        if (top < pad) top = pad;
        if (top + h > vh - pad) top = vh - h - pad;

        el.style.left = left + 'px';
        el.style.top = top + 'px';
    }

    function hide() {
        if (overlay) overlay.style.display = 'none';
    }

    document.addEventListener('mouseover', function (ev) {
        var row = findRow(ev.target);
        if (!row) {
            hide();
            return;
        }
        show(row, ev.clientX, ev.clientY);
    });

    document.addEventListener('mousemove', function (ev) {
        var row = findRow(ev.target);
        if (!row) return;
        if (overlay && overlay.style.display === 'block') {
            position(overlay, ev.clientX, ev.clientY);
        }
    });

    document.addEventListener('mouseout', function (ev) {
        var related = ev.relatedTarget;
        if (related && findRow(related)) return;
        hide();
    });

    // Hide on scroll within the panel — tooltip becomes stale.
    document.addEventListener(
        'scroll',
        function (ev) {
            var t = ev.target;
            if (t && t.classList && (
                t.classList.contains('volume-spike-list') ||
                t.classList.contains('big-orders-list')
            )) {
                hide();
            }
        },
        true
    );
})();
