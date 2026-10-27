# @title Core types, configuration, and edit planning
from __future__ import annotations

import array
import base64
import contextlib
import dataclasses
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

CORE_VERSION = '1.0.0'
MODEL_REPO = 'audio-cpp/AuK-Base-and-Flash-GGUF'
MODEL_REVISION = '2814a16a49b822a5709e11a78cfd7c1662f19b61'
RUNTIME_TAG = 'v0.9.0'
RUNTIME_COMMIT_PREFIX = '795c45f'
RUNTIME_ASSET = 'audio-v0.9.0-bin-ubuntu-x64-cuda12.8-colab.tar.gz'
RUNTIME_SHA256 = 'c9ed906f918246669c324f0d31f1b7dd80cbe003c35cf8a54932f333b57ca3f6'
RUNTIME_URL = f'https://github.com/0xShug0/audio.cpp/releases/download/{RUNTIME_TAG}/{RUNTIME_ASSET}'
PROFILE_FILES = {
    'base_f32': ('base', 'auk-base-f32.gguf'),
    'flash_f16': ('flash', 'auk-flash-f16.gguf'),
    'base_q8': ('base', 'auk-base-q8_0.gguf'),
}
SHARED_FILES = ('qwen2.5-omni-3b-q8_0.gguf', 'auk-vae-f32.gguf')
SIDECARS = ('config/auk-base.yaml', 'config/auk-flash.yaml',
            'tokenizer/tokenizer.json', 'tokenizer/tokenizer_config.json')
ALLOWED_SUFFIXES = {'.wav', '.mp3', '.flac', '.m4a', '.mp4', '.mov', '.ogg', '.opus', '.webm'}
FORMAT_WHITELIST = 'wav,mp3,flac,mov,matroska,webm,ogg,aac'

class WallClockAbort(Exception):
    """Overall run budget exhausted. Operational stop, not a request failure."""

class EditorError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def atomic_bytes(path: Path, content: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        Path(temporary).unlink(missing_ok=True)


def atomic_json(path: Path, content: Any) -> None:
    atomic_bytes(path, json.dumps(content, ensure_ascii=False, indent=2,
                                 allow_nan=False).encode('utf-8'))


def command(args: list[str], *, timeout: float = 60, cwd: Path | None = None,
            binary: bool = False) -> Any:
    """Never invokes a shell; user-supplied filenames cannot become commands."""
    try:
        result = subprocess.run([str(a) for a in args], cwd=cwd, timeout=timeout,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=False)
    except subprocess.TimeoutExpired as exc:
        raise EditorError('process_timeout', f'{Path(args[0]).name} exceeded {timeout:g}s.') from exc
    except OSError as exc:
        raise EditorError('process_unavailable', f'Could not start {Path(args[0]).name}: {exc}') from exc
    if result.returncode:
        # Bounded diagnostic, no successful subprocess output is placed in job manifests.
        detail = result.stderr.decode(errors='replace')[-1800:]
        raise EditorError('process_failed', f'{Path(args[0]).name} exited {result.returncode}: {detail}')
    return result.stdout if binary else result.stdout.decode('utf-8', errors='replace')


def require_finite(value: float, name: str, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise EditorError('invalid_argument', f'{name} must be a number.') from exc
    if not math.isfinite(number) or not low <= number <= high:
        raise EditorError('invalid_argument', f'{name} must be between {low} and {high}.')
    return number


@dataclasses.dataclass(frozen=True)
class Limits:
    max_upload_bytes: int = 64 * 1024 * 1024
    max_source_seconds: float = 600.0
    max_input_seconds: float = 15.0
    max_output_seconds: float = 20.0
    combined_seconds: float = 30.0  # Conservative application policy, not an audio.cpp guarantee.
    min_audio_seconds: float = 0.5
    ffmpeg_timeout: float = 45.0
    startup_timeout: float = 300.0
    inference_timeout: float = 900.0
    wall_clock_budget_seconds: float | None = None
    response_bytes: int = 8 * 1024 * 1024
    asr_timeout: float = 180.0


# Evidence-bounded application scope for nonverbal_remove (NVDEL-01 probe 2026-10-18,
# binary ec0bf996, source build 795c45f): the runtime accepted a 23.88s input and
# produced exactly 22.0s (combined 45.88s) in 29.75s inference on L4, ASR identical,
# speaker cosine 0.9660. Runtime/vendor limits BEYOND this envelope are unverified; do
# not raise without new probe evidence. Every other operation keeps the default caps.
NVDEL_SCOPE = {'max_input_seconds': 25.0, 'max_output_seconds': 25.0, 'combined_seconds': 50.0}

def scoped_limits(limits: Limits, operation: str) -> Limits:
    if operation == 'nonverbal_remove':
        return dataclasses.replace(limits, **NVDEL_SCOPE)
    return limits


@dataclasses.dataclass(frozen=True)
class EditSpec:
    operation: str = 'custom'
    instruction: str = ''
    emotion: str = 'excited'
    voice_description: str = ''
    old_words: str = ''
    new_words: str = ''
    speed: float = 1.0
    target_seconds: float | None = None
    source_transcript: str = ''
    expected_transcript: str = ''
    seed: int = 42
    sound: str = ''


def _quote_words(text: str) -> str:
    """Take-home prompt style: Replace 'old' with 'new'. Double quotes only when the text has an apostrophe."""
    text = text.strip()
    if "'" not in text:
        return "'" + text + "'"
    if '"' not in text:
        return '"' + text + '"'
    return json.dumps(text, ensure_ascii=False)


def build_plan(spec: EditSpec, duration: float, limits: Limits) -> dict:
    # Per-operation application scope (NVDEL-01 envelope for nonverbal_remove) applies to
    # every build_plan check: input duration, target bounds, and the combined budget.
    limits = scoped_limits(limits, spec.operation)
    duration = require_finite(duration, 'input duration', limits.min_audio_seconds, limits.max_input_seconds)
    if isinstance(spec.seed, bool) or not isinstance(spec.seed, int) or not 0 <= spec.seed < 2**31:
        raise EditorError('invalid_seed', 'Use an integer seed from 0 to 2147483647.')
    for name in ('instruction', 'voice_description', 'old_words', 'new_words',
                 'source_transcript', 'expected_transcript', 'emotion', 'sound'):
        value = getattr(spec, name)
        if not isinstance(value, str) or len(value) > 4000 or '\x00' in value:
            raise EditorError('invalid_text', f'{name} must be text of at most 4,000 characters without NUL.')
    op = spec.operation
    preserve_content = op in {'emotion', 'whisper', 'enhance', 'denoise', 'dereverb', 'voice', 'speed',
                              'nonverbal_remove'}
    prompts = {
        'whisper': 'Speak in a soft whisper, retaining the words and speaker identity.',
        'enhance': 'Clean the speech by reducing noise and room reverberation. Keep all speakers, words, and duration.',
        'denoise': 'Reduce background noise while retaining all speech and the original duration.',
        'dereverb': 'Reduce room reverberation without changing the speech, speaker, or duration.',
    }
    expected = spec.expected_transcript.strip()
    target = duration
    if op == 'emotion':
        if spec.emotion not in {'happy', 'angry', 'sad', 'fearful', 'surprised', 'disgusted', 'calm', 'excited'}:
            raise EditorError('invalid_emotion', 'Choose one of the emotions listed in the form.')
        prompt = f'Change the emotion to {spec.emotion}. Retain the words and speaker identity.'
    elif op in prompts:
        prompt = prompts[op]
    elif op == 'voice':
        if not spec.voice_description.strip():
            raise EditorError('missing_description', 'Enter a voice description, not a named person.')
        prompt = f'Keep the words unchanged. Change the voice character to {json.dumps(spec.voice_description)}.'
    elif op == 'speed':
        speed = require_finite(spec.speed, 'speed', 0.5, 2.0)
        target = duration / speed
        prompt = f'Adjust the speech speed to {speed:g}x.'
        if spec.target_seconds is not None and abs(spec.target_seconds - target) > .02:
            raise EditorError('duration_conflict', 'Speed determines duration. Leave target_seconds at 0 in the form.')
    elif op == 'replace_words':
        if not spec.old_words.strip() or not spec.new_words.strip() or spec.old_words == spec.new_words:
            raise EditorError('invalid_replacement', 'Provide different nonempty old and new words.')
        if not spec.source_transcript.strip():
            raise EditorError('missing_transcript', 'Word replacement requires a human-checked source transcript.')
        if spec.source_transcript.count(spec.old_words) != 1:
            raise EditorError('ambiguous_replacement', 'The old words must occur exactly once in the source transcript. Select a smaller clip for repeated words.')
        derived = spec.source_transcript.replace(spec.old_words, spec.new_words, 1)
        if expected and expected != derived:
            raise EditorError('transcript_conflict', 'Expected transcript disagrees with the specified replacement.')
        expected = derived
        prompt = f'Replace {_quote_words(spec.old_words)} with {_quote_words(spec.new_words)}.'
    elif op == 'nonverbal_remove':
        # Vendor cookbook 4.4 mechanism (verified NVDEL-01 probe 2026-10-18): whole-clip
        # regeneration at an explicit gen_seconds target - a regeneration length, not an
        # excision length. Words are preserved; QA compares against the source transcript.
        sound = spec.sound.strip()
        if not sound:
            raise EditorError('missing_sound', 'Name the nonverbal sound to remove, e.g. humming, breaths, laughs.')
        if spec.target_seconds is None:
            raise EditorError('missing_target', 'nonverbal_remove needs an explicit target_seconds shorter than the input.')
        prompt = f'Remove the {sound} from the audio.'
    elif op == 'custom':
        prompt = spec.instruction.strip()
        if not prompt:
            raise EditorError('missing_instruction', 'Enter an editing instruction.')
    else:
        raise EditorError('unknown_operation', f'Unsupported operation: {op}')
    if spec.target_seconds is not None and op != 'speed':
        if op not in {'custom', 'replace_words', 'nonverbal_remove'} and abs(spec.target_seconds - duration) > .02:
            raise EditorError('duration_conflict', 'This preset preserves duration. Use custom for a duration-changing edit.')
        target = require_finite(spec.target_seconds, 'target_seconds', limits.min_audio_seconds, limits.max_output_seconds)
        if op == 'nonverbal_remove' and target >= duration:
            raise EditorError('duration_conflict', 'nonverbal_remove must shorten the clip; target_seconds must be below the input duration.')
    if preserve_content and spec.source_transcript.strip():
        if expected and expected != spec.source_transcript.strip():
            raise EditorError('transcript_conflict', 'This operation should preserve the source transcript.')
        expected = spec.source_transcript.strip()
    target = math.ceil((target - 1e-9) / .02) * .02
    require_finite(target, 'output duration', limits.min_audio_seconds, limits.max_output_seconds)
    if duration + target > limits.combined_seconds + .001:
        raise EditorError('duration_budget', f'Input + output exceeds the {limits.combined_seconds:g}s application budget. Select a shorter clip.')
    return {'operation': op, 'instruction': prompt, 'target_seconds': round(target, 3),
            'preserve_content': preserve_content, 'expected_transcript': expected, 'seed': spec.seed}


# @title Bounded audio decoding and validation
# --- Bounded media decoding and measurable, non-semantic checks ---

def probe_audio(path: Path, limits: Limits, *, user_upload: bool = True) -> dict:
    path = Path(path).resolve()
    if not path.is_file() or path.stat().st_size == 0:
        raise EditorError('empty_input', 'Input is missing or empty.')
    if path.stat().st_size > limits.max_upload_bytes:
        raise EditorError('upload_too_large', f'Upload exceeds {limits.max_upload_bytes // 2**20} MiB.')
    if user_upload and path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise EditorError('unsupported_format', 'Use WAV, MP3, FLAC, M4A, MP4, MOV, OGG, Opus, or WebM.')
    raw = command(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe',
                   '-format_whitelist', FORMAT_WHITELIST, '-probesize', '5000000',
                   '-analyzeduration', '5000000', '-show_streams', '-show_format', '-of', 'json', str(path)],
                  timeout=limits.ffmpeg_timeout)
    try:
        data = json.loads(raw)
        streams = [s for s in data.get('streams', []) if s.get('codec_type') == 'audio']
        if len(streams) != 1:
            raise EditorError('audio_stream_count', 'Provide exactly one audio track; preselect the desired track for multitrack video.')
        stream = streams[0]
        duration = stream.get('duration', data.get('format', {}).get('duration'))
        if duration in (None, 'N/A'):
            duration = data.get('format', {}).get('duration')
        duration = require_finite(duration, 'media duration', limits.min_audio_seconds, limits.max_source_seconds)
        channels = int(stream['channels'])
        sample_rate = int(stream['sample_rate'])
        if channels not in (1, 2) or not 8000 <= sample_rate <= 192000:
            raise EditorError('unsupported_audio', 'Only mono/stereo audio at 8-192 kHz is accepted.')
        return {'duration_seconds': duration, 'channels': channels, 'sample_rate': sample_rate,
                'has_video': any(s.get('codec_type') == 'video' for s in data['streams']),
                'bytes': path.stat().st_size}
    except (KeyError, ValueError, TypeError) as exc:
        raise EditorError('bad_media_metadata', 'Could not determine valid audio metadata.') from exc


def measure_signal(path: Path, limits: Limits) -> dict:
    raw = command(['ffmpeg', '-hide_banner', '-v', 'error', '-nostdin', '-xerror',
                   '-protocol_whitelist', 'file,pipe', '-format_whitelist', FORMAT_WHITELIST,
                   '-i', str(path), '-map', '0:a:0', '-vn', '-sn', '-dn',
                   '-t', str(limits.max_output_seconds + 1), '-ac', '1', '-ar', '24000',
                   '-f', 'f32le', '-c:a', 'pcm_f32le', 'pipe:1'],
                  timeout=limits.ffmpeg_timeout, binary=True)
    if len(raw) < 4 or len(raw) % 4:
        raise EditorError('bad_pcm', 'Decoded audio is empty or malformed.')
    samples = array.array('f'); samples.frombytes(raw)
    if sys.byteorder != 'little': samples.byteswap()
    if not all(math.isfinite(x) for x in samples):
        raise EditorError('nonfinite_audio', 'Output contains NaN or infinite samples.')
    peak = max(abs(x) for x in samples)
    rms = math.sqrt(math.fsum(x*x for x in samples) / len(samples))
    clip_fraction = sum(abs(x) >= .999 for x in samples) / len(samples)
    return {'frames': len(samples), 'duration_seconds': len(samples)/24000,
            'peak': peak, 'rms_dbfs': 20 * math.log10(max(rms, 1e-12)),
            'near_full_scale_fraction': clip_fraction}


def prepare_audio(source: Path, out: Path, start: float, end: float | None,
                  limits: Limits, channel: str = 'mix') -> dict:
    meta = probe_audio(source, limits)
    start = require_finite(start, 'start_seconds', 0, meta['duration_seconds'])
    end = meta['duration_seconds'] if end is None else require_finite(end, 'end_seconds', 0, meta['duration_seconds'])
    span = end - start
    require_finite(span, 'selected duration', limits.min_audio_seconds, limits.max_input_seconds)
    if channel not in {'mix', 'left', 'right'}:
        raise EditorError('invalid_channel', 'Channel must be mix, left, or right.')
    if meta['channels'] == 1 and channel == 'right':
        raise EditorError('invalid_channel', 'A mono recording does not have a right channel.')
    args = ['ffmpeg', '-hide_banner', '-v', 'error', '-nostdin', '-xerror',
            '-protocol_whitelist', 'file,pipe', '-format_whitelist', FORMAT_WHITELIST,
            '-i', str(source), '-map', '0:a:0', '-vn', '-sn', '-dn',
            '-ss', f'{start:.6f}', '-t', f'{span:.6f}']
    if channel != 'mix':
        args += ['-af', f'pan=mono|c0=c{0 if channel == "left" else 1}']
    args += ['-ac', '1', '-ar', '24000', '-c:a', 'pcm_s16le', '-f', 'wav', '-y', str(out)]
    command(args, timeout=limits.ffmpeg_timeout)
    signal_stats = measure_signal(out, limits)
    if abs(signal_stats['duration_seconds'] - span) > .06:
        raise EditorError('truncated_input', 'Decoded input is shorter than the selected range.')
    if signal_stats['rms_dbfs'] <= -100:
        raise EditorError('silent_input', 'Selected audio is effectively silent. Check the channel/range.')
    warnings = []
    if signal_stats['rms_dbfs'] < -55: warnings.append('Input is very quiet; speech quality is not established.')
    if signal_stats['near_full_scale_fraction'] > .005: warnings.append('Input may already be clipped.')
    if meta['channels'] == 2 and channel == 'mix': warnings.append('Stereo was explicitly downmixed; output is mono.')
    if meta['has_video']: warnings.append('Only the voice track is exported; no video remux or lip-sync guarantee.')
    if start > 0 or end < meta['duration_seconds'] - .02:
        warnings.append('Output is only the selected clip; it is NOT spliced into the original recording.')
    return {'source': meta, 'start_seconds': start, 'end_seconds': end, 'channel': channel,
            'signal': signal_stats, 'warnings': warnings}


def validate_output(path: Path, target: float, limits: Limits) -> dict:
    meta = probe_audio(path, limits, user_upload=False)
    if meta['sample_rate'] != 24000 or meta['channels'] != 1:
        raise EditorError('wrong_output_format', 'Expected a mono 24 kHz output from AuK.')
    if abs(meta['duration_seconds'] - target) > .06:
        raise EditorError('wrong_output_duration', 'Output duration does not match the requested target.')
    stats = measure_signal(path, limits)
    if abs(stats['duration_seconds'] - target) > .06:
        raise EditorError('truncated_output', 'Decoded output is incomplete.')
    if stats['rms_dbfs'] <= -100:
        raise EditorError('silent_output', 'Model returned effectively silent audio.')
    if stats['peak'] > 1.001:
        raise EditorError('out_of_range_output', 'Audio exceeds full scale; output was not silently normalized.')
    warnings = []
    if stats['near_full_scale_fraction'] > .005: warnings.append('Output may contain clipping; listen before approving.')
    if stats['rms_dbfs'] < -55: warnings.append('Output is very quiet; inspect the recording.')
    return {'technical_checks': 'passed', 'signal': stats, 'warnings': warnings,
            'naturalness': 'not_automatically_verified', 'speaker_identity': 'not_automatically_verified'}


def decode_response(response: dict, limits: Limits) -> bytes:
    if not isinstance(response, dict) or not isinstance(response.get('audio'), str):
        raise EditorError('missing_audio', 'Server returned no base64 audio field.')
    encoded = response['audio']
    if len(encoded) > limits.response_bytes:
        raise EditorError('response_too_large', 'Audio response exceeded the configured bound.')
    try:
        content = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise EditorError('invalid_base64', 'Server audio is not valid base64.') from exc
    if len(content) < 44 or content[:4] != b'RIFF' or content[8:12] != b'WAVE':
        raise EditorError('invalid_wav', 'Server did not return a RIFF/WAVE file.')
    return content


def normalized_tokens(text: str) -> list[str]:
    # A documented heuristic, not a multilingual semantic equivalence metric.
    text = unicodedata.normalize('NFKC', text).casefold()
    return re.findall(r"[^\W_]+(?:['’][^\W_]+)?", text, flags=re.UNICODE)


def edit_distance(a: list, b: list) -> int:
    previous = list(range(len(b) + 1))
    for i, left in enumerate(a, 1):
        row = [i]
        for j, right in enumerate(b, 1):
            row.append(min(row[-1]+1, previous[j]+1, previous[j-1]+(left != right)))
        previous = row
    return previous[-1]


def compare_transcript(expected: str, observed: str) -> dict:
    a, b = normalized_tokens(expected), normalized_tokens(observed)
    if not a:
        raise EditorError('empty_expected_text', 'Expected transcript has no comparable characters.')
    wer = edit_distance(a, b) / len(a)
    # Use character comparison for CJK text; English word-error rate is not suitable there.
    is_cjk = any('\u3400' <= c <= '\u9fff' for c in expected)
    if is_cjk:
        a, b = list(''.join(a)), list(''.join(b))
    error = edit_distance(a, b) / max(1, len(a))
    return {'metric': 'character_error_rate' if is_cjk else 'word_error_rate',
            'error_rate': round(error, 4), 'word_error_rate': round(wer, 4),
            'exact_normalized_match': a == b,
            'status': 'no_text_discrepancy_detected' if a == b else 'review_required'}


# @title Local server lifecycle and hard deadlines
# --- Local server lifecycle: single owner, no public tunnel, kill on deadline ---

def process_start_ticks(pid: int) -> str | None:
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def kill_owned_group(pid: int, ticks: str | None) -> None:
    if not ticks or process_start_ticks(pid) != ticks:
        return
    with contextlib.suppress(ProcessLookupError): os.killpg(pid, signal.SIGTERM)
    deadline = time.monotonic() + 4
    while process_start_ticks(pid) == ticks and time.monotonic() < deadline:
        # Zombies have exited and cannot retain GPU memory.
        try:
            if Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0] == 'Z': return
        except OSError: return
        time.sleep(.05)
    if process_start_ticks(pid) == ticks:
        with contextlib.suppress(ProcessLookupError): os.killpg(pid, signal.SIGKILL)


