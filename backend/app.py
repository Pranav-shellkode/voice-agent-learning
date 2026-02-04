from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import JSONResponse
import asyncio
import json
from stt_service import STTService

app = FastAPI()

# Store active sessions
active_sessions = {}

@app.get("/")
async def home():
    return "Sample"


@app.websocket("/ws/transcribe")
async def websocket_transcribe(websocket: WebSocket):
    await websocket.accept()
    session_id = id(websocket)
    
    # Create async queue for audio data
    audio_queue = asyncio.Queue()
    transcript_queue = asyncio.Queue()
    
    # Audio generator for AssemblyAI
    async def audio_generator():
        while True:
            audio_data = await audio_queue.get()
            if audio_data is None:  # Stop signal
                break
            yield audio_data
    
    # Callback to send transcripts back to client
    def on_transcript(text: str):
        asyncio.create_task(
            websocket.send_json({
                "type": "transcript",
                "text": text
            })
        )
    
    # Create STT service
    stt_service = STTService(on_transcript_callback=on_transcript)
    active_sessions[session_id] = stt_service
    
    # Start processing in background
    async def process_audio():
        await asyncio.to_thread(
            stt_service.process_audio_bytes,
            audio_generator()
        )
    
    process_task = asyncio.create_task(process_audio())
    
    try:
        while True:
            # Receive audio from client
            data = await websocket.receive()
            
            if "bytes" in data:
                await audio_queue.put(data["bytes"])
            elif "text" in data:
                msg = json.loads(data["text"])
                if msg.get("type") == "stop":
                    break
                    
    except WebSocketDisconnect:
        print(f"Client {session_id} disconnected")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Cleanup
        await audio_queue.put(None)  # Stop signal
        stt_service.disconnect()
        del active_sessions[session_id]
        await websocket.close()
    return "something"

@app.get("/transcripts/{session_id}")
async def get_transcripts(session_id: int):
    """Get all transcripts for a session"""
    if session_id not in active_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    stt_service = active_sessions[session_id]
    return {"transcripts": stt_service.get_transcripts()}

@app.get("/health")
async def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8080)