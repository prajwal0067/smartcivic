// SmartCivic AI Portal - Frontend Javascript

const API_BASE = window.location.origin;
let allComplaints = [];
let selectedImageFile = null;
let map = null;
let marker = null;

// DOM Elements
const submitBtn = document.getElementById('submit-btn');
const btnText = document.getElementById('btn-text');
const btnSpinner = document.getElementById('btn-spinner');
const complaintTextarea = document.getElementById('complaint-text');
const ticketsContainer = document.getElementById('tickets-container');
const notificationContainer = document.getElementById('notification-container');

// Stats Counters
const kpiTotal = document.getElementById('kpi-total');
const kpiCritical = document.getElementById('kpi-critical');
const kpiWet = document.getElementById('kpi-wet');
const kpiResolved = document.getElementById('kpi-resolved');

// Filter Inputs
const searchInput = document.getElementById('search-input');
const filterSeverity = document.getElementById('filter-severity');
const filterType = document.getElementById('filter-type');
const filterStatus = document.getElementById('filter-status');

// New Auth & Tracking DOM Elements
const authPanel = document.getElementById('auth-panel');
const trackingDashboard = document.getElementById('tracking-dashboard');
const myTicketsContainer = document.getElementById('my-tickets-container');
const citizenDisplayName = document.getElementById('citizen-display-name');
const complaintImageInput = document.getElementById('complaint-image');
const uploadPreviewContainer = document.getElementById('upload-preview-container');
const uploadPreview = document.getElementById('upload-preview');
const uploadPrompt = document.getElementById('upload-prompt');
const uploadIcon = document.getElementById('upload-icon');
const uploadZone = document.getElementById('upload-zone');

const mainNavTabs = document.getElementById('main-nav-tabs');
const userProfileHeader = document.getElementById('user-profile-header');
const headerUsername = document.getElementById('header-username');
const headerUserAvatar = document.getElementById('header-user-avatar');

// Predefined Samples
const SAMPLES = {
    1: "The waste collector skipped ward 5 on Ring Road in Shimoga again. There's a pile of decomposing kitchen food waste on the curb and the smell is awful, stray animals are tearing it up.",
    2: "There are lots of discarded cardboard boxes and empty plastic bottles lying around in the central market area on MG Road. It looks very messy.",
    3: "A mix of kitchen garbage bags and plastic containers have been dumped near the government school entrance on Nehru Road. The pile is growing and blocking the gate.",
    4: "Our regular collection truck hasn't visited standard street, Sagar for two days. Bins are full but not yet spilling."
};

// Initialize App
window.addEventListener('DOMContentLoaded', () => {
    const token = localStorage.getItem('citizen_token');
    if (!token) {
        showAuthView();
    } else {
        showMainApp();
    }
    setupDragAndDrop();
});

// Authentication UI control
function showAuthView() {
    if (mainNavTabs) mainNavTabs.style.display = 'none';
    if (userProfileHeader) userProfileHeader.style.display = 'none';
    
    document.querySelectorAll('.view-panel').forEach(panel => {
        panel.classList.remove('active');
    });
    
    const viewAuth = document.getElementById('view-auth');
    if (viewAuth) viewAuth.classList.add('active');
}

// Show active citizen dashboard if logged in
function showMainApp() {
    const name = localStorage.getItem('citizen_name');
    
    if (mainNavTabs) mainNavTabs.style.display = 'flex';
    if (userProfileHeader) {
        userProfileHeader.style.display = 'flex';
        if (headerUsername) headerUsername.textContent = name || 'Citizen';
        if (headerUserAvatar) headerUserAvatar.textContent = (name || 'C').charAt(0).toUpperCase();
    }
    
    switchTab('citizen');
}

