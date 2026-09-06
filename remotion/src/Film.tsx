import React from 'react';
import {AbsoluteFill, Audio, Img, OffthreadVideo, Sequence, useCurrentFrame, useVideoConfig} from 'remotion';
import {Subtitle, type SubtitleConfig} from './Subtitle';
import {captionLines, captionParts, soundVolume} from './timing';

type Event = {from: number; to: number; kind: string; [key: string]: any};
export type Line = {id: string; beat: string; text: string; from: number; to: number; path: string; character: string | null; duration: number; mouth: {start: number; end: number; state: string}[]};
export type FilmProps = {
  title: string; video: {width: number; height: number; fps: number}; durationInFrames: number;
  lines: Line[]; beats: {id: string; from: number; to: number; visuals: Event[]}[];
  audio: Event[]; characters: any; subtitles: SubtitleConfig; mix: {duck_volume: number; duck_seconds: number}; assetBase: string;
};
const asset = (base: string, path: string) => `${base}/project/${path.split('/').map(encodeURIComponent).join('/')}`;
const fullFrame: React.CSSProperties = {position: 'absolute', inset: 0};

const Visual: React.FC<{event: Event; base: string; fps: number}> = ({event: e, base, fps}) => {
  return <div style={fullFrame}>{e.media === 'video'
    ? <Sequence from={e.from} durationInFrames={e.to - e.from} layout="none"><OffthreadVideo src={asset(base, e.path)} startFrom={Math.round((e.source_start ?? 0) * fps)} muted style={{width: '100%', height: '100%', objectFit: e.fit ?? 'cover'}} /></Sequence>
    : <Img src={asset(base, e.path)} style={{width: '100%', height: '100%', objectFit: e.fit ?? 'cover'}} />}</div>;
};

const Character: React.FC<{line: Line; config: any; base: string; frame: number; fps: number}> = ({line, config, base, frame, fps}) => {
  const voice = config.voices[line.character!];
  const seconds = (frame - line.from) / fps;
  const index = line.mouth.findIndex(m => seconds >= m.start && seconds < m.end);
  const mouth = line.mouth[index];
  const previous = line.mouth[index - 1];
  const alpha = mouth && previous ? Math.min(1, (seconds - mouth.start) / config.mouth_transition_seconds) : 1;
  const url = (state: string) => `${base}/shared/${voice[state].split('/').map(encodeURIComponent).join('/')}`;
  const css: React.CSSProperties = {position: 'absolute', height: `${config.height_percent}%`, bottom: `${config.bottom_percent}%`, [voice.side]: `${voice.margin_x_percent}%`};
  return <>{previous && alpha < 1 && <Img src={url(previous.state)} style={css} />}<Img src={url(mouth?.state ?? 'closed')} style={{...css, opacity: alpha}} /></>;
};

export const Film: React.FC<FilmProps> = (props) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const portrait = height > width;
  const beat = props.beats.find(x => frame >= x.from && frame < x.to);
  const active = props.lines.find(x => frame >= x.from && frame < x.to);
  const pageChars = props.subtitles.max_chars_per_line * props.subtitles.max_lines;
  const parts = active ? captionParts(active.text, pageChars) : [];
  const fraction = active ? (frame - active.from) / Math.max(1, active.to - active.from) : 0;
  let cumulative = 0;
  const captionPart = parts.find(x => {cumulative += x.length; return fraction < cumulative / active!.text.length;}) ?? '';
  const caption = captionPart ? captionLines(captionPart, props.subtitles.max_chars_per_line) : '';
  return <AbsoluteFill style={{background: '#091321'}}>
    <div style={{position: 'absolute', width: portrait ? 1080 : 1920, height: portrait ? 1920 : 1080, transform: `scale(${width / (portrait ? 1080 : 1920)})`, transformOrigin: 'top left', color: '#f2f6fc', fontFamily: 'Yu Gothic UI, Yu Gothic, sans-serif'}}>
      {beat?.visuals.filter(x => frame >= x.from && frame < x.to).map((event, i) => <Visual key={`${beat.id}-${i}`} event={event} base={props.assetBase} fps={fps} />)}
      {active?.character && <Character line={active} config={props.characters} base={props.assetBase} frame={frame} fps={fps} />}
      {caption && <Subtitle text={caption} character={active?.character ?? null} config={props.subtitles} />}
    </div>
    {props.lines.map(line => <Sequence key={line.id} from={line.from} durationInFrames={Math.ceil(line.duration * fps)}><Audio src={asset(props.assetBase, line.path)} /></Sequence>)}
    {props.audio.map((sound, i) => <Sequence key={i} from={sound.from} durationInFrames={sound.to - sound.from}><Audio src={asset(props.assetBase, sound.path)} startFrom={Math.round((sound.source_start ?? 0) * fps)} loop={sound.loop ?? false} loopVolumeCurveBehavior="extend" volume={local => soundVolume(sound, local, fps, props.lines, props.mix)} /></Sequence>)}
  </AbsoluteFill>;
};
