class VoiceAssistant {
    constructor() {
        this.ws = null;
        this.conversationHistory = [];
        this.isConnected = false;
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.isRecording = false;
        this.currentMode = 'text';
        
        // 🚀 Streaming state
        this.currentStreamingMessage = null;
        this.streamingText = '';
        this.audioQueue = [];
        this.isPlayingAudio = false;
        
        this.initializeElements();
        this.attachEventListeners();
    }

    initializeElements() {
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
            const arrayBuffer = await audioBlob.arrayBuffer();
            const base64Audio = btoa(
                new Uint8Array(arrayBuffer).reduce(
                    (data, byte) => data + String.fromCharCode(byte),
                    ''
                )
            );

            this.ws.send(JSON.stringify({
                type: 'audio_chunk',
                data: base64Audio
            }));

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
                await this.handleWebSocketMessage(data);
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

    async handleWebSocketMessage(data) {
        switch(data.type) {
            case 'audio_received':
                console.log(`Audio chunks received: ${data.chunks}`);
                break;
                
            case 'transcription':
                // Show transcribed user text
                this.addMessage(data.text, 'user');
                break;
                
            case 'llm_start':
                // 🚀 Create streaming message element
                this.streamingText = '';
                this.currentStreamingMessage = this.createStreamingMessage();
                break;
                
            case 'llm_chunk':
                // 🚀 Append text chunk immediately (token-by-token)
                this.streamingText += data.text;
                this.updateStreamingMessage(data.text);
                break;
                
            case 'llm_complete':
                // Finalize the message
                if (this.currentStreamingMessage) {
                    this.currentStreamingMessage.classList.remove('streaming');
                }
                console.log('LLM generation complete');
                break;
                
            case 'tts_start':
                // Clear audio queue for new response
                this.audioQueue = [];
                console.log('TTS generation started');
                break;
                
            case 'tts_chunk':
                // 🚀 Queue audio chunk and start playing
                this.audioQueue.push({
                    audio: data.audio,
                    index: data.chunk_index,
                    is_last: data.is_last
                });
                
                // Start playing if not already playing
                if (!this.isPlayingAudio) {
                    this.playNextAudioChunk();
                }
                break;
                
            case 'tts_complete':
                console.log('TTS generation complete');
                break;
                
            case 'turn_complete':
                // Update conversation history
                this.conversationHistory = data.conversation_history || this.conversationHistory;
                this.hideLoading();
                this.recordingStatus.textContent = 'Click to start recording';
                break;
                
            case 'error':
                this.showError(data.message);
                this.hideLoading();
                this.recordingStatus.textContent = 'Click to start recording';
                break;
                
            // Legacy support for old non-streaming messages
            case 'response':
                if (data.user_text) {
                    this.addMessage(data.user_text, 'user');
                }
                this.addMessage(data.text, 'assistant');
                this.conversationHistory = data.conversation_history || this.conversationHistory;
                
                if (data.audio) {
                    await this.playAudio(data.audio);
                }
                
                this.hideLoading();
                this.recordingStatus.textContent = 'Click to start recording';
                break;
        }
    }

    createStreamingMessage() {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message assistant streaming';
        
        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        contentDiv.textContent = '';
        
        messageDiv.appendChild(contentDiv);
        this.chatContainer.appendChild(messageDiv);
        
        this.chatContainer.scrollTop = this.chatContainer.scrollHeight;
        
        return messageDiv;
    }

    updateStreamingMessage(chunk) {
        if (this.currentStreamingMessage) {
            const contentDiv = this.currentStreamingMessage.querySelector('.message-content');
            contentDiv.textContent += chunk;
            
            // Auto-scroll to bottom
            this.chatContainer.scrollTop = this.chatContainer.scrollHeight;
        }
    }

    async playNextAudioChunk() {
        if (this.audioQueue.length === 0) {
            this.isPlayingAudio = false;
            return;
        }

        this.isPlayingAudio = true;
        const chunk = this.audioQueue.shift();
        
        try {
            await this.playAudioHex(chunk.audio);
            
            // Play next chunk after current finishes
            if (this.audioQueue.length > 0 || !chunk.is_last) {
                setTimeout(() => this.playNextAudioChunk(), 50);
            } else {
                this.isPlayingAudio = false;
            }
        } catch (error) {
            console.error('Error playing audio chunk:', error);
            // Continue to next chunk even if one fails
            this.playNextAudioChunk();
        }
    }

    async playAudioHex(hexString) {
        return new Promise((resolve, reject) => {
            try {
                const bytes = new Uint8Array(hexString.match(/.{1,2}/g).map(byte => parseInt(byte, 16)));
                const blob = new Blob([bytes], { type: 'audio/mpeg' });
                const url = URL.createObjectURL(blob);
                
                const audio = new Audio(url);
                
                audio.onended = () => {
                    URL.revokeObjectURL(url);
                    resolve();
                };
                
                audio.onerror = (error) => {
                    URL.revokeObjectURL(url);
                    reject(error);
                };
                
                audio.play();
            } catch (error) {
                reject(error);
            }
        });
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
        this.audioQueue = [];
        this.isPlayingAudio = false;
        this.streamingText = '';
        this.currentStreamingMessage = null;
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