(function () {
    'use strict';

    var sidebar = document.getElementById('crpSidebar');
    var overlay = document.getElementById('saheSidebarOverlay');
    var command = document.getElementById('saheCommand');
    var commandInput = document.getElementById('saheCommandInput');
    var commandResults = document.getElementById('saheCommandResults');
    var notificationPanel = document.getElementById('saheNotifications');
    var userPanel = document.getElementById('saheUserMenu');
    var tour = document.getElementById('saheTour');

    function setExpanded(button, expanded) {
        if (button) button.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    }

    function closePopovers(except) {
        [notificationPanel, userPanel].forEach(function (panel) {
            if (panel && panel !== except) panel.classList.remove('is-open');
        });
        if (except !== notificationPanel) setExpanded(document.getElementById('saheNotificationButton'), false);
        if (except !== userPanel) setExpanded(document.getElementById('saheUserButton'), false);
    }

    function togglePopover(panel, button) {
        if (!panel) return;
        var opening = !panel.classList.contains('is-open');
        closePopovers(panel);
        panel.classList.toggle('is-open', opening);
        setExpanded(button, opening);
    }

    function openSidebar() {
        if (sidebar) sidebar.classList.add('show');
        if (overlay) overlay.classList.add('is-open');
        document.body.style.overflow = 'hidden';
    }

    function closeSidebar() {
        if (sidebar) sidebar.classList.remove('show');
        if (overlay) overlay.classList.remove('is-open');
        document.body.style.overflow = '';
    }

    window.toggleSidebar = function () {
        if (window.matchMedia('(max-width: 991.98px)').matches) {
            if (sidebar && sidebar.classList.contains('show')) closeSidebar();
            else openSidebar();
            return;
        }
        document.body.classList.toggle('sahe-sidebar-collapsed');
        document.querySelectorAll('.sahe-sidebar-toggle').forEach(function (button) {
            var collapsed = document.body.classList.contains('sahe-sidebar-collapsed');
            button.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
            button.setAttribute('aria-label', collapsed ? 'Expand navigation' : 'Collapse navigation');
            button.innerHTML = '<i class="bi bi-' + (collapsed ? 'layout-sidebar' : 'layout-sidebar-inset') + '"></i>';
        });
    };

    var searchable = Array.prototype.map.call(document.querySelectorAll('.crp-sidebar-item[href]'), function (link) {
        return { label: link.textContent.trim(), href: link.href, icon: (link.querySelector('i') || {}).className || 'bi bi-arrow-right' };
    }).filter(function (item, index, all) {
        return item.label && all.findIndex(function (candidate) { return candidate.href === item.href && candidate.label === item.label; }) === index;
    });

    function renderResults(query) {
        if (!commandResults) return;
        var normalized = (query || '').trim().toLowerCase();
        var matches = searchable.filter(function (item) { return !normalized || item.label.toLowerCase().indexOf(normalized) !== -1; }).slice(0, 12);
        commandResults.innerHTML = '';
        if (!matches.length) {
            commandResults.innerHTML = '<div class="sahe-command-empty">No student portal page matches that search.</div>';
            return;
        }
        matches.forEach(function (item, index) {
            var link = document.createElement('a');
            link.className = 'sahe-command-result' + (index === 0 ? ' is-active' : '');
            link.href = item.href;
            var icon = document.createElement('i');
            icon.className = item.icon;
            var label = document.createElement('span');
            label.textContent = item.label;
            link.appendChild(icon);
            link.appendChild(label);
            commandResults.appendChild(link);
        });
    }

    function openCommand() {
        if (!command) return;
        closePopovers();
        command.classList.add('is-open');
        command.setAttribute('aria-hidden', 'false');
        renderResults(commandInput ? commandInput.value : '');
        setTimeout(function () { if (commandInput) commandInput.focus(); }, 30);
    }

    function closeCommand() {
        if (!command) return;
        command.classList.remove('is-open');
        command.setAttribute('aria-hidden', 'true');
    }

    document.getElementById('saheSearchButton')?.addEventListener('click', openCommand);
    document.getElementById('saheNotificationButton')?.addEventListener('click', function (event) {
        event.stopPropagation(); togglePopover(notificationPanel, event.currentTarget);
    });
    document.getElementById('saheUserButton')?.addEventListener('click', function (event) {
        event.stopPropagation(); togglePopover(userPanel, event.currentTarget);
    });
    document.getElementById('saheSidebarUserButton')?.addEventListener('click', function (event) {
        event.stopPropagation(); togglePopover(userPanel, event.currentTarget);
    });
    document.getElementById('saheTourButton')?.addEventListener('click', function () {
        if (!tour) return;
        tour.classList.add('is-open');
        tour.setAttribute('aria-hidden', 'false');
    });
    document.getElementById('saheTourClose')?.addEventListener('click', function () {
        if (!tour) return;
        tour.classList.remove('is-open');
        tour.setAttribute('aria-hidden', 'true');
    });
    overlay?.addEventListener('click', closeSidebar);
    command?.addEventListener('click', function (event) { if (event.target === command) closeCommand(); });
    commandInput?.addEventListener('input', function () { renderResults(commandInput.value); });
    commandInput?.addEventListener('keydown', function (event) {
        var links = commandResults.querySelectorAll('.sahe-command-result');
        var active = commandResults.querySelector('.is-active');
        var index = Array.prototype.indexOf.call(links, active);
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            if (active) active.classList.remove('is-active');
            index = event.key === 'ArrowDown' ? Math.min(index + 1, links.length - 1) : Math.max(index - 1, 0);
            if (links[index]) { links[index].classList.add('is-active'); links[index].scrollIntoView({ block: 'nearest' }); }
        } else if (event.key === 'Enter' && active) {
            window.location.href = active.href;
        }
    });

    document.addEventListener('click', function (event) {
        if (!event.target.closest('.sahe-popover') && !event.target.closest('[aria-controls="saheNotifications"]') && !event.target.closest('[aria-controls="saheUserMenu"]')) closePopovers();
    });
    document.addEventListener('keydown', function (event) {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); openCommand(); }
        if (event.key === 'Escape') {
            closeCommand(); closePopovers(); closeSidebar();
            if (tour) { tour.classList.remove('is-open'); tour.setAttribute('aria-hidden', 'true'); }
        }
    });
    document.querySelectorAll('.crp-sidebar-item').forEach(function (link) { link.addEventListener('click', closeSidebar); });
})();
