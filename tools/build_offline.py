"""Build Windows/macOS core bundles, or an optional MCP bundle for this OS/Python."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
from zipfile import ZipFile, ZIP_DEFLATED


def run(*args, env=None):
    subprocess.run([sys.executable, '-m', 'pip', *args], check=True, env=env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-mcp', action='store_true', help='Include MCP SDK/native wheels for the build computer OS, architecture and Python minor')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    target = sysconfig.get_platform().replace('.', '_') + f'-py{sys.version_info.major}{sys.version_info.minor}'
    folder = root / 'dist' / ('offline-mcp-' + target if args.with_mcp else 'offline')
    wheels = folder / 'wheelhouse'
    wheels.mkdir(parents=True, exist_ok=True)
    # Regenerate only this build's wheelhouse. A repeated MCP build must not
    # mistake native SDK wheels from its previous run for core dependencies.
    for wheel in wheels.glob('*.whl'):
        wheel.unlink()
    run('download', '--only-binary=:all:', '--dest', str(wheels), '-r', 'requirements.txt')
    for path in wheels.glob('markupsafe-*.whl'):
        path.unlink()
    # Force its documented compiler-failure fallback so the wheel contains only
    # Python, rather than a native extension for the build computer.
    run('wheel', '--no-deps', '--no-binary=MarkupSafe', '--no-cache-dir', 'MarkupSafe==3.0.4', '-w', str(wheels),
        env={**os.environ, 'CIBUILDWHEEL': '0', 'CC': 'powerapps-no-native-compiler'})
    run('wheel', '--no-deps', '.', '-w', str(wheels))
    if any(not p.name.endswith('-none-any.whl') and not p.name.startswith('regex-') for p in wheels.glob('*.whl')):
        raise RuntimeError('Core bundle contains an unexpected native dependency')
    # Regex has a native extension. Include compatible CPython wheels for each
    # supported Windows/macOS architecture and version, without a compiler or
    # network on the work computer. Pip selects its matching wheel offline.
    for minor in ('311','312','313','314'):
        mac_intel={'311':'macosx_10_9_x86_64','312':'macosx_10_13_x86_64',
                   '313':'macosx_10_13_x86_64','314':'macosx_10_15_x86_64'}[minor]
        for platform in ('win_amd64','win_arm64','macosx_11_0_arm64',mac_intel):
            run('download','--only-binary=:all:','--no-deps','--dest',str(wheels),
                '--platform',platform,'--python-version',minor,'--implementation','cp',
                '--abi','cp'+minor,'regex==2026.9.29')
    if args.with_mcp:
        run('download', '--only-binary=:all:', '--dest', str(wheels), 'mcp==2.3.0')
        # Pin every wheel actually resolved; optional native dependencies require a
        # separate bundle built on a machine matching the intended work computer.
        requirements = sorted({p.name.split('-')[0].replace('_', '-') + '==' + p.name.split('-')[1]
                               for p in wheels.glob('*.whl')})
        (folder / 'requirements-mcp.txt').write_text('\n'.join(requirements) + '\n', encoding='utf-8')
    for name in ['setup_offline.cmd', 'setup_offline.sh', 'start.cmd', 'start.sh', 'requirements.txt', 'README.md', 'LICENSE']:
        shutil.copy2(root / name, folder / name)
    documentation = folder / 'docs'
    if documentation.exists():
        shutil.rmtree(documentation)
    shutil.copytree(root / 'docs', documentation)
    if args.with_mcp:
        for name in ('setup_offline.cmd', 'setup_offline.sh'):
            script = folder / name
            script.write_text(script.read_text(encoding='utf-8').replace('powerapps-sim==0.1.0', '-r requirements-mcp.txt'), encoding='utf-8')
    (folder / 'bundle.json').write_text(json.dumps({'kind':'mcp' if args.with_mcp else 'core',
        'sdk':'2.3.0' if args.with_mcp else None, 'target':target if args.with_mcp else 'windows-macos-cpython',
        'babel':'2.18.0','regex':'2026.9.29','regex_architectures':['Windows x64','Windows ARM64','macOS Intel','macOS Apple Silicon'],
        'python':f'{sys.version_info.major}.{sys.version_info.minor}' if args.with_mcp else '3.11–3.14'}, indent=2), encoding='utf-8')
    output = root / 'dist' / ('powerapps-sim-offline-mcp-' + target + '.zip' if args.with_mcp else 'powerapps-sim-offline.zip')
    with ZipFile(output, 'w', ZIP_DEFLATED) as z:
        for path in folder.rglob('*'):
            if path.is_file():
                z.write(path, path.relative_to(folder))
    print(f'Offline bundle: {output}')


if __name__ == '__main__':
    main()
