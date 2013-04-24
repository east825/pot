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
Pot is simple command-line utility that helps you to manage your precious dotfiles.
"""

from __future__ import print_function
import argparse
import shutil
import glob
import logging
import subprocess
import sys
from contextlib import contextmanager

import yaml
import os
import re


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
# logger.addHandler(logging.NullHandler)
logger.propagate = False

DEFAULT_INCLUSION_FORMAT = '. {src}'
DEFAULT_REPO = '~/.pot'

_quit_mode = False

def real_dir(path):
    return not os.path.islink(path) and os.path.isdir(path)


def broken_link(path):
    return os.path.islink(path) and not os.path.exists(path)


def link_to_same_file(dst, src):
    return os.path.islink(dst) and os.path.exists(dst) and os.path.samefile(src, dst)


def yaml_scalar(value):
    return yaml.ScalarNode(tag='tag:yaml.org,2002:str', value=value)


def yaml_map(items):
    return yaml.MappingNode(tag='tag:yaml.org,2002:map', value=items)


def yaml_seq(elems):
    return yaml.SequenceNode(tag='tag:yaml.org,2002:seq', value=elems)


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


@contextmanager
def reporting(msg, error_msg=None, exc_type=EnvironmentError, failfast=False):
    if not error_msg:
        error_msg = '"{}" failed'.format(msg)
    if not _quit_mode:
        print(msg)
    try:
        yield
    except Exception as e:
        logger.error('{}: {}'.format(error_msg, e))
        if not isinstance(e, exc_type) or failfast:
            raise


class DotFile(object):
    """Represents single dotfile stored in repo.

    name   - name of the dotfile in repository
    target - name of the file in system
    action - action for placing dotfile in system. Can be one of symlink/copy/include.
    """

    def __init__(self, name, target=None, action='symlink'):
        self.name = name
        self.target = os.path.join('~', name) if target is None else target
        self.action = action

    def as_yaml_node(self):
        # It needs to be done manually to preserve order of key-value pairs
        return yaml_map([
            (yaml_scalar('name'), yaml_scalar(self.name)),
            (yaml_scalar('target'), yaml_scalar(self.target)),
            (yaml_scalar('action'), yaml_scalar(self.action))
        ])

    def to_yaml(self, stream=None):
        return yaml.serialize(self.as_yaml_node(), stream)

    def __str__(self):
        # attrs = ' '.join('{}={}'.format(k, v) for k, v in self.__dict__.items())
        return "<DotFile: name={name!r} target={target!r} action={action!r}>".format(**self.__dict__)


class Config(object):
    """Represents content of 'config.yaml' (dotfiles and settings)"""

    def __init__(self, dotfiles, **kwargs):
        self.dotfiles = dotfiles
        self.__dict__.update(kwargs)

    def __str__(self):
        attrs = dict(self.__dict__)
        dotfiles = attrs.pop('dotfiles')
        return '<Config: {} len(dotfiles)={}>'.format(
            ' '.join('{}={}'.format(k, v) for k, v in attrs.items()),
            len(dotfiles))

    def as_yaml_node(self):
        attrs = dict(self.__dict__)
        dotfiles = attrs.pop('dotfiles')
        return yaml_map(
            [(yaml_scalar(name), yaml_scalar(str(value))) for name, value in attrs.items()] +
            [(yaml_scalar('dotfiles'), yaml_seq([d.as_yaml_node() for d in dotfiles]))],
        )

    @classmethod
    def from_yaml(cls, stream):
        config = yaml.load(stream)
        dotfiles = config.pop('dotfiles')
        dotfiles = [DotFile(**df) for df in dotfiles]
        return cls(dotfiles, **config)

    def to_yaml(self, stream=None):
        return yaml.serialize(self.as_yaml_node(), stream)


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
        with reporting('Cloning {}'.format(args.git), failfast=True):
            with cd(args.location):
                clone_git_dotfiles(args.git)
    with cd(args.location):
        if not os.path.exists('dotfiles'):
            logging.debug('Creating dotfiles directory')
            os.mkdir('dotfiles')
        hidden = os.path.join('dotfiles', '.**')
        dotfiles = [DotFile(name=os.path.basename(f)) for f in glob.iglob(hidden)]
        config = Config(dotfiles)
        logger.debug('New config:\n%s', config)
        with open('config.yaml', 'wb') as cfg:
            config.to_yaml(stream=cfg)


def install_dotfiles(args):
    with open(os.path.join(args.location, 'config.yaml')) as cfg:
        config = Config.from_yaml(cfg)
    for dotfile in config.dotfiles:
        action = dotfile.action
        src = os.path.abspath(os.path.join('dotfiles', dotfile.name))
        logger.debug('src: %s', src)
        if not os.path.exists(src):
            print("Dotfile {!r} doesn't exists. Check your configuration.".format(src), file=sys.stderr)
            if args.failfast:
                return
            continue
        dst = os.path.expanduser(dotfile.target)
        logger.debug('dst: %s', dst)
        # os.path.exists(path) returns False for broken symlinks,
        # os.path.lexists does the right thing
        if action in ('symlink', 'copy') and os.path.lexists(dst):
            # symlinks are always deleted, other files only if force flag was set
            if args.force or broken_link(dst) or link_to_same_file(src, dst):
                with reporting('Removing {}'.format(dst), failfast=args.failfast):
                    # os.path.isdir always follows symlinks
                    if real_dir(dst):
                        shutil.rmtree(dst)
                    else:
                        os.remove(dst)
            else:
                print('File "{}" exists. Delete it manually or use force mode to override it'.format(dst),
                      file=sys.stderr)
                if args.failfast:
                    return
                continue
        if action == 'symlink':
            with reporting('Symlinking "{}" -> "{}"'.format(src, dst)):
                os.symlink(src, dst)
        elif action == 'copy':
            with reporting('Copying "{}" -> "{}"'.format(src, dst)):
                shutil.copy(src, dst)
        elif action == 'include':
            inclusion_smt = DEFAULT_INCLUSION_FORMAT.format(src=src)
            pattern = re.escape(inclusion_smt)
            pattern = r'^\s*{}\s*$'.format(pattern)
            logger.debug('Inclusion pattern %s', pattern)
            pattern = re.compile(pattern, re.MULTILINE)
            with reporting('Including "{}" in "{}"'.format(src, dst), failfast=args.failfast):
                with open(dst, 'r+') as target:
                    print('Checking for previous inclusion in "{}"...'.format(dst), end=' ')
                    if pattern.search(target.read()):
                        print('Found. Skipping')
                        continue
                    print('Not found')
                    print('Appending {smt!r} to {target}'.format(smt=inclusion_smt, target=dst))
                    target.write(inclusion_smt + '\n')


def grab_dotfile(args):
    pot_repo = os.path.expanduser(os.getenv('POT_HOME', DEFAULT_REPO))
    logger.debug('Using %s as global repo', pot_repo)
    dst_path = os.path.join(pot_repo, 'dotfiles', os.path.basename(args.path))
    with reporting('Moving {} to {}'.format(args.path, dst_path), failfast=True):
        # move always overwrite its target
        shutil.move(args.path, dst_path)
    with reporting('Symlinking {} -> {}'.format(dst_path, args.path), failfast=True):
        os.symlink(dst_path, args.path)


def main():
    parser = argparse.ArgumentParser(prog='pot', description=__doc__)
    parser.add_argument('-v', action='count', dest='verbosity', help='verbosity level')
    parser.add_argument('-f', '--force', action='store_true', help='overwrite existing files')
    parser.add_argument('-F', '--fail-fast', action='store_true', help='stop on first error')
    subparsers = parser.add_subparsers()

    # new storage initialization command
    init_command = subparsers.add_parser('init', help='create pot repository and populate default config.yaml')
    init_command.add_argument('location', nargs='?', default='.', help='pot repository')
    init_command.add_argument('--git', metavar='URL', help='git repository URL')
    init_command.set_defaults(func=initialize_storage)

    # dotfile installation command
    install_command = subparsers.add_parser('install', help='install dotfiles in system')
    install_command.add_argument('location', nargs='?', default='.', help='pot repository')
    install_command.set_defaults(func=install_dotfiles)

    # dotfile capturing command
    grab_command = subparsers.add_parser('grab', help='move dotfile to repository and symlink it')
    grab_command.add_argument('path', help='path to dotfile')
    grab_command.set_defaults(func=grab_dotfile)

    args = parser.parse_args()

    console = logging.StreamHandler()
    if not args.verbosity:
        global _quit_mode
        _quit_mode = True
    if args.verbosity < 2:
        console.setLevel(logging.ERROR)
        console.setFormatter(fmt=logging.Formatter('%(message)s'))
    else:
        console.setLevel(logging.DEBUG)
        console.setFormatter(fmt=logging.Formatter('%(levelname)s:%(name)s: %(message)s'))
    logger.addHandler(console)

    try:
        args.func(args)
    except Exception as e:
        if args.verbosity > 1:
            logging.exception(e)
        sys.exit(1)


if __name__ == '__main__':
    main()
