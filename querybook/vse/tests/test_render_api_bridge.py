import os

import numpy as np
import pytest
import torch

from conftest import APPS
from vse.render.compositor import FaceCompositor
from vse.render.diffusion_renderer import DDPM, ConditionalUNet
from vse.render.nerf_renderer import ConditionalFaceNeRF, NeRFFaceRenderer, render_rays


def test_compositor_keeps_outside_pixels():
    f = np.full((40, 40, 3), 100, np.uint8)
    r = np.full((40, 40, 3), 200, np.uint8)
    m = np.zeros((40, 40)); m[10:30, 10:30] = 1
    out = FaceCompositor(feather_px=2, colour_match=False).compose_one(f, r, m)
    assert out[0, 0, 0] == 100 and out[20, 20, 0] == 200


def test_nerf_renders():
    torch.manual_seed(0)
    m = ConditionalFaceNeRF(cond_dim=8, width=32, depth=2)
    rgb, depth, acc = render_rays(m, torch.zeros(5, 3), torch.tensor([[0.0, 0.0, -1.0]] * 5), torch.zeros(8), samples=8)
    assert rgb.shape == (5, 3) and (acc >= 0).all()
    img, a = NeRFFaceRenderer(m, focal=20.0, size=8).render(torch.eye(4)[:3], torch.zeros(8))
    assert img.shape == (8, 8, 3)


def test_diffusion_step_and_inpaint_keeps_known():
    torch.manual_seed(0)
    net = ConditionalUNet(base=8, cond_dim=4)
    d = DDPM(steps=20)
    x0 = torch.rand(1, 3, 16, 16) * 2 - 1
    loss = d.loss(net, x0, torch.zeros(1, 7, 16, 16), torch.zeros(1, 4))
    assert loss.item() > 0
    mask = torch.zeros(1, 1, 16, 16); mask[..., 4:12, 4:12] = 1
    out = d.inpaint(net, x0, mask, torch.zeros(1, 3, 16, 16), torch.zeros(1, 4), steps=5)
    assert torch.allclose(out[..., 0, 0], x0[..., 0, 0])


@pytest.mark.skipif(not os.path.isfile(os.path.join(APPS, "language", "vse.py")), reason="QueryBook apps not present")
def test_bridge_and_api_with_stage1():
    from fastapi.testclient import TestClient

    from vse.api.server import create_app
    from vse.bridge.querybook import frames_to_tensor, load_stage1
    s1 = load_stage1(APPS)
    rnd = s1._rng("t")
    spk = {"scale": 1.0, "offset": [0.0] * 13, "rate": 4.5, "noise": 0.01, "jitter": 0.0, "fps": 30}
    frames, _, _ = s1.synthetic_frames("please open the window", spk, rnd)
    assert frames_to_tensor(frames).shape[1] == 13
    client = TestClient(create_app(stage1=s1))
    j = client.post("/vse/lip_read", json={"frames": frames, "script": "please open the window"}).json()
    import time
    for _ in range(200):
        st = client.get("/vse/job/" + j["job_id"]).json()
        if st["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)
    assert st["status"] == "completed", st
    assert st["result"]["script"]["agreement"] > 40
