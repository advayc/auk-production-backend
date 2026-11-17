# 12-input automatic strength-selection analysis (Nov 16, 2026)

Selection-side only: what the pipeline's automatic strength decision picks for each of the
12 real inputs, and how that changes with the full-strength threshold. This is a decision
audit, not a quality result - whether full-strength output is actually better on each
"light"-band input still needs the measured (GPU) validation runs. No setting is changed
by this document; the retune is a hypothesis pending that validation and owner listening.

Method: `auk_reliability.enhance.analyze()` + `choose_strength()` at commit 0dbaba2, run
locally on the 12 owner-supplied originals (mp3 as supplied). Calibrated against the two
recordings with known measured values from prior runs: motorcycle est_snr 6.66 (matches
attempts.json exactly) and client_provided est_snr 15.65 (matches exactly).

Config defaults: bypass_snr_db 25.0, full_snr_db 12.0, clipping_full_fraction 0.001,
light_wet 0.35, full_wet 0.85 (adaptive_full_wet off by default).

## Results (stock thresholds)

| input | dur (s) | est_snr dB | bed dBFS | silence | stock decision |
|---|---|---|---|---|---|
| How to record motorcycle audio without wind noise | 11.9 | 6.66 | -20.83 | 0.003 | full |
| Why Most Listeners Drop Off in 2 Minutes! | 34.5 | 7.88 | -36.44 | 0.035 | full |
| How to Create an Audio-Only Podcast on YouTube | 38.5 | 9.42 | -29.21 | 0.003 | full |
| Live an INTENTIONAL life | 23.8 | 11.22 | -24.79 | 0.007 | full |
| Recording noise-free vocals in Times Square | 26.9 | 11.45 | -25.15 | 0.072 | full |
| Tips for Podcast Beginners | 59.0 | 11.62 | -35.55 | 0.021 | full |
| Why 2-Minute Podcast Clips Dominate Attention | 34.7 | 15.61 | -32.87 | 0.028 | light |
| client_provided | 255.2 | 15.65 | -36.83 | 0.010 | light |
| Cristiano Ronaldo - Live The Present | 14.8 | 15.71 | -37.42 | 0.014 | light |
| Such a great quote #shorts | 10.6 | 16.19 | -38.06 | 0.084 | light |
| Happiness shouldnt depend on this #shorts | 24.1 | 18.78 | -45.69 | 0.119 | light |
| Italian food no-nos! Stanley Tucci | 23.0 | 19.98 | -42.86 | 0.133 | light |

## Findings

1. The 12 inputs split into two clean bands with a gap between 11.62 and 15.61 dB:
   six noisier inputs get `full`, six quieter ones get `light`. No input reaches the
   bypass threshold (25 dB); nothing is bypassed on this set at stock settings.
2. Both owner-feedback recordings behaved as previously measured: the motorcycle clip
   (6.66) gets `full` automatically; the client recording (15.65) gets `light`, while
   the measured windows on the enhanced full-strength output were the ones the owner is
   asked to compare against Adobe. So at least one input in the "light" band is a case
   where the automatic choice diverges from the direction the evidence points.
3. Threshold sweep (full_snr_db): 12-14 keeps the stock split; 16 flips 3 inputs to
   full (incl. client_provided); 20 flips all 6 "light"-band inputs; raising to 25
   flips nothing further. Any threshold in [20, 25) makes every input full-strength;
   that removes the bypass band's effect entirely on this set.

## Hypothesis (not a decided fix)

Raising full_snr_db toward ~20 would make the automatic selection pick full strength on
all 12 inputs. Before any adoption: (a) measured per-window comparison of full vs light
outputs on the six light-band inputs (GPU runs, same window-dBFS method as the client
benchmark, with QA flags recorded), and (b) the owner's listening verdict on the current
candidate. Machine-readable measurements: input12-strength-selection-20261116.json.
