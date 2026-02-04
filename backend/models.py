
from pydantic import BaseModel 
from typing import Optional 


class ChatMessage(BaseModel):
    text: str
    conversation_history: Optional[list] = []


class TTSRequest(BaseModel):
    text: str


class AudioTranscribeRequest(BaseModel):
    audio_base64: str