// Tab Management
function switchTab(tabName) {
    const token = localStorage.getItem('citizen_token');
    if (!token) {
        showAuthView();
        return;
    }

    document.querySelectorAll('.nav-tab').forEach(tab => {
        tab.classList.remove('active');
    });
    const activeTabButton = document.getElementById(`tab-${tabName}`);
    if (activeTabButton) activeTabButton.classList.add('active');

    document.querySelectorAll('.view-panel').forEach(panel => {
        panel.classList.remove('active');
    });
    const activePanel = document.getElementById(`view-${tabName}`);
    if (activePanel) activePanel.classList.add('active');

    if (tabName === 'admin') {
        fetchComplaints();
    } else if (tabName === 'track') {
        fetchMyComplaints();
    } else if (tabName === 'citizen') {
        setTimeout(initMap, 100);
    }
}

// Map Geotagging Widget Logic (Leaflet)
function initMap() {
    const mapElement = document.getElementById('map');
    if (!mapElement || map) return; // map is already defined

    const defaultLat = 12.9716;
    const defaultLng = 77.5946;

    if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(
            (position) => {
                setupMap(position.coords.latitude, position.coords.longitude);
            },
            () => {
                setupMap(defaultLat, defaultLng);
            }
        );
    } else {
        setupMap(defaultLat, defaultLng);
    }
}

function setupMap(lat, lng) {
    try {
        if (typeof L !== 'undefined') {
            map = L.map('map').setView([lat, lng], 13);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                maxZoom: 19,
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            }).addTo(map);

            marker = L.marker([lat, lng], { draggable: true }).addTo(map);

            updateCoordsDisplay(lat, lng);

            marker.on('dragend', () => {
                const pos = marker.getLatLng();
                updateCoordsDisplay(pos.lat, pos.lng);
            });

            map.on('click', (e) => {
                const clickLat = e.latlng.lat;
                const clickLng = e.latlng.lng;
                marker.setLatLng([clickLat, clickLng]);
                updateCoordsDisplay(clickLat, clickLng);
            });
            
            setTimeout(() => {
                if (map) map.invalidateSize();
            }, 300);
        } else {
            console.error("Leaflet is not loaded.");
        }
    } catch (e) {
        console.error("Error setting up Leaflet map:", e);
    }
}

function updateCoordsDisplay(lat, lng) {
    const latDisplay = document.getElementById('lat-display');
    const lngDisplay = document.getElementById('lng-display');
    const latInput = document.getElementById('complaint-lat');
    const lngInput = document.getElementById('complaint-lng');

    if (latDisplay) latDisplay.textContent = parseFloat(lat).toFixed(6);
    if (lngDisplay) lngDisplay.textContent = parseFloat(lng).toFixed(6);
    if (latInput) latInput.value = lat;
    if (lngInput) lngInput.value = lng;
}

function locateUser() {
    if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(
            (position) => {
                const lat = position.coords.latitude;
                const lng = position.coords.longitude;
                if (map && marker) {
                    map.setView([lat, lng], 15);
                    marker.setLatLng([lat, lng]);
                    updateCoordsDisplay(lat, lng);
                } else {
                    setupMap(lat, lng);
                }
            },
            () => {
                showToast("Could not access your location. Check GPS/permissions.", "error");
            }
        );
    } else {
        showToast("Geolocation is not supported by your browser.", "error");
    }
}

