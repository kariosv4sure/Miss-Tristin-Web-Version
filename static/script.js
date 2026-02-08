// ===== GLOBAL STATE =====
let currentTheme = localStorage.getItem('theme') || 'light';
let chatHistory = JSON.parse(localStorage.getItem('chatHistory')) || [];

// ===== MOBILE MENU =====
function initMobileMenu() {
    const mobileMenuBtn = document.getElementById('mobileMenuBtn');
    const navLinks = document.getElementById('navLinks');
    
    if (mobileMenuBtn && navLinks) {
        mobileMenuBtn.addEventListener('click', () => {
            navLinks.classList.toggle('active');
            const icon = mobileMenuBtn.querySelector('i');
            if (icon) {
                icon.classList.toggle('fa-bars');
                icon.classList.toggle('fa-times');
            }
        });
        
        // Close menu when clicking on a link
        document.querySelectorAll('.nav-link').forEach(link => {
            link.addEventListener('click', () => {
                navLinks.classList.remove('active');
                const icon = mobileMenuBtn.querySelector('i');
                if (icon) {
                    icon.classList.remove('fa-times');
                    icon.classList.add('fa-bars');
                }
            });
        });
        
        // Close menu when clicking outside
        document.addEventListener('click', (e) => {
            if (!navLinks.contains(e.target) && !mobileMenuBtn.contains(e.target)) {
                navLinks.classList.remove('active');
                const icon = mobileMenuBtn.querySelector('i');
                if (icon) {
                    icon.classList.remove('fa-times');
                    icon.classList.add('fa-bars');
                }
            }
        });
    }
}

// ===== THEME TOGGLE =====
function initTheme() {
    document.body.classList.toggle('dark-mode', currentTheme === 'dark');
    updateThemeIcons();
    updateCSSVariables();
}

function toggleTheme() {
    currentTheme = currentTheme === 'light' ? 'dark' : 'light';
    document.body.classList.toggle('dark-mode');
    localStorage.setItem('theme', currentTheme);
    updateThemeIcons();
    updateCSSVariables();
    
    // Show theme change animation
    const body = document.body;
    body.style.transition = 'none';
    setTimeout(() => {
        body.style.transition = '';
    }, 10);
}

function updateThemeIcons() {
    const themeToggle = document.querySelector('.theme-toggle');
    if (themeToggle) {
        const sunIcon = themeToggle.querySelector('.fa-sun');
        const moonIcon = themeToggle.querySelector('.fa-moon');
        const circle = themeToggle.querySelector('.toggle-circle');
        
        if (circle) {
            circle.style.transform = currentTheme === 'dark' 
                ? 'translateX(calc(100% - 28px))' 
                : 'translateX(4px)';
        }
        
        // Update icon opacities
        if (sunIcon && moonIcon) {
            if (currentTheme === 'dark') {
                sunIcon.style.opacity = '1';
                moonIcon.style.opacity = '0';
            } else {
                sunIcon.style.opacity = '0';
                moonIcon.style.opacity = '1';
            }
        }
    }
}

function updateCSSVariables() {
    const root = document.documentElement;
    if (currentTheme === 'dark') {
        root.style.setProperty('--light-mode-icon-opacity', '0');
        root.style.setProperty('--dark-mode-icon-opacity', '1');
    } else {
        root.style.setProperty('--light-mode-icon-opacity', '1');
        root.style.setProperty('--dark-mode-icon-opacity', '0');
    }
}

// ===== CHAT FUNCTIONS =====
function initChat() {
    const sendBtn = document.getElementById('sendBtn');
    const messageInput = document.getElementById('messageInput');
    const quickActions = document.querySelectorAll('.quick-btn');
    const clearChatBtn = document.querySelector('.clear-chat-btn');

    if (sendBtn && messageInput) {
        sendBtn.addEventListener('click', sendMessage);
        messageInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
        
        // Auto-resize input
        messageInput.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = (this.scrollHeight) + 'px';
        });
    }

    if (clearChatBtn) {
        clearChatBtn.addEventListener('click', clearChatHistory);
    }

    quickActions.forEach(btn => {
        btn.addEventListener('click', () => {
            const text = btn.textContent;
            if (messageInput) {
                messageInput.value = text;
                sendMessage();
            }
        });
    });

    loadChatHistory();
}

async function sendMessage() {
    const input = document.getElementById('messageInput');
    const message = input.value.trim();
    const sendBtn = document.getElementById('sendBtn');

    if (!message) return;

    // Clear input and disable button
    input.value = '';
    input.style.height = 'auto';
    if (sendBtn) sendBtn.disabled = true;

    // Add user message
    addMessage('user', message);

    // Show typing indicator
    showTyping();

    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: message })
        });

        const data = await response.json();
        hideTyping();

        if (data.success) {
            addMessage('ai', data.response);
            saveToHistory('user', message);
            saveToHistory('ai', data.response);
        } else {
            addMessage('error', data.error || 'Oops! Something went wrong 😅');
        }
    } catch (error) {
        hideTyping();
        addMessage('error', 'Network error. Check your connection and try again! 🌐');
        console.error('Error:', error);
    } finally {
        if (sendBtn) sendBtn.disabled = false;
        input.focus();
    }
}

