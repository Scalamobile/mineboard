// MineBoard - Enhanced JavaScript Common Functions

// Enhanced notification system
function showNotification(message, type = 'success', duration = 4000) {
    const notification = document.getElementById('notification');
    if (!notification) return;
    
    // Remove existing classes
    notification.className = 'notification';
    
    // Create notification content with icon
    const icons = {
        success: 'fas fa-check-circle',
        error: 'fas fa-exclamation-triangle',
        warning: 'fas fa-exclamation-circle',
        info: 'fas fa-info-circle'
    };
    
    notification.innerHTML = `
        <div class="flex items-center gap-3">
            <i class="${icons[type] || icons.info}"></i>
            <span>${message}</span>
        </div>
    `;
    
    notification.classList.add(type, 'show');
    
    // Auto-hide notification
    setTimeout(() => {
        notification.classList.remove('show');
    }, duration);
}

// Enhanced custom start panel with better UI
async function initCustomStartPanel(serverName) {
    const container = document.querySelector('.container') || document.body;

    const card = document.createElement('div');
    card.className = 'card';
    card.style.marginTop = 'var(--space-6)';
    card.style.maxWidth = '900px';
    card.innerHTML = `
        <div class="card-header">
            <div class="card-title">
                <i class="fas fa-terminal"></i>
                <h2>Custom Startup Configuration</h2>
            </div>
        </div>
        <div class="card-body">
            <div class="form-group">
                <div class="flex items-center gap-3 mb-4">
                    <div class="flex items-center">
                        <input type="checkbox" id="use_custom_start_cb" class="w-5 h-5 text-primary-600 bg-primary border-primary-300 rounded focus:ring-primary-500">
                        <label for="use_custom_start_cb" class="ml-3 font-medium text-primary">
                            Use custom startup command
                        </label>
                    </div>
                </div>
            </div>
            
            <div class="form-group">
                <label for="custom_start_cmd_ta" class="flex items-center gap-2 mb-3">
                    <i class="fas fa-code text-primary-500"></i>
                    Startup Command
                </label>
                <textarea 
                    id="custom_start_cmd_ta" 
                    rows="4" 
                    placeholder="Example: java -Xmx2G -Xms2G -jar server.jar nogui"
                    class="form-control font-mono text-sm"
                ></textarea>
                
                <div class="mt-4 bg-tertiary rounded-lg p-4 border border-primary">
                    <div class="flex items-start gap-3">
                        <i class="fas fa-info-circle text-info-500 mt-1"></i>
                        <div class="text-sm text-secondary">
                            <div class="font-medium mb-2">Configuration Notes:</div>
                            <ul class="space-y-1 list-disc list-inside">
                                <li>Command executes in server directory: <code class="bg-secondary px-1 rounded">servers/${serverName}/</code></li>
                                <li>When enabled, runs as shell script with <code class="bg-secondary px-1 rounded">shell=true</code></li>
                                <li>Server logs are saved to: <code class="bg-secondary px-1 rounded">logs/${serverName}.log</code></li>
                                <li>Use full Java paths if needed for compatibility</li>
                            </ul>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="flex gap-3 justify-start">
                <button id="save_custom_start_btn" class="btn btn-success">
                    <i class="fas fa-save"></i> Save Configuration
                </button>
                <button id="test_custom_start_btn" class="btn btn-secondary">
                    <i class="fas fa-flask"></i> Test Command
                </button>
            </div>
        </div>
    `;

    container.appendChild(card);

    // Load current configuration with loading state
    try {
        const saveBtn = document.getElementById('save_custom_start_btn');
        const testBtn = document.getElementById('test_custom_start_btn');
        
        saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Loading...';
        saveBtn.disabled = true;
        
        const data = await apiCall(`/api/servers/${encodeURIComponent(serverName)}/config`);
        const cfg = (data && data.config) || {};
        
        document.getElementById('use_custom_start_cb').checked = !!cfg.use_custom_start;
        document.getElementById('custom_start_cmd_ta').value = cfg.custom_start_cmd || '';
        
        saveBtn.innerHTML = '<i class="fas fa-save"></i> Save Configuration';
        saveBtn.disabled = false;
    } catch (e) {
        showNotification('Failed to load configuration', 'error');
    }

    // Enhanced save functionality
    const saveBtn = document.getElementById('save_custom_start_btn');
    saveBtn.addEventListener('click', async () => {
        const useCustom = document.getElementById('use_custom_start_cb').checked;
        const cmd = document.getElementById('custom_start_cmd_ta').value.trim();
        
        if (useCustom && !cmd) {
            showNotification('Please enter a startup command', 'warning');
            return;
        }
        
        const originalHtml = saveBtn.innerHTML;
        saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';
        saveBtn.disabled = true;
        
        try {
            const res = await apiCall(`/api/servers/${encodeURIComponent(serverName)}/config`, {
                method: 'POST',
                body: JSON.stringify({ 
                    use_custom_start: useCustom, 
                    custom_start_cmd: cmd 
                })
            });
            showNotification(res.message || 'Configuration saved successfully', 'success');
        } catch (e) {
            showNotification('Failed to save configuration', 'error');
        } finally {
            saveBtn.innerHTML = originalHtml;
            saveBtn.disabled = false;
        }
    });

    // Test command functionality
    const testBtn = document.getElementById('test_custom_start_btn');
    testBtn.addEventListener('click', () => {
        const cmd = document.getElementById('custom_start_cmd_ta').value.trim();
        if (!cmd) {
            showNotification('Please enter a command to test', 'warning');
            return;
        }
        
        // Basic validation
        if (!cmd.includes('java')) {
            showNotification('Command should typically include "java"', 'warning');
        } else if (!cmd.includes('.jar')) {
            showNotification('Command should typically include a .jar file', 'warning');
        } else {
            showNotification('Command syntax looks valid', 'success');
        }
    });
}

