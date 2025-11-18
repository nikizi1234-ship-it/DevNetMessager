// Получаем параметры из URL
const urlParams = new URLSearchParams(window.location.search);
const currentUserId = parseInt(urlParams.get('user_id') || '1');
const otherUserId = currentUserId === 1 ? 2 : 1;

// WebSocket соединение
let websocket = null;

// Инициализация чата
document.addEventListener('DOMContentLoaded', function() {
    document.getElementById('current-user').textContent = `User ${currentUserId}`;
    connectWebSocket();
    loadMessageHistory();
});

// Получение cookie
function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
    return null;
}

// Подключение к WebSocket
function connectWebSocket() {
    const token = getCookie('access_token');
    
    if (!token) {
        console.error('No access token found');
        addSystemMessage('❌ Требуется авторизация. Пожалуйста, войдите в систему.');
        return;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;
    
    websocket = new WebSocket(wsUrl);
    
    websocket.onopen = function() {
        console.log('WebSocket connected');
        // Отправляем аутентификацию
        websocket.send(JSON.stringify({
            type: 'auth',
            token: token
        }));
    };
    
    websocket.onmessage = function(event) {
        const data = JSON.parse(event.data);
        handleWebSocketMessage(data);
    };
    
    websocket.onclose = function() {
        console.log('WebSocket disconnected');
        addSystemMessage('❌ Соединение потеряно. Переподключение...');
        setTimeout(connectWebSocket, 3000);
    };
    
    websocket.onerror = function(error) {
        console.error('WebSocket error:', error);
        addSystemMessage('❌ Ошибка подключения к серверу');
    };
}

// Обработка входящих WebSocket сообщений
function handleWebSocketMessage(data) {
    console.log('WebSocket message received:', data);
    
    switch (data.type) {
        case 'auth_success':
            console.log('✅ WebSocket authenticated successfully');
            addSystemMessage('✅ Подключено к чату');
            break;
            
        case 'message':
            displayMessage({
                from_user_id: data.from_user_id,
                content: data.content,
                timestamp: data.timestamp
            }, data.from_user_id === currentUserId);
            break;
            
        case 'message_sent':
            console.log('✅ Message sent successfully');
            // Можно обновить статус сообщения если нужно
            break;
            
        case 'error':
            console.error('WebSocket error:', data.message);
            addSystemMessage(`❌ Ошибка: ${data.message}`);
            break;
            
        case 'chat_deleted':
            addSystemMessage('💬 История чата была удалена');
            // Перезагружаем историю сообщений
            loadMessageHistory();
            break;
            
        default:
            console.log('Unknown message type:', data.type);
    }
}

// Загрузка истории сообщений
async function loadMessageHistory() {
    try {
        const response = await fetch(`/api/messages/${otherUserId}`, {
            credentials: 'include' // Важно для отправки cookies
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const messages = await response.json();
        
        // Очищаем чат перед загрузкой истории
        document.getElementById('messages').innerHTML = '';
        
        messages.forEach(msg => {
            displayMessage(msg, msg.from_user_id === currentUserId);
        });
    } catch (error) {
        console.error('Error loading message history:', error);
        addSystemMessage('❌ Ошибка загрузки истории сообщений');
    }
}

// Отправка сообщения
function sendMessage() {
    const input = document.getElementById('messageInput');
    const content = input.value.trim();
    
    if (!content) {
        return;
    }
    
    if (!websocket || websocket.readyState !== WebSocket.OPEN) {
        addSystemMessage('❌ Нет соединения с сервером');
        return;
    }
    
    const messageData = {
        type: 'message',
        to_user_id: otherUserId,
        content: content,
        message_type: 'text'
    };
    
    try {
        websocket.send(JSON.stringify(messageData));
        input.value = '';
        
        // Показываем сообщение сразу (optimistic update)
        displayMessage({
            from_user_id: currentUserId,
            content: content,
            timestamp: new Date().toISOString()
        }, true);
    } catch (error) {
        console.error('Error sending message:', error);
        addSystemMessage('❌ Ошибка отправки сообщения');
    }
}

// Отправка по Enter
document.getElementById('messageInput').addEventListener('keypress', function(e) {
    if (e.key === 'Enter') {
        sendMessage();
    }
});

// Отображение сообщения в чате
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

// Экранирование HTML для безопасности
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Системные сообщения
function addSystemMessage(text) {
    const messagesDiv = document.getElementById('messages');
    const messageDiv = document.createElement('div');
    messageDiv.className = 'system-message';
    messageDiv.textContent = text;
    
    messagesDiv.appendChild(messageDiv);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

// Добавляем CSS стили для системных сообщений
const style = document.createElement('style');
style.textContent = `
    .system-message {
        text-align: center;
        color: #888;
        margin: 10px 0;
        font-style: italic;
        font-size: 0.9em;
    }
    
    .message {
        margin: 10px 0;
        padding: 8px 12px;
        border-radius: 15px;
        max-width: 70%;
        word-wrap: break-word;
    }
    
    .message.own {
        background: #007bff;
        color: white;
        margin-left: auto;
        text-align: right;
    }
    
    .message.other {
        background: #f1f1f1;
        color: #333;
        margin-right: auto;
    }
    
    .message-time {
        opacity: 0.7;
        font-size: 0.8em;
        margin-top: 5px;
        display: block;
    }
    
    .message-content {
        margin-bottom: 3px;
    }
`;
document.head.appendChild(style);
