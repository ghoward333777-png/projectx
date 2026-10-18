import numpy as np
import torch

from vse.visual.camera import background_motion, intrinsics
from vse.visual.identity import IdentityEncoder
from vse.visual.lighting import LightingEstimator, fit_sh, shade
from vse.visual.mesh import FaceFitter3D, MorphableModel, project


def test_sh_recovers_light():
    g = np.random.default_rng(1)
    n = g.normal(size=(500, 3)); n /= np.linalg.norm(n, axis=1, keepdims=True)
    true = g.normal(size=(9, 3))
    est = fit_sh(n, shade(n, true), ridge=1e-6)
    assert np.allclose(est, true, atol=1e-3)


def test_morphable_fit_reduces_error():
    torch.manual_seed(0)
    m = MorphableModel.random(seed=2)
    shape = torch.randn(10) * 0.5
    expr = torch.randn(4, 8) * 0.5
    pose = torch.zeros(4, 6); pose[:, 2] = 0.1
    target = project(m, shape, expr, pose).detach().numpy()
    # clean synthetic landmarks: light regularization lets the fit recover the face almost exactly
    fitter = FaceFitter3D(m, iters=600, lr=0.05, w_shape=1e-6, w_expr=1e-6, w_smooth=1e-6)
    meshes, err = fitter.fit(target)
    assert len(meshes) == 4 and err < 0.02 * fitter.initial_error, (err, fitter.initial_error)


def test_camera_helpers():
    cam = intrinsics(1920, 1080)
    assert 1300 < cam.fx < 1400 and cam.cx == 960
    a = np.random.default_rng(0).random((64, 64))
    b = np.roll(np.roll(a, 3, axis=1), -2, axis=0)
    dx, dy = background_motion(a, b)
    assert (dx, dy) == (-3, 2)


def test_identity_and_lighting_shapes():
    e = IdentityEncoder(64, width=8)
    assert e(torch.rand(2, 3, 64, 64)).shape == (2, 64)
    assert LightingEstimator(8)(torch.rand(2, 3, 64, 64)).shape == (2, 27)
