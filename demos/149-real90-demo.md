# AuK real90 demo

## Transcript replace (7)

### 1. Replace 'sold out' with 'available'.
`replace-01` · target transcript: "The show is available, like the others in the run."
CPU repair v8 (Oct 20): low-frequency thump removed (140 Hz zero-phase filter on the event span) and the flagged 0.23 s dead-air gap cut (10 ms crossfades; tail time-shifted 0.24 s). WER exact, speaker match 0.922, defect screen clean. Approved by user listening review Oct 20.

**Before**

https://github.com/user-attachments/assets/2aa5337b-8e0a-44f5-a724-7ec8db41041b

**After**

https://github.com/user-attachments/assets/fd82f044-f62c-4bc1-91e7-40935e0ad3ed

### 2. Replace 'believed' with 'thought'.
`replace-02` · target transcript: "It is thought he had been stabbed."
Automated screen: 6/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/b20ddafc-f77a-41c8-a739-d5e23d9a5a29

**After**

https://github.com/user-attachments/assets/a9ea59d1-c071-4f1f-befb-0d9b5c7089af

### 3. Replace 'People' with 'Visitors'.
`replace-04` · target transcript: "Visitors come into the Borders for the beauty of the background."
Automated screen: 8/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/ebb974bb-b23c-4f3e-8488-20053b1f52d0

**After**

https://github.com/user-attachments/assets/e0411a6b-545f-4e75-b031-46dd4b197cc1

### 4. Replace 'air traffic' with 'local traffic'.
`replace-05` · target transcript: "The main concern is that it could interfere with local traffic."
Automated screen: 1/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/13884750-7367-4cf6-8827-263544007fee

**After**

https://github.com/user-attachments/assets/fc34f542-8c84-42e8-96a3-8ef10198e964

### 5. Replace 'Several other' with 'Many other'.
`replace-06` · target transcript: "Many other countries are also reported to be interested in the format."
Regenerated Oct 20 (Phase C, seed 44): the duplicated "other" is gone. WER exact, speaker match 0.909, defect screen clean. Approved by user listening review Oct 20.

**Before**

https://github.com/user-attachments/assets/ca968871-5f89-4ede-92a2-05b7e11dd067

**After**

https://github.com/user-attachments/assets/63ca750b-2047-4d5c-991a-449fa87ad37f

### 6. Replace 'London' with 'Edinburgh'.
`replace-07` · target transcript: "He was born in Edinburgh of Scottish parents."
Automated screen: 6/10 (acoustic checks only, not a listening rating).
CPU repair candidate (everything outside the edited span preserved); listening review pending.

**Before**

https://github.com/user-attachments/assets/bdc904bb-ab66-4b7b-b1d8-7ece02b1ddec

**After**

https://github.com/user-attachments/assets/3535a8ab-10f5-4960-afaf-b08d87e463df

### 7. Replace 'money' with 'reward'.
`replace-09` · target transcript: "I am not interested in the reward, it is the principle."
Automated screen: 6/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/90765e3d-956e-4229-960e-368dad4268c8

**After**

https://github.com/user-attachments/assets/d5d95fb6-b3bd-4916-b4ce-ed7c168ed32e

## Transcript delete (9)

### 1. Replace 'out, like the others in the run.' with 'out,'.
`delete-01` · target transcript: "The show is sold out,"
Automated screen: 1/10 (acoustic checks only, not a listening rating).
CPU repair candidate (everything outside the edited span preserved); listening review pending.

**Before**

https://github.com/user-attachments/assets/360ae33b-e389-4f9a-9727-65853000b105

**After**

https://github.com/user-attachments/assets/a97cac25-dc05-4eef-8544-6c9b63db25ac

### 2. Replace 'It is believed he' with 'he'.
`delete-02` · target transcript: "he had been stabbed."
Automated screen: 7/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/c6b94eca-eaf0-4477-8e4c-eaf4f0e193ea

**After**

https://github.com/user-attachments/assets/232318be-ab97-4042-a729-f3c7fb9c0c60

