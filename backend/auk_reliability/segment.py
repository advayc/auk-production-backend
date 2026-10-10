"""Fixed-duration segment replacement. No whole-recording model regeneration."""
import wave, math, array, sys
from pathlib import Path
from .core import EditorError, command, probe_audio, compare_transcript

def normalize_recording(source, output, limits):
 meta=probe_audio(source,limits)
 command(['ffmpeg','-v','error','-nostdin','-xerror','-protocol_whitelist','file,pipe','-i',str(source),
  '-map','0:a:0','-ac','1','-ar','24000','-c:a','pcm_s16le','-y',str(output)],timeout=limits.ffmpeg_timeout)
 with wave.open(str(output)) as w:
  actual=w.getnframes()/w.getframerate()
 if abs(actual-meta['duration_seconds'])>.06: raise EditorError('truncated_input','Full recording failed decode-duration check.')
 return actual

def verify_alignment(source_segment, parameters, transcriber):
 if parameters.get('segment_scope')=='whole_clip':
  # No timestamps involved: the window is the entire clip, whose transcript was human-checked.
  # Alignment is NOT marked human-verified; ASR must still match the whole clip exactly below.
  if parameters['segment_text'].strip()!=parameters.get('source_text','').strip():
   raise EditorError('whole_clip_text_mismatch','Whole-clip scope requires segment_text to equal the checked source_text.')
 elif parameters.get('alignment_verified') is not True:
  raise EditorError('alignment_not_verified','Explicit timestamps must be human-checked against the source recording.')
 if transcriber is None: raise EditorError('alignment_qa_unavailable','Segment edits require source ASR checking.')
 observed=transcriber(source_segment);text=observed.get('text','') if isinstance(observed,dict) else observed
 if compare_transcript(parameters['segment_text'],text)['error_rate']>0:
  raise EditorError('segment_transcript_mismatch','Selected segment does not exactly match normalized segment_text in ASR. Review alignment.')

def splice(normalized, generated, output, start, end):
 with wave.open(str(normalized)) as w:
  params=w.getparams();original=w.readframes(w.getnframes())
 with wave.open(str(generated)) as w:
  if w.getnchannels()!=1 or w.getsampwidth()!=2 or w.getframerate()!=24000:
   raise EditorError('wrong_output_format','Splice needs mono PCM16 24kHz.')
  patch=w.readframes(w.getnframes())
 first=round(start*24000)*2;last=round(end*24000)*2
 if len(patch)!=last-first: raise EditorError('splice_duration_mismatch','Segment frame count must match; no time stretching or padding fallback.')
 result=original[:first]+patch+original[last:]
 with wave.open(str(output),'wb') as w:
  w.setparams(params);w.writeframes(result)
 with wave.open(str(output)) as w: saved=w.readframes(w.getnframes())
 if saved[:first]!=original[:first] or saved[last:]!=original[last:] or len(saved)!=len(original):
  raise EditorError('outside_segment_changed','Splice changed audio outside the chosen normalized interval.')
 samples=array.array('h');samples.frombytes(saved)
 if sys.byteorder!='little':samples.byteswap()
 jumps=[abs(samples[j]-samples[j-1])/32768 for j in (first//2,last//2) if 0<j<len(samples)]
 return {'outside_interval_pcm_exact':True,'normalized_format':'mono PCM16 24kHz',
  'boundary_jump_peak':max(jumps,default=0),'boundary_review_required':True,
  'note':'Outside PCM is exact relative to normalized source, not compressed/stereo original. No crossfade alters outside samples.'}
