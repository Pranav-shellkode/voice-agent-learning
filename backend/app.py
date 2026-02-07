from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request 
from fastapi.responses import HTMLResponse 
from fastapi.templating import Jinja2Templates 
from models import AudioTranscribeRequest, ChatMessage, TTSRequest 
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
import re

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
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as temp_file:
            temp_file.write(audio_bytes)
            temp_path = temp_file.name
        
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


async def stream_bedrock_response(text: str, conversation_history: list, websocket: WebSocket):
    """
    Stream LLM response token by token
    Returns the complete response text
    """
    try:
        system_prompt = f"""You are a helpful helpdesk assistant. Answer questions based on the following knowledge base:

{KNOWLEDGE_BASE}
Answer from the knowledge base file that you read only ....
Your role is that of a helpdesk assistant for a company called Shellkode, keep your response under 50 words always.. (very important)
Keep in mind that your questions are from a speech to text model, so pretend you can "hear" them.
If the question is not covered in the knowledge base, politely say you don't have that information and suggest contacting support.
Keep your response quite compact and to the point and professional don't be too talkative while being friendly toned"""

        messages = []
        
        if len(conversation_history) == 0:
            messages.append({
                "role": "user",
                "content": [{"type": "text", "text": system_prompt}]
            })
        
        MAX_HISTORY = 5
        messages.extend(conversation_history[-MAX_HISTORY:])
        messages.append({
            "role": "user",
            "content": [{"type": "text", "text": text}]
        })
        
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 512,
            "messages": messages,
            "temperature": 0.5,
        }
        
        # Use streaming API
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: bedrock_runtime.invoke_model_with_response_stream(
                modelId="anthropic.claude-3-5-sonnet-20240620-v1:0",
                body=json.dumps(request_body),
            )
        )
        
        full_response = ""
        event_stream = response['body']
        
        # Process streaming events
        for event in event_stream:
            chunk = event.get('chunk')
            if chunk:
                chunk_data = json.loads(chunk['bytes'].decode())
                
                if chunk_data['type'] == 'content_block_delta':
                    if chunk_data['delta']['type'] == 'text_delta':
                        text_chunk = chunk_data['delta']['text']
                        full_response += text_chunk
                        
                        # Send chunk immediately
                        await websocket.send_json({
                            "type": "llm_chunk",
                            "text": text_chunk
                        })
                        logger.info(f"LLM chunk: {text_chunk}")
        
        logger.info(f"LLM complete: {full_response}")
        return full_response
       
    except Exception as e:
        logger.error(f"Error calling Bedrock: {e}")
        raise Exception(f"Bedrock error: {str(e)}")


async def stream_tts_generation(text: str, websocket: WebSocket):
    """
    Generate TTS sentence by sentence and stream to frontend
    """
    try:
        # Split text into sentences
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())
        sentences = [s.strip() for s in sentences if s.strip()]
        
        logger.info(f"Generating TTS for {len(sentences)} sentences")
        
        for i, sentence in enumerate(sentences):
            logger.info(f"Processing sentence {i+1}/{len(sentences)}: {sentence}")
            
            # Generate TTS for this sentence
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda s=sentence: deepgram.speak.v1.audio.generate(
                    text=s,
                    model="aura-2-thalia-en"
                )
            )
            
            # Collect audio bytes
            audio_buffer = io.BytesIO()
            for chunk in response:
                audio_buffer.write(chunk)
            
            audio_buffer.seek(0)
            audio_bytes = audio_buffer.getvalue()
            
            logger.info(f"Generated {len(audio_bytes)} bytes of audio for sentence {i+1}")
            
            # Send audio chunk to frontend
            await websocket.send_json({
                "type": "tts_chunk",
                "audio": audio_bytes.hex(),
                "chunk_index": i,
                "is_last": (i == len(sentences) - 1)
            })
            
            logger.info(f"Sent TTS chunk {i+1}/{len(sentences)}")
        
    except Exception as e:
        logger.error(f"Error in TTS streaming: {e}", exc_info=True)
        raise Exception(f"TTS error: {str(e)}")


# Keep original functions for REST endpoints
async def send_to_bedrock(text: str, conversation_history: list) -> str:
    """Non-streaming LLM"""
    try:
        system_prompt = f"""You are a helpful helpdesk assistant. Answer questions based on the following knowledge base:

{KNOWLEDGE_BASE}
Your role is that of a helpdesk assistant for a company called Shellkode, keep your response under 50 words always.. (very important)
Keep in mind that your questions are from a speech to text model, so pretend you can "hear" them.
If the question is not covered in the knowledge base, politely say you don't have that information and suggest contacting support.
Keep your response quite compact and to the point and professional don't be too talkative while being friendly toned"""

        messages = []
        
        if len(conversation_history) == 0:
            messages.append({
                "role": "user",
                "content": [{"type": "text", "text": system_prompt}]
            })
        
        MAX_HISTORY = 5
        messages.extend(conversation_history[-MAX_HISTORY:])
        messages.append({
            "role": "user",
            "content": [{"type": "text", "text": text}]
        })
        
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 512,
            "messages": messages,
            "temperature": 0.5,
        }
        
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: bedrock_runtime.invoke_model(
                modelId="anthropic.claude-3-5-sonnet-20240620-v1:0",
                body=json.dumps(request_body),
            )
        )

        response_body = json.loads(response['body'].read())
        return response_body['content'][0]['text']
       
    except Exception as e:
        logger.error(f"Error calling Bedrock: {e}")
        raise HTTPException(status_code=500, detail=f"Bedrock error: {str(e)}")


