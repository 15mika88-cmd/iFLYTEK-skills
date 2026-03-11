#!/usr/bin/env python3
"""
iFLYTEK IAT (Intelligent Audio Transcription) - Speech to Text
Uses the iFLYTEK Global WebSocket API to transcribe audio files.

Usage:
    python iflytek_asr.py <wav_file> [language_code]

Credentials are loaded from ~/.config/opencode/iflytek_auth.json

Audio MUST be pre-converted to: mono, 16-bit PCM, 8000 or 16000 Hz WAV.
Use ffmpeg before calling this script:
    ffmpeg -i input.mp3 -ar 16000 -ac 1 -acodec pcm_s16le output.wav -y
"""

import asyncio
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import wave
from pathlib import Path
from urllib.parse import quote, urlparse

try:
    import websockets
except ImportError:
    print(
        "ERROR: 'websockets' module not found. Install it with: pip install websockets",
        file=sys.stderr,
    )
    sys.exit(1)

# --- Constants ---
IAT_ENDPOINT = "wss://iat-api-sg.xf-yun.com/v2/iat"
AUTH_CONFIG_NAME = "iflytek_auth.json"
FRAME_SIZE = 12800  # Bulk-send mode: ~800ms per frame at 16kHz
SEND_INTERVAL = 0.005  # Minimal delay between frames to avoid buffer overflow
DEFAULT_LANGUAGE = "zh_cn"


def find_auth_config() -> Path:
    """
    Locate iflytek_auth.json in standard config directories.
    Search order:
      1. ~/.config/opencode/iflytek_auth.json
      2. $APPDATA/opencode/iflytek_auth.json  (Windows fallback)
    """
    candidates = []

    # XDG / Unix-like
    xdg_config = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    candidates.append(Path(xdg_config) / "opencode" / AUTH_CONFIG_NAME)

    # Windows APPDATA
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "opencode" / AUTH_CONFIG_NAME)

    for path in candidates:
        if path.is_file():
            return path

    msg = (
        f"ERROR: Credential file '{AUTH_CONFIG_NAME}' not found.\n"
        f"Searched locations:\n"
        + "\n".join(f"  - {p}" for p in candidates)
        + "\n\nCreate it with the following content:\n"
        '{\n    "appid": "<YOUR_APPID>",\n'
        '    "api_key": "<YOUR_API_KEY>",\n'
        '    "api_secret": "<YOUR_API_SECRET>"\n}'
    )
    print(msg, file=sys.stderr)
    sys.exit(1)


def load_credentials() -> dict:
    """Load and validate iFLYTEK credentials from config file."""
    config_path = find_auth_config()
    with open(config_path, "r", encoding="utf-8") as f:
        creds = json.load(f)

    required_keys = ("appid", "api_key", "api_secret")
    missing = [k for k in required_keys if not creds.get(k)]
    if missing:
        print(
            f"ERROR: Missing keys in {config_path}: {', '.join(missing)}",
            file=sys.stderr,
        )
        sys.exit(1)

    return creds


