#!/usr/bin/python2
# This Python file uses the following encoding: utf-8

# Copyright (C) 2011-2017 Richard Alpe <rical@highwind.se>
#
# This file is part of 9pm.
#
# 9pm is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# 9pm is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

import argparse
import os
import yaml
import subprocess
import sys
import time
import pprint
import tempfile
import shutil
import re

TEST_CNT=0
ROOT_PATH = os.path.dirname(os.path.realpath(__file__))
# TODO: proper argument strucutre
DATABASE = ""

if "TCLLIBPATH" in os.environ:
    os.environ["TCLLIBPATH"] = os.environ["TCLLIBPATH"] + " " + ROOT_PATH
else:
    os.environ["TCLLIBPATH"] = ROOT_PATH

class pcolor:
    purple = '\033[95m'
    blue = '\033[94m'
    green = '\033[92m'
    yellow = '\033[93m'
    red = '\033[91m'
    reset = '\033[0m'

def run_test(cmdline, test):
    args = ["-t"]

    if cmdline.debug:
        args.append("-d")

    args.extend(["-b", DATABASE])


    if cmdline.config:
        args.extend(["-c", cmdline.config])

    if 'options' in test:
        args.extend(test['options'])
    args.extend(cmdline.option)

    print pcolor.blue + "\nStarting test", test['name'] + pcolor.reset
    if cmdline.debug:
        print "Executing:", [test['case']] + args
    proc = subprocess.Popen([test['case']] + args, stdout=subprocess.PIPE)
    err = False

    while True:
        line = proc.stdout.readline()
        if line == '':
            break

        string = line.rstrip()
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")

        plan = re.search('^(\d+)..(\d+)$', string)
        ok = re.search('^ok (\d+) -', string)
        not_ok = re.search('^not ok (\d+) -', string)

        if plan:
            print pcolor.purple + stamp, string +  pcolor.reset
            test['plan'] = plan.group(2)
        elif ok:
            print pcolor.green + stamp, string +  pcolor.reset
            test['executed'] = ok.group(1)
        elif not_ok:
            print pcolor.red + stamp, string +  pcolor.reset
            err = True
            test['executed'] = not_ok.group(1)
        else:
            print stamp, string

        if (ok or not_ok) and not 'plan' in test:
            print "test error, test started before plan"
            err = True

    out, error = proc.communicate()
    exitcode = proc.returncode

    if exitcode != 0:
        err = True
    elif test['plan'] != test['executed']:
        print "test error, not conforming to plan (" + test['executed'] + "/" + test['plan'] + ")"
        err = True

    return err

# In this function, we generate an unique name for each case and suite. Both
# suites and cases can be passed an arbitrary amount of times and the same test
# can reside in different suites. We need something unique to identify them by.
def prefix_name(name):
    global TEST_CNT
    TEST_CNT += 1
    return str(TEST_CNT).zfill(4) + "-" + name

def gen_name(filename):
    return prefix_name(os.path.basename(filename))

def parse_yaml(path):
    with open(path, 'r') as stream:
        try:
            data = yaml.load(stream)
        except yaml.YAMLError as exc:
            print(exc)
            return -1
    return data

def parse(fpath):
    suite = {}
    suite['fpath'] = fpath
    suite['name'] = gen_name(fpath)
    suite['suite'] = []
    suite['result'] = "pending"
    cur = os.path.dirname(fpath)

    data = parse_yaml(fpath)
    for entry in data:
        if 'suite' in entry:
            fpath = os.path.join(cur, entry['suite'])
            suite['suite'].append(parse(fpath))
        elif 'case' in entry:
            case = {}

            if 'name' in entry:
                name = entry['name']
            else:
                name = os.path.basename(entry['case'])

            if 'opts' in entry:
                case['options'] = [o.replace('<base>', cur) for o in entry['opts']]

            case['case'] = os.path.join(cur, entry['case'])
            case['name'] = prefix_name(name)
            suite['suite'].append(case)
        else:
            print "error, missing suite/case in suite", suite['name']
            sys.exit(1)
    return suite

def print_tree(data, base, depth):
    i = 1
    llen = len(data['suite'])

    for test in data['suite']:
        if i < llen:
            prefix = "├── "
            nextbase = base + "│   "
        else:
            prefix = "└── "
            nextbase = base + "    "

        if test['result'] == "pass":
            sign = "✓"
            color = pcolor.green
        else:
            sign = "✗"
            color = pcolor.red

        print base + prefix + color + sign, test['name'] + pcolor.reset

        if 'suite' in test:
            print_tree(test, nextbase, depth + 1)
        i += 1

def run_suite(cmdline, data, depth):
    err = False

    for test in data['suite']:
        if 'suite' in test:
            if run_suite(cmdline, test, depth + 2):
                err = True

        elif 'case' in test:
            if not os.path.isfile(test['case']):
                print "error, test case not found ", test['case']
                sys.exit(1)
            if not os.access(test['case'], os.X_OK):
                print "error, test case not executable ", test['case']
                sys.exit(1)

            if run_test(cmdline, test):
                test['result'] = "fail";
                err = True
            else:
                test['result'] = "pass";

    if err:
        data['result'] = "fail";
    else:
        data['result'] = "pass";

    return err

def parse_cmdline():
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', metavar='FILE', action='store',
            help='Use config file')
    parser.add_argument('-d', '--debug', action='store_true',
            help='Enable debug mode')
    parser.add_argument('-o', '--option', action='append', default=[],
            help='Option to pass to tests and suites (use multiple -o for multiple options)')
    parser.add_argument('suites', nargs='+', metavar='TEST|SUITE',
            help='Test or suite to run')
    if len(sys.argv) == 1:
        # Normally, argparse does not display the help message if the user
        # didn't explicitly invoke '-h' but we also want it shown if the user
        # didn't specify any arguments at all.
        parser.print_help()
        sys.exit(1)
    return parser.parse_args()

def main():
    global DATABASE
    print(pcolor.yellow + "9PM - Simplicity is the ultimate sophistication"
      + pcolor.reset);

    args = parse_cmdline()

    temp = tempfile.NamedTemporaryFile(suffix='_dict_db', prefix='9pm_',
                                       dir='/tmp')
    if args.debug:
        print "Created databasefile:", temp.name
    DATABASE = temp.name

    cmdl = {'name': 'cmdl', 'suite': []}
    for filename in args.suites:
        fpath = os.path.join(os.getcwd(), filename)
        if filename.endswith('.yaml'):
            cmdl['suite'].append(parse(fpath))
        else:
            cmdl['suite'].append({"case": fpath, "name": gen_name(filename)})

    err = run_suite(args, cmdl, 0)
    if err:
        print pcolor.red + "\n✗ Execution" + pcolor.reset
    else:
        print pcolor.green + "\n✓ Execution" + pcolor.reset
    print_tree(cmdl, "", 0)

    temp.close()
    sys.exit(err)

if __name__ == '__main__':
    main()