// Load Preset Samples
function loadSample(index) {
    if (SAMPLES[index]) {
        complaintTextarea.value = SAMPLES[index];
        showToast("Sample loaded into textarea. Hit submit to test!", "success");
        complaintTextarea.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
}

// Citizen Form Submission
async function submitComplaint(event) {
    event.preventDefault();
    const text = complaintTextarea.value.trim();

    if (!text || text.length < 5) {
        showToast("Please enter a descriptive complaint.", "error");
        return;
    }

    submitBtn.disabled = true;
    btnText.style.display = 'none';
    btnSpinner.style.display = 'block';

    try {
        const formData = new FormData();
        formData.append('text', text);
        if (selectedImageFile) {
            formData.append('file', selectedImageFile); // 'file' matches backend parameter
        }

        const latInput = document.getElementById('complaint-lat');
        const lngInput = document.getElementById('complaint-lng');
        if (latInput && latInput.value) {
            formData.append('latitude', latInput.value);
        }
        if (lngInput && lngInput.value) {
            formData.append('longitude', lngInput.value);
        }

        const headers = {};
        const token = localStorage.getItem('citizen_token');
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        } else {
            showToast("You must be logged in to submit a complaint.", "error");
            showAuthView();
            return;
        }

        const response = await fetch(`${API_BASE}/api/complaints`, {
            method: 'POST',
            headers: headers,
            body: formData
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || "Server error occurred");
        }

        const data = await response.json();
        
        // Show success analysis results popup modal
        showResultsModal(data);

        // Reset state
        complaintTextarea.value = '';
        clearImagePreview();
        
        if (map && marker) {
            const defaultLat = 12.9716;
            const defaultLng = 77.5946;
            map.setView([defaultLat, defaultLng], 13);
            marker.setLatLng([defaultLat, defaultLng]);
            updateCoordsDisplay(defaultLat, defaultLng);
        }

    } catch (error) {
        console.error("Error submitting complaint:", error);
        showToast(`Submission failed: ${error.message}`, "error");
    } finally {
        submitBtn.disabled = false;
        btnText.style.display = 'block';
        btnSpinner.style.display = 'none';
    }
}

// Modal Display logic
function showResultsModal(data) {
    const modal = document.getElementById('results-modal');
    if (!modal) return;

    document.getElementById('res-location').textContent = data.location || 'Unknown';
    
    const severityVal = document.getElementById('res-severity');
    severityVal.textContent = data.severity || 'Medium';
    severityVal.className = 'result-value badge';
    if (data.severity === 'Critical') severityVal.classList.add('badge-critical');
    else if (data.severity === 'Low') severityVal.classList.add('badge-low');
    else severityVal.classList.add('badge-medium');

    const typeVal = document.getElementById('res-type');
    typeVal.textContent = data.waste_type || 'Mixed';
    typeVal.className = 'result-value badge badge-type';

    const coordsVal = document.getElementById('res-coords');
    if (data.latitude && data.longitude) {
        coordsVal.textContent = `${parseFloat(data.latitude).toFixed(5)}, ${parseFloat(data.longitude).toFixed(5)}`;
    } else {
        coordsVal.textContent = 'Not Geotagged';
    }

    document.getElementById('res-reason').textContent = data.urgency_reason || '';

    const imgSection = document.getElementById('res-image-section');
    if (data.image_path) {
        document.getElementById('res-image-preview').src = `${API_BASE}${data.image_path}`;
        const tagsContainer = document.getElementById('res-image-tags');
        tagsContainer.innerHTML = '';
        
        if (data.image_tags) {
            const tags = data.image_tags.split(', ');
            tags.forEach(tag => {
                const pill = document.createElement('span');
                pill.className = 'ai-pill';
                pill.textContent = tag;
                tagsContainer.appendChild(pill);
            });
        } else {
            const pill = document.createElement('span');
            pill.className = 'ai-pill';
            pill.textContent = 'No Objects Identified';
            tagsContainer.appendChild(pill);
        }
        
        imgSection.style.display = 'block';
    } else {
        imgSection.style.display = 'none';
    }

    modal.style.display = 'flex';
}

function closeResultsModal() {
    const modal = document.getElementById('results-modal');
    if (modal) {
        modal.style.display = 'none';
    }
    switchTab('track');
}

// Fetch all complaints from local SQLite DB
async function fetchComplaints() {
    try {
        const response = await fetch(`${API_BASE}/api/complaints`);
        if (!response.ok) {
            throw new Error("Unable to fetch grievances dashboard");
        }
        allComplaints = await response.json();
        updateKpis(allComplaints);
        applyFilters();
    } catch (error) {
        console.error("Error loading complaints:", error);
        showToast("Error connecting to operations dashboard.", "error");
        
        ticketsContainer.innerHTML = `
            <div class="empty-state">
                <svg class="empty-icon" viewBox="0 0 24 24" style="fill: var(--color-critical)">
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/>
                </svg>
                <h3 class="empty-title">Dashboard Loading Error</h3>
                <p class="empty-desc">${error.message}</p>
            </div>
        `;
    }
}

