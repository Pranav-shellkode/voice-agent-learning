class VoiceAssistant {
constructor() {
    // websocket connection 
    this.ws = null;
    // empty list of conversation history 
    this.conversationHistory = [];
    this.isConnected = false;
    // mic recorder 
    this.mediaRecorder = null;
    this.audioChunks = [];
    this.isRecording = false;
    // text voice mode 
    this.currentMode = 'text';
    
    this.initializeElements();
    this.attachEventListeners();
}

initializeElements(){
    this.chatContainer = document.getElementById('chatContainer');
    this.messageInput = document.getElementById('messageInput');
    this.sendBtn = document.getElementById('sendBtn');
    this.connectBtn = document.getElementById('connectBtn');
    this.clearBtn = document.getElementById('clearBtn');
    this.recordBtn = document.getElementById('recordBtn');
    this.statusDot = document.getElementById('statusDot');
    this.statusText = document.getElementById('statusText');
    this.loading = document.getElementById('loading');
    this.errorMessage = document.getElementById('errorMessage');
    this.textMode = document.getElementById('textMode');
    this.voiceMode = document.getElementById('voiceMode');
    this.textModeBtn = document.getElementById('textModeBtn');
    this.voiceModeBtn = document.getElementById('voiceModeBtn');
    this.recordingStatus = document.getElementById('recordingStatus');
}

attachEventListeners() {
    this.sendBtn.addEventListener('click', () => this.sendMessage());

    this.messageInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') this.sendMessage();
    });
    this.connectBtn.addEventListener('click', () => this.toggleConnection());
    this.clearBtn.addEventListener('click', () => this.clearChat());
    this.recordBtn.addEventListener('click', () => this.toggleRecording());
    this.textModeBtn.addEventListener('click', () => this.switchMode('text'));
    this.voiceModeBtn.addEventListener('click', () => this.switchMode('voice'));
}

switchMode(mode) {
    this.currentMode = mode;
    
    if (mode === 'text') {
        this.textMode.style.display = 'block';
        this.voiceMode.style.display = 'none';
        this.textModeBtn.classList.add('active');
        this.voiceModeBtn.classList.remove('active');
    } else {
        this.textMode.style.display = 'none';
        this.voiceMode.style.display = 'block';
        this.textModeBtn.classList.remove('active');
        this.voiceModeBtn.classList.add('active');
    }
}

async toggleRecording() {
    if (!this.isConnected) {
        this.showError('Please connect to the server first');
        return;
    }

    if (this.isRecording) {
        this.stopRecording();
    } else {
        await this.startRecording();
    }
}

async startRecording() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        this.mediaRecorder = new MediaRecorder(stream);
        this.audioChunks = [];

        this.mediaRecorder.ondataavailable = (event) => {
            this.audioChunks.push(event.data);
        };

        this.mediaRecorder.onstop = async () => {
            const audioBlob = new Blob(this.audioChunks, { type: 'audio/webm' });
            await this.sendAudio(audioBlob);
            
            // Stop all tracks
            stream.getTracks().forEach(track => track.stop());
        };

        this.mediaRecorder.start();
        this.isRecording = true;
        this.recordBtn.classList.add('recording');
        this.recordingStatus.textContent = 'Recording... Click to stop';
        this.recordBtn.textContent = '⏹️';

    } catch (error) {
        this.showError('Microphone access denied: ' + error.message);
    }
}

stopRecording() {
    if (this.mediaRecorder && this.isRecording) {
        this.mediaRecorder.stop();
        this.isRecording = false;
        this.recordBtn.classList.remove('recording');
        this.recordingStatus.textContent = 'Processing audio...';
        this.recordBtn.textContent = '🎤';
        this.showLoading();
    }
}

async sendAudio(audioBlob) {
    try {
        // Convert blob to base64
        const arrayBuffer = await audioBlob.arrayBuffer();
        const base64Audio = btoa(
            new Uint8Array(arrayBuffer).reduce(
                (data, byte) => data + String.fromCharCode(byte),
                ''
            )
        );

        // Send complete audio as one chunk
        this.ws.send(JSON.stringify({
            type: 'audio_chunk',
            data: base64Audio
        }));

        // Signal end of turn
        this.ws.send(JSON.stringify({
            type: 'end_turn',
            conversation_history: this.conversationHistory
        }));

    } catch (error) {
        this.showError('Failed to send audio: ' + error.message);
        this.hideLoading();
        this.recordingStatus.textContent = 'Click to start recording';
    }
}

