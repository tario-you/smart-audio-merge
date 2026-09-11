"""Verify real decoded audio, source preservation, and failure cleanup."""
import array
import hashlib
import json
import math
import os
import random
import signal
import subprocess
import sys
import time
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
from audio import probe, tool

ARTIFACTS = ROOT / '.test-artifacts'
ARTIFACTS.mkdir(exist_ok=True)
TEST = Path(tempfile.mkdtemp(prefix='audio-qa-', dir=ARTIFACTS))
INPUT = TEST / 'inputs'
INPUT.mkdir(exist_ok=True)
ENGINE = ROOT / 'engine/main.py'


def run(args, **kwargs):
    return subprocess.run(args, capture_output=True, check=True, **kwargs)


def tone(path, frequency, duration=1.2, rate=44100):
    samples = array.array('h', (int(8000 * math.sin(2 * math.pi * frequency * i / rate)) for i in range(int(duration * rate))))
    with wave.open(str(path), 'wb') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(rate); f.writeframes(samples.tobytes())


def decode(path, rate=8000):
    raw = run([tool('ffmpeg'), '-v', 'error', '-i', str(path), '-ac', '1', '-ar', str(rate), '-f', 'f32le', 'pipe:1']).stdout
    data = array.array('f'); data.frombytes(raw)
    return data


def frequency(data, start, length=.4, rate=8000):
    data = data[int(start * rate):int((start + length) * rate)]
    crossings = sum(a <= 0 < b for a, b in zip(data, data[1:]))
    return crossings / length


def engine(args):
    return subprocess.run([sys.executable, str(ENGINE)] + list(map(str, args)), capture_output=True, text=True)


files = []
names = ['001_1 intro.wav', "Chapter two - quote's \"test\".mp3", 'Track III.flac', '04 recording.m4a', '10 last\nline.wav']
freqs = [300, 450, 600, 750, 900]
for index, (name, hz) in enumerate(zip(names, freqs)):
    source = TEST / f'tone-{index}.wav'
    tone(source, hz, rate=44100 if index % 2 else 48000)
    target = INPUT / name
    if target.suffix == '.wav':
        target.write_bytes(source.read_bytes())
    else:
        run([tool('ffmpeg'), '-v', 'error', '-y', '-i', str(source), str(target)])
    files.append(target)
hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
shuffled = files[::-1]
plan = engine(['plan', '--', *shuffled])
assert plan.returncode == 0, plan.stdout
assert [x['name'] for x in json.loads(plan.stdout)['items']] == names
print('PASS: mixed formats, names with spaces, quotes, and newline; correct order', flush=True)

for suffix in ['mp3', 'm4a', 'flac', 'wav']:
    output = TEST / f'mixed-result-{time.time_ns()}.{suffix}'
    result = engine(['merge', '--output', output, '--', *shuffled])
    assert result.returncode == 0, result.stdout + result.stderr
    samples = decode(output)
    duration = len(samples) / 8000
    assert abs(duration - 6) < .12, duration
    measured = [frequency(samples, i * 1.2 + .35) for i in range(5)]
    assert all(abs(a - b) < 5 for a, b in zip(measured, freqs)), measured
    print(f'PASS: {suffix.upper()}, duration {duration:.3f}s, audio sequence {measured}', flush=True)

    before = hashlib.sha256(output.read_bytes()).hexdigest()
    refused = engine(['merge', '--output', output, '--', *files])
    assert refused.returncode == 1 and 'already exists' in refused.stdout
    assert hashlib.sha256(output.read_bytes()).hexdigest() == before
print('PASS: all existing output files preserved', flush=True)

attempt = engine(['merge', '--output', files[0], '--', *files])
assert attempt.returncode == 1
for path, before in hashes.items():
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == before
print('PASS: input hashes unchanged, including attempted source overwrite', flush=True)

