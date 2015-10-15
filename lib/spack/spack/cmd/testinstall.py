##############################################################################
# Copyright (c) 2013, Lawrence Livermore National Security, LLC.
# Produced at the Lawrence Livermore National Laboratory.
#
# This file is part of Spack.
# Written by Todd Gamblin, tgamblin@llnl.gov, All rights reserved.
# LLNL-CODE-647188
#
# For details, see https://scalability-llnl.github.io/spack
# Please also see the LICENSE file for our notice and the LGPL.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License (as published by
# the Free Software Foundation) version 2.1 dated February 1999.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the IMPLIED WARRANTY OF
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the terms and
# conditions of the GNU General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 59 Temple Place, Suite 330, Boston, MA 02111-1307 USA
##############################################################################
from external import argparse
import xml.etree.ElementTree as ET
import itertools

import llnl.util.tty as tty
from llnl.util.filesystem import *

import spack
import spack.cmd

description = "Build and install packages"

def setup_parser(subparser):
    #subparser.add_argument(
    #    '-i', '--ignore-dependencies', action='store_true', dest='ignore_deps',
    #    help="Do not try to install dependencies of requested packages.")
    
    subparser.add_argument(
        '-j', '--jobs', action='store', type=int,
        help="Explicitly set number of make jobs.  Default is #cpus.")
        
    #always false for test
    #subparser.add_argument(
    #    '--keep-prefix', action='store_true', dest='keep_prefix',
    #    help="Don't remove the install prefix if installation fails.")
    
    #always true for test
    #subparser.add_argument(
    #    '--keep-stage', action='store_true', dest='keep_stage',
    #    help="Don't remove the build stage if installation succeeds.")
    
    subparser.add_argument(
        '-n', '--no-checksum', action='store_true', dest='no_checksum',
        help="Do not check packages against checksum")
    subparser.add_argument(
        '-v', '--verbose', action='store_true', dest='verbose',
        help="Display verbose build output while installing.")
    
    #subparser.add_argument(
    #    '--fake', action='store_true', dest='fake',
    #    help="Fake install.  Just remove the prefix and touch a fake file in it.")
    
    subparser.add_argument(
        'output', help="test output goes in this file")
    
    subparser.add_argument(
        'package', help="spec of package to install")


class JunitResultFormat(object):
    def __init__(self):
        self.root = ET.Element('testsuite')
        self.tests = []
        
    def addTest(self, buildId, passed=True, buildInfo=None):
        self.tests.append((buildId, passed, buildInfo))
    
    def writeTo(self, stream):
        self.root.set('tests', '{0}'.format(len(self.tests)))
        for buildId, passed, buildInfo in self.tests:
            testcase = ET.SubElement(self.root, 'testcase')
            testcase.set('classname', buildId.name)
            testcase.set('name', buildId.stringId())
            if not passed:
                failure = ET.SubElement(testcase, 'failure')
                failure.set('type', "Build Error")
                failure.text = buildInfo
        ET.ElementTree(self.root).write(stream)


class BuildId(object):
    def __init__(self, name, version, hashId):
        self.name = name
        self.version = version
        self.hashId = hashId
    
    def stringId(self):
        return "-".join(str(x) for x in (self.name, self.version, self.hashId))


def createTestOutput(spec, handled, output):
    if spec in handled:
        return handled[spec]
    
    childSuccesses = list(createTestOutput(dep, handled, output) 
            for dep in spec.dependencies.itervalues())
    package = spack.db.get(spec)
    handled[spec] = package.installed
    
    if all(childSuccesses):
        bId = BuildId(spec.name, spec.version, spec.dag_hash())

        if package.installed:
            buildLogPath = spack.install_layout.build_log_path(spec)
        else:
            #TODO: search recursively under stage.path instead of only within
            #    stage.source_path
            buildLogPath = join_path(package.stage.source_path, 'spack-build.out')            

        with open(buildLogPath, 'rb') as F:
            buildLog = F.read() #TODO: this may not return all output
            #TODO: add the whole build log? it could be several thousand
            #    lines. It may be better to look for errors.
            output.addTest(bId, package.installed, buildLogPath + '\n' +
                spec.to_yaml() + buildLog)
    #TODO: create a failed test if a dependency didn't install?

    return handled[spec]


def testinstall(parser, args):
    if not args.package:
        tty.die("install requires a package argument")

    if args.jobs is not None:
        if args.jobs <= 0:
            tty.die("The -j option must be a positive integer!")

    if args.no_checksum:
        spack.do_checksum = False        # TODO: remove this global.

    #TODO: should a single argument be wrapped in a list?
    specs = spack.cmd.parse_specs(args.package, concretize=True)
    newInstalls = set()
    for spec in itertools.chain.from_iterable(spec.traverse() 
            for spec in specs):
        package = spack.db.get(spec)
        if not package.installed:
            newInstalls.add(spec)
    
    try:
        for spec in specs:
            package = spack.db.get(spec)
            if not package.installed:
                package.do_install(
                    keep_prefix=False,
                    keep_stage=False,
                    ignore_deps=False,
                    make_jobs=args.jobs,
                    verbose=args.verbose,
                    fake=False)
    finally:        
        #Find all packages that are not a dependency of another package
        topLevelNewInstalls = newInstalls - set(itertools.chain.from_iterable(
                spec.dependencies for spec in newInstalls))
        
        jrf = JunitResultFormat()
        handled = {}
        for spec in topLevelNewInstalls:
            createTestOutput(spec, handled, jrf)

        with open(args.output, 'wb') as F:
            jrf.writeTo(F)
