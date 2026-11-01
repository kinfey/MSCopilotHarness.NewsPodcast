import asyncio
import os
import subprocess
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

import httpx

from station.http import post_with_retry

VOICES = {
    "cn": {"male": "zh-CN-Wei", "female": "zh-CN-Mei"},
    "en": {"male": "en-US-Grant", "female": "en-US-Harper"},
}
VOICE_TEMPOS = {
    "cn": {"male": 1.25, "female": 1.0},
    "en": {"male": 1.0, "female": 1.0},
}
MAX_SECONDS = 1200


def ssml(text: str, language: str, speaker: str) -> str:
    model = os.environ.get("MAI_MODEL", "MAI-Voice-2.1")
    if model not in ("MAI-Voice-2.1", "MAI-Voice-2.1-Flash"):
        raise ValueError("Unsupported MAI model")
    locale = "zh-CN" if language == "cn" else "en-US"
    voice = VOICES[language][speaker] + ":" + model
    return (
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{locale}">'
        f'<voice name="{voice}">{escape(text)}</voice></speak>'
    )


async def synthesize(text: str, language: str, speaker: str) -> bytes:
    region = os.environ["SPEECH_REGION"]
    if not region.isalnum():
        raise ValueError("Invalid Speech region")
    async with httpx.AsyncClient(timeout=240) as client:
        result = await post_with_retry(
            client,
            f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
            headers={
                "Ocp-Apim-Subscription-Key": os.environ["SPEECH_KEY"],
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm",
                "User-Agent": "Meridian24",
            },
            content=ssml(text, language, speaker).encode(),
        )
        if not result.content.startswith(b"RIFF"):
            raise RuntimeError("Speech endpoint did not return PCM WAV")
        return await asyncio.to_thread(apply_voice_tempo, result.content, language, speaker)


def apply_voice_tempo(wav: bytes, language: str, speaker: str) -> bytes:
    tempo = VOICE_TEMPOS[language][speaker]
    if tempo == 1.0:
        return wav
    # Apply pitch-preserving tempo to the PCM track before measuring story timestamps.
    with tempfile.TemporaryDirectory(prefix="meridian-voice-") as temp:
        output = Path(temp) / "speech.wav"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "wav",
                "-i",
                "pipe:0",
                "-af",
                f"atempo={tempo}",
                "-c:a",
                "pcm_s16le",
                "-ar",
                "24000",
                "-ac",
                "1",
                str(output),
            ],
            input=wav,
            check=True,
            capture_output=True,
        )
        return output.read_bytes()


def duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def check_duration(chapters: list[dict], total: float) -> None:
    if total <= 0 or total > MAX_SECONDS or any(c["duration"] <= 0 or c["duration"] > MAX_SECONDS for c in chapters):
        raise ValueError("Audio exceeds the 20-minute broadcast/section limit or is empty; refuse publication")


async def assemble(paths: list[Path], output: Path) -> float:
    # Only locally generated filenames enter ffmpeg's concat list.
    listing = output.with_suffix(".txt")
    listing.write_text("".join(f"file '{p.name}'\n" for p in paths))

    def encode():
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "1",
                "-i",
                str(listing),
                "-af",
                "loudnorm=I=-16:TP=-1.5:LRA=11",
                "-c:a",
                "aac",
                "-ar",
                "48000",
                "-ac",
                "1",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                "-vn",
                str(output),
            ],
            check=True,
            capture_output=True,
        )
        return duration(output)

    return await asyncio.to_thread(encode)
