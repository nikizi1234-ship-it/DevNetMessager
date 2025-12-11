// WebSocket соединение
let websocket = null;
let currentUserId = null;
let currentUsername = null;

// Инициализация приложения
document.addEventListener('DOMContentLoaded', function() {
    checkAuth();
    setupEventListeners();
});

// Проверка аутентификации
async function checkAuth() {
    try {
        const response = await fetch('/api/me', {
            credentials: 'include'
        });
        
        if (response.ok) {
            const userData = await response.json();
            currentUserId = userData.id;
            currentUsername = userData.username;
            
            document.getElementById('current-user').textContent = userData.display_name || userData.username;
            document.getElementById('auth-section').style.display = 'none';
            document.getElementById('chat-section').style.display = 'block';
            
            initializeChat();
        } else {
            showLoginForm();
        }
    } catch (error) {
        console.error('Auth check failed:', error);
        showLoginForm();
    }
}

// Показать форму входа
function showLoginForm() {
    document.getElementById('auth-section').style.display = 'block';
    document.getElementById('chat-section').style.display = 'none';
}

// Настройка обработчиков событий
function setupEventListeners() {
    // Форма входа
    document.getElementById('login-form').addEventListener('submit', async function(e) {
        e.preventDefault();
        await login();
    });
    
    // Форма регистрации
    document.getElementById('register-form').addEventListener('submit', async function(e) {
        e.preventDefault();
        await register();
    });
    
    // Переключение между формами
    document.getElementById('show-register').addEventListener('click', function() {
        document.getElementById('login-form').style.display = 'none';
        document.getElementById('register-form').style.display = 'block';
    });
    
    document.getElementById('show-login').addEventListener('click', function() {
        document.getElementById('register-form').style.display = 'none';
        document.getElementById('login-form').style.display = 'block';
    });
    
    // Выход
    document.getElementById('logout-btn').addEventListener('click', logout);
}

