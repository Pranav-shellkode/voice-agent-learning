from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import assemblyai as aai
import logging
from typing import Optional
import os
import boto3
import json
from deepgram import DeepgramClient
import io
import asyncio
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("ASSEMBLY_API_KEY")
deepgram_key = os.getenv("DEEPGRAM_API_KEY")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Voice Assistant API",
    description="Real-time STT->LLM->TTS pipeline",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

bedrock_runtime = boto3.client(service_name='bedrock-runtime')
deepgram = DeepgramClient(api_key=deepgram_key)

KNOWLEDGE_BASE = ""


class ChatMessage(BaseModel):
    text: str
    conversation_history: Optional[list] = []


class TTSRequest(BaseModel):
    text: str


def load_knowledge_base(file_path: str = "data/knowledge_base.txt") -> str:
    """Load knowledge base from file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            knowledge = f.read()
        logger.info(f"Knowledge base loaded from {file_path}")
        return knowledge
    except Exception as e:
        logger.error(f"Error loading knowledge base: {e}")
        return ""


async def send_to_bedrock(text: str, conversation_history: list) -> str:
    """Send transcribed text to AWS Bedrock with knowledge base context"""
    try:
        system_prompt = f"""You are a helpful helpdesk assistant. Answer questions based on the following knowledge base:

{KNOWLEDGE_BASE}
Keep in mind that you're questions are from a speech to text model, so pretend you can "hear" them....
If the question is not covered in the knowledge base, politely say you don't have that information and suggest contacting support.
Keep your response quite compact and to the point and professional don't be too talkative while being friendly toned"""

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
        
        # Call Bedrock (run in executor to avoid blocking)
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: bedrock_runtime.invoke_model(
                modelId="anthropic.claude-3-5-sonnet-20240620-v1:0",
                body=json.dumps(request_body),
        
            )
        )

        # Parse response
        response_body = json.loads(response['body'].read())
        assistant_message = response_body['content'][0]['text']
        
        logger.info(f"Claude (Bedrock): {assistant_message}")
        
        return assistant_message
       
    except Exception as e:
        logger.error(f"Error calling Bedrock: {e}")
        raise HTTPException(status_code=500, detail=f"Bedrock error: {str(e)}")


async def generate_tts(text: str) -> bytes:
    """Convert text to speech using Deepgram"""
    try:
        logger.info("Generating speech with Deepgram")
        
        # Run Deepgram TTS in executor to avoid blocking
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: deepgram.speak.v1.audio.generate(
                text=text,
                model="aura-2-thalia-en"
            )
        )
        
        audio_buffer = io.BytesIO()
        for chunk in response:
            audio_buffer.write(chunk)
        
        audio_buffer.seek(0)
        return audio_buffer.getvalue()
        
    except Exception as e:
        logger.error(f"Error in TTS: {e}")
        raise HTTPException(status_code=500, detail=f"TTS error: {str(e)}")


@asynccontextmanager
async def startup_event(app:FastAPI):
    """Load knowledge base on startup"""
    global KNOWLEDGE_BASE
    KNOWLEDGE_BASE = load_knowledge_base()
    if not KNOWLEDGE_BASE:
        logger.warning("Warning: Knowledge base is empty. Create a 'data/knowledge_base.txt' file.")
    yield


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "online",
        "service": "Voice Assistant API",
        "endpoints": {
            "websocket": "/ws",
            "chat": "/api/chat",
            "tts": "/api/tts"
        }
    }


@app.post("/api/chat")
async def chat(message: ChatMessage):
    """
    Process text message through LLM and return response with audio
    """
    try:
        # Get LLM response
        assistant_response = await send_to_bedrock(
            message.text,
            message.conversation_history
        )
        
        # Generate TTS audio
        audio_data = await generate_tts(assistant_response)
        
        return {
            "text": assistant_response,
            "audio_available": True
        }
        
    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/tts")
async def text_to_speech(request: TTSRequest):
    """
    Convert text to speech and stream audio
    """
    try:
        audio_data = await generate_tts(request.text)
        
        return StreamingResponse(
            io.BytesIO(audio_data),
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "attachment; filename=response.mp3"
            }
        )
        
    except Exception as e:
        logger.error(f"Error in TTS endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time STT->LLM->TTS pipeline
    
    Expected message format:
    {
        "type": "audio" | "text" | "end_turn",
        "data": <audio_bytes_base64> | <text_string>,
        "conversation_history": []  # optional
    }
    """
    await websocket.accept()
    logger.info("WebSocket connection established")
    
    conversation_history = []
    
    try:
        while True:
            # Receive message from client
            message = await websocket.receive_json()
            
            msg_type = message.get("type")
            
            if msg_type == "text":
                # Process text message
                text = message.get("data")
                conversation_history = message.get("conversation_history", conversation_history)
                
                logger.info(f"Received text: {text}")
                
                # Get LLM response
                assistant_response = await send_to_bedrock(text, conversation_history)
                
                # Update conversation history
                conversation_history.append({
                    "role": "user",
                    "content": [{"type": "text", "text": text}]
                })
                conversation_history.append({
                    "role": "assistant",
                    "content": [{"type": "text", "text": assistant_response}]
                })
                
                # Generate TTS
                audio_data = await generate_tts(assistant_response)
                
                # Send response back
                await websocket.send_json({
                    "type": "response",
                    "text": assistant_response,
                    "audio": audio_data.hex(),  # Send as hex string
                    "conversation_history": conversation_history
                })
                
            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                
            elif msg_type == "close":
                logger.info("Client requested close")
                break
                
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e)
            })
        except:
            pass


@app.get("/api/knowledge-base")
async def get_knowledge_base():
    """Get current knowledge base content"""
    return {
        "content": KNOWLEDGE_BASE,
        "loaded": bool(KNOWLEDGE_BASE)
    }


@app.post("/api/knowledge-base/reload")
async def reload_knowledge_base():
    """Reload knowledge base from file"""
    global KNOWLEDGE_BASE
    KNOWLEDGE_BASE = load_knowledge_base()
    return {
        "status": "reloaded",
        "loaded": bool(KNOWLEDGE_BASE)
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="info"
    )