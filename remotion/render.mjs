import {bundle} from '@remotion/bundler';
import {renderMedia, selectComposition} from '@remotion/renderer';
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import {fileURLToPath} from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.dirname(here);
const [projectArg, outputArg, quality = 'preview'] = process.argv.slice(2);
const project = path.resolve(projectArg);
const props = JSON.parse(fs.readFileSync(path.join(project, 'work/timing.json'), 'utf8'));
const server = http.createServer((req, res) => {
  try {
    const url = new URL(req.url, 'http://localhost');
    const match = /^\/(project|shared)\/(.*)$/.exec(decodeURIComponent(url.pathname));
    if (!match) {res.writeHead(404).end(); return;}
    const root = match[1] === 'project' ? project : path.join(repo, 'assets');
    const relative = match[1] === 'shared' ? match[2].replace(/^assets\//, '') : match[2];
    const file = fs.realpathSync(path.resolve(root, relative));
    const realRoot = fs.realpathSync(root);
    if (!file.startsWith(realRoot + path.sep)) {res.writeHead(403).end(); return;}
    const size = fs.statSync(file).size;
    const range = /^bytes=(\d+)-(\d*)$/.exec(req.headers.range ?? '');
    const start = range ? Number(range[1]) : 0;
    const end = range?.[2] ? Math.min(Number(range[2]), size - 1) : size - 1;
    if (start >= size || end < start) {res.writeHead(416).end(); return;}
    const types = {'.mp4': 'video/mp4', '.wav': 'audio/wav', '.mp3': 'audio/mpeg', '.png': 'image/png', '.jpg': 'image/jpeg', '.webp': 'image/webp'};
    const headers = {'Access-Control-Allow-Origin': '*', 'Content-Type': types[path.extname(file)] ?? 'application/octet-stream', 'Content-Length': end - start + 1, 'Accept-Ranges': 'bytes'};
    if (range) headers['Content-Range'] = `bytes ${start}-${end}/${size}`;
    res.writeHead(range ? 206 : 200, headers);
    fs.createReadStream(file, {start, end}).on('error', () => res.destroy()).pipe(res);
  } catch {res.writeHead(404).end();}
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
try {
  props.assetBase = `http://127.0.0.1:${server.address().port}`;
  const serveUrl = await bundle({entryPoint: path.join(here, 'src/index.ts'), publicDir: null,
    outDir: path.join(project, 'work/bundle'),
    webpackOverride: config => ({...config, resolve: {...config.resolve,
      modules: [path.join(here, 'node_modules'), 'node_modules']}})});
  const composition = await selectComposition({serveUrl, id: 'Film', inputProps: props, logLevel: 'error'});
  await renderMedia({composition, serveUrl, inputProps: props, outputLocation: path.resolve(outputArg),
    codec: 'h264', audioCodec: 'aac', pixelFormat: 'yuv420p', enforceAudioTrack: true,
    scale: quality === 'preview' ? 0.5 : 1, crf: quality === 'preview' ? 25 : 18,
    concurrency: 2, logLevel: 'error', timeoutInMilliseconds: 120000});
} finally {server.closeAllConnections(); server.close();}
