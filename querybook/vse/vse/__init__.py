"""Visual Speech Engine — stage 2 (trainable PyTorch models).

Same data formats and API as the stage-1 engine inside QueryBook's Language Builder (apps/language/vse.py),
so each trained subsystem can replace its stage-1 counterpart and be measured with the same benchmark.
Nothing here is trained: checkpoints come from the scripts/ training jobs on your own GPUs and licensed data.
"""
__version__ = "0.1.0"
