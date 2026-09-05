export const captionParts = (text: string): string[] => {
  const tokens = text.match(/[A-Za-z0-9][A-Za-z0-9._+:/-]*|[ァ-ヺー]+|[\s\S]/gu) ?? [];
  const parts: string[] = [];
  let current = '';
  for (const token of tokens) {
    if (current.length + token.length > 40 && current && !/^[、。！？!?）」』]/u.test(token)) {parts.push(current); current = '';}
    current += token;
  }
  if (current) parts.push(current);
  return parts;
};

export function soundVolume(sound: {from: number; to: number; volume?: number; fade_in?: number; fade_out?: number; duck?: boolean}, local: number, fps: number, lines: {from: number; to: number}[], mix: {duck_volume: number; duck_seconds: number}) {
  const time = sound.from + local;
  const fadeIn = sound.fade_in ? Math.min(1, local / (sound.fade_in * fps)) : 1;
  const fadeOut = sound.fade_out ? Math.min(1, (sound.to - time) / (sound.fade_out * fps)) : 1;
  let duck = 1;
  if (sound.duck) for (const line of lines) {
    const distance = time < line.from ? line.from - time : time >= line.to ? time - line.to : 0;
    const ramp = Math.max(0, 1 - distance / Math.max(1, mix.duck_seconds * fps));
    duck = Math.min(duck, 1 - ramp * (1 - mix.duck_volume));
  }
  return Math.max(0, (sound.volume ?? 1) * fadeIn * fadeOut * duck);
}
