# Roadmap — the ladder

Each rung is one piece of machinery. Build it on a toy problem, then on a
minimal protein instance. Rungs build on earlier ones, so go in order.

Legend: [x] done · [ ] planned

## Track 0 — Foundations
- [x] 0.1 Proteins as tensors — sequence/structure as arrays, distance & contact
      maps, per-residue SE(3) frames (foreshadows structure diffusion).
- [x] 0.2 The oracle mindset — what "controllable generation" means formally:
      generator `p(x)`, oracle `f(x)`, target `p(x | f(x)=y)`. Rejection vs reward
      tilting `p(x)exp(r/T)`, the reward-vs-diversity frontier, multi-objective design.

## Track 1 — Generative cores (the engines you will later steer)
- [ ] 1.1 Autoregressive sequence model from scratch — a tiny transformer over
      amino acids; sampling, temperature, perplexity.
- [ ] 1.2 Masked language model (ESM/BERT-style) — the masking objective, then
      *generating* by Gibbs sampling from the masked model.
- [ ] 1.3 Continuous diffusion (DDPM) — full forward/reverse from scratch on toy
      2D data. The mechanism, demystified.
- [ ] 1.4 Flow matching — the modern reframing of 1.3; simpler, faster.
- [ ] 1.5 Discrete / masked diffusion (D3PM, masked-diffusion) — diffusion for
      sequences. This is the core of DPLM.
- [ ] 1.6 SE(3) frame diffusion — generate per-residue frames on a toy manifold;
      the simplified idea behind RFdiffusion / FrameFlow / FoldFlow.

## Track 2 — Control (the payoff)
- [ ] 2.1 Conditional generation & classifier-free guidance — condition tokens,
      the CFG trick, guidance scale.
- [ ] 2.2 Classifier guidance & training-free guidance — steer a *frozen*
      generator toward a property oracle via gradients.
- [ ] 2.3 RL on a generator — REINFORCE, then DPO — maximize an oracle reward.
      (Same problem as RLHF on an LLM, with a clean reward signal.)
- [ ] 2.4 Inverse folding as conditioning — structure -> sequence, the
      ProteinMPNN idea.

## Track 3 — The design–build–test loop
- [ ] 3.1 Closing the loop — generate -> score with a pretrained oracle
      (ESMFold/ESM) -> filter -> active learning / Bayesian optimization.

## Notebook contract
Every notebook: **Concept -> Warmup (toy) -> Reps (TODO) -> Checkpoints (assert)
-> Protein instance -> Reflection (what transfers) -> Solutions appendix.**