### 3. Replace 'George Mitchell' with 'Mitchell'.
`delete-03` · target transcript: "Mitchell is trying to close the gap."
Automated screen: 6/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/d79dd695-6333-4224-8eeb-fa8187ead439

**After**

https://github.com/user-attachments/assets/f8653912-b5bf-4689-b75a-cf97ef729046

### 4. Replace 'main concern' with 'concern'.
`delete-05` · target transcript: "The concern is that it could interfere with air traffic."
Automated screen: 1/10 (acoustic checks only, not a listening rating).
CPU repair candidate (everything outside the edited span preserved); listening review pending.

**Before**

https://github.com/user-attachments/assets/920fcd0d-7347-4b45-9a45-2cd801776fa5

**After**

https://github.com/user-attachments/assets/02d03ed0-6b62-4b6f-af30-cd6dbea5202d

### 5. Replace 'Several other countries' with 'countries'.
`delete-06` · target transcript: "countries are also reported to be interested in the format."
Automated screen: 10/10 (acoustic checks only, not a listening rating).
CPU repair candidate (everything outside the edited span preserved); listening review pending.

**Before**

https://github.com/user-attachments/assets/09402505-afca-4b8a-813a-25eef1874c3f

**After**

https://github.com/user-attachments/assets/ad89397d-9e38-4d01-a63d-4993cb3622d5

### 6. Replace 'London of Scottish parents.' with 'London'.
`delete-07` · target transcript: "He was born in London"
Automated screen: 6/10 (acoustic checks only, not a listening rating).
CPU repair candidate (everything outside the edited span preserved); listening review pending.

**Before**

https://github.com/user-attachments/assets/bb039b66-7ab6-4563-8748-bae7fded1425

**After**

https://github.com/user-attachments/assets/e96e1123-be16-40c0-b377-b870ef9a3456

### 7. Replace 'Last night, Mr' with 'Mr'.
`delete-08` · target transcript: "Mr Robertson said he was delighted."
Automated screen: 9/10 (acoustic checks only, not a listening rating).
CPU repair candidate (everything outside the edited span preserved); listening review pending.

**Before**

https://github.com/user-attachments/assets/67b5792d-af19-4573-abb1-873345e3bf16

**After**

https://github.com/user-attachments/assets/cb9db723-170d-4225-82bc-1ef80bda87ef

### 8. Replace 'not interested' with 'interested'.
`delete-09` · target transcript: "I am interested in the money, it is the principle."
Automated screen: 7/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/1d571ae2-3747-46dd-bd9f-79823c0c8907

**After**

https://github.com/user-attachments/assets/2cf90cbf-5566-45a9-ab01-327778cb403c

### 9. Replace 'however, in' with 'in'.
`delete-10` · target transcript: "The Scots are, in good company."
Automated screen: 7/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/407c20ab-253e-4f0c-98e6-8695958080f1

**After**

https://github.com/user-attachments/assets/382ffc9c-3e9b-498a-904a-02d339956a52

## Transcript insert (7)

### 1. Replace 'believed' with 'widely believed'.
`insert-02` · target transcript: "It is widely believed he had been stabbed."
Automated screen: 4/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/fa32d3ba-f767-4dc9-b44a-66feec238410

**After**

https://github.com/user-attachments/assets/d3d9ee51-1d6f-44db-9695-63014fe67231

### 2. Replace 'come' with 'often come'.
`insert-04` · target transcript: "People often come into the Borders for the beauty of the background."
Automated screen: 8/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/1983ceef-95c4-4988-8020-c61150eebeb4

**After**

https://github.com/user-attachments/assets/2ec01b2c-a1de-4bad-a2f1-8b3985626d5f

### 3. Replace 'Several' with 'Many agree. Several'.
`insert-06` · target transcript: "Many agree. Several other countries are also reported to be interested in the format."
Automated screen: 3/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/0af4a9c1-468c-4f50-af95-a51f58e00173

**After**

https://github.com/user-attachments/assets/0210d0e5-57c7-424b-9ca6-ae9d897bdd6b