def generate_auth_url(endpoint: str, api_key: str, api_secret: str) -> str:
    """Build the authenticated WebSocket URL using HMAC-SHA256."""
    parsed = urlparse(endpoint)
    host = parsed.netloc
    path = parsed.path
    date = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())

    sign_string = f"host: {host}\ndate: {date}\nGET {path} HTTP/1.1"
    signature = hmac.new(
        api_secret.encode("utf-8"),
        sign_string.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    signature_b64 = base64.b64encode(signature).decode("utf-8")

    auth_origin = (
        f'api_key="{api_key}", algorithm="hmac-sha256", '
        f'headers="host date request-line", signature="{signature_b64}"'
    )
    authorization = base64.b64encode(auth_origin.encode("utf-8")).decode("utf-8")

    params = (
        f"host={quote(host)}&date={quote(date)}&authorization={quote(authorization)}"
    )
    return f"{endpoint}?{params}"


def read_wav(file_path: str) -> tuple:
    """Read a WAV file and return (raw_pcm_bytes, sample_rate)."""
    with wave.open(file_path, "rb") as wf:
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        framerate = wf.getframerate()
        nframes = wf.getnframes()
        audio_data = wf.readframes(nframes)

    if channels != 1:
        print(
            f"WARNING: Audio has {channels} channels. Expected mono (1 channel).",
            file=sys.stderr,
        )
        print(
            "Please convert first: ffmpeg -i input -ar 16000 -ac 1 -acodec pcm_s16le output.wav -y",
            file=sys.stderr,
        )
    if sample_width != 2:
        print(
            f"WARNING: Sample width is {sample_width * 8}-bit. Expected 16-bit.",
            file=sys.stderr,
        )
    if framerate not in (8000, 16000):
        print(
            f"WARNING: Sample rate is {framerate}Hz. Recommended: 8000 or 16000 Hz.",
            file=sys.stderr,
        )

    return audio_data, framerate


async def recognize(audio_file: str, language: str = DEFAULT_LANGUAGE) -> str:
    """
    Perform speech-to-text recognition via iFLYTEK IAT WebSocket API.
    Returns the transcription text.
    """
    creds = load_credentials()
    auth_url = generate_auth_url(IAT_ENDPOINT, creds["api_key"], creds["api_secret"])
    audio_data, framerate = read_wav(audio_file)

    audio_format = f"audio/L16;rate={framerate}"

    async with websockets.connect(auth_url) as ws:
        # First frame: business params + empty audio
        await ws.send(
            json.dumps(
                {
                    "common": {"app_id": creds["appid"]},
                    "business": {
                        "language": language,
                        "domain": "iat",
                        "ptt": 1,
                    },
                    "data": {
                        "status": 0,
                        "format": audio_format,
                        "encoding": "raw",
                        "audio": "",
                    },
                }
            )
        )

        result_text = ""

        async def sender():
            """Send audio data in bulk frames."""
            for i in range(0, len(audio_data), FRAME_SIZE):
                chunk = audio_data[i : i + FRAME_SIZE]
                status = 2 if i + FRAME_SIZE >= len(audio_data) else 1
                await ws.send(
                    json.dumps(
                        {
                            "data": {
                                "status": status,
                                "format": audio_format,
                                "encoding": "raw",
                                "audio": base64.b64encode(chunk).decode("utf-8"),
                            }
                        }
                    )
                )
                await asyncio.sleep(SEND_INTERVAL)

        async def receiver():
            """Receive and assemble transcription results."""
            nonlocal result_text
            try:
                async for msg in ws:
                    res = json.loads(msg)
                    code = res.get("code")
                    if code != 0:
                        print(
                            f"Server error: code={code}, message={res.get('message')}",
                            file=sys.stderr,
                        )
                        break

                    data = res.get("data", {})
                    if "result" in data and data["result"]:
                        for w_item in data["result"].get("ws", []):
                            for cw in w_item.get("cw", []):
                                result_text += cw.get("w", "")

                    if data.get("status") == 2:
                        break
            except websockets.exceptions.ConnectionClosed:
                pass  # Server closed after final result

        await asyncio.gather(sender(), receiver())

    return result_text


def main():
    if len(sys.argv) < 2:
        print(
            "Usage: python iflytek_asr.py <wav_file> [language_code]", file=sys.stderr
        )
        print(f"Default language: {DEFAULT_LANGUAGE}", file=sys.stderr)
        print(
            "Supported: zh_cn, en_us, ms_my, ja_jp, ko_kr, fr_fr, es_es, ...",
            file=sys.stderr,
        )
        sys.exit(1)

    audio_path = sys.argv[1]
    language = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_LANGUAGE

    if not os.path.isfile(audio_path):
        print(f"ERROR: Audio file not found: {audio_path}", file=sys.stderr)
        sys.exit(1)

    text = asyncio.run(recognize(audio_path, language))
    print(text)


if __name__ == "__main__":
    main()