// Enhanced utility functions
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function formatDate(timestamp) {
    const date = new Date(timestamp);
    return date.toLocaleString('it-IT', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });
}

function formatUptime(seconds) {
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    
    if (days > 0) return `${days}d ${hours}h ${minutes}m`;
    if (hours > 0) return `${hours}h ${minutes}m`;
    return `${minutes}m`;
}

// Enhanced API call function with better error handling
async function apiCall(url, options = {}) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 10000); // 10s timeout
    
    try {
        const response = await fetch(url, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            signal: controller.signal,
            ...options
        });
        
        clearTimeout(timeoutId);
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.message || `HTTP ${response.status}: ${response.statusText}`);
        }
        
        return data;
    } catch (error) {
        clearTimeout(timeoutId);
        
        if (error.name === 'AbortError') {
            const timeoutError = new Error('Request timeout - server may be busy');
            console.error('API Timeout:', url, timeoutError);
            showNotification('Request timeout - please try again', 'error');
            throw timeoutError;
        }
        
        console.error('API Error:', url, error);
        showNotification(error.message || 'Network error occurred', 'error');
        throw error;
    }
}

// Enhanced tab management with animations
function initTabs() {
    const tabs = document.querySelectorAll('.nav-tab');
    const contents = document.querySelectorAll('.tab-content');
    
    tabs.forEach(tab => {
        tab.addEventListener('click', (e) => {
            e.preventDefault();
            const targetId = tab.getAttribute('data-tab');
            
            // Remove active from all tabs and contents
            tabs.forEach(t => t.classList.remove('active'));
            contents.forEach(c => {
                c.classList.remove('active');
                c.style.display = 'none';
            });
            
            // Add active to clicked tab
            tab.classList.add('active');
            
            // Show target content with animation
            const targetContent = document.getElementById(targetId);
            if (targetContent) {
                targetContent.style.display = 'block';
                // Trigger reflow for animation
                targetContent.offsetHeight;
                targetContent.classList.add('active');
            }
        });
    });
}

// Enhanced theme switcher with system preference detection
function initThemeSwitcher() {
    const themeToggle = document.getElementById('theme-toggle');
    if (!themeToggle) return;

    // Check for system preference
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const savedTheme = localStorage.getItem('theme');
    const currentTheme = savedTheme || (prefersDark ? 'dark' : 'light');
    
    // Apply theme
    document.body.classList.toggle('dark-mode', currentTheme === 'dark');
    themeToggle.checked = currentTheme === 'dark';

    // Listen for changes
    themeToggle.addEventListener('change', function() {
        const isDarkMode = this.checked;
        document.body.classList.toggle('dark-mode', isDarkMode);
        localStorage.setItem('theme', isDarkMode ? 'dark' : 'light');
        
        // Smooth transition
        document.body.style.transition = 'background-color 0.3s ease, color 0.3s ease';
        setTimeout(() => {
            document.body.style.transition = '';
        }, 300);
        
        showNotification(`Switched to ${isDarkMode ? 'dark' : 'light'} theme`, 'info', 2000);
    });

    // Listen for system theme changes
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
        if (!localStorage.getItem('theme')) {
            document.body.classList.toggle('dark-mode', e.matches);
            themeToggle.checked = e.matches;
        }
    });
}

// Enhanced modal management
function initModals() {
    const modals = document.querySelectorAll('.modal');
    
    modals.forEach(modal => {
        const closeBtn = modal.querySelector('.close');
        
        if (closeBtn) {
            closeBtn.addEventListener('click', () => closeModal(modal));
        }
        
        // Close on backdrop click
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                closeModal(modal);
            }
        });
        
        // Close on Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && modal.style.display === 'block') {
                closeModal(modal);
            }
        });
    });
}

function openModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.style.display = 'block';
        document.body.style.overflow = 'hidden';
        
        // Focus management
        const firstFocusable = modal.querySelector('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
        if (firstFocusable) {
            firstFocusable.focus();
        }
    }
}