async toggleConnection() {
    if (this.isConnected) {
        this.disconnect();
    } else {
        await this.connect();
    }
}

async connect() {
    try {
        const wsUrl = 'ws://127.0.0.1:8000/ws';
        
        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            this.isConnected = true;
            this.updateStatus(true);
            this.connectBtn.textContent = 'Disconnect';
            this.showError('');
        };

        this.ws.onmessage = async (event) => {
            const data = JSON.parse(event.data);
            
            if (data.type === 'audio_received') {
                console.log(`Audio chunks received: ${data.chunks}`);
            } else if (data.type === 'response') {
                // Show transcribed text if from audio
                if (data.user_text) {
                    this.addMessage(data.user_text, 'user');
                }
                
                this.addMessage(data.text, 'assistant');
                this.conversationHistory = data.conversation_history || this.conversationHistory;
                
                // Play audio if available
                if (data.audio) {
                    await this.playAudio(data.audio);
                }
                
                this.hideLoading();
                this.recordingStatus.textContent = 'Click to start recording';
                
            } else if (data.type === 'error') {
                this.showError(data.message);
                this.hideLoading();
                this.recordingStatus.textContent = 'Click to start recording';
            }
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            this.showError('Connection error. Make sure the backend is running.');
        };

        this.ws.onclose = () => {
            this.isConnected = false;
            this.updateStatus(false);
            this.connectBtn.textContent = 'Connect';
        };

    } catch (error) {
        this.showError('Failed to connect: ' + error.message);
    }
}

disconnect() {
    if (this.ws) {
        this.ws.send(JSON.stringify({ type: 'close' }));
        this.ws.close();
    }
}

async sendMessage() {
    const text = this.messageInput.value.trim();
    
    if (!text) return;
    
    if (!this.isConnected) {
        this.showError('Please connect to the server first');
        return;
    }

    this.addMessage(text, 'user');
    this.messageInput.value = '';
    this.showLoading();

    try {
        this.ws.send(JSON.stringify({
            type: 'text',
            data: text,
            conversation_history: this.conversationHistory
        }));
    } catch (error) {
        this.showError('Failed to send message: ' + error.message);
        this.hideLoading();
    }
}

addMessage(text, sender) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${sender}`;
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    contentDiv.textContent = text;
    
    messageDiv.appendChild(contentDiv);
    this.chatContainer.appendChild(messageDiv);
    
    this.chatContainer.scrollTop = this.chatContainer.scrollHeight;
}

async playAudio(hexString) {
    try {
        const bytes = new Uint8Array(hexString.match(/.{1,2}/g).map(byte => parseInt(byte, 16)));
        const blob = new Blob([bytes], { type: 'audio/mpeg' });
        const url = URL.createObjectURL(blob);
        
        const audio = new Audio(url);
        await audio.play();
        
        audio.onended = () => URL.revokeObjectURL(url);
    } catch (error) {
        console.error('Error playing audio:', error);
    }
}

clearChat() {
    this.chatContainer.innerHTML = `
        <div class="message assistant">
            <div class="message-content">
                Hello! I'm your helpdesk assistant. You can type or speak to me!
            </div>
        </div>
    `;
    this.conversationHistory = [];
}

updateStatus(connected) {
    if (connected) {
        this.statusDot.classList.add('connected');
        this.statusText.textContent = 'Connected';
    } else {
        this.statusDot.classList.remove('connected');
        this.statusText.textContent = 'Disconnected';
    }
}

showLoading() {
    this.loading.classList.add('active');
    this.sendBtn.disabled = true;
    this.recordBtn.disabled = true;
}

hideLoading() {
    this.loading.classList.remove('active');
    this.sendBtn.disabled = false;
    this.recordBtn.disabled = false;
}

showError(message) {
    if (message) {
        this.errorMessage.textContent = message;
        this.errorMessage.classList.add('show');
    } else {
        this.errorMessage.classList.remove('show');
    }
}
}

const app = new VoiceAssistant();