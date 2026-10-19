# All ten cases per operation

90 executable tests: 60 voice-editor cases and 30 transcript-editor cases. Each table below lists all ten cases for that operation.

**These are code tests using simulated inference.** Real audio generation and human listening remain pending. The tests run real FFmpeg/WAV preparation, duration checks, QA routing, and artifact logging.

[Exact requests and expected results (JSON)](showcase_test_cases.json) · [Test source](../backend/tests/test_showcase_modes.py) · [Audio batch instructions](SHOWCASE.md)

## Run the presentation tests

From the repository root:

```sh
PYTHONPATH=backend:backend/tests python -m unittest test_showcase_modes -v
```

Run just the ten speed cases:

```sh
PYTHONPATH=backend:backend/tests python -m unittest discover -s backend/tests -p test_showcase_modes.py -k voice_editor_speed -v
```

Run one specific case:

```sh
PYTHONPATH=backend:backend/tests python -m unittest test_showcase_modes.ShowcaseOperationTests.test_voice_editor_speed_01 -v
```

Every case verifies a single attempt, a valid 24 kHz WAV with the planned frame count, the exact expected transcript, correct identity-QA routing, saved result metadata, and a pending human-review status. Transcript cases also verify the text changed and that whole-clip scope is recorded.

## voice_editor / emotion

| Case | Requested edit | Input text | Expected text | Output duration |
|---|---|---|---|---:|
| 01 | calm | They were the better team on the night | They were the better team on the night | 5 s |
| 02 | happy | They were the better team on the night according to everyone | They were the better team on the night according to everyone | 5 s |
| 03 | sad | They were the better team on the night in our opinion | They were the better team on the night in our opinion | 5 s |
| 04 | angry | They were the better team on the night despite the rain | They were the better team on the night despite the rain | 5 s |
| 05 | fearful | They were the better team on the night as we expected | They were the better team on the night as we expected | 5 s |
| 06 | surprised | They were the better team on the night by a wide margin | They were the better team on the night by a wide margin | 5 s |
| 07 | disgusted | They were the better team on the night after all | They were the better team on the night after all | 5 s |
| 08 | excited | They were the better team on the night without a doubt | They were the better team on the night without a doubt | 5 s |
| 09 | calm | They were the better team on the night against their rivals | They were the better team on the night against their rivals | 5 s |
| 10 | happy | They were the better team on the night this season | They were the better team on the night this season | 5 s |

## voice_editor / voice_characteristics

| Case | Requested edit | Input text | Expected text | Output duration |
|---|---|---|---|---:|
| 01 | warm and low | They were the better team on the night | They were the better team on the night | 5 s |
| 02 | bright and airy | They were the better team on the night according to everyone | They were the better team on the night according to everyone | 5 s |
| 03 | raspy | They were the better team on the night in our opinion | They were the better team on the night in our opinion | 5 s |
| 04 | smooth and resonant | They were the better team on the night despite the rain | They were the better team on the night despite the rain | 5 s |
| 05 | soft and breathy | They were the better team on the night as we expected | They were the better team on the night as we expected | 5 s |
| 06 | crisp and clear | They were the better team on the night by a wide margin | They were the better team on the night by a wide margin | 5 s |
| 07 | deep and rounded | They were the better team on the night after all | They were the better team on the night after all | 5 s |
| 08 | light and youthful | They were the better team on the night without a doubt | They were the better team on the night without a doubt | 5 s |
| 09 | rich and full | They were the better team on the night against their rivals | They were the better team on the night against their rivals | 5 s |
| 10 | thin and nasal | They were the better team on the night this season | They were the better team on the night this season | 5 s |

## voice_editor / whisper

| Case | Requested edit | Input text | Expected text | Output duration |
|---|---|---|---|---:|
| 01 | Soft whisper; preserve words and identity | They were the better team on the night | They were the better team on the night | 5 s |
| 02 | Soft whisper; preserve words and identity | They were the better team on the night according to everyone | They were the better team on the night according to everyone | 5 s |
| 03 | Soft whisper; preserve words and identity | They were the better team on the night in our opinion | They were the better team on the night in our opinion | 5 s |
| 04 | Soft whisper; preserve words and identity | They were the better team on the night despite the rain | They were the better team on the night despite the rain | 5 s |
| 05 | Soft whisper; preserve words and identity | They were the better team on the night as we expected | They were the better team on the night as we expected | 5 s |
| 06 | Soft whisper; preserve words and identity | They were the better team on the night by a wide margin | They were the better team on the night by a wide margin | 5 s |
| 07 | Soft whisper; preserve words and identity | They were the better team on the night after all | They were the better team on the night after all | 5 s |
| 08 | Soft whisper; preserve words and identity | They were the better team on the night without a doubt | They were the better team on the night without a doubt | 5 s |
| 09 | Soft whisper; preserve words and identity | They were the better team on the night against their rivals | They were the better team on the night against their rivals | 5 s |
| 10 | Soft whisper; preserve words and identity | They were the better team on the night this season | They were the better team on the night this season | 5 s |

