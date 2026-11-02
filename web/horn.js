// The goal horn (Settings > Display, off until someone turns it on, per device). Made here from three low notes, so there's no
// file to fetch and no league's recording in the app. Phones only let a page make sound after a tap: arm() waits for the
// next one, and a goal before that stays silent.
const NOTES = [185, 233.08, 277.18];   // a low F-sharp chord, with a slow swell, like a ship's horn
const LENGTH = 2.4;
const WAKE_MS = 300;
let audio = null;

const wake = () => {
  audio ||= new (window.AudioContext || window.webkitAudioContext)();
  if (audio.state === "suspended") audio.resume().catch(() => {});
};
export function arm() { addEventListener("pointerdown", wake, { once: true, passive: true }); }

export async function play() {
  wake();
  // Sound scheduled on a sleeping page would go off at the next tap, long after the goal.
  if (audio.state !== "running") await Promise.race([audio.resume(), new Promise(ok => setTimeout(ok, WAKE_MS))]);
  if (audio.state !== "running") return;
  const start = audio.currentTime + .02, level = audio.createGain(), soften = audio.createBiquadFilter();
  soften.type = "lowpass"; soften.frequency.value = 900;
  level.gain.setValueAtTime(.0001, start);
  level.gain.exponentialRampToValueAtTime(.16, start + .18);
  level.gain.setValueAtTime(.16, start + LENGTH - .5);
  level.gain.exponentialRampToValueAtTime(.0001, start + LENGTH);
  soften.connect(level).connect(audio.destination);
  for (const [i, hz] of NOTES.entries()) {
    const voice = audio.createOscillator();
    voice.type = "sawtooth"; voice.frequency.value = hz; voice.detune.value = i * 4 - 4;
    voice.connect(soften); voice.start(start); voice.stop(start + LENGTH);
  }
}