### 4. Replace 'born' with 'originally born'.
`insert-07` · target transcript: "He was originally born in London of Scottish parents."
Automated screen: 6/10 (acoustic checks only, not a listening rating).
CPU repair candidate (everything outside the edited span preserved); listening review pending.

**Before**

https://github.com/user-attachments/assets/50890df7-eb26-4da5-9027-7a2d605b111f

**After**

https://github.com/user-attachments/assets/f160dfaf-f16b-48b8-b05d-5ae64f4aac60

### 5. Replace 'delighted' with 'very delighted'.
`insert-08` · target transcript: "Last night, Mr Robertson said he was very delighted."
Automated screen: 5/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/42d0b03c-5286-4a49-9ed6-309aabb5d305

**After**

https://github.com/user-attachments/assets/44d02e80-446a-4397-ac6a-a2fed358edd1

### 6. Replace 'interested' with 'interested at all'.
`insert-09` · target transcript: "I am not interested at all in the money, it is the principle."
Automated screen: 6/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/3eb512b0-f2d0-4401-b227-0443f8aa221e

**After**

https://github.com/user-attachments/assets/e9b9253e-97c6-4b08-91db-e1befead869d

### 7. Replace 'however,' with 'however, indeed'.
`insert-10` · target transcript: "The Scots are, however, indeed in good company."
Automated screen: 4/10 (acoustic checks only, not a listening rating).
CPU repair candidate (everything outside the edited span preserved); listening review pending.

**Before**

https://github.com/user-attachments/assets/856fb20e-216f-49f7-af7a-3d3068fffaa6

**After**

https://github.com/user-attachments/assets/a4e82c61-03ef-49c2-bf1e-424a0c4c583e

## Voice characteristics (10)

### 1. Keep the words unchanged. Change the voice character to "warm and low".
`voice_characteristics-01` · target transcript: "The show is sold out, like the others in the run."
Automated screen: 1/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/fdc1ffb9-49e9-4bb2-8697-44dcce73efe8

**After**

https://github.com/user-attachments/assets/31f81d79-86ce-4f91-927c-f78984a72819

### 2. Keep the words unchanged. Change the voice character to "bright and airy".
`voice_characteristics-02` · target transcript: "It is believed he had been stabbed."
Automated screen: 6/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/909603c2-e40b-4a61-ac32-51bc93e65f61

**After**

https://github.com/user-attachments/assets/a1693c79-d8c9-4b98-ad55-f2f58caf7b41

### 3. Keep the words unchanged. Change the voice character to "raspy".
`voice_characteristics-03` · target transcript: "George Mitchell is trying to close the gap."
Automated screen: 6/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/27d179c8-1248-466b-82d1-79f2b6e34919

**After**

https://github.com/user-attachments/assets/dfce3dc5-773f-4be1-932e-bb73e6121eb8

### 4. Keep the words unchanged. Change the voice character to "smooth and resonant".
`voice_characteristics-04` · target transcript: "People come into the Borders for the beauty of the background."
Automated screen: 7/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/b0aa98ed-ec57-4c00-99d0-51275abf935a

**After**

https://github.com/user-attachments/assets/d3bf3879-d447-4ce0-ad2a-062e83d49e44

### 5. Keep the words unchanged. Change the voice character to "soft and breathy".
`voice_characteristics-05` · target transcript: "The main concern is that it could interfere with air traffic."
Automated screen: 1/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/545489ae-543a-4d36-8d6c-5fe4e8fa9f37

**After**

https://github.com/user-attachments/assets/a5f2a2b7-cf91-471e-b1e0-d61dea0e2a46

### 6. Keep the words unchanged. Change the voice character to "crisp and clear".
`voice_characteristics-06` · target transcript: "Several other countries are also reported to be interested in the format."
Automated screen: 1/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/eebd8b8c-ce03-4771-8067-a41671366967

**After**

https://github.com/user-attachments/assets/9bdcaf72-b4aa-43d5-9a61-768e7811bccd

### 7. Keep the words unchanged. Change the voice character to "deep and rounded".
`voice_characteristics-07` · target transcript: "He was born in London of Scottish parents."
Automated screen: 6/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/8b7e53c3-e8cd-40e3-afe4-68f2d7268d4b

