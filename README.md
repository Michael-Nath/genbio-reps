# reps — a gym for controllable generation in biology

A personal, from-scratch training ground for the *machinery* behind controllable
generative models, taught through proteins.

## Run in Colab

Colab ships with numpy/matplotlib/torch preinstalled, so the notebooks just run.

- 0.1 Proteins as tensors — [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Michael-Nath/genbio-reps/blob/main/00_foundations/01_proteins_as_tensors.ipynb)
- 0.2 The oracle mindset — [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Michael-Nath/genbio-reps/blob/main/00_foundations/02_the_oracle_mindset.ipynb)
- 1.1 Autoregressive sequence model — [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Michael-Nath/genbio-reps/blob/main/01_generative_cores/01_autoregressive_sequence_model.ipynb)
- 1.2 Masked language model — [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Michael-Nath/genbio-reps/blob/main/01_generative_cores/02_masked_language_model.ipynb)
- 1.3 Continuous diffusion (DDPM) — [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Michael-Nath/genbio-reps/blob/main/01_generative_cores/03_continuous_diffusion_ddpm.ipynb)
- 1.4 Flow matching — [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Michael-Nath/genbio-reps/blob/main/01_generative_cores/04_flow_matching.ipynb)
- 1.5 Discrete / masked diffusion — [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Michael-Nath/genbio-reps/blob/main/01_generative_cores/05_discrete_masked_diffusion.ipynb)
- 1.6 SE(3) frame diffusion — [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Michael-Nath/genbio-reps/blob/main/01_generative_cores/06_se3_frame_diffusion.ipynb)
- 2.1 Conditional generation & CFG — [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Michael-Nath/genbio-reps/blob/main/02_control/01_conditional_generation_cfg.ipynb)

While the repo is **private**, the first click needs a one-time grant: in Colab,
`File -> Open notebook -> GitHub`, tick *Include private repos*, and authorize.
To save edits back, use `File -> Save a copy in GitHub` (GitHub stays the source
of truth). If you make the repo public, every link above works with no auth.

## Work through it live with a friend

Pair on a notebook in real time — shared cells, edits, and outputs over a single
kernel, low latency:

```bash
cd collab && ./share.sh
```

It prints a public URL; send it to your partner and you're both in the same live
notebook. See [`collab/README.md`](collab/README.md).

## Philosophy

Most people "learn" generative bio by running someone's repo. It works, and they
learn nothing transferable. This repo inverts that:

- **One mechanism per notebook.** Isolate a single piece of machinery
  (a diffusion step, a guidance term, a REINFORCE update) and nothing else.
- **Toy first, protein second.** Build the mechanism on tiny data where you can
  print every tensor, *then* apply the identical code to a minimal protein
  instance.
- **You write the core.** Notebooks ship with `raise NotImplementedError`
  scaffolds and `assert` checkpoints, so you know when a rep is correct without
  anyone grading it. Reference solutions live at the bottom of each notebook —
  don't scroll there until you've tried.
- **Everything transfers.** The same diffusion / guidance / RL machinery steers
  images, audio, and text. Proteins are just the vehicle.

## How to use it

1. `pip install -r requirements.txt`
2. Open a notebook in order (see `ROADMAP.md`).
3. Read the concept cell, do the reps, make the checkpoints pass.
4. Only then read the reference solution and the reflection.

## Status

Built one rep at a time, on purpose. See `ROADMAP.md` for the ladder and what's
done. Compute: everything through Track 1 runs on a laptop CPU. Heavier reps
(pretrained ESM/AlphaFold, real training) will note their requirements.
