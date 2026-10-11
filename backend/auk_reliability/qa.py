"""Content/identity heuristics. Never equate them with perceptual quality."""
import math
from .core import compare_transcript
class SemanticQAGate:
 def __init__(self, transcriber=None, speaker_verifier=None, speaker_threshold=.75, max_text_error=0.0):
  self.transcriber=transcriber;self.speaker_verifier=speaker_verifier
  self.speaker_threshold=speaker_threshold;self.max_text_error=max_text_error
 def check(self, source, output, plan):
  checks={};unverified=[]
  if self.transcriber is None: unverified.append('transcript_qa_unavailable')
  else:
   observed=self.transcriber(output)
   text=observed.get('text','') if isinstance(observed,dict) else observed
   checks['transcript']=compare_transcript(plan['expected_transcript'],text)
   checks['transcript']['expected']=plan['expected_transcript'];checks['transcript']['observed']=text  # diagnostic only; gate unchanged
   if isinstance(observed,dict) and observed.get('words'): checks['transcript']['words']=observed['words']  # diagnostic timings only; gate unchanged
   checks['transcript']['passed']=checks['transcript']['error_rate']<=self.max_text_error
  if plan['identity_required']:
   if self.speaker_verifier is None: unverified.append('speaker_qa_unavailable')
   else:
    score=float(self.speaker_verifier(source,output));checks['speaker']={'score':score if math.isfinite(score) else None,'threshold':self.speaker_threshold,
      'passed': math.isfinite(score) and score>=self.speaker_threshold}
  passed=all(c['passed'] for c in checks.values()) and not unverified
  return {'automatic_pass':passed,'checks':checks,'unverified':unverified,
    'semantic_success':None,'quality_review_required':['instruction_following','naturalness','noise/reverb improvement','seams/endings'],
    'note':'ASR and embedding scores are heuristics. Human quality review remains required.'}
