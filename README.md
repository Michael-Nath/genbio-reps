# reps — a gym for controllable generation in biology

A personal, from-scratch training ground for the *machinery* behind controllable
generative models, taught through proteins.

## Run in Colab

Colab ships with numpy/matplotlib/torch preinstalled, so the notebooks just run.

- 0.1 Proteins as tensors — [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Michael-Nath/genbio-reps/blob/main/00_foundations/01_proteins_as_tensors.ipynb)

While the repo is **private**, the first click needs a one-time grant: in Colab,
`File -> Open notebook -> GitHub`, tick *Include private repos*, and authorize.
To save edits back, use `File -> Save a copy in GitHub` (GitHub stays the source
of truth). If you make the repo public, every link above works with no auth.

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
