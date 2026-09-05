#!/usr/bin/env python3
"""Build and install the current user's native Finder Quick Action."""
import os
import plistlib
import shutil
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INSTALL = Path.home() / 'Library/Application Support/Smart Audio Merge'
APP = INSTALL / 'Smart Audio Merge.app'
CONTENTS = APP / 'Contents'
WORKFLOW = Path.home() / 'Library/Services/Smart Audio Merge.workflow'


def plist(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('wb') as file:
        plistlib.dump(data, file)


def main():
    (CONTENTS / 'MacOS').mkdir(parents=True, exist_ok=True)
    (CONTENTS / 'Resources/engine').mkdir(parents=True, exist_ok=True)
    for source in (ROOT / 'engine').glob('*.py'):
        shutil.copy2(source, CONTENTS / 'Resources/engine' / source.name)
    subprocess.run(['/usr/bin/clang', '-O2', '-fobjc-arc', '-fblocks', '-framework', 'AppKit', '-framework', 'QuartzCore',
                    '-framework', 'UniformTypeIdentifiers', *map(str, sorted((ROOT / 'native').glob('*.m'))),
                    '-o', str(CONTENTS / 'MacOS/SmartAudioMerge')], check=True)
    plist(CONTENTS / 'Info.plist', {
        'CFBundleIdentifier': 'com.tarioyou.smartaudiomerge',
        'CFBundleName': 'Smart Audio Merge', 'CFBundleDisplayName': 'Smart Audio Merge',
        'CFBundleExecutable': 'SmartAudioMerge', 'CFBundlePackageType': 'APPL',
        'CFBundleVersion': '1', 'CFBundleShortVersionString': '1.0',
        'LSMinimumSystemVersion': '13.0', 'NSHighResolutionCapable': True,
        'NSPrincipalClass': 'NSApplication',
        'NSDocumentsFolderUsageDescription': 'Read selected audio files and save your merged audio.',
        'NSDownloadsFolderUsageDescription': 'Read selected audio files and save your merged audio.',
        'NSDesktopFolderUsageDescription': 'Read selected audio files and save your merged audio.',
        'NSRemovableVolumesUsageDescription': 'Read selected audio files and save your merged audio.',
    })
    subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', str(APP)], check=True)
    command = 'exec "$HOME/Library/Application Support/Smart Audio Merge/Smart Audio Merge.app/Contents/MacOS/SmartAudioMerge" "$@"'
    action = {
        'ActionBundlePath': '/System/Library/Automator/Run Shell Script.action',
        'ActionName': 'Run Shell Script',
        'ActionParameters': {'CheckedForUserDefaultShell': True, 'COMMAND_STRING': command,
                             'inputMethod': 1, 'shell': '/bin/zsh', 'source': ''},
        'AMAccepts': {'Container': 'List', 'Optional': False, 'Types': ['com.apple.cocoa.path']},
        'AMProvides': {'Container': 'List', 'Types': ['com.apple.cocoa.string']},
        'AMActionVersion': '2.0.3', 'AMApplication': ['Automator'],
        'AMParameterProperties': {key: {} for key in ['CheckedForUserDefaultShell', 'COMMAND_STRING', 'inputMethod', 'shell', 'source']},
        'arguments': {}, 'BundleIdentifier': 'com.apple.RunShellScript',
        'CanShowSelectedItemsWhenRun': False, 'CanShowWhenRun': False,
        'Category': ['AMCategoryUtilities'], 'CFBundleVersion': '2.0.3',
        'Class Name': 'RunShellScriptAction', 'InputUUID': str(uuid.uuid4()),
        'OutputUUID': str(uuid.uuid4()), 'UUID': str(uuid.uuid4()), 'UnlocalizedApplications': ['Automator'],
    }
    plist(WORKFLOW / 'Contents/document.wflow', {
        'actions': [{'action': action}], 'AMApplicationBuild': '523', 'AMApplicationVersion': '2.10',
        'AMDocumentVersion': '2', 'connectors': {},
        'workflowMetaData': {
            'serviceApplicationBundleID': 'com.apple.finder',
            'serviceApplicationPath': '/System/Library/CoreServices/Finder.app',
            'serviceInputTypeIdentifier': 'com.apple.Automator.fileSystemObject',
            'serviceOutputTypeIdentifier': 'com.apple.Automator.nothing',
            'serviceProcessesInput': False, 'workflowTypeIdentifier': 'com.apple.Automator.servicesMenu',
            'serviceInputType': 'files', 'serviceInputTypeIsDirectory': False,
            'serviceInputTypeIsFile': True, 'serviceInputTypeIsText': False,
        }})
    plist(WORKFLOW / 'Contents/Info.plist', {
        'CFBundleIdentifier': 'com.tarioyou.smartaudiomerge.quickaction', 'CFBundleName': 'Smart Audio Merge',
        'CFBundleVersion': '1.0', 'NSServices': [{
            'NSMenuItem': {'default': 'Smart Audio Merge'}, 'NSMessage': 'runWorkflowAsService',
            'NSRequiredContext': {'NSApplicationIdentifier': 'com.apple.finder'},
            'NSSendFileTypes': ['public.audio'],
        }]})
    subprocess.run(['/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister', '-f', str(APP)], check=True)
    subprocess.run(['/System/Library/CoreServices/pbs', '-read_bundle', str(WORKFLOW)], check=True)
    subprocess.run(['/System/Library/CoreServices/pbs', '-update'], check=True)
    print(f'Installed app: {APP}')
    print(f'Installed Finder action: {WORKFLOW}')


if __name__ == '__main__':
    main()