// Вход в систему
async function login() {
    const formData = new FormData(document.getElementById('login-form'));
    
    try {
        const response = await fetch('/api/login', {
            method: 'POST',
            body: formData,
            credentials: 'include'
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showNotification('✅ Вход выполнен успешно!', 'success');
            setTimeout(() => {
                window.location.reload();
            }, 1000);
        } else {
            // Исправленная обработка ошибки
            let errorMessage = 'Ошибка входа';
            if (data.detail) {
                if (typeof data.detail === 'string') {
                    errorMessage = data.detail;
                } else if (typeof data.detail === 'object') {
                    errorMessage = JSON.stringify(data.detail);
                }
            } else if (data.message) {
                errorMessage = data.message;
            }
            let errorMessage = 'Ошибка регистрации';
            if (data.detail && typeof data.detail === 'string') {
                errorMessage = data.detail;
            } else if (data.message && typeof data.message === 'string') {
                errorMessage = data.message;
            } else if (data.detail && typeof data.detail === 'object') {
                errorMessage = 'Ошибка валидации данных';
            }
            showNotification(`❌ ${errorMessage}`, 'error');
        }
    } catch (error) {
        showNotification('❌ Ошибка подключения к серверу', 'error');
    }
}

// Регистрация
async function register() {
    const formData = new FormData(document.getElementById('register-form'));
    
    try {
        const response = await fetch('/api/register', {
            method: 'POST',
            body: formData,
            credentials: 'include'
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showNotification('✅ Регистрация успешна!', 'success');
            setTimeout(() => {
                window.location.reload();
            }, 1000);
        } else {
            // Исправленная обработка ошибки
            let errorMessage = 'Ошибка регистрации';
            if (data.detail) {
                if (typeof data.detail === 'string') {
                    errorMessage = data.detail;
                } else if (typeof data.detail === 'object') {
                    errorMessage = JSON.stringify(data.detail);
                }
            } else if (data.message) {
                errorMessage = data.message;
            }
            showNotification(`❌ ${errorMessage}`, 'error');
        }
    } catch (error) {
        showNotification('❌ Ошибка подключения к серверу', 'error');
    }
}

// Выход из системы
async function logout() {
    try {
        await fetch('/api/logout', {
            method: 'POST',
            credentials: 'include'
        });
        
        showNotification('✅ Выход выполнен успешно!', 'success');
        setTimeout(() => {
            window.location.reload();
        }, 1000);
    } catch (error) {
        console.error('Logout error:', error);
    }
}

// Инициализация чата
async function initializeChat() {
    await loadUsers();
    connectWebSocket();
    
    // Загрузка чатов при открытии
    document.getElementById('load-chats').addEventListener('click', loadChats);
}

// Подключение к WebSocket
function connectWebSocket() {
    if (!currentUserId) return;
    
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/${currentUserId}`;
    
    websocket = new WebSocket(wsUrl);
    
    websocket.onopen = function() {
        console.log('WebSocket connected');
        showNotification('✅ Подключено к чату', 'success');
    };
    
    websocket.onmessage = function(event) {
        const messageData = JSON.parse(event.data);
        handleWebSocketMessage(messageData);
    };
    
    websocket.onclose = function() {
        console.log('WebSocket disconnected');
        showNotification('❌ Соединение потеряно. Переподключение...', 'warning');
        setTimeout(connectWebSocket, 3000);
    };
    
    websocket.onerror = function(error) {
        console.error('WebSocket error:', error);
        showNotification('❌ Ошибка подключения к серверу', 'error');
    };
}

// Обработка WebSocket сообщений
function handleWebSocketMessage(messageData) {
    if (messageData.type === 'message') {
        displayMessage(messageData, messageData.from_user_id === currentUserId);
    } else if (messageData.type === 'message_sent') {
        console.log('✅ Message sent successfully');
    } else if (messageData.type === 'error') {
        showNotification(`❌ ${messageData.message}`, 'error');
    } else if (messageData.type === 'chat_deleted') {
        showNotification('💬 История чата была удалена', 'info');
        // Перезагружаем текущий чат если нужно
    }
}

// Загрузка пользователей
async function loadUsers() {
    try {
        const response = await fetch('/api/users', {
            credentials: 'include'
        });
        
        if (response.ok) {
            const data = await response.json();
            displayUsers(data.users);
        }
    } catch (error) {
        console.error('Error loading users:', error);
    }
}

// Отображение пользователей
function displayUsers(users) {
    const usersList = document.getElementById('users-list');
    usersList.innerHTML = '';
    
    users.forEach(user => {
        const userElement = document.createElement('div');
        userElement.className = `user-item ${user.is_online ? 'online' : 'offline'}`;
        userElement.innerHTML = `
            <div class="user-avatar">${user.display_name.charAt(0)}</div>
            <div class="user-info">
                <div class="user-name">${user.display_name}</div>
                <div class="user-status">${user.is_online ? '🟢 Online' : '⚫ Offline'}</div>
            </div>
            <button class="chat-btn" onclick="startChat(${user.id})">💬</button>
        `;
        usersList.appendChild(userElement);
    });
}

// Начать чат с пользователем
function startChat(userId) {
    // Здесь можно реализовать логику открытия чата с конкретным пользователем
    showNotification(`💬 Начат чат с пользователем ID: ${userId}`, 'info');
}

// Отправка сообщения
function sendMessage() {
    const input = document.getElementById('messageInput');
    const content = input.value.trim();
    
    if (content && websocket && websocket.readyState === WebSocket.OPEN) {
        // В реальном приложении здесь будет ID выбранного пользователя
        const toUserId = currentUserId === 1 ? 2 : 1;
        
        const messageData = {
            to_user_id: toUserId,
            content: content,
            type: 'text'
        };
        
        websocket.send(JSON.stringify(messageData));
        input.value = '';
        
        // Показываем сообщение сразу
        displayMessage({
            from_user_id: currentUserId,
            content: content,
            timestamp: new Date().toISOString()
        }, true);
    } else if (!websocket || websocket.readyState !== WebSocket.OPEN) {
        showNotification('❌ Нет соединения с сервером', 'error');
    }
}

// Отображение сообщения
function displayMessage(messageData, isOwn) {
    const messagesDiv = document.getElementById('messages');
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${isOwn ? 'own' : 'other'}`;
    
    const time = new Date(messageData.timestamp).toLocaleTimeString();
    messageDiv.innerHTML = `
        <div class="message-content">${escapeHtml(messageData.content)}</div>
        <small class="message-time">${time}</small>
    `;
    
    messagesDiv.appendChild(messageDiv);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

// Утилиты
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showNotification(message, type) {
    // Простая реализация уведомлений
    console.log(`${type}: ${message}`);
    // Можно добавить красивые toast уведомления
}

// Отправка по Enter
document.getElementById('messageInput').addEventListener('keypress', function(e) {
    if (e.key === 'Enter') {
        sendMessage();
    }
});