# Lyrics3 and ID3v1 tags sit after the last audio frame, and the MP3 decoder
# reports that trailing block as one damaged packet. Every chapter of a real
# 75-file audiobook carried one, so the first file ended the whole merge.
tagged = TEST / 'trailing-tag.mp3'
run([tool('ffmpeg'), '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=520:duration=3', '-c:a', 'libmp3lame', str(tagged)])
lyrics3 = b'LYRICSBEGIN' + b'IND' + b'00002' + b'10' + b'LYR' + b'00000'
with tagged.open('ab') as handle:
    handle.write(lyrics3 + b'%06d' % len(lyrics3) + b'LYRICS200' + b'TAG' + b'Tagged tone'.ljust(125, b'\0'))
strict = subprocess.run([tool('ffmpeg'), '-v', 'error', '-xerror', '-i', str(tagged), '-f', 'null', '-'], capture_output=True)
assert strict.returncode != 0, 'the fixture no longer carries the damaged trailing packet'
tagged_out = TEST / f'tagged-{time.time_ns()}.mp3'
result = engine(['merge', '--keep-order', '--output', tagged_out, '--', tagged, files[0]])
assert result.returncode == 0, result.stdout + result.stderr
samples = decode(tagged_out)
assert abs(len(samples) / 8000 - 4.2) < .15, len(samples) / 8000
assert abs(frequency(samples, 1) - 520) < 5 and abs(frequency(samples, 3.5) - 300) < 5
print('PASS: a trailing Lyrics3 and ID3v1 tag merges with all of its audio', flush=True)

# Tolerating that tag must not hide a file that really loses audio.
from audio import merge as merge_audio
short_out = TEST / f'short-{time.time_ns()}.mp3'
try:
    merge_audio([{**probe(tagged), 'duration': 600.0}], short_out, lambda event: None)
    raise AssertionError('a materially short decode was accepted')
except RuntimeError as error:
    assert 'could be read' in str(error), error
assert not short_out.exists() and not list(TEST.glob('.smart-audio-merge-*'))
print('PASS: a materially short decode still fails and leaves no output', flush=True)

bad = TEST / 'broken.mp3'; bad.write_bytes(b'not audio')
failed_out = TEST / 'must-not-exist.mp3'
result = engine(['merge', '--output', failed_out, '--', files[0], bad])
assert result.returncode == 1 and not failed_out.exists()
print('PASS: unreadable input fails cleanly', flush=True)

# A long, compact synthetic input makes cancellation observable during encoding.
long = TEST / 'long.flac'
run([tool('ffmpeg'), '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=200:duration=1800', '-c:a', 'flac', str(long)])
cancel_out = TEST / 'cancelled.mp3'
process = subprocess.Popen([sys.executable, str(ENGINE), 'merge', '--output', str(cancel_out), str(long), str(files[0])], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
first = process.stdout.readline()
assert 'progress' in first, first
process.terminate()
rest, errors = process.communicate(timeout=15)
assert process.returncode == 130, (process.returncode, rest, errors)
assert not cancel_out.exists()
assert not list(TEST.glob('.smart-audio-merge-*'))
print('PASS: cancellation removes temporary output and stops child encoders', flush=True)

# Exercise 100 selected files, not only 100 sort keys.
hundred = TEST / 'hundred'; hundred.mkdir(exist_ok=True)
paths = []
for n in range(1, 101):
    path = hundred / f'{n:0{1+n%3}d}_1.wav'
    tone(path, 200 + n * 10, duration=.12, rate=8000)
    paths.append(path)
random.Random(71).shuffle(paths)
out100 = TEST / f'hundred-{time.time_ns()}.flac'
result = engine(['merge', '--output', out100, '--', *paths])
assert result.returncode == 0, result.stdout + result.stderr
samples = decode(out100)
assert abs(len(samples) / 8000 - 12) < .01
for n in range(100):
    hz = frequency(samples, n * .12 + .02, length=.08)
    assert abs(hz - (210 + n * 10)) < 15, (n, hz)
print('PASS: 100-file merge, 12.000s, all 100 tones in numeric order', flush=True)

# Line-separated fixture for automator CLI; its CLI cannot carry a newline filename.
(TEST / 'workflow-input.txt').write_text('\n'.join(str(p) for p in files[:4][::-1]) + '\n')
print('ALL INTEGRATION CHECKS PASSED', flush=True)
print(f'Test artifacts: {TEST}', flush=True)
