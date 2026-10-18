"""Log-mel spectrogram (torch.stft), 10 ms hop."""
from __future__ import annotations

import math

import torch


def mel_filterbank(n_fft, sr, n_mels, fmin=20.0, fmax=None):
    fmax = fmax or sr / 2
    mel = lambda f: 2595 * math.log10(1 + f / 700.0)
    inv = lambda m: 700 * (10 ** (m / 2595.0) - 1)
    pts = torch.tensor([inv(mel(fmin) + (mel(fmax) - mel(fmin)) * i / (n_mels + 1)) for i in range(n_mels + 2)])
    freqs = torch.linspace(0, sr / 2, n_fft // 2 + 1)
    fb = torch.zeros(n_mels, n_fft // 2 + 1)
    for m in range(n_mels):
        lo, c, hi = pts[m], pts[m + 1], pts[m + 2]
        fb[m] = torch.clamp(torch.minimum((freqs - lo) / (c - lo), (hi - freqs) / (hi - c)), min=0.0)
    return fb


class LogMel(torch.nn.Module):
    def __init__(self, sample_rate=16000, n_mels=80, win_ms=25.0, hop_ms=10.0):
        super().__init__()
        self.win = int(sample_rate * win_ms / 1000)
        self.hop = int(sample_rate * hop_ms / 1000)
        self.n_fft = 1 << (self.win - 1).bit_length()
        self.register_buffer("fb", mel_filterbank(self.n_fft, sample_rate, n_mels), persistent=False)
        self.register_buffer("window", torch.hann_window(self.win), persistent=False)
        self.hop_s = hop_ms / 1000.0

    def forward(self, wav):                 # wav: [B, N] float → [B, T, n_mels]
        spec = torch.stft(wav, self.n_fft, self.hop, self.win, self.window, center=True, return_complex=True)
        power = spec.abs() ** 2                                  # [B, F, T]
        mel = torch.matmul(self.fb, power).clamp(min=1e-10).log()
        mel = mel - mel.mean(dim=-1, keepdim=True)               # per-utterance mean normalization
        return mel.transpose(1, 2)