class LocalAuKServer:
    def __init__(self, binary: Path, model_dir: Path, root: Path, limits: Limits, memory_saver: bool):
        self.binary, self.model_dir, self.root = Path(binary).resolve(), Path(model_dir).resolve(), Path(root).resolve()
        self.limits, self.memory_saver = limits, bool(memory_saver)
        self.root.mkdir(parents=True, exist_ok=True)
        self.owner_file = self.root / 'server_owner.json'
        self.process = None; self.log_handle = None; self.profile = None; self.has_run = False
        self.model_id = 'auk-voice-' + uuid.uuid4().hex
        self.url = ''
        self.deadline = None  # monotonic wall-clock stop shared from the worker; None disables
        self.recover_orphan()

    def recover_orphan(self) -> None:
        if not self.owner_file.exists(): return
        info = json.loads(self.owner_file.read_text())
        pid = int(info['pid'])
        # The Editor's process lock is already held. Do not kill unrelated processes.
        try:
            argv = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
            if str(info['config']).encode() in argv:
                kill_owned_group(pid, info.get('start_ticks'))
        except OSError: pass
        self.owner_file.unlink(missing_ok=True)

    def stop(self) -> None:
        if self.process is not None:
            kill_owned_group(self.process.pid, self.start_ticks)
            with contextlib.suppress(subprocess.TimeoutExpired): self.process.wait(timeout=5)
        self.process = None
        if self.log_handle is not None: self.log_handle.close()
        self.log_handle = None; self.profile = None; self.has_run = False
        self.owner_file.unlink(missing_ok=True)

    def _get(self, route: str) -> dict:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(self.url + route, timeout=2) as response:
            return json.loads(response.read(100_000))

    def start(self, profile: str) -> bool:
        if profile not in PROFILE_FILES:
            raise EditorError('unknown_profile', 'Select a supported Base/Flash profile.')
        if self.profile == profile and self.process is not None and self.process.poll() is None:
            return False
        self.stop()
        variant, generator = PROFILE_FILES[profile]
        for name in (generator, *SHARED_FILES, *SIDECARS):
            if not (self.model_dir / name).is_file():
                raise EditorError('missing_model', f'Missing {name}. Rerun the model-download cell for {profile}.')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        self.url = f'http://127.0.0.1:{port}'
        config = {
            'host': '127.0.0.1', 'port': port, 'backend': 'cuda', 'device': 0,
            'threads': 2, 'lazy_load': False, 'max_loaded_models': 1,
            'log_request_body': False, 'max_request_body_bytes': 64 * 1024,
            'models': [{
                'id': self.model_id, 'family': 'auk', 'path': str(self.model_dir),
                'task': 'gen', 'mode': 'offline',
                'session_options': {
                    'auk.variant': variant, 'auk.model_gguf': generator,
                    'auk.qwen_gguf': SHARED_FILES[0], 'auk.vae_gguf': SHARED_FILES[1],
                    'auk.mem_saver': str(self.memory_saver).lower(),
                },
                'default_request_options': {
                    'num_inference_steps': 4 if variant == 'flash' else 32,
                    'guidance_scale': 0.0 if variant == 'flash' else 2.0,
                    'sway_sampling_coef': -1.0,
                },
            }],
        }
        specs = self.binary.parent / 'model_specs' / 'auk.json'
        if specs.is_file(): config['model_spec_override'] = str(specs)
        config_path = self.root / ('server-' + self.model_id + '.json')
        atomic_json(config_path, config)
        log_path = self.root / 'server.log'
        # Bound retained logs: previous startup only; application does not enable --log.
        if log_path.exists(): os.replace(log_path, self.root / 'server.previous.log')
        self.log_handle = log_path.open('wb')
        try:
            self.process = subprocess.Popen([str(self.binary), '--config', str(config_path), '--no-ui'],
                cwd=self.binary.parent, stdin=subprocess.DEVNULL, stdout=self.log_handle,
                stderr=subprocess.STDOUT, start_new_session=True)
            self.start_ticks = process_start_ticks(self.process.pid)
            atomic_json(self.owner_file, {'pid': self.process.pid, 'start_ticks': self.start_ticks,
                                         'config': str(config_path)})
            deadline = time.monotonic() + self.limits.startup_timeout
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise EditorError('server_start_failed', 'AuK server exited at startup. Inspect the private server log; check driver, model hashes, and memory.')
                try:
                    self._get('/health')
                    models = self._get('/v1/models')
                    if any(item.get('id') == self.model_id for item in models.get('data', [])):
                        self.profile = profile; self.has_run = False
                        return True
                except (OSError, ValueError, KeyError): pass
                time.sleep(.4)
            raise EditorError('server_start_timeout', 'Server exceeded its startup deadline; its process was stopped.')
        except BaseException:
            self.stop()
            raise

    def run(self, profile: str, input_path: Path, plan: dict) -> tuple[dict, dict]:
        started = time.monotonic()
        self.start(profile)
        startup_seconds = time.monotonic() - started
        cold = not self.has_run
        payload = {'model': self.model_id, 'request': {
            'audio': str(Path(input_path).resolve()), 'text': plan['instruction'],
            'seed': plan['seed'], 'options': {'duration_sec': plan['target_seconds']}}}
        proc, ticks = self.process, self.start_ticks
        expired = threading.Event()
        effective_timeout = self.limits.inference_timeout
        if self.deadline is not None:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise EditorError('inference_timeout', 'Wall-clock budget exhausted before inference started.')
            effective_timeout = min(effective_timeout, remaining)
        def watchdog():
            expired.set()
            kill_owned_group(proc.pid, ticks)
        timer = threading.Timer(effective_timeout, watchdog)
        timer.daemon = True
        call_started = time.monotonic(); timer.start()
        success = False
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            request = urllib.request.Request(self.url + '/v1/tasks/run',
                data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode(),
                headers={'Content-Type': 'application/json'}, method='POST')
            with opener.open(request, timeout=effective_timeout) as response:
                body = response.read(self.limits.response_bytes + 1)
            if len(body) > self.limits.response_bytes:
                raise EditorError('response_too_large', 'Response exceeded its size bound.')
            if expired.is_set(): raise EditorError('inference_timeout', 'Inference deadline exceeded; worker process stopped.')
            parsed = json.loads(body)
            if not isinstance(parsed, dict): raise EditorError('invalid_response', 'Server returned an invalid response object.')
            success = True; self.has_run = True
            return parsed, {'server_start_seconds': round(startup_seconds, 3),
                            'inference_seconds': round(time.monotonic() - call_started, 3),
                            'first_request_after_start': cold,
                            'memory_saver': self.memory_saver}
        except urllib.error.HTTPError as exc:
            detail = exc.read(16_384).decode(errors='replace').lower()
            oom = any(x in detail for x in ('out of memory', 'cuda_error_out_of_memory', 'insufficient_memory', 'cuda allocation'))
            code = 'out_of_memory' if oom else 'server_http_error'
            message = ('GPU memory was exhausted. Select memory-saving mode or a smaller profile, then explicitly retry.'
                       if oom else f'AuK returned HTTP {exc.code}. Inspect the private server log. No fallback output was substituted.')
            raise EditorError(code, message) from exc
        except (OSError, ValueError) as exc:
            code = 'inference_timeout' if expired.is_set() else 'inference_transport_error'
            raise EditorError(code, 'Inference did not complete; its server process was stopped. An explicit retry is required.') from exc
        finally:
            timer.cancel(); timer.join(timeout=6)
            if not success: self.stop()


