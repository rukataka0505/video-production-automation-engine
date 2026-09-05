import React from 'react';
import {AbsoluteFill, Audio, Img, OffthreadVideo, Sequence, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import CustomVisual from '@project-visuals';
import {captionParts, soundVolume} from './timing';

type Event = {from: number; to: number; kind: string; [key: string]: any};
export type Line = {id: string; beat: string; text: string; from: number; to: number; path: string; character: string | null; duration: number; mouth: {start: number; end: number; state: string}[]};
export type FilmProps = {
  title: string; video: {width: number; height: number; fps: number}; durationInFrames: number;
  lines: Line[]; beats: {id: string; title: string; from: number; to: number; visuals: Event[]}[];
  audio: Event[]; characters: any; mix: {duck_volume: number; duck_seconds: number}; assetBase: string;
};
const asset = (base: string, path: string) => `${base}/project/${path.split('/').map(encodeURIComponent).join('/')}`;
const cyan = '#6de1ec';
const fullFrame: React.CSSProperties = {position: 'absolute', inset: 0};

const Visual: React.FC<{event: Event; frame: number; base: string; fps: number; lineTimes: Record<string, {from: number; to: number}>}> = ({event: e, frame, base, fps, lineTimes}) => {
  const elapsed = frame - e.from;
  const reveal = interpolate(elapsed, [0, Math.max(1, fps * .2)], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  if (e.kind === 'media') return <div style={fullFrame}>{e.media === 'video'
    ? <Sequence from={e.from} durationInFrames={e.to - e.from} layout="none"><OffthreadVideo src={asset(base, e.path)} startFrom={Math.round((e.source_start ?? 0) * fps)} muted style={{width: '100%', height: '100%', objectFit: e.fit ?? 'cover'}} /></Sequence>
    : <Img src={asset(base, e.path)} style={{width: '100%', height: '100%', objectFit: e.fit ?? 'cover'}} />}</div>;
  if (e.kind === 'compare') return <div style={{...fullFrame, display: 'flex', gap: 28, alignItems: 'center'}}>{e.items.map((x: any, i: number) => <div key={i} style={{flex: 1, minWidth: 0, padding: 30, border: '2px solid #3b526a', borderRadius: 18, background: '#122034', textAlign: 'center'}}>
    {x.path && <Img src={asset(base, x.path)} style={{width: '100%', height: 230, objectFit: 'contain'}} />}
    <div style={{fontSize: 32, color: '#c6d3e2'}}>{x.label}</div><div style={{fontSize: 72, fontWeight: 800, color: i ? '#ffd27a' : cyan, marginTop: 20}}>{x.value}</div>
    {x.detail && <div style={{fontSize: 27, marginTop: 20}}>{x.detail}</div>}
  </div>)}</div>;
  if (e.kind === 'diagram') return <div style={{...fullFrame, display: 'flex', alignItems: 'center', gap: 14}}>{e.nodes.map((node: any, i: number) => <React.Fragment key={i}>
    {i > 0 && <div style={{color: cyan, fontSize: 38, opacity: frame >= node.from ? 1 : 0}}>→</div>}
    <div style={{flex: 1, padding: '34px 18px', border: '2px solid #4c7595', borderRadius: 16, background: '#152a40', opacity: frame >= node.from ? 1 : 0}}>
      <div style={{fontSize: 32, textAlign: 'center', fontWeight: 700, whiteSpace: 'pre-line'}}>{node.text}</div>
      {node.detail && <div style={{fontSize: 27, color: cyan, textAlign: 'center', marginTop: 20, whiteSpace: 'pre-line'}}>{node.detail}</div>}
    </div></React.Fragment>)}</div>;
  if (e.kind === 'focus') {
    const rect = e.rect ?? [5, 10, 90, 65];
    return <div style={{position: 'absolute', left: `${rect[0]}%`, top: `${rect[1]}%`, width: `${rect[2]}%`, height: `${rect[3]}%`, border: `5px solid ${e.color ?? '#ffd27a'}`, borderRadius: 12, opacity: reveal}}>
      <span style={{position: 'absolute', left: 15, top: -42, padding: '6px 18px', background: '#091321', color: e.color ?? '#ffd27a', fontSize: 30}}>{e.text}</span>
    </div>;
  }
  if (e.kind === 'text') return <div style={{...fullFrame, display: 'flex', justifyContent: 'center', alignItems: 'center', textAlign: 'center', fontSize: e.size ?? 62, lineHeight: 1.5, fontWeight: 800, color: e.color ?? '#fff', whiteSpace: 'pre-line', opacity: reveal}}>{e.text}</div>;
  if (e.kind === 'custom') return <CustomVisual frame={elapsed} fps={fps} data={e.props ?? {}} lineTimes={Object.fromEntries(Object.entries(lineTimes).map(([id, t]) => [id, {from: t.from - e.from, to: t.to - e.from}]))} asset={(path: string) => asset(base, path)} />;
  return null;
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
  const {fps, width} = useVideoConfig();
  const beat = props.beats.find(x => frame >= x.from && frame < x.to);
  const active = props.lines.find(x => frame >= x.from && frame < x.to);
  const used = new Set(props.lines.filter(x => x.beat === beat?.id).map(x => x.character));
  const left = used.has('zundamon') ? 490 : 120;
  const right = used.has('metan') ? 490 : 120;
  const parts = active ? captionParts(active.text) : [];
  const fraction = active ? (frame - active.from) / Math.max(1, active.to - active.from) : 0;
  let cumulative = 0;
  const caption = parts.find(x => {cumulative += x.length; return fraction < cumulative / active!.text.length;}) ?? '';
  const lineTimes = Object.fromEntries(props.lines.map(x => [x.id, {from: x.from, to: x.to}]));
  const color = active?.character === 'zundamon' ? '#66e07a' : active?.character === 'metan' ? '#c995ff' : '#fff';
  const safeArea: React.CSSProperties = {position: 'absolute', top: 165, bottom: 310, left, right};
  return <AbsoluteFill style={{background: '#091321'}}>
    <div style={{position: 'absolute', width: 1920, height: 1080, transform: `scale(${width / 1920})`, transformOrigin: 'top left', color: '#f2f6fc', fontFamily: 'Yu Gothic UI, Yu Gothic, sans-serif'}}>
      {beat?.visuals.filter(x => frame >= x.from && frame < x.to).map((event, i) => <div key={`${beat.id}-${i}`} style={event.kind === 'compare' || event.kind === 'diagram' ? safeArea : fullFrame}><Visual event={event} frame={frame} base={props.assetBase} fps={fps} lineTimes={lineTimes} /></div>)}
      <div style={{position: 'absolute', top: 76, left, right, fontSize: 36, color: cyan, fontWeight: 700}}>{beat?.title}</div>
      {active?.character && <Character line={active} config={props.characters} base={props.assetBase} frame={frame} fps={fps} />}
      {caption && <div style={{position: 'absolute', left: 170, right: 170, bottom: 55, minHeight: 150, display: 'flex', justifyContent: 'center', alignItems: 'center', textAlign: 'center', fontSize: 64, lineHeight: 1.3, fontWeight: 800, color, WebkitTextStroke: '10px #fff', paintOrder: 'stroke fill', textShadow: '4px 4px 2px #000, -4px -4px 2px #000, 4px -4px 2px #000, -4px 4px 2px #000', textWrap: 'balance', wordBreak: 'normal', lineBreak: 'strict', whiteSpace: 'pre-wrap'}}>{caption}</div>}
    </div>
    {props.lines.map(line => <Sequence key={line.id} from={line.from} durationInFrames={Math.ceil(line.duration * fps)}><Audio src={asset(props.assetBase, line.path)} /></Sequence>)}
    {props.audio.map((sound, i) => <Sequence key={i} from={sound.from} durationInFrames={sound.to - sound.from}><Audio src={asset(props.assetBase, sound.path)} startFrom={Math.round((sound.source_start ?? 0) * fps)} loop={sound.loop ?? false} loopVolumeCurveBehavior="extend" volume={local => soundVolume(sound, local, fps, props.lines, props.mix)} /></Sequence>)}
  </AbsoluteFill>;
};