// Calculate Dashboard Statistics
function updateKpis(complaints) {
    const total = complaints.length;
    const critical = complaints.filter(c => c.severity === 'Critical' && c.status === 'Pending').length;
    const wet = complaints.filter(c => c.waste_type === 'Wet' && c.status === 'Pending').length;
    const resolved = complaints.filter(c => c.status === 'Resolved').length;

    kpiTotal.textContent = total;
    kpiCritical.textContent = critical;
    kpiWet.textContent = wet;
    kpiResolved.textContent = resolved;
}

// Apply multi-field filtering
function applyFilters() {
    const query = searchInput.value.toLowerCase().trim();
    const severity = filterSeverity.value;
    const type = filterType.value;
    const status = filterStatus.value;

    const filtered = allComplaints.filter(complaint => {
        const matchesQuery = !query || 
            complaint.location.toLowerCase().includes(query) || 
            complaint.raw_text.toLowerCase().includes(query) ||
            complaint.urgency_reason.toLowerCase().includes(query);

        const matchesSeverity = severity === 'all' || complaint.severity === severity;
        const matchesType = type === 'all' || complaint.waste_type === type;
        const matchesStatus = status === 'all' || complaint.status === status;

        return matchesQuery && matchesSeverity && matchesType && matchesStatus;
    });

    renderComplaints(filtered);
}

// Helper to format date string
function formatDate(isoString) {
    try {
        const dateStr = isoString.replace(" ", "T");
        const date = new Date(dateStr);
        if (isNaN(date.getTime())) return isoString;
        
        return date.toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    } catch(e) {
        return isoString;
    }
}

