import re
import os
import subprocess
from pathlib import Path

from aura import config
from aura.analyzers.python import visitor


def test_basic_ast(fixtures):
    pth = fixtures.path('basic_ast.py')
    data = visitor.get_ast_tree(pth)

    assert data['implementation'] == 'CPython'
    assert data['ast_tree']['_type'] == 'Module'
    assert isinstance(data['ast_tree']['body'], list)
    assert len(data['ast_tree']['body']) == 9  # Top level lines with python code


def test_interpreters():
    args = ['-c', 'import sys; print(sys.version)']
    py2 = config.CFG.get('interpreters', 'python2')
    py2_version = subprocess.check_output([py2] + args).decode().strip().split()[0]
    assert re.match(r'^2\.7\.\d+$', py2_version)

    py3 = config.CFG.get('interpreters', 'python3')
    py3_version = subprocess.check_output([py3] + args).decode().strip().split()[0]
    assert re.match(r'^3\.(6|7)\.\d+$', py3_version)


def test_py2k(fixtures):
    pth = fixtures.path('py2k.py')
    data = visitor.get_ast_tree(pth)

    assert isinstance(data, dict)
