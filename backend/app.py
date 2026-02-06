from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException , Request 
from fastapi.responses import HTMLResponse 
from fastapi.templating import Jinja2Templates 
from models import AudioTranscribeRequest, ChatMessage , TTSRequest 
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
import base64
import tempfile

load_dotenv()
templates = Jinja2Templates(directory="frontend/")

api_key = os.getenv("ASSEMBLY_API_KEY")
deepgram_key = os.getenv("DEEPGRAM_API_KEY")
aai.settings.api_key = api_key
deepgram = DeepgramClient(api_key=deepgram_key)
bedrock_runtime = boto3.client(service_name='bedrock-runtime')


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

KNOWLEDGE_BASE = ""


@asynccontextmanager
async def lifespan(app: FastAPI):
    global KNOWLEDGE_BASE
    KNOWLEDGE_BASE = load_knowledge_base()
    if not KNOWLEDGE_BASE:
        logger.warning("Knowledge base not found..")
    yield


app = FastAPI(
    title="Voice Assistant API",
    description="Helpdesk assistant",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def load_knowledge_base(file_path: str = "data/knowledge_base.txt") -> str:
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            knowledge = f.read()
        logger.info(f"Knowledge base loaded from {file_path}")
        return knowledge
    except Exception as e:
        logger.error(f"Error loading knowledge base: {e}")
        return ""


async def transcribe_audio(audio_bytes: bytes) -> str:
    """Transcribe audio using AssemblyAI"""
    try:
        logger.info("Transcribing audio with AssemblyAI")
        
        # Save audio temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as temp_file:
            temp_file.write(audio_bytes)
            temp_path = temp_file.name
        
        # Run transcription in executor to avoid blocking
        loop = asyncio.get_event_loop()
        transcriber = aai.Transcriber()
        
        transcript = await loop.run_in_executor(
            None,
            lambda: transcriber.transcribe(temp_path)
        )
        
        try:
            os.unlink(temp_path)
        except:
            pass
        
        if transcript.status == aai.TranscriptStatus.error:
            raise Exception(f"Transcription failed: {transcript.error}")
        
        logger.info(f"Transcription: {transcript.text}")
        return transcript.text
        
    except Exception as e:
        logger.error(f"Error in STT: {e}")
        raise HTTPException(status_code=500, detail=f"STT error: {str(e)}")


async def send_to_bedrock(text: str, conversation_history: list) -> str:
    """Send transcribed text to AWS Bedrock with knowledge base context"""
    try:
        system_prompt = f"""You are a helpful helpdesk assistant. Answer questions based on the following knowledge base:

{KNOWLEDGE_BASE}
Your role is that of a helpdesk assistant for a company called Shellkode , keep your response under 50 words always .. (very important)
Keep in mind that your questions are from a speech to text model, so pretend you can "hear" them.
If the question is not covered in the knowledge base, politely say you don't have that information and suggest contacting support.
Keep your response quite compact and to the point and professional don't be too talkative while being friendly toned"""

        messages = []
        
        # Add system message as first user message with assistant acknowledgment
        if len(conversation_history) == 0:
            messages.append({
                "role": "user",
                "content": [{"type": "text", "text": system_prompt}]
            })
            # messages.append({
            #     "role": "assistant",
            #     "content": [{"type": "text", "text": "I understand. I'll answer questions based on the knowledge base provided."}]
            # })
        
        
        MAX_HISTORY = 5
        def trim_history(conversation_history):
            return conversation_history[-MAX_HISTORY:]

        # Add conversation history
        messages.extend(trim_history(conversation_history))

        # Add current user message in case of a continued conversation 
        messages.append({
            "role": "user",
            "content": [{"type": "text", "text": text}]
        })
        
        # Prepare request body for Claude on Bedrock
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 512,
            "messages": messages,
            "temperature": 0.5,
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

        response_body = json.loads(response['body'].read())
        assistant_message = response_body['content'][0]['text']
        
        logger.info(f"LLM : {assistant_message}")
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


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "online",
        "service": "Voice Assistant API",
        "endpoints": {
            "websocket": "/ws",
            "chat": "/api/chat",
            "tts": "/api/tts",
            "transcribe": "/api/transcribe"
        }
    }


@app.post("/api/transcribe")
async def transcribe(request: AudioTranscribeRequest):
    """
    Transcribe audio to text using AssemblyAI
    """
    try:
        # Decode base64 audio
        audio_bytes = base64.b64decode(request.audio_base64)
        
        # Transcribe
        text = await transcribe_audio(audio_bytes)
        
        return {
            "text": text
        }
        
    except Exception as e:
        logger.error(f"Error in transcribe endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
    WebSocket endpoint for STT->LLM->TTS pipeline
    Accumulates audio chunks and transcribes on end_turn
    
    Expected message format:
    {
        "type": "audio_chunk" | "end_turn" | "text" | "close",
        "data": <audio_bytes_base64> | <text_string>,
        "conversation_history": []  # optional
    }
    """
    await websocket.accept()
    logger.info("WebSocket connection established")
    
    conversation_history = []
    audio_chunks = []
    
    try:
        while True:
            # Receive message from client
            message = await websocket.receive_json()
            
            msg_type = message.get("type")
            
            if msg_type == "audio_chunk":
                # Accumulate audio chunks
                audio_base64 = message.get("data")
                audio_bytes = base64.b64decode(audio_base64)
                audio_chunks.append(audio_bytes)
                
                # Send acknowledgment
                await websocket.send_json({
                    "type": "audio_received",
                    "chunks": len(audio_chunks)
                })
                
            elif msg_type == "end_turn":
                # Combine all audio chunks
                if not audio_chunks:
                    await websocket.send_json({
                        "type": "error",
                        "message": "No audio received"
                    })
                    continue
                
                logger.info(f"Processing {len(audio_chunks)} audio chunks")
                full_audio = b''.join(audio_chunks)
                audio_chunks = []  # Reset
                
                conversation_history_input = message.get("conversation_history", conversation_history)
                
                try:
                    # Transcribe
                    text = await transcribe_audio(full_audio)
                    
                    if not text or text.strip() == "":
                        await websocket.send_json({
                            "type": "error",
                            "message": "No speech detected"
                        })
                        continue
                    
                    # Get LLM response
                    assistant_response = await send_to_bedrock(text, conversation_history_input)
                    
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
                        "user_text": text,
                        "text": assistant_response,
                        "audio": audio_data.hex(),
                        "conversation_history": conversation_history
                    })
                    
                except Exception as e:
                    logger.error(f"Error processing audio: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Processing error: {str(e)}"
                    })
            
            elif msg_type == "text":
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
                    "audio": audio_data.hex(),
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


# @app.get("/api/knowledge-base")
# async def get_knowledge_base():
#     """Get current knowledge base content"""
#     return {
#         "content": KNOWLEDGE_BASE,
#         "loaded": bool(KNOWLEDGE_BASE)
#     }


# @app.post("/api/knowledge-base/reload")
# async def reload_knowledge_base():
#     """Reload knowledge base from file"""
#     global KNOWLEDGE_BASE
#     KNOWLEDGE_BASE = load_knowledge_base()
#     return {
#         "status": "reloaded",
#         "loaded": bool(KNOWLEDGE_BASE)
#     }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="info"
    )