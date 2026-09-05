import React from 'react';
import {Composition} from 'remotion';
import {Film, type FilmProps} from './Film';
export const RemotionRoot: React.FC = () => <Composition id="Film" component={Film} width={1920} height={1080} fps={30} durationInFrames={30} defaultProps={{} as FilmProps} calculateMetadata={({props}) => ({...props.video, durationInFrames: props.durationInFrames})} />;
