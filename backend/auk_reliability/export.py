"""User-facing MP3 export. Lossless edit/QA artifacts remain unchanged."""
from pathlib import Path
import json, math, os, subprocess, tempfile
from .core import EditorError, atomic_json, sha256_file

def export_mp3_final(request_dir):
    """Encode a QA-passing WAV once for delivery, never for editing or QA.

    The result and preview keep their internal WAV path so exact-PCM guarantees
    are not mislabeled as MP3 guarantees. final-export.json identifies the file
    the user receives. Listening review status is not upgraded by an export.
    """
    root = Path(request_dir).resolve()
    result = json.loads((root / 'result.json').read_text())
    if not result.get('technical_success') or not result.get('automatic_qa_pass') or not result.get('output_path'):
        raise EditorError('export_not_ready', 'MP3 final export needs a technically valid, automatic-QA-passing edit.')
    source = Path(result['output_path']).resolve()
    if source.suffix.lower() != '.wav' or root not in source.parents or not source.is_file():
        raise EditorError('export_source_invalid', 'Final export needs the request lossless WAV processing artifact.')
    target = root / 'final.mp3'
    def run(args):
        return subprocess.run(args, check=True, capture_output=True, text=True, timeout=90)
    probe = json.loads(run(['ffprobe','-v','error','-show_entries','stream=sample_rate,channels:format=duration','-of','json',str(source)]).stdout)
    stream = probe['streams'][0]; duration = float(probe['format']['duration'])
    if stream['channels'] != 1 or int(stream['sample_rate']) != 24000 or not math.isfinite(duration) or duration <= 0:
        raise EditorError('export_source_invalid', 'Final export needs mono 24kHz lossless processing audio.')
    fd, name = tempfile.mkstemp(prefix='.final-', suffix='.mp3', dir=root); os.close(fd)
    temp = Path(name)
    try:
        run(['ffmpeg','-v','error','-nostdin','-xerror','-i',str(source),'-map','0:a:0','-map_metadata','-1',
             '-ar','48000','-c:a','libmp3lame','-b:a','320k','-y',str(temp)])
        run(['ffmpeg','-v','error','-nostdin','-xerror','-i',str(temp),'-f','null','-'])
        encoded = json.loads(run(['ffprobe','-v','error','-show_entries','stream=codec_name,sample_rate,channels,bit_rate:format=duration','-of','json',str(temp)]).stdout)
        es = encoded['streams'][0]; ed = float(encoded['format']['duration'])
        # MP3 frame padding is expected. It does not change the WAV's PCM contract.
        if es['codec_name'] != 'mp3' or es['channels'] != 1 or int(es['sample_rate']) != 48000 or int(es['bit_rate']) != 320000 or abs(ed-duration) > .15:
            raise EditorError('export_validation_failed','Encoded MP3 format or duration validation failed.')
        os.replace(temp,target)
        record = {'format':'mp3','output_path':str(target),'bitrate_requested_kbps':320,
                  'sample_rate':48000,'processing_sample_rate':24000,'channels':1,'lossy':True,'duration_seconds':ed,
                  'processing_wav_path':str(source),'processing_wav_sha256':sha256_file(source),
                  'mp3_sha256':sha256_file(target),'automatic_qa_applies_to':'lossless processing WAV',
                  'human_listening':'unscored; export does not approve quality',
                  'note':'MP3 is the final delivery file. WAV is retained for lossless processing and QA.'}
        atomic_json(root/'final-export.json',record)
        return record
    finally:
        temp.unlink(missing_ok=True)
