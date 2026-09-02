import React from 'react';
import {Composition} from 'remotion';
import {NewsIntro, type NewsIntroProps} from './NewsIntro';
import {StatsCard, type StatsCardProps} from './StatsCard';

const defaultProps: NewsIntroProps = {
  kicker: 'WEEKLY BRIEFING',
  title: 'SPACE NEWS',
  subtitle: '直近7日間の重要ニュース',
  date: '2026.09.01',
  accent: '#42D4FF',
};

const statsDefaultProps: StatsCardProps = {
  kicker: 'KEY NUMBERS',
  title: '今週の重要ポイント',
  accent: '#42D4FF',
  stats: [
    {value: '37回', label: '同一ブースターの飛行回数'},
    {value: '100回', label: '2026年のFalcon 9打ち上げ'},
    {value: '29機', label: '今回投入したStarlink衛星'},
  ],
};

export const RemotionRoot: React.FC = () => (
  <>
    <Composition
      id="NewsIntro"
      component={NewsIntro}
      durationInFrames={240}
      fps={30}
      width={1920}
      height={1080}
      defaultProps={defaultProps}
    />
    <Composition
      id="StatsCard"
      component={StatsCard}
      durationInFrames={240}
      fps={30}
      width={1920}
      height={1080}
      defaultProps={statsDefaultProps}
    />
  </>
);
