import { bus } from './bus.js';

// The stage owns the box the picture lives in, the content rect (where the picture
// actually is inside that box) and full screen. Full screen is always requested on
// the stage element so the overlay and controls stay inside the fullscreen subtree.
export class Stage {
  constructor(root) {
    this.root = root;
    this.picture = root.querySelector('.stage__picture');
    this.overlay = root.querySelector('.stage__overlay');
    this.controls = root.querySelector('.stage__controls');
    this.cards = root.querySelector('.stage__cards');
    this.pictureSizeValue = null;
    this.rect = null;

    this._onFullscreenChange = () => this._syncFullscreen();
    document.addEventListener('fullscreenchange', this._onFullscreenChange);
    document.addEventListener('webkitfullscreenchange', this._onFullscreenChange);
    window.addEventListener('resize', () => this.layout());
    window.addEventListener('orientationchange', () => this.layout());
    if (typeof ResizeObserver !== 'undefined') {
      this._ro = new ResizeObserver(() => this.layout());
      this._ro.observe(root);
    }
    this.layout();
  }

  /** Natural picture size from the adapter; null means "assume 16:9". */
  setPictureSize(size) {
    this.pictureSizeValue = size && size.width > 0 && size.height > 0 ? { ...size } : null;
    this.layout();
  }

  /** Recompute the content rect and publish it as CSS custom properties. */
  layout() {
    const stageWidth = this.root.clientWidth;
    const stageHeight = this.root.clientHeight;
    if (stageWidth === 0 || stageHeight === 0) return;
    const pic = this.pictureSizeValue ?? { width: 16, height: 9 };
    const scale = Math.min(stageWidth / pic.width, stageHeight / pic.height);
    const width = pic.width * scale;
    const height = pic.height * scale;
    const x = (stageWidth - width) / 2;
    const y = (stageHeight - height) / 2;
    this.rect = {
      x, y, width, height, stageWidth, stageHeight,
      source: this.pictureSizeValue ? 'media' : 'fallback',
    };
    const style = this.root.style;
    style.setProperty('--content-x', `${x}px`);
    style.setProperty('--content-y', `${y}px`);
    style.setProperty('--content-w', `${width}px`);
    style.setProperty('--content-h', `${height}px`);
    bus.emit('stage:layout', this.rect);
  }

  contentRect() { return this.rect; }

  isFullscreen() {
    const el = document.fullscreenElement || document.webkitFullscreenElement || null;
    return el === this.root || this.root.classList.contains('is-fake-fullscreen');
  }

  async toggleFullscreen() {
    if (this.isFullscreen()) await this.exitFullscreen();
    else await this.enterFullscreen();
  }

  async enterFullscreen() {
    const request = this.root.requestFullscreen || this.root.webkitRequestFullscreen;
    if (request) {
      try {
        await request.call(this.root, { navigationUI: 'hide' });
        return;
      } catch (_err) {
        // iOS Safari and a few embedded browsers: fall through to the fixed-position fallback.
      }
    }
    this.root.classList.add('is-fake-fullscreen');
    this._syncFullscreen();
  }

  async exitFullscreen() {
    if (this.root.classList.contains('is-fake-fullscreen')) {
      this.root.classList.remove('is-fake-fullscreen');
      this._syncFullscreen();
      return;
    }
    const exit = document.exitFullscreen || document.webkitExitFullscreen;
    if (exit && (document.fullscreenElement || document.webkitFullscreenElement)) {
      try { await exit.call(document); } catch (_err) { /* already out */ }
    }
  }

  _syncFullscreen() {
    const on = this.isFullscreen();
    this.root.classList.toggle('is-fullscreen', on);
    this.layout();
    bus.emit('stage:fullscreen', on);
  }
}
