"""VeriWave Create: Audio. Music, sound effects and speech from a prompt, as WAV (16-bit mono, 22,050 Hz).

Local engine:
* music: a melody and bass line in a key, scale and tempo chosen from the prompt's mood words, seeded from the prompt;
* sound effects: rain, ocean waves, wind, an alarm or a beep, from shaped noise and tones;
* speech: the words to say, spoken by espeak-ng (the speech engine QueryBook already uses) when it is installed.
Pitch arithmetic is integer (milli-hertz from a fixed table); every sample is clamped to the 16-bit range.

Lean:
    def RATE : Nat := 22050
    def I16_MIN : Int := -32768
    def I16_MAX : Int := 32767
"""
from __future__ import annotations

import io
import math
import struct
import wave

from . import core

RATE = 22050
# equal-tempered pitches of octave 4 (C4 .. B4) in milli-hertz, A4 = 440 Hz
OCTAVE4_MHZ = [261626, 277183, 293665, 311127, 329628, 349228, 369994, 391995, 415305, 440000, 466164, 493883]
SCALES: dict[str, list[int]] = {"major": [0, 2, 4, 5, 7, 9, 11], "minor": [0, 2, 3, 5, 7, 8, 10], "pentatonic": [0, 2, 4, 7, 9]}
EFFECTS = ["rain", "ocean", "wind", "alarm", "beep"]


def kind_of(prompt: str) -> str:
    """speech, an effect name, or music

    Lean:
        def kindOf (p : String) : String :=
          let ws := words p
          if hasAny ws ["say", "speak", "read aloud", "narrate", "pronounce", "voice saying"] then "speech"
          else if hasAny ws ["rain", "raining", "rainfall"] then "rain"
          else if hasAny ws ["ocean", "waves", "sea", "surf"] then "ocean"
          else if hasAny ws ["wind", "windy", "breeze", "storm"] then "wind"
          else if hasAny ws ["alarm", "siren"] then "alarm"
          else if hasAny ws ["beep", "notification", "ding", "chime"] then "beep"
          else "music"
        #guard kindOf "say hello world" == "speech"                       -- py: kind_of("say hello world") == "speech"
        #guard kindOf "ocean waves at night" == "ocean"                   -- py: kind_of("ocean waves at night") == "ocean"
        #guard kindOf "a calm piano melody" == "music"                    -- py: kind_of("a calm piano melody") == "music"
    """
    ws = core.words(prompt)
    if core.has_any(ws, ["say", "speak", "read aloud", "narrate", "pronounce", "voice saying"]):
        return "speech"
    if core.has_any(ws, ["rain", "raining", "rainfall"]):
        return "rain"
    if core.has_any(ws, ["ocean", "waves", "sea", "surf"]):
        return "ocean"
    if core.has_any(ws, ["wind", "windy", "breeze", "storm"]):
        return "wind"
    if core.has_any(ws, ["alarm", "siren"]):
        return "alarm"
    if core.has_any(ws, ["beep", "notification", "ding", "chime"]):
        return "beep"
    return "music"


def mood(prompt: str) -> tuple[str, int, int]:
    """(scale, tempo in beats per minute, key as a semitone above C) from the prompt's mood words

    Lean:
        def moodScale (ws : List String) : String :=
          if hasAny ws ["sad", "dark", "melancholy", "mysterious", "spooky", "minor", "lonely", "rainy"] then "minor"
          else if hasAny ws ["calm", "peaceful", "relaxing", "gentle", "sleep", "meditation", "lullaby", "ambient"] then "pentatonic"
          else "major"
        def moodTempo (ws : List String) : Nat :=
          if hasAny ws ["fast", "upbeat", "energetic", "dance", "exciting", "happy"] then 128
          else if hasAny ws ["slow", "calm", "peaceful", "relaxing", "sleep", "lullaby", "sad", "gentle"] then 72
          else 96
        theorem moodTempo_range (ws : List String) : 72 ≤ moodTempo ws ∧ moodTempo ws ≤ 128 := by
          unfold moodTempo; split <;> (try split) <;> omega
        #guard moodScale (words "a sad song") == "minor" && moodTempo (words "a sad song") == 72   -- py: mood("a sad song")[:2] == ("minor", 72)
        #guard moodScale (words "an upbeat jingle") == "major" && moodTempo (words "an upbeat jingle") == 128   -- py: mood("an upbeat jingle")[:2] == ("major", 128)
    """
    ws = core.words(prompt)
    if core.has_any(ws, ["sad", "dark", "melancholy", "mysterious", "spooky", "minor", "lonely", "rainy"]):
        scale = "minor"
    elif core.has_any(ws, ["calm", "peaceful", "relaxing", "gentle", "sleep", "meditation", "lullaby", "ambient"]):
        scale = "pentatonic"
    else:
        scale = "major"
    if core.has_any(ws, ["fast", "upbeat", "energetic", "dance", "exciting", "happy"]):
        tempo = 128
    elif core.has_any(ws, ["slow", "calm", "peaceful", "relaxing", "sleep", "lullaby", "sad", "gentle"]):
        tempo = 72
    else:
        tempo = 96
    return scale, tempo, core.seed_of(prompt) % 12


