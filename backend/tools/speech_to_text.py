import os
import io
from google.cloud import speech_v1p1beta1 as speech
from pydub import AudioSegment
def transcribe_webm(audio_path: str) -> str:
    """
    Convert webm → wav → send to Google STT → return transcript.
    """
    try:
        wav_path = audio_path.replace(".webm", ".wav")
        AudioSegment.from_file(audio_path).export(wav_path, format="wav")
        client = speech.SpeechClient()
        with io.open(wav_path, "rb") as f:
            content = f.read()
        audio = speech.RecognitionAudio(content=content)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=48000,
            language_code="en-US",
            enable_automatic_punctuation=True,
        )
        response = client.recognize(config=config, audio=audio)
        if not response.results:
            return ""
        transcript = response.results[0].alternatives[0].transcript
        return transcript.strip()
    except Exception as e:
        print("STT Error:", e)
        return ""