#! /usr/bin/env python
# -*- coding: utf-8 -*-
#
#############################################################
#                                                           #
#      Copyright @ 2018 -  Dashingsoft corp.                #
#      All rights reserved.                                 #
#                                                           #
#      pyarmor                                              #
#                                                           #
#      Version: 4.3.2 -                                     #
#                                                           #
#############################################################
#
#
#  @File: packer.py
#
#  @Author: Jondy Zhao(jondy.zhao@gmail.com)
#
#  @Create Date: 2018/11/08
#
#  @Description:
#
#   Pack obfuscated Python scripts with PyInstaller
#
#   The prefer way is
#
#       pip install pyinstaller
#       cd /path/to/src
#       parmor pack hello.py
#

'''
Pack obfuscated scripts to one bundle, distribute the bundle as a
folder or file to other people, and they can execute your program
without Python installed.

'''

import logging
import os
import re
import shutil
import sys

from codecs import open as codecs_open
from distutils.util import get_platform
from glob import glob
from json import load as json_load
from py_compile import compile as compile_file
from shlex import split
from subprocess import Popen, PIPE, STDOUT
from zipfile import PyZipFile

import polyfills.argparse as argparse

# Default output path, library name, command options for setup script
DEFAULT_PACKER = {
    'py2app': ('dist', 'library.zip', ['py2app', '--dist-dir']),
    'py2exe': ('dist', 'library.zip', ['py2exe', '--dist-dir']),
    'PyInstaller': ('dist', '', ['-m', 'PyInstaller', '--distpath']),
    'cx_Freeze': (
        os.path.join(
            'build', 'exe.%s-%s' % (get_platform(), sys.version[0:3])),
        'python%s%s.zip' % sys.version_info[:2],
        ['build', '--build-exe'])
}


def logaction(func):
    def wrap(*args, **kwargs):
        logging.info('%s', func.__name__)
        return func(*args, **kwargs)
    return wrap


def run_command(cmdlist, verbose=True):
    logging.info('\n\n%s\n\n', ' '.join(
        [x if x.find(' ') == -1 else ('"%s"' % x) for x in cmdlist]))
    if verbose:
        sep = '=' * 20
        logging.info('%s Run command %s', sep, sep)
        p = Popen(cmdlist)
        p.wait()
        if p.returncode != 0:
            raise RuntimeError('Run command failed')
        logging.info('%s End command %s\n', sep, sep)
    else:
        p = Popen(cmdlist, stdout=PIPE, stderr=STDOUT)
        output, _ = p.communicate()
        if p.returncode != 0:
            raise RuntimeError(output.decode())


def relpath(path, start=os.curdir):
    try:
        r = os.path.relpath(path, start)
        return path if r.count('..') > 2 else r
    except Exception:
        return path


@logaction
def update_library(obfdist, libzip):
    '''Update compressed library generated by py2exe or cx_Freeze, replace
the original scripts with obfuscated ones.

    '''
    # # It's simple ,but there are duplicated .pyc files
    # with PyZipFile(libzip, 'a') as f:
    #     f.writepy(obfdist)
    filelist = []
    for root, dirs, files in os.walk(obfdist):
        filelist.extend([os.path.join(root, s) for s in files])

    with PyZipFile(libzip, 'r') as f:
        namelist = f.namelist()
        f.extractall(obfdist)

    for s in filelist:
        if s.lower().endswith('.py'):
            compile_file(s, s + 'c')

    with PyZipFile(libzip, 'w') as f:
        for name in namelist:
            f.write(os.path.join(obfdist, name), name)


@logaction
def copy_runtime_files(runtimes, output):
    for s in glob(os.path.join(runtimes, '*.key')):
        shutil.copy(s, output)
    for s in glob(os.path.join(runtimes, '*.lic')):
        shutil.copy(s, output)
    for dllname in glob(os.path.join(runtimes, '_pytransform.*')):
        shutil.copy(dllname, output)


def pathwrapper(func):
    def wrap(*args, **kwargs):
        oldpath = os.getcwd()
        os.chdir(args[2])
        logging.info('Change current path to %s', os.getcwd())
        logging.info('-' * 50)
        try:
            return func(*args, **kwargs)
        finally:
            os.chdir(oldpath)
            logging.info('Restore current path to %s', oldpath)
            logging.info('%s\n', '-' * 50)
    return wrap


@pathwrapper
def run_setup_script(src, entry, build, script, packcmd, obfdist):
    '''Update entry script, copy pytransform.py to source path, then run
setup script to build the bundle.

    '''
    obf_entry = os.path.join(obfdist, entry)

    tempfile = '%s.armor.bak' % entry
    shutil.move(os.path.join(src, entry), tempfile)
    shutil.move(obf_entry, src)
    shutil.copy(os.path.join(obfdist, 'pytransform.py'), src)

    try:
        run_command([sys.executable, script] + packcmd)
    finally:
        shutil.move(tempfile, os.path.join(src, entry))
        os.remove(os.path.join(src, 'pytransform.py'))


def call_pyarmor(args):
    s = os.path.join(os.path.dirname(__file__), 'pyarmor.py')
    run_command([sys.executable, s] + list(args))


def _packer(t, src, entry, build, script, output, options, xoptions, clean):
    libname = DEFAULT_PACKER[t][1]
    packcmd = DEFAULT_PACKER[t][2] + [relpath(output, build)] + options
    script = 'setup.py' if script is None else script
    check_setup_script(t, os.path.join(build, script))
    if xoptions:
        logging.warning('-x, -xoptions are ignored')

    project = relpath(os.path.join(build, 'obf'))
    obfdist = os.path.join(project, 'dist')

    logging.info('obfuscated scrips output path: %s', obfdist)
    logging.info('build path: %s', project)
    if clean and os.path.exists(project):
        logging.info('Remove build path')
        shutil.rmtree(project)

    logging.info('Run PyArmor to create a project')
    call_pyarmor(['init', '-t', 'app', '--src', relpath(src),
                  '--entry', entry, project])

    logging.info('Run PyArmor to config the project')
    filters = ('global-include *.py', 'prune build, prune dist',
               'prune %s' % project,
               'exclude %s pytransform.py' % entry)
    args = ('config', '--runtime-path', '.', '--package-runtime', '0',
            '--restrict-mode', '0', '--manifest', ','.join(filters), project)
    call_pyarmor(args)

    logging.info('Run PyArmor to build the project')
    call_pyarmor(['build', '-B', project])

    run_setup_script(src, entry, build, script, packcmd,
                     os.path.abspath(obfdist))

    update_library(obfdist, os.path.join(output, libname))

    copy_runtime_files(obfdist, output)


@logaction
def check_setup_script(_type, setup):
    if os.path.exists(setup):
        return

    logging.info('Please run the following command to generate setup.py')
    if _type == 'py2exe':
        logging.info('\tpython -m py2exe.build_exe -W setup.py hello.py')
    elif _type == 'cx_Freeze':
        logging.info('\tcxfreeze-quickstart')
    else:
        logging.info('\tvi setup.py')
    raise RuntimeError('No setup script %s found' % setup)


def _make_hook_pytransform(hookfile, obfdist, encoding=None):
    # On Mac OS X pyinstaller will call mac_set_relative_dylib_deps to
    # modify .dylib file, it results in the cross protection of pyarmor fails.
    # In order to fix this problem, we need add .dylib as data file
    p = obfdist + os.sep
    lines = ['binaries=[(r"{0}_pytransform*", ".")]']

    if encoding is None:
        with open(hookfile, 'w') as f:
            f.write('\n'.join(lines).format(p))
    else:
        with codecs_open(hookfile, 'w', encoding) as f:
            f.write('\n'.join(lines).format(p))


def _pyi_makespec(hookpath, src, script, packcmd, modname='pytransform'):
    options = ['-p', hookpath, '--hidden-import', modname,
               '--additional-hooks-dir', hookpath, os.path.join(src, script)]
    cmdlist = packcmd + options
    # cmdlist[:4] = ['pyi-makespec']
    cmdlist[:4] = [sys.executable, '-m', 'PyInstaller.utils.cliutils.makespec']
    run_command(cmdlist)


def _guess_encoding(filename):
    with open(filename, 'rb') as f:
        line = f.read(80)
        if line and line[0] == 35:
            n = line.find(b'\n')
            m = re.search(r'coding[=:]\s*([-\w.]+)', line[:n].decode())
            if m:
                return m.group(1)


def _patch_specfile(obfdist, src, specfile, hookpath=None, encoding=None,
                    modname='pytransform'):
    if encoding is None:
        with open(specfile, 'r') as f:
            lines = f.readlines()
    else:
        with codecs_open(specfile, 'r', encoding) as f:
            lines = f.readlines()

    p = os.path.abspath(obfdist)
    patched_lines = (
        "", "# Patched by PyArmor",
        "_src = %s" % repr(os.path.abspath(src)),
        "_obf = 0",
        "for i in range(len(a.scripts)):",
        "    if a.scripts[i][1].startswith(_src):",
        "        x = a.scripts[i][1].replace(_src, r'%s')" % p,
        "        if os.path.exists(x):",
        "            a.scripts[i] = a.scripts[i][0], x, a.scripts[i][2]",
        "            _obf += 1",
        "if _obf == 0:",
        "    raise RuntimeError('No obfuscated script found')",
        "for i in range(len(a.pure)):",
        "    if a.pure[i][1].startswith(_src):",
        "        x = a.pure[i][1].replace(_src, r'%s')" % p,
        "        if os.path.exists(x):",
        "            if hasattr(a.pure, '_code_cache'):",
        "                with open(x) as f:",
        "                    a.pure._code_cache[a.pure[i][0]] = compile(f.read(), a.pure[i][1], 'exec')",
        "            a.pure[i] = a.pure[i][0], x, a.pure[i][2]",
        "# Patch end.", "", "")

    if encoding is not None and sys.version_info[0] == 2:
        patched_lines = [x.decode(encoding) for x in patched_lines]

    for i in range(len(lines)):
        if lines[i].startswith("pyz = PYZ("):
            lines[i:i] = '\n'.join(patched_lines)
            break
    else:
        raise RuntimeError('Unsupport .spec file, no "pyz = PYZ" found')

    if hookpath is not None:
        for k in range(len(lines)):
            if lines[k].startswith('a = Analysis('):
                break
        else:
            raise RuntimeError('Unsupport .spec file, no "a = Analysis" found')
        n = i
        keys = []
        for i in range(k, n):
            if lines[i].lstrip().startswith('pathex='):
                lines[i] = lines[i].replace('pathex=',
                                            'pathex=[r"%s"]+' % hookpath, 1)
                keys.append('pathex')
            elif lines[i].lstrip().startswith('hiddenimports='):
                lines[i] = lines[i].replace('hiddenimports=',
                                            'hiddenimports=["%s"]+' % modname, 1)
                keys.append('hiddenimports')
            elif lines[i].lstrip().startswith('hookspath='):
                lines[i] = lines[i].replace('hookspath=',
                                            'hookspath=[r"%s"]+' % hookpath, 1)
                keys.append('hookspath')
        d = set(['pathex', 'hiddenimports', 'hookspath']) - set(keys)
        if d:
            raise RuntimeError('Unsupport .spec file, no %s found' % list(d))

    patched_file = specfile[:-5] + '-patched.spec'
    if encoding is None:
        with open(patched_file, 'w') as f:
            f.writelines(lines)
    else:
        with codecs_open(patched_file, 'w', encoding) as f:
            f.writelines(lines)

    return os.path.normpath(patched_file)


def _pyinstaller(src, entry, output, options, xoptions, args):
    '''
    Args:
        src: str - (absolute) or (relative to cwd) path for root;
        entry: str - (absolute) or (relative to cwd) path for entry script;
        output: str - (absolute) or (relative to cwd) path for pack output;
        options: List[str] - options for pyinstaller
        xoptions: List[str] - options for obfuscate
        args - cli arguments
    '''
    clean = args.clean
    licfile = args.license_file
    if licfile in ('no', 'outer') or args.no_license:
        licfile = False
    src = relpath(src)
    output = relpath(output)
    obfdist = os.path.join(output, 'obf')
    initcmd = DEFAULT_PACKER['PyInstaller'][2] + [output]
    packcmd = initcmd + options
    script = relpath(entry, start=src)

    if not script.endswith('.py') or not os.path.exists(os.path.join(src, script)):
        raise RuntimeError('No entry script %s found' % script)

    if args.name:
        packcmd.extend(['--name', args.name])
    else:
        args.name = os.path.basename(entry)[:-3]

    specfile = args.setup
    if specfile is None:
        specfile = os.path.join(args.name + '.spec')
        # In Windows, it doesn't work if specpath is not in same drive
        # as entry script
        # if hasattr(args, 'project'):
        #     specpath = args.project
        #     if specpath.endswith('.json'):
        #         specpath = os.path.dirname(specpath)
        #     packcmd.extend(['--specpath', specpath])
        #     specfile = os.path.join(specpath, specfile)
    elif not os.path.exists(specfile):
        raise RuntimeError('No specfile %s found' % specfile)

    logging.info('build path: %s', relpath(obfdist))
    if clean and os.path.exists(obfdist):
        logging.info('Remove build path')
        shutil.rmtree(obfdist)

    logging.info('Run PyArmor to obfuscate scripts...')
    licargs = ['--with-license', licfile] if licfile else \
        ['--with-license', 'outer'] if licfile is False else []
    if hasattr(args, 'project'):
        if xoptions:
            logging.warning('Ignore xoptions as packing project')
        call_pyarmor(['build', '-B', '-O', obfdist, '--package-runtime', '0']
                     + licargs + [args.project])
    else:
        call_pyarmor(['obfuscate', '-O', obfdist, '--package-runtime', '0',
                      '-r', '--exclude', output]
                     + licargs + xoptions + [script])

    obftemp = os.path.join(obfdist, 'temp')
    if not os.path.exists(obftemp):
        logging.info('Create temp path: %s', obftemp)
        os.makedirs(obftemp)
    supermode = True
    runmodname = None
    for x in glob(os.path.join(obfdist, 'pytransform*')):
        nlist = os.path.basename(x).split('.')
        if str(nlist[-1]) in ('py', 'so', 'pyd'):
            logging.info('Found runtime module %s', os.path.basename(x))
            if runmodname is not None:
                raise RuntimeError('Too many runtime module found')
            runmodname = nlist[0]
            supermode = nlist[1] != 'py'
            logging.info('Copy %s to temp path', x)
            shutil.copy(x, obftemp)
    if runmodname is None:
        raise RuntimeError('No runtime module found')

    if args.setup is None:
        logging.info('Run PyInstaller to generate .spec file...')
        _pyi_makespec(obftemp, src, script, packcmd, runmodname)
        if not os.path.exists(specfile):
            raise RuntimeError('No specfile "%s" found', specfile)
        logging.info('Save .spec file to %s', specfile)
        hookpath = None
    else:
        logging.info('Use customized .spec file: %s', specfile)
        hookpath = obftemp

    encoding = _guess_encoding(specfile)

    hookfile = os.path.join(obftemp, 'hook-%s.py' % runmodname)
    logging.info('Generate hook script: %s', hookfile)
    if not supermode:
        _make_hook_pytransform(hookfile, obfdist, encoding)

    logging.info('Patching .spec file...')
    patched_spec = _patch_specfile(obfdist, src, specfile, hookpath,
                                   encoding, runmodname)
    logging.info('Save patched .spec file to %s', patched_spec)

    logging.info('Run PyInstaller with patched .spec file...')
    run_command([sys.executable] + initcmd + ['-y', '--clean', patched_spec])

    if not args.keep:
        if args.setup is None:
            logging.info('Remove .spec file %s', specfile)
            os.remove(specfile)
        logging.info('Remove patched .spec file %s', patched_spec)
        os.remove(patched_spec)
        logging.info('Remove build path %s', obfdist)
        shutil.rmtree(obfdist)


def _get_project_entry(project):
    if project.endswith('.json'):
        filename = project
        path = os.path.dirname(project)
    else:
        path = project
        filename = os.path.join(project, '.pyarmor_config')
    if not os.path.exists(filename):
        raise RuntimeError('No project %s found' % project)
    with open(filename, 'r') as f:
        obj = json_load(f)
        src = obj['src']
        if not src:
            raise RuntimeError('No src in this project %s' % project)
        if not os.path.isabs(src):
            src = os.path.join(path, src)
        if not os.path.exists(src):
            raise RuntimeError('The project src %s does not exists' % project)
        if not obj['entry']:
            raise RuntimeError('No entry in this project %s' % project)
        entry = obj['entry'].split(',')[0]
    return src, entry


def _check_extra_options(options):
    for x in ('-y', '--noconfirm'):
        if x in options:
            options.remove(x)
    for item in options:
        for x in item.split('='):
            if x in ('-n', '--name', '--distpath', '--specpath'):
                raise RuntimeError('The option "%s" could not be used '
                                   'as the extra options' % x)


def _check_entry_script(filename):
    try:
        with open(filename) as f:
            n = 0
            for line in f:
                if (line.startswith('__pyarmor') and
                    line[:100].find('__name__, __file__') > 0) \
                    or line.startswith('pyarmor(__name__, __file__'):
                    return False
                if n > 1:
                    break
                n + 1
    except Exception:
        # Ignore encoding error
        pass


def _get_src_from_xoptions(xoptions):
    if xoptions is None:
        return None

    # src parameter for `obfuscate`
    parser = argparse.ArgumentParser()
    parser.add_argument('-s', '--src', metavar='PATH', default=None)
    args = parser.parse_known_args(xoptions)[0]
    return args.src


def packer(args):
    t = args.type

    xoptions = [] if args.xoptions is None else split(args.xoptions)
    extra_options = [] if args.options is None else split(args.options)
    _check_extra_options(extra_options)

    if args.entry[0].endswith('.py'):
        xoption_src = _get_src_from_xoptions(xoptions)
        src = os.path.abspath(
            os.path.dirname(args.entry[0])
            if xoption_src is None else
            xoption_src
        )
        entry = relpath(args.entry[0])
    else:
        src, entry = _get_project_entry(args.entry[0])
        args.project = args.entry[0]

    if _check_entry_script(os.path.abspath(entry)) is False:
        raise RuntimeError('DO NOT pack the obfuscated script, please '
                           'pack the original script directly')

    if args.setup is None:
        build = src
        script = None
    else:
        build = os.path.abspath(os.path.dirname(args.setup))
        script = os.path.basename(args.setup)

    if args.output is None:
        dist = DEFAULT_PACKER[t][0]
        output = os.path.join(build, dist)
    else:
        output = os.path.abspath(args.output)
    output = os.path.normpath(output)

    logging.info('Prepare to pack obfuscated scripts with %s...', t)
    logging.info('entry script: %s', entry)
    logging.info('src for searching scripts: %s', relpath(src))

    if t == 'PyInstaller':
        _pyinstaller(src, entry, output, extra_options, xoptions, args)
    else:
        logging.warning('Deprecated way, use PyInstaller instead')
        _packer(t, src, entry, build, script, output,
                extra_options, xoptions, args.clean)

    logging.info('Final output path: %s', relpath(output))
    logging.info('Pack obfuscated scripts successfully.')


def add_arguments(parser):
    parser.add_argument('-v', '--version', action='version', version='v0.1')

    parser.add_argument('-t', '--type', default='PyInstaller', metavar='TYPE',
                        choices=DEFAULT_PACKER.keys(), help=argparse.SUPPRESS)
    parser.add_argument('-s', '--setup', metavar='FILE',
                        help='Use external .spec file to pack the script')
    parser.add_argument('-n', '--name', help='Name to assign to the bundled '
                        'app (default: first script’s basename)')
    parser.add_argument('-O', '--output', metavar='PATH',
                        help='Directory to put final built distributions in')
    parser.add_argument('-e', '--options', metavar='EXTRA_OPTIONS',
                        help='Pass these extra options to `pyinstaller`')
    parser.add_argument('-x', '--xoptions', metavar='EXTRA_OPTIONS',
                        help='Pass these extra options to `pyarmor obfuscate`')
    parser.add_argument('--no-license', '--without-license',
                        action='store_true', dest='no_license',
                        help=argparse.SUPPRESS)
    parser.add_argument('--with-license', metavar='FILE', dest='license_file',
                        help='Use this license file other than default one')
    parser.add_argument('--clean', action="store_true",
                        help='Remove cached .spec file before packing')
    parser.add_argument('--keep', '--debug', dest='keep', action="store_true",
                        help='Do not remove build files after packing')
    parser.add_argument('entry', metavar='SCRIPT', nargs=1,
                        help='Entry script or project path')


def main(args):
    parser = argparse.ArgumentParser(
        prog='packer.py',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description='Pack obfuscated scripts',
        epilog=__doc__,
    )
    add_arguments(parser)
    packer(parser.parse_args(args))


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)-8s %(message)s',
    )
    main(sys.argv[1:])
