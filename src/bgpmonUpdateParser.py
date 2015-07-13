#!/usr/bin/python

from __future__ import print_function
import sys
import os
import json
import socket
import string
import re
import xml
import argparse
import calendar
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime

from settings import *

verbose = False
warning = False
logging = False

def print_log(*objs):
    if logging or verbose:
        print("[LOGS] ", *objs, file=sys.stderr)

def print_info(*objs):
    if verbose:
        print("[INFO] ", *objs, file=sys.stderr)

def print_warn(*objs):
    if warning or verbose:
        print("[WARN] ", *objs, file=sys.stderr)

def print_error(*objs):
    print("[ERROR] ", *objs, file=sys.stderr)

def parse2JSON(xml, filter):
    try:
        tree = ET.fromstring(xml)
    except:
        print_error("Cannot parse XML: %s!" % xml)
        return None
    print_info("root: %s" % tree.tag)
    for child in tree:
        print_info(child.tag)
    src = tree.find('{urn:ietf:params:xml:ns:bgp_monitor}SOURCE')
    # check if source exists, otherwise return
    if src is None:
        print_warn("Invalid XML: %s." % xml)
        return None
    # find source
    src_addr = src.find('{urn:ietf:params:xml:ns:bgp_monitor}ADDRESS').text
    src_asn = src.find('{urn:ietf:params:xml:ns:bgp_monitor}ASN2').text
    # init return struct
    bgp_message = dict()
    bgp_message['type'] = 'announcement'
    bgp_message['asn'] = str(src_asn)
    bgp_message['prefixes'] = list()
    bgp_message['path'] = list()

    # check wether it is a keep alive message
    keep_alive = tree.find('{urn:ietf:params:xml:ns:xfb}KEEP_ALIVE')
    if keep_alive is not None:
        print_log("BGP KEEP ALIVE %s (AS %s)" % (src_addr, src_asn))
        return None
    # proceed with bgp update parsing
    update = tree.find('{urn:ietf:params:xml:ns:xfb}UPDATE')
    if update is None:
        return None

    # check if its a bgp withdraw message
    withdraws = update.findall('.//{urn:ietf:params:xml:ns:xfb}WITHDRAW')
    for withdraw in withdraws:
        bgp_message['type'] = 'withdraw'
        prefix = withdraw.text
        print_log ("BGP WITHDRAW %s by AS %s" % (prefix, src_asn))
        bgp_message['prefixes'].append(str(prefix))

    if bgp_message['type'] == 'withdraw':
        #bgp_message['path'].append(str(src_asn))
        json_str = json.dumps(bgp_message)
        return json_str

    asp = update.find('{urn:ietf:params:xml:ns:xfb}AS_PATH')
    if asp is not None:
        for asn in asp.findall('.//{urn:ietf:params:xml:ns:xfb}ASN2'):
                bgp_message['path'].append(str(asn.text))
    if filter and (len(bgp_message['path']) > 0):
        origin = bgp_message['path'][-1]
        if origin not in filter:
            return None

    #next_hop = update.find('{urn:ietf:params:xml:ns:xfb}NEXT_HOP').text
    prefixes = update.findall('.//{urn:ietf:params:xml:ns:xfb}NLRI')
    for prefix in prefixes:
        bgp_message['prefixes'].append(str(prefix.text))
    json_str = json.dumps(bgp_message)
    return json_str

def parse2XML(xml):
    try:
        tree = minidom.parseString(xml)
    except:
        print_error("Cannot parse XML: %s", xml)
        return None
    return tree.toprettyxml()

def read_filter(fin):
    print_log ("CALL read_filter (%s)." % fin)
    if not os.path.isfile(fin):
        print_warn("not a file")
        return None
    lines = [line.strip() for line in open(fin)]
    filter = set()
    for l in lines:
        asn = l.split(',')
        try:
            t = int(asn)
        except:
            pass
        else:
            filter.add(asn)
    if len(filter) > 0:
        return filter
    # found nothing, so return None
    return None

def main():
    parser = argparse.ArgumentParser(description='', epilog='')
    parser.add_argument('-l', '--logging',
                        help='Ouptut log info.', action='store_true')
    parser.add_argument('-w', '--warning',
                        help='Output warnings.', action='store_true')
    parser.add_argument('-v', '--verbose',
                        help='Verbose output.', action='store_true')
    parser.add_argument('-a', '--addr',
                        help='Address or name of BGPmon host.',
                        default=default_bgpmon_server['host'])
    parser.add_argument('-p', '--port',
                        help='Port of BGPmon Update XML stream.',
                        default=default_bgpmon_server['port'], type=int)
    parser.add_argument('-x', '--xml',
                        help='Set output format to XML, default JSON.',
                        action='store_true')
    fgroup = parser.add_mutually_exclusive_group(required=False)
    fgroup.add_argument('-f', '--filter',
                        help="ASN filter, as comma separated list.",
                        type=str, default=None)
    fgroup.add_argument('-r', '--readfilter',
                        help="ASN filter, read from csv file.",
                        type=str, default=None)
    args = vars(parser.parse_args())

    global verbose
    verbose   = args['verbose']
    global warning
    warning   = args['warning']
    global logging
    logging = args['logging']

    # BEGIN
    print_log(datetime.now().strftime('%Y-%m-%d %H:%M:%S') + " starting ...")

    port = args['port']
    addr = args['addr'].strip()
    format_xml = args['xml']
    filter = None
    if args['filter']:
        filter = args['filter'].split(',')
    if args['readfilter']:
        filter = read_filter(args['readfilter'])

    print_log(datetime.now().strftime('%Y-%m-%d %H:%M:%S') +
              " connecting to BGPmon Update XML stream (%s:%d)" % (addr,port))

    sock =  socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((addr,port))
    except:
        print_error("Failed to connect to BGPmon!")
        sys.exit(1)

    data = ""
    stream = ""
    while(True):
        data = sock.recv(1024)
        stream += data
        stream = string.replace(stream, "<xml>", "")
        while (re.search('</BGP_MONITOR_MESSAGE>', stream)):
            messages = stream.split('</BGP_MONITOR_MESSAGE>')
            msg = messages[0] + '</BGP_MONITOR_MESSAGE>'
            stream = '</BGP_MONITOR_MESSAGE>'.join(messages[1:])
            if format_xml:
                output = parse2XML(msg)
            else:
                output = parse2JSON(msg, filter)
            if output:
                print(output.strip(), file=sys.stdout)
                sys.stdout.flush()

    print_log(datetime.now().strftime('%Y-%m-%d %H:%M:%S') +  " done ...")
    # END

if __name__ == "__main__":
    main()