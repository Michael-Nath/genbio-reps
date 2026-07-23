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
- [x] 1.1 Autoregressive sequence model from scratch — the chain rule, teacher
      forcing, and a hand-written causal-attention transformer over amino acids;
      sampling, temperature, perplexity vs an exactly-computable Bayes floor.
- [x] 1.2 Masked language model (ESM/BERT-style) — the 80/10/10 masking objective,
      bidirectional attention, pseudo-perplexity, then *generating* by Gibbs
      sampling (and watching one-shot independent decoding fail). Infilling.
- [x] 1.3 Continuous diffusion (DDPM) — full forward/reverse from scratch on
      Ramachandran (phi, psi) angles: noise schedule, closed-form forward jump,
      eps-prediction, ancestral sampling, and a mode-coverage check.
- [x] 1.4 Flow matching — straight-line paths, constant velocity target, ODE
      sampling; measured head-to-head vs 1.3 (same data/net/budget) on quality
      per network evaluation, plus how straight the learned paths really are.
- [x] 1.5 Discrete / masked diffusion — [MASK] as the noise state, random
      corruption rates, iterative unmasking (random vs confidence-first order),
      and free motif conditioning. ~14x cheaper than 1.2's Gibbs. Core of DPLM.
- [x] 1.6 SE(3) frame diffusion — so3_exp/so3_log, geodesic flow matching on the
      rotation manifold + linear on translations; generates helix/strand backbones
      that stay exactly on SO(3). The simplified RFdiffusion / FrameFlow idea.

## Track 2 — Control (the payoff)
- [x] 2.1 Conditional generation & classifier-free guidance — label dropout to a
      NULL token, v_uncond + w(v_cond - v_uncond), and the measured cost: adherence
      saturates while samples get tighter than real data, then distort.
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
