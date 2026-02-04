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

load_dotenv()

api_key = os.getenv("ASSEMBLY_API_KEY") 

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

transcribed_texts = []

def on_begin(self: Type[StreamingClient], event: BeginEvent):
    print(f" Session started: {event.id}")

def on_turn(self: Type[StreamingClient], event: TurnEvent):
    if event.end_of_turn and event.turn_is_formatted:
        transcribed_text = event.transcript
        print(f" Transcribed: {transcribed_text}")
    
        # Store it
        transcribed_texts.append(transcribed_text)
    
    if event.end_of_turn and not event.turn_is_formatted:
        params = StreamingSessionParameters(
            format_turns=True,
        )
        self.set_params(params)

def on_terminated(self: Type[StreamingClient], event: TerminationEvent):
    print(f" Session ended: {event.audio_duration_seconds}s of audio processed")
    print(f"\n Full transcription: {' '.join(transcribed_texts)}")

def on_error(self: Type[StreamingClient], error: StreamingError):
    print(f" Error: {error}")

def main():
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

    print(" Speak into your microphone... ")
    
    try:
        # This line captures and transcribes from mic
        client.stream(
            aai.extras.MicrophoneStream(sample_rate=16000)
        )
    except KeyboardInterrupt:
        print("\n Stopping...")
    finally:
        client.disconnect(terminate=True)

if __name__ == "__main__":
    main()