**After**

https://github.com/user-attachments/assets/94a8b741-d1ff-4118-808e-1d4726ff2d5d

### 8. Keep the words unchanged. Change the voice character to "light and youthful".
`voice_characteristics-08` · target transcript: "Last night, Mr Robertson said he was delighted."
Automated screen: 1/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/36bd7686-9fb2-4ece-a058-687c56d1b24f

**After**

https://github.com/user-attachments/assets/1dc0cd99-ae6d-49cb-8979-39ed7dc4b33c

### 9. Keep the words unchanged. Change the voice character to "rich and full".
`voice_characteristics-09` · target transcript: "I am not interested in the money, it is the principle."
Automated screen: 7/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/07ed2bd1-0a01-4081-b21e-a43836bd27f4

**After**

https://github.com/user-attachments/assets/8745c2c9-cb9f-403d-9197-b2399c3fc54c

### 10. Keep the words unchanged. Change the voice character to "thin and nasal".
`voice_characteristics-10` · target transcript: "The Scots are, however, in good company."
After player restored in the Oct 20 update (was missing). Automated screen 3/10 - flagged, shown for completeness; listening review pending.
Automated screen: 3/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/7febe1d6-156a-4928-8347-ea8dbea222b2

**After** - player upload pending, lands in the second commit.

**After**

https://github.com/user-attachments/assets/8f36f461-f20d-4434-be5a-2843c9bc0a58
## Custom style (5)

### 1. Sound gentle. Keep every word unchanged.
`custom-03` · target transcript: "George Mitchell is trying to close the gap."
Automated screen: 6/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/03ae3011-a809-4127-a873-341192f3a127

**After**

https://github.com/user-attachments/assets/fbd353df-eec8-4e57-922e-85f7da100e60

### 2. Sound hesitant. Keep every word unchanged.
`custom-05` · target transcript: "The main concern is that it could interfere with air traffic."
Automated screen: 1/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/083fc8f1-c46f-46af-b58f-e594b16aacb9

**After**

https://github.com/user-attachments/assets/8e264744-4191-410d-aa5a-b64e941bf8ec

### 3. Sound reassuring. Keep every word unchanged.
`custom-06` · target transcript: "Several other countries are also reported to be interested in the format."
Automated screen: 3/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/5be4cb89-ce23-4df5-966e-7f85c571af8c

**After**

https://github.com/user-attachments/assets/99093495-5526-4808-97ad-fee90da7135e

### 4. Sound formal. Keep every word unchanged.
`custom-07` · target transcript: "He was born in London of Scottish parents."
Automated screen: 6/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/a2a1f150-4a2d-4b6b-bfd6-3af556837103

**After**

https://github.com/user-attachments/assets/50b9a873-fd6c-4f79-8424-7a90e72e7dba

### 5. Sound conversational. Keep every word unchanged.
`custom-08` · target transcript: "Last night, Mr Robertson said he was delighted."
Automated screen: 5/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/b8fa3911-fdf9-420b-bd44-3b72e9ad1ed8

**After**

https://github.com/user-attachments/assets/84da9d54-8dc8-42ee-a823-bfe1a14ab1b2

## Nonverbal removal (8)

### 1. Remove the humming from the audio.
`nonverbal_remove-01` · target transcript: "The show is sold out, like the others in the run."
Automated screen: 1/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/cc5e591d-3de2-443f-8b9f-5e94a282bd05

**After**

https://github.com/user-attachments/assets/d000da02-7be5-45d4-8245-b0569f2ad06f

### 2. Remove the humming from the audio.
`nonverbal_remove-02` · target transcript: "It is believed he had been stabbed."
Automated screen: 6/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/0a2b56a9-96a7-47c9-a022-aeb20d303f3e

**After**

https://github.com/user-attachments/assets/67893494-440a-475e-9246-4d0705dbe6e6

### 3. Remove the humming from the audio.
`nonverbal_remove-03` · target transcript: "George Mitchell is trying to close the gap."
Automated screen: 6/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/d514a09a-9526-481d-a0dc-f5d98f2e6e8e

