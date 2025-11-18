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

// Подключение к WebSocket
function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/${currentUserId}`;
    
    websocket = new WebSocket(wsUrl);
    
    websocket.onopen = function() {
        console.log('WebSocket connected');
        addSystemMessage('✅ Подключено к чату');
    };
    
    websocket.onmessage = function(event) {
        const messageData = JSON.parse(event.data);
        displayMessage(messageData, false);
    };
    
    websocket.onclose = function() {
        console.log('WebSocket disconnected');
        addSystemMessage('❌ Соединение потеряно. Переподключение...');
        setTimeout(connectWebSocket, 3000);
    };
    
    websocket.onerror = function(error) {
        console.error('WebSocket error:', error);
    };
}

// Загрузка истории сообщений
async function loadMessageHistory() {
    try {
        const response = await fetch(`/api/messages/${currentUserId}/${otherUserId}`);
        const messages = await response.json();
        
        messages.forEach(msg => {
            displayMessage(msg, msg.from_user_id === currentUserId);
        });
    } catch (error) {
        console.error('Error loading message history:', error);
    }
}

// Отправка сообщения
function sendMessage() {
    const input = document.getElementById('messageInput');
    const content = input.value.trim();
    
    if (content && websocket) {
        const messageData = {
            to_user_id: otherUserId,
            content: content,
            type: 'text'
        };
        
        websocket.send(JSON.stringify(messageData));
        input.value = '';
        
        // Показываем сообщение сразу (optimistic update)
        displayMessage({
            from_user_id: currentUserId,
            content: content,
            timestamp: new Date().toISOString()
        }, true);
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
        <div>${messageData.content}</div>
        <small style="opacity: 0.7;">${time}</small>
    `;
    
    messagesDiv.appendChild(messageDiv);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

// Системные сообщения
function addSystemMessage(text) {
    const messagesDiv = document.getElementById('messages');
    const messageDiv = document.createElement('div');
    messageDiv.style.textAlign = 'center';
    messageDiv.style.color = '#888';
    messageDiv.style.margin = '10px 0';
    messageDiv.textContent = text;
    
    messagesDiv.appendChild(messageDiv);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}