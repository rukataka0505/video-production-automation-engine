const captionTokens = (text: string): string[] =>
  text.match(/[A-Za-z0-9][A-Za-z0-9._+:/-]*|[ァ-ヺー]+|[\s\S]/gu) ?? [];

export const captionParts = (text: string, maxChars = 42): string[] => {
  const limit = Math.max(1, Math.floor(maxChars));
  const tokens = captionTokens(text);
  const parts: string[] = [];
  let current = '';
  for (const token of tokens) {
    if (current.length + token.length > limit && current && !/^[、。！？!?）」』]/u.test(token)) {parts.push(current); current = '';}
    current += token;
  }
  if (current) parts.push(current);
  return parts;
};

export const captionLines = (text: string, maxCharsPerLine = 21): string => {
  const limit = Math.max(1, Math.floor(maxCharsPerLine));
  const tokens = captionTokens(text.replace(/\r\n/g, '\n'));
  const lines: string[] = [''];
  for (const token of tokens) {
    if (token === '\n') {lines.push(''); continue;}
    const current = lines[lines.length - 1];
    if (current.length + token.length > limit && current && !/^[、。！？!?）」』]/u.test(token)) lines.push(token);
    else lines[lines.length - 1] += token;
  }
  return lines.join('\n');
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