**After**

https://github.com/user-attachments/assets/74e5ef93-4475-4d8c-b8fb-02552ecc2867

### 4. Remove the humming from the audio.
`nonverbal_remove-04` · target transcript: "People come into the Borders for the beauty of the background."
Automated screen: 7/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/a8e861d7-82c5-41f9-84d6-6abc356cf0b6

**After**

https://github.com/user-attachments/assets/8d0a2809-199e-4f80-823d-3326207d7851

### 5. Remove the humming from the audio.
`nonverbal_remove-05` · target transcript: "The main concern is that it could interfere with air traffic."
Automated screen: 1/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/4641dfbd-c6a7-44b8-be98-da4f61e94dd2

**After**

https://github.com/user-attachments/assets/2f5819e2-70b1-42f4-96c1-6e7bb1bfb0b5

### 6. Remove the humming from the audio.
`nonverbal_remove-07` · target transcript: "He was born in London of Scottish parents."
Automated screen: 6/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/d9b66904-595d-4bac-bccf-f85b1344c30c

**After**

https://github.com/user-attachments/assets/40086092-559a-4d20-828c-c40c3f6624c0

### 7. Remove the humming from the audio.
`nonverbal_remove-08` · target transcript: "Last night, Mr Robertson said he was delighted."
Automated screen: 7/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/8004f0ae-1418-4347-997e-04844f44514a

**After**

https://github.com/user-attachments/assets/41f33201-ae9b-4144-9034-9f9b0f7af88e

### 8. Remove the humming from the audio.
`nonverbal_remove-10` · target transcript: "The Scots are, however, in good company."
Automated screen: 7/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/97966def-16db-4e6f-b8b1-3d6e588131e8

**After**

https://github.com/user-attachments/assets/8fc3b8dc-ee30-4add-8ddb-0d03a29bb088

### 9. Remove the humming from the audio (Phase C regen + repair).
`nonverbal_remove-06` · regenerated Oct 20 (Phase C, seed 43) + single-sample glitch repair (cubic deglitch at 1.04-1.05 s). WER exact, speaker match 0.847, acoustic + defect screens clean. Listening review pending.

**Before**

https://github.com/user-attachments/assets/99d16fa2-c0de-4b18-943a-884bd5dd170e

**After**

https://github.com/user-attachments/assets/bc4fb73d-abad-44f0-812f-f70dbf6da5ee
## Speed (4)

### 1. Adjust the speech speed to 0.6x.
`speed-02` · target transcript: "It is believed he had been stabbed."
Automated screen: 7/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/247b8d4c-8e9c-4510-942a-c34a26d46f46

**After**

https://github.com/user-attachments/assets/d9051587-56c9-4f8a-9c6e-a2d17efbf2e6

### 2. Adjust the speech speed to 0.75x.
`speed-03` · target transcript: "George Mitchell is trying to close the gap."
Automated screen: 6/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/12a439cf-018c-45bf-a76e-9ca3db993d7e

**After**

https://github.com/user-attachments/assets/83969987-149d-47b2-a5db-912a8bfbecb8

### 3. Adjust the speech speed to 1.25x.
`speed-07` · target transcript: "He was born in London of Scottish parents."
Automated screen: 7/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/2bcb2860-46c6-41d0-85fd-651c0c68dfcb

**After**

https://github.com/user-attachments/assets/3f08741e-1284-4af6-bf8a-64a3ae3ba08f

### 4. Adjust the speech speed to 1.5x.
`speed-08` · target transcript: "Last night, Mr Robertson said he was delighted."
Automated screen: 7/10 (acoustic checks only, not a listening rating).

**Before**

https://github.com/user-attachments/assets/aec0a98a-d656-4173-8291-b04a49a55f2c

**After**

https://github.com/user-attachments/assets/f48cbdfc-0e42-4b64-93ba-0a0d719832b9

### 5. Adjust the speech speed (Phase C regen, seed 44).
`speed-06` · regenerated Oct 20. WER exact, speaker match 0.810, acoustic + defect screens clean. Listening review pending.

**Before**

