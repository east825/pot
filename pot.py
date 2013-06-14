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

VERBOSE_MESSAGE_FORMAT = '[%(levelname)s]:%(funcName)s:%(lineno)s %(message)s'
POT_HOME = os.path.expanduser(os.getenv('POT_HOME', '~/.pot'))
# file inclusion format in Bash and other shell-like command interpreters
DEFAULT_INCLUSION_FORMAT = '. {src}'


class RangeFilter(logging.Filter):
    def __init__(self, name='', minlevel=logging.NOTSET, maxlevel=logging.FATAL):
        super(RangeFilter, self).__init__(name)
        self.minlevel = minlevel
        self.maxlevel = maxlevel

    def filter(self, record):
        return self.minlevel <= record.levelno <= self.maxlevel


logger = logging.getLogger('pot')
logger.setLevel(logging.DEBUG)
# disable warning about missing handler
logger.addHandler(logging.NullHandler())
logger.propagate = False

info_handler = logging.StreamHandler(sys.stdout)
info_handler.addFilter(RangeFilter(minlevel=logging.INFO, maxlevel=logging.INFO))
logger.addHandler(info_handler)

error_handler = logging.StreamHandler()
error_handler.setLevel(logging.ERROR)
error_handler.setFormatter(fmt=logging.Formatter('[%(levelname)s] %(message)s'))
logger.addHandler(error_handler)

_quiet_mode = False


def real_dir(path):
    """Check that path refers to real directory, not symlink to it."""
    return not os.path.islink(path) and os.path.isdir(path)


def real_file(path):
    """Check that path refers to real file, not symlink to it."""
    return not os.path.islink(path) and os.path.isfile(path)


def broken_link(path):
    """Check that path refers to broken symbolic link."""
    return os.path.islink(path) and not os.path.exists(path)


def same_file_symlink(dst, src):
    """Check that dst is symlink pointing to dst."""
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
def report_action(description=None, suppress=False):
    if description is not None:
        print(description)
    try:
        yield
    except Exception as e:
        logger.error('Failed: %s', e)
        if not suppress:
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

    def _as_yaml_node(self):
        # It needs to be done manually to preserve order of key-value pairs
        return yaml_map([
            (yaml_scalar('name'), yaml_scalar(self.name)),
            (yaml_scalar('target'), yaml_scalar(self.target)),
            (yaml_scalar('action'), yaml_scalar(self.action))
        ])

    def to_yaml(self, stream=None):
        return yaml.serialize(self._as_yaml_node(), stream)

    def __str__(self):
        # attrs = ' '.join('{}={}'.format(k, v) for k, v in self.__dict__.items())
        return "<DotFile: name={name!r} target={target!r} action={action!r}>".format(**self.__dict__)

    def __repr__(self):
        return self.__str__()

    def __eq__(self, other):
        return self.name == other.name and self.target == other.target and self.action == other.action

    def __hash__(self):
        return hash(self.name) ^ hash(self.target) ^ hash(self.action)


class Config(object):
    """Represents content of 'config.yaml' (dotfiles and settings)."""

    def __init__(self, dotfiles):
        self.dotfiles = dotfiles

    def __str__(self):
        attrs = dict(self.__dict__)
        dotfiles = attrs.pop('dotfiles')
        return '<Config: #dotfiles={}>'.format(len(dotfiles))

    def __repr__(self):
        return self.__str__()

    def _as_yaml_node(self):
        return yaml_map([
            (yaml_scalar('dotfiles'), yaml_seq(map(DotFile._as_yaml_node, self.dotfiles)))
        ])

    @classmethod
    def from_yaml(cls, stream):
        d = yaml.load(stream)
        dotfiles = [DotFile(**df) for df in d.get('dotfiles', [])]
        return cls(dotfiles)

    def to_yaml(self, stream=None):
        return yaml.serialize(self._as_yaml_node(), stream)

    def __eq__(self, other):
        # exact order of dotfiles should not matter
        return set(self.dotfiles) == set(other.dotfiles)


def clone_git_repo(url):
    def check_call(*args):
        subprocess.check_call(args)

    check_call('git', 'clone', url, 'dotfiles')
    with cd('dotfiles'):
        if os.path.exists('.gitmodules'):
            check_call('git', 'submodule', 'init')
            check_call('git', 'submodule', 'update')


def init(path, git_url=None):
    if not os.path.exists(path):
        os.makedirs(path)
    if git_url:
        with report_action('Cloning {}'.format(git_url), suppress=True):
            with cd(path):
                clone_git_repo(git_url)
    with cd(path):
        if not os.path.exists('dotfiles'):
            os.mkdir('dotfiles')
        hidden = os.path.join('dotfiles', '.**')
        dotfiles = [DotFile(name=os.path.basename(f)) for f in glob.glob(hidden)]
        config = Config(dotfiles)
        with open('config.yaml', 'wb') as fd:
            config.to_yaml(stream=fd)