def freq_mhz(midi: int) -> int:
    """a MIDI note's pitch in milli-hertz: the octave-4 table, doubled or halved per octave (integer arithmetic)

    Lean:
        def octave4 : List Nat := [261626, 277183, 293665, 311127, 329628, 349228, 369994, 391995, 415305, 440000, 466164, 493883]
        def freqMhz (midi : Nat) : Nat :=
          let base := octave4.getD (midi % 12) 0
          let oct := midi / 12
          if oct ≥ 5 then base * 2 ^ (oct - 5) else base / 2 ^ (5 - oct)
        #guard freqMhz 69 == 440000                                       -- py: freq_mhz(69) == 440000
        #guard freqMhz 57 == 220000                                       -- py: freq_mhz(57) == 220000
        #guard freqMhz 81 == 880000                                       -- py: freq_mhz(81) == 880000
    """
    base = OCTAVE4_MHZ[midi % 12]
    octv = midi // 12
    if octv >= 5:
        return base * 2 ** (octv - 5)
    return base // 2 ** (5 - octv)


def to_i16(x: float) -> int:
    """a sample in [-1, 1] as a 16-bit integer, clamped

    Lean:
        def toI16 (scaled : Int) : Int := clamp I16_MIN I16_MAX scaled
        theorem toI16_range (s : Int) : I16_MIN ≤ toI16 s ∧ toI16 s ≤ I16_MAX := clamp_in _ _ _ (by decide)
        #guard toI16 99999 == 32767                                       -- py: to_i16(3.0) == 32767
        #guard toI16 (-99999) == -32768                                   -- py: to_i16(-3.0) == -32768
    """
    return core.clamp(-32768, 32767, int(round(x * 32767)))