## voice_editor / speed

| Case | Requested edit | Input text | Expected text | Output duration |
|---|---|---|---|---:|
| 01 | 0.5x speed | They were the better team on the night | They were the better team on the night | 10 s |
| 02 | 0.6x speed | They were the better team on the night according to everyone | They were the better team on the night according to everyone | 8.34 s |
| 03 | 0.75x speed | They were the better team on the night in our opinion | They were the better team on the night in our opinion | 6.68 s |
| 04 | 0.8x speed | They were the better team on the night despite the rain | They were the better team on the night despite the rain | 6.26 s |
| 05 | 0.9x speed | They were the better team on the night as we expected | They were the better team on the night as we expected | 5.56 s |
| 06 | 1.1x speed | They were the better team on the night by a wide margin | They were the better team on the night by a wide margin | 4.56 s |
| 07 | 1.25x speed | They were the better team on the night after all | They were the better team on the night after all | 4 s |
| 08 | 1.5x speed | They were the better team on the night without a doubt | They were the better team on the night without a doubt | 3.34 s |
| 09 | 1.75x speed | They were the better team on the night against their rivals | They were the better team on the night against their rivals | 2.86 s |
| 10 | 2x speed | They were the better team on the night this season | They were the better team on the night this season | 2.5 s |

## voice_editor / custom

| Case | Requested edit | Input text | Expected text | Output duration |
|---|---|---|---|---:|
| 01 | Sound confident. Keep every word unchanged. | They were the better team on the night | They were the better team on the night | 5 s |
| 02 | Sound bored and monotone. Keep every word unchanged. | They were the better team on the night according to everyone | They were the better team on the night according to everyone | 5 s |
| 03 | Sound gentle. Keep every word unchanged. | They were the better team on the night in our opinion | They were the better team on the night in our opinion | 5 s |
| 04 | Sound energetic. Keep every word unchanged. | They were the better team on the night despite the rain | They were the better team on the night despite the rain | 5 s |
| 05 | Sound hesitant. Keep every word unchanged. | They were the better team on the night as we expected | They were the better team on the night as we expected | 5 s |
| 06 | Sound reassuring. Keep every word unchanged. | They were the better team on the night by a wide margin | They were the better team on the night by a wide margin | 5 s |
| 07 | Sound formal. Keep every word unchanged. | They were the better team on the night after all | They were the better team on the night after all | 5 s |
| 08 | Sound conversational. Keep every word unchanged. | They were the better team on the night without a doubt | They were the better team on the night without a doubt | 5 s |
| 09 | Sound dramatic. Keep every word unchanged. | They were the better team on the night against their rivals | They were the better team on the night against their rivals | 5 s |
| 10 | Sound understated. Keep every word unchanged. | They were the better team on the night this season | They were the better team on the night this season | 5 s |

## voice_editor / nonverbal_remove

| Case | Requested edit | Input text | Expected text | Output duration |
|---|---|---|---|---:|
| 01 | Remove humming; shorten duration | They were the better team on the night | They were the better team on the night | 3 s |
| 02 | Remove humming; shorten duration | They were the better team on the night according to everyone | They were the better team on the night according to everyone | 3.1 s |
| 03 | Remove humming; shorten duration | They were the better team on the night in our opinion | They were the better team on the night in our opinion | 3.2 s |
| 04 | Remove humming; shorten duration | They were the better team on the night despite the rain | They were the better team on the night despite the rain | 3.3 s |
| 05 | Remove humming; shorten duration | They were the better team on the night as we expected | They were the better team on the night as we expected | 3.4 s |
| 06 | Remove humming; shorten duration | They were the better team on the night by a wide margin | They were the better team on the night by a wide margin | 3.5 s |
| 07 | Remove humming; shorten duration | They were the better team on the night after all | They were the better team on the night after all | 3.6 s |
| 08 | Remove humming; shorten duration | They were the better team on the night without a doubt | They were the better team on the night without a doubt | 3.7 s |
| 09 | Remove humming; shorten duration | They were the better team on the night against their rivals | They were the better team on the night against their rivals | 3.8 s |
| 10 | Remove humming; shorten duration | They were the better team on the night this season | They were the better team on the night this season | 3.9 s |