def install(names=None, force=False):
    if not os.path.exists('config.yaml'):
        logger.error('Configuration file not found.')
        return
    with open(os.path.join(os.getcwd(), 'config.yaml')) as cfg:
        config = Config.from_yaml(cfg)
    names_to_dotfiles = {df.name: df for df in config.dotfiles}
    if names is None:
        names = names_to_dotfiles.keys()
    for name in names:
        if name not in names_to_dotfiles:
            logger.error('No such file %s. Check configuration file.', name)
            continue
        dotfile = names_to_dotfiles[name]
        action = dotfile.action
        src = os.path.abspath(os.path.join('dotfiles', dotfile.name))
        if not os.path.exists(src):
            logger.error('Dotfile "%s" doesn\'t exists', src)
            continue
        dst = os.path.expanduser(dotfile.target)
        # os.path.exists(path) returns False for broken symlinks,
        # os.path.lexists does the right thing
        if action in ('symlink', 'copy') and os.path.lexists(dst):
            if force or broken_link(dst) or same_file_symlink(dst, src):
                logger.debug('Removing %s', dst)
                with report_action():
                    # os.path.isdir always follows symlinks
                    if real_dir(dst):
                        shutil.rmtree(dst)
                    else:
                        os.remove(dst)
            else:
                logger.error('File "%s" exists. Delete it manually or use force mode to override it', dst)
                continue
        if action == 'symlink':
            with report_action('Symlinking "{}" -> "{}"'.format(dst, src)):
                os.symlink(src, dst)
        elif action == 'copy':
            with report_action('Copying "{}" as "{}"'.format(src, dst)):
                shutil.copytree(src, dst)
        elif action == 'include':
            inclusion_line = DEFAULT_INCLUSION_FORMAT.format(src=src)
            pattern = re.escape(inclusion_line)
            pattern = r'^\s*{}\s*$'.format(pattern)
            pattern = re.compile(pattern, re.MULTILINE)
            with report_action('Including "{}" in "{}"'.format(src, dst)):
                with open(dst, 'r+') as target:
                    logger.debug('checking for previous inclusion in "%s"...', dst)
                    if pattern.search(target.read()):
                        logger.info('  Skipped: "%s" is already found', inclusion_line)
                        continue
                    logger.debug('Appending "%s" to "%s"', inclusion_line, dst)
                    target.write(inclusion_line + '\n')


def grab(path, force=False):
    logger.debug('using %s as global repo', POT_HOME)
    dotfiles_dir = os.path.join(POT_HOME, 'dotfiles', os.path.basename(path))
    with report_action('Moving "{}" to "{}"'.format(path, dotfiles_dir)):
        filename = os.path.basename(path)
        if os.path.exists(os.path.join(dotfiles_dir, filename)) and not force:
            logger.error('"%" already exists in "%"', filename, dotfiles_dir)
            return
            # move always overwrite its target
        shutil.move(path, dotfiles_dir)
    with report_action('Symlinking "{}" -> "{}"'.format(dotfiles_dir, path)):
        os.symlink(dotfiles_dir, path)


def main():
    parser = argparse.ArgumentParser(prog='pot', description=__doc__)
    parser.add_argument('-v', action='store_true', dest='verbose', help='verbose mode')
    parser.add_argument('-f', '--force', action='store_true', help='overwrite existing files')
    # parser.add_argument('-F', '--fail-fast', action='store_true', help='stop on first error')
    subparsers = parser.add_subparsers()

    # new storage initialization command
    init_command = subparsers.add_parser('init', help='create pot repository and populate default config.yaml')
    init_command.add_argument('location', nargs='?', default='.', help='pot repository')
    init_command.add_argument('--git', metavar='URL', help='git repository URL')
    init_command.set_defaults(func=lambda args: init(args.location, git_url=args.git))

    # dotfile installation command
    install_command = subparsers.add_parser('install', help='install dotfiles in system')
    install_command.add_argument('dotfiles', nargs='*', help='dotfiles names to install')
    install_command.set_defaults(func=lambda args: install(args.dotfiles or None, args.force))

    # dotfile capturing command
    grab_command = subparsers.add_parser('grab', help='move dotfile to repository and symlink it')
    grab_command.add_argument('path', help='path to dotfile')
    grab_command.set_defaults(func=lambda args: grab(args.path, args.force))

    args = parser.parse_args()

    if args.verbose:
        debug_handler = logging.StreamHandler()
        debug_handler.addFilter(RangeFilter(minlevel=logging.DEBUG, maxlevel=logging.DEBUG))
        debug_handler.setFormatter(logging.Formatter(VERBOSE_MESSAGE_FORMAT))
        logger.addHandler(debug_handler)

    try:
        args.func(args)
    except Exception as e:
        logger.error(e)
        sys.exit(1)


if __name__ == '__main__':
    main()
