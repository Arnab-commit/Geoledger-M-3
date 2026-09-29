// GeoLedger — Digital Land Record Command Centre Core Application Framework
// Strictly preserves all existing API contracts, authentication mechanisms, and helper methods.

// API configuration
const API_BASE = '';  // Same origin

// Auth helper
const Auth = {
    getToken() { return localStorage.getItem('geoldger_token'); },
    setToken(token) { localStorage.setItem('geoldger_token', token); },
    getUser() {
        const user = localStorage.getItem('geoldger_user');
        try {
            return user ? JSON.parse(user) : null;
        } catch (e) {
            return null;
        }
    },
    setUser(user) { localStorage.setItem('geoldger_user', JSON.stringify(user)); },
    logout() {
        localStorage.removeItem('geoldger_token');
        localStorage.removeItem('geoldger_user');
        window.location.href = 'index.html';
    },
    isAuthenticated() { return !!this.getToken(); },
    requireAuth() {
        if (!this.isAuthenticated()) {
            window.location.href = 'index.html';
            return false;
        }
        // The browser cache is only a display hint. Confirm every protected
        // page session with the existing backend before treating it as valid.
        fetch('/api/auth/me', { headers: { Authorization: `Bearer ${this.getToken()}` } })
            .then(async response => {
                if (!response.ok) throw new Error('Session expired');
                const user = await response.json();
                this.setUser(user);
                if (typeof setupSidebar === 'function') setupSidebar();
            })
            .catch(() => this.logout());
        return true;
    },
    getHeaders() {
        const headers = { 'Content-Type': 'application/json' };
        const token = this.getToken();
        if (token) headers['Authorization'] = `Bearer ${token}`;
        return headers;
    },
    getUploadHeaders() {
        const headers = {};
        const token = this.getToken();
        if (token) headers['Authorization'] = `Bearer ${token}`;
        return headers;
    }
};

// Unified API caller
async function api(endpoint, options = {}) {
    const url = `${API_BASE}${endpoint}`;
    const config = {
        headers: Auth.getHeaders(),
        ...options,
    };
    if (options.body && !(options.body instanceof FormData)) {
        config.body = JSON.stringify(options.body);
    }
    if (options.body instanceof FormData) {
        config.headers = Auth.getUploadHeaders();
    }

    try {
        const response = await fetch(url, config);
        if (response.status === 401) {
            Auth.logout();
            return null;
        }
        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: `HTTP Error ${response.status}` }));
            throw new Error(error.detail || `HTTP ${response.status}`);
        }
        return await response.json();
    } catch (err) {
        throw err;
    }
}

// Toast notification helper (Archival Command Centre Styling)
function showToast(message, type = 'info') {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    const toastClass = type === 'error' || type === 'danger' ? 'toast-danger' :
                       type === 'success' ? 'toast-success' :
                       type === 'warning' ? 'toast-warning' : 'toast-info';

    toast.className = `toast ${toastClass}`;
    toast.innerHTML = `
        <div style="display: flex; align-items: center; gap: 8px;">
            <span style="font-weight: 500;">${message}</span>
        </div>
        <button onclick="this.parentElement.remove()" class="toast-close" title="Dismiss">&times;</button>
    `;

    container.appendChild(toast);
    setTimeout(() => {
        if (toast && toast.parentElement) {
            toast.style.opacity = '0';
            toast.style.transform = 'translateX(100%)';
            toast.style.transition = 'all 0.25s ease';
            setTimeout(() => toast.remove(), 250);
        }
    }, 4500);
}

// Formatting helpers
function formatDate(dateStr) {
    if (!dateStr) return '—';
    try {
        const d = new Date(dateStr);
        return d.toLocaleDateString('en-IN', {
            year: 'numeric', month: 'short', day: 'numeric',
            hour: '2-digit', minute: '2-digit'
        });
    } catch (e) {
        return dateStr;
    }
}

function formatConfidence(value) {
    if (value === null || value === undefined) return '—';
    const num = typeof value === 'number' ? value : parseFloat(value);
    const pct = num <= 1.0 ? (num * 100).toFixed(0) : num.toFixed(0);
    let cls = 'confidence-high';
    if (pct < 60) cls = 'confidence-low';
    else if (pct < 85) cls = 'confidence-medium';
    return `<span class="confidence-badge ${cls}">${pct}%</span>`;
}

function getStatusBadge(status) {
    if (!status) return '<span class="badge badge-secondary">—</span>';
    const s = String(status).toLowerCase();
    const map = {
        'verified': 'success',
        'completed': 'success',
        'resolved': 'success',
        'clear': 'success',
        'pending': 'warning',
        'needs_review': 'warning',
        'in_review': 'warning',
        'preprocessing': 'warning',
        'ocr_processing': 'warning',
        'extraction': 'warning',
        'corrected': 'info',
        'open': 'warning',
        'failed': 'danger',
        'rejected': 'danger',
        'high': 'danger',
        'critical': 'danger',
        'medium': 'warning',
        'low': 'info'
    };
    const badgeType = map[s] || 'secondary';
    return `<span class="badge badge-${badgeType}">${status.replace(/_/g, ' ')}</span>`;
}

// Format cryptographic SHA-256 hash
function formatHash(hash) {
    if (!hash) return '—';
    const short = hash.substring(0, 12) + '...';
    return `<code class="tabular-code link" title="Click to copy full SHA-256 hash" onclick="copyToClipboard('${hash}', 'SHA-256 Hash')">${short}</code>`;
}

