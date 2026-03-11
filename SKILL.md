---
name: iflytek-asr
description: "iFLYTEK speech-to-text skill. Converts audio files to text using iFLYTEK Global IAT (Intelligent Audio Transcription) WebSocket API. Supports multi-language recognition including Chinese, English, Malay, Japanese, Korean, etc. Handles audio format conversion via ffmpeg automatically."
metadata:
  version: 1.0.0
  dependencies: python>=3.10, websockets, ffmpeg(system)
---

# iFLYTEK ASR (Speech-to-Text)

Convert audio files to text using the iFLYTEK Global IAT WebSocket API.

## When to Use

- User asks to transcribe / recognize / convert audio to text
- User mentions iFLYTEK (讯飞) ASR
- User has audio files (.wav, .mp3, .m4a, .flac, .ogg, .amr, .pcm, etc.) that need speech-to-text

## Prerequisites

### 1. Credentials Configuration

Credentials **MUST** be stored in `~/.config/opencode/iflytek_auth.json` (never hardcoded).

Create the file if it does not exist:

```json
{
    "appid": "<YOUR_APPID>",
    "api_key": "<YOUR_API_KEY>",
    "api_secret": "<YOUR_API_SECRET>"
}
```

If the file is missing, prompt the user to provide their iFLYTEK APPID / APIKey / APISecret and create it.

### 2. System Dependencies

Before running recognition, **always check** that required tools are available:

```bash
# Check Python websockets module
python -c "import websockets; print('websockets OK')"

# Check ffmpeg (required for audio format conversion)
ffmpeg -version
```

**If `websockets` is missing**, install it:
```bash
pip install websockets
```

**If `ffmpeg` is missing**, inform the user:
- Windows: Download from https://ffmpeg.org/download.html or `winget install ffmpeg`
- macOS: `brew install ffmpeg`
- Linux: `sudo apt install ffmpeg`

Do NOT proceed without ffmpeg — audio conversion will fail.

## Workflow

### Step 1: Audio Format Conversion

The IAT API requires **mono-channel, 16-bit PCM WAV** at **8000 Hz or 16000 Hz**.

**Always** convert the source audio before recognition:

```bash
ffmpeg -i "<input_audio_path>" -ar 16000 -ac 1 -acodec pcm_s16le "<output_wav_path>" -y
```

- Use a temp file in the current working directory (e.g., `_asr_temp.wav`).
- Clean up the temp file after recognition is complete.

### Step 2: Run Recognition

```bash
python {baseDir}/scripts/iflytek_asr.py "<converted_wav_path>" [language_code]
```

**Arguments:**
- `<converted_wav_path>` — Path to the pre-converted WAV file (from Step 1).
- `[language_code]` — Optional. Defaults to `zh_cn`. Common codes:

| Code    | Language              |
|---------|-----------------------|
| zh_cn   | Chinese (Mandarin)    |
| en_us   | English               |
| ms_my   | Malay                 |
| ja_jp   | Japanese              |
| ko_kr   | Korean                |
| ru_ru   | Russian               |
| fr_fr   | French                |
| es_es   | Spanish               |
| th_th   | Thai                  |
| vi_vn   | Vietnamese            |
| id_id   | Indonesian            |
| ar_sa   | Arabic                |

### Step 3: Output

The script prints the transcription text to stdout.
If the user wants the result saved, redirect or write it to a file.

## Full Example (End-to-End)

```bash
# 1. Check prerequisites
python -c "import websockets; print('OK')"
ffmpeg -version

# 2. Convert audio to compatible format
ffmpeg -i "/path/to/recording.mp3" -ar 16000 -ac 1 -acodec pcm_s16le "_asr_temp.wav" -y

# 3. Recognize (Malay example)
python {baseDir}/scripts/iflytek_asr.py "_asr_temp.wav" ms_my

# 4. Clean up
rm _asr_temp.wav
```

## Error Handling

| Error | Cause | Fix |
|-------|-------|-----|
| `FileNotFoundError: iflytek_auth.json` | Credentials not configured | Ask user for APPID/Key/Secret, create the config file |
| `HTTP 401 Unauthorized` | Wrong or expired credentials | Ask user to verify credentials in iFLYTEK console |
| `ModuleNotFoundError: websockets` | Missing Python dependency | `pip install websockets` |
| `ffmpeg: command not found` | ffmpeg not installed | Guide user to install ffmpeg |
| `no close frame received` | Network instability | Retry the recognition (transient error) |
| `ConnectionAbortedError 10053` | Local firewall / proxy blocking | Check proxy settings, try without VPN |

## API Reference

- **Protocol**: WebSocket (wss)
- **Endpoint**: `wss://iat-api-sg.xf-yun.com/v2/iat` (Singapore node, Global)
- **Auth**: HMAC-SHA256 signature with APIKey + APISecret
- **Audio format**: PCM 16-bit, mono, 8000/16000 Hz
- **Max duration**: ~60 seconds per WebSocket session (for longer audio, the script sends in fast-bulk mode)
- **Official docs**: https://global.xfyun.cn/doc/asr/voicedictation/ost.html
