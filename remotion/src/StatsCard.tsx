import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';

export type StatsCardProps = {
  kicker: string;
  title: string;
  accent?: string;
  stats: Array<{value: string; label: string}>;
};

export const StatsCard: React.FC<StatsCardProps> = ({kicker, title, accent = '#42D4FF', stats}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const titleProgress = spring({frame, fps, config: {damping: 18, stiffness: 110}});

  return (
    <AbsoluteFill
      style={{
        background: 'linear-gradient(135deg, #030811 0%, #071827 52%, #0B243A 100%)',
        color: 'white',
        fontFamily: 'Yu Gothic UI, Noto Sans JP, sans-serif',
        padding: '120px 140px',
      }}
    >
      <div style={{fontSize: 28, letterSpacing: 9, color: accent, fontWeight: 800, opacity: titleProgress}}>{kicker}</div>
      <div style={{fontSize: 68, fontWeight: 800, marginTop: 20, transform: `translateY(${(1 - titleProgress) * 40}px)`, opacity: titleProgress}}>{title}</div>
      <div style={{display: 'flex', gap: 34, marginTop: 88}}>
        {stats.map((stat, index) => {
          const progress = spring({frame: frame - 18 - index * 10, fps, config: {damping: 17, stiffness: 105}});
          const valueScale = interpolate(progress, [0, 1], [0.82, 1]);
          return (
            <div
              key={`${stat.value}-${index}`}
              style={{
                flex: 1,
                minHeight: 340,
                padding: '58px 42px',
                borderRadius: 28,
                border: `2px solid ${accent}55`,
                background: 'linear-gradient(160deg, rgba(255,255,255,0.10), rgba(255,255,255,0.035))',
                boxShadow: `0 24px 80px rgba(0,0,0,0.3), inset 0 0 50px ${accent}10`,
                opacity: progress,
                transform: `translateY(${(1 - progress) * 70}px)`,
              }}
            >
              <div style={{fontSize: 94, lineHeight: 1, fontWeight: 900, color: accent, transform: `scale(${valueScale})`, transformOrigin: 'left center'}}>{stat.value}</div>
              <div style={{fontSize: 31, lineHeight: 1.55, color: '#DCE9F3', marginTop: 42, fontWeight: 650}}>{stat.label}</div>
            </div>
          );
        })}
      </div>
      <div style={{position: 'absolute', right: 140, bottom: 80, width: 260, height: 6, background: accent, opacity: 0.8}} />
    </AbsoluteFill>
  );
};