// Format hectares / acres with precision
function formatArea(hectares, unit = 'Ha') {
    if (hectares === null || hectares === undefined || isNaN(hectares)) return '—';
    const val = parseFloat(hectares);
    return `${val.toFixed(4)} ${unit}`;
}

// Setup common sidebar user info and navigation with RBAC adaptation
function setupSidebar() {
    const user = Auth.getUser();
    const userInfo = document.getElementById('user-info');
    if (userInfo && user) {
        const rawRole = (user.role || 'citizen').toLowerCase();
        const isOfficer = rawRole === 'revenue_officer' || rawRole === 'verifier';
        const isAdmin = rawRole === 'admin' || rawRole === 'super_admin';
        const isAuditor = rawRole === 'auditor';
        const isCitizen = !isOfficer && !isAdmin && !isAuditor;

        const roleLabel = isAdmin ? 'ADMINISTRATOR' :
                          isOfficer ? 'REVENUE OFFICER' :
                          isAuditor ? 'LAND AUDITOR' : 'CITIZEN';

        const roleDesc = isAdmin ? 'SYSTEM GOVERNANCE' :
                         isOfficer ? 'CADASTRAL ADJUDICATOR' :
                         isAuditor ? 'STATUTORY AUDIT OBSERVER' : 'LANDOWNER / APPLICANT';

        const badgeClass = isAdmin ? 'badge-danger' :
                           isOfficer ? 'badge-info' :
                           isAuditor ? 'badge-warning' : 'badge-secondary';

        userInfo.innerHTML = `
            <div class="user-badge-container">
                <div style="color: #FFFFFF; font-weight: 600; font-size: 0.82rem; font-family: var(--font-body);">${user.full_name || user.username}</div>
                <div class="user-badge-meta">
                    <span class="badge ${badgeClass}" style="font-size: 0.62rem; padding: 1px 6px;">${roleLabel}</span>
                    <span style="font-size: 0.68rem; color: #8C959E;">${roleDesc}</span>
                </div>
            </div>
        `;

        // Dynamic RBAC Menu adaptation for Citizens
        if (isCitizen) {
            // Update labels to citizen-centric view
            document.querySelectorAll('.sidebar-nav .nav-link').forEach(link => {
                const href = link.getAttribute('href');
                if (href === 'documents.html') {
                    const span = link.querySelector('span:first-child');
                    if (span) span.textContent = 'My Documents & Intake';
                }
                if (href === 'parcel.html') {
                    const span = link.querySelector('span:first-child');
                    if (span) span.textContent = 'My Land Parcels';
                }
                if (href === 'verification.html') {
                    // Citizens cannot adjudicate: hide from primary nav
                    link.style.display = 'none';
                }
            });
        }

        // Dynamic RBAC Menu adaptation for Administrators
        if (isAdmin) {
            const nav = document.querySelector('.sidebar-nav');
            if (nav && !document.getElementById('nav-admin-link')) {
                const adminLink = document.createElement('a');
                adminLink.id = 'nav-admin-link';
                adminLink.href = 'admin.html';
                adminLink.className = 'nav-link';
                adminLink.innerHTML = `
                    <span>User & Role Governance</span>
                    <span class="nav-link-code">ADM</span>
                `;
                nav.appendChild(adminLink);
            }
        }
    }

    // Highlight current nav item
    const path = window.location.pathname.split('/').pop() || 'dashboard.html';
    document.querySelectorAll('.sidebar-nav .nav-link').forEach(link => {
        const href = link.getAttribute('href');
        if (href === path) {
            link.classList.add('active');
        } else {
            link.classList.remove('active');
        }
    });

    // Initialize global command search bar if present
    initGlobalCommandSearch();
}

// Global Command Search handler across ULPIN, Khasra, and Cases
function initGlobalCommandSearch() {
    const searchInput = document.getElementById('global-command-search');
    if (!searchInput || searchInput.dataset.bound === 'true') return;
    searchInput.dataset.bound = 'true';

    searchInput.addEventListener('keydown', async (e) => {
        if (e.key === 'Enter') {
            const query = searchInput.value.trim();
            if (!query) return;

            showToast(`Searching record index for "${query}"...`, 'info');
            try {
                // First query parcels
                const parcels = await api(`/api/parcels?search=${encodeURIComponent(query)}&limit=1`);
                if (parcels && parcels.length > 0) {
                    window.location.href = `parcel.html?id=${parcels[0].id}`;
                    return;
                }

                // If not found as parcel, check documents
                const docRes = await api(`/api/documents?search=${encodeURIComponent(query)}&limit=1`);
                const matchedDoc = (docRes.documents || [])[0];
                if (matchedDoc) {
                    window.location.href = `documents.html?search=${encodeURIComponent(query)}`;
                    return;
                }

                showToast(`No exact parcel or document found for "${query}". Redirecting to parcel registry.`, 'warning');
                setTimeout(() => { window.location.href = 'parcel.html'; }, 1000);
            } catch (err) {
                console.error('Search error:', err);
                window.location.href = `parcel.html`;
            }
        }
    });
}

// Modal management
function openModal(id) {
    const el = document.getElementById(id);
    if (el) {
        el.style.display = 'flex';
        el.classList.add('active');
    }
}

function closeModal(id) {
    const el = document.getElementById(id);
    if (el) {
        el.style.display = 'none';
        el.classList.remove('active');
    }
}

// Copy to clipboard with toast
function copyToClipboard(text, label = 'Copied') {
    if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(() => {
            showToast(`${label} copied to clipboard`, 'success');
        });
    }
}
