"""Content/identity heuristics. Never equate them with perceptual quality."""
import math
from .core import compare_transcript, normalized_tokens
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
   if checks['transcript']['error_rate']>0:
    # Case-scoped documented ASR variants for output QA (same contract as the segment gate):
    # explicit per-case token+position exceptions for known ASR misspellings of faithful
    # ground truth (homophones, rare proper nouns). Caller-supplied only; never a fuzzy or
    # global alias. expected_transcript stays immutable; every declared slot must match its
    # documented position/expected/observed and every other token must match exactly, or the
    # gate keeps its original failure.
    variants=plan.get('output_asr_variants') or []
    if variants:
     expected_tokens=normalized_tokens(plan['expected_transcript']);observed_tokens=normalized_tokens(text)
     if len(expected_tokens)==len(observed_tokens):
      fixed=list(observed_tokens);applied=[]
      for v in variants:
       pos=v.get('position') if isinstance(v,dict) else None
       if not (isinstance(pos,int) and 0<=pos<len(expected_tokens)
               and expected_tokens[pos]==v.get('expected') and observed_tokens[pos]==v.get('observed')
               and v.get('expected')!=v.get('observed')):
        applied=None;break
       fixed[pos]=v['expected'];applied.append({'position':pos,'expected':v['expected'],'observed':v['observed'],'note':v.get('note','')})
      if applied is not None and fixed==expected_tokens:
       checks['transcript'].update({'error_rate':0.0,'word_error_rate':0.0,'exact_normalized_match':True,
        'status':'no_text_discrepancy_detected','applied_asr_variants':applied})
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
