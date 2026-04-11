/**
 * Drag-and-drop reordering for the favorites list.
 *
 * Flow:
 *  1. User drags a .favorite-item to a new position.
 *  2. On drop the DOM is visually reordered and the new stock-id array is
 *     stored in window._favoritesOrder.
 *  3. The hidden button #favorites-reorder-btn is clicked, which fires a
 *     Dash clientside callback that pushes the order into favorites-order-store.
 *  4. A Python callback persists the new order and updates app-state-store,
 *     so the next render reflects the saved order.
 *
 * Event delegation is used so listeners survive Dash re-renders that only
 * replace the *children* of #favorites-list, not the container itself.
 */
(function () {
    'use strict';

    var dragSrcEl = null;

    function handleDragStart(e) {
        var item = e.target.closest('.favorite-item[data-stock-id]');
        if (!item) return;
        dragSrcEl = item;
        item.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', item.getAttribute('data-stock-id'));
    }

    function handleDragOver(e) {
        var item = e.target.closest('.favorite-item[data-stock-id]');
        if (!item || item === dragSrcEl) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';

        // Show drop target indicator only on the hovered item
        var list = document.getElementById('favorites-list');
        if (list) {
            list.querySelectorAll('.favorite-item.drag-over').forEach(function (el) {
                if (el !== item) el.classList.remove('drag-over');
            });
        }
        item.classList.add('drag-over');
    }

    function handleDragLeave(e) {
        var item = e.target.closest('.favorite-item[data-stock-id]');
        // Only remove if the pointer truly left the item (not just entered a child)
        if (item && !item.contains(e.relatedTarget)) {
            item.classList.remove('drag-over');
        }
    }

    function handleDrop(e) {
        e.preventDefault();
        var target = e.target.closest('.favorite-item[data-stock-id]');
        if (!target || !dragSrcEl || target === dragSrcEl) return;

        var list = document.getElementById('favorites-list');
        if (!list) return;

        // Determine insert position: drop above or below target mid-point
        var rect = target.getBoundingClientRect();
        var midY = rect.top + rect.height / 2;
        if (e.clientY < midY) {
            list.insertBefore(dragSrcEl, target);
        } else {
            list.insertBefore(dragSrcEl, target.nextSibling);
        }

        // Collect new order from DOM
        var newOrder = Array.from(
            list.querySelectorAll('.favorite-item[data-stock-id]')
        ).map(function (el) {
            return el.getAttribute('data-stock-id');
        });

        // Notify Dash
        window._favoritesOrder = newOrder;
        var btn = document.getElementById('favorites-reorder-btn');
        if (btn) btn.click();
    }

    function handleDragEnd() {
        var list = document.getElementById('favorites-list');
        if (list) {
            list.querySelectorAll('.favorite-item.dragging, .favorite-item.drag-over')
                .forEach(function (el) {
                    el.classList.remove('dragging', 'drag-over');
                });
        }
        dragSrcEl = null;
    }

    function attachListeners(list) {
        list.addEventListener('dragstart',  handleDragStart);
        list.addEventListener('dragover',   handleDragOver);
        list.addEventListener('dragleave',  handleDragLeave);
        list.addEventListener('drop',       handleDrop);
        list.addEventListener('dragend',    handleDragEnd);
    }

    function init() {
        var list = document.getElementById('favorites-list');
        if (list) {
            attachListeners(list);
            return;
        }

        // #favorites-list may not exist yet if Dash hasn't rendered it.
        // Watch for it with a MutationObserver.
        var observer = new MutationObserver(function (mutations, obs) {
            var list = document.getElementById('favorites-list');
            if (list) {
                attachListeners(list);
                obs.disconnect();
            }
        });
        observer.observe(document.body, { childList: true, subtree: true });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
}());
