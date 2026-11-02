// The goal horn (Settings > Display, off until someone turns it on, per device). Made here from two low notes, so there's no
// file to fetch and no league's recording in the app. Phones only let a page make sound after a tap: arm() waits for the
// next one.
const NOTES = [185, 233.08, 277.18];   // a low F-sharp chord, with a slow swell, like a ship's horn
const LENGTH = 2.4;
let audio = null;

const wake = () => {
  audio ||= new (window.AudioContext || window.webkitAudioContext)();
  if (audio.state === "suspended") audio.resume().catch(() => {});
};
export function arm() { addEventListener("pointerdown", wake, { once: true, passive: true }); }

export function play() {
  wake();
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
