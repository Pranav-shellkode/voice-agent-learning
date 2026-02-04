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
from typing import Type
import os 
import boto3
import json
from deepgram import DeepgramClient
import pygame
import io
import threading
from concurrent.futures import ThreadPoolExecutor

load_dotenv()
api_key = os.getenv("ASSEMBLY_API_KEY")
deepgram_key = os.getenv("DEEPGRAM_API_KEY")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

transcribed_texts = []
conversation_history = []

# Initialize clients
bedrock_runtime = boto3.client(service_name='bedrock-runtime')
deepgram = DeepgramClient(api_key=deepgram_key)
pygame.mixer.init()

# Thread pool for parallel processing
executor = ThreadPoolExecutor(max_workers=3)

def load_knowledge_base(file_path=r"data\knowledge_base.txt"):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            knowledge = f.read()
        logger.info(f"Knowledge base loaded from {file_path}")
        return knowledge
    except Exception as e:
        logger.error(f"Error loading knowledge base: {e}")
        return ""

KNOWLEDGE_BASE = load_knowledge_base()

def send_to_bedrock(text: str):
    """Send transcribed text to AWS Bedrock with knowledge base context"""
    try:
        system_prompt = f"""You are a helpful helpdesk assistant. Answer questions based on the following knowledge base:

{KNOWLEDGE_BASE}
Keep in mind that you're questions are from a speech to text model , so pretend you can "hear" them ....
Keep responses compact, professional, and friendly. If not in knowledge base, politely say so."""

        messages = []
        
        if len(conversation_history) == 0:
            messages.append({
                "role": "user",
                "content": [{"type": "text", "text": system_prompt}]
            })
            messages.append({
                "role": "assistant",
                "content": [{"type": "text", "text": "Understood. I'll help based on the knowledge base."}]
            })
        
        messages.extend(conversation_history)
        messages.append({
            "role": "user",
            "content": [{"type": "text", "text": text}]
        })
        
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 300,  # Reduced for faster responses
            "messages": messages,
            "temperature": 0.3  # Lower for faster, more focused responses
        }
        
        response = bedrock_runtime.invoke_model(
            modelId="anthropic.claude-3-5-sonnet-20240620-v1:0",  
            body=json.dumps(request_body),
        )
        
        response_body = json.loads(response['body'].read())
        assistant_message = response_body['content'][0]['text']
        
        print(f"\n🤖 Claude: {assistant_message}\n")
        
        conversation_history.append({
            "role": "user",
            "content": [{"type": "text", "text": text}]
        })
        conversation_history.append({
            "role": "assistant",
            "content": [{"type": "text", "text": assistant_message}]
        })
        
        # Run TTS in separate thread to not block
        executor.submit(tts, assistant_message)
        
        return assistant_message
       
    except Exception as e:
        logger.error(f"Error calling Bedrock: {e}")
        return None

def tts(assistant_message):
    """Convert text to speech using Deepgram and play it"""
    try:
        print("Generating speech...")
        
        response = deepgram.speak.v1.audio.generate(
            text=assistant_message,
            model="aura-2-thalia-en"  
        )

        # Collect all chunks efficiently
        audio_buffer = io.BytesIO()
        for chunk in response:
            audio_buffer.write(chunk)
        
        audio_buffer.seek(0)
        
        # Load and play
        pygame.mixer.music.load(audio_buffer)
        pygame.mixer.music.play()
        
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(10)
        
        print("✓ Speech complete\n")
        
    except Exception as e:
        logger.error(f"Error in TTS: {e}")

def on_begin(self: Type[StreamingClient], event: BeginEvent):
    print(f"✓ Session started: {event.id}")

def on_turn(self: Type[StreamingClient], event: TurnEvent):
    if event.end_of_turn and event.turn_is_formatted:
        transcribed_text = event.transcript
        print(f"\n🎤 You: {transcribed_text}")
        
        transcribed_texts.append(transcribed_text)
        
        # Process in background thread to not block STT
        executor.submit(send_to_bedrock, transcribed_text)

    if event.end_of_turn and not event.turn_is_formatted:
        params = StreamingSessionParameters(format_turns=True)
        self.set_params(params)

def on_terminated(self: Type[StreamingClient], event: TerminationEvent):
    print(f"\n✓ Session ended: {event.audio_duration_seconds}s")
    print(f"📝 Total turns: {len(transcribed_texts)}")

def on_error(self: Type[StreamingClient], error: StreamingError):
    print(f"❌ Error: {error}")

def main():
    if not KNOWLEDGE_BASE:
        print("⚠️ Warning: Knowledge base is empty.")
    
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
            format_turns=True,
            # Add these for faster processing
            encoding_format='pcm_mulaw',  # More efficient encoding
        )
    )
    
    print("🎙️ Speak now... (Ctrl+C to stop)\n")
    
    try:
        client.stream(
            aai.extras.MicrophoneStream(sample_rate=16000)
        )
    except KeyboardInterrupt:
        print("\n Stopping...")
    finally:
        client.disconnect(terminate=True)
        executor.shutdown(wait=False)
        pygame.mixer.quit()

if __name__ == "__main__":
    main()