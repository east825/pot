# vim: fileencoding=utf-8

# Copyright (c) 2013 Mikhail Golubev
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

"""
Mantis is simple command-line utility that helps you to manage your precious dotfiles.
"""

from __future__ import print_function

import argparse
import shutil
import yaml
import glob
import os
from StringIO import StringIO
import logging
import re
import subprocess
import sys
from contextlib import contextmanager


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
console = logging.StreamHandler()
console.setLevel(logging.DEBUG)
console.setFormatter(fmt=logging.Formatter('%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(console)
logger.propagate = False

DEFAULT_INCLUSION_FORMAT = '. {src}'
DEFAULT_REPO = '~/.mantis'


@contextmanager
def cd(path):
    old_cwd = os.getcwd()
    try:
        os.chdir(path)
        logger.debug('Changing cwd to %s', path)
        yield
    finally:
        logger.debug('Changing cwd back to %s', old_cwd)
        os.chdir(old_cwd)


class DotFile(object):
    """Represents single dotfile stored in repo.

    name - name of the dotfile in repository
    target - name of the file in system
    action - action for placing dotfile in system. Can be one of symlink/copy/include.
    """

    def __init__(self, name, target=None, action='symlink'):
        self.name = name
        self.target = os.path.join('~', name) if target is None else target
        self.action = action

    def __str__(self):
        # attrs = ' '.join('{}={}'.format(k, v) for k, v in self.__dict__.items())
        return "<DotFile: name={name!r} target={target!r} action={action!r}>".format(**self.__dict__)


class Config(object):
    def __init__(self, dotfiles, **kwargs):
        self.dotfiles = dotfiles
        self.__dict__.update(kwargs)

    def __str__(self):
        attrs = dict(self.__dict__)
        dotfiles = attrs.pop('dotfiles')
        return '<Config: {} len(dotfiles)={}>'.format(
            ' '.join('{}={}'.format(k, v) for k, v in attrs.items()),
            len(dotfiles))

    @classmethod
    def from_yaml(cls, stream):
        config = yaml.load(stream)
        dotfiles = config.pop('dotfiles')
        dotfiles = [DotFile(**df) for df in dotfiles]
        return cls(dotfiles, **config)

    def to_yaml(self, stream=None):
        if stream is None:
            stringbuf = StringIO()
            self.to_yaml(stringbuf)
            return stringbuf.getvalue()
        else:
            attrs = dict(self.__dict__)
            dotfiles = attrs.pop('dotfiles')
            dotfiles = dict(dotfiles=[d.__dict__ for d in dotfiles])
            yaml.dump(attrs, stream, default_flow_style=False)
            yaml.dump(dotfiles, stream, default_flow_style=False)


def clone_git_dotfiles(url):
    def check_call(*args):
        subprocess.check_call(args)

    check_call('git', 'clone', url, 'dotfiles')
    with cd('dotfiles'):
        if os.path.exists('.gitmodules'):
            check_call('git', 'submodule', 'init')
            check_call('git', 'submodule', 'update')


def initialize_storage(args):
    if not os.path.exists(args.location):
        os.makedirs(args.location)
    if args.git:
        print('Cloning {}'.format(args.git))
        try:
            with cd(args.location):
                clone_git_dotfiles(args.git)
        except subprocess.CalledProcessError:
            print('Can\'t clone and initialize git repo properly', file=sys.stderr)
            return
    dotfiles_pattern = os.path.join(args.location, 'dotfiles', '.**')
    # for name in os.listdir(os.path.join(args.location, 'dotfiles')):
    #     print(name)
    dotfiles = [DotFile(name=os.path.basename(f)) for f in glob.iglob(dotfiles_pattern)]
    config = Config(dotfiles, foo='bar')
    logger.debug('New config:\n%s', config)
    with open(os.path.join(args.location, 'config.yaml'), 'wb') as fd:
        config.to_yaml(stream=fd)


def install_dotfiles(args):
    with open(os.path.join(args.location, 'config.yaml')) as fd:
        config = Config.from_yaml(fd)
    for dotfile in config.dotfiles:
        action = dotfile.action
        src = os.path.abspath(os.path.join('dotfiles', dotfile.name))
        logger.debug('src: %s', src)
        if not os.path.exists(src):
            print("Dotfile {!r} doesn't exists. Check your configuration.".format(src), file=sys.stderr)
            continue
        dst = os.path.expanduser(dotfile.target)
        logger.debug('dst: %s', dst)
        if action in ('symlink', 'copy') and os.path.exists(dst):
            # symlinks are always deleted, other files only if force flag was set
            if args.force or os.path.islink(dst):
                try:
                    # os.path.isdir always follows symlinks
                    if os.path.isdir(dst) and not os.path.islink(dst):
                        shutil.rmtree(dst)
                    else:
                        os.remove(dst)
                except OSError as e:
                    print("Can't delete {!r}: {}".format(e.filename, e.strerror), file=sys.stderr)
                    continue
            else:
                print('File {} exists. Delete it manually or use force mode to override it'.format(dst),
                      file=sys.stderr)
                continue
        if action == 'symlink':
            print('Symlinking {} -> {}'.format(src, dst))
            os.symlink(src, dst)
        elif action == 'copy':
            print('Copying {} -> {}'.format(src, dst))
            shutil.copy(src, dst)
        elif action == 'include':
            inclusion_smt = DEFAULT_INCLUSION_FORMAT.format(src=src)
            pattern = re.escape(inclusion_smt)
            pattern = r'^\s*{}\s*$'.format(pattern)
            logger.debug('Inclusion pattern %s', pattern)
            pattern = re.compile(pattern, re.MULTILINE)
            try:
                with open(dst, 'r+') as target:
                    print('Checking for previous inclusion in {!r}...'.format(dst), end=' ')
                    if pattern.search(target.read()):
                        print('Found. Skipping')
                        continue
                    print('Not found')
                    print('Appending {smt!r} to {target}'.format(smt=inclusion_smt, target=dst))
                    target.write(inclusion_smt + '\n')
            except IOError as e:
                print("Can't read/write target {!r}: {}".format(e.filename, e.strerror), file=sys.stderr)


def grab_dotfile(args):
    mantis_repo = os.path.expanduser(os.getenv('MANTIS_HOME', DEFAULT_REPO))
    logger.debug('Using %s as global repo', mantis_repo)
    dst_path = os.path.join(mantis_repo, 'dotfiles', os.path.basename(args.path))
    print('Moving {src} to {dst}'.format(src=args.path, dst=dst_path))
    try:
        shutil.move(args.path, dst_path)
    except EnvironmentError as e:
        print("Can't move {src} -> {dst}: {strerr}".format(src=args.path, dst=dst_path, strerr=e.strerror),
              file=sys.stderr)
        return
    print('Symlinking {} -> {}'.format(dst_path, args.path))
    try:
        os.symlink(dst_path, args.path)
    except OSError as e:
        print("Can't create symlink: {}".format(e.strerror), file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(prog='mantis', description=__doc__)
    parser.add_argument('-v', action='count', dest='verbosity', help='verbosity level')
    parser.add_argument('-f', '--force', action='store_true', help='overwrite existing files')
    subparsers = parser.add_subparsers()

    # new storage initialization command
    init_command = subparsers.add_parser('init', help='create mantis repository and populate default config.yaml')
    init_command.add_argument('location', nargs='?', default='.', help='mantis repository')
    init_command.add_argument('--git', metavar='URL', help='git repository URL')
    init_command.set_defaults(func=initialize_storage)

    # dotfile installation command
    install_command = subparsers.add_parser('install', help='install dotfiles in system')
    install_command.add_argument('location', nargs='?', default='.', help='mantis repository')
    install_command.set_defaults(func=install_dotfiles)

    # dotfile capturing command
    grab_command = subparsers.add_parser('grab', help='move dotfile to repository and symlink it')
    grab_command.add_argument('path', help='path to dotfile')
    grab_command.set_defaults(func=grab_dotfile)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
