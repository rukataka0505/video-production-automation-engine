declare module '@project-visuals' {
  import type {ComponentType} from 'react';
  const component: ComponentType<{frame: number; fps: number; data: any; lineTimes: Record<string, {from: number; to: number}>; asset: (path: string) => string}>;
  export default component;
}
