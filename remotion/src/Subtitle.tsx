import React from 'react';

type SpeakerStyle = {
  text_color: string;
  inner_outline_color: string;
  outer_outline_color: string;
};

export type SubtitleConfig = {
  font_family: string;
  font_size: number;
  font_weight: number;
  line_height: number;
  bottom: number;
  side_margin: number;
  min_height: number;
  max_chars_per_line: number;
  max_lines: number;
  inner_outline_width: number;
  outer_outline_width: number;
  default_style: SpeakerStyle;
  speaker_styles: Record<string, SpeakerStyle>;
};

export const Subtitle: React.FC<{text: string; character: string | null; config: SubtitleConfig}> = ({text, character, config}) => {
  const palette = (character && config.speaker_styles[character]) || config.default_style;
  const hasInnerOutline = palette.inner_outline_color.toLowerCase() !== palette.text_color.toLowerCase();
  const innerOutlineWidth = hasInnerOutline ? config.inner_outline_width : 0;
  const common: React.CSSProperties = {
    position: 'absolute', inset: 0, display: 'flex', justifyContent: 'center', alignItems: 'center',
    textAlign: 'center', fontFamily: config.font_family, fontSize: config.font_size,
    fontWeight: config.font_weight, lineHeight: config.line_height, color: palette.text_color,
    whiteSpace: 'pre', wordBreak: 'normal', lineBreak: 'strict', paintOrder: 'stroke fill',
  };
  const outerExtent = innerOutlineWidth + config.outer_outline_width;
  return <div style={{position: 'absolute', left: config.side_margin, right: config.side_margin, bottom: config.bottom, minHeight: config.min_height}}>
    <div aria-hidden style={{...common, WebkitTextStroke: `${outerExtent * 2}px ${palette.outer_outline_color}`}}>{text}</div>
    <div style={{...common, WebkitTextStroke: hasInnerOutline ? `${innerOutlineWidth * 2}px ${palette.inner_outline_color}` : undefined}}>{text}</div>
  </div>;
};