// Generate grievance cards list in admin dashboard
function renderComplaints(complaints) {
    if (!complaints || complaints.length === 0) {
        ticketsContainer.innerHTML = `
            <div class="empty-state">
                <svg class="empty-icon" viewBox="0 0 24 24">
                    <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
                </svg>
                <h3 class="empty-title">No Grievances Found</h3>
                <p class="empty-desc">Adjust your filters or submit a new citizen complaint.</p>
            </div>
        `;
        return;
    }

    ticketsContainer.innerHTML = complaints.map(ticket => {
        const severityClass = `severity-${ticket.severity.toLowerCase()}`;
        const statusClass = `status-${ticket.status.toLowerCase()}`;
        
        const badgeClassMap = {
            'Low': 'badge-low',
            'Medium': 'badge-medium',
            'Critical': 'badge-critical'
        };
        
        const badgeClass = badgeClassMap[ticket.severity] || 'badge-medium';
        const isResolved = ticket.status === 'Resolved';
        
        const checkIcon = `<svg viewBox="0 0 24 24"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>`;
        const restoreIcon = `<svg viewBox="0 0 24 24"><path d="M12 5V1L7 6l5 5V7c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6H4c0 4.42 3.58 8 8 8s8-3.58 8-8-3.58-8-8-8z"/></svg>`;
        
        return `
            <div class="ticket-card ${severityClass} ${statusClass}" id="ticket-${ticket.id}">
                <div class="ticket-header" onclick="toggleCard(${ticket.id})">
                    <div class="ticket-left">
                        <span class="ticket-id">#${ticket.id}</span>
                        <span class="badge ${badgeClass}">${ticket.severity}</span>
                        <span class="badge badge-type">${ticket.waste_type}</span>
                        
                        <div class="ticket-location">
                            <svg viewBox="0 0 24 24"><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/></svg>
                            <span>${ticket.location}</span>
                        </div>
                    </div>
                    
                    <div class="ticket-right">
                        <span class="ticket-timestamp">${formatDate(ticket.created_at)}</span>
                        
                        <div class="ticket-actions">
                            <button 
                                class="btn-icon resolve-btn" 
                                title="${isResolved ? 'Mark as Unresolved' : 'Mark as Resolved'}"
                                onclick="toggleResolve(${ticket.id}, '${ticket.status}', event)"
                            >
                                ${isResolved ? restoreIcon : checkIcon}
                            </button>
                            
                            <button 
                                class="btn-icon delete-btn" 
                                title="Delete Complaint"
                                onclick="deleteComplaint(${ticket.id}, event)"
                            >
                                <svg viewBox="0 0 24 24"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>
                            </button>
                            
                            <button class="btn-icon expand-toggle-btn" title="Toggle Detail View">
                                <svg class="expand-arrow" viewBox="0 0 24 24" style="width: 20px; height: 20px; transition: transform 0.2s;"><path d="M16.59 8.59L12 13.17 7.41 8.59 6 10l6 6 6-6z"/></svg>
                            </button>
                        </div>
                    </div>
                </div>
                
                <div class="ticket-drawer">
                    <div class="drawer-content">
                        <div>
                            <h4 class="drawer-panel-title">Citizen Grievance Text</h4>
                            <div class="raw-text-panel">"${ticket.raw_text}"</div>
                            ${ticket.image_path ? `
                            <div style="margin-top: 1rem;">
                                <h4 class="drawer-panel-title">Attached Photo</h4>
                                <div class="complaint-img-container">
                                    <img src="${API_BASE}${ticket.image_path}" alt="Situation Photo" onclick="window.open('${API_BASE}${ticket.image_path}', '_blank')">
                                </div>
                                ${ticket.image_tags ? `
                                <div style="margin-top: 0.5rem;">
                                    <span class="badge image-tags-badge">
                                        <svg viewBox="0 0 24 24" style="width:12px;height:12px;fill:currentColor;"><path d="M21.41 11.58l-9-9C12.05 2.22 11.55 2 11 2H4c-1.1 0-2 .9-2 2v7c0 .55.22 1.05.59 1.42l9 9c.36.36.86.58 1.41.58.55 0 1.05-.22 1.41-.59l7-7c.37-.36.59-.86.59-1.41 0-.55-.23-1.06-.59-1.42zM5.5 7C4.67 7 4 6.33 4 5.5S4.67 4 5.5 4 7 4.67 7 5.5 6.33 7 5.5 7z"/></svg>
                                        AI Tags: ${ticket.image_tags}
                                    </span>
                                </div>
                                ` : ''}
                            </div>
                            ` : ''}
                        </div>
                        
                        <div class="ai-reasoning-panel">
                            <h4 class="drawer-panel-title">AI Analysis & Reason</h4>
                            <p class="ai-reasoning-text">${ticket.urgency_reason}</p>
                            
                            <div class="ai-tag-bar">
                                <span class="ai-pill">Auto-Location: ${ticket.location}</span>
                                <span class="ai-pill">Severity: ${ticket.severity}</span>
                                <span class="ai-pill">Type: ${ticket.waste_type}</span>
                                ${ticket.latitude && ticket.longitude ? `
                                <a href="https://www.google.com/maps/search/?api=1&query=${ticket.latitude},${ticket.longitude}" target="_blank" class="geo-link" onclick="event.stopPropagation()">
                                    <svg viewBox="0 0 24 24"><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/></svg>
                                    <span>Pinpoint (${parseFloat(ticket.latitude).toFixed(4)}, ${parseFloat(ticket.longitude).toFixed(4)})</span>
                                </a>
                                ` : ''}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function toggleCard(id) {
    const card = document.getElementById(`ticket-${id}`);
    if (card) {
        const isExpanded = card.classList.toggle('expanded');
        const arrow = card.querySelector('.expand-arrow');
        if (arrow) {
            arrow.style.transform = isExpanded ? 'rotate(180deg)' : 'rotate(0deg)';
        }
    }
}

// Toggle ticket status
async function toggleResolve(id, currentStatus, event) {
    event.stopPropagation();
    const newStatus = currentStatus === 'Pending' ? 'Resolved' : 'Pending';
    
    try {
        const response = await fetch(`${API_BASE}/api/complaints/${id}`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ status: newStatus })
        });

        if (!response.ok) {
            throw new Error("Failed to update status");
        }

        showToast(`Ticket #${id} marked as ${newStatus.toLowerCase()}.`, "success");
        fetchComplaints();
    } catch (error) {
        console.error(error);
        showToast(`Failed to update ticket: ${error.message}`, "error");
    }
}

// Delete ticket entry from db
async function deleteComplaint(id, event) {
    event.stopPropagation();
    if (!confirm(`Are you sure you want to permanently delete ticket #${id}?`)) {
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/api/complaints/${id}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            throw new Error("Failed to delete record");
        }

        showToast(`Ticket #${id} has been permanently deleted.`, "success");
        fetchComplaints();
    } catch (error) {
        console.error(error);
        showToast(`Failed to delete complaint: ${error.message}`, "error");
    }
}

