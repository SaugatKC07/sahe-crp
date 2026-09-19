(function () {
    'use strict';
    var root = document.documentElement;
    var storageKey = 'sahe-crp-theme';

    function readCookie(name) {
        var prefix = name + '=';
        return document.cookie.split(';').map(function (value) { return value.trim(); })
            .filter(function (value) { return value.indexOf(prefix) === 0; })
            .map(function (value) { return decodeURIComponent(value.substring(prefix.length)); })[0] || '';
    }

    function refreshPortalNavigation() {
        var path = window.location.pathname;
        document.querySelectorAll('.crp-sidebar-item, .admin-link').forEach(function (link) {
            var linkPath = new URL(link.href, window.location.origin).pathname;
            link.classList.toggle('active', linkPath === path || (linkPath !== '/crp/' && path.indexOf(linkPath) === 0));
        });
    }

    function preferredTheme() {
        try {
            var saved = localStorage.getItem(storageKey);
            if (saved === 'dark' || saved === 'light') return saved;
        } catch (e) {}
        return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }

    function applyTheme(theme) {
        if (theme === 'dark') root.setAttribute('data-sahe-theme', 'dark');
        else root.removeAttribute('data-sahe-theme');
        document.querySelectorAll('.sahe-theme-toggle').forEach(function (button) {
            var dark = theme === 'dark';
            button.setAttribute('aria-label', dark ? 'Use light theme' : 'Use dark theme');
            button.setAttribute('title', dark ? 'Use light theme' : 'Use dark theme');
            if (button.hasAttribute('data-theme-label')) button.textContent = dark ? 'Light' : 'Dark';
            else button.innerHTML = '<i class="bi bi-' + (dark ? 'sun' : 'moon-stars') + '"></i>';
        });
        window.dispatchEvent(new CustomEvent('sahe:themechange', { detail: { theme: theme } }));
    }

    function installThemeControl() {
        if (document.querySelector('.sahe-theme-toggle')) return;
        var host = document.querySelector('.crp-topbar-right, .navbar-nav:last-child');
        if (!host) return;
        var button = document.createElement('button');
        button.type = 'button';
        button.className = 'sahe-theme-toggle';
        button.addEventListener('click', function () {
            var next = root.hasAttribute('data-sahe-theme') ? 'light' : 'dark';
            try { localStorage.setItem(storageKey, next); } catch (e) {}
            applyTheme(next);
        });
        host.insertBefore(button, host.firstChild);
        applyTheme(root.hasAttribute('data-sahe-theme') ? 'dark' : 'light');
    }

    applyTheme(preferredTheme());
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', installThemeControl);
    else installThemeControl();

    function installSidebarControl() {
        var sidebar = document.getElementById('crpSidebar');
        var overlay = document.getElementById('saheSidebarOverlay');
        if (!sidebar) return;
        var collapsed = false;
        function updateToggle() {
            document.querySelectorAll('.sahe-sidebar-toggle').forEach(function (button) {
                button.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
                button.setAttribute('aria-label', collapsed ? 'Expand navigation' : 'Collapse navigation');
                button.innerHTML = '<i class="bi bi-' + (collapsed ? 'layout-sidebar' : 'layout-sidebar-inset') + '"></i>';
            });
        }
        function closeSidebar() {
            sidebar.classList.remove('show');
            if (overlay) overlay.classList.remove('is-open');
            document.body.style.overflow = '';
        }
        window.toggleSidebar = function () {
            if (window.matchMedia('(max-width: 991.98px)').matches) {
                var open = !sidebar.classList.contains('show');
                sidebar.classList.toggle('show', open);
                if (overlay) overlay.classList.toggle('is-open', open);
                document.body.style.overflow = open ? 'hidden' : '';
                return;
            }
            collapsed = !collapsed;
            document.body.classList.toggle('sahe-sidebar-collapsed', collapsed);
            updateToggle();
        };
        document.querySelectorAll('.sahe-sidebar-toggle').forEach(function (button) {
            button.addEventListener('click', window.toggleSidebar);
        });
        updateToggle();
        if (overlay) overlay.addEventListener('click', closeSidebar);
        sidebar.querySelectorAll('.crp-sidebar-item').forEach(function (link) {
            link.addEventListener('click', closeSidebar);
        });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', installSidebarControl);
    else installSidebarControl();

    if (window.htmx) {
        document.body.addEventListener('htmx:configRequest', function (event) {
            var token = readCookie('csrftoken');
            if (token) event.detail.headers['X-CSRFToken'] = token;
        });
        document.body.addEventListener('htmx:beforeRequest', function () {
            document.body.classList.add('portal-navigating');
        });
        document.body.addEventListener('htmx:afterSwap', function () {
            document.body.classList.remove('portal-navigating');
            refreshPortalNavigation();
            window.dispatchEvent(new CustomEvent('sahe:contentready'));
        });
        document.body.addEventListener('htmx:afterRequest', function () {
            document.body.classList.remove('portal-navigating');
        });
        document.body.addEventListener('sahe:page-title', function (event) {
            var title = event.detail && event.detail.title;
            if (!title) return;
            document.title = title;
            var pageTitle = document.getElementById('portal-page-title');
            if (pageTitle) pageTitle.textContent = title.split(' · ')[0].split(' - ')[0];
        });
        refreshPortalNavigation();
    }
})();
