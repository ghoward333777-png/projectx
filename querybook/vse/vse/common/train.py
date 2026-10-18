"""One training loop for every model: AdamW, warm-up + cosine schedule, mixed precision, gradient clipping,
periodic validation, best/last checkpoints. Each model supplies `loss(batch) -> (loss, metrics)`."""
from __future__ import annotations

import math
import os
import random
import time

import torch

from .logging import get_logger

log = get_logger("vse.train")


def seed_all(seed):
    random.seed(seed)
    torch.manual_seed(seed)


def schedule(step, warmup, total):
    if step < warmup:
        return (step + 1) / max(1, warmup)
    p = (step - warmup) / max(1, total - warmup)
    return 0.5 * (1 + math.cos(math.pi * min(1.0, p)))


def train(model, loss_fn, train_loader, val_loader, cfg, max_steps=None, on_eval=None):
    """Run training. loss_fn(model, batch, device) -> (loss tensor, {metric: float}). Returns the last metrics."""
    device = torch.device(cfg.device if (cfg.device != "cuda" or torch.cuda.is_available()) else "cpu")
    seed_all(cfg.seed)
    model.to(device)
    if cfg.init_from:
        model.load_state_dict(torch.load(cfg.init_from, map_location=device)["model"], strict=False)
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.optim.lr, weight_decay=cfg.optim.weight_decay, betas=tuple(cfg.optim.betas))
    total = max_steps or cfg.optim.max_steps
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: schedule(s, cfg.optim.warmup_steps, total))
    use_amp = cfg.optim.amp and device.type == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
    os.makedirs(cfg.checkpoint_dir, exist_ok=True)
    step, best, metrics, t0 = 0, float("inf"), {}, time.time()
    while step < total:
        for batch in train_loader:
            model.train()
            with torch.autocast(device_type=device.type, enabled=use_amp):
                loss, metrics = loss_fn(model, batch, device)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.optim.grad_clip)
            scaler.step(opt)
            scaler.update()
            sched.step()
            step += 1
            metrics = dict(metrics, loss=float(loss.detach()))
            if step % cfg.log_every == 0:
                log.info("%s step %d loss %.4f lr %.2e (%.1f s)", cfg.name, step, metrics["loss"], sched.get_last_lr()[0], time.time() - t0)
            if val_loader is not None and (step % cfg.eval_every == 0 or step == total):
                val = evaluate(model, loss_fn, val_loader, device)
                log.info("%s step %d validation %s", cfg.name, step, val)
                if on_eval:
                    on_eval(step, val)
                if val["loss"] < best:
                    best = val["loss"]
                    save(model, os.path.join(cfg.checkpoint_dir, cfg.name + ".best.pt"), cfg, step, val)
            if step >= total:
                break
    save(model, os.path.join(cfg.checkpoint_dir, cfg.name + ".last.pt"), cfg, step, metrics)
    return metrics


@torch.no_grad()
def evaluate(model, loss_fn, loader, device):
    model.eval()
    tot, n, agg = 0.0, 0, {}
    for batch in loader:
        loss, m = loss_fn(model, batch, device)
        tot += float(loss); n += 1
        for k, v in m.items():
            agg[k] = agg.get(k, 0.0) + float(v)
    return dict({k: v / max(1, n) for k, v in agg.items()}, loss=tot / max(1, n))


def save(model, path, cfg, step, metrics):
    torch.save({"model": model.state_dict(), "config": cfg.__dict__ if not hasattr(cfg, "__dataclass_fields__") else None,
                "name": cfg.name, "step": step, "metrics": metrics}, path)
    return path


def load_weights(model, path, device="cpu"):
    state = torch.load(path, map_location=device)
    model.load_state_dict(state["model"])
    return state