async def generate_tts(text: str) -> bytes:
    """Non-streaming TTS"""
    try:
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
    return {
        "endpoints": {
            "websocket": "/ws",
            "chat": "/api/chat",
            "tts": "/api/tts",
            "transcribe": "/api/transcribe"
        }
    }


@app.post("/api/transcribe")
async def transcribe(request: AudioTranscribeRequest):
    try:
        audio_bytes = base64.b64decode(request.audio_base64)
        text = await transcribe_audio(audio_bytes)
        return {"text": text}
    except Exception as e:
        logger.error(f"Error in transcribe endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat")
async def chat(message: ChatMessage):
    try:
        assistant_response = await send_to_bedrock(
            message.text,
            message.conversation_history
        )
        audio_data = await generate_tts(assistant_response)
        return {"text": assistant_response, "audio_available": True}
    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/tts")
async def text_to_speech(request: TTSRequest):
    try:
        audio_data = await generate_tts(request.text)
        return StreamingResponse(
            io.BytesIO(audio_data),
            media_type="audio/mpeg",
            headers={"Content-Disposition": "attachment; filename=response.mp3"}
        )
    except Exception as e:
        logger.error(f"Error in TTS endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Streaming WebSocket endpoint
    """
    await websocket.accept()
    logger.info("WebSocket connection established")
    
    conversation_history = []
    audio_chunks = []
    
    try:
        while True:
            message = await websocket.receive_json()
            msg_type = message.get("type")
            
            if msg_type == "audio_chunk":
                audio_base64 = message.get("data")
                audio_bytes = base64.b64decode(audio_base64)
                audio_chunks.append(audio_bytes)
                
                await websocket.send_json({
                    "type": "audio_received",
                    "chunks": len(audio_chunks)
                })
                
            elif msg_type == "end_turn":
                if not audio_chunks:
                    await websocket.send_json({
                        "type": "error",
                        "message": "No audio received"
                    })
                    continue
                
                logger.info(f"Processing {len(audio_chunks)} audio chunks")
                full_audio = b''.join(audio_chunks)
                audio_chunks = []
                
                conversation_history_input = message.get("conversation_history", conversation_history)
                
                try:
                    # Step 1: Transcribe
                    text = await transcribe_audio(full_audio)
                    
                    if not text or text.strip() == "":
                        await websocket.send_json({
                            "type": "error",
                            "message": "No speech detected"
                        })
                        continue
                    
                    await websocket.send_json({
                        "type": "transcription",
                        "text": text
                    })
                    
                    # Step 2: Stream LLM
                    await websocket.send_json({"type": "llm_start"})
                    
                    assistant_response = await stream_bedrock_response(
                        text, conversation_history_input, websocket
                    )
                    
                    await websocket.send_json({
                        "type": "llm_complete",
                        "full_text": assistant_response
                    })
                    
                    # Update history
                    conversation_history.append({
                        "role": "user",
                        "content": [{"type": "text", "text": text}]
                    })
                    conversation_history.append({
                        "role": "assistant",
                        "content": [{"type": "text", "text": assistant_response}]
                    })
                    
                    # Step 3: Stream TTS
                    await websocket.send_json({"type": "tts_start"})
                    await stream_tts_generation(assistant_response, websocket)
                    await websocket.send_json({"type": "tts_complete"})
                    
                    await websocket.send_json({
                        "type": "turn_complete",
                        "conversation_history": conversation_history
                    })
                    
                except Exception as e:
                    logger.error(f"Error processing audio: {e}", exc_info=True)
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Processing error: {str(e)}"
                    })
            
            elif msg_type == "text":
                text = message.get("data")
                conversation_history = message.get("conversation_history", conversation_history)
                
                logger.info(f"Received text: {text}")
                
                try:
                    # Stream LLM
                    await websocket.send_json({"type": "llm_start"})
                    
                    assistant_response = await stream_bedrock_response(
                        text, conversation_history, websocket
                    )
                    
                    await websocket.send_json({
                        "type": "llm_complete",
                        "full_text": assistant_response
                    })
                    
                    # Update history
                    conversation_history.append({
                        "role": "user",
                        "content": [{"type": "text", "text": text}]
                    })
                    conversation_history.append({
                        "role": "assistant",
                        "content": [{"type": "text", "text": assistant_response}]
                    })
                    
                    # Stream TTS
                    await websocket.send_json({"type": "tts_start"})
                    await stream_tts_generation(assistant_response, websocket)
                    await websocket.send_json({"type": "tts_complete"})
                    
                    await websocket.send_json({
                        "type": "turn_complete",
                        "conversation_history": conversation_history
                    })
                    
                except Exception as e:
                    logger.error(f"Error processing text: {e}", exc_info=True)
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Processing error: {str(e)}"
                    })
                
            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                
            elif msg_type == "close":
                logger.info("Client requested close")
                break
                
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except:
            pass


@app.get("/api/knowledge-base")
async def get_knowledge_base():
    return {"content": KNOWLEDGE_BASE, "loaded": bool(KNOWLEDGE_BASE)}


@app.post("/api/knowledge-base/reload")
async def reload_knowledge_base():
    global KNOWLEDGE_BASE
    KNOWLEDGE_BASE = load_knowledge_base()
    return {"status": "reloaded", "loaded": bool(KNOWLEDGE_BASE)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")