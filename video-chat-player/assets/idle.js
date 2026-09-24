import { bus } from './bus.js';

// The one object that decides whether the overlay and control bar are visible.
// States: visible → (timeout) fading → (fadeMs) hidden; any activity reveals instantly.
// pinned: one or more reasons hold it open (composer focus, draft, hover, paused, modal,
// keyboard focus inside the stage). Nothing else touches the visibility classes.
export class IdleController {
  constructor(stage, options = {}) {
    this.stage = stage;
    this.root = stage.root;
    this.timeout = clamp(options.timeout ?? 3000, 1500, 10000);
    this.touchTimeout = options.touchTimeout ?? 5000;
    this.leaveTimeout = options.leaveTimeout ?? 1000;
    this.fadeMs = options.fadeMs ?? 220;
    this.state = 'visible';
    this.pins = new Set();
    this.touch = false;
    this.keyboardMode = false;
    this._timer = 0;
    this._fadeTimer = 0;

    const activity = () => this.activity();
    for (const type of ['pointermove', 'pointerdown', 'wheel']) {
      this.root.addEventListener(type, activity, { passive: true });
    }
    this.root.addEventListener('pointerdown', () => { this.keyboardMode = false; }, { passive: true });
    this.root.addEventListener('touchstart', () => { this.touch = true; this.activity(); }, { passive: true });
    document.addEventListener('keydown', (event) => {
      this.keyboardMode = true;
      if (!isTypingIn(event.target) || this.root.contains(event.target)) this.activity();
    });
    this.root.addEventListener('pointerleave', () => { if (!this.touch) this._arm(this.leaveTimeout); });
    this.root.addEventListener('pointerenter', activity);

    // Hovering the overlay or the control bar holds them open.
    for (const [el, reason] of [[stage.overlay, 'hover'], [stage.controls, 'hover-controls']]) {
      el.addEventListener('pointerenter', () => { if (!this.touch) this.pin(reason); });
      el.addEventListener('pointerleave', () => this.unpin(reason));
    }

    // Keyboard focus inside the stage never lands on an invisible control.
    this.root.addEventListener('focusin', (event) => {
      if (event.target !== this.root && this.keyboardMode) this.pin('focus');
    });
    this.root.addEventListener('focusout', (event) => {
      if (!event.relatedTarget || !this.root.contains(event.relatedTarget)) this.unpin('focus');
    });

    this.activity();
  }

  /** Any user activity: reveal instantly and restart the idle timer. */
  activity() {
    if (this.state === 'hidden' || this.state === 'fading') this._reveal();
    this._arm(this.touch ? this.touchTimeout : this.timeout);
  }

  /** Touch devices: a tap toggles instead of hovering. */
  toggle() {
    if (this.state === 'hidden' || this.state === 'fading') this.activity();
    else this.hideNow();
  }

  hideNow() {
    clearTimeout(this._timer);
    this._hide();
  }

  pin(reason) {
    this.pins.add(reason);
    clearTimeout(this._timer);
    if (this.state !== 'pinned') {
      if (this.state === 'hidden' || this.state === 'fading') this._reveal();
      this._set('pinned');
    }
  }

  unpin(reason) {
    if (!this.pins.delete(reason)) return;
    if (this.pins.size === 0 && this.state === 'pinned') {
      this._set('visible');
      this._arm(this.touch ? this.touchTimeout : this.timeout);
    }
  }

  isPinned(reason) { return reason ? this.pins.has(reason) : this.pins.size > 0; }
  get visible() { return this.state !== 'hidden'; }

  _arm(ms) {
    clearTimeout(this._timer);
    if (this.pins.size > 0) return;
    this._timer = setTimeout(() => this._hide(), ms);
  }

  _hide() {
    if (this.pins.size > 0 || this.state === 'hidden' || this.state === 'fading') return;
    this.root.classList.add('is-fading');
    this._set('fading');
    this._fadeTimer = setTimeout(() => {
      this.root.classList.remove('is-fading');
      this.root.classList.add('is-idle');
      this._set('hidden');
    }, this.fadeMs);
  }

  _reveal() {
    clearTimeout(this._fadeTimer);
    this.root.classList.remove('is-idle', 'is-fading');
    this._set(this.pins.size > 0 ? 'pinned' : 'visible');
  }

  _set(state) {
    if (this.state === state) return;
    this.state = state;
    bus.emit('idle:state', state);
  }
}

function clamp(n, lo, hi) { return Math.min(hi, Math.max(lo, Number(n) || lo)); }

export function isTypingIn(target) {
  if (!target || !target.tagName) return false;
  const tag = target.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable === true;
}