// Toast System
function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    
    const icon = type === 'success' 
        ? `<svg viewBox="0 0 24 24" style="width:20px;height:20px;fill:var(--color-low);"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>`
        : `<svg viewBox="0 0 24 24" style="width:20px;height:20px;fill:var(--color-critical);"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>`;
        
    toast.innerHTML = `
        ${icon}
        <span class="toast-message">${message}</span>
    `;

    notificationContainer.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('toast-out');
        toast.addEventListener('animationend', () => {
            toast.remove();
        });
    }, 4000);
}

// Fetch personalized reports list (My complaints)
async function fetchMyComplaints() {
    const token = localStorage.getItem('citizen_token');
    if (!token) return;
    
    try {
        myTicketsContainer.innerHTML = `
            <div class="empty-state">
                <svg class="empty-icon" viewBox="0 0 24 24" style="animation: rotate 2s linear infinite;">
                    <circle cx="12" cy="12" r="10" fill="none" stroke="var(--primary)" stroke-width="3" stroke-dasharray="15 30"></circle>
                </svg>
                <h3 class="empty-title">Loading grievances...</h3>
                <p class="empty-desc">Fetching tickets tied to your citizen portal account.</p>
            </div>
        `;
        
        const response = await fetch(`${API_BASE}/api/complaints/me`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        
        if (!response.ok) {
            if (response.status === 401) {
                handleLogout();
                return;
            }
            throw new Error("Unable to fetch personalized reports list");
        }
        
        const myComplaints = await response.json();
        renderMyComplaints(myComplaints);
    } catch (error) {
        console.error("Error fetching citizen complaints:", error);
        myTicketsContainer.innerHTML = `
            <div class="empty-state">
                <h3 class="empty-title" style="color: var(--color-critical);">Personal Dashboard Error</h3>
                <p class="empty-desc">${error.message}</p>
            </div>
        `;
    }
}

// Render personal tickets in Citizen Tracking tab
function renderMyComplaints(complaints) {
    if (!complaints || complaints.length === 0) {
        myTicketsContainer.innerHTML = `
            <div class="empty-state">
                <svg class="empty-icon" viewBox="0 0 24 24">
                    <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
                </svg>
                <h3 class="empty-title">No Grievances Found</h3>
                <p class="empty-desc">You have not submitted any complaints under this account yet.</p>
            </div>
        `;
        return;
    }

    myTicketsContainer.innerHTML = complaints.map(ticket => {
        const severityClass = `severity-${ticket.severity.toLowerCase()}`;
        const statusClass = `status-${ticket.status.toLowerCase()}`;
        
        const badgeClassMap = {
            'Low': 'badge-low',
            'Medium': 'badge-medium',
            'Critical': 'badge-critical'
        };
        
        const badgeClass = badgeClassMap[ticket.severity] || 'badge-medium';
        const isResolved = ticket.status === 'Resolved';
        
        return `
            <div class="ticket-card ${severityClass} ${statusClass}" id="my-ticket-${ticket.id}">
                <div class="ticket-header" onclick="toggleMyCard(${ticket.id})">
                    <div class="ticket-left">
                        <span class="ticket-id">#${ticket.id}</span>
                        <span class="badge ${badgeClass}">${ticket.severity}</span>
                        <span class="badge badge-type">${ticket.waste_type}</span>
                        
                        <div class="ticket-location">
                            <svg viewBox="0 0 24 24"><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/></svg>
                            <span>${ticket.location}</span>
                        </div>
                    </div>
                    
                    <div class="ticket-right">
                        <span class="badge ${isResolved ? 'badge-low' : 'badge-medium'}">${ticket.status}</span>
                        <span class="ticket-timestamp">${formatDate(ticket.created_at)}</span>
                        <button class="btn-icon expand-toggle-btn" title="Toggle Detail View">
                            <svg class="expand-arrow" viewBox="0 0 24 24" style="width: 20px; height: 20px; transition: transform 0.2s;"><path d="M16.59 8.59L12 13.17 7.41 8.59 6 10l6 6 6-6z"/></svg>
                        </button>
                    </div>
                </div>
                
                <div class="ticket-drawer">
                    <div class="drawer-content">
                        <div>
                            <h4 class="drawer-panel-title">Citizen Grievance Description</h4>
                            <div class="raw-text-panel">"${ticket.raw_text}"</div>
                            ${ticket.image_path ? `
                            <div style="margin-top: 1rem;">
                                <h4 class="drawer-panel-title">Attached Photo</h4>
                                <div class="complaint-img-container">
                                    <img src="${API_BASE}${ticket.image_path}" alt="Attached Photo" onclick="window.open('${API_BASE}${ticket.image_path}', '_blank')">
                                </div>
                                ${ticket.image_tags ? `
                                <div style="margin-top: 0.5rem;">
                                    <span class="badge image-tags-badge">
                                        <svg viewBox="0 0 24 24" style="width:12px;height:12px;fill:currentColor;"><path d="M21.41 11.58l-9-9C12.05 2.22 11.55 2 11 2H4c-1.1 0-2 .9-2 2v7c0 .55.22 1.05.59 1.42l9 9c.36.36.86.58 1.41.58.55 0 1.05-.22 1.41-.59l7-7c.37-.36.59-.86.59-1.41 0-.55-.23-1.06-.59-1.42zM5.5 7C4.67 7 4 6.33 4 5.5S4.67 4 5.5 4 7 4.67 7 5.5 6.33 7 5.5 7z"/></svg>
                                        AI Tags: ${ticket.image_tags}
                                    </span>
                                </div>
                                ` : ''}
                            </div>
                            ` : ''}
                        </div>
                        
                        <div class="ai-reasoning-panel">
                            <h4 class="drawer-panel-title">AI Analysis Details</h4>
                            <p class="ai-reasoning-text">${ticket.urgency_reason}</p>
                            
                            <div class="ai-tag-bar">
                                <span class="ai-pill">Detected Location: ${ticket.location}</span>
                                <span class="ai-pill">Severity: ${ticket.severity}</span>
                                <span class="ai-pill">Waste Categorization: ${ticket.waste_type}</span>
                                ${ticket.latitude && ticket.longitude ? `
                                <a href="https://www.google.com/maps/search/?api=1&query=${ticket.latitude},${ticket.longitude}" target="_blank" class="geo-link" onclick="event.stopPropagation()">
                                    <svg viewBox="0 0 24 24"><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/></svg>
                                    <span>Pinpoint (${parseFloat(ticket.latitude).toFixed(4)}, ${parseFloat(ticket.longitude).toFixed(4)})</span>
                                </a>
                                ` : ''}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function toggleMyCard(id) {
    const card = document.getElementById(`my-ticket-${id}`);
    if (card) {
        const isExpanded = card.classList.toggle('expanded');
        const arrow = card.querySelector('.expand-arrow');
        if (arrow) {
            arrow.style.transform = isExpanded ? 'rotate(180deg)' : 'rotate(0deg)';
        }
    }
}

// Drag & Drop / Image Selection Handlers
function handleImageSelect(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    if (file.size > 5 * 1024 * 1024) {
        showToast("Image size must be less than 5MB", "error");
        complaintImageInput.value = '';
        return;
    }
    
    selectedImageFile = file;
    
    const reader = new FileReader();
    reader.onload = (e) => {
        uploadPreview.src = e.target.result;
        uploadPreviewContainer.style.display = 'block';
        uploadPrompt.style.display = 'none';
        uploadIcon.style.display = 'none';
    };
    reader.readAsDataURL(file);
}

function clearImagePreview(event) {
    if (event) event.stopPropagation();
    selectedImageFile = null;
    complaintImageInput.value = '';
    uploadPreview.src = '';
    uploadPreviewContainer.style.display = 'none';
    uploadPrompt.style.display = 'block';
    uploadIcon.style.display = 'block';
}

function setupDragAndDrop() {
    if (!uploadZone) return;
    
    ['dragenter', 'dragover'].forEach(eventName => {
        uploadZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            uploadZone.classList.add('dragover');
        }, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        uploadZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            uploadZone.classList.remove('dragover');
        }, false);
    });

    uploadZone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;
        if (files && files.length > 0) {
            complaintImageInput.files = files;
            handleImageSelect({ target: { files: files } });
        }
    }, false);
}

// Auth Handlers
function switchAuthMode(mode) {
    document.querySelectorAll('.auth-tab').forEach(tab => tab.classList.remove('active'));
    document.querySelectorAll('.auth-form').forEach(form => form.classList.remove('active'));
    
    if (mode === 'login') {
        document.getElementById('auth-tab-login').classList.add('active');
        document.getElementById('login-form').classList.add('active');
    } else {
        document.getElementById('auth-tab-signup').classList.add('active');
        document.getElementById('signup-form').classList.add('active');
    }
}

async function handleLogin(event) {
    event.preventDefault();
    const username = document.getElementById('login-username').value.trim();
    const password = document.getElementById('login-password').value;
    
    try {
        const response = await fetch(`${API_BASE}/api/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || "Authentication failed");
        }
        
        const data = await response.json();
        localStorage.setItem('citizen_token', data.token);
        localStorage.setItem('citizen_name', data.user.username);
        showToast(`Signed in successfully! Welcome back, ${data.user.username}.`, "success");
        
        document.getElementById('login-form').reset();
        showMainApp();
    } catch(e) {
        console.error(e);
        showToast(e.message, "error");
    }
}

