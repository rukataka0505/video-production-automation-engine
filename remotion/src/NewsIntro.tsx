import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';

export type NewsIntroProps = {
  kicker?: string;
  title: string;
  subtitle: string;
  date: string;
  accent?: string;
};

export const NewsIntro: React.FC<NewsIntroProps> = ({kicker = 'WEEKLY BRIEFING', title, subtitle, date, accent = '#42D4FF'}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const entrance = spring({frame, fps, config: {damping: 18, stiffness: 100}});
  const lineWidth = interpolate(frame, [6, 42], [0, 780], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const glow = interpolate(frame, [0, 60, 180, 239], [0.28, 0.55, 0.45, 0.2]);

  return (
    <AbsoluteFill
      style={{
        background: 'radial-gradient(circle at 74% 28%, #14304c 0%, #07111f 48%, #030811 100%)',
        color: 'white',
        fontFamily: 'Yu Gothic UI, Noto Sans JP, sans-serif',
        overflow: 'hidden',
      }}
    >
      <div style={{position: 'absolute', inset: -180, opacity: glow, background: `linear-gradient(115deg, transparent 38%, ${accent} 50%, transparent 62%)`, transform: `translateX(${frame * 2}px) rotate(-8deg)`}} />
      <div style={{position: 'absolute', left: 150, top: 205, transform: `translateY(${(1 - entrance) * 80}px)`, opacity: entrance}}>
        <div style={{fontSize: 30, letterSpacing: 10, color: accent, fontWeight: 700}}>{kicker}</div>
        <div style={{fontSize: 108, letterSpacing: 4, fontWeight: 800, lineHeight: 1.18, marginTop: 24}}>{title}</div>
        <div style={{width: lineWidth, height: 7, background: accent, boxShadow: `0 0 30px ${accent}`, marginTop: 28}} />
        <div style={{fontSize: 48, fontWeight: 600, marginTop: 34}}>{subtitle}</div>
      </div>
      <div style={{position: 'absolute', right: 150, bottom: 120, fontSize: 30, letterSpacing: 4, color: '#B6C9D9'}}>{date}</div>
      <div style={{position: 'absolute', left: 0, bottom: 0, width: `${interpolate(frame, [0, 239], [0, 100])}%`, height: 8, background: accent}} />
    </AbsoluteFill>
  );
};