function addMessage(sender, text) {
    const container = document.getElementById('messagesContainer');
    if (!container) return;

    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${sender}`;

    const time = new Date().toLocaleTimeString([], { 
        hour: '2-digit', 
        minute: '2-digit',
        hour12: true 
    });

    if (sender === 'ai') {
        messageDiv.innerHTML = `
            <div class="message-avatar">💅</div>
            <div class="message-bubble">
                <div class="message-text">${formatMessage(text)}</div>
                <div class="message-time">${time}</div>
            </div>
        `;
    } else if (sender === 'user') {
        messageDiv.innerHTML = `
            <div class="message-bubble">
                <div class="message-text">${formatMessage(text)}</div>
                <div class="message-time">${time}</div>
            </div>
            <div class="message-avatar">👤</div>
        `;
    } else {
        // Error message
        messageDiv.innerHTML = `
            <div class="message-bubble" style="background: #FEE2E2; border-left: 4px solid #EF4444; color: #991B1B;">
                <div class="message-text">${text}</div>
                <div class="message-time">${time}</div>
            </div>
        `;
        messageDiv.style.justifyContent = 'center';
        messageDiv.style.margin = '1rem 0';
    }

    container.appendChild(messageDiv);
    scrollToBottom();
}

function formatMessage(text) {
    // Convert markdown-like formatting
    let formatted = text
        .replace(/\n/g, '<br>')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/__(.*?)__/g, '<u>$1</u>')
        .replace(/~~(.*?)~~/g, '<del>$1</del>')
        .replace(/(https?:\/\/[^\s]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer" class="link">$1</a>')
        .replace(/`([^`]+)`/g, '<code>$1</code>');

    // Make @mentions clickable
    formatted = formatted.replace(/@(\w+)/g, '<span class="mention">@$1</span>');

    return formatted;
}

function showTyping() {
    const container = document.getElementById('messagesContainer');
    if (!container) return;

    const typingDiv = document.createElement('div');
    typingDiv.className = 'message ai';
    typingDiv.id = 'typingIndicator';

    typingDiv.innerHTML = `
        <div class="message-avatar">💅</div>
        <div class="message-bubble">
            <div class="typing-indicator">
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
            </div>
        </div>
    `;

    container.appendChild(typingDiv);
    scrollToBottom();
}

function hideTyping() {
    const typing = document.getElementById('typingIndicator');
    if (typing) typing.remove();
}

function scrollToBottom() {
    const container = document.getElementById('messagesContainer');
    if (container) {
        container.scrollTop = container.scrollHeight;
    }
}

// ===== CHAT HISTORY =====
function saveToHistory(sender, message) {
    chatHistory.push({
        sender,
        message,
        time: new Date().toISOString()
    });

    // Keep only last 100 messages
    if (chatHistory.length > 100) {
        chatHistory = chatHistory.slice(-100);
    }

    localStorage.setItem('chatHistory', JSON.stringify(chatHistory));
}

function loadChatHistory() {
    const container = document.getElementById('messagesContainer');
    if (!container || chatHistory.length === 0) return;

    // Clear existing messages except welcome
    const welcomeMsg = container.querySelector('.message.ai:first-child');
    container.innerHTML = '';
    if (welcomeMsg) container.appendChild(welcomeMsg);

    // Load history
    chatHistory.forEach(item => {
        if (item.sender !== 'error') {
            addMessage(item.sender, item.message);
        }
    });

    scrollToBottom();
}

function clearChatHistory() {
    if (confirm('Clear all chat history? All our fabulous conversation will be gone! 💔')) {
        chatHistory = [];
        localStorage.removeItem('chatHistory');

        const container = document.getElementById('messagesContainer');
        if (container) {
            const welcomeMsg = container.querySelector('.message.ai:first-child');
            container.innerHTML = '';
            if (welcomeMsg) container.appendChild(welcomeMsg);
            addMessage('ai', 'Chat cleared. What now? Hope you brought your A-game 😏');
        }
    }
}

// ===== INITIALIZATION =====
document.addEventListener('DOMContentLoaded', () => {
    // Initialize theme
    initTheme();

    // Initialize mobile menu
    initMobileMenu();

    // Initialize theme toggle button
    const themeToggle = document.querySelector('.theme-toggle');
    if (themeToggle) {
        themeToggle.addEventListener('click', toggleTheme);
    }

    // Initialize chat if on chat page
    if (document.getElementById('messagesContainer')) {
        initChat();
    }

    // Set active nav link
    const currentPath = window.location.pathname;
    document.querySelectorAll('.nav-link').forEach(link => {
        if (link.getAttribute('href') === currentPath) {
            link.classList.add('active');
        }
    });

    // Add animation to feature cards on scroll
    const observerOptions = {
        threshold: 0.1,
        rootMargin: '0px 0px -50px 0px'
    };

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('animated');
            }
        });
    }, observerOptions);

    document.querySelectorAll('.feature-card, .creator-card').forEach(card => {
        observer.observe(card);
    });
});

// ===== KEYBOARD SHORTCUTS =====
document.addEventListener('keydown', (e) => {
    // Ctrl/Cmd + K to focus chat input
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        const input = document.getElementById('messageInput');
        if (input) input.focus();
    }
    
    // Esc to clear input
    if (e.key === 'Escape') {
        const input = document.getElementById('messageInput');
        if (input) input.value = '';
    }
    
    // Ctrl/Cmd + / to toggle theme
    if ((e.ctrlKey || e.metaKey) && e.key === '/') {
        e.preventDefault();
        toggleTheme();
    }
});