async function handleSignup(event) {
    event.preventDefault();
    const username = document.getElementById('signup-username').value.trim();
    const password = document.getElementById('signup-password').value;
    
    try {
        const response = await fetch(`${API_BASE}/api/auth/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || "Registration failed");
        }
        
        // Auto login on successful register
        const loginResponse = await fetch(`${API_BASE}/api/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        
        if (!loginResponse.ok) {
            showToast("Registration successful! Please log in manually.", "success");
            switchAuthMode('login');
            return;
        }
        
        const data = await loginResponse.json();
        localStorage.setItem('citizen_token', data.token);
        localStorage.setItem('citizen_name', data.user.username);
        showToast(`Registration complete! Welcome, ${data.user.username}.`, "success");
        
        document.getElementById('signup-form').reset();
        showMainApp();
    } catch(e) {
        console.error(e);
        showToast(e.message, "error");
    }
}

async function handleLogout() {
    const token = localStorage.getItem('citizen_token');
    if (token) {
        try {
            await fetch(`${API_BASE}/api/auth/logout`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` }
            });
        } catch(e) {
            console.error("Logout API error:", e);
        }
    }
    localStorage.removeItem('citizen_token');
    localStorage.removeItem('citizen_name');
    showToast("Signed out successfully.", "success");
    showAuthView();
}
