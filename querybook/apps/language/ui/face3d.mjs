// 3D talking head (three.js, bundled) with an "Enter VR" button for WebXR headsets.
import * as THREE from "./vendor/three/three.module.min.js";
import { VRButton } from "./vendor/three/VRButton.js";

export class Face3D {
  constructor(el) {
    this.el = el;
    el.innerHTML = "";
    const w = el.clientWidth || 360, h = Math.round(w * 1.05);
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    this.renderer.setSize(w, h);
    this.renderer.xr.enabled = true;
    el.appendChild(this.renderer.domElement);
    const vr = VRButton.createButton(this.renderer);
    vr.style.position = "relative"; vr.style.left = "auto"; vr.style.bottom = "auto"; vr.style.marginTop = "6px";
    el.appendChild(vr);
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(32, w / h, 0.05, 50);
    this.camera.position.set(0, 1.6, -0.3);              // desktop view: 0.5 m from the face (VR uses the headset instead)
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x664433, 1.1));
    const key = new THREE.DirectionalLight(0xffffff, 1.4); key.position.set(0.6, 2.2, 1.5); this.scene.add(key);
    const head = this.head = new THREE.Group();
    head.position.set(0, 1.6, -0.8);                   // eye height, 0.8 m in front of a VR viewer standing at the origin
    this.scene.add(head);
    const skin = new THREE.MeshStandardMaterial({ color: 0xe9b796, roughness: 0.7 });
    const skull = new THREE.Mesh(new THREE.SphereGeometry(0.1, 48, 36), skin); skull.scale.set(0.82, 1.08, 0.9); head.add(skull);
    const hair = new THREE.Mesh(new THREE.SphereGeometry(0.103, 48, 24, 0, Math.PI * 2, 0, Math.PI * 0.34),
      new THREE.MeshStandardMaterial({ color: 0x4a3122, roughness: 0.9 })); hair.scale.set(0.84, 1.1, 0.93); hair.position.y = 0.006; head.add(hair);
    const white = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.3 }), iris = new THREE.MeshStandardMaterial({ color: 0x3b2a1f });
    this.lids = [];
    [-0.032, 0.032].forEach(x => {
      const e = new THREE.Mesh(new THREE.SphereGeometry(0.012, 24, 16), white); e.position.set(x, 0.022, 0.078); head.add(e);
      const i = new THREE.Mesh(new THREE.SphereGeometry(0.006, 16, 12), iris); i.position.set(x, 0.022, 0.089); head.add(i);
      const lid = new THREE.Mesh(new THREE.SphereGeometry(0.0128, 24, 16, 0, Math.PI * 2, 0, Math.PI / 2), skin); lid.position.copy(e.position); lid.scale.y = 0.05; head.add(lid);
      this.lids.push(lid);
      const brow = new THREE.Mesh(new THREE.CapsuleGeometry(0.0025, 0.02, 4, 8), new THREE.MeshStandardMaterial({ color: 0x4a3122 }));
      brow.rotation.z = Math.PI / 2 + (x < 0 ? 0.12 : -0.12); brow.position.set(x, 0.042, 0.083); head.add(brow);
    });
    const nose = new THREE.Mesh(new THREE.ConeGeometry(0.011, 0.034, 16), skin); nose.rotation.x = Math.PI / 2.4; nose.position.set(0, -0.005, 0.094); head.add(nose);
    this.cavity = new THREE.Mesh(new THREE.CircleGeometry(1, 32), new THREE.MeshBasicMaterial({ color: 0x4a1515 }));
    this.cavity.position.set(0, -0.048, 0.0835); head.add(this.cavity);
    this.teeth = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 0.002), new THREE.MeshStandardMaterial({ color: 0xfafaf2 })); head.add(this.teeth);
    this.tongue = new THREE.Mesh(new THREE.SphereGeometry(1, 16, 12), new THREE.MeshStandardMaterial({ color: 0xc85d63 })); head.add(this.tongue);
    this.lipMat = new THREE.MeshStandardMaterial({ color: 0xb0545a, roughness: 0.5 });
    this.upper = null; this.lower = null;
    this.jaw = new THREE.Group(); head.add(this.jaw);
    const chin = new THREE.Mesh(new THREE.SphereGeometry(0.03, 24, 16), skin); chin.scale.set(1.1, 0.6, 0.7); chin.position.set(0, -0.08, 0.045); this.jaw.add(chin);
    this.drag = null; this.rot = { x: 0, y: 0 };
    const c = this.renderer.domElement;
    c.addEventListener("pointerdown", e => { this.drag = [e.clientX, e.clientY, this.rot.x, this.rot.y]; c.setPointerCapture(e.pointerId); });
    c.addEventListener("pointermove", e => { if (this.drag) { this.rot.y = this.drag[3] + (e.clientX - this.drag[0]) / 150; this.rot.x = this.drag[2] + (e.clientY - this.drag[1]) / 250; } });
    c.addEventListener("pointerup", () => { this.drag = null; });
    this.m = null;
    this.renderer.setAnimationLoop(() => { if (this.m) this._apply(this.m, performance.now() / 1000); this.renderer.render(this.scene, this.camera); });
    this.blinkAt = 1.5;
  }
  _lip(points) {
    const curve = new THREE.CatmullRomCurve3(points.map(p => new THREE.Vector3(p[0], p[1], p[2])));
    return new THREE.TubeGeometry(curve, 28, 0.0042, 8, false);
  }
  _apply(m, t) {
    const W = 0.022 + 0.022 * m.width * (1 - 0.35 * m.round), H = 0.002 + 0.024 * m.open, R = m.round, y0 = -0.048, z = 0.086 + 0.006 * R;
    const top = y0 + H * 0.35, bot = y0 - H * 0.65, lift = R * H * 0.25;
    const up = [[-W, y0, z - 0.006], [-W * 0.5, top + lift, z], [0, top + 0.001, z + 0.001], [W * 0.5, top + lift, z], [W, y0, z - 0.006]];
    const lo = [[-W, y0, z - 0.006], [-W * 0.5, bot - lift, z], [0, bot - 0.001, z + 0.001], [W * 0.5, bot - lift, z], [W, y0, z - 0.006]];
    [["upper", up], ["lower", lo]].forEach(([k, pts]) => {
      if (this[k]) { this.head.remove(this[k]); this[k].geometry.dispose(); }
      this[k] = new THREE.Mesh(this._lip(pts), this.lipMat); this.head.add(this[k]);
    });
    this.cavity.scale.set(W * 0.95, Math.max(0.0005, H * 0.5), 1); this.cavity.position.y = y0 - H * 0.15;
    this.teeth.scale.set(W * 1.4, Math.min(H * 0.35, 0.006) * m.teeth + 0.0001, 1); this.teeth.position.set(0, top - Math.min(H * 0.35, 0.006) * m.teeth / 2, 0.0838);
    this.tongue.scale.set(W * 0.6, Math.max(0.0003, H * 0.22 * (0.5 + m.tongue)), 0.008); this.tongue.position.set(0, bot + H * 0.2 + 0.004 * m.tongue, 0.08);
    this.jaw.position.y = -H * 0.55;
    const blink = Math.max(0, 1 - Math.abs(t - this.blinkAt) / 0.08);
    if (t > this.blinkAt + 0.2) this.blinkAt = t + 2.5 + ((t * 7.3) % 2);
    this.lids.forEach(l => { l.scale.y = 0.05 + 0.95 * blink; });
    this.head.rotation.set(this.rot.x + Math.sin(t * 0.7) * 0.02, this.rot.y + Math.sin(t * 0.43) * 0.04, 0);
  }
  draw(m) { this.m = m; }
  dispose() { this.renderer.setAnimationLoop(null); this.renderer.dispose(); this.el.innerHTML = ""; }
}
