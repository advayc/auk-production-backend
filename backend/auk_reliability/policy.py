"""Explicit application policy, not a claim about the model's capabilities."""
from .core import EditorError, EditSpec, build_plan, _quote_words
OPERATIONS = {
 'voice_editor': ('emotion','voice_characteristics','whisper','speed','custom','nonverbal_remove'),
 'voice_enhancer': ('enhance','denoise','dereverb'),
 'transcript_editor': ('replace','insert','delete'),
}
# Current delivery scope. Enhancer policy remains available for its separate owner.
ACTIVE_MODES = ('voice_editor', 'transcript_editor')

def selected_modes(modes=None):
 if modes is None: return ACTIVE_MODES
 if isinstance(modes,str): raise ValueError('modes must be a sequence of mode names')
 modes=tuple(modes)
 if not modes or len(set(modes))!=len(modes) or any(m not in OPERATIONS for m in modes):
  raise ValueError('Select nonempty, unique supported modes')
 return modes

PROFILES = ('base_f32','base_q8','flash_f16')
RETRYABLE = frozenset({'inference_timeout','http_timeout','http_error','process_timeout',
 'missing_audio','invalid_base64','invalid_wav','wrong_output_duration','truncated_output',
 'silent_output','bad_pcm','qa_failed','clipped_output','quiet_output',
 'transplant_generation_mismatch'})

def plan_request(mode, operation, p, duration, limits):
 if mode not in OPERATIONS or operation not in OPERATIONS[mode]:
  raise EditorError('unsupported_operation', f'Unsupported {mode}/{operation}')
 if not isinstance(p,dict): raise EditorError('invalid_parameters','parameters must be a dictionary')
 if p.get('rights_confirmed') is not True:
  raise EditorError('rights_not_confirmed','Confirm rights to process this recording.')
 source=p.get('source_text','')
 if not isinstance(source,str) or not source.strip():
  raise EditorError('missing_transcript','Provide a human-checked source_text for content QA.')
 spec=EditSpec(operation={'voice_characteristics':'voice'}.get(operation,operation),
  source_transcript=source, seed=p.get('seed',42), emotion=p.get('emotion','calm'),
  voice_description=p.get('description',''), speed=p.get('speed_factor',1.0),
  instruction=p.get('instruction',''), expected_transcript=p.get('expected_text',''),
  sound=p.get('sound',''), target_seconds=p.get('target_seconds'))
 if mode=='transcript_editor':
  expected=p.get('edited_segment_text','')
  if not isinstance(expected,str) or not expected.strip():
   raise EditorError('empty_edited_segment','A nonempty edited_segment_text is required; include surrounding context for deletes.')
  before=p.get('segment_text','')
  if not isinstance(before,str) or not before.strip():
   raise EditorError('missing_segment_transcript','Provide checked segment_text and explicit segment_start/end_seconds.')
  old=p.get('original_text',''); text=p.get('text',''); replacement=p.get('replacement_text','')
  if operation=='replace':
   if not old or not replacement or before.count(old)!=1:
    raise EditorError('ambiguous_edit','Replacement must identify exactly one phrase inside segment_text.')
   derived=before.replace(old,replacement,1)
  elif operation=='delete':
   if not text or before.count(text)!=1: raise EditorError('ambiguous_edit','Delete text must occur exactly once in segment_text.')
   derived=' '.join(before.replace(text,'',1).split())
  else:
   anchor=p.get('anchor',''); position=p.get('position')
   if not text or not anchor or before.count(anchor)!=1 or position not in ('before','after'):
    raise EditorError('ambiguous_edit','Insertion needs a unique anchor and before/after position.')
   derived=before.replace(anchor, (text+' '+anchor) if position=='before' else (anchor+' '+text),1)
  if ' '.join(expected.split())!=' '.join(derived.split()):
   raise EditorError('transcript_conflict','edited_segment_text does not match the requested edit.')
  span=None
  style=p.get('instruction_style','replace_prompt')
  if style=='explicit_insert' and operation!='insert':
   raise EditorError('unsupported_instruction_style','instruction_style=explicit_insert applies to insert operations only.')
  if style=='replace_prompt':
   # v0.2.5: upstream/take-home phrasing "Replace 'old' with 'new'." (same words QA applies).
   # v0.2.6: insert and delete are expressed in the same supported form over a minimal span (confirmed on GPU
   # Oct 16: the free-form "Regenerate this speech as" prompt left the source unchanged; the Replace phrasing
   # produces the words but needs the v0.2.7 duration scaling below to fit them naturally).
   if operation=='replace': span=(old,replacement)
   elif operation=='insert': span=(anchor,(text+' '+anchor) if position=='before' else (anchor+' '+text))
   else:
    words=before.split(); target=text.split(); n=len(target)
    idx=[i for i in range(len(words)-n+1) if words[i:i+n]==target]
    if len(idx)==1 and len(words)>n:
     i=idx[0]
     span=(' '.join(words[i:i+n+1]),words[i+n]) if i+n<len(words) else (' '.join(words[i-1:i+n]),words[i-1])
  # v0.2.7 (whole_clip scope only): scale the output duration by the word-count change. A fixed
  # source-length target forces added words into the same time budget (Oct 16 insert smoke on
  # p326_028: seed 42 blended 'really believed' into 'relieved', seed 44 dropped 'really', seed 43
  # fit the text but the speaker score fell to 0.735 under the 0.75 gate - all consistent with
  # rushed timing at a fixed 3.22 s). Equal-word-count edits keep the source duration exactly.
  # Localized splices keep the checked interval duration: splice() requires an exact frame match
  # and the outside PCM must stay unchanged; a longer localized insert needs a wider interval.
  before_words=len(before.split());after_words=len(expected.split())
  scaled=None
  if p.get('segment_scope')=='whole_clip' and before_words and after_words!=before_words:
   ratio=min(max(after_words/before_words,0.5),2.0)
   scaled=duration*ratio
  if style=='explicit_insert':
   # Arm-B discriminator variant (opt-in only): name the insertion point explicitly instead of
   # expressing insert as a phrase replacement. Default replace_prompt behavior is unchanged.
   pos='before' if position=='before' else 'after'
   spec=EditSpec(operation='custom',
     instruction=f"Insert {_quote_words(text)} immediately {pos} {_quote_words(anchor)}. Keep every other word, the word order, and the speaker voice unchanged.",
     source_transcript=before,expected_transcript=expected,seed=p.get('seed',42),target_seconds=scaled)
  elif span is not None:
   spec=EditSpec(operation='replace_words',old_words=span[0],new_words=span[1],
     source_transcript=before,expected_transcript=expected,seed=p.get('seed',42),target_seconds=scaled)
  else:
   spec=EditSpec(operation='custom',instruction=f'Regenerate this speech as: {expected}. Preserve speaker identity and naturalness.',
    source_transcript=before,expected_transcript=expected,seed=p.get('seed',42),target_seconds=scaled)
  plan=build_plan(spec,duration,limits);plan['expected_transcript']=expected
 else:
  if operation=='custom':
   contract=p.get('semantic_contract',{})
   if not isinstance(contract,dict) or contract.get('preserve_transcript') is not True:
    raise EditorError('unsupported_contract','Custom v0.2 supports only preserve_transcript=True and requires quality review.')
  plan=build_plan(spec,duration,limits)
  plan['expected_transcript']=source
 plan['mode']=mode;plan['public_operation']=operation
 plan['identity_required']=operation!='voice_characteristics'
 plan['quality_review_required']=True
 return plan
