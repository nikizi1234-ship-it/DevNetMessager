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
// Проверка аутентификации
async function checkAuth() {
    console.log('DEBUG: Skipping complex auth check, showing login form immediately');
    
    // Временно отключаем проверку через API для тестирования регистрации
    // Просто показываем форму входа
    showLoginForm();
    return;
    
    /*
    // Резервный код для восстановления полноценной проверки позже:
    try {
        console.log('DEBUG: Starting auth check via /api/me');
        const response = await fetch('/api/me', {
            method: 'GET',
            credentials: 'include'
        });
        
        console.log('DEBUG: Auth check response status:', response.status, response.statusText);
        
        if (response.ok) {
            const data = await response.json();
            console.log('DEBUG: Auth successful, user data:', data);
            
            if (data.user && data.user.id) {
                currentUserId = data.user.id;
                currentUsername = data.user.username;
                
                document.getElementById('current-user').textContent = 
                    data.user.display_name || data.user.username;
                document.getElementById('auth-section').style.display = 'none';
                document.getElementById('chat-section').style.display = 'block';
                
                initializeChat();
                return;
            }
        }
        
        // Если мы здесь, значит пользователь не авторизован
        console.log('DEBUG: User not authenticated, showing login form');
        showLoginForm();
        
    } catch (error) {
        console.error('DEBUG: Auth check failed with error:', error);
        showLoginForm();
    }
    */
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
            
            // Проверяем тип data.detail перед вызовом .toLowerCase()
            if (data.detail) {
                if (typeof data.detail === 'string') {
                    errorMessage = data.detail;
                } else if (typeof data.detail === 'object') {
                    // Если это объект, преобразуем в строку
                    errorMessage = 'Ошибка валидации данных';
                }
            } else if (data.message && typeof data.message === 'string') {
                errorMessage = data.message;
            }
            
            showNotification(`❌ ${errorMessage}`, 'error');
        }
    } catch (error) {
        showNotification('❌ Ошибка подключения к серверу', 'error');
    }
}

// Регистрация
// Регистрация - ИСПРАВЛЕННАЯ ВЕРСИЯ
async function register(event) {
    if (event) event.preventDefault();
    
    const form = document.getElementById('register-form');
    const submitBtn = form.querySelector('button[type="submit"]');
    const originalBtnText = submitBtn.textContent;
    
    submitBtn.textContent = 'Регистрация...';
    submitBtn.disabled = true;
    
    try {
        // Собираем данные из формы в объект
        const formData = {
            username: form.querySelector('[name="username"]').value,
            email: form.querySelector('[name="email"]').value,
            password: form.querySelector('[name="password"]').value,
            display_name: form.querySelector('[name="displayName"]').value || null
        };
        
        console.log('DEBUG: Sending JSON data:', formData);
        
        const response = await fetch('/api/register', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            body: JSON.stringify(formData),
            credentials: 'include'
        });
        
        console.log('DEBUG: Response status:', response.status);
        
        let data;
        try {
            const text = await response.text();
            console.log('DEBUG: Response text:', text);
            data = text ? JSON.parse(text) : {};
        } catch (parseError) {
            console.error('DEBUG: JSON parse error:', parseError);
            data = { detail: 'Invalid server response' };
        }
        
        if (response.ok) {
            console.log('DEBUG: Registration successful!', data);
            
            // Показываем успешное сообщение
            const successMsg = document.createElement('div');
            successMsg.className = 'success-message';
            successMsg.innerHTML = '<strong>✅ Регистрация успешна!</strong><br>Вы будете перенаправлены...';
            successMsg.style.cssText = `
                background: #d4edda;
                color: #155724;
                padding: 15px;
                border-radius: 5px;
                margin: 10px 0;
                border: 1px solid #c3e6cb;
            `;
            
            form.parentNode.insertBefore(successMsg, form.nextSibling);
            
            // Перенаправление через 2 секунды
            setTimeout(() => {
                window.location.href = '/'; // или страница входа
            }, 2000);
            
        } else {
            // Обработка ошибки
            console.log('DEBUG: Registration failed:', data);
            
            let errorMessage = 'Ошибка регистрации';
            
            // Извлекаем сообщение об ошибке
            if (data.detail) {
                // Проверяем тип data.detail
                if (typeof data.detail === 'string') {
                    errorMessage = data.detail;
                } else if (Array.isArray(data.detail) && data.detail.length > 0) {
                    // Обработка Pydantic ошибок валидации
                    const error = data.detail[0];
                    if (error.msg) {
                        errorMessage = error.msg;
                        
                        // Добавляем локацию если есть
                        if (error.loc && error.loc.length > 0) {
                            const field = error.loc[error.loc.length - 1];
                            errorMessage = `Поле "${field}": ${error.msg}`;
                        }
                    }
                } else if (typeof data.detail === 'object') {
                    // Если это объект, пытаемся извлечь сообщение
                    errorMessage = 'Ошибка валидации данных';
                }
            } else if (data.message && typeof data.message === 'string') {
                errorMessage = data.message;
            }
            
            // Показываем ошибку
            alert(`❌ Ошибка: ${errorMessage}`);
        }
        
    } catch (error) {
        console.error('DEBUG: Fetch error:', error);
        alert('❌ Ошибка сети при регистрации');
    } finally {
        submitBtn.textContent = originalBtnText;
        submitBtn.disabled = false;
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