def melody(prompt: str, bars: int) -> list[tuple[int, int]]:
    """the tune: (MIDI note, length in eighth notes), a stepwise walk on the scale, ending on the home note

    Lean:
        def degreeStep (pos : Int) (step : Int) (n : Nat) : Int := clamp 0 ((2 * n : Nat) - 1 : Int) (pos + step)
        theorem degreeStep_ge (p s : Int) (n : Nat) (h : 1 ≤ n) : 0 ≤ degreeStep p s n :=
          (clamp_in 0 _ _ (by omega)).1
        def eighthsPerBar : Nat := 8
        #guard eighthsPerBar * 8 == 64                                     -- py: sum(d for _, d in melody("a song", 8)) == 64
    """
    scale, _, key = mood(prompt)
    steps = SCALES[scale]
    rng = core.Rng(core.seed_of(prompt + "|melody"))
    n = len(steps)
    pos = n
    out: list[tuple[int, int]] = []
    total = bars * 8
    used = 0
    while used < total:
        left = total - used
        dur = min(left, int(rng.pick(["1", "2", "2", "4"])))
        if left <= 4:
            dur = left
            pos = n
        pos = core.clamp(0, 2 * n - 1, pos + rng.between(-2, 2))
        out.append((60 + key + 12 * (pos // n) + steps[pos % n] - 12, dur))
        used += dur
    return out


def tone(samples: list[float], start: int, length: int, freq: float, amp: float, shape: str) -> None:
    """adds one note to the sample buffer with a short attack and a release (sine, or a softer two-partial 'warm' tone)

    Lean:
        def toneEnd (start length total : Nat) : Nat := min (start + length) total
        theorem toneEnd_le (s l t : Nat) : toneEnd s l t ≤ t := Nat.min_le_right _ _
        #guard toneEnd 10 100 50 == 50                                     -- py: tone([0.0] * 50, 10, 100, 440.0, 0.5, "sine") is None
    """
    end = min(start + length, len(samples))
    att = max(1, min(400, length // 8))
    rel = max(1, min(4000, length // 3))
    w = 2 * math.pi * freq / RATE
    for i in range(start, end):
        k = i - start
        env = min(1.0, k / att) * min(1.0, (length - k) / rel)
        v = math.sin(w * k)
        if shape == "warm":
            v = 0.7 * v + 0.3 * math.sin(2 * w * k)
        samples[i] += amp * env * v


def music(prompt: str) -> tuple[list[float], dict]:
    """eight bars: the melody over a bass line on the scale's home chord changes

    Lean:
        def samplesFor (eighths tempo : Nat) : Nat := eighths * (RATE * 60 / tempo / 2)
        #guard samplesFor 64 96 == 64 * 6890                               -- py: len(music("a song")[0]) == 64 * 6890
    """
    scale, tempo, key = mood(prompt)
    eighth = RATE * 60 // tempo // 2
    notes = melody(prompt, 8)
    total = sum(d for _, d in notes) * eighth
    samples = [0.0] * total
    t = 0
    for midi, d in notes:
        tone(samples, t, d * eighth, freq_mhz(midi) / 1000.0, 0.32, "warm")
        t += d * eighth
    prog = [0, 7, 9, 5] if scale != "minor" else [0, 8, 3, 10]
    for bar in range(8):
        root = 36 + key + prog[bar % 4]
        tone(samples, bar * 8 * eighth, 8 * eighth, freq_mhz(root) / 1000.0, 0.22, "sine")
        tone(samples, bar * 8 * eighth, 8 * eighth, freq_mhz(root + 7) / 1000.0, 0.10, "sine")
    return samples, {"scale": scale, "tempo": tempo, "key": ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"][key],
                     "notes": len(notes), "bars": 8}


def noise(rng: core.Rng) -> float:
    """one white-noise value in [-1, 1) from the deterministic stream

    Lean:
        def noiseInt (v : Nat) : Int := (v % 65536 : Nat) - 32768
        theorem noiseInt_range (v : Nat) : -32768 ≤ noiseInt v ∧ noiseInt v < 32768 := by
          unfold noiseInt; have := Nat.mod_lt v (show 65536 > 0 by decide); omega
        #guard noiseInt 0 == -32768                                         -- py: -1.0 <= noise(core.Rng(1)) < 1.0
    """
    return ((rng.next() % 65536) - 32768) / 32768.0


def effect(name: str, prompt: str, seconds: int) -> list[float]:
    """a sound effect: rain (filtered noise with drops), ocean (noise swelling every few seconds), wind, alarm, beep

    Lean:
        def effectSeconds (name : String) (asked : Nat) : Nat :=
          if name == "beep" then 1 else if name == "alarm" then min 4 (max 1 asked) else min 30 (max 3 asked)
        theorem effectSeconds_le (n : String) (a : Nat) : effectSeconds n a ≤ 30 := by
          unfold effectSeconds; split <;> (try split) <;> omega
        #guard effectSeconds "rain" 100 == 30                              -- py: len(effect("rain", "rain", 100)) == 30 * RATE
    """
    secs = 1 if name == "beep" else min(4, max(1, seconds)) if name == "alarm" else min(30, max(3, seconds))
    n = secs * RATE
    rng = core.Rng(core.seed_of(prompt + "|" + name))
    out = [0.0] * n
    if name in ("beep", "alarm"):
        for i in range(n):
            t = i / RATE
            if name == "beep":
                out[i] = 0.5 * math.sin(2 * math.pi * 880 * t) * min(1.0, (n - i) / 2000)
            else:
                f = 700 if int(t * 4) % 2 == 0 else 950
                out[i] = 0.45 * math.sin(2 * math.pi * f * t)
        return out
    low = 0.0
    for i in range(n):
        x = noise(rng)
        if name == "rain":
            low = low + 0.35 * (x - low)
            v = 0.5 * low
            if rng.below(2600) == 0:
                for k in range(min(300, n - i)):
                    out[i + k] += 0.5 * math.exp(-k / 40.0) * math.sin(k * 0.9)
        elif name == "ocean":
            low = low + 0.05 * (x - low)
            swell = 0.55 + 0.45 * math.sin(2 * math.pi * i / (RATE * 6.0))
            v = 1.6 * low * swell
        else:
            low = low + 0.02 * (x - low)
            v = 2.2 * low * (0.6 + 0.4 * math.sin(2 * math.pi * i / (RATE * 3.7)))
        out[i] += v
    fade = min(RATE, n // 4)
    for i in range(fade):
        out[i] *= i / fade
        out[n - 1 - i] *= i / fade
    return out


def seconds_in(prompt: str) -> int:
    """a length the prompt names ('20 seconds', '1 minute'), else 12 seconds

    Lean:
        def secondsIn : List String → Nat
          | a :: rest@(b :: _) =>
            if a.all Char.isDigit && !a.isEmpty && ["second", "seconds", "sec", "secs", "s"].contains b then a.toNat!
            else if a.all Char.isDigit && !a.isEmpty && ["minute", "minutes", "min"].contains b then a.toNat! * 60
            else secondsIn rest
          | _ => 12
        #guard secondsIn (words "20 seconds of rain") == 20                -- py: seconds_in("20 seconds of rain") == 20
        #guard secondsIn (words "rain") == 12                              -- py: seconds_in("rain") == 12
    """
    ws = core.words(prompt)
    for i in range(len(ws) - 1):
        if ws[i].isdigit() and ws[i].isascii():
            if ws[i + 1] in ("second", "seconds", "sec", "secs", "s"):
                return int(ws[i])
            if ws[i + 1] in ("minute", "minutes", "min"):
                return int(ws[i]) * 60
    return 12


def speech_text(prompt: str) -> str:
    """what to say: the quoted words if any, else everything after 'say', 'speak', 'read aloud' or 'narrate'

    Lean:
        def quoted (s : String) : Option String :=
          match s.splitOn "\"" with
          | _ :: q :: _ :: _ => if q.trim.isEmpty then none else some q.trim
          | _ => none
        #guard quoted "say \"good morning\" please" == some "good morning"   -- py: speech_text('say "good morning" please') == "good morning"
    """
    parts = prompt.split('"')
    if len(parts) >= 3 and parts[1].strip():
        return parts[1].strip()
    low = core.lower(prompt)
    for lead in ("read aloud ", "narrate ", "speak ", "say "):
        i = low.find(lead)
        if i >= 0:
            return prompt[i + len(lead):].strip().strip(":").strip()
    return prompt.strip()


def to_wav(samples: list[float]) -> bytes:
    """16-bit mono PCM WAV bytes, peak-normalised to 0.9 when louder than that

    Lean:
        def wavBytes (nSamples : Nat) : Nat := 44 + 2 * nSamples
        #guard wavBytes 100 == 244                                          -- py: len(to_wav([0.0] * 100)) == 244
    """
    peak = max((abs(s) for s in samples), default=0.0)
    gain = 0.9 / peak if peak > 0.9 else 1.0
    buf = io.BytesIO()
    w = wave.open(buf, "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(RATE)
    w.writeframes(b"".join(struct.pack("<h", to_i16(s * gain)) for s in samples))
    w.close()
    return buf.getvalue()


def plan(prompt: str) -> dict:
    """what the local engine will make for this prompt (the speech itself is produced by the server, with espeak-ng)

    Lean:
        def planKind (k : String) : String := if k == "speech" then "speech" else if k == "music" then "music" else "effect"
        #guard planKind "rain" == "effect"                                  -- py: plan("rain on a tin roof")["kind"] == "effect"
    """
    k = kind_of(prompt)
    if k == "speech":
        return {"kind": "speech", "text": speech_text(prompt)}
    if k == "music":
        return {"kind": "music"}
    return {"kind": "effect", "effect": k, "seconds": seconds_in(prompt)}


def render(prompt: str) -> dict:
    """music or an effect as WAV bytes, with what was made

    Lean:
        def durationTenths (nSamples : Nat) : Nat := nSamples * 10 / RATE
        #guard durationTenths 22050 == 10                                    -- py: render("a beep")["seconds"] == 1.0
    """
    p = plan(prompt)
    if p["kind"] == "music":
        samples, info = music(prompt)
        info["kind"] = "music"
    elif p["kind"] == "effect":
        samples = effect(str(p["effect"]), prompt, int(p["seconds"]))
        info = {"kind": "effect", "effect": p["effect"]}
    else:
        raise ValueError("speech is made by the server")
    info["seconds"] = round(len(samples) / RATE, 1)
    info["wav"] = to_wav(samples)
    info["engine"] = "local"
    return info
