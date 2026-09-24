import { bus } from './bus.js';

// The player's state machine: IDLE → LOADING → READY → PLAYING ⇄ PAUSED → ENDED, with
// ERROR reachable from anywhere. Illegal transitions are reported, never silently applied.
export const STATES = ['idle', 'loading', 'ready', 'playing', 'paused', 'buffering', 'ended', 'error'];
const ALLOWED = {
  idle: ['loading', 'error'],
  loading: ['ready', 'error', 'loading', 'idle'],
  ready: ['playing', 'paused', 'loading', 'error', 'ended'],
  playing: ['paused', 'buffering', 'ended', 'loading', 'error', 'playing'],
  paused: ['playing', 'loading', 'error', 'ended', 'paused'],
  buffering: ['playing', 'paused', 'loading', 'error', 'ended'],
  ended: ['loading', 'playing', 'paused', 'error', 'idle'],
  error: ['loading', 'idle'],
};

export class PlayerStateMachine {
  constructor(onChange) {
    this.state = 'idle';
    this.error = null;
    this.history = [];
    this.onChange = onChange;
  }

  can(next) { return (ALLOWED[this.state] || []).includes(next); }

  /** Moves to `next`; returns false (and reports) when the transition is not allowed. */
  go(next, error = null) {
    if (!STATES.includes(next)) return false;
    const legal = this.can(next);
    if (!legal) bus.emit('player:illegal', { from: this.state, to: next });
    const prev = this.state;
    this.state = next;
    this.error = next === 'error' ? error : null;
    this.history.push({ from: prev, to: next, at: Date.now(), legal });
    if (this.history.length > 50) this.history.shift();
    this.onChange?.(next, prev, error);
    bus.emit('player:state', { state: next, prev, error });
    return legal;
  }

  is(...states) { return states.includes(this.state); }
}
