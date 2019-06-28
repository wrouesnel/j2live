#!/usr/bin/env python

import os
import sys

from distutils.core import setup

name = "j2live"

rootdir = os.path.abspath(os.path.dirname(__file__))

# Restructured text project description read from file
long_description = open(os.path.join(rootdir, 'README.md')).read()

# Python 2.4 or later needed
if sys.version_info < (3, 6, 0, 'final', 0):
    raise SystemExit('Python 3.6 or later is required!')

# Build a list of all project modules
packages = []
for dirname, dirnames, filenames in os.walk(name):
        if '__init__.py' in filenames:
            packages.append(dirname.replace('/', '.'))

package_dir = {name: name}

exec(open(os.path.join(name, 'version.py')).read())

setup(name=name,
      version=version,  # PEP440
      description='j2live - Ansible/Jinja2 Gtk live templating',
      long_description=long_description,
      url='https://github.com/wrouesnel/j2live',
      author='Will Rouesnel',
      author_email='wrouesnel@wrouesnel.com',
      license='ASL',
      # https://pypi.python.org/pypi?%3Aaction=list_classifiers
      classifiers=[
          'Development Status :: 1 - Planning',
          'Environment :: Console',
          'License :: OSI Approved :: Apache Software License',
          'Natural Language :: English',
          'Operating System :: OS Independent',
          'Programming Language :: Python :: 3',
          'Programming Language :: Python :: 3.6',
      ],
      keywords='jinja2 ansible commandline',
      packages=packages,
      package_dir=package_dir,
      entry_points = {
          "console_scripts" : [
              "j2live = j2live.__main__"
          ]
      }
    #   package_data=package_data,
    #   scripts=scripts,
    #   data_files=data_files,
      )