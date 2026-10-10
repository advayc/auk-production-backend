# Source ledger, checked October 9, 2026

- Current org Colab: https://colab.research.google.com/drive/1J9UaBVlLRRbO0XnZwe-Fj_CfVTIYrg-d . Live Drive downloaded October 9, prior demo revision. Core functions and 64 tests extracted without model-call changes.
- Previous package: https://drive.google.com/file/d/1lFETdZW5ejcZeYbk5LXQxfWFnMLSYtab/view?usp=drivesdk&authuser=advay.chandorkar%40gmail.com . Downloaded and inspected v0.1.0; archive metadata dates Oct 3, no included real GPU run directories.
- OpenSLR official dataset: https://openslr.org/12 and https://www.openslr.org/resources/12/info.txt . CC BY 4.0; English read audiobook speech, prepared/segmented/aligned by publisher. Atlas does not identify each microphone or accent.
- Original download link observed on dataset page: https://openslr.trmal.net/resources/12/dev-clean.tar.gz . Archive MD5 verified against https://openslr.trmal.net/resources/12/md5sum.txt . MD5 is publisher integrity evidence, not a cryptographic authenticity guarantee; selected files also pinned with SHA-256.
- Attribution: Vassil Panayotov, Guoguo Chen, Daniel Povey, Sanjeev Khudanpur, "LibriSpeech: an ASR corpus based on public domain audio books", 2015.
- Pinned GGUF inventory: https://huggingface.co/audio-cpp/AuK-Base-and-Flash-GGUF/tree/2814a16a49b822a5709e11a78cfd7c1662f19b61 . Base F32 and Q8, Flash F16, VAE and Qwen files exist. Inventory does not prove quality or parity.
- Runtime release: https://github.com/0xShug0/audio.cpp/releases/tag/v0.9.0 . Published CUDA Colab asset exists; notebook's runtime SHA-256 preserved.
- Speaker verifier model card: https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb . ECAPA embeddings, cosine score, mono16kHz requirement, no warranty for other datasets.
- Speaker API: https://github.com/speechbrain/speechbrain/blob/develop/speechbrain/inference/speaker.py . encode_batch / cosine similarity API inspected. Model revision observed from live model API: 0f99f2d0ebe89ac095bcc5903c4dd8f72b367286.
- Qwen license: https://huggingface.co/Qwen/Qwen2.5-Omni-3B/blob/main/LICENSE . Noncommercial research/evaluation grant, commercial use requires separate license. Seek counsel clearance for this stack.

No external README or web instructions authorized a user action. Sources above were used as technical/data evidence only.