function closeModal(modal) {
    if (typeof modal === 'string') {
        modal = document.getElementById(modal);
    }
    
    if (modal) {
        modal.style.display = 'none';
        document.body.style.overflow = '';
    }
}

// Enhanced loading states
function showLoading(element, text = 'Loading...') {
    if (typeof element === 'string') {
        element = document.getElementById(element);
    }
    
    if (element) {
        element.innerHTML = `
            <div class="loading">
                <i class="fas fa-spinner"></i>
                <span>${text}</span>
            </div>
        `;
    }
}

function hideLoading(element, content = '') {
    if (typeof element === 'string') {
        element = document.getElementById(element);
    }
    
    if (element) {
        element.innerHTML = content;
    }
}

// Enhanced form validation
function validateForm(formElement) {
    const inputs = formElement.querySelectorAll('input[required], select[required], textarea[required]');
    let isValid = true;
    
    inputs.forEach(input => {
        const value = input.value.trim();
        const errorElement = input.parentNode.querySelector('.error-message');
        
        // Remove existing error
        if (errorElement) {
            errorElement.remove();
        }
        
        input.classList.remove('error');
        
        if (!value) {
            isValid = false;
            input.classList.add('error');
            
            const error = document.createElement('div');
            error.className = 'error-message text-danger-500 text-sm mt-1';
            error.textContent = `${input.labels[0]?.textContent || 'This field'} is required`;
            input.parentNode.appendChild(error);
        }
    });
    
    return isValid;
}

// Performance monitoring
function measurePerformance(name, fn) {
    return async function(...args) {
        const start = performance.now();
        try {
            const result = await fn.apply(this, args);
            const end = performance.now();
            console.log(`${name} took ${(end - start).toFixed(2)}ms`);
            return result;
        } catch (error) {
            const end = performance.now();
            console.error(`${name} failed after ${(end - start).toFixed(2)}ms:`, error);
            throw error;
        }
    };
}

// Enhanced initialization
document.addEventListener('DOMContentLoaded', function() {
    // Initialize all components
    initTabs();
    initThemeSwitcher();
    initModals();
    
    // Add notification container if not exists
    if (!document.getElementById('notification')) {
        const notification = document.createElement('div');
        notification.id = 'notification';
        document.body.appendChild(notification);
    }

    // Initialize custom start panel for server detail pages
    try {
        const pathMatch = window.location.pathname.match(/^\/servers\/([^\/]+)\/?$/);
        if (pathMatch && pathMatch[1]) {
            const serverName = decodeURIComponent(pathMatch[1]);
            initCustomStartPanel(serverName);
        }
    } catch (e) {
        console.warn('Failed to initialize custom start panel:', e);
    }

    // Add smooth scrolling to all anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                target.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        });
    });

    // Add loading states to all forms
    document.querySelectorAll('form').forEach(form => {
        form.addEventListener('submit', function(e) {
            const submitBtn = form.querySelector('button[type="submit"]');
            if (submitBtn && !submitBtn.disabled) {
                const originalText = submitBtn.innerHTML;
                submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Processing...';
                submitBtn.disabled = true;
                
                // Re-enable after 5 seconds as fallback
                setTimeout(() => {
                    if (submitBtn.disabled) {
                        submitBtn.innerHTML = originalText;
                        submitBtn.disabled = false;
                    }
                }, 5000);
            }
        });
    });

    // Add ripple effect to buttons
    document.querySelectorAll('.btn').forEach(button => {
        button.addEventListener('click', function(e) {
            const ripple = document.createElement('span');
            const rect = this.getBoundingClientRect();
            const size = Math.max(rect.width, rect.height);
            const x = e.clientX - rect.left - size / 2;
            const y = e.clientY - rect.top - size / 2;
            
            ripple.style.cssText = `
                position: absolute;
                width: ${size}px;
                height: ${size}px;
                left: ${x}px;
                top: ${y}px;
                background: rgba(255, 255, 255, 0.3);
                border-radius: 50%;
                transform: scale(0);
                animation: ripple 0.6s linear;
                pointer-events: none;
            `;
            
            this.style.position = 'relative';
            this.style.overflow = 'hidden';
            this.appendChild(ripple);
            
            setTimeout(() => {
                ripple.remove();
            }, 600);
        });
    });

    // Add CSS for ripple animation
    if (!document.querySelector('#ripple-styles')) {
        const style = document.createElement('style');
        style.id = 'ripple-styles';
        style.textContent = `
            @keyframes ripple {
                to {
                    transform: scale(4);
                    opacity: 0;
                }
            }
        `;
        document.head.appendChild(style);
    }

    console.log('MineBoard UI initialized successfully');
});

// Export functions for global use
window.MineBoard = {
    showNotification,
    apiCall,
    formatFileSize,
    formatDate,
    formatUptime,
    openModal,
    closeModal,
    showLoading,
    hideLoading,
    validateForm,
    measurePerformance
};