https://github.com/user-attachments/assets/12acbfd1-f5a8-4250-8023-ac2e3d87a38a

**After**

https://github.com/user-attachments/assets/4a83d394-42fa-4d86-b709-58c635cd8cc0
## Multi-word replace (2, new Oct 20)
### 1. Replace 'are also reported to be interested' with 'have also expressed strong interest'.
`replacemw-04` · target transcript: "Several other countries have also expressed strong interest in the format." Regenerated Oct 20 (Phase C, seed 44) + single-sample glitch repair (cubic deglitch at 1.05-1.06 s). WER exact, speaker match 0.891, acoustic + defect screens clean. Listening review pending.

**Before**

https://github.com/user-attachments/assets/4073b276-b3fa-4d65-bb17-fbd8194eaa58

**After**

https://github.com/user-attachments/assets/00a8f53b-473f-4d62-991c-8bdd8dd7741d

### 2. Replace 'am not interested in' with 'do not care about'.
`replacemw-05` · target transcript: "I do not care about the money, it is the principle." Regenerated Oct 20 (Phase C, seed 43). WER exact, speaker match 0.859, acoustic + defect screens clean. Listening review pending.

**Before**

https://github.com/user-attachments/assets/c2c8da64-ab59-442f-9ebe-24befbf48c36

**After**

https://github.com/user-attachments/assets/71e04a7e-1017-4f14-8cb4-3fa023956177
## Whisper (4)
### 1. Whisper-style read (keep every word unchanged).
`whisper-02` · Automated screen: 6/10 (acoustic checks only, not a listening rating). Listening review pending.

**Before**

https://github.com/user-attachments/assets/0c4631b1-bdfa-4a86-9d9c-cedf43c792bb

**After**

https://github.com/user-attachments/assets/60116f73-3e20-4f87-be6f-32ee53ccbb97

### 2. Whisper-style read (keep every word unchanged).
`whisper-03` · Automated screen: 6/10 (acoustic checks only, not a listening rating). Listening review pending.

**Before**

https://github.com/user-attachments/assets/26470fe1-5217-4ee7-9d1a-2b6ce978e683

**After**

https://github.com/user-attachments/assets/55566485-1374-4e9f-9138-bac49457e6fa

### 3. Whisper-style read (keep every word unchanged).
`whisper-04` · Automated screen: 7/10 (acoustic checks only, not a listening rating). Listening review pending.

**Before**

https://github.com/user-attachments/assets/5f53282d-0a8e-48d7-b193-70aaaba68a48

**After**

https://github.com/user-attachments/assets/0524eb24-e522-4b71-9523-0aa3420c02e2

### 4. Whisper-style read (keep every word unchanged).
`whisper-09` · Automated screen: 7/10 (acoustic checks only, not a listening rating). Listening review pending.

**Before**

https://github.com/user-attachments/assets/f28eaae0-ecac-4452-90fc-e185b9881ca8

**After**

https://github.com/user-attachments/assets/151e0fa8-acbc-477c-853f-364454319e43
## Status of the rest

Oct 20 update: the replace-01 and replace-06 Afters are the versions approved in the user's listening review. nonverbal_remove-06, speed-06, the two multi-word cases, voice_characteristics-10's missing After player, and four whisper players were added from the Oct 20 regeneration run or repaired wrappers; all are labeled listening-pending.

Updated versions held back from this showcase because automated screens still flag them: replace-03, insert-03, emotion-05, nonverbal_remove-09, whisper-08 (interior gaps or repeat signatures), custom-04 (low-frequency event inherited from the source recording), replace-08 (residual low-frequency event after repair), whisper-01, whisper-05, whisper-06 (low automated scores). They are excluded rather than presented as passing.

Automated screens catch gaps, clicks, clipping, and repeated-word signatures; they cannot judge naturalness. Every After marked "listening review pending" is unheard by a human. The two approved entries were confirmed by the user on Oct 20.

Every After not marked as a repair or regeneration is the original one-attempt output; CPU repairs preserve all audio outside the edited span. Evaluation-only, noncommercial; source audio LibriSpeech dev-clean (CC BY 4.0).
