from deepgram import AsyncDeepgramClient
from deepgram.core.events import EventType
from deepgram.extensions.types.sockets import ListenV2SocketClientResponse 
import pyaudio
from dotenv import load_dotenv 
import os 

load_dotenv() 

async def transcribe():
    RATE = 16000
    CHUNK = 8000
    api_key = os.getenv("DEEPGRAM_API_KEY")
    client = AsyncDeepgramClient(api_key=api_key)

    async with client.listen.v2.connect(
        eot_threshold=0.7,
        eager_eot_threshold=0.5,
        eot_timeout_ms=1000, 
        model="flux-general-en",
        encoding="linear16",
        sample_rate=str(RATE),
    ) as connection:
        
        def on_message(message : ListenV2SocketClientResponse ):
            transcript = message.channel.alternatives[0].transcript
            if transcript:
                print(transcript)
        
        connection.on(EventType.OPEN, lambda _: print("Connection opened"))
        connection.on(EventType.MESSAGE, on_message)
        connection.on(EventType.CLOSE, lambda _: print("Connection closed"))
        connection.on(EventType.ERROR, lambda error: print(f"Error: {error}"))
        
        await connection.start_listening() 
        print("started listening:")
     
        try:
            while True:
                data = stream.read(CHUNK)
                connection.send_media(data)
        except KeyboardInterrupt:
            pass
        finally:
            stream.stop_stream()
            stream.close()
            audio.terminate()