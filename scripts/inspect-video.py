#!/usr/bin/env python3
"""inspect-video.py — Inspect encoded video metadata, decode it, and extract review stills.

Uses Python's standard library and ffmpeg/ffprobe on PATH (or explicit paths).
Example: python3 scripts/inspect-video.py clip.mp4 --out review --duration 8
         --size 1280x720 --codec h264 --pixel-format yuv420p --at 1 --at 7
Without --at, extracts the first, middle and final nominal frame. For variable
frame rate, choose explicit timestamps; average fps is only a sampling estimate.

The JSON report binds observations and stills to the input SHA-256. It never
claims that text is correct, the layout is legible, a desktop player works, or
cloud sync has arrived. Keep human/visual review separately, bound to that hash,
so a technical recheck neither erases it nor applies it to a changed movie.
Reports contain local input paths: keep them with the artifact, not in public
source control. The input is read only. Use an empty output directory per run;
existing evidence is never overwritten. A mismatch or tool failure exits 1.

--selftest exercises metadata failures without external dependencies.
--integration-test additionally uses ffmpeg to generate a synthetic movie and
checks extraction, full decoding, mismatches and corrupt input.
"""
import argparse
import datetime
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def run(argv):
    p = subprocess.run(argv, capture_output=True, text=True, check=False)
    if p.returncode:
        raise ValueError(f'{Path(argv[0]).name} exited {p.returncode}: {p.stderr.strip()}')
    return p


def number(value):
    try:
        result = float(Fraction(str(value)))
        return result if math.isfinite(result) else None
    except (ValueError, ZeroDivisionError):
        return None


def metadata(probe):
    videos = [s for s in probe.get('streams', [])
              if s.get('codec_type') == 'video' and not s.get('disposition', {}).get('attached_pic')]
    if not videos:
        raise ValueError('No non-cover-art video stream')
    v = videos[0]
    duration = number(v.get('duration')) or number(probe.get('format', {}).get('duration'))
    if duration is None or duration <= 0:
        raise ValueError('No positive finite video duration')
    return {'stream_index': v['index'], 'width': v['width'], 'height': v['height'],
            'codec': v.get('codec_name'), 'pixel_format': v.get('pix_fmt'),
            'duration_seconds': duration, 'fps': number(v.get('avg_frame_rate')),
            'audio_streams': sum(s.get('codec_type') == 'audio' for s in probe.get('streams', [])),
            'frames_metadata': number(v.get('nb_frames'))}


def mismatches(observed, expected, tolerance):
    errors = []
    for key, value in expected.items():
        if value is None:
            continue
        actual = observed.get(key)
        matches = (abs(actual-value) <= tolerance if key == 'duration_seconds'
                   and actual is not None else actual == value)
        if not matches:
            errors.append(f'{key}: expected {value}, observed {actual}')
    return errors


def inspect(video, out, expected, times=None, tolerance=.02,
            ffmpeg='ffmpeg', ffprobe='ffprobe'):
    video, out = Path(video).resolve(), Path(out).resolve()
    if not video.is_file():
        raise ValueError(f'Input is not a file: {video}')
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError('Output directory must be absent or empty; evidence is not overwritten')
    out.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with video.open('rb') as source:
        for chunk in iter(lambda: source.read(1024*1024), b''):
            digest.update(chunk)
    report = {'input': str(video), 'sha256': digest.hexdigest(), 'bytes': video.stat().st_size,
              'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'expected': expected, 'duration_tolerance_seconds': tolerance,
              'ok': False, 'errors': [], 'stills': [], 'visual_review': 'not performed'}
    try:
        probe = json.loads(run([ffprobe, '-v', 'error', '-show_streams', '-show_format',
                                '-of', 'json', str(video)]).stdout)
        observed = metadata(probe)
        report['observed'] = observed
        report['errors'].extend(mismatches(observed, expected, tolerance))
        decoded = run([ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-err_detect', 'explode',
                       '-i', str(video), '-map', f"0:{observed['stream_index']}",
                       '-f', 'null', '-'])
        if decoded.stderr.strip():
            raise ValueError('Decode reported errors: '+decoded.stderr.strip())
        report['full_decode'] = 'successful'
        duration, fps = observed['duration_seconds'], observed['fps']
        if times is None:
            if fps is None or fps <= 0:
                raise ValueError('Average frame rate unavailable; provide explicit --at times')
            times = sorted(set([0.0, duration/2, max(0.0, duration-1/fps)]))
        for i, t in enumerate(times):
            if not math.isfinite(t) or not 0 <= t < duration:
                raise ValueError(f'Still timestamp outside video: {t}')
            dest = out/f'frame-{i:03d}.png'
            run([ffmpeg, '-nostdin', '-v', 'error', '-n', '-ss', str(t), '-i', str(video),
                 '-map', f"0:{observed['stream_index']}", '-frames:v', '1', str(dest)])
            if not dest.is_file() or dest.stat().st_size == 0:
                raise ValueError(f'No decoded frame at {t}')
            report['stills'].append({'seconds': t, 'path': dest.name})
        report['ok'] = not report['errors']
    except (ValueError, OSError, KeyError) as exc:
        report['errors'].append(str(exc))
    (out/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return report


def selftest(integration=False, ffmpeg='ffmpeg', ffprobe='ffprobe'):
    sample = {'streams': [{'index': 0, 'codec_type': 'video', 'duration': '2',
              'width': 160, 'height': 90, 'codec_name': 'mpeg4', 'pix_fmt': 'yuv420p',
              'avg_frame_rate': '12/1', 'nb_frames': '24'}]}
    got = metadata(sample)
    assert not mismatches(got, {'width': 160, 'duration_seconds': 2}, .001)
    assert len(mismatches(got, {'width': 320, 'duration_seconds': 3}, .001)) == 2
    assert number('N/A') is None and number('0/0') is None
    for bad in ({}, {'streams': [dict(sample['streams'][0], disposition={'attached_pic': 1})]}):
        try:
            metadata(bad)
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid video was accepted')
    if integration:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            movie = root/'synthetic.mp4'
            run([ffmpeg, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                 'color=c=blue:s=160x90:r=12:d=2', '-c:v', 'mpeg4', '-pix_fmt', 'yuv420p', str(movie)])
            good = inspect(movie, root/'good', {'width': 160, 'duration_seconds': 2}, ffmpeg=ffmpeg, ffprobe=ffprobe)
            assert good['ok'] and len(good['stills']) == 3 and good['full_decode'] == 'successful'
            bad = inspect(movie, root/'wrong', {'duration_seconds': 3}, ffmpeg=ffmpeg, ffprobe=ffprobe)
            assert not bad['ok'] and bad['errors']
            outside = inspect(movie, root/'outside', {}, [2], ffmpeg=ffmpeg, ffprobe=ffprobe)
            assert not outside['ok']
            corrupt = root/'corrupt.mp4'; corrupt.write_bytes(b'not a media container')
            assert not inspect(corrupt, root/'corrupt-review', {}, ffmpeg=ffmpeg, ffprobe=ffprobe)['ok']
            try:
                inspect(movie, root/'good', {})
            except ValueError:
                pass
            else:
                raise AssertionError('Existing evidence was overwritten')
    print('inspect-video selftest: metadata, mismatches, invalid media'+(' and ffmpeg integration' if integration else ''))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('video', nargs='?', type=Path)
    p.add_argument('--out', type=Path)
    p.add_argument('--duration', type=float)
    p.add_argument('--tolerance', type=float, default=.02)
    p.add_argument('--size', help='WIDTHxHEIGHT')
    p.add_argument('--codec')
    p.add_argument('--pixel-format')
    p.add_argument('--at', type=float, action='append')
    p.add_argument('--ffmpeg', default=shutil.which('ffmpeg') or 'ffmpeg')
    p.add_argument('--ffprobe', default=shutil.which('ffprobe') or 'ffprobe')
    p.add_argument('--selftest', action='store_true')
    p.add_argument('--integration-test', action='store_true')
    args = p.parse_args()
    if args.selftest or args.integration_test:
        selftest(args.integration_test, args.ffmpeg, args.ffprobe)
        return 0
    if args.video is None or args.out is None:
        p.error('video and --out are required')
    if not math.isfinite(args.tolerance) or args.tolerance < 0:
        p.error('--tolerance must be finite and nonnegative')
    if args.duration is not None and (not math.isfinite(args.duration) or args.duration <= 0):
        p.error('--duration must be finite and positive')
    expected = {'duration_seconds': args.duration, 'codec': args.codec, 'pixel_format': args.pixel_format}
    if args.size:
        try:
            width, height = map(int, args.size.lower().split('x'))
            if min(width, height) <= 0:
                raise ValueError()
        except ValueError:
            p.error('--size requires positive WIDTHxHEIGHT')
        expected.update(width=width, height=height)
    try:
        report = inspect(args.video, args.out, expected, args.at, args.tolerance, args.ffmpeg, args.ffprobe)
    except (OSError, ValueError) as exc:
        p.exit(1, str(exc)+'\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
