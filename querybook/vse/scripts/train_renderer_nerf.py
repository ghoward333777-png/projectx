"""Conditional face NeRF, per identity. Manifest rows: {"image": "x.npy" [H,W,3], "c2w": [[3x4]], "focal": f, "cond": [C]}.
Each step samples random rays from one frame (photometric L2)."""
import numpy as np
import torch
from _common import args

from vse.common.data import read_manifest
from vse.common.train import save
from vse.render.nerf_renderer import ConditionalFaceNeRF, camera_rays, render_rays

a, cfg = args({"--rays": dict(type=int, default=1024)})
rows = read_manifest(cfg.data.train_manifest)
cond_dim = len(rows[0]["cond"])
model = ConditionalFaceNeRF(cond_dim, width=max(32, cfg.model.dim // 2))
opt = torch.optim.Adam(model.parameters(), cfg.optim.lr)
g = torch.Generator().manual_seed(cfg.seed)
for step in range(a.steps or cfg.optim.max_steps):
    r = rows[int(torch.randint(len(rows), (1,), generator=g))]
    img = torch.from_numpy(np.load(r["image"])).float() / 255.0
    h, w = img.shape[:2]
    o, d = camera_rays(h, w, r["focal"], torch.tensor(r["c2w"], dtype=torch.float32))
    pick = torch.randint(o.size(0), (a.rays,), generator=g)
    rgb, _, _ = render_rays(model, o[pick], d[pick], torch.tensor(r["cond"], dtype=torch.float32), perturb=True)
    loss = ((rgb - img.view(-1, 3)[pick]) ** 2).mean()
    opt.zero_grad(); loss.backward(); opt.step()
    if step % cfg.log_every == 0:
        print("step", step, "loss", float(loss))
cfg.name = "renderer_nerf"
save(model, cfg.checkpoint_dir + "/renderer_nerf.last.pt", cfg, step, {"loss": float(loss)})
