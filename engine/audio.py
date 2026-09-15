"""Read-only inputs, bounded-memory decoding, and atomic output publication."""
import json
import ctypes
import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

CHILDREN = set()


def tool(name):
    for candidate in (f'/opt/homebrew/bin/{name}', f'/usr/local/bin/{name}', shutil.which(name)):
        if candidate and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError(f'{name} is unavailable. Reinstall FFmpeg with Homebrew.')


def stop_children():
    for process in list(CHILDREN):
        if process.poll() is None:
            process.terminate()
    for process in list(CHILDREN):
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    CHILDREN.clear()


def cancelled(_signum, _frame):
    raise KeyboardInterrupt


def details(text):
    """Keep FFmpeg's own last words whole, so a message never starts mid-word."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return ' | '.join(lines[-3:])[-500:] or 'FFmpeg reported no details.'


def clock(seconds):
    seconds = max(0, round(seconds))
    return (f'{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}' if seconds >= 3600
            else f'{seconds // 60}:{seconds % 60:02d}')


def probe(path):
    path = Path(path).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError(f'Select audio files, including: {path.name}')
    args = [tool('ffprobe'), '-v', 'error', '-select_streams', 'a:0', '-show_streams', '-show_format', '-of', 'json', str(path)]
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    CHILDREN.add(process)
    try:
        stdout, stderr = process.communicate(timeout=45)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        CHILDREN.discard(process)
    if process.returncode:
        raise ValueError(f'Cannot read audio from {path.name}: {details(stderr)}')
    data = json.loads(stdout)
    streams = data.get('streams', [])
    if not streams:
        raise ValueError(f'No audio track found in {path.name}.')
    stream = streams[0]
    tags = {k.lower(): v for k, v in {**data.get('format', {}).get('tags', {}), **stream.get('tags', {})}.items()}
    def tag_number(name):
        try:
            return int(str(tags.get(name, '')).split('/')[0])
        except ValueError:
            return None
    duration = float(stream.get('duration') or data.get('format', {}).get('duration') or 0)
    return {'path': str(path), 'name': path.name, 'duration': duration,
            'codec': stream.get('codec_name'),
            'sample_rate': int(stream.get('sample_rate', 44100)), 'channels': int(stream.get('channels', 2)),
            'track': tag_number('track'), 'disc': tag_number('disc')}


def inspect(paths):
    unique = list(dict.fromkeys(str(Path(p).expanduser().resolve(strict=True)) for p in paths))
    if len(unique) < 2:
        raise ValueError('Select at least two different audio files in Finder.')
    return [probe(path) for path in unique]


def publish(temporary, output):
    # macOS RENAME_EXCL publishes atomically and preserves any existing file.
    # Unlike hard links, this also works on removable filesystems such as exFAT.
    libc = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
    rename = libc.renamex_np
    rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(os.fsencode(temporary), os.fsencode(output), 0x4):
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(output))


def can_copy_mp3(items, output):
    return (output.suffix.lower() == '.mp3' and bool(items)
            and all(item.get('codec') == 'mp3' and item['duration'] > 0 for item in items)
            and len({(item['sample_rate'], item['channels']) for item in items}) == 1)


def copy_mp3(items, temporary, emit):
    """Copy compatible MP3 frames; uncertain inputs use the existing decoder."""
    # Aliases live on the system volume because exFAT destinations cannot
    # create symlinks. Only the final audio staging file uses the destination.
    with tempfile.TemporaryDirectory(prefix='smart-audio-merge-inputs-') as folder:
        return _copy_mp3(items, temporary, emit, Path(folder))


def _copy_mp3(items, temporary, emit, folder):
    # Safe aliases keep quotes, backslashes and newlines out of ffconcat syntax.
    for index, item in enumerate(items):
        (folder / f'input-{index}.mp3').symlink_to(item['path'])
    listing = folder / 'inputs.ffconcat'
    listing.write_text('ffconcat version 1.0\n' + ''.join(
        f"file input-{index}.mp3\n" for index in range(len(items))))
    emit({'event': 'progress', 'fraction': 0, 'message': 'Merging MP3 files without re-encoding…'})
    total = sum(item['duration'] for item in items)
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen([tool('ffmpeg'), '-hide_banner', '-loglevel', 'error', '-nostdin',
            '-f', 'concat', '-safe', '1', '-i', str(listing), '-map', '0:a:0',
            '-map_metadata', '-1', '-map_chapters', '-1', '-c:a', 'copy',
            # Rebuild packet timestamps from frame durations. Some MP3 headers
            # exclude padding, making concat timestamps overlap at each join.
            '-bsf:a', 'setts=ts=if(eq(N\\,0)\\,0\\,PREV_OUTDTS+PREV_OUTDURATION)',
            '-progress', 'pipe:1', '-nostats', '-n', str(temporary)],
            stdout=subprocess.PIPE, stderr=errors, text=True)
        CHILDREN.add(process)
        try:
            for line in process.stdout:
                if line.startswith('out_time_us='):
                    try:
                        seconds = int(line.strip().split('=', 1)[1]) / 1_000_000
                    except ValueError:
                        continue
                    emit({'event': 'progress', 'fraction': min(.99, max(0, seconds / total)),
                          'message': 'Merging MP3 files without re-encoding…'})
            status = process.wait()
            errors.seek(0)
            if status or errors.read():
                return None
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            process.stdout.close()
            CHILDREN.discard(process)
    try:
        actual = probe(temporary)
    except (ValueError, RuntimeError):
        return None
    # FFmpeg versions differ on whether reported MP3 duration includes padding.
    # Copy preserves up to two MPEG frames of padding per input. Never allow
    # that positive allowance to hide missing audio.
    delta = actual['duration'] - total
    padding = len(items) * 2304 / items[0]['sample_rate']
    if delta < -max(.1, len(items) * .002) or delta > padding + .1:
        return None
    return actual


def merge(items, output, emit):
    output = Path(output).expanduser().absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('That destination already exists. Choose a new filename to preserve it.')
    if not output.parent.is_dir():
        raise ValueError('Choose an existing destination folder.')
    formats = {
        '.mp3': ['-c:a', 'libmp3lame', '-q:a', '2'],
        '.m4a': ['-c:a', 'aac', '-b:a', '256k', '-movflags', '+faststart'],
        '.flac': ['-c:a', 'flac', '-sample_fmt', 's32'],
        '.wav': ['-c:a', 'pcm_s24le', '-rf64', 'auto'],
    }
    codec = formats.get(output.suffix.lower())
    if codec is None:
        raise ValueError('Choose MP3, M4A, FLAC, or WAV output.')
    sample_rate = max(item['sample_rate'] for item in items)
    if output.suffix.lower() == '.mp3':
        sample_rate = min(48000, max(32000, sample_rate))
        sample_rate = min((32000, 44100, 48000), key=lambda n: abs(n - sample_rate))
    channels = min(2, max(item['channels'] for item in items))
    total = sum(item['duration'] for item in items)
    ffmpeg = tool('ffmpeg')
    with tempfile.TemporaryDirectory(prefix='.smart-audio-merge-', dir=output.parent) as temp:
        temporary = Path(temp) / ('merged' + output.suffix.lower())
        if can_copy_mp3(items, output):
            actual = copy_mp3(items, temporary, emit)
            if actual is not None:
                publish(temporary, output)
                emit({'event': 'complete', 'output': str(output), 'duration': actual['duration']})
                return
            temporary.unlink(missing_ok=True)
            emit({'event': 'progress', 'fraction': 0, 'message': 'Converting audio for compatibility…'})
        with tempfile.TemporaryFile() as encoder_errors:
            encoder = subprocess.Popen([ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-f', 'f32le',
                '-ar', str(sample_rate), '-ac', str(channels), '-i', 'pipe:0', '-map_metadata', '-1',
                *codec, '-threads', '2', '-n', str(temporary)], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=encoder_errors)
            CHILDREN.add(encoder)
            try:
                completed = 0
                for index, item in enumerate(items):
                    emit({'event': 'progress', 'fraction': index / len(items), 'message': f'Merging {index + 1} of {len(items)}: {item["name"]}'})
                    with tempfile.TemporaryFile() as decoder_errors:
                        decoder = subprocess.Popen([ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin',
                            '-i', item['path'], '-map', '0:a:0', '-vn', '-sn', '-dn', '-ar', str(sample_rate), '-ac', str(channels),
                            '-c:a', 'pcm_f32le', '-f', 'f32le', '-threads', '2', 'pipe:1'], stdout=subprocess.PIPE, stderr=decoder_errors)
                        CHILDREN.add(decoder)
                        count, last_update = 0, 0
                        try:
                            while chunk := decoder.stdout.read(256 * 1024):
                                encoder.stdin.write(chunk)
                                count += len(chunk)
                                seconds = count / (4 * sample_rate * channels)
                                if seconds - last_update >= 3:
                                    fraction = min(.99, (completed + seconds) / total) if total else index / len(items)
                                    emit({'event': 'progress', 'fraction': fraction, 'message': f'Merging {index + 1} of {len(items)}: {item["name"]}'})
                                    last_update = seconds
                            decoder.stdout.close()
                            status = decoder.wait()
                            decoded = count / (4 * sample_rate * channels)
                            # Tags that trail the last audio frame, such as Lyrics3 and ID3v1,
                            # reach the decoder as one damaged packet. Judge the audio that came
                            # out, so a recoverable decoder complaint cannot fail a whole file.
                            decoder_errors.seek(0)
                            reported = details(decoder_errors.read().decode(errors='replace'))
                            if status != 0 or count == 0:
                                raise RuntimeError(f'Could not decode {item["name"]}: {reported}')
                            if item['duration'] - decoded > max(2, item['duration'] * .01):
                                raise RuntimeError(f'Only {clock(decoded)} of {clock(item["duration"])} could be read '
                                                   f'from {item["name"]}: {reported}')
                            CHILDREN.discard(decoder)
                            completed += decoded
                        finally:
                            if decoder.poll() is None:
                                decoder.terminate()
                                decoder.wait()
                            CHILDREN.discard(decoder)
                encoder.stdin.close()
                emit({'event': 'progress', 'fraction': .99, 'message': 'Finishing the merged file…'})
                if encoder.wait() != 0:
                    encoder_errors.seek(0)
                    raise RuntimeError('Audio encoding failed: ' + encoder_errors.read().decode(errors='replace')[-600:])
                CHILDREN.discard(encoder)
                actual = probe(temporary)
                decoded_duration = completed
                if abs(actual['duration'] - decoded_duration) > max(.5, decoded_duration * .002):
                    raise RuntimeError('Output duration verification failed. The partial output was removed.')
                publish(temporary, output)
                emit({'event': 'complete', 'output': str(output), 'duration': actual['duration']})
            finally:
                # A failed file leaves the encoder waiting on its pipe, and the
                # interpreter would report that broken pipe after the real reason.
                try:
                    encoder.stdin.close()
                except (BrokenPipeError, OSError):
                    pass
                stop_children()


for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, cancelled)