# @title Restart-safe jobs, cache integrity, and explicit review
# --- Persistent single-user jobs, idempotency, explicit review, no billing claims ---

class VoiceEditor:
    def __init__(self, root: Path, binary: Path, model_dir: Path, *, memory_saver: bool,
                 provenance: dict, limits: Limits = Limits(), commercial: bool = False,
                 commercial_license_confirmed: bool = False,
                 transport_factory: Callable | None = None, asr: Callable | None = None,
                 asr_fingerprint: str = 'disabled'):
        if commercial and not commercial_license_confirmed:
            raise EditorError('license_not_cleared', 'Commercial use is disabled until the required model licenses are independently cleared.')
        self.root = Path(root).resolve(); self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self.limits, self.provenance = limits, dict(provenance)
        self.provenance.update({'core_version': CORE_VERSION, 'memory_saver': bool(memory_saver),
                                'asr_fingerprint': asr_fingerprint})
        self.asr = asr
        self._mutex = threading.Lock()
        self._lockfile = (self.root / '.worker.lock').open('a+')
        try:
            fcntl.flock(self._lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._lockfile.close()
            raise EditorError('worker_busy', 'Another editor owns this job directory. Stop it before creating another.') from exc
        try:
            self.db = sqlite3.connect(self.root / 'jobs.sqlite3')
            self.db.execute('PRAGMA journal_mode=WAL'); self.db.execute('PRAGMA synchronous=FULL')
            self.db.execute('CREATE TABLE IF NOT EXISTS jobs (job_id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, status TEXT NOT NULL, updated_at TEXT NOT NULL)')
            self.db.commit()
            factory = transport_factory or LocalAuKServer
            self.transport = factory(binary, model_dir, self.root / 'runtime', limits, memory_saver)
            # No in-flight job can remain valid after ownership is reacquired.
            stale = self.db.execute("SELECT job_id FROM jobs WHERE status IN ('queued','running')").fetchall()
            for (job_id,) in stale:
                p = self.root / 'jobs' / job_id / 'manifest.json'
                old = json.loads(p.read_text()) if p.is_file() else {'job_id': job_id}
                old.update({'status': 'interrupted', 'error_code': 'worker_restarted', 'updated_at': utc_now()})
                atomic_json(p, old)
            self.db.execute("UPDATE jobs SET status='interrupted', updated_at=? WHERE status IN ('queued','running')", (utc_now(),))
            self.db.commit()
        except BaseException:
            with contextlib.suppress(Exception): self.db.close()
            fcntl.flock(self._lockfile, fcntl.LOCK_UN); self._lockfile.close()
            raise

    def close(self) -> None:
        if self._lockfile.closed: return
        self.transport.stop(); self.db.close()
        fcntl.flock(self._lockfile, fcntl.LOCK_UN); self._lockfile.close()

    def _save(self, job_dir: Path, manifest: dict, status: str) -> None:
        manifest['status'] = status; manifest['updated_at'] = utc_now()
        atomic_json(job_dir / 'manifest.json', manifest)
        self.db.execute('UPDATE jobs SET status=?, updated_at=? WHERE job_id=?',
                        (status, manifest['updated_at'], manifest['job_id']))
        self.db.commit()

    def edit(self, source: Path, spec: EditSpec, *, profile: str = 'base_f32',
             start_seconds: float = 0, end_seconds: float | None = None, channel: str = 'mix',
             rights_confirmed: bool = False, retry_failed: bool = False,
             allow_unchecked_word_edits: bool = False, cache_namespace: str = '') -> dict:
        if not self._mutex.acquire(blocking=False):
            raise EditorError('worker_busy', 'One edit is already running in this worker.')
        try:
            return self._edit(source, spec, profile=profile, start_seconds=start_seconds,
                              end_seconds=end_seconds, channel=channel, rights_confirmed=rights_confirmed,
                              retry_failed=retry_failed, allow_unchecked_word_edits=allow_unchecked_word_edits,
                              cache_namespace=cache_namespace)
        finally:
            self._mutex.release()

    def _edit(self, source: Path, spec: EditSpec, **options) -> dict:
        if not options['rights_confirmed']:
            raise EditorError('rights_not_confirmed', 'Confirm you are authorized to edit this recording before running it.')
        profile = options['profile']
        if profile not in PROFILE_FILES: raise EditorError('unknown_profile', 'Choose a supported profile.')
        source = Path(source).resolve()
        probe_audio(source, self.limits)  # Fail before hashing/staging a very large/unsupported file.
        if spec.operation == 'replace_words' and self.asr is None and not options['allow_unchecked_word_edits']:
            raise EditorError('asr_required', 'Enable optional ASR QA for word edits, or explicitly allow an unchecked evaluation output.')
        identity = {'source_sha256': sha256_file(source), 'spec': dataclasses.asdict(spec),
                    'profile': profile, 'start': options['start_seconds'], 'end': options['end_seconds'],
                    'channel': options['channel'], 'limits': dataclasses.asdict(self.limits),
                    'provenance': self.provenance, 'cache_namespace': options['cache_namespace']}
        fingerprint = canonical_hash(identity)
        row = self.db.execute('SELECT job_id, status FROM jobs WHERE fingerprint=?', (fingerprint,)).fetchone()
        if row:
            job_id, state = row
            job_dir = self.root / 'jobs' / job_id
            manifest = json.loads((job_dir / 'manifest.json').read_text())
            output = job_dir / 'output.wav'
            if state == 'generated':
                if not output.is_file() or sha256_file(output) != manifest.get('output_sha256'):
                    raise EditorError('corrupt_cached_output', 'Cached output is missing or changed; it was not returned as a valid result.')
                return {**manifest, 'cache_hit': True, 'output_path': str(output), 'job_dir': str(job_dir)}
            if not options['retry_failed']:
                raise EditorError('explicit_retry_required', f'Previous attempt is {state}. Enable retry_failed to rerun the same job.')
        else:
            job_id = uuid.uuid4().hex
            job_dir = self.root / 'jobs' / job_id; job_dir.mkdir(parents=True)
            manifest = {'job_id': job_id, 'fingerprint': fingerprint, 'created_at': utc_now(), 'attempts': 0}
            self.db.execute('INSERT INTO jobs VALUES (?,?,?,?)', (job_id, fingerprint, 'queued', utc_now())); self.db.commit()
        manifest.update({'request': identity, 'attempts': manifest.get('attempts', 0)+1,
                         'human_review': 'pending', 'semantic_validation': 'not_run',
                         'rights_confirmed': True, 'error_code': None})
        output = job_dir / 'output.wav'; output.unlink(missing_ok=True)
        self._save(job_dir, manifest, 'running')
        started = time.monotonic()
        try:
            prepared = job_dir / 'input.wav'
            media = prepare_audio(source, prepared, options['start_seconds'], options['end_seconds'],
                                  self.limits, options['channel'])
            # Source can be a user-managed local path. Detect a change while it was read.
            if sha256_file(source) != identity['source_sha256']:
                raise EditorError('source_changed', 'Source changed during preparation; upload a stable copy and retry.')
            plan = build_plan(spec, media['signal']['duration_seconds'], self.limits)
            manifest['input'] = media; manifest['plan'] = plan
            self._save(job_dir, manifest, 'running')
            qa_started = time.monotonic()
            source_asr = None
            if self.asr is not None and (plan['preserve_content'] or spec.operation == 'replace_words'):
                source_asr = self.asr(prepared)
                if not source_asr.get('text', '').strip():
                    raise EditorError('speech_not_detected', 'ASR did not detect words. Check the clip; this may be an ASR failure.')
                if spec.operation == 'replace_words':
                    source_check = compare_transcript(spec.source_transcript, source_asr['text'])
                    if source_check['error_rate'] > .2:
                        raise EditorError('source_transcript_mismatch', 'ASR substantially disagrees with the supplied transcript; review the clip/transcript before replacing words.')
            manifest['source_asr'] = source_asr
            pre_qa_seconds = time.monotonic() - qa_started
            response, timing = self.transport.run(profile, prepared, plan)
            raw_path = job_dir / 'raw-output.wav'
            atomic_bytes(raw_path, decode_response(response, self.limits))
            quality = validate_output(raw_path, plan['target_seconds'], self.limits)
            # 16-bit WAV export, no loudness normalization, denoiser, TTS, or synthetic fallback.
            temporary = job_dir / 'export.tmp.wav'
            command(['ffmpeg', '-hide_banner', '-v', 'error', '-nostdin', '-xerror', '-i', str(raw_path),
                     '-map', '0:a:0', '-c:a', 'pcm_s16le', '-f', 'wav', '-y', str(temporary)],
                    timeout=self.limits.ffmpeg_timeout)
            validate_output(temporary, plan['target_seconds'], self.limits)
            os.replace(temporary, output)
            raw_path.unlink(missing_ok=True)
            expected = plan['expected_transcript']
            if not expected and source_asr and plan['preserve_content']:
                expected = source_asr['text']
            qa_started = time.monotonic()
            if self.asr is not None and expected:
                output_asr = self.asr(output)
                quality['transcript_check'] = compare_transcript(expected, output_asr.get('text', ''))
                quality['output_asr'] = output_asr
                if spec.operation == 'replace_words':
                    new_tokens = normalized_tokens(spec.new_words)
                    actual = normalized_tokens(output_asr.get('text', ''))
                    present = bool(new_tokens) and any(actual[i:i+len(new_tokens)] == new_tokens for i in range(len(actual)))
                    quality['replacement_detected'] = present
                    if not present: quality['transcript_check']['status'] = 'review_required'
                manifest['semantic_validation'] = quality['transcript_check']['status']
                if manifest['semantic_validation'] == 'review_required':
                    quality['warnings'].append('ASR detected a text discrepancy. Do not treat this output as an approved edit.')
            else:
                manifest['semantic_validation'] = 'not_run'
                quality['warnings'].append('No automatic content check was run. A valid WAV is not proof that the requested edit succeeded.')
            timing['qa_seconds'] = round(pre_qa_seconds + time.monotonic() - qa_started, 3)
            timing['total_seconds'] = round(time.monotonic() - started, 3)
            timing['inference_real_time_factor'] = round(timing['inference_seconds']/plan['target_seconds'], 3)
            manifest.update({'quality': quality, 'timing': timing, 'output_sha256': sha256_file(output),
                             'input_sha256': sha256_file(prepared), 'profile_used': profile,
                             'warnings': media['warnings'] + quality['warnings']})
            self._save(job_dir, manifest, 'generated')
            return {**manifest, 'cache_hit': False, 'output_path': str(output), 'job_dir': str(job_dir)}
        except BaseException as exc:
            # Never leave a stale playable output beside a failed manifest.
            for name in ('output.wav', 'raw-output.wav', 'export.tmp.wav'):
                (job_dir / name).unlink(missing_ok=True)
            manifest['error_code'] = getattr(exc, 'code', type(exc).__name__)
            manifest['elapsed_before_failure_seconds'] = round(time.monotonic() - started, 3)
            self._save(job_dir, manifest, 'interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed')
            raise

    def review(self, job_id: str, *, approved: bool, notes: str = '') -> dict:
        if not re.fullmatch(r'[a-f0-9]{32}', job_id): raise EditorError('invalid_job_id', 'Invalid job ID.')
        job_dir = self.root / 'jobs' / job_id
        row = self.db.execute('SELECT status FROM jobs WHERE job_id=?', (job_id,)).fetchone()
        if not row or row[0] != 'generated': raise EditorError('not_reviewable', 'Only a generated output can be reviewed.')
        manifest = json.loads((job_dir / 'manifest.json').read_text())
        if approved and (not (job_dir/'output.wav').is_file() or sha256_file(job_dir/'output.wav') != manifest['output_sha256']):
            raise EditorError('corrupt_output', 'Output changed since generation; approval blocked.')
        manifest.update({'human_review': 'approved' if approved else 'rejected',
                         'review_notes': str(notes)[:2000], 'reviewed_at': utc_now()})
        self._save(job_dir, manifest, 'generated')
        return manifest


# @title Artifact download and checksum helpers
# Setup helpers: download immutable artifacts, check hashes, and keep a lock manifest.
def download_file(url: str, destination: Path, *, expected_sha256: str | None = None,
                  max_seconds: int = 1800) -> Path:
    if urllib.parse.urlparse(url).scheme != 'https':
        raise EditorError('insecure_download', 'Artifact downloads require HTTPS.')
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and expected_sha256 and sha256_file(destination) == expected_sha256:
        return destination
    partial = destination.with_name(destination.name + '.part')
    # curl can resume a large HF download. A mismatched final digest is never accepted.
    args = ['curl', '--fail', '--location', '--show-error', '--silent', '--proto', '=https',
            '--proto-redir', '=https', '--connect-timeout', '20', '--max-time', str(max_seconds),
            '--retry', '3', '--retry-delay', '2', '--retry-all-errors',
            '--continue-at', '-', '--output', str(partial), url]
    command(args, timeout=max_seconds * 4 + 30)
    if not partial.is_file() or partial.stat().st_size == 0:
        raise EditorError('download_empty', f'Download returned no bytes: {destination.name}')
    if expected_sha256 and sha256_file(partial) != expected_sha256:
        partial.unlink(missing_ok=True)
        raise EditorError('checksum_mismatch', f'Checksum failed for {destination.name}; corrupt partial removed. Rerun setup.')
    os.replace(partial, destination)
    return destination


def fetch_text(url: str, *, limit: int = 2 * 1024 * 1024) -> str:
    req = urllib.request.Request(url, headers={'User-Agent': 'MagicHour-AuK-Colab/1.0'})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                data = response.read(limit + 1)
            if len(data) > limit: raise EditorError('metadata_too_large', 'Metadata exceeded its size bound.')
            return data.decode('utf-8')
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            if attempt < 2: time.sleep(2 ** attempt)
    raise EditorError('metadata_unavailable', 'Could not fetch pinned artifact metadata. Check network access, then rerun setup.') from last


def parse_lfs_pointer(text: str) -> tuple[str, int]:
    digest = re.search(r'^oid sha256:([a-f0-9]{64})$', text, flags=re.MULTILINE)
    size = re.search(r'^size ([0-9]+)$', text, flags=re.MULTILINE)
    if not digest or not size:
        raise EditorError('bad_model_pointer', 'Expected a SHA-256 Git LFS pointer from the pinned model revision.')
    count = int(size.group(1))
    if count <= 0: raise EditorError('bad_model_pointer', 'Model pointer has invalid size.')
    return digest.group(1), count


def safe_extract(archive_path: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    root = target.resolve()
    with tarfile.open(archive_path, 'r:gz') as archive:
        members = archive.getmembers()
        if sum(m.size for m in members) > 4 * 2**30:
            raise EditorError('archive_too_large', 'Runtime archive expands beyond the safety bound.')
        for member in members:
            p = (root / member.name).resolve()
            if p != root and root not in p.parents:
                raise EditorError('unsafe_archive', 'Archive path escapes its destination.')
            if not (member.isfile() or member.isdir()):
                raise EditorError('unsafe_archive', 'Links/devices in runtime archives are not accepted.')
        for member in members:
            archive.extract(member, root, filter='data')


def gpu_details() -> dict:
    row = command(['nvidia-smi', '--query-gpu=name,memory.total,memory.free,compute_cap',
                   '--format=csv,noheader,nounits'], timeout=10).strip().splitlines()[0]
    name, total, free, capability = [part.strip() for part in row.split(',')]
    return {'name': name, 'total_mib': int(total), 'free_mib': int(free), 'compute_capability': capability}


def setup_runtime(root: Path, *, mode: str, gpu: dict) -> tuple[Path, dict]:
    target = root / 'runtime-package'
    lock_path = target / 'runtime.lock.json'
    if mode not in {'t4_prebuilt', 'source_build'}: raise EditorError('bad_setup_mode', 'Select t4_prebuilt or source_build.')
    if mode == 't4_prebuilt' and gpu['compute_capability'] != '7.5':
        raise EditorError('wrong_gpu', 'This prebuilt targets T4/SM75. Select a T4, or choose source_build explicitly for the attached GPU.')
    if lock_path.is_file():
        lock = json.loads(lock_path.read_text())
        binary = Path(lock['binary'])
        if (lock.get('mode') == mode and lock.get('tag') == RUNTIME_TAG
            and lock.get('compute_capability') == gpu['compute_capability']
            and binary.is_file() and sha256_file(binary) == lock.get('binary_sha256')):
            command([str(binary), '--help'], timeout=20)
            return binary, lock
    target.mkdir(parents=True, exist_ok=True)
    if mode == 't4_prebuilt':
        archive = root / RUNTIME_ASSET
        print('Downloading checksum-pinned T4 runtime...')
        download_file(RUNTIME_URL, archive, expected_sha256=RUNTIME_SHA256, max_seconds=300)
        unpacked = target / 'unpacked'
        if unpacked.exists(): shutil.rmtree(unpacked)
        safe_extract(archive, unpacked)
        candidates = [p for p in unpacked.rglob('audiocpp_server') if p.is_file()]
        if len(candidates) != 1: raise EditorError('bad_runtime_archive', 'Expected exactly one server binary.')
        binary = candidates[0]; binary.chmod(0o755)
        extra = {'archive_sha256': RUNTIME_SHA256}
    else:
        if not shutil.which('nvcc'): raise EditorError('cuda_toolkit_missing', 'source_build requires the CUDA development toolkit (nvcc).')
        source = root / 'audio-cpp-source'
        if not (source / '.git').is_dir():
            command(['git', 'clone', '--filter=blob:none', '--no-checkout',
                     'https://github.com/0xShug0/audio.cpp.git', str(source)], timeout=600)
        command(['git', 'fetch', '--depth', '1', 'origin', 'tag', RUNTIME_TAG], cwd=source, timeout=300)
        revision = command(['git', 'rev-parse', f'{RUNTIME_TAG}^{{commit}}'], cwd=source).strip()
        if not re.fullmatch(r'[a-f0-9]{40}', revision) or not revision.startswith(RUNTIME_COMMIT_PREFIX):
            raise EditorError('unexpected_source_commit', 'Release source no longer resolves to the verified commit prefix. Stop and review it.')
        command(['git', 'checkout', '--detach', revision], cwd=source)
        command(['git', '-c', 'url.https://github.com/.insteadOf=git@github.com:',
                 'submodule', 'update', '--init', '--recursive'], cwd=source, timeout=600)
        architecture = gpu['compute_capability'].replace('.', '')
        build = source / ('build-colab-sm' + architecture)
        command(['cmake', '-S', str(source), '-B', str(build), '-DCMAKE_BUILD_TYPE=Release',
                 '-DENGINE_ENABLE_CUDA=ON', '-DENGINE_ENABLE_VULKAN=OFF',
                 '-DENGINE_ENABLE_NATIVE_CPU=OFF', '-DENGINE_BUILD_TESTS=OFF',
                 '-DAUDIOCPP_DEPLOYMENT_BUILD=ON', '-DAUDIOCPP_BUILD_NATIVE_MODEL_MANAGER=OFF',
                 f'-DCMAKE_CUDA_ARCHITECTURES={architecture}'], timeout=600)
        command(['cmake', '--build', str(build), '--parallel', '2', '--target', 'audiocpp_server'], timeout=3600)
        candidates = [p for p in build.rglob('audiocpp_server') if p.is_file()]
        if len(candidates) != 1: raise EditorError('build_missing_binary', 'Build did not produce one server executable.')
        binary = candidates[0]
        extra = {'source_commit': revision}
    command([str(binary), '--help'], timeout=30)
    lock = {'tag': RUNTIME_TAG, 'mode': mode, 'binary': str(binary.resolve()),
            'binary_sha256': sha256_file(binary), 'compute_capability': gpu['compute_capability'],
            'created_at': utc_now(), **extra}
    atomic_json(lock_path, lock)
    return binary.resolve(), lock


def setup_models(root: Path, profiles: list[str]) -> tuple[Path, dict]:
    if not profiles or any(p not in PROFILE_FILES for p in profiles):
        raise EditorError('unknown_profile', 'Choose supported download profiles.')
    directory = root / 'models' / MODEL_REVISION
    directory.mkdir(parents=True, exist_ok=True)
    filenames = sorted({PROFILE_FILES[p][1] for p in profiles} | set(SHARED_FILES))
    remote = f'https://huggingface.co/{MODEL_REPO}'
    specs = {}
    for name in filenames:
        pointer = fetch_text(f'{remote}/raw/{MODEL_REVISION}/{name}', limit=16_384)
        digest, size = parse_lfs_pointer(pointer)
        specs[name] = {'sha256': digest, 'bytes': size}
    missing_size = sum(item['bytes'] for name, item in specs.items() if not (directory/name).is_file())
    if shutil.disk_usage(root).free < missing_size + 2 * 2**30:
        raise EditorError('disk_space', 'Insufficient disk space for the selected weights plus 2 GiB working space.')
    for name, spec in specs.items():
        print(f'Checking/downloading {name} ({spec["bytes"]/2**30:.2f} GiB)...')
        path = download_file(f'{remote}/resolve/{MODEL_REVISION}/{name}', directory/name,
                             expected_sha256=spec['sha256'])
        if path.stat().st_size != spec['bytes']:
            raise EditorError('model_size_mismatch', f'Model size is incorrect: {name}')
    for name in SIDECARS:
        # Immutable model commit fixes sidecar contents; record their hashes as well.
        path = directory / name
        if not path.is_file(): download_file(f'{remote}/resolve/{MODEL_REVISION}/{name}', path, max_seconds=300)
        if path.suffix == '.json': json.loads(path.read_text())
        specs[name] = {'sha256': sha256_file(path), 'bytes': path.stat().st_size}
    lock = {'repo': MODEL_REPO, 'revision': MODEL_REVISION, 'files': specs}
    atomic_json(directory / 'model.lock.json', lock)
    return directory, lock


# @title Optional isolated CPU speech QA helpers
# Optional CPU-only speech QA. Its isolated environment never imports Torch into this notebook.
ASR_MODEL_REPO = 'Systran/faster-whisper-small'
ASR_MODEL_REVISION = '536b0662742c02347bc0e980a01041f333bce120'
ASR_SCRIPT = r'''
import json, os, sys
os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
os.environ['HF_HUB_OFFLINE'] = '1'
from faster_whisper import WhisperModel
model_path, audio_path, output_path, language = sys.argv[1:]
model = WhisperModel(model_path, device='cpu', compute_type='int8', cpu_threads=2,
                     num_workers=1, local_files_only=True)
segments, info = model.transcribe(audio_path, beam_size=3, temperature=0,
    condition_on_previous_text=False, vad_filter=True, word_timestamps=True,
    language=None if language == 'auto' else language)
segments = list(segments)
result = {
    'text': ' '.join(s.text.strip() for s in segments).strip(),
    'language': info.language, 'language_probability': float(info.language_probability),
    'words': [{'word': w.word, 'start': w.start, 'end': w.end,
               'probability': float(w.probability)} for s in segments for w in (s.words or [])],
}
with open(output_path, 'w', encoding='utf-8') as stream:
    json.dump(result, stream, ensure_ascii=False, allow_nan=False)
'''


def make_venv(env: Path) -> Path:
    """Create an isolated venv even where ensurepip is broken (Colab, Python 3.13)."""
    py = env / 'bin/python'
    if py.is_file():
        try:
            command([str(py), '-m', 'pip', '--version'], timeout=30)
            return py
        except EditorError:
            command([sys.executable, '-m', 'pip', '--python', str(py), 'install', '--quiet', 'pip'], timeout=300)
            command([str(py), '-m', 'pip', '--version'], timeout=30)
            return py
    try:
        command([sys.executable, '-m', 'venv', str(env)], timeout=180)
        command([str(py), '-m', 'pip', '--version'], timeout=30)
        return py
    except EditorError:
        shutil.rmtree(env, ignore_errors=True)
    command([sys.executable, '-m', 'venv', '--without-pip', str(env)], timeout=120)
    try:
        command([sys.executable, '-m', 'pip', '--python', str(py), 'install',
                 '--disable-pip-version-check', '--quiet', 'pip'], timeout=300)
    except EditorError:
        command(['uv', 'pip', 'install', '--python', str(py), 'pip'], timeout=300)
    command([str(py), '-m', 'pip', '--version'], timeout=30)
    return py


def setup_asr(root: Path, limits: Limits, language: str = 'auto') -> tuple[Callable, str]:
    if not re.fullmatch(r'auto|[a-z]{2,3}', language):
        raise EditorError('invalid_language', 'ASR language should be auto or an ISO language code such as en or zh.')
    qa_root = root / 'speech-qa'; qa_root.mkdir(parents=True, exist_ok=True)
    env = qa_root / 'venv'; py = env / 'bin/python'
    freeze_path = qa_root / 'requirements.lock.txt'
    fresh_environment = not py.is_file()
    py = make_venv(env)
    if fresh_environment and freeze_path.is_file():
        command([str(py), '-m', 'pip', 'install', '--disable-pip-version-check', '--quiet', '-r', str(freeze_path)], timeout=900)
    if not freeze_path.is_file():
        command([str(py), '-m', 'pip', 'install', '--disable-pip-version-check',
                 '--quiet', 'faster-whisper==1.2.1', 'av==16.0.0', 'ctranslate2==4.6.0', 'huggingface-hub==0.35.3', 'tokenizers==0.22.1', 'onnxruntime==1.23.1', 'numpy==2.3.3'], timeout=900)
        frozen = command([str(py), '-m', 'pip', 'freeze'], timeout=30)
        atomic_bytes(freeze_path, frozen.encode())
    else:
        actual = command([str(py), '-m', 'pip', 'freeze'], timeout=30)
        if actual.strip() != freeze_path.read_text().strip():
            raise EditorError('qa_environment_changed', 'QA environment changed from its saved package lock. Recreate it explicitly before running.')
    command([str(py), '-m', 'pip', 'check'], timeout=30)
    model = qa_root / ASR_MODEL_REVISION; model.mkdir(exist_ok=True)
    remote = f'https://huggingface.co/{ASR_MODEL_REPO}'
    digest, size = parse_lfs_pointer(fetch_text(f'{remote}/raw/{ASR_MODEL_REVISION}/model.bin',limit=16_384))
    download_file(f'{remote}/resolve/{ASR_MODEL_REVISION}/model.bin', model/'model.bin', expected_sha256=digest)
    for name in ('config.json', 'tokenizer.json', 'vocabulary.txt'):
        if not (model/name).is_file(): download_file(f'{remote}/resolve/{ASR_MODEL_REVISION}/{name}',model/name,max_seconds=300)
    hashes = {p.name: sha256_file(p) for p in model.iterdir() if p.is_file()}
    script = qa_root / 'transcribe_local.py'; atomic_bytes(script, ASR_SCRIPT.encode())
    fingerprint = canonical_hash({'model': ASR_MODEL_REVISION, 'files': hashes,
                                  'requirements': freeze_path.read_text(), 'script': sha256_file(script),
                                  'language': language})
    atomic_json(qa_root/'qa.lock.json',{'revision':ASR_MODEL_REVISION,'fingerprint':fingerprint,
                                      'files':hashes,'language':language})
    def transcribe(path: Path) -> dict:
        fd, name = tempfile.mkstemp(suffix='.json', dir=qa_root); os.close(fd)
        out = Path(name)
        try:
            command([str(py), str(script), str(model), str(Path(path).resolve()), str(out), language],
                    timeout=limits.asr_timeout)
            value = json.loads(out.read_text())
            if not isinstance(value.get('text'),str): raise EditorError('invalid_asr_result','ASR did not return text.')
            return value
        finally:
            out.unlink(missing_ok=True)
    return transcribe, fingerprint
# @title Core types, configuration, and edit planning
from __future__ import annotations

import array
import base64
import contextlib
import dataclasses
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

CORE_VERSION = '1.0.0'
MODEL_REPO = 'audio-cpp/AuK-Base-and-Flash-GGUF'
MODEL_REVISION = '2814a16a49b822a5709e11a78cfd7c1662f19b61'
RUNTIME_TAG = 'v0.9.0'
RUNTIME_COMMIT_PREFIX = '795c45f'
RUNTIME_ASSET = 'audio-v0.9.0-bin-ubuntu-x64-cuda12.8-colab.tar.gz'
RUNTIME_SHA256 = 'c9ed906f918246669c324f0d31f1b7dd80cbe003c35cf8a54932f333b57ca3f6'
RUNTIME_URL = f'https://github.com/0xShug0/audio.cpp/releases/download/{RUNTIME_TAG}/{RUNTIME_ASSET}'
PROFILE_FILES = {
    'base_f32': ('base', 'auk-base-f32.gguf'),
    'flash_f16': ('flash', 'auk-flash-f16.gguf'),
    'base_q8': ('base', 'auk-base-q8_0.gguf'),
}
SHARED_FILES = ('qwen2.5-omni-3b-q8_0.gguf', 'auk-vae-f32.gguf')
SIDECARS = ('config/auk-base.yaml', 'config/auk-flash.yaml',
            'tokenizer/tokenizer.json', 'tokenizer/tokenizer_config.json')
ALLOWED_SUFFIXES = {'.wav', '.mp3', '.flac', '.m4a', '.mp4', '.mov', '.ogg', '.opus', '.webm'}
FORMAT_WHITELIST = 'wav,mp3,flac,mov,matroska,webm,ogg,aac'

class WallClockAbort(Exception):
    """Overall run budget exhausted. Operational stop, not a request failure."""

class EditorError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def atomic_bytes(path: Path, content: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        Path(temporary).unlink(missing_ok=True)


def atomic_json(path: Path, content: Any) -> None:
    atomic_bytes(path, json.dumps(content, ensure_ascii=False, indent=2,
                                 allow_nan=False).encode('utf-8'))


def command(args: list[str], *, timeout: float = 60, cwd: Path | None = None,
            binary: bool = False) -> Any:
    """Never invokes a shell; user-supplied filenames cannot become commands."""
    try:
        result = subprocess.run([str(a) for a in args], cwd=cwd, timeout=timeout,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=False)
    except subprocess.TimeoutExpired as exc:
        raise EditorError('process_timeout', f'{Path(args[0]).name} exceeded {timeout:g}s.') from exc
    except OSError as exc:
        raise EditorError('process_unavailable', f'Could not start {Path(args[0]).name}: {exc}') from exc
    if result.returncode:
        # Bounded diagnostic, no successful subprocess output is placed in job manifests.
        detail = result.stderr.decode(errors='replace')[-1800:]
        raise EditorError('process_failed', f'{Path(args[0]).name} exited {result.returncode}: {detail}')
    return result.stdout if binary else result.stdout.decode('utf-8', errors='replace')


def require_finite(value: float, name: str, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise EditorError('invalid_argument', f'{name} must be a number.') from exc
    if not math.isfinite(number) or not low <= number <= high:
        raise EditorError('invalid_argument', f'{name} must be between {low} and {high}.')
    return number


@dataclasses.dataclass(frozen=True)
class Limits:
    max_upload_bytes: int = 64 * 1024 * 1024
    max_source_seconds: float = 600.0
    max_input_seconds: float = 15.0
    max_output_seconds: float = 20.0
    combined_seconds: float = 30.0  # Conservative application policy, not an audio.cpp guarantee.
    min_audio_seconds: float = 0.5
    ffmpeg_timeout: float = 45.0
    startup_timeout: float = 300.0
    inference_timeout: float = 900.0
    wall_clock_budget_seconds: float | None = None
    response_bytes: int = 8 * 1024 * 1024
    asr_timeout: float = 180.0


# Evidence-bounded application scope for nonverbal_remove (NVDEL-01 probe 2026-10-18,
# binary ec0bf996, source build 795c45f): the runtime accepted a 23.88s input and
# produced exactly 22.0s (combined 45.88s) in 29.75s inference on L4, ASR identical,
# speaker cosine 0.9660. Runtime/vendor limits BEYOND this envelope are unverified; do
# not raise without new probe evidence. Every other operation keeps the default caps.
NVDEL_SCOPE = {'max_input_seconds': 25.0, 'max_output_seconds': 25.0, 'combined_seconds': 50.0}

def scoped_limits(limits: Limits, operation: str) -> Limits:
    if operation == 'nonverbal_remove':
        return dataclasses.replace(limits, **NVDEL_SCOPE)
    return limits


@dataclasses.dataclass(frozen=True)
class EditSpec:
    operation: str = 'custom'
    instruction: str = ''
    emotion: str = 'excited'
    voice_description: str = ''
    old_words: str = ''
    new_words: str = ''
    speed: float = 1.0
    target_seconds: float | None = None
    source_transcript: str = ''
    expected_transcript: str = ''
    seed: int = 42
    sound: str = ''


def _quote_words(text: str) -> str:
    """Take-home prompt style: Replace 'old' with 'new'. Double quotes only when the text has an apostrophe."""
    text = text.strip()
    if "'" not in text:
        return "'" + text + "'"
    if '"' not in text:
        return '"' + text + '"'
    return json.dumps(text, ensure_ascii=False)


def build_plan(spec: EditSpec, duration: float, limits: Limits) -> dict:
    duration = require_finite(duration, 'input duration', limits.min_audio_seconds, limits.max_input_seconds)
    if isinstance(spec.seed, bool) or not isinstance(spec.seed, int) or not 0 <= spec.seed < 2**31:
        raise EditorError('invalid_seed', 'Use an integer seed from 0 to 2147483647.')
    for name in ('instruction', 'voice_description', 'old_words', 'new_words',
                 'source_transcript', 'expected_transcript', 'emotion', 'sound'):
        value = getattr(spec, name)
        if not isinstance(value, str) or len(value) > 4000 or '\x00' in value:
            raise EditorError('invalid_text', f'{name} must be text of at most 4,000 characters without NUL.')
    op = spec.operation
    preserve_content = op in {'emotion', 'whisper', 'enhance', 'denoise', 'dereverb', 'voice', 'speed',
                              'nonverbal_remove'}
    prompts = {
        'whisper': 'Speak in a soft whisper, retaining the words and speaker identity.',
        'enhance': 'Clean the speech by reducing noise and room reverberation. Keep all speakers, words, and duration.',
        'denoise': 'Reduce background noise while retaining all speech and the original duration.',
        'dereverb': 'Reduce room reverberation without changing the speech, speaker, or duration.',
    }
    expected = spec.expected_transcript.strip()
    target = duration
    if op == 'emotion':
        if spec.emotion not in {'happy', 'angry', 'sad', 'fearful', 'surprised', 'disgusted', 'calm', 'excited'}:
            raise EditorError('invalid_emotion', 'Choose one of the emotions listed in the form.')
        prompt = f'Change the emotion to {spec.emotion}. Retain the words and speaker identity.'
    elif op in prompts:
        prompt = prompts[op]
    elif op == 'voice':
        if not spec.voice_description.strip():
            raise EditorError('missing_description', 'Enter a voice description, not a named person.')
        prompt = f'Keep the words unchanged. Change the voice character to {json.dumps(spec.voice_description)}.'
    elif op == 'speed':
        speed = require_finite(spec.speed, 'speed', 0.5, 2.0)
        target = duration / speed
        prompt = f'Adjust the speech speed to {speed:g}x.'
        if spec.target_seconds is not None and abs(spec.target_seconds - target) > .02:
            raise EditorError('duration_conflict', 'Speed determines duration. Leave target_seconds at 0 in the form.')
    elif op == 'replace_words':
        if not spec.old_words.strip() or not spec.new_words.strip() or spec.old_words == spec.new_words:
            raise EditorError('invalid_replacement', 'Provide different nonempty old and new words.')
        if not spec.source_transcript.strip():
            raise EditorError('missing_transcript', 'Word replacement requires a human-checked source transcript.')
        if spec.source_transcript.count(spec.old_words) != 1:
            raise EditorError('ambiguous_replacement', 'The old words must occur exactly once in the source transcript. Select a smaller clip for repeated words.')
        derived = spec.source_transcript.replace(spec.old_words, spec.new_words, 1)
        if expected and expected != derived:
            raise EditorError('transcript_conflict', 'Expected transcript disagrees with the specified replacement.')
        expected = derived
        prompt = f'Replace {_quote_words(spec.old_words)} with {_quote_words(spec.new_words)}.'
    elif op == 'nonverbal_remove':
        # Vendor cookbook 4.4 mechanism (verified NVDEL-01 probe 2026-10-18): whole-clip
        # regeneration at an explicit gen_seconds target - a regeneration length, not an
        # excision length. Words are preserved; QA compares against the source transcript.
        sound = spec.sound.strip()
        if not sound:
            raise EditorError('missing_sound', 'Name the nonverbal sound to remove, e.g. humming, breaths, laughs.')
        if spec.target_seconds is None:
            raise EditorError('missing_target', 'nonverbal_remove needs an explicit target_seconds shorter than the input.')
        prompt = f'Remove the {sound} from the audio.'
    elif op == 'custom':
        prompt = spec.instruction.strip()
        if not prompt:
            raise EditorError('missing_instruction', 'Enter an editing instruction.')
    else:
        raise EditorError('unknown_operation', f'Unsupported operation: {op}')
    if spec.target_seconds is not None and op != 'speed':
        if op not in {'custom', 'replace_words', 'nonverbal_remove'} and abs(spec.target_seconds - duration) > .02:
            raise EditorError('duration_conflict', 'This preset preserves duration. Use custom for a duration-changing edit.')
        target = require_finite(spec.target_seconds, 'target_seconds', limits.min_audio_seconds, limits.max_output_seconds)
        if op == 'nonverbal_remove' and target >= duration:
            raise EditorError('duration_conflict', 'nonverbal_remove must shorten the clip; target_seconds must be below the input duration.')
    if preserve_content and spec.source_transcript.strip():
        if expected and expected != spec.source_transcript.strip():
            raise EditorError('transcript_conflict', 'This operation should preserve the source transcript.')
        expected = spec.source_transcript.strip()
    target = math.ceil((target - 1e-9) / .02) * .02
    require_finite(target, 'output duration', limits.min_audio_seconds, limits.max_output_seconds)
    if duration + target > limits.combined_seconds + .001:
        raise EditorError('duration_budget', f'Input + output exceeds the {limits.combined_seconds:g}s application budget. Select a shorter clip.')
    return {'operation': op, 'instruction': prompt, 'target_seconds': round(target, 3),
            'preserve_content': preserve_content, 'expected_transcript': expected, 'seed': spec.seed}


# @title Bounded audio decoding and validation
# --- Bounded media decoding and measurable, non-semantic checks ---

def probe_audio(path: Path, limits: Limits, *, user_upload: bool = True) -> dict:
    path = Path(path).resolve()
    if not path.is_file() or path.stat().st_size == 0:
        raise EditorError('empty_input', 'Input is missing or empty.')
    if path.stat().st_size > limits.max_upload_bytes:
        raise EditorError('upload_too_large', f'Upload exceeds {limits.max_upload_bytes // 2**20} MiB.')
    if user_upload and path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise EditorError('unsupported_format', 'Use WAV, MP3, FLAC, M4A, MP4, MOV, OGG, Opus, or WebM.')
    raw = command(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe',
                   '-format_whitelist', FORMAT_WHITELIST, '-probesize', '5000000',
                   '-analyzeduration', '5000000', '-show_streams', '-show_format', '-of', 'json', str(path)],
                  timeout=limits.ffmpeg_timeout)
    try:
        data = json.loads(raw)
        streams = [s for s in data.get('streams', []) if s.get('codec_type') == 'audio']
        if len(streams) != 1:
            raise EditorError('audio_stream_count', 'Provide exactly one audio track; preselect the desired track for multitrack video.')
        stream = streams[0]
        duration = stream.get('duration', data.get('format', {}).get('duration'))
        if duration in (None, 'N/A'):
            duration = data.get('format', {}).get('duration')
        duration = require_finite(duration, 'media duration', limits.min_audio_seconds, limits.max_source_seconds)
        channels = int(stream['channels'])
        sample_rate = int(stream['sample_rate'])
        if channels not in (1, 2) or not 8000 <= sample_rate <= 192000:
            raise EditorError('unsupported_audio', 'Only mono/stereo audio at 8-192 kHz is accepted.')
        return {'duration_seconds': duration, 'channels': channels, 'sample_rate': sample_rate,
                'has_video': any(s.get('codec_type') == 'video' for s in data['streams']),
                'bytes': path.stat().st_size}
    except (KeyError, ValueError, TypeError) as exc:
        raise EditorError('bad_media_metadata', 'Could not determine valid audio metadata.') from exc


def measure_signal(path: Path, limits: Limits) -> dict:
    raw = command(['ffmpeg', '-hide_banner', '-v', 'error', '-nostdin', '-xerror',
                   '-protocol_whitelist', 'file,pipe', '-format_whitelist', FORMAT_WHITELIST,
                   '-i', str(path), '-map', '0:a:0', '-vn', '-sn', '-dn',
                   '-t', str(limits.max_output_seconds + 1), '-ac', '1', '-ar', '24000',
                   '-f', 'f32le', '-c:a', 'pcm_f32le', 'pipe:1'],
                  timeout=limits.ffmpeg_timeout, binary=True)
    if len(raw) < 4 or len(raw) % 4:
        raise EditorError('bad_pcm', 'Decoded audio is empty or malformed.')
    samples = array.array('f'); samples.frombytes(raw)
    if sys.byteorder != 'little': samples.byteswap()
    if not all(math.isfinite(x) for x in samples):
        raise EditorError('nonfinite_audio', 'Output contains NaN or infinite samples.')
    peak = max(abs(x) for x in samples)
    rms = math.sqrt(math.fsum(x*x for x in samples) / len(samples))
    clip_fraction = sum(abs(x) >= .999 for x in samples) / len(samples)
    return {'frames': len(samples), 'duration_seconds': len(samples)/24000,
            'peak': peak, 'rms_dbfs': 20 * math.log10(max(rms, 1e-12)),
            'near_full_scale_fraction': clip_fraction}


def prepare_audio(source: Path, out: Path, start: float, end: float | None,
                  limits: Limits, channel: str = 'mix') -> dict:
    meta = probe_audio(source, limits)
    start = require_finite(start, 'start_seconds', 0, meta['duration_seconds'])
    end = meta['duration_seconds'] if end is None else require_finite(end, 'end_seconds', 0, meta['duration_seconds'])
    span = end - start
    require_finite(span, 'selected duration', limits.min_audio_seconds, limits.max_input_seconds)
    if channel not in {'mix', 'left', 'right'}:
        raise EditorError('invalid_channel', 'Channel must be mix, left, or right.')
    if meta['channels'] == 1 and channel == 'right':
        raise EditorError('invalid_channel', 'A mono recording does not have a right channel.')
    args = ['ffmpeg', '-hide_banner', '-v', 'error', '-nostdin', '-xerror',
            '-protocol_whitelist', 'file,pipe', '-format_whitelist', FORMAT_WHITELIST,
            '-i', str(source), '-map', '0:a:0', '-vn', '-sn', '-dn',
            '-ss', f'{start:.6f}', '-t', f'{span:.6f}']
    if channel != 'mix':
        args += ['-af', f'pan=mono|c0=c{0 if channel == "left" else 1}']
    args += ['-ac', '1', '-ar', '24000', '-c:a', 'pcm_s16le', '-f', 'wav', '-y', str(out)]
    command(args, timeout=limits.ffmpeg_timeout)
    signal_stats = measure_signal(out, limits)
    if abs(signal_stats['duration_seconds'] - span) > .06:
        raise EditorError('truncated_input', 'Decoded input is shorter than the selected range.')
    if signal_stats['rms_dbfs'] <= -100:
        raise EditorError('silent_input', 'Selected audio is effectively silent. Check the channel/range.')
    warnings = []
    if signal_stats['rms_dbfs'] < -55: warnings.append('Input is very quiet; speech quality is not established.')
    if signal_stats['near_full_scale_fraction'] > .005: warnings.append('Input may already be clipped.')
    if meta['channels'] == 2 and channel == 'mix': warnings.append('Stereo was explicitly downmixed; output is mono.')
    if meta['has_video']: warnings.append('Only the voice track is exported; no video remux or lip-sync guarantee.')
    if start > 0 or end < meta['duration_seconds'] - .02:
        warnings.append('Output is only the selected clip; it is NOT spliced into the original recording.')
    return {'source': meta, 'start_seconds': start, 'end_seconds': end, 'channel': channel,
            'signal': signal_stats, 'warnings': warnings}


def validate_output(path: Path, target: float, limits: Limits) -> dict:
    meta = probe_audio(path, limits, user_upload=False)
    if meta['sample_rate'] != 24000 or meta['channels'] != 1:
        raise EditorError('wrong_output_format', 'Expected a mono 24 kHz output from AuK.')
    if abs(meta['duration_seconds'] - target) > .06:
        raise EditorError('wrong_output_duration', 'Output duration does not match the requested target.')
    stats = measure_signal(path, limits)
    if abs(stats['duration_seconds'] - target) > .06:
        raise EditorError('truncated_output', 'Decoded output is incomplete.')
    if stats['rms_dbfs'] <= -100:
        raise EditorError('silent_output', 'Model returned effectively silent audio.')
    if stats['peak'] > 1.001:
        raise EditorError('out_of_range_output', 'Audio exceeds full scale; output was not silently normalized.')
    warnings = []
    if stats['near_full_scale_fraction'] > .005: warnings.append('Output may contain clipping; listen before approving.')
    if stats['rms_dbfs'] < -55: warnings.append('Output is very quiet; inspect the recording.')
    return {'technical_checks': 'passed', 'signal': stats, 'warnings': warnings,
            'naturalness': 'not_automatically_verified', 'speaker_identity': 'not_automatically_verified'}


def decode_response(response: dict, limits: Limits) -> bytes:
    if not isinstance(response, dict) or not isinstance(response.get('audio'), str):
        raise EditorError('missing_audio', 'Server returned no base64 audio field.')
    encoded = response['audio']
    if len(encoded) > limits.response_bytes:
        raise EditorError('response_too_large', 'Audio response exceeded the configured bound.')
    try:
        content = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise EditorError('invalid_base64', 'Server audio is not valid base64.') from exc
    if len(content) < 44 or content[:4] != b'RIFF' or content[8:12] != b'WAVE':
        raise EditorError('invalid_wav', 'Server did not return a RIFF/WAVE file.')
    return content


def normalized_tokens(text: str) -> list[str]:
    # A documented heuristic, not a multilingual semantic equivalence metric.
    text = unicodedata.normalize('NFKC', text).casefold()
    return re.findall(r"[^\W_]+(?:['’][^\W_]+)?", text, flags=re.UNICODE)


def edit_distance(a: list, b: list) -> int:
    previous = list(range(len(b) + 1))
    for i, left in enumerate(a, 1):
        row = [i]
        for j, right in enumerate(b, 1):
            row.append(min(row[-1]+1, previous[j]+1, previous[j-1]+(left != right)))
        previous = row
    return previous[-1]


def compare_transcript(expected: str, observed: str) -> dict:
    a, b = normalized_tokens(expected), normalized_tokens(observed)
    if not a:
        raise EditorError('empty_expected_text', 'Expected transcript has no comparable characters.')
    wer = edit_distance(a, b) / len(a)
    # Use character comparison for CJK text; English word-error rate is not suitable there.
    is_cjk = any('\u3400' <= c <= '\u9fff' for c in expected)
    if is_cjk:
        a, b = list(''.join(a)), list(''.join(b))
    error = edit_distance(a, b) / max(1, len(a))
    return {'metric': 'character_error_rate' if is_cjk else 'word_error_rate',
            'error_rate': round(error, 4), 'word_error_rate': round(wer, 4),
            'exact_normalized_match': a == b,
            'status': 'no_text_discrepancy_detected' if a == b else 'review_required'}


# @title Local server lifecycle and hard deadlines
# --- Local server lifecycle: single owner, no public tunnel, kill on deadline ---

def process_start_ticks(pid: int) -> str | None:
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def kill_owned_group(pid: int, ticks: str | None) -> None:
    if not ticks or process_start_ticks(pid) != ticks:
        return
    with contextlib.suppress(ProcessLookupError): os.killpg(pid, signal.SIGTERM)
    deadline = time.monotonic() + 4
    while process_start_ticks(pid) == ticks and time.monotonic() < deadline:
        # Zombies have exited and cannot retain GPU memory.
        try:
            if Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0] == 'Z': return
        except OSError: return
        time.sleep(.05)
    if process_start_ticks(pid) == ticks:
        with contextlib.suppress(ProcessLookupError): os.killpg(pid, signal.SIGKILL)


class LocalAuKServer:
    def __init__(self, binary: Path, model_dir: Path, root: Path, limits: Limits, memory_saver: bool):
        self.binary, self.model_dir, self.root = Path(binary).resolve(), Path(model_dir).resolve(), Path(root).resolve()
        self.limits, self.memory_saver = limits, bool(memory_saver)
        self.root.mkdir(parents=True, exist_ok=True)
        self.owner_file = self.root / 'server_owner.json'
        self.process = None; self.log_handle = None; self.profile = None; self.has_run = False
        self.model_id = 'auk-voice-' + uuid.uuid4().hex
        self.url = ''
        self.deadline = None  # monotonic wall-clock stop shared from the worker; None disables
        self.recover_orphan()

    def recover_orphan(self) -> None:
        if not self.owner_file.exists(): return
        info = json.loads(self.owner_file.read_text())
        pid = int(info['pid'])
        # The Editor's process lock is already held. Do not kill unrelated processes.
        try:
            argv = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
            if str(info['config']).encode() in argv:
                kill_owned_group(pid, info.get('start_ticks'))
        except OSError: pass
        self.owner_file.unlink(missing_ok=True)

    def stop(self) -> None:
        if self.process is not None:
            kill_owned_group(self.process.pid, self.start_ticks)
            with contextlib.suppress(subprocess.TimeoutExpired): self.process.wait(timeout=5)
        self.process = None
        if self.log_handle is not None: self.log_handle.close()
        self.log_handle = None; self.profile = None; self.has_run = False
        self.owner_file.unlink(missing_ok=True)

    def _get(self, route: str) -> dict:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(self.url + route, timeout=2) as response:
            return json.loads(response.read(100_000))

    def start(self, profile: str) -> bool:
        if profile not in PROFILE_FILES:
            raise EditorError('unknown_profile', 'Select a supported Base/Flash profile.')
        if self.profile == profile and self.process is not None and self.process.poll() is None:
            return False
        self.stop()
        variant, generator = PROFILE_FILES[profile]
        for name in (generator, *SHARED_FILES, *SIDECARS):
            if not (self.model_dir / name).is_file():
                raise EditorError('missing_model', f'Missing {name}. Rerun the model-download cell for {profile}.')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        self.url = f'http://127.0.0.1:{port}'
        config = {
            'host': '127.0.0.1', 'port': port, 'backend': 'cuda', 'device': 0,
            'threads': 2, 'lazy_load': False, 'max_loaded_models': 1,
            'log_request_body': False, 'max_request_body_bytes': 64 * 1024,
            'models': [{
                'id': self.model_id, 'family': 'auk', 'path': str(self.model_dir),
                'task': 'gen', 'mode': 'offline',
                'session_options': {
                    'auk.variant': variant, 'auk.model_gguf': generator,
                    'auk.qwen_gguf': SHARED_FILES[0], 'auk.vae_gguf': SHARED_FILES[1],
                    'auk.mem_saver': str(self.memory_saver).lower(),
                },
                'default_request_options': {
                    'num_inference_steps': 4 if variant == 'flash' else 32,
                    'guidance_scale': 0.0 if variant == 'flash' else 2.0,
                    'sway_sampling_coef': -1.0,
                },
            }],
        }
        specs = self.binary.parent / 'model_specs' / 'auk.json'
        if specs.is_file(): config['model_spec_override'] = str(specs)
        config_path = self.root / ('server-' + self.model_id + '.json')
        atomic_json(config_path, config)
        log_path = self.root / 'server.log'
        # Bound retained logs: previous startup only; application does not enable --log.
        if log_path.exists(): os.replace(log_path, self.root / 'server.previous.log')
        self.log_handle = log_path.open('wb')
        try:
            self.process = subprocess.Popen([str(self.binary), '--config', str(config_path), '--no-ui'],
                cwd=self.binary.parent, stdin=subprocess.DEVNULL, stdout=self.log_handle,
                stderr=subprocess.STDOUT, start_new_session=True)
            self.start_ticks = process_start_ticks(self.process.pid)
            atomic_json(self.owner_file, {'pid': self.process.pid, 'start_ticks': self.start_ticks,
                                         'config': str(config_path)})
            deadline = time.monotonic() + self.limits.startup_timeout
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise EditorError('server_start_failed', 'AuK server exited at startup. Inspect the private server log; check driver, model hashes, and memory.')
                try:
                    self._get('/health')
                    models = self._get('/v1/models')
                    if any(item.get('id') == self.model_id for item in models.get('data', [])):
                        self.profile = profile; self.has_run = False
                        return True
                except (OSError, ValueError, KeyError): pass
                time.sleep(.4)
            raise EditorError('server_start_timeout', 'Server exceeded its startup deadline; its process was stopped.')
        except BaseException:
            self.stop()
            raise

    def run(self, profile: str, input_path: Path, plan: dict) -> tuple[dict, dict]:
        started = time.monotonic()
        self.start(profile)
        startup_seconds = time.monotonic() - started
        cold = not self.has_run
        payload = {'model': self.model_id, 'request': {
            'audio': str(Path(input_path).resolve()), 'text': plan['instruction'],
            'seed': plan['seed'], 'options': {'duration_sec': plan['target_seconds']}}}
        proc, ticks = self.process, self.start_ticks
        expired = threading.Event()
        effective_timeout = self.limits.inference_timeout
        if self.deadline is not None:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise EditorError('inference_timeout', 'Wall-clock budget exhausted before inference started.')
            effective_timeout = min(effective_timeout, remaining)
        def watchdog():
            expired.set()
            kill_owned_group(proc.pid, ticks)
        timer = threading.Timer(effective_timeout, watchdog)
        timer.daemon = True
        call_started = time.monotonic(); timer.start()
        success = False
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            request = urllib.request.Request(self.url + '/v1/tasks/run',
                data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode(),
                headers={'Content-Type': 'application/json'}, method='POST')
            with opener.open(request, timeout=effective_timeout) as response:
                body = response.read(self.limits.response_bytes + 1)
            if len(body) > self.limits.response_bytes:
                raise EditorError('response_too_large', 'Response exceeded its size bound.')
            if expired.is_set(): raise EditorError('inference_timeout', 'Inference deadline exceeded; worker process stopped.')
            parsed = json.loads(body)
            if not isinstance(parsed, dict): raise EditorError('invalid_response', 'Server returned an invalid response object.')
            success = True; self.has_run = True
            return parsed, {'server_start_seconds': round(startup_seconds, 3),
                            'inference_seconds': round(time.monotonic() - call_started, 3),
                            'first_request_after_start': cold,
                            'memory_saver': self.memory_saver}
        except urllib.error.HTTPError as exc:
            detail = exc.read(16_384).decode(errors='replace').lower()
            oom = any(x in detail for x in ('out of memory', 'cuda_error_out_of_memory', 'insufficient_memory', 'cuda allocation'))
            code = 'out_of_memory' if oom else 'server_http_error'
            message = ('GPU memory was exhausted. Select memory-saving mode or a smaller profile, then explicitly retry.'
                       if oom else f'AuK returned HTTP {exc.code}. Inspect the private server log. No fallback output was substituted.')
            raise EditorError(code, message) from exc
        except (OSError, ValueError) as exc:
            code = 'inference_timeout' if expired.is_set() else 'inference_transport_error'
            raise EditorError(code, 'Inference did not complete; its server process was stopped. An explicit retry is required.') from exc
        finally:
            timer.cancel(); timer.join(timeout=6)
            if not success: self.stop()


# @title Restart-safe jobs, cache integrity, and explicit review
# --- Persistent single-user jobs, idempotency, explicit review, no billing claims ---

class VoiceEditor:
    def __init__(self, root: Path, binary: Path, model_dir: Path, *, memory_saver: bool,
                 provenance: dict, limits: Limits = Limits(), commercial: bool = False,
                 commercial_license_confirmed: bool = False,
                 transport_factory: Callable | None = None, asr: Callable | None = None,
                 asr_fingerprint: str = 'disabled'):
        if commercial and not commercial_license_confirmed:
            raise EditorError('license_not_cleared', 'Commercial use is disabled until the required model licenses are independently cleared.')
        self.root = Path(root).resolve(); self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self.limits, self.provenance = limits, dict(provenance)
        self.provenance.update({'core_version': CORE_VERSION, 'memory_saver': bool(memory_saver),
                                'asr_fingerprint': asr_fingerprint})
        self.asr = asr
        self._mutex = threading.Lock()
        self._lockfile = (self.root / '.worker.lock').open('a+')
        try:
            fcntl.flock(self._lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._lockfile.close()
            raise EditorError('worker_busy', 'Another editor owns this job directory. Stop it before creating another.') from exc
        try:
            self.db = sqlite3.connect(self.root / 'jobs.sqlite3')
            self.db.execute('PRAGMA journal_mode=WAL'); self.db.execute('PRAGMA synchronous=FULL')
            self.db.execute('CREATE TABLE IF NOT EXISTS jobs (job_id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, status TEXT NOT NULL, updated_at TEXT NOT NULL)')
            self.db.commit()
            factory = transport_factory or LocalAuKServer
            self.transport = factory(binary, model_dir, self.root / 'runtime', limits, memory_saver)
            # No in-flight job can remain valid after ownership is reacquired.
            stale = self.db.execute("SELECT job_id FROM jobs WHERE status IN ('queued','running')").fetchall()
            for (job_id,) in stale:
                p = self.root / 'jobs' / job_id / 'manifest.json'
                old = json.loads(p.read_text()) if p.is_file() else {'job_id': job_id}
                old.update({'status': 'interrupted', 'error_code': 'worker_restarted', 'updated_at': utc_now()})
                atomic_json(p, old)
            self.db.execute("UPDATE jobs SET status='interrupted', updated_at=? WHERE status IN ('queued','running')", (utc_now(),))
            self.db.commit()
        except BaseException:
            with contextlib.suppress(Exception): self.db.close()
            fcntl.flock(self._lockfile, fcntl.LOCK_UN); self._lockfile.close()
            raise

    def close(self) -> None:
        if self._lockfile.closed: return
        self.transport.stop(); self.db.close()
        fcntl.flock(self._lockfile, fcntl.LOCK_UN); self._lockfile.close()

    def _save(self, job_dir: Path, manifest: dict, status: str) -> None:
        manifest['status'] = status; manifest['updated_at'] = utc_now()
        atomic_json(job_dir / 'manifest.json', manifest)
        self.db.execute('UPDATE jobs SET status=?, updated_at=? WHERE job_id=?',
                        (status, manifest['updated_at'], manifest['job_id']))
        self.db.commit()

    def edit(self, source: Path, spec: EditSpec, *, profile: str = 'base_f32',
             start_seconds: float = 0, end_seconds: float | None = None, channel: str = 'mix',
             rights_confirmed: bool = False, retry_failed: bool = False,
             allow_unchecked_word_edits: bool = False, cache_namespace: str = '') -> dict:
        if not self._mutex.acquire(blocking=False):
            raise EditorError('worker_busy', 'One edit is already running in this worker.')
        try:
            return self._edit(source, spec, profile=profile, start_seconds=start_seconds,
                              end_seconds=end_seconds, channel=channel, rights_confirmed=rights_confirmed,
                              retry_failed=retry_failed, allow_unchecked_word_edits=allow_unchecked_word_edits,
                              cache_namespace=cache_namespace)
        finally:
            self._mutex.release()

    def _edit(self, source: Path, spec: EditSpec, **options) -> dict:
        if not options['rights_confirmed']:
            raise EditorError('rights_not_confirmed', 'Confirm you are authorized to edit this recording before running it.')
        profile = options['profile']
        if profile not in PROFILE_FILES: raise EditorError('unknown_profile', 'Choose a supported profile.')
        source = Path(source).resolve()
        probe_audio(source, self.limits)  # Fail before hashing/staging a very large/unsupported file.
        if spec.operation == 'replace_words' and self.asr is None and not options['allow_unchecked_word_edits']:
            raise EditorError('asr_required', 'Enable optional ASR QA for word edits, or explicitly allow an unchecked evaluation output.')
        identity = {'source_sha256': sha256_file(source), 'spec': dataclasses.asdict(spec),
                    'profile': profile, 'start': options['start_seconds'], 'end': options['end_seconds'],
                    'channel': options['channel'], 'limits': dataclasses.asdict(self.limits),
                    'provenance': self.provenance, 'cache_namespace': options['cache_namespace']}
        fingerprint = canonical_hash(identity)
        row = self.db.execute('SELECT job_id, status FROM jobs WHERE fingerprint=?', (fingerprint,)).fetchone()
        if row:
            job_id, state = row
            job_dir = self.root / 'jobs' / job_id
            manifest = json.loads((job_dir / 'manifest.json').read_text())
            output = job_dir / 'output.wav'
            if state == 'generated':
                if not output.is_file() or sha256_file(output) != manifest.get('output_sha256'):
                    raise EditorError('corrupt_cached_output', 'Cached output is missing or changed; it was not returned as a valid result.')
                return {**manifest, 'cache_hit': True, 'output_path': str(output), 'job_dir': str(job_dir)}
            if not options['retry_failed']:
                raise EditorError('explicit_retry_required', f'Previous attempt is {state}. Enable retry_failed to rerun the same job.')
        else:
            job_id = uuid.uuid4().hex
            job_dir = self.root / 'jobs' / job_id; job_dir.mkdir(parents=True)
            manifest = {'job_id': job_id, 'fingerprint': fingerprint, 'created_at': utc_now(), 'attempts': 0}
            self.db.execute('INSERT INTO jobs VALUES (?,?,?,?)', (job_id, fingerprint, 'queued', utc_now())); self.db.commit()
        manifest.update({'request': identity, 'attempts': manifest.get('attempts', 0)+1,
                         'human_review': 'pending', 'semantic_validation': 'not_run',
                         'rights_confirmed': True, 'error_code': None})
        output = job_dir / 'output.wav'; output.unlink(missing_ok=True)
        self._save(job_dir, manifest, 'running')
        started = time.monotonic()
        try:
            prepared = job_dir / 'input.wav'
            media = prepare_audio(source, prepared, options['start_seconds'], options['end_seconds'],
                                  self.limits, options['channel'])
            # Source can be a user-managed local path. Detect a change while it was read.
            if sha256_file(source) != identity['source_sha256']:
                raise EditorError('source_changed', 'Source changed during preparation; upload a stable copy and retry.')
            plan = build_plan(spec, media['signal']['duration_seconds'], self.limits)
            manifest['input'] = media; manifest['plan'] = plan
            self._save(job_dir, manifest, 'running')
            qa_started = time.monotonic()
            source_asr = None
            if self.asr is not None and (plan['preserve_content'] or spec.operation == 'replace_words'):
                source_asr = self.asr(prepared)
                if not source_asr.get('text', '').strip():
                    raise EditorError('speech_not_detected', 'ASR did not detect words. Check the clip; this may be an ASR failure.')
                if spec.operation == 'replace_words':
                    source_check = compare_transcript(spec.source_transcript, source_asr['text'])
                    if source_check['error_rate'] > .2:
                        raise EditorError('source_transcript_mismatch', 'ASR substantially disagrees with the supplied transcript; review the clip/transcript before replacing words.')
            manifest['source_asr'] = source_asr
            pre_qa_seconds = time.monotonic() - qa_started
            response, timing = self.transport.run(profile, prepared, plan)
            raw_path = job_dir / 'raw-output.wav'
            atomic_bytes(raw_path, decode_response(response, self.limits))
            quality = validate_output(raw_path, plan['target_seconds'], self.limits)
            # 16-bit WAV export, no loudness normalization, denoiser, TTS, or synthetic fallback.
            temporary = job_dir / 'export.tmp.wav'
            command(['ffmpeg', '-hide_banner', '-v', 'error', '-nostdin', '-xerror', '-i', str(raw_path),
                     '-map', '0:a:0', '-c:a', 'pcm_s16le', '-f', 'wav', '-y', str(temporary)],
                    timeout=self.limits.ffmpeg_timeout)
            validate_output(temporary, plan['target_seconds'], self.limits)
            os.replace(temporary, output)
            raw_path.unlink(missing_ok=True)
            expected = plan['expected_transcript']
            if not expected and source_asr and plan['preserve_content']:
                expected = source_asr['text']
            qa_started = time.monotonic()
            if self.asr is not None and expected:
                output_asr = self.asr(output)
                quality['transcript_check'] = compare_transcript(expected, output_asr.get('text', ''))
                quality['output_asr'] = output_asr
                if spec.operation == 'replace_words':
                    new_tokens = normalized_tokens(spec.new_words)
                    actual = normalized_tokens(output_asr.get('text', ''))
                    present = bool(new_tokens) and any(actual[i:i+len(new_tokens)] == new_tokens for i in range(len(actual)))
                    quality['replacement_detected'] = present
                    if not present: quality['transcript_check']['status'] = 'review_required'
                manifest['semantic_validation'] = quality['transcript_check']['status']
                if manifest['semantic_validation'] == 'review_required':
                    quality['warnings'].append('ASR detected a text discrepancy. Do not treat this output as an approved edit.')
            else:
                manifest['semantic_validation'] = 'not_run'
                quality['warnings'].append('No automatic content check was run. A valid WAV is not proof that the requested edit succeeded.')
            timing['qa_seconds'] = round(pre_qa_seconds + time.monotonic() - qa_started, 3)
            timing['total_seconds'] = round(time.monotonic() - started, 3)
            timing['inference_real_time_factor'] = round(timing['inference_seconds']/plan['target_seconds'], 3)
            manifest.update({'quality': quality, 'timing': timing, 'output_sha256': sha256_file(output),
                             'input_sha256': sha256_file(prepared), 'profile_used': profile,
                             'warnings': media['warnings'] + quality['warnings']})
            self._save(job_dir, manifest, 'generated')
            return {**manifest, 'cache_hit': False, 'output_path': str(output), 'job_dir': str(job_dir)}
        except BaseException as exc:
            # Never leave a stale playable output beside a failed manifest.
            for name in ('output.wav', 'raw-output.wav', 'export.tmp.wav'):
                (job_dir / name).unlink(missing_ok=True)
            manifest['error_code'] = getattr(exc, 'code', type(exc).__name__)
            manifest['elapsed_before_failure_seconds'] = round(time.monotonic() - started, 3)
            self._save(job_dir, manifest, 'interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed')
            raise

    def review(self, job_id: str, *, approved: bool, notes: str = '') -> dict:
        if not re.fullmatch(r'[a-f0-9]{32}', job_id): raise EditorError('invalid_job_id', 'Invalid job ID.')
        job_dir = self.root / 'jobs' / job_id
        row = self.db.execute('SELECT status FROM jobs WHERE job_id=?', (job_id,)).fetchone()
        if not row or row[0] != 'generated': raise EditorError('not_reviewable', 'Only a generated output can be reviewed.')
        manifest = json.loads((job_dir / 'manifest.json').read_text())
        if approved and (not (job_dir/'output.wav').is_file() or sha256_file(job_dir/'output.wav') != manifest['output_sha256']):
            raise EditorError('corrupt_output', 'Output changed since generation; approval blocked.')
        manifest.update({'human_review': 'approved' if approved else 'rejected',
                         'review_notes': str(notes)[:2000], 'reviewed_at': utc_now()})
        self._save(job_dir, manifest, 'generated')
        return manifest


# @title Artifact download and checksum helpers
# Setup helpers: download immutable artifacts, check hashes, and keep a lock manifest.
def download_file(url: str, destination: Path, *, expected_sha256: str | None = None,
                  max_seconds: int = 1800) -> Path:
    if urllib.parse.urlparse(url).scheme != 'https':
        raise EditorError('insecure_download', 'Artifact downloads require HTTPS.')
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and expected_sha256 and sha256_file(destination) == expected_sha256:
        return destination
    partial = destination.with_name(destination.name + '.part')
    # curl can resume a large HF download. A mismatched final digest is never accepted.
    args = ['curl', '--fail', '--location', '--show-error', '--silent', '--proto', '=https',
            '--proto-redir', '=https', '--connect-timeout', '20', '--max-time', str(max_seconds),
            '--retry', '3', '--retry-delay', '2', '--retry-all-errors',
            '--continue-at', '-', '--output', str(partial), url]
    command(args, timeout=max_seconds * 4 + 30)
    if not partial.is_file() or partial.stat().st_size == 0:
        raise EditorError('download_empty', f'Download returned no bytes: {destination.name}')
    if expected_sha256 and sha256_file(partial) != expected_sha256:
        partial.unlink(missing_ok=True)
        raise EditorError('checksum_mismatch', f'Checksum failed for {destination.name}; corrupt partial removed. Rerun setup.')
    os.replace(partial, destination)
    return destination


def fetch_text(url: str, *, limit: int = 2 * 1024 * 1024) -> str:
    req = urllib.request.Request(url, headers={'User-Agent': 'MagicHour-AuK-Colab/1.0'})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                data = response.read(limit + 1)
            if len(data) > limit: raise EditorError('metadata_too_large', 'Metadata exceeded its size bound.')
            return data.decode('utf-8')
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            if attempt < 2: time.sleep(2 ** attempt)
    raise EditorError('metadata_unavailable', 'Could not fetch pinned artifact metadata. Check network access, then rerun setup.') from last


def parse_lfs_pointer(text: str) -> tuple[str, int]:
    digest = re.search(r'^oid sha256:([a-f0-9]{64})$', text, flags=re.MULTILINE)
    size = re.search(r'^size ([0-9]+)$', text, flags=re.MULTILINE)
    if not digest or not size:
        raise EditorError('bad_model_pointer', 'Expected a SHA-256 Git LFS pointer from the pinned model revision.')
    count = int(size.group(1))
    if count <= 0: raise EditorError('bad_model_pointer', 'Model pointer has invalid size.')
    return digest.group(1), count


def safe_extract(archive_path: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    root = target.resolve()
    with tarfile.open(archive_path, 'r:gz') as archive:
        members = archive.getmembers()
        if sum(m.size for m in members) > 4 * 2**30:
            raise EditorError('archive_too_large', 'Runtime archive expands beyond the safety bound.')
        for member in members:
            p = (root / member.name).resolve()
            if p != root and root not in p.parents:
                raise EditorError('unsafe_archive', 'Archive path escapes its destination.')
            if not (member.isfile() or member.isdir()):
                raise EditorError('unsafe_archive', 'Links/devices in runtime archives are not accepted.')
        for member in members:
            archive.extract(member, root, filter='data')


def gpu_details() -> dict:
    row = command(['nvidia-smi', '--query-gpu=name,memory.total,memory.free,compute_cap',
                   '--format=csv,noheader,nounits'], timeout=10).strip().splitlines()[0]
    name, total, free, capability = [part.strip() for part in row.split(',')]
    return {'name': name, 'total_mib': int(total), 'free_mib': int(free), 'compute_capability': capability}


def setup_runtime(root: Path, *, mode: str, gpu: dict) -> tuple[Path, dict]:
    target = root / 'runtime-package'
    lock_path = target / 'runtime.lock.json'
    if mode not in {'t4_prebuilt', 'source_build'}: raise EditorError('bad_setup_mode', 'Select t4_prebuilt or source_build.')
    if mode == 't4_prebuilt' and gpu['compute_capability'] != '7.5':
        raise EditorError('wrong_gpu', 'This prebuilt targets T4/SM75. Select a T4, or choose source_build explicitly for the attached GPU.')
    if lock_path.is_file():
        lock = json.loads(lock_path.read_text())
        binary = Path(lock['binary'])
        if (lock.get('mode') == mode and lock.get('tag') == RUNTIME_TAG
            and lock.get('compute_capability') == gpu['compute_capability']
            and binary.is_file() and sha256_file(binary) == lock.get('binary_sha256')):
            command([str(binary), '--help'], timeout=20)
            return binary, lock
    target.mkdir(parents=True, exist_ok=True)
    if mode == 't4_prebuilt':
        archive = root / RUNTIME_ASSET
        print('Downloading checksum-pinned T4 runtime...')
        download_file(RUNTIME_URL, archive, expected_sha256=RUNTIME_SHA256, max_seconds=300)
        unpacked = target / 'unpacked'
        if unpacked.exists(): shutil.rmtree(unpacked)
        safe_extract(archive, unpacked)
        candidates = [p for p in unpacked.rglob('audiocpp_server') if p.is_file()]
        if len(candidates) != 1: raise EditorError('bad_runtime_archive', 'Expected exactly one server binary.')
        binary = candidates[0]; binary.chmod(0o755)
        extra = {'archive_sha256': RUNTIME_SHA256}
    else:
        if not shutil.which('nvcc'): raise EditorError('cuda_toolkit_missing', 'source_build requires the CUDA development toolkit (nvcc).')
        source = root / 'audio-cpp-source'
        if not (source / '.git').is_dir():
            command(['git', 'clone', '--filter=blob:none', '--no-checkout',
                     'https://github.com/0xShug0/audio.cpp.git', str(source)], timeout=600)
        command(['git', 'fetch', '--depth', '1', 'origin', 'tag', RUNTIME_TAG], cwd=source, timeout=300)
        revision = command(['git', 'rev-parse', f'{RUNTIME_TAG}^{{commit}}'], cwd=source).strip()
        if not re.fullmatch(r'[a-f0-9]{40}', revision) or not revision.startswith(RUNTIME_COMMIT_PREFIX):
            raise EditorError('unexpected_source_commit', 'Release source no longer resolves to the verified commit prefix. Stop and review it.')
        command(['git', 'checkout', '--detach', revision], cwd=source)
        command(['git', '-c', 'url.https://github.com/.insteadOf=git@github.com:',
                 'submodule', 'update', '--init', '--recursive'], cwd=source, timeout=600)
        architecture = gpu['compute_capability'].replace('.', '')
        build = source / ('build-colab-sm' + architecture)
        command(['cmake', '-S', str(source), '-B', str(build), '-DCMAKE_BUILD_TYPE=Release',
                 '-DENGINE_ENABLE_CUDA=ON', '-DENGINE_ENABLE_VULKAN=OFF',
                 '-DENGINE_ENABLE_NATIVE_CPU=OFF', '-DENGINE_BUILD_TESTS=OFF',
                 '-DAUDIOCPP_DEPLOYMENT_BUILD=ON', '-DAUDIOCPP_BUILD_NATIVE_MODEL_MANAGER=OFF',
                 f'-DCMAKE_CUDA_ARCHITECTURES={architecture}'], timeout=600)
        command(['cmake', '--build', str(build), '--parallel', '2', '--target', 'audiocpp_server'], timeout=3600)
        candidates = [p for p in build.rglob('audiocpp_server') if p.is_file()]
        if len(candidates) != 1: raise EditorError('build_missing_binary', 'Build did not produce one server executable.')
        binary = candidates[0]
        extra = {'source_commit': revision}
    command([str(binary), '--help'], timeout=30)
    lock = {'tag': RUNTIME_TAG, 'mode': mode, 'binary': str(binary.resolve()),
            'binary_sha256': sha256_file(binary), 'compute_capability': gpu['compute_capability'],
            'created_at': utc_now(), **extra}
    atomic_json(lock_path, lock)
    return binary.resolve(), lock


def setup_models(root: Path, profiles: list[str]) -> tuple[Path, dict]:
    if not profiles or any(p not in PROFILE_FILES for p in profiles):
        raise EditorError('unknown_profile', 'Choose supported download profiles.')
    directory = root / 'models' / MODEL_REVISION
    directory.mkdir(parents=True, exist_ok=True)
    filenames = sorted({PROFILE_FILES[p][1] for p in profiles} | set(SHARED_FILES))
    remote = f'https://huggingface.co/{MODEL_REPO}'
    specs = {}
    for name in filenames:
        pointer = fetch_text(f'{remote}/raw/{MODEL_REVISION}/{name}', limit=16_384)
        digest, size = parse_lfs_pointer(pointer)
        specs[name] = {'sha256': digest, 'bytes': size}
    missing_size = sum(item['bytes'] for name, item in specs.items() if not (directory/name).is_file())
    if shutil.disk_usage(root).free < missing_size + 2 * 2**30:
        raise EditorError('disk_space', 'Insufficient disk space for the selected weights plus 2 GiB working space.')
    for name, spec in specs.items():
        print(f'Checking/downloading {name} ({spec["bytes"]/2**30:.2f} GiB)...')
        path = download_file(f'{remote}/resolve/{MODEL_REVISION}/{name}', directory/name,
                             expected_sha256=spec['sha256'])
        if path.stat().st_size != spec['bytes']:
            raise EditorError('model_size_mismatch', f'Model size is incorrect: {name}')
    for name in SIDECARS:
        # Immutable model commit fixes sidecar contents; record their hashes as well.
        path = directory / name
        if not path.is_file(): download_file(f'{remote}/resolve/{MODEL_REVISION}/{name}', path, max_seconds=300)
        if path.suffix == '.json': json.loads(path.read_text())
        specs[name] = {'sha256': sha256_file(path), 'bytes': path.stat().st_size}
    lock = {'repo': MODEL_REPO, 'revision': MODEL_REVISION, 'files': specs}
    atomic_json(directory / 'model.lock.json', lock)
    return directory, lock


# @title Optional isolated CPU speech QA helpers
# Optional CPU-only speech QA. Its isolated environment never imports Torch into this notebook.
ASR_MODEL_REPO = 'Systran/faster-whisper-small'
ASR_MODEL_REVISION = '536b0662742c02347bc0e980a01041f333bce120'
ASR_SCRIPT = r'''
import json, os, sys
os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
os.environ['HF_HUB_OFFLINE'] = '1'
from faster_whisper import WhisperModel
model_path, audio_path, output_path, language = sys.argv[1:]
model = WhisperModel(model_path, device='cpu', compute_type='int8', cpu_threads=2,
                     num_workers=1, local_files_only=True)
segments, info = model.transcribe(audio_path, beam_size=3, temperature=0,
    condition_on_previous_text=False, vad_filter=True, word_timestamps=True,
    language=None if language == 'auto' else language)
segments = list(segments)
result = {
    'text': ' '.join(s.text.strip() for s in segments).strip(),
    'language': info.language, 'language_probability': float(info.language_probability),
    'words': [{'word': w.word, 'start': w.start, 'end': w.end,
               'probability': float(w.probability)} for s in segments for w in (s.words or [])],
}
with open(output_path, 'w', encoding='utf-8') as stream:
    json.dump(result, stream, ensure_ascii=False, allow_nan=False)
'''


def make_venv(env: Path) -> Path:
    """Create an isolated venv even where ensurepip is broken (Colab, Python 3.13)."""
    py = env / 'bin/python'
    if py.is_file():
        try:
            command([str(py), '-m', 'pip', '--version'], timeout=30)
            return py
        except EditorError:
            command([sys.executable, '-m', 'pip', '--python', str(py), 'install', '--quiet', 'pip'], timeout=300)
            command([str(py), '-m', 'pip', '--version'], timeout=30)
            return py
    try:
        command([sys.executable, '-m', 'venv', str(env)], timeout=180)
        command([str(py), '-m', 'pip', '--version'], timeout=30)
        return py
    except EditorError:
        shutil.rmtree(env, ignore_errors=True)
    command([sys.executable, '-m', 'venv', '--without-pip', str(env)], timeout=120)
    try:
        command([sys.executable, '-m', 'pip', '--python', str(py), 'install',
                 '--disable-pip-version-check', '--quiet', 'pip'], timeout=300)
    except EditorError:
        command(['uv', 'pip', 'install', '--python', str(py), 'pip'], timeout=300)
    command([str(py), '-m', 'pip', '--version'], timeout=30)
    return py


def setup_asr(root: Path, limits: Limits, language: str = 'auto') -> tuple[Callable, str]:
    if not re.fullmatch(r'auto|[a-z]{2,3}', language):
        raise EditorError('invalid_language', 'ASR language should be auto or an ISO language code such as en or zh.')
    qa_root = root / 'speech-qa'; qa_root.mkdir(parents=True, exist_ok=True)
    env = qa_root / 'venv'; py = env / 'bin/python'
    freeze_path = qa_root / 'requirements.lock.txt'
    fresh_environment = not py.is_file()
    py = make_venv(env)
    if fresh_environment and freeze_path.is_file():
        command([str(py), '-m', 'pip', 'install', '--disable-pip-version-check', '--quiet', '-r', str(freeze_path)], timeout=900)
    if not freeze_path.is_file():
        command([str(py), '-m', 'pip', 'install', '--disable-pip-version-check',
                 '--quiet', 'faster-whisper==1.2.1', 'av==16.0.0', 'ctranslate2==4.6.0', 'huggingface-hub==0.35.3', 'tokenizers==0.22.1', 'onnxruntime==1.23.1', 'numpy==2.3.3'], timeout=900)
        frozen = command([str(py), '-m', 'pip', 'freeze'], timeout=30)
        atomic_bytes(freeze_path, frozen.encode())
    else:
        actual = command([str(py), '-m', 'pip', 'freeze'], timeout=30)
        if actual.strip() != freeze_path.read_text().strip():
            raise EditorError('qa_environment_changed', 'QA environment changed from its saved package lock. Recreate it explicitly before running.')
    command([str(py), '-m', 'pip', 'check'], timeout=30)
    model = qa_root / ASR_MODEL_REVISION; model.mkdir(exist_ok=True)
    remote = f'https://huggingface.co/{ASR_MODEL_REPO}'
    digest, size = parse_lfs_pointer(fetch_text(f'{remote}/raw/{ASR_MODEL_REVISION}/model.bin',limit=16_384))
    download_file(f'{remote}/resolve/{ASR_MODEL_REVISION}/model.bin', model/'model.bin', expected_sha256=digest)
    for name in ('config.json', 'tokenizer.json', 'vocabulary.txt'):
        if not (model/name).is_file(): download_file(f'{remote}/resolve/{ASR_MODEL_REVISION}/{name}',model/name,max_seconds=300)
    hashes = {p.name: sha256_file(p) for p in model.iterdir() if p.is_file()}
    script = qa_root / 'transcribe_local.py'; atomic_bytes(script, ASR_SCRIPT.encode())
    fingerprint = canonical_hash({'model': ASR_MODEL_REVISION, 'files': hashes,
                                  'requirements': freeze_path.read_text(), 'script': sha256_file(script),
                                  'language': language})
    atomic_json(qa_root/'qa.lock.json',{'revision':ASR_MODEL_REVISION,'fingerprint':fingerprint,
                                      'files':hashes,'language':language})
    def transcribe(path: Path) -> dict:
        fd, name = tempfile.mkstemp(suffix='.json', dir=qa_root); os.close(fd)
        out = Path(name)
        try:
            command([str(py), str(script), str(model), str(Path(path).resolve()), str(out), language],
                    timeout=limits.asr_timeout)
            value = json.loads(out.read_text())
            if not isinstance(value.get('text'),str): raise EditorError('invalid_asr_result','ASR did not return text.')
            return value
        finally:
            out.unlink(missing_ok=True)
    return transcribe, fingerprint
