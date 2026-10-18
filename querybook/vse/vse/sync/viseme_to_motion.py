"""Visemes → motion: the spec's single-stream mapper is the FaceMotionSynthesizer with neutral prosody/emotion/speaker
inputs, so one trained model serves both (see motion_synthesizer.py)."""
from .motion_synthesizer import FaceMotionSynthesizer, MotionGenerator, motion_loss  # noqa: F401
