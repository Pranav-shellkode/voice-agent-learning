import streamlit as st
import assemblyai as aai
from assemblyai.streaming.v3 import (
    BeginEvent,
    StreamingClient,
    StreamingClientOptions,
    StreamingError,
    StreamingEvents,
    StreamingParameters,
    StreamingSessionParameters,
    TerminationEvent,
    TurnEvent,
)
from dotenv import load_dotenv
import logging
import os
import boto3
import json
from deepgram import DeepgramClient
import base64
from io import BytesIO
import numpy as np
from typing import Type

load_dotenv()

api_key = os.getenv("ASSEMBLY_API_KEY")
deepgram_key = os.getenv("DEEPGRAM_API_KEY")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize clients
bedrock_runtime = boto3.client(service_name='bedrock-runtime')
deepgram = DeepgramClient(api_key=deepgram_key)

def load_knowledge_base(file_path="data/knowledge_base.txt"):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            knowledge = f.read()
        logger.info(f"Knowledge base loaded from {file_path}")
        return knowledge
    except Exception as e:
        logger.error(f"Error loading knowledge base: {e}")
        return ""

KNOWLEDGE_BASE = load_knowledge_base()

# Initialize session state
if 'conversation_history' not in st.session_state:
    st.session_state.conversation_history = []
if 'transcribed_texts' not in st.session_state:
    st.session_state.transcribed_texts = []
if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'streaming_client' not in st.session_state:
    st.session_state.streaming_client = None
if 'is_recording' not in st.session_state:
    st.session_state.is_recording = False

def send_to_bedrock(text: str):
    """Send transcribed text to AWS Bedrock with knowledge base context"""
    try:
        system_prompt = f"""You are a helpful helpdesk assistant. Answer questions based on the following knowledge base:

{KNOWLEDGE_BASE}
Keep in mind that you're questions are from a speech to text model, so pretend you can "hear" them.
If the question is not covered in the knowledge base, politely say you don't have that information and suggest contacting support.
Keep your response quite compact and to the point and professional don't be too talkative while being friendly toned"""

        messages = []
        
        if len(st.session_state.conversation_history) == 0:
            messages.append({
                "role": "user",
                "content": [{"type": "text", "text": system_prompt}]
            })
            messages.append({
                "role": "assistant",
                "content": [{"type": "text", "text": "I understand. I'll answer questions based on the knowledge base provided."}]
            })
        
        messages.extend(st.session_state.conversation_history)
        messages.append({
            "role": "user",
            "content": [{"type": "text", "text": text}]
        })
        
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 512,
            "messages": messages,
            "temperature": 0.5
        }
        
        response = bedrock_runtime.invoke_model(
            modelId="anthropic.claude-3-5-sonnet-20240620-v1:0",
            body=json.dumps(request_body),
        )
        
        response_body = json.loads(response['body'].read())
        assistant_message = response_body['content'][0]['text']
        
        logger.info(f"Claude (Bedrock): {assistant_message}")
        
        st.session_state.conversation_history.append({
            "role": "user",
            "content": [{"type": "text", "text": text}]
        })
        st.session_state.conversation_history.append({
            "role": "assistant",
            "content": [{"type": "text", "text": assistant_message}]
        })
        
        return assistant_message
       
    except Exception as e:
        logger.error(f"Error calling Bedrock: {e}")
        return None

def tts(assistant_message):
    """Convert text to speech using Deepgram"""
    try:
        logger.info("Generating speech")
        client = DeepgramClient(api_key=deepgram_key)
        response = client.speak.v1.audio.generate(
            text=assistant_message,
            model="aura-2-thalia-en"
        )

        audio_data = b''.join(chunk for chunk in response)
        return audio_data
        
    except Exception as e:
        logger.error(f"Error in TTS: {e}")
        return None

def on_begin(self: Type[StreamingClient], event: BeginEvent):
    logger.info(f"Session started: {event.id}")
    st.session_state.status = "🎙️ Recording... Speak now"

def on_turn(self: Type[StreamingClient], event: TurnEvent):
    if event.end_of_turn and event.turn_is_formatted:
        transcribed_text = event.transcript
        logger.info(f"You: {transcribed_text}")
        
        st.session_state.transcribed_texts.append(transcribed_text)
        st.session_state.messages.append({"role": "user", "content": transcribed_text})
        
        assistant_response = send_to_bedrock(transcribed_text)
        
        if assistant_response:
            st.session_state.messages.append({"role": "assistant", "content": assistant_response})
            
            # Generate TTS
            audio_data = tts(assistant_response)
            if audio_data:
                st.session_state.last_audio = audio_data

    if event.end_of_turn and not event.turn_is_formatted:
        params = StreamingSessionParameters(format_turns=True)
        self.set_params(params)

def on_terminated(self: Type[StreamingClient], event: TerminationEvent):
    logger.info(f"Session ended: {event.audio_duration_seconds}s of audio processed")
    st.session_state.status = "✅ Session ended"
    st.session_state.is_recording = False

def on_error(self: Type[StreamingClient], error: StreamingError):
    logger.error(f"Error: {error}")
    st.session_state.status = f"❌ Error: {error}"
    st.session_state.is_recording = False

# Streamlit UI
st.set_page_config(page_title="Voice Assistant", page_icon="🎤", layout="wide")

st.title("🎤 Voice Assistant")

# Status display
if 'status' not in st.session_state:
    st.session_state.status = "Ready to start"

status_placeholder = st.empty()
status_placeholder.info(st.session_state.status)

# Start/Stop button
col1, col2 = st.columns([1, 5])

with col1:
    if st.button("🎙️ Start" if not st.session_state.is_recording else "⏹️ Stop", 
                 type="primary" if not st.session_state.is_recording else "secondary"):
        
        if not st.session_state.is_recording:
            # Start recording
            st.session_state.is_recording = True
            st.session_state.status = "Connecting..."
            
            client = StreamingClient(
                StreamingClientOptions(
                    api_key=api_key,
                    api_host="streaming.assemblyai.com",
                )
            )
            
            client.on(StreamingEvents.Begin, on_begin)
            client.on(StreamingEvents.Turn, on_turn)
            client.on(StreamingEvents.Termination, on_terminated)
            client.on(StreamingEvents.Error, on_error)
            
            client.connect(
                StreamingParameters(
                    sample_rate=16000,
                    format_turns=True
                )
            )
            
            st.session_state.streaming_client = client
            
            # Start streaming from microphone
            client.stream(aai.extras.MicrophoneStream(sample_rate=16000))
            
        else:
            # Stop recording
            if st.session_state.streaming_client:
                st.session_state.streaming_client.disconnect(terminate=True)
                st.session_state.streaming_client = None
            st.session_state.is_recording = False
            st.session_state.status = "Stopped"

# Chat display
st.subheader("Conversation")

chat_container = st.container()

with chat_container:
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

# Audio playback
if 'last_audio' in st.session_state and st.session_state.last_audio:
    st.audio(st.session_state.last_audio, format='audio/mp3')
    del st.session_state.last_audio

# Clear conversation button
if st.button("🗑️ Clear Conversation"):
    st.session_state.conversation_history = []
    st.session_state.transcribed_texts = []
    st.session_state.messages = []
    st.rerun()