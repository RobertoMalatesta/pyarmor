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
#   Pack obfuscated Python scripts with any of third party
#   tools: py2exe, py2app, cx_Freeze
#

'''Pack obfuscated scripts to one bundle, distribute the
bundle as a folder or file to other people, and they can
execute your program without Python installed.

The prefer way is

    pip install pyinstaller
    cd /path/to/src
    parmor pack hello.py

'''

import logging
import os
import shutil
import subprocess
import sys

from distutils.util import get_platform
from glob import glob
from py_compile import compile as compile_file
from shlex import split
from zipfile import PyZipFile

try:
    import argparse
except ImportError:
    # argparse is new in version 2.7
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
        logging.info('')
        logging.info('%s', func.__name__)
        return func(*args, **kwargs)
    return wrap


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
def run_setup_script(src, entry, build, script, packcmd, obfdist):
    '''Update entry script, copy pytransform.py to source path, then run
setup script to build the bundle.

    '''
    obf_entry = os.path.join(obfdist, entry)

    tempfile = '%s.armor.bak' % entry
    shutil.move(os.path.join(src, entry), tempfile)
    shutil.move(obf_entry, src)
    shutil.copy('pytransform.py', src)

    p = subprocess.Popen([sys.executable, script] + packcmd, cwd=build,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    stdoutdata, _ = p.communicate()

    shutil.move(tempfile, os.path.join(src, entry))
    os.remove(os.path.join(src, 'pytransform.py'))

    if p.returncode != 0:
        logging.error('\n\n%s\n\n', stdoutdata.decode())
        raise RuntimeError('Run setup script failed')


@logaction
def copy_runtime_files(runtimes, output):
    for s in glob(os.path.join(runtimes, '*.key')):
        shutil.copy(s, output)
    for s in glob(os.path.join(runtimes, '*.lic')):
        shutil.copy(s, output)
    for dllname in glob(os.path.join(runtimes, '_pytransform.*')):
        shutil.copy(dllname, output)


def call_armor(args):
    logging.info('')
    logging.info('')
    s = os.path.join(os.path.dirname(__file__), 'pyarmor.py')
    p = subprocess.Popen([sys.executable, s] + list(args))
    p.wait()
    if p.returncode != 0:
        raise RuntimeError('Call pyarmor failed')


def pathwrapper(func):
    def wrap(*args, **kwargs):
        oldpath = os.getcwd()
        os.chdir(os.path.abspath(os.path.dirname(__file__)))
        logging.info('Change path to %s', os.getcwd())
        try:
            return func(*args, **kwargs)
        finally:
            os.chdir(oldpath)
    return wrap


def _packer(src, entry, build, script, packcmd, output, libname,
            xoptions, clean=False):
    project = os.path.join(build, 'obf')
    obfdist = os.path.join(project, 'dist')

    logging.info('Build path: %s', project)
    logging.info('Obfuscated scrips output path: %s', obfdist)
    if clean and os.path.exists(project):
        logging.info('Clean build path %s', project)
        shutil.rmtree(project)

    args = 'init', '-t', 'app', '--src', src, '--entry', entry, project
    call_armor(args)

    filters = ('global-include *.py', 'prune build, prune dist',
               'exclude %s pytransform.py' % entry)
    args = ('config', '--runtime-path', '',
            '--manifest', ','.join(filters), project)
    call_armor(args)

    if xoptions:
        args = ['config'] + list(xoptions) + [project]
        call_armor(args)

    args = 'build', project
    call_armor(args)

    run_setup_script(src, entry, build, script, packcmd, obfdist)

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
    raise RuntimeError('No setup script %s found', setup)


@logaction
def run_pyi_makespec(project, obfdist, src, entry, packcmd):
    s = os.pathsep
    d = os.path.relpath(obfdist, project)
    datas = [
        '--add-data', '%s%s.' % (os.path.join(d, '*.lic'), s),
        '--add-data', '%s%s.' % (os.path.join(d, '*.key'), s),
        '--add-data', '%s%s.' % (os.path.join(d, '_pytransform.*'), s)
    ]
    scripts = [os.path.join(src, entry)]

    options = ['-y']
    options.extend(datas)
    options.extend(scripts)

    p = subprocess.Popen([sys.executable] + packcmd + options,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    stdoutdata, _ = p.communicate()

    if p.returncode != 0:
        logging.error('\n\n%s\n\n', stdoutdata.decode())
        raise RuntimeError('Make specfile failed')


@logaction
def update_specfile(project, obfdist, src, entry, specfile):
    with open(specfile) as f:
        lines = f.readlines()

    patched_lines = (
        "", "# Patched by PyArmor",
        "a.scripts[-1] = '%s', r'%s', 'PYSOURCE'" % (
            entry[:-3], os.path.join(obfdist, entry)),
        "for i in range(len(a.pure)):",
        "    if a.pure[i][1].startswith(a.pathex[0]):",
        "        a.pure[i] = a.pure[i][0], a.pure[i][1].replace("
        "a.pathex[0], r'%s'), a.pure[i][2]" % os.path.abspath(obfdist),
        "# Patch end.", "", "")

    for i in range(len(lines)):
        if lines[i].startswith("pyz = PYZ(a.pure"):
            break
    else:
        raise RuntimeError('Unsupport specfile, no PYZ line found')
    lines[i:i] = '\n'.join(patched_lines)

    patched_file = specfile[:-5] + '-patched.spec'
    with open(patched_file, 'w') as f:
        f.writelines(lines)

    return os.path.normpath(patched_file)


@logaction
def run_pyinstaller(project, src, entry, specfile, packcmd):
    p = subprocess.Popen(
        [sys.executable] + packcmd + ['-y', specfile],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    stdoutdata, _ = p.communicate()

    if p.returncode != 0:
        logging.error('\n\n%s\n\n', stdoutdata.decode())
        raise RuntimeError('Run pyinstller failed')


def _pyinstaller(src, entry, packcmd, output, specfile, xoptions, clean=False):
    project = os.path.join(output, 'obf')
    obfdist = os.path.join(project, 'dist')
    if specfile is None:
        specfile = os.path.join(src, os.path.basename(entry)[:-3] + '.spec')

    logging.info('spec file: %s', specfile)
    logging.info('Build path: %s', project)
    logging.info('Obfuscated scrips output path: %s', obfdist)
    if clean and os.path.exists(project):
        logging.info('Clean build path %s', project)
        shutil.rmtree(project)

    args = ['obfuscate', '-r', '-O', obfdist] + xoptions
    call_armor(args + [os.path.join(src, entry)])

    if not os.path.exists(specfile):
        run_pyi_makespec(project, obfdist, src, entry, packcmd)

    patched_spec = update_specfile(project, obfdist, src, entry, specfile)

    run_pyinstaller(project, src, entry, patched_spec, packcmd)


def packer(args):
    t = args.type
    src = os.path.abspath(os.path.dirname(args.entry[0]))
    entry = os.path.basename(args.entry[0])
    extra_options = [] if args.options is None else split(args.options)
    xoptions = [] if args.xoptions is None else split(args.xoptions)

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
        output = args.output if os.path.isabs(args.output) \
            else os.path.join(build, args.output)
    output = os.path.normpath(output)

    libname = DEFAULT_PACKER[t][1]
    packcmd = DEFAULT_PACKER[t][2] + [output] + extra_options

    logging.info('Prepare to pack obfuscated scripts with %s', t)
    logging.info('src for scripts: %s', src)
    logging.info('output path: %s', output)

    if t == 'PyInstaller':
        _pyinstaller(src, entry, packcmd, output, script,
                     xoptions, args.clean)
    else:
        script = 'setup.py' if script is None else script
        check_setup_script(t, os.path.join(build, script))
        _packer(src, entry, build, script, packcmd, output, libname,
                xoptions, args.clean)

    logging.info('')
    logging.info('Pack obfuscated scripts successfully in the path')
    logging.info('')
    logging.info('\t%s', output)


def add_arguments(parser):
    parser.add_argument('-v', '--version', action='version', version='v0.1')

    parser.add_argument('-t', '--type', default='PyInstaller', metavar='TYPE',
                        choices=DEFAULT_PACKER.keys(),
                        help=', '.join(DEFAULT_PACKER.keys()))
    parser.add_argument('-s', '--setup', help=argparse.SUPPRESS)
    parser.add_argument('-O', '--output',
                        help='Directory to put final built distributions in')
    parser.add_argument('-e', '--options',
                        help='Extra options to run pack command')
    parser.add_argument('-x', '--xoptions',
                        help='Extra options to obfuscate scripts')
    parser.add_argument('--clean', action="store_true",
                        help='Remove build path before packing')
    parser.add_argument('entry', metavar='SCRIPT', nargs=1,
                        help='Entry script')


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
    try:
        main(sys.argv[1:])
    except Exception as e:
        if sys.flags.debug:
            raise
        print(e)
        sys.exit(1)