## transcript_editor / replace

| Case | Requested edit | Input text | Expected text | Output duration |
|---|---|---|---|---:|
| 01 | Replace 'better' with 'stronger' | They were the better team on the night | They were the stronger team on the night | 5 s |
| 02 | Replace 'better' with 'weaker' | They were the better team on the night according to everyone | They were the weaker team on the night according to everyone | 5 s |
| 03 | Replace 'team' with 'side' | They were the better team on the night in our opinion | They were the better side on the night in our opinion | 5 s |
| 04 | Replace 'night' with 'day' | They were the better team on the night despite the rain | They were the better team on the day despite the rain | 5 s |
| 05 | Replace 'the better' with 'a stronger' | They were the better team on the night as we expected | They were a stronger team on the night as we expected | 5 s |
| 06 | Replace 'better team' with 'stronger side' | They were the better team on the night by a wide margin | They were the stronger side on the night by a wide margin | 5 s |
| 07 | Replace 'on the night' with 'in the game' | They were the better team on the night after all | They were the better team in the game after all | 5 s |
| 08 | Replace 'They were' with 'We were' | They were the better team on the night without a doubt | We were the better team on the night without a doubt | 5 s |
| 09 | Replace 'They were' with 'They are' | They were the better team on the night against their rivals | They are the better team on the night against their rivals | 5 s |
| 10 | Replace 'the better team' with 'a much stronger side' | They were the better team on the night this season | They were a much stronger side on the night this season | 5.5 s |

## transcript_editor / insert

| Case | Requested edit | Input text | Expected text | Output duration |
|---|---|---|---|---:|
| 01 | Insert 'really' after 'were' | They were the better team on the night | They were really the better team on the night | 5.64 s |
| 02 | Insert 'clearly' after 'were' | They were the better team on the night according to everyone | They were clearly the better team on the night according to everyone | 5.46 s |
| 03 | Insert 'much' before 'better' | They were the better team on the night in our opinion | They were the much better team on the night in our opinion | 5.46 s |
| 04 | Insert 'football' before 'team' | They were the better team on the night despite the rain | They were the better football team on the night despite the rain | 5.46 s |
| 05 | Insert 'last' before 'night' | They were the better team on the night as we expected | They were the better team on the last night as we expected | 5.46 s |
| 06 | Insert 'certainly' after 'They' | They were the better team on the night by a wide margin | They certainly were the better team on the night by a wide margin | 5.42 s |
| 07 | Insert 'indeed' after 'team' | They were the better team on the night after all | They were the better team indeed on the night after all | 5.5 s |
| 08 | Insert 'by far' before 'the better' | They were the better team on the night without a doubt | They were by far the better team on the night without a doubt | 5.92 s |
| 09 | Insert 'without doubt' after 'were' | They were the better team on the night against their rivals | They were without doubt the better team on the night against their rivals | 5.92 s |
| 10 | Insert 'overall' after 'night' | They were the better team on the night this season | They were the better team on the night overall this season | 5.5 s |

## transcript_editor / delete

| Case | Requested edit | Input text | Expected text | Output duration |
|---|---|---|---|---:|
| 01 | Delete 'They' | They were the better team on the night | were the better team on the night | 4.38 s |
| 02 | Delete 'were' | They were the better team on the night according to everyone | They the better team on the night according to everyone | 4.56 s |
| 03 | Delete 'the better' | They were the better team on the night in our opinion | They were team on the night in our opinion | 4.1 s |
| 04 | Delete 'better' | They were the better team on the night despite the rain | They were the team on the night despite the rain | 4.56 s |
| 05 | Delete 'team' | They were the better team on the night as we expected | They were the better on the night as we expected | 4.56 s |
| 06 | Delete 'on the night' | They were the better team on the night by a wide margin | They were the better team by a wide margin | 3.76 s |
| 07 | Delete 'on' | They were the better team on the night after all | They were the better team the night after all | 4.5 s |
| 08 | Delete 'the night' | They were the better team on the night without a doubt | They were the better team on without a doubt | 4.1 s |
| 09 | Delete 'They were' | They were the better team on the night against their rivals | the better team on the night against their rivals | 4.1 s |
| 10 | Delete 'the better team' | They were the better team on the night this season | They were on the night this season | 3.5 s |

## Keep the index in sync

The exporter reads the same scenario builder that the executable tests use.

```sh
python demos/export_showcase_catalog.py
python demos/export_showcase_catalog.py --check
```
