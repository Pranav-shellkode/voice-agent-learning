import assemblyai as aai
import requests
import pyttsx3 
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

load_dotenv()
api_key = os.getenv("ASSEMBLY_API_KEY")
deepgram_key = os.getenv("DEEPGRAM_API_KEY")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

transcribed_texts = []
conversation_history = []

# Initialize Bedrock client
bedrock_runtime = boto3.client(
    service_name='bedrock-runtime',
)

deepgram = DeepgramClient(api_key=deepgram_key)

pygame.mixer.init()

def load_knowledge_base(file_path="data/knowledge_base.txt"):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            knowledge = f.read()
        logger.info(f"Knowledge base loaded from {file_path}")
        return knowledge
    except Exception as e:
        logger.error(f"Error loading knowledge base: {e}")
        return ""

# Load knowledge base at startup
KNOWLEDGE_BASE = load_knowledge_base()

def send_to_bedrock(text: str):
    """Send transcribed text to AWS Bedrock with knowledge base context"""
    try:
        # Create system prompt with knowledge base
        system_prompt = f"""You are a helpful helpdesk assistant. Answer questions based on the following knowledge base:

{KNOWLEDGE_BASE}
Keep in mind that you're questions are from a speech to text model , so pretend you can "hear" them ....
If the question is not covered in the knowledge base, politely say you don't have that information and suggest contacting support.
Keep your response quite compact and to the point and professional don't be too talkative while being friendly toned"""


        # Build messages with system context
        messages = []
        
        # Add system message as first user message with assistant acknowledgment
        if len(conversation_history) == 0:
            messages.append({
                "role": "user",
                "content": [{"type": "text", "text": system_prompt}]
            })
            messages.append({
                "role": "assistant",
                "content": [{"type": "text", "text": "I understand. I'll answer questions based on the knowledge base provided."}]
            })
        
        # Add conversation history
        messages.extend(conversation_history)
        
        # Add current user message
        messages.append({
            "role": "user",
            "content": [{"type": "text", "text": text}]
        })
        
        # Prepare request body for Claude on Bedrock
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 512,
            "messages": messages,
            "temperature": 0.5  
        }
        
        # Call Bedrock
        response = bedrock_runtime.invoke_model(
            modelId="anthropic.claude-3-5-sonnet-20240620-v1:0",  
            body=json.dumps(request_body),
        )
        
        # Parse response
        response_body = json.loads(response['body'].read())
        assistant_message = response_body['content'][0]['text']
        
        print(f"\n Claude (Bedrock): {assistant_message}\n")
        
        # Add to conversation history (without system prompt)
        conversation_history.append({
            "role": "user",
            "content": [{"type": "text", "text": text}]
        })
        conversation_history.append({
            "role": "assistant",
            "content": [{"type": "text", "text": assistant_message}]
        })
        
        
        tts(assistant_message)
        
        return assistant_message
       
    except Exception as e:
        logger.error(f"Error calling Bedrock: {e}")
        return None
    
def tts(assistant_message):
    """Convert text to speech using Deepgram and play it"""
    try:
        print("Generating speech:")
        client = DeepgramClient(api_key=deepgram_key)
        response = client.speak.v1.audio.generate(
            text=assistant_message,
            model="aura-2-thalia-en"
        )

        audio_buffer = io.BytesIO()
        for chunk in response:
            audio_buffer.write(chunk)
        
        audio_buffer.seek(0)
        pygame.mixer.music.load(audio_buffer) 
        pygame.mixer.music.play()
        

        # with open("response.mp3","wb") as audio_file:
        #      for chunk in response:
        #          audio_file.write(chunk)
        
        # engine = pyttsx3.init() 
        # engine.say(assistant_message) 
        # engine.runAndWait()
        
        # # Save to file (optional - for debugging)
        # # with open("response.mp3", "wb") as audio_file:
        # #     audio_file.write(response.stream.getValue())
        
        # pygame.mixer.music.load("response.mp3")
        # pygame.mixer.music.play()
        
        # Wait for audio to finish playing
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(10)
        
        # os.remove("response.mp3")
        
        print("✓ Speech playback completed\n")
        
    except Exception as e:
        logger.error(f"Error in TTS: {e}")

def on_begin(self: Type[StreamingClient], event: BeginEvent):
    print(f"Session started: {event.id}")

def on_turn(self: Type[StreamingClient], event: TurnEvent):
    if event.end_of_turn and event.turn_is_formatted:
        transcribed_text = event.transcript
        print(f"\n You: {transcribed_text}")
        
        transcribed_texts.append(transcribed_text)
        
        send_to_bedrock(transcribed_text)

    if event.end_of_turn and not event.turn_is_formatted:
        params = StreamingSessionParameters(
            format_turns=True,
        )
        self.set_params(params)

def on_terminated(self: Type[StreamingClient], event: TerminationEvent):
    print(f"\n Session ended: {event.audio_duration_seconds}s of audio processed")
    print(f"\n Total turns: {len(transcribed_texts)}")

def on_error(self: Type[StreamingClient], error: StreamingError):
    print(f" Error: {error}")

def main():
    if not KNOWLEDGE_BASE:
        print("Warning: Knowledge base is empty. Create a 'knowledge_base.txt' file.")
    
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
    
    print("Speak into your mic now... (Ctrl+C to stop)\n")
    
    try:
        client.stream(
            aai.extras.MicrophoneStream(sample_rate=16000)
        )
    except KeyboardInterrupt:
        print("\n️ Stopping...")
    finally:
        client.disconnect(terminate=True)
        pygame.mixer.quit()

if __name__ == "__main__":
    main()