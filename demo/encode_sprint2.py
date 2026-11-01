"""Encode the real browser screencast with one uniform playback multiplier."""
import argparse
import json
from pathlib import Path
import subprocess
from PIL import Image

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--recording', type=Path, required=True)
parser.add_argument('--ffmpeg', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--normal-output', type=Path)
args = parser.parse_args()
recording = args.recording.resolve()
manifest = json.loads((recording / 'manifest.json').read_text())
assert not manifest['errors'], manifest['errors']
frames = manifest['frames']
# Native OS pickers appear in same-session screenshots but are omitted from
# Chromium's screencast surface. Preserve those actual captures while open.
captures = []
for index, step in enumerate(manifest['steps']):
    if 'dropdown open' in step['label']:
        captures.append((step['time'], manifest['steps'][index + 1]['time'] - .5, step['file']))
    if step['label'] == 'Delivered bags and receiver identity' and (recording / 'delivery-detail.png').exists():
        captures.append((step['time'], manifest['steps'][index + 1]['time'] - .5, 'delivery-detail.png'))
for start, stop, filename in captures:
    # Concat uses a single image codec; normalize real PNG captures to JPEG.
    source_capture = recording / filename
    normalized = recording / (source_capture.stem + '-capture.jpg')
    Image.open(source_capture).convert('RGB').save(normalized, quality=95)
    filename = normalized.name
    # Pickers can suppress screencast events entirely, so insert the actual
    # screenshot at its capture time rather than relying on an existing frame.
    restore = next((frame for frame in reversed(frames) if frame['time'] <= stop), frames[0])
    frames = [frame for frame in frames if not start <= frame['time'] < stop]
    frames += [{'time': start, 'file': filename}, {'time': stop, 'file': restore['file']}]
    frames.sort(key=lambda frame: frame['time'])
concat = recording / 'frames.txt'
lines = []
for index, frame in enumerate(frames):
    end = frames[index + 1]['time'] if index + 1 < len(frames) else manifest['duration']
    filename = frame['file']
    lines += [f"file '{(recording / filename).as_posix()}'", f'duration {max(.001, end - frame["time"]):.6f}']
lines += [f"file '{(recording / frames[-1]['file']).as_posix()}'"]
concat.write_text('\n'.join(lines), encoding='utf-8')
source = manifest['duration'] - frames[0]['time']
speed = source / 120


def encode(destination, multiplier, duration):
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        str(args.ffmpeg.resolve()), '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', str(concat),
        '-vf', f'setpts=PTS/{multiplier:.9f},fps=25', '-t', str(duration), '-an', '-c:v', 'libx264',
        '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(destination.resolve()),
    ], check=True)
    subprocess.run([str(args.ffmpeg.resolve()), '-v', 'error', '-i', str(destination.resolve()),
                    '-f', 'null', '-'], check=True)


encode(args.output, speed, 120)
if args.normal_output:
    encode(args.normal_output, 1, source)
print(json.dumps({'source_seconds': source, 'output_seconds': 120, 'uniform_speed': speed,
                  'captured_frames': len(manifest['frames']), 'encoded_image_samples': len(frames),
                  'audio': False, 'cursor': False, 'grey_clicks': True}, indent=